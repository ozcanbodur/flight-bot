import os
import aiohttp
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY")
RAPIDAPI_HOST = "skyscanner-flights-travel-api.p.rapidapi.com"
BASE_URL = f"https://{RAPIDAPI_HOST}"


def _to_api_date(date_str: str) -> str:
    try:
        return datetime.strptime(date_str, "%d.%m.%Y").strftime("%Y-%m-%d")
    except ValueError:
        return date_str


async def _request_json(session: aiohttp.ClientSession, path: str, params: dict):
    url = f"{BASE_URL}{path}"
    headers = {
        "x-rapidapi-key": RAPIDAPI_KEY,
        "x-rapidapi-host": RAPIDAPI_HOST,
        "Content-Type": "application/json",
    }

    async with session.get(url, headers=headers, params=params) as resp:
        text = await resp.text()

        if resp.status != 200:
            raise Exception(f"API Hatası {resp.status}: {text}")

        try:
            return await resp.json()
        except Exception:
            raise Exception(f"Geçersiz JSON yanıtı: {text}")


async def search_airport(session: aiohttp.ClientSession, query: str):
    data = await _request_json(
        session,
        "/flights/searchAirport",
        {
            "market": "TR",
            "locale": "tr-TR",
            "query": query,
        },
    )

    candidates = []

    if isinstance(data, dict):
        for key in ["data", "results", "airports", "places"]:
            if isinstance(data.get(key), list):
                candidates = data[key]
                break
    elif isinstance(data, list):
        candidates = data

    if not candidates:
        raise Exception(f"Havalimanı bulunamadı: {query}")

    best = candidates[0]

    sky_id = (
        best.get("skyId")
        or best.get("navigation", {}).get("relevantFlightParams", {}).get("skyId")
        or best.get("presentation", {}).get("skyId")
    )

    entity_id = (
        best.get("entityId")
        or best.get("navigation", {}).get("relevantFlightParams", {}).get("entityId")
        or best.get("presentation", {}).get("entityId")
    )

    name = (
        best.get("presentation", {}).get("title")
        or best.get("name")
        or best.get("title")
        or query
    )

    if not sky_id or not entity_id:
        raise Exception(f"{query} için skyId/entityId alınamadı. API yanıtını kontrol et.")

    return {
        "name": name,
        "skyId": str(sky_id),
        "entityId": str(entity_id),
    }


async def search_flights(origin: str, destination: str, depart_date: str,
                         return_date: str = None, passengers: int = 1):
    if not RAPIDAPI_KEY:
        raise Exception("RAPIDAPI_KEY environment variable eksik.")

    depart_date_api = _to_api_date(depart_date)
    return_date_api = _to_api_date(return_date) if return_date else None

    async with aiohttp.ClientSession() as session:
        origin_info = await search_airport(session, origin)
        destination_info = await search_airport(session, destination)

        params = {
            "countryCode": "TR",
            "market": "TR",
            "currency": "TRY",
            "adults": str(passengers),
            "childrens": "0",
            "infants": "0",
            "cabinClass": "economy",
            "date": depart_date_api,
            "originSkyId": origin_info["skyId"],
            "originEntityId": origin_info["entityId"],
            "destinationSkyId": destination_info["skyId"],
            "destinationEntityId": destination_info["entityId"],
        }

        if return_date_api:
            params["returnDate"] = return_date_api

        data = await _request_json(
            session,
            "/flights/searchFlights",
            params
        )

        return {
            "raw": data,
            "origin": origin_info,
            "destination": destination_info,
            "depart_date": depart_date_api,
            "return_date": return_date_api,
            "passengers": passengers,
        }


def _extract_itineraries(raw: dict):
    if not isinstance(raw, dict):
        return []

    for key in ["data", "itineraries", "results"]:
        value = raw.get(key)
        if isinstance(value, list):
            return value

    data = raw.get("data")
    if isinstance(data, dict):
        for key in ["itineraries", "results"]:
            value = data.get(key)
            if isinstance(value, list):
                return value

    return []


def _extract_price(item: dict):
    price = item.get("price") or item.get("pricingOptions") or item.get("cheapestPrice")

    if isinstance(price, dict):
        return (
            price.get("formatted")
            or price.get("displayAmount")
            or str(price.get("amount"))
            or "Fiyat yok"
        )

    if isinstance(price, list) and price:
        first = price[0]
        if isinstance(first, dict):
            return (
                first.get("formattedPrice")
                or first.get("price", {}).get("formatted")
                or str(first.get("amount"))
                or "Fiyat yok"
            )

    if isinstance(price, str):
        return price

    return "Fiyat yok"


