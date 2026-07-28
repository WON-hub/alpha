from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from math import atan2, cos, radians, sin, sqrt

from app.models import Affiliation, Partnership, Restaurant
from app.schemas import GroupIn, RecommendationRequest


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
    matching = [group for group in groups if partnership.affiliation_id in ancestor_ids(group.affiliation_id, affiliations_by_id)]
    eligible_count = sum(group.count for group in matching)
    if eligible_count == 0:
        return None
    names = [affiliations_by_id[group.affiliation_id].name for group in matching if group.affiliation_id in affiliations_by_id]
    return EligibleGroup(count=eligible_count, total=total, affiliation_names=names)


def _benefit_raw_score(partnership: Partnership) -> float:
    rate_points = 0
    if partnership.discount_rate:
        rate_points = 10 if partnership.discount_rate <= 10 else 15
    value = max(partnership.estimated_cash_value or 0, partnership.fixed_discount or 0)
    value_points = 0
    if value:
        value_points = 10 if value <= 1000 else 20 if value < 3000 else 30
    return float(min(30, max(rate_points, value_points)))


def _application_ratio(partnership: Partnership, eligible: EligibleGroup) -> float:
    if partnership.application_scope in {"ALL_GROUP", "ONCE_PER_ORDER"}:
        return 1.0
    return eligible.count / eligible.total


def calculate_savings(partnership: Partnership, budget_per_person: int, eligible: EligibleGroup) -> int:
    total_amount = budget_per_person * eligible.total
    eligible_amount = budget_per_person * eligible.count
    if partnership.application_scope == "ELIGIBLE_MEMBERS_ONLY":
        discount_base = eligible_amount
    else:
        discount_base = total_amount

    savings = 0.0
    if partnership.discount_rate:
        savings += discount_base * partnership.discount_rate / 100
    if partnership.fixed_discount:
        if partnership.application_scope == "ELIGIBLE_MEMBERS_ONLY":
            savings += partnership.fixed_discount * eligible.count
        else:
            savings += partnership.fixed_discount
    if partnership.estimated_cash_value:
        if partnership.application_scope == "ELIGIBLE_MEMBERS_ONLY":
            savings += partnership.estimated_cash_value * eligible.count
        else:
            savings += partnership.estimated_cash_value
    return max(0, min(total_amount, round(savings)))


def benefit_label(partnership: Partnership) -> str:
    bits: list[str] = []
    if partnership.discount_rate:
        bits.append(f"{partnership.discount_rate:g}% 할인")
    if partnership.fixed_discount:
        bits.append(f"{partnership.fixed_discount:,}원 할인")
    if partnership.service_item:
        bits.append(f"{partnership.service_item} 제공")
    return " + ".join(bits) or "제휴 혜택"


def _reasons(partnership: Partnership, distance_m: float, max_distance_m: int, savings: int, eligible: EligibleGroup, review_limited: bool) -> list[str]:
    reasons = [f"{benefit_label(partnership)}으로 약 {savings:,}원 절약 예상"]
    if partnership.application_scope == "ALL_GROUP":
        reasons.append("동행자 중 대상자가 있어 일행 전체에 적용")
    elif partnership.application_scope == "ELIGIBLE_MEMBERS_ONLY":
        reasons.append(f"대상 소속 {eligible.count}명에게 적용")
    else:
        reasons.append("주문 1건 기준으로 한 번 적용")
    if distance_m <= max_distance_m * 0.5:
        reasons.append("현재 위치에서 가까운 편")
    if review_limited:
        reasons.append("리뷰가 적어 만족도 점수는 기본값 반영")
    return reasons


def recommend(
    request: RecommendationRequest,
    restaurants: list[Restaurant],
    affiliations: list[Affiliation],
    as_of: date | None = None,
) -> list[dict]:
    affiliations_by_id = {affiliation.id: affiliation for affiliation in affiliations}
    results: list[dict] = []
    current = as_of or date.today()
    total_people = sum(group.count for group in request.groups)
    estimated_total = request.budget_per_person * total_people

    for restaurant in restaurants:
        if restaurant.status != "active" or (request.category != "전체" and restaurant.category != request.category):
            continue
        distance_m = haversine_m(request.location.lat, request.location.lng, restaurant.latitude, restaurant.longitude)
        if distance_m > request.max_distance_m:
            continue
        valid_partnerships = [p for p in restaurant.partnerships if is_partnership_valid(p, current)]
        for partnership in valid_partnerships:
            if request.payment_method and partnership.payment_method and partnership.payment_method != request.payment_method:
                continue
            eligible = resolve_eligible_group(partnership, request.groups, affiliations_by_id)
            if eligible is None or total_people < partnership.min_people or estimated_total < partnership.min_order_amount:
                continue
            savings = calculate_savings(partnership, request.budget_per_person, eligible)
            final_total = max(0, estimated_total - savings)
            satisfaction_score = (restaurant.rating_average / 5 * 100) if restaurant.review_count else 60.0
            benefit_score = min(100, (_benefit_raw_score(partnership) / 30 * 100) * _application_ratio(partnership, eligible))
            distance_score = max(0, 100 - (distance_m / request.max_distance_m * 100))
            cdi = benefit_score * 0.4 + distance_score * 0.2 + satisfaction_score * 0.4
            review_limited = restaurant.review_count == 0
            results.append(
                {
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
                    "menu_summary": restaurant.menu_summary,
                    "distance_m": round(distance_m),
                    "walking_minutes": max(1, round(distance_m / 75)),
                    "eligible_affiliations": eligible.affiliation_names,
                    "benefit_label": benefit_label(partnership),
                    "application_scope": partnership.application_scope,
                    "payment_method": partnership.payment_method,
                    "min_order_amount": partnership.min_order_amount,
                    "min_people": partnership.min_people,
                    "verification_method": partnership.verification_method,
                    "estimated_total": estimated_total,
                    "estimated_savings": savings,
                    "final_total": final_total,
                    "final_per_person": round(final_total / total_people) if total_people else 0,
                    "cdi": round(cdi, 1),
                    "benefit_score": round(benefit_score, 1),
                    "distance_score": round(distance_score, 1),
                    "satisfaction_score": round(satisfaction_score, 1),
                    "review_limited": review_limited,
                    "reasons": _reasons(partnership, distance_m, request.max_distance_m, savings, eligible, review_limited),
                    "partnership_id": partnership.id,
                }
            )
    results.sort(key=lambda item: (-item["cdi"], -item["estimated_savings"], item["distance_m"]))
    return results[:5]

