import os
import aiohttp
import asyncio
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY")
RAPIDAPI_HOST = "skyscanner-flights-travel-api.p.rapidapi.com"
BASE_URL = f"https://{RAPIDAPI_HOST}"

RETRYABLE_STATUS_CODES = {502, 503, 504}
MAX_RETRIES = 3
RETRY_DELAYS = [2, 5, 8]


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

    last_error = None

    for attempt in range(MAX_RETRIES):
        try:
            async with session.get(
                url,
                headers=headers,
                params=params,
                timeout=aiohttp.ClientTimeout(total=35)
            ) as resp:
                text = await resp.text()

                if resp.status == 200:
                    try:
                        return await resp.json()
                    except Exception:
                        raise Exception(f"Geçersiz JSON yanıtı: {text}")

                if resp.status in RETRYABLE_STATUS_CODES:
                    last_error = Exception(f"API Hatası {resp.status}: {text}")
                    if attempt < MAX_RETRIES - 1:
                        delay = RETRY_DELAYS[attempt]
                        logger.warning(
                            "Retryable API error on %s attempt %s/%s. Waiting %ss. Response: %s",
                            path, attempt + 1, MAX_RETRIES, delay, text[:500]
                        )
                        await asyncio.sleep(delay)
                        continue
                    raise last_error

                raise Exception(f"API Hatası {resp.status}: {text}")

        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            last_error = e
            if attempt < MAX_RETRIES - 1:
                delay = RETRY_DELAYS[attempt]
                logger.warning(
                    "Network error on %s attempt %s/%s. Waiting %ss. Error: %s",
                    path, attempt + 1, MAX_RETRIES, delay, str(e)
                )
                await asyncio.sleep(delay)
                continue
            raise Exception(f"Ağ hatası: {str(e)}")

    if last_error:
        raise last_error

    raise Exception("Bilinmeyen API hatası")


def _extract_candidates(data):
    if isinstance(data, dict):
        for key in ["data", "results", "airports", "places"]:
            if isinstance(data.get(key), list):
                return data[key]
    elif isinstance(data, list):
        return data
    return []


def _candidate_sky_id(item):
    return (
        item.get("skyId")
        or item.get("navigation", {}).get("relevantFlightParams", {}).get("skyId")
        or item.get("presentation", {}).get("skyId")
        or ""
    )


def _candidate_entity_id(item):
    return (
        item.get("entityId")
        or item.get("navigation", {}).get("relevantFlightParams", {}).get("entityId")
        or item.get("presentation", {}).get("entityId")
        or ""
    )


def _candidate_name(item):
    return (
        item.get("presentation", {}).get("title")
        or item.get("name")
        or item.get("title")
        or ""
    )


def _score_candidate(item, query_upper):
    sky_id = str(_candidate_sky_id(item)).upper()
    name = str(_candidate_name(item)).upper()

    score = 0

    if sky_id == query_upper:
        score += 100
    if sky_id.startswith(query_upper):
        score += 50
    if query_upper == name:
        score += 40
    if query_upper in name:
        score += 20
    if "AIRPORT" in name:
        score += 5

    return score


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

    candidates = _extract_candidates(data)

    if not candidates:
        raise Exception(f"Havalimanı bulunamadı: {query}")

    query_upper = query.strip().upper()
    best = sorted(candidates, key=lambda item: _score_candidate(item, query_upper), reverse=True)[0]

    sky_id = _candidate_sky_id(best)
    entity_id = _candidate_entity_id(best)
    name = _candidate_name(best) or query

    if not sky_id or not entity_id:
        raise Exception(f"{query} için skyId/entityId alınamadı. API yanıtını kontrol et.")

    logger.info(
        "Airport match for %s -> name=%s skyId=%s entityId=%s",
        query, name, sky_id, entity_id
    )

    return {
        "name": name,
        "skyId": str(sky_id),
        "entityId": str(entity_id),
    }


def _filter_itineraries_by_stops(itineraries, stop_preference):
    if stop_preference == "any":
        return itineraries

    filtered = []
    for item in itineraries:
        legs = item.get("legs", [])
        if not isinstance(legs, list) or not legs:
            continue

        leg_stop_counts = []
        for leg in legs:
            stop_count = leg.get("stopCount")
            if isinstance(stop_count, int):
                leg_stop_counts.append(stop_count)

        if not leg_stop_counts:
            continue

        if stop_preference == "nonstop":
            if all(sc == 0 for sc in leg_stop_counts):
                filtered.append(item)

        elif stop_preference == "with_stops":
            if any(sc > 0 for sc in leg_stop_counts):
                filtered.append(item)

    return filtered


