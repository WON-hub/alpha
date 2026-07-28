from typing import Any

import httpx

from app.config import get_settings


async def geocode_address(address: str) -> dict[str, Any] | None:
    settings = get_settings()
    if not settings.google_geocoding_api_key or not address.strip():
        return None
    params = {"address": address, "key": settings.google_geocoding_api_key, "language": "ko"}
    async with httpx.AsyncClient(timeout=8) as client:
        response = await client.get("https://maps.googleapis.com/maps/api/geocode/json", params=params)
        response.raise_for_status()
        data = response.json()
    result = (data.get("results") or [None])[0]
    if not result:
        return None
    location = result["geometry"]["location"]
    return {"formatted_address": result.get("formatted_address", address), "lat": location["lat"], "lng": location["lng"]}

