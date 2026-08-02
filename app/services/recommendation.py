from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from math import atan2, cos, radians, sin, sqrt

from app.models import Affiliation, Partnership, Restaurant
from app.schemas import GroupIn, RecommendationRequest
from app.services.scoring_rules import ScoringRule, load_default_scoring_rules


FIXED_BUDGET_PER_PERSON = 12_000
MIN_REVIEW_COUNT = 10
DEFAULT_PLATFORM_SATISFACTION = 60.0
CDI_BENEFIT_WEIGHT = 0.53
CDI_DISTANCE_WEIGHT = 0.27
CDI_SATISFACTION_WEIGHT = 0.20

DISTANCE_BANDS = (
    (50, 100),
    (100, 80),
    (150, 60),
    (250, 40),
    (500, 20),
)


@dataclass
class EligibleGroup:
    count: int
    total: int
    affiliation_names: list[str]


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    radius = 6_371_000
    phi1, phi2 = radians(lat1), radians(lat2)
    d_phi = radians(lat2 - lat1)
    d_lambda = radians(lng2 - lng1)
    a = sin(d_phi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(d_lambda / 2) ** 2
    return 2 * radius * atan2(sqrt(a), sqrt(1 - a))


def is_partnership_valid(partnership: Partnership, as_of: date | None = None) -> bool:
    current = as_of or date.today()
    return partnership.status == "active" and partnership.start_date <= current <= partnership.end_date


def ancestor_ids(affiliation_id: int, affiliations_by_id: dict[int, Affiliation]) -> set[int]:
    ids: set[int] = set()
    current = affiliations_by_id.get(affiliation_id)
    while current:
        if current.id in ids:
            break
        ids.add(current.id)
        current = affiliations_by_id.get(current.parent_id) if current.parent_id else None
    return ids


def resolve_eligible_group(
    partnership: Partnership,
    groups: list[GroupIn],
    affiliations_by_id: dict[int, Affiliation],
) -> EligibleGroup | None:
    total = sum(group.count for group in groups)
    target = affiliations_by_id.get(partnership.affiliation_id)
    partnership_is_all = bool(target and target.name == "전체")
    matching = [
        group
        for group in groups
        if partnership_is_all
        or (affiliations_by_id.get(group.affiliation_id) and affiliations_by_id[group.affiliation_id].name == "전체")
        or partnership.affiliation_id in ancestor_ids(group.affiliation_id, affiliations_by_id)
    ]
    eligible_count = sum(group.count for group in matching)
    if eligible_count == 0:
        return None
    names = [affiliations_by_id[group.affiliation_id].name for group in matching if group.affiliation_id in affiliations_by_id]
    return EligibleGroup(count=eligible_count, total=total, affiliation_names=names)


def _college_name(affiliation_id: int, affiliations_by_id: dict[int, Affiliation]) -> str:
    current = affiliations_by_id.get(affiliation_id)
    visited: set[int] = set()
    while current and current.id not in visited:
        visited.add(current.id)
        if current.name == "전체":
            return "전체"
        if current.type in {"college", "university"}:
            return current.name
        current = affiliations_by_id.get(current.parent_id) if current.parent_id else None
    return affiliations_by_id.get(affiliation_id).name if affiliation_id in affiliations_by_id else ""


def _service_text(partnership: Partnership) -> str:
    return " ".join(
        str(value or "")
        for value in (partnership.benefit_text, partnership.service_item, partnership.eligibility_description, partnership.verification_method)
    ).lower()


def _rules_for(rules: list[ScoringRule] | None, rule_type: str) -> list[ScoringRule]:
    active = rules if rules is not None else load_default_scoring_rules()
    return [rule for rule in active if rule.rule_type == rule_type]


def _value_rule(rules: list[ScoringRule] | None, rule_type: str, value: float) -> ScoringRule | None:
    return next((rule for rule in _rules_for(rules, rule_type) if rule.matches_value(value)), None)


def _rule_score(rules: list[ScoringRule] | None, rule_type: str, rule_key: str, fallback: float = 0) -> float:
    return next((rule.score for rule in _rules_for(rules, rule_type) if rule.rule_key == rule_key), fallback)


def _benefit_base_score(partnership: Partnership, rules: list[ScoringRule] | None = None) -> int:
    scores: list[int] = []
    rate = float(partnership.discount_rate or 0)
    if rate > 0:
        rule = _value_rule(rules, "discount_rate", rate)
        if rule:
            scores.append(int(rule.score))

    fixed = max(int(partnership.fixed_discount or 0), int(partnership.estimated_cash_value or 0))
    if fixed > 0:
        rule = _value_rule(rules, "fixed_discount", fixed)
        if rule:
            scores.append(int(rule.score))

    text = _service_text(partnership)
    text_rules = _rules_for(rules, "benefit_text")
    matched_text_rule = next((rule for rule in text_rules if rule.matches_text(text)), None)
    if matched_text_rule:
        scores.append(int(matched_text_rule.score))
    elif partnership.service_item or partnership.benefit_type:
        fallback_rule = next((rule for rule in text_rules if not rule.keywords), None)
        scores.append(int(fallback_rule.score if fallback_rule else 20))
    return max(scores, default=20)


def _condition_penalty(partnership: Partnership, rules: list[ScoringRule] | None = None) -> int:
    text = " ".join(
        str(value or "")
        for value in (partnership.benefit_text, partnership.eligibility_description, partnership.verification_method, partnership.payment_method)
    ).lower()
    penalty = sum(rule.score for rule in _rules_for(rules, "condition") if rule.matches_text(text))
    if partnership.min_order_amount:
        penalty += 10
    if partnership.min_people > 1:
        penalty += 10
    return int(min(_rule_score(rules, "condition_cap", "maximum_penalty", 20), penalty))


def benefit_score_components(partnership: Partnership, rules: list[ScoringRule] | None = None) -> tuple[float, float, float, float]:
    """Return base, bonus, condition penalty, and uncapped application score."""
    base = float(_benefit_base_score(partnership, rules))
    text = _service_text(partnership)
    has_discount = bool(partnership.discount_rate or partnership.fixed_discount)
    has_service = bool(partnership.service_item or any(token in text for token in ("음료", "사이드", "서비스")))
    bonus = _rule_score(rules, "bonus", "discount_and_service", 5) if has_discount and has_service else 0.0
    if not any(token in text for token in ("또는", "택1", "택 1")):
        benefit_parts = [part for part in re.split(r"(?:\r?\n|;|①|②|③|④)", benefit_text(partnership)) if part.strip()]
        additional_rule = next((rule for rule in _rules_for(rules, "bonus") if rule.rule_key == "additional_service"), None)
        if additional_rule:
            service_count = sum(keyword in text for keyword in additional_rule.keywords)
            bonus = max(bonus, float(max(0, len(benefit_parts) - 1) * additional_rule.score))
            bonus = max(bonus, float(max(0, service_count - 1) * additional_rule.score))
    penalty = float(_condition_penalty(partnership, rules))
    score = max(0.0, min(100.0, base + bonus - penalty))
    if partnership.benefit_needs_review:
        score = 0.0
    return base, bonus, penalty, score


def _application_ratio(partnership: Partnership, eligible: EligibleGroup) -> float:
    if partnership.application_scope in {"ALL_GROUP", "ONCE_PER_ORDER"}:
        return 1.0
    return eligible.count / eligible.total if eligible.total else 0.0


def calculate_benefit_score(partnership: Partnership, eligible: EligibleGroup, rules: list[ScoringRule] | None = None) -> float:
    if partnership.benefit_needs_review:
        return 0.0
    if partnership.benefit_preprocessed_at:
        score = float(partnership.benefit_score_cached or 0)
    else:
        score = benefit_score_components(partnership, rules)[3]
    return min(100, score * _application_ratio(partnership, eligible))


def distance_score(distance_m: float) -> float:
    for upper_bound, score in DISTANCE_BANDS:
        if distance_m < upper_bound:
            return float(score)
    return 0.0


def bayesian_satisfaction(restaurant: Restaurant, platform_mean: float, confidence_count: int = MIN_REVIEW_COUNT) -> float:
    review_count = max(0, int(restaurant.review_count or 0))
    actual = (float(restaurant.rating_average or 0) / 5 * 100) if review_count else platform_mean
    return (confidence_count * platform_mean + review_count * actual) / (confidence_count + review_count)


def _platform_mean(restaurants: list[Restaurant]) -> float:
    total_reviews = sum(max(0, int(restaurant.review_count or 0)) for restaurant in restaurants)
    if not total_reviews:
        return DEFAULT_PLATFORM_SATISFACTION
    weighted_score = sum((float(restaurant.rating_average or 0) / 5 * 100) * restaurant.review_count for restaurant in restaurants)
    return weighted_score / total_reviews


def calculate_savings(partnership: Partnership, budget_per_person: int, eligible: EligibleGroup) -> int:
    total_amount = budget_per_person * eligible.total
    eligible_amount = budget_per_person * eligible.count
    discount_base = eligible_amount if partnership.application_scope == "ELIGIBLE_MEMBERS_ONLY" else total_amount
    savings = 0.0
    if partnership.discount_rate:
        savings += discount_base * partnership.discount_rate / 100
    if partnership.fixed_discount:
        savings += partnership.fixed_discount * eligible.count if partnership.application_scope == "ELIGIBLE_MEMBERS_ONLY" else partnership.fixed_discount
    if partnership.estimated_cash_value:
        savings += partnership.estimated_cash_value * eligible.count if partnership.application_scope == "ELIGIBLE_MEMBERS_ONLY" else partnership.estimated_cash_value
    return max(0, min(total_amount, round(savings)))


def _fallback_benefit_text(partnership: Partnership) -> str:
    items: list[str] = []
    if partnership.discount_rate:
        rate = int(partnership.discount_rate) if float(partnership.discount_rate).is_integer() else partnership.discount_rate
        items.append(f"{rate}% 할인")
    if partnership.fixed_discount:
        items.append(f"{partnership.fixed_discount:,}원 할인")
    if partnership.service_item:
        items.append(str(partnership.service_item).strip())
    if partnership.estimated_cash_value and not partnership.service_item:
        items.append(f"추가 혜택 ({partnership.estimated_cash_value:,}원 상당)")
    return "\n".join(item for item in items if item)


def benefit_text(partnership: Partnership) -> str:
    return str(partnership.benefit_text or "").strip() or _fallback_benefit_text(partnership)


def benefit_items(partnership: Partnership) -> list[str]:
    text = benefit_text(partnership)
    items = [part.strip(" •·-\t") for part in re.split(r"[\r\n]+", text) if part.strip(" •·-\t")]
    return list(dict.fromkeys(items or ["제휴 혜택"]))


def benefit_conditions(partnership: Partnership) -> list[str]:
    conditions: list[str] = []
    if partnership.verification_method:
        conditions.append(str(partnership.verification_method).strip())
    if partnership.eligibility_description:
        conditions.append(str(partnership.eligibility_description).strip())
    if partnership.application_scope == "ELIGIBLE_MEMBERS_ONLY":
        conditions.append("대상 소속 구성원에게 적용")
    elif partnership.application_scope == "ONCE_PER_ORDER":
        conditions.append("주문당 1회 적용")
    if partnership.min_order_amount:
        conditions.append("최소 주문 조건 있음")
    if partnership.min_people > 1:
        conditions.append(f"{partnership.min_people}명 이상 이용")
    if partnership.payment_method:
        conditions.append(f"{partnership.payment_method} 결제 필요")
    return list(dict.fromkeys(item for item in conditions if item))


def public_benefit_label(partnership: Partnership) -> str:
    return " · ".join(benefit_items(partnership))


def benefit_grade(score: float) -> tuple[str, str]:
    if score >= 65:
        return "황금밥알", "🌟🍚"
    if score >= 50:
        return "은빛밥알", "✨🍚"
    if score >= 30:
        return "고운밥알", "🌸🍚"
    return "한톨밥알", "🍚"


def fallback_store_summary(restaurant: Restaurant) -> str:
    from app.services.ai import fallback_store_summary as make_summary

    return make_summary(restaurant.category, restaurant.menu_summary, restaurant.name)


def _reasons(partnership: Partnership, distance_m: float, eligible: EligibleGroup) -> list[str]:
    reasons = ["적용 가능한 제휴 혜택"]
    if partnership.application_scope == "ALL_GROUP":
        reasons.append("일행 전체 적용")
    elif partnership.application_scope == "ELIGIBLE_MEMBERS_ONLY":
        reasons.append(f"대상 소속 {eligible.count}명 적용")
    else:
        reasons.append("주문당 1회 적용")
    if distance_m < 150:
        reasons.append("현재 위치에서 가까움")
    if not partnership.restaurant.review_count:
        reasons.append("신규 매장 기본 만족도 적용")
    return reasons


def _merge_result(current: dict, candidate: dict) -> dict:
    for key in ("eligible_affiliations", "eligible_colleges", "benefit_items", "benefit_conditions", "reasons"):
        current[key] = list(dict.fromkeys(current[key] + candidate[key]))
    if candidate["cdi"] > current["cdi"]:
        preserved = {key: current[key] for key in ("eligible_affiliations", "eligible_colleges", "benefit_items", "benefit_conditions", "reasons")}
        current.update(candidate)
        current.update(preserved)
    return current


def recommend(
    request: RecommendationRequest,
    restaurants: list[Restaurant],
    affiliations: list[Affiliation],
    as_of: date | None = None,
    scoring_rules: list[ScoringRule] | None = None,
) -> list[dict]:
    affiliations_by_id = {affiliation.id: affiliation for affiliation in affiliations}
    platform_mean = _platform_mean(restaurants)
    current = as_of or date.today()
    total_people = sum(group.count for group in request.groups)
    budget_per_person = FIXED_BUDGET_PER_PERSON
    estimated_total = budget_per_person * total_people
    grouped: dict[int, dict] = {}

    for restaurant in restaurants:
        if restaurant.status != "active" or (request.category != "전체" and restaurant.category != request.category):
            continue
        distance_m = haversine_m(request.location.lat, request.location.lng, restaurant.latitude, restaurant.longitude)
        if request.max_distance_m is not None and distance_m > request.max_distance_m:
            continue
        satisfaction = float(restaurant.bayesian_satisfaction_score or 0) if restaurant.satisfaction_preprocessed_at else bayesian_satisfaction(restaurant, platform_mean)
        valid_partnerships = [partnership for partnership in restaurant.partnerships if is_partnership_valid(partnership, current)]
        for partnership in valid_partnerships:
            if partnership.benefit_needs_review:
                continue
            if request.payment_method and partnership.payment_method and partnership.payment_method != request.payment_method:
                continue
            eligible = resolve_eligible_group(partnership, request.groups, affiliations_by_id)
            if eligible is None or total_people < partnership.min_people or estimated_total < partnership.min_order_amount:
                continue
            benefit = calculate_benefit_score(partnership, eligible, scoring_rules)
            distance = distance_score(distance_m)
            cdi = (
                benefit * CDI_BENEFIT_WEIGHT
                + distance * CDI_DISTANCE_WEIGHT
                + satisfaction * CDI_SATISFACTION_WEIGHT
            )
            savings = calculate_savings(partnership, budget_per_person, eligible)
            grade, emoji = benefit_grade(benefit)
            candidate = {
                "id": restaurant.id,
                "name": restaurant.name,
                "category": restaurant.category,
                "rating_average": round(restaurant.rating_average, 1),
                "review_count": restaurant.review_count,
                "latitude": restaurant.latitude,
                "longitude": restaurant.longitude,
                "address": restaurant.address,
                "phone": restaurant.phone,
                "opening_hours": restaurant.opening_hours,
                "distance_m": round(distance_m),
                "walking_minutes": max(1, round(distance_m / 75)),
                "eligible_affiliations": eligible.affiliation_names,
                "eligible_colleges": [_college_name(partnership.affiliation_id, affiliations_by_id)],
                "ai_store_summary": restaurant.ai_summary or fallback_store_summary(restaurant),
                "benefit_items": benefit_items(partnership),
                "benefit_conditions": benefit_conditions(partnership),
                "benefit_grade": grade,
                "benefit_grade_emoji": emoji,
                "benefit_label": public_benefit_label(partnership),
                "application_scope": partnership.application_scope,
                "payment_method": partnership.payment_method,
                "min_order_amount": partnership.min_order_amount,
                "min_people": partnership.min_people,
                "verification_method": partnership.verification_method,
                "estimated_total": estimated_total,
                "estimated_savings": savings,
                "final_total": max(0, estimated_total - savings),
                "final_per_person": round(max(0, estimated_total - savings) / total_people) if total_people else 0,
                "cdi": round(cdi, 1),
                "benefit_score": round(benefit, 1),
                "distance_score": round(distance, 1),
                "satisfaction_score": round(satisfaction, 1),
                "review_limited": restaurant.review_count < MIN_REVIEW_COUNT,
                "reasons": _reasons(partnership, distance_m, eligible),
                "partnership_id": partnership.id,
            }
            if restaurant.id in grouped:
                grouped[restaurant.id] = _merge_result(grouped[restaurant.id], candidate)
            else:
                grouped[restaurant.id] = candidate

    results = list(grouped.values())
    results.sort(key=lambda item: (-item["cdi"], -item["benefit_score"], item["distance_m"]))
    return results
