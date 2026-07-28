from datetime import date, timedelta

from app.models import Affiliation, Partnership, Restaurant
from app.schemas import GroupIn, LocationIn, RecommendationRequest
from app.services.recommendation import calculate_savings, is_partnership_valid, recommend, resolve_eligible_group


def build_affiliations():
    university = Affiliation(id=1, name="광운대학교", type="university")
    college = Affiliation(id=2, name="전자정보공과대학", type="college", parent_id=1)
    department = Affiliation(id=3, name="전자공학과", type="department", parent_id=2)
    return [university, college, department]


def build_partnership(scope="ALL_GROUP", rate=20):
    return Partnership(id=1, restaurant_id=1, affiliation_id=2, benefit_type="percentage", discount_rate=rate, fixed_discount=0, estimated_cash_value=0, min_order_amount=0, min_people=1, payment_method="", application_scope=scope, verification_method="학생증", start_date=date.today() - timedelta(days=1), end_date=date.today() + timedelta(days=1), status="active")


def test_hierarchical_affiliation_matching():
    affiliations = build_affiliations()
    eligible = resolve_eligible_group(build_partnership(), [GroupIn(affiliation_id=3, count=2)], {item.id: item for item in affiliations})
    assert eligible is not None
    assert eligible.count == 2


def test_partnership_date_validation():
    partnership = build_partnership()
    assert is_partnership_valid(partnership)
    partnership.end_date = date.today() - timedelta(days=1)
    assert not is_partnership_valid(partnership)


def test_application_scope_and_savings():
    partnership = build_partnership("ELIGIBLE_MEMBERS_ONLY", rate=10)
    affiliations = build_affiliations()
    eligible = resolve_eligible_group(partnership, [GroupIn(affiliation_id=3, count=1), GroupIn(affiliation_id=1, count=2)], {item.id: item for item in affiliations})
    assert eligible.count == 1
    assert calculate_savings(partnership, 10000, eligible) == 1000


def test_recommendation_filters_expired_and_sorts_by_cdi():
    restaurant = Restaurant(id=1, name="테스트 식당", category="식사류", address="", latitude=37.6194, longitude=127.0597, rating_average=5, review_count=10, status="active", partnerships=[build_partnership()])
    request = RecommendationRequest(location=LocationIn(lat=37.6194, lng=127.0597), category="전체", budget_per_person=10000, max_distance_m=1000, groups=[GroupIn(affiliation_id=3, count=2)])
    result = recommend(request, [restaurant], build_affiliations())
    assert len(result) == 1
    assert result[0]["estimated_savings"] == 4000
    restaurant.partnerships[0].end_date = date.today() - timedelta(days=1)
    assert recommend(request, [restaurant], build_affiliations()) == []

