import os
import aiohttp
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY", "")
RAPIDAPI_HOST = "skyscanner50.p.rapidapi.com"

HEADERS = {
    "X-RapidAPI-Key": RAPIDAPI_KEY,
    "X-RapidAPI-Host": RAPIDAPI_HOST
}


def parse_date(date_str: str) -> str:
    """GG.AA.YYYY → YYYY-MM-DD"""
    dt = datetime.strptime(date_str, "%d.%m.%Y")
    return dt.strftime("%Y-%m-%d")


async def search_flights(
    origin: str,
    destination: str,
    depart_date: str,
    return_date: str | None,
    passengers: int
) -> dict:
    """
    Skyscanner RapidAPI üzerinden uçuş arama.
    Endpoint: /api/v1/searchFlights
    """
    url = f"https://{RAPIDAPI_HOST}/api/v1/searchFlights"

    params = {
        "originSkyId": origin,
        "destinationSkyId": destination,
        "originEntityId": origin,
        "destinationEntityId": destination,
        "date": parse_date(depart_date),
        "adults": str(passengers),
        "currency": "TRY",
        "market": "TR",
        "locale": "tr-TR",
        "cabinClass": "economy",
        "sortBy": "best",
        "limit": "5"
    }

    if return_date:
        params["returnDate"] = parse_date(return_date)

    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=HEADERS, params=params, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise Exception(f"API Hatası {resp.status}: {text[:200]}")
            data = await resp.json()

    return parse_skyscanner_response(data, passengers)


def parse_skyscanner_response(data: dict, passengers: int) -> dict:
    """API yanıtını işle ve fiyat listesi çıkar."""
    results = []

    try:
        itineraries = data.get("data", {}).get("itineraries", [])

        for item in itineraries[:5]:
            price_raw = item.get("price", {}).get("raw", 0)
            price_formatted = item.get("price", {}).get("formatted", "N/A")

            legs = item.get("legs", [])
            segments_info = []

            for leg in legs:
                carriers = leg.get("carriers", {}).get("marketing", [])
                airline = carriers[0].get("name", "Bilinmiyor") if carriers else "Bilinmiyor"
                departure = leg.get("departure", "")
                arrival = leg.get("arrival", "")
                duration = leg.get("durationInMinutes", 0)
                stops = leg.get("stopCount", 0)

                segments_info.append({
                    "airline": airline,
                    "departure": departure,
                    "arrival": arrival,
                    "duration_min": duration,
                    "stops": stops
                })

            results.append({
                "price_raw": price_raw,
                "price_formatted": price_formatted,
                "price_per_person": price_raw / passengers if passengers > 0 else price_raw,
                "legs": segments_info,
                "score": item.get("score", 0)
            })

        # Fiyata göre sırala
        results.sort(key=lambda x: x["price_raw"])

    except Exception as e:
        logger.error(f"Response parse error: {e}")
        logger.debug(f"Raw data: {data}")

    return {
        "flights": results,
        "checked_at": datetime.now().strftime("%d.%m.%Y %H:%M"),
        "total_found": len(results)
    }


def format_duration(minutes: int) -> str:
    h = minutes // 60
    m = minutes % 60
    return f"{h}s {m}dk" if h > 0 else f"{m}dk"


def format_datetime(dt_str: str) -> str:
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        return dt.strftime("%d.%m %H:%M")
    except:
        return dt_str[:16] if dt_str else "?"


def format_price_message(results: dict, cfg: dict) -> str:
    origin = cfg["origin"]
    destination = cfg["destination"]
    depart = cfg["depart_date"]
    ret = cfg.get("return_date")
    pax = cfg["passengers"]
    checked_at = results["checked_at"]
    flights = results["flights"]

    trip_type = "🔄 Gidiş-Dönüş" if ret else "➡️ Tek Yön"
    ret_str = f" / {ret}" if ret else ""

    header = (
        f"✈️ *{origin} → {destination}*\n"
        f"{trip_type} | 📅 {depart}{ret_str} | 👥 {pax} yolcu\n"
        f"🕐 Kontrol: {checked_at}\n"
        f"{'─' * 30}\n"
    )

    if not flights:
        return header + "\n⚠️ Fiyat bulunamadı. Tarih veya havalimanı kodunu kontrol edin."

    body = ""
    for i, f in enumerate(flights[:5], 1):
        medal = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"][i - 1]
        legs = f["legs"]

        body += f"\n{medal} *{f['price_formatted']}*"
        if pax > 1:
            per_person = f['price_raw'] / pax
            body += f"  _(kişi başı ~{per_person:,.0f} ₺)_"
        body += "\n"

        for j, leg in enumerate(legs):
            direction = "🛫 Gidiş" if j == 0 else "🛬 Dönüş"
            stops_str = "Aktarmasız" if leg["stops"] == 0 else f"{leg['stops']} aktarma"
            body += (
                f"   {direction}: {leg['airline']}\n"
                f"   {format_datetime(leg['departure'])} → {format_datetime(leg['arrival'])}"
                f" ({format_duration(leg['duration_min'])}, {stops_str})\n"
            )

    footer = f"\n💡 En ucuz: *{flights[0]['price_formatted']}*"
    if len(flights) > 1:
        diff = flights[-1]['price_raw'] - flights[0]['price_raw']
        footer += f" | Fark: {diff:,.0f} ₺"

    return header + body + footer