async def search_flights(origin: str, destination: str, depart_date: str,
                         return_date: str = None, passengers: int = 1,
                         stop_preference: str = "any"):
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

        data = await _request_json(session, "/flights/searchFlights", params)

        itineraries = data.get("itineraries", [])
        if isinstance(itineraries, list):
            filtered = _filter_itineraries_by_stops(itineraries, stop_preference)
            data["itineraries"] = filtered

        logger.info("Flight search status: %s", data.get("status"))
        logger.info("Flight search total before filter: %s", data.get("total"))
        logger.info("Flight search total after filter: %s", len(data.get("itineraries", [])))

        return {
            "raw": data,
            "origin": origin_info,
            "destination": destination_info,
            "depart_date": depart_date_api,
            "return_date": return_date_api,
            "passengers": passengers,
            "stop_preference": stop_preference,
        }


def _extract_itineraries(raw: dict):
    if not isinstance(raw, dict):
        return []
    itineraries = raw.get("itineraries")
    return itineraries if isinstance(itineraries, list) else []


def _format_price(price_obj):
    if isinstance(price_obj, dict):
        formatted = price_obj.get("formatted")
        if formatted:
            if formatted.startswith("TRY "):
                number = formatted.replace("TRY ", "").strip()
                try:
                    amount = float(number)
                    return f"{amount:,.0f}".replace(",", ".") + " TL"
                except ValueError:
                    return formatted
            return formatted

        amount = price_obj.get("amount")
        currency = price_obj.get("currency", "")
        if amount is not None:
            try:
                numeric = float(amount)
                if currency == "TRY":
                    return f"{numeric:,.0f}".replace(",", ".") + " TL"
                return f"{currency} {numeric:,.2f}"
            except ValueError:
                return f"{currency} {amount}"

    return "Fiyat yok"


def _format_dt(dt_str):
    if not dt_str:
        return "-"
    try:
        dt = datetime.strptime(dt_str, "%Y-%m-%dT%H:%M:%S")
        return dt.strftime("%d.%m %H:%M")
    except ValueError:
        return dt_str


def _format_duration(minutes):
    if not isinstance(minutes, int):
        return ""
    hours = minutes // 60
    mins = minutes % 60

    if hours and mins:
        return f"{hours}s {mins}dk"
    if hours:
        return f"{hours}s"
    return f"{mins}dk"


def _extract_carrier(leg):
    carriers = leg.get("carriers")
    if isinstance(carriers, list) and carriers:
        first = carriers[0]
        if isinstance(first, dict):
            name = first.get("name")
            if name:
                return name
    return "Havayolu bilgisi yok"


def _format_leg(prefix, leg):
    if not isinstance(leg, dict):
        return []

    carrier = _extract_carrier(leg)
    dep = _format_dt(leg.get("departure"))
    arr = _format_dt(leg.get("arrival"))
    duration = _format_duration(leg.get("durationMinutes"))
    stop_count = leg.get("stopCount")

    if stop_count == 0:
        stop_text = "Aktarmasız"
    elif isinstance(stop_count, int):
        stop_text = f"{stop_count} aktarma"
    else:
        stop_text = "Aktarma bilgisi yok"

    return [
        f"   {prefix} {carrier}",
        f"   {dep} → {arr} | {duration} | {stop_text}"
    ]


def format_price_message(results: dict, cfg: dict) -> str:
    raw = results.get("raw", {})
    itineraries = _extract_itineraries(raw)

    route = f"{cfg['origin']} → {cfg['destination']}"
    trip_type = "🔄 Gidiş-Dönüş" if cfg.get("return_date") else "➡️ Tek Yön"
    dates = cfg["depart_date"]
    if cfg.get("return_date"):
        dates += f" / {cfg['return_date']}"

    pref_map = {
        "any": "Fark etmez",
        "nonstop": "Aktarmasız",
        "with_stops": "Aktarmalı",
    }
    pref_label = pref_map.get(cfg.get("stop_preference", "any"), "Fark etmez")

    header = (
        f"✈️ {route}\n"
        f"{trip_type} | 📅 {dates} | 👥 {cfg['passengers']} yolcu\n"
        f"🧭 Tercih: {pref_label}\n"
        f"🕐 Kontrol: {datetime.now().strftime('%d.%m.%Y %H:%M')}\n"
        f"{'─' * 24}\n"
    )

    if not itineraries:
        status = raw.get("status", "")
        total = raw.get("total")
        extra = f"\nDurum: {status}" if status else ""
        if total is not None:
            extra += f"\nToplam sonuç: {total}"
        return header + "\n❌ Tercihinize uygun uçuş sonucu bulunamadı." + extra

    lines = [header]

    for idx, item in enumerate(itineraries[:5], start=1):
        price = _format_price(item.get("price"))
        lines.append(f"{idx}. 💸 {price}")

        legs = item.get("legs", [])
        if isinstance(legs, list) and len(legs) > 0:
            lines.extend(_format_leg("🛫", legs[0]))
        if isinstance(legs, list) and len(legs) > 1:
            lines.extend(_format_leg("🛬", legs[1]))

        booking_url = item.get("bookingUrl")
        if booking_url:
            lines.append(f"   🔗 Bilet linki: {booking_url}")

        lines.append("")

    return "\n".join(lines).strip()
