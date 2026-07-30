from __future__ import annotations

import json
import re
from typing import Any, Iterable

import httpx

from app.config import get_settings
from app.services.scoring_rules import ScoringRule


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


def _rule_prompt_payload(scoring_rules: Iterable[ScoringRule] | None) -> list[dict[str, Any]]:
    return [
        {
            "ruleType": rule.rule_type,
            "ruleKey": rule.rule_key,
            "label": rule.label,
            "keywords": list(rule.keywords),
            "minValue": rule.min_value,
            "maxValue": rule.max_value,
            "score": rule.score,
        }
        for rule in (scoring_rules or [])
    ]


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _number(value: Any, default: float = 0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _rule_map(scoring_rules: Iterable[ScoringRule] | None) -> dict[str, ScoringRule]:
    return {rule.rule_key: rule for rule in (scoring_rules or [])}


def _rule_entry(item: Any, rule_map: dict[str, ScoringRule], rule_types: set[str]) -> tuple[ScoringRule, dict[str, Any]] | None:
    if isinstance(item, str):
        rule_key = item
        evidence = ""
        reason = ""
    elif isinstance(item, dict):
        rule_key = str(item.get("ruleKey") or item.get("rule_key") or "").strip()
        evidence = str(item.get("evidence") or item.get("phrase") or "").strip()
        reason = str(item.get("reason") or "").strip()
    else:
        return None
    rule = rule_map.get(rule_key)
    if not rule or rule.rule_type not in rule_types:
        return None
    entry = {"ruleKey": rule.rule_key, "label": rule.label, "score": rule.score}
    if evidence:
        entry["evidence"] = evidence
    if reason:
        entry["reason"] = reason
    return rule, entry


def _append_rule(entries: list[dict[str, Any]], rule: ScoringRule, evidence: str = "", reason: str = "") -> None:
    if any(item.get("ruleKey") == rule.rule_key for item in entries):
        return
    item: dict[str, Any] = {"ruleKey": rule.rule_key, "label": rule.label, "score": rule.score}
    if evidence:
        item["evidence"] = evidence
    if reason:
        item["reason"] = reason
    entries.append(item)


def _value_rule(scoring_rules: Iterable[ScoringRule] | None, rule_type: str, value: float) -> ScoringRule | None:
    return next(
        (rule for rule in (scoring_rules or []) if rule.rule_type == rule_type and rule.matches_value(value)),
        None,
    )


def normalize_benefit_analysis(
    result: dict[str, Any],
    benefit_text: str,
    scoring_rules: Iterable[ScoringRule] | None = None,
) -> dict[str, Any]:
    """Validate Gemini rule selections and calculate canonical B components.

    Gemini chooses the closest existing rule and supplies the evidence. The server then
    confirms the rule keys and derives numeric values from the active rule table so an
    invented score can never be persisted.
    """
    rules = list(scoring_rules or [])
    rule_map = _rule_map(rules)
    analysis = dict(result)
    unknown_benefits = [str(item) for item in _as_list(analysis.get("unknownBenefits")) if str(item).strip()]
    unknown_conditions = [str(item) for item in _as_list(analysis.get("unknownConditions")) if str(item).strip()]
    invalid_mappings: list[str] = []

    benefit_entries: list[dict[str, Any]] = []
    for item in _as_list(analysis.get("matchedBenefitRules")):
        parsed = _rule_entry(item, rule_map, {"discount_rate", "fixed_discount", "benefit_text"})
        if parsed:
            _append_rule(benefit_entries, parsed[0], parsed[1].get("evidence", ""), parsed[1].get("reason", ""))
        elif item not in (None, "", {}):
            invalid_mappings.append(str(item))

    rate = _number(analysis.get("discountRate", analysis.get("discount_rate")), 0)
    amount = _number(analysis.get("discountAmount", analysis.get("fixed_discount")), 0)
    if rate > 0:
        rule = _value_rule(rules, "discount_rate", rate)
        if rule:
            _append_rule(benefit_entries, rule, f"{rate:g}% 할인")
    if amount > 0:
        rule = _value_rule(rules, "fixed_discount", amount)
        if rule:
            _append_rule(benefit_entries, rule, f"{amount:,.0f}원 할인")

    benefit_text_for_matching = " ".join(
        str(value or "")
        for value in (benefit_text, analysis.get("benefitType"), analysis.get("freeItem"), analysis.get("targetMenu"))
    )
    has_numeric_rule = any(
        rule_map.get(item["ruleKey"]) and rule_map[item["ruleKey"]].rule_type in {"discount_rate", "fixed_discount"}
        for item in benefit_entries
    )
    if not has_numeric_rule:
        for rule in rules:
            if rule.rule_type == "benefit_text" and rule.matches_text(benefit_text_for_matching):
                _append_rule(benefit_entries, rule, benefit_text.strip())
                break
    if not benefit_entries:
        fallback = next((rule for rule in rules if rule.rule_type == "benefit_text" and not rule.keywords), None)
        if fallback and (analysis.get("freeItem") or analysis.get("benefitType") or benefit_text.strip()):
            _append_rule(benefit_entries, fallback, benefit_text.strip())
        else:
            unknown_benefits.append(benefit_text.strip() or "혜택 내용 없음")

    condition_entries: list[dict[str, Any]] = []
    for item in _as_list(analysis.get("matchedConditionRules")):
        parsed = _rule_entry(item, rule_map, {"condition"})
        if parsed:
            _append_rule(condition_entries, parsed[0], parsed[1].get("evidence", ""), parsed[1].get("reason", ""))
        elif item not in (None, "", {}):
            invalid_mappings.append(str(item))

    # A new phrase is accepted when Gemini maps it to the closest existing condition.
    mapped_condition_phrases: list[str] = []
    for item in _as_list(analysis.get("newConditionMappings")):
        parsed = _rule_entry(item, rule_map, {"condition"})
        if parsed:
            evidence = parsed[1].get("evidence", "") or (item.get("phrase", "") if isinstance(item, dict) else "")
            _append_rule(condition_entries, parsed[0], evidence, parsed[1].get("reason", "closest existing rule"))
            if evidence:
                mapped_condition_phrases.append(evidence)
        elif item not in (None, "", {}):
            unknown_conditions.append(str(item.get("phrase") if isinstance(item, dict) else item))

    if mapped_condition_phrases:
        unknown_conditions = [
            item for item in unknown_conditions
            if not any(phrase == item or phrase in item or item in phrase for phrase in mapped_condition_phrases)
        ]

    condition_text = " ".join(str(item) for item in _as_list(analysis.get("conditions")))
    condition_text = " ".join(part for part in (condition_text, str(analysis.get("availableTime") or ""), benefit_text) if part)
    if _number(analysis.get("minimumOrder", analysis.get("minimum_order")), 0) > 0:
        rule = next((item for item in rules if item.rule_type == "condition" and item.rule_key == "minimum_order_text"), None)
        if rule:
            _append_rule(condition_entries, rule, "최소 주문 금액")
    if _number(analysis.get("requiredPeople", analysis.get("required_people")), 1) > 1:
        rule = next((item for item in rules if item.rule_type == "condition" and item.rule_key == "minimum_quantity_or_people"), None)
        if rule:
            _append_rule(condition_entries, rule, "최소 인원")
    for rule in rules:
        if rule.rule_type == "condition" and rule.matches_text(condition_text):
            _append_rule(condition_entries, rule, condition_text.strip())

    student_verification = bool(analysis.get("studentVerification", analysis.get("student_verification", False)))
    if student_verification:
        # Student verification is an explicit field, not a penalty rule in the taxonomy.
        condition_entries = [
            item for item in condition_entries
            if not any(token in str(item.get("evidence", "")) for token in ("학생", "학생증", "student id"))
        ]
        unknown_conditions = [item for item in unknown_conditions if "학생" not in item and "학생증" not in item]

    base = max((float(item["score"]) for item in benefit_entries), default=0.0)
    bonus_entries: list[dict[str, Any]] = []
    for item in _as_list(analysis.get("matchedBonusRules")):
        parsed = _rule_entry(item, rule_map, {"bonus"})
        if parsed:
            _append_rule(bonus_entries, parsed[0], parsed[1].get("evidence", ""), parsed[1].get("reason", ""))
        elif item not in (None, "", {}):
            invalid_mappings.append(str(item))
    has_discount = rate > 0 or amount > 0
    has_service = bool(analysis.get("freeItem") or any(item["ruleKey"] == "other_service" for item in benefit_entries))
    if has_discount and has_service:
        rule = rule_map.get("discount_and_service")
        if rule:
            _append_rule(bonus_entries, rule, "할인과 서비스 동시 제공")
    bonus = sum(float(item["score"]) for item in bonus_entries)
    penalty_cap = next((rule.score for rule in rules if rule.rule_type == "condition_cap" and rule.rule_key == "maximum_penalty"), 20)
    penalty = min(float(penalty_cap), sum(float(item["score"]) for item in condition_entries))
    needs_review = bool(analysis.get("needsReview") or unknown_benefits or unknown_conditions or invalid_mappings)
    final_score = max(0.0, min(100.0, base + bonus - penalty))

    analysis["matchedBenefitRules"] = benefit_entries
    analysis["matchedConditionRules"] = condition_entries
    analysis["matchedBonusRules"] = bonus_entries
    analysis["newConditionMappings"] = _as_list(analysis.get("newConditionMappings"))
    analysis["unknownBenefits"] = list(dict.fromkeys(unknown_benefits))
    analysis["unknownConditions"] = list(dict.fromkeys(unknown_conditions))
    analysis["baseScore"] = base
    analysis["bonusScore"] = bonus
    analysis["conditionPenalty"] = penalty
    analysis["finalBenefitScore"] = final_score
    analysis["benefitBaseScore"] = base
    analysis["benefitBonusScore"] = bonus
    analysis["benefitConditionPenalty"] = penalty
    analysis["benefitScore"] = final_score
    analysis["needsReview"] = needs_review
    return analysis


def analyze_benefit(benefit_text: str, scoring_rules: Iterable[ScoringRule] | None = None) -> dict[str, Any]:
    """Ask Gemini to classify a benefit against the active scoring taxonomy."""
    rules_payload = json.dumps(_rule_prompt_payload(scoring_rules), ensure_ascii=False)
    prompt = f"""
Analyze this Korean partnership benefit sentence and return ONLY one JSON object.
Keep the extraction fields below and also classify the benefit against the supplied rules.
Never invent a rule key or score. Select the closest existing rule for a new benefit or
condition phrase and record the phrase in newConditionMappings with the selected ruleKey,
score, and a short reason. Only set needsReview=true when no reasonable existing rule can
represent the phrase, the text is ambiguous, or the output cannot be safely interpreted.

Required extraction keys:
benefitType, discountRate, discountAmount, freeItem, targetMenu, minimumOrder,
availableTime, requiredPeople, studentVerification, conditions, conditionCount,
unknownBenefits, unknownConditions, needsReview.

Required scoring keys:
matchedBenefitRules, matchedBonusRules, matchedConditionRules, newConditionMappings,
baseScore, bonusScore, conditionPenalty, finalBenefitScore.
Each matched rule item must contain ruleKey, score, and evidence. Use only ruleKey values
from the rule table. baseScore is the highest applicable benefit rule score. bonusScore is
the sum of applicable bonus rules. conditionPenalty is the sum of condition rule scores,
capped at the maximum_penalty rule. Student ID presentation is represented only by
studentVerification and must never be mapped to a penalty rule. finalBenefitScore is
clamp(baseScore + bonusScore - conditionPenalty, 0, 100). The server validates these
values before saving.

Active scoring rules:
{rules_payload}

Original benefit text:
{benefit_text}
""".strip()
    result = _json_from_text(_call_gemini(prompt))
    if not isinstance(result, dict):
        raise AIServiceError("AI가 혜택 분석 결과를 반환하지 않았습니다.")
    return normalize_benefit_analysis(result, benefit_text, scoring_rules)
