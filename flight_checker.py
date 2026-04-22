import os
import aiohttp
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY")
RAPIDAPI_HOST = "skyscanner-flights-travel-api.p.rapidapi.com"
BASE_URL = f"https://{RAPIDAPI_HOST}"


def _to_api_date(date_str: str) -> str:
    """
    Bot tarafında gelen GG.AA.YYYY formatını YYYY-MM-DD formatına çevirir.
    Eğer zaten YYYY-MM-DD geldiyse olduğu gibi döner.
    """
    try:
        return datetime.strptime(date_str, "%d.%m.%Y").strftime("%Y-%m-%d")
    except ValueError:
        return date_str


async def _request_json(session: aiohttp.ClientSession, path: str, params: dict):
    url = f"{BASE_URL}{path}"
    headers = {
        "x-rapidapi-key": RAPIDAPI_KEY,
        "x-rapidapi-host": RAPIDAPI_HOST,
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
    """
    Havalimanı / şehir arar.
    Örn: IST, SAW, Sarajevo, London
    En uygun sonucu döndürür.
    """
    data = await _request_json(
        session,
        "/api/v1/flights/searchAirport",
        {"query": query}
    )

    # API yapısı değişebilir diye birkaç olası alanı deniyoruz
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
        raise Exception(f"{query} için gerekli airport kimlikleri alınamadı.")

    return {
        "name": name,
        "skyId": str(sky_id),
        "entityId": str(entity_id),
    }


async def search_flights(origin: str, destination: str, depart_date: str,
                         return_date: str = None, passengers: int = 1):
    """
    Uçuş araması yapar.
    origin / destination: IST, SAW, LHR, SJJ gibi kod veya şehir adı
    depart_date / return_date: GG.AA.YYYY veya YYYY-MM-DD
    """
    if not RAPIDAPI_KEY:
        raise Exception("RAPIDAPI_KEY environment variable eksik.")

    depart_date_api = _to_api_date(depart_date)
    return_date_api = _to_api_date(return_date) if return_date else None

    async with aiohttp.ClientSession() as session:
        origin_info = await search_airport(session, origin)
        destination_info = await search_airport(session, destination)

        params = {
            "originSkyId": origin_info["skyId"],
            "destinationSkyId": destination_info["skyId"],
            "originEntityId": origin_info["entityId"],
            "destinationEntityId": destination_info["entityId"],
            "date": depart_date_api,
            "adults": str(passengers),
            "cabinClass": "economy",
            "currency": "TRY",
            "market": "TR",
        }

        if return_date_api:
            params["returnDate"] = return_date_api

        data = await _request_json(
            session,
            "/api/v1/flights/searchFlights",
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
    """
    API cevabından itinerary listesini çıkarmaya çalışır.
    Farklı response yapıları için esnek tutuldu.
    """
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
            or price.get("amount")
            or "Fiyat yok"
        )
    if isinstance(price, list) and price:
        first = price[0]
        if isinstance(first, dict):
            return (
                first.get("formattedPrice")
                or first.get("price", {}).get("formatted")
                or first.get("amount")
                or "Fiyat yok"
            )
    if isinstance(price, str):
        return price
    return "Fiyat yok"


def format_price_message(results: dict, cfg
