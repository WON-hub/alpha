from __future__ import annotations

import re
from typing import Any

import httpx

from app.config import get_settings


class PlaceSearchConfigurationError(RuntimeError):
    pass


class PlaceSearchError(RuntimeError):
    pass


def _match_text(value: str) -> str:
    return re.sub(r"[^0-9a-z가-힣]", "", str(value or "").casefold())


def _google_category(place: dict[str, Any]) -> str:
    display_name = place.get("primaryTypeDisplayName") or {}
    return str(display_name.get("text") or place.get("primaryType") or "기타")


async def _search_google(query: str, api_key: str) -> list[dict[str, Any]]:
    endpoint = "https://places.googleapis.com/v1/places:searchText"
    headers = {
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": ",".join(
            [
                "places.id",
                "places.displayName",
                "places.formattedAddress",
                "places.location",
                "places.nationalPhoneNumber",
                "places.primaryType",
                "places.primaryTypeDisplayName",
            ]
        ),
    }
    body = {"textQuery": query, "languageCode": "ko", "regionCode": "KR", "maxResultCount": 5}
    async with httpx.AsyncClient(timeout=8) as client:
        response = await client.post(endpoint, headers=headers, json=body)
    if response.status_code >= 400:
        raise PlaceSearchError(f"Google Places API 요청이 실패했습니다. ({response.status_code})")
    places = response.json().get("places") or []
    results: list[dict[str, Any]] = []
    for place in places:
        location = place.get("location") or {}
        display_name = place.get("displayName") or {}
        results.append(
            {
                "place_id": str(place.get("id") or ""),
                "place_provider": "google",
                "name": str(display_name.get("text") or query),
                "category": _google_category(place),
                "address": str(place.get("formattedAddress") or ""),
                "latitude": location.get("latitude"),
                "longitude": location.get("longitude"),
                "phone": str(place.get("nationalPhoneNumber") or ""),
                "opening_hours": "",
                "image_url": "",
            }
        )
    return [item for item in results if item["latitude"] is not None and item["longitude"] is not None]


async def _search_kakao(query: str, api_key: str) -> list[dict[str, Any]]:
    endpoint = "https://dapi.kakao.com/v2/local/search/keyword.json"
    headers = {"Authorization": f"KakaoAK {api_key}"}
    params = {"query": query, "size": 5, "page": 1}
    async with httpx.AsyncClient(timeout=8) as client:
        response = await client.get(endpoint, headers=headers, params=params)
    if response.status_code >= 400:
        if response.status_code == 401:
            raise PlaceSearchError("카카오 장소 검색 인증에 실패했습니다. KAKAO_REST_API_KEY에는 카카오디벨로퍼스의 REST API 키를 입력해 주세요.")
        if response.status_code == 403:
            raise PlaceSearchError("카카오 Local API가 비활성화되어 있습니다. 카카오 디벨로퍼스에서 이 앱의 OPEN_MAP_AND_LOCAL 서비스를 활성화해 주세요.")
        raise PlaceSearchError(f"Kakao Local API 요청이 실패했습니다. ({response.status_code})")
    documents = response.json().get("documents") or []
    results: list[dict[str, Any]] = []
    for place in documents:
        address = str(place.get("road_address_name") or place.get("address_name") or "")
        results.append(
            {
                "place_id": str(place.get("id") or ""),
                "place_provider": "kakao",
                "name": str(place.get("place_name") or query),
                "category": str(place.get("category_name") or "기타"),
                "address": address,
                "latitude": float(place.get("y") or 0),
                "longitude": float(place.get("x") or 0),
                "phone": str(place.get("phone") or ""),
                "opening_hours": "",
                "image_url": "",
            }
        )
    return [item for item in results if item["latitude"] and item["longitude"]]


async def search_places(query: str) -> list[dict[str, Any]]:
    settings = get_settings()
    normalized_query = query.strip()
    if not normalized_query:
        return []
    provider = settings.place_search_provider.strip().lower()
    if provider == "google":
        if not settings.google_places_api_key:
            raise PlaceSearchConfigurationError("GOOGLE_PLACES_API_KEY가 설정되지 않았습니다.")
        return await _search_google(normalized_query, settings.google_places_api_key)
    if provider == "kakao":
        if not settings.kakao_rest_api_key:
            raise PlaceSearchConfigurationError("KAKAO_REST_API_KEY가 설정되지 않았습니다.")
        return await _search_kakao(normalized_query, settings.kakao_rest_api_key)
    raise PlaceSearchConfigurationError("PLACE_SEARCH_PROVIDER는 google 또는 kakao여야 합니다.")


async def resolve_place(name: str, address: str = "") -> dict[str, Any] | None:
    """Resolve one store to a provider result for admin-side coordinate autofill."""
    store_name = str(name or "").strip()
    store_address = str(address or "").strip()
    query = " ".join(part for part in (store_name, store_address) if part).strip()
    results = await search_places(query)
    if not results:
        return None

    wanted_name = _match_text(store_name)
    wanted_address = _match_text(store_address)

    def rank(item: dict[str, Any]) -> tuple[int, int, int]:
        candidate_name = _match_text(item.get("name", ""))
        candidate_address = _match_text(item.get("address", ""))
        exact_name = int(bool(wanted_name and candidate_name == wanted_name))
        name_contains = int(bool(wanted_name and (wanted_name in candidate_name or candidate_name in wanted_name)))
        address_contains = int(bool(wanted_address and (wanted_address in candidate_address or candidate_address in wanted_address)))
        return exact_name, name_contains, address_contains

    return max(results, key=rank)
