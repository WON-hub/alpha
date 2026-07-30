from __future__ import annotations

import json
import re
from typing import Any

import httpx

from app.config import get_settings


class AIConfigurationError(RuntimeError):
    pass


class AIServiceError(RuntimeError):
    pass


def _extract_text(payload: dict[str, Any]) -> str:
    candidates = payload.get("candidates") or []
    if not candidates:
        return ""
    parts = ((candidates[0].get("content") or {}).get("parts") or [])
    return "".join(str(part.get("text") or "") for part in parts).strip()


def _call_gemini(prompt: str, *, use_search: bool = False) -> str:
    settings = get_settings()
    if not settings.gemini_api_key:
        raise AIConfigurationError("GEMINI_API_KEY가 설정되지 않았습니다.")
    body: dict[str, Any] = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 2048},
    }
    if use_search:
        body["tools"] = [{"google_search": {}}]
    models = [settings.gemini_model.strip()]
    fallback_model = settings.gemini_fallback_model.strip()
    if fallback_model and fallback_model not in models:
        models.append(fallback_model)

    last_status: int | None = None
    for index, model in enumerate(models):
        endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        try:
            response = httpx.post(
                endpoint,
                headers={"x-goog-api-key": settings.gemini_api_key, "Content-Type": "application/json"},
                json=body,
                timeout=30,
            )
        except httpx.HTTPError as exc:
            if index < len(models) - 1:
                continue
            raise AIServiceError("AI 서버에 연결하지 못했습니다.") from exc

        last_status = response.status_code
        if response.status_code >= 400:
            # 모델 과부하·일시 장애·지원되지 않는 모델이면 보조 모델로 재시도합니다.
            if response.status_code in {404, 429, 500, 502, 503, 504} and index < len(models) - 1:
                continue
            raise AIServiceError(f"AI 요청이 실패했습니다. ({response.status_code})")
        text = _extract_text(response.json())
        if not text:
            raise AIServiceError("AI 응답이 비어 있습니다.")
        return text

    raise AIServiceError(f"AI 요청이 실패했습니다. ({last_status or 503})")


def _json_from_text(text: str) -> Any:
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        match = re.search(r"(\[.*\]|\{.*\})", cleaned, flags=re.DOTALL)
        if not match:
            raise AIServiceError("AI 응답을 JSON으로 읽지 못했습니다.") from exc
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError as nested_exc:
            raise AIServiceError("AI 응답 형식이 올바르지 않습니다.") from nested_exc


def fallback_store_summary(category: str, menu_summary: str, name: str = "") -> str:
    category = str(category or "기타").strip()
    menu_summary = str(menu_summary or "").strip()
    if menu_summary:
        return f"{category} 중심의 매장으로, {menu_summary} 메뉴를 판매합니다."
    if name:
        return f"{category} 매장입니다. {name}의 대표 메뉴와 영업 정보는 매장에 확인해 주세요."
    return f"{category} 중심의 광운대학교 인근 제휴 매장입니다."


def generate_store_summary(name: str, category: str, menu_summary: str, address: str) -> str:
    """Generate one factual store description during admin registration only."""
    prompt = f"""
You are writing a factual one-line Korean description for a campus restaurant directory.
Use Google Search grounding to verify the business matching the name and address.
Mention what kind of business it is, representative menu/products, or what it is known for.
Do not mention partnership benefits, discounts, student conditions, or estimated savings.
Do not invent facts. If public information cannot be verified, say that store information
is being checked. Return one Korean sentence of at most 80 Korean characters.

Name: {name}
Category: {category}
Existing menu/description: {menu_summary}
Address: {address}
""".strip()
    return _call_gemini(prompt, use_search=True).replace("\n", " ").strip().strip('"')[:240]


def generate_recommendation_reason(
    name: str,
    category: str,
    address: str,
    benefit_text: str,
    distance_m: float,
    satisfaction_score: float,
    user_affiliations: list[str],
) -> str:
    prompt = f"""
Write a concise Korean AI recommendation reason in 1-2 sentences, at most 80 characters.
Use only the supplied facts. Explain why this randomly selected store fits the user's
current affiliation, benefit, distance, and satisfaction. Do not claim that AI selected it
and do not invent facts.

Store: {name}
Category: {category}
Address: {address}
Benefit: {benefit_text}
Distance: {round(distance_m)}m
Satisfaction score: {round(satisfaction_score)} / 100
User affiliations: {', '.join(user_affiliations) or '전체'}
""".strip()
    return _call_gemini(prompt).replace("\n", " ").strip().strip('"')[:240]


def analyze_benefit(benefit_text: str) -> dict[str, Any]:
    """Extract a reviewable, JSON-only benefit analysis from the original text."""
    prompt = f"""
Analyze this Korean partnership benefit sentence and return ONLY one JSON object.
Do not invent missing values. Use null for unknown numbers/text, [] for no conditions,
and use a 0-100 benefitScore. The output keys must be exactly:
benefitType, discountRate, discountAmount, freeItem, targetMenu, minimumOrder,
availableTime, requiredPeople, studentVerification, conditions, conditionCount,
benefitScore, unknownBenefits, unknownConditions, needsReview.
discountRate is a percentage number such as 10 for 10%. discountAmount and minimumOrder
are Korean won integers. studentVerification is true only when student ID or equivalent
verification is explicitly required. conditions must contain the exact conditions found.
unknownBenefits must contain exact benefit phrases that cannot be represented by the
discountRate, discountAmount, freeItem, targetMenu, or benefitType fields.
unknownConditions must contain exact conditions that cannot be represented by
minimumOrder, availableTime, requiredPeople, studentVerification, or the conditions list.
If either unknown list is non-empty, set needsReview to true. Also set needsReview to true
when the sentence is ambiguous or the benefit amount cannot be safely interpreted.
Never hide an unknown phrase just to produce a score.

Original benefit text:
{benefit_text}
""".strip()
    result = _json_from_text(_call_gemini(prompt))
    if not isinstance(result, dict):
        raise AIServiceError("AI가 혜택 분석 결과를 반환하지 않았습니다.")
    result.setdefault("unknownBenefits", [])
    result.setdefault("unknownConditions", [])
    result["needsReview"] = bool(result.get("needsReview") or result["unknownBenefits"] or result["unknownConditions"])
    return result