def _format_price(price_value):
    if not price_value:
        return "Fiyat yok"

    text = str(price_value).replace("TRY", "").strip()

    try:
        amount = float(text)
        formatted = f"{amount:,.0f}".replace(",", ".")
        return f"{formatted} TL"
    except ValueError:
        return str(price_value)


def _format_dt(dt_str):
    if not dt_str or dt_str == "-":
        return "-"

    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            dt = datetime.strptime(dt_str, fmt)
            return dt.strftime("%d.%m %H:%M")
        except ValueError:
            pass

    return dt_str


def _extract_carrier(leg):
    if not isinstance(leg, dict):
        return "Havayolu bilgisi yok"

    for key in [
        "carrier",
        "marketingCarrier",
        "operatingCarrier",
        "airline",
        "name",
    ]:
        value = leg.get(key)
        if isinstance(value, str) and value.strip():
            return value

        if isinstance(value, dict):
            for nested_key in ["name", "displayName", "carrierName"]:
                nested_val = value.get(nested_key)
                if isinstance(nested_val, str) and nested_val.strip():
                    return nested_val

    carriers = leg.get("carriers")
    if isinstance(carriers, list) and carriers:
        first = carriers[0]
        if isinstance(first, dict):
            for key in ["name", "displayName", "carrierName"]:
                val = first.get(key)
                if isinstance(val, str) and val.strip():
                    return val

    return "Havayolu bilgisi yok"


def _extract_booking_link(raw, item):
    candidate_paths = [
        item.get("deeplink"),
        item.get("deepLink"),
        item.get("bookingUrl"),
        item.get("url"),
        raw.get("deeplink") if isinstance(raw, dict) else None,
        raw.get("deepLink") if isinstance(raw, dict) else None,
        raw.get("bookingUrl") if isinstance(raw, dict) else None,
        raw.get("url") if isinstance(raw, dict) else None,
    ]

    for link in candidate_paths:
        if isinstance(link, str) and link.startswith("http"):
            return link

    return None


def format_price_message(results: dict, cfg: dict) -> str:
    raw = results.get("raw", {})
    itineraries = _extract_itineraries(raw)

    route = f"{cfg['origin']} → {cfg['destination']}"
    trip_type = "🔄 Gidiş-Dönüş" if cfg.get("return_date") else "➡️ Tek Yön"
    dates = cfg["depart_date"]
    if cfg.get("return_date"):
        dates += f" / {cfg['return_date']}"

    header = (
        f"✈️ *{route}*\n"
        f"{trip_type} | 📅 {dates} | 👥 {cfg['passengers']} yolcu\n"
        f"🕐 Kontrol: {datetime.now().strftime('%d.%m.%Y %H:%M')}\n"
        f"{'─' * 24}\n"
    )

    if not itineraries:
        return header + "\n❌ Uygun uçuş sonucu bulunamadı."

    lines = [header]

    for idx, item in enumerate(itineraries[:5], start=1):
        price_raw = _extract_price(item)
        price = _format_price(price_raw)

        legs = item.get("legs", [])
        outbound = item.get("outbound")
        inbound = item.get("inbound")

        if not outbound and isinstance(legs, list) and len(legs) > 0:
            outbound = legs[0]

        if not inbound and isinstance(legs, list) and len(legs) > 1:
            inbound = legs[1]

        lines.append(f"{idx}. 💸 *{price}*")

        if isinstance(outbound, dict):
            dep = _format_dt(
                outbound.get("departure")
                or outbound.get("departureDateTime")
                or outbound.get("originDeparture")
            )
            arr = _format_dt(
                outbound.get("arrival")
                or outbound.get("arrivalDateTime")
                or outbound.get("destinationArrival")
            )
            carrier = _extract_carrier(outbound)

            lines.append(f"   🛫 {carrier}")
            lines.append(f"   {dep} → {arr}")

        if isinstance(inbound, dict):
            dep = _format_dt(
                inbound.get("departure")
                or inbound.get("departureDateTime")
                or inbound.get("originDeparture")
            )
            arr = _format_dt(
                inbound.get("arrival")
                or inbound.get("arrivalDateTime")
                or inbound.get("destinationArrival")
            )
            carrier = _extract_carrier(inbound)

            lines.append(f"   🛬 {carrier}")
            lines.append(f"   {dep} → {arr}")

        booking_link = _extract_booking_link(raw, item)
        if booking_link:
            lines.append(f"   🔗 {booking_link}")

        lines.append("")

    return "\n".join(lines).strip()
