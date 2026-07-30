from datetime import date, timedelta

from app.models import Affiliation, Partnership, Restaurant
from app.schemas import GroupIn, LocationIn, RecommendationRequest
from app.services.recommendation import (
    bayesian_satisfaction,
    benefit_grade,
    benefit_score_components,
    calculate_savings,
    distance_score,
    is_partnership_valid,
    recommend,
    resolve_eligible_group,
)


def build_affiliations():
    university = Affiliation(id=1, name="광운대학교", type="university")
    college = Affiliation(id=2, name="전자정보공과대학", type="college", parent_id=1)
    department = Affiliation(id=3, name="전자공학과", type="department", parent_id=2)
    return [university, college, department]


def build_partnership(scope="ALL_GROUP", rate=20, affiliation_id=2, service_item=""):
    return Partnership(
        id=1,
        restaurant_id=1,
        affiliation_id=affiliation_id,
        benefit_type="percentage",
        discount_rate=rate,
        fixed_discount=0,
        service_item=service_item,
        estimated_cash_value=0,
        min_order_amount=0,
        min_people=1,
        payment_method="",
        application_scope=scope,
        verification_method="학생증",
        start_date=date.today() - timedelta(days=1),
        end_date=date.today() + timedelta(days=1),
        status="active",
    )


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


def test_application_scope_and_fixed_budget_savings():
    partnership = build_partnership("ELIGIBLE_MEMBERS_ONLY", rate=10)
    affiliations = build_affiliations()
    eligible = resolve_eligible_group(partnership, [GroupIn(affiliation_id=3, count=1), GroupIn(affiliation_id=1, count=2)], {item.id: item for item in affiliations})
    assert eligible.count == 1
    assert calculate_savings(partnership, 12_000, eligible) == 1_200


def test_distance_bands_are_discrete():
    assert distance_score(0) == 5
    assert distance_score(99.9) == 5
    assert distance_score(100) == 4
    assert distance_score(200) == 3
    assert distance_score(400) == 2
    assert distance_score(600) == 1
    assert distance_score(999.9) == 1
    assert distance_score(1000) == 0


def test_benefit_grade_thresholds_match_report():
    assert benefit_grade(65)[0] == "황금밥알"
    assert benefit_grade(64.9)[0] == "은빛밥알"
    assert benefit_grade(50)[0] == "은빛밥알"
    assert benefit_grade(49.9)[0] == "고운밥알"
    assert benefit_grade(30)[0] == "고운밥알"
    assert benefit_grade(29.9)[0] == "한톨밥알"


def test_report_benefit_bonus_adds_five_for_multiple_services():
    partnership = build_partnership(rate=0, service_item="음료와 사리 제공")
    _base, bonus, _penalty, score = benefit_score_components(partnership)
    assert bonus == 5
    assert score == 65


def test_unrecognized_benefit_requires_review_and_is_not_scored():
    partnership = build_partnership(rate=20)
    partnership.benefit_needs_review = True
    _base, _bonus, _penalty, score = benefit_score_components(partnership)
    assert score == 0


def test_bayesian_satisfaction_uses_platform_prior_for_new_store():
    new_restaurant = Restaurant(rating_average=0, review_count=0)
    rated_restaurant = Restaurant(rating_average=5, review_count=10)
    assert bayesian_satisfaction(new_restaurant, 60) == 60
    assert bayesian_satisfaction(rated_restaurant, 60) == 80


def test_recommendation_deduplicates_restaurant_and_merges_benefits():
    first = build_partnership(rate=20, affiliation_id=2)
    second = build_partnership(rate=0, affiliation_id=3, service_item="무료 음료")
    second.id = 2
    restaurant = Restaurant(
        id=1,
        name="중복 없는 식당",
        category="식사류",
        address="",
        latitude=37.6194,
        longitude=127.0597,
        rating_average=5,
        review_count=10,
        status="active",
        partnerships=[first, second],
    )
    request = RecommendationRequest(
        location=LocationIn(lat=37.6194, lng=127.0597),
        category="전체",
        budget_per_person=10000,
        groups=[GroupIn(affiliation_id=3, count=2)],
    )
    result = recommend(request, [restaurant], build_affiliations())
    assert len(result) == 1
    assert "20% 할인" in result[0]["benefit_items"]
    assert "무료 음료" in result[0]["benefit_items"]
    assert result[0]["eligible_colleges"] == ["전자정보공과대학"]
    assert result[0]["estimated_savings"] == 4_800


def test_expired_partnership_is_filtered():
    restaurant = Restaurant(
        id=1,
        name="만료 식당",
        category="식사류",
        address="",
        latitude=37.6194,
        longitude=127.0597,
        rating_average=5,
        review_count=10,
        status="active",
        partnerships=[build_partnership()],
    )
    request = RecommendationRequest(location=LocationIn(lat=37.6194, lng=127.0597), groups=[GroupIn(affiliation_id=3, count=2)])
    restaurant.partnerships[0].end_date = date.today() - timedelta(days=1)
    assert recommend(request, [restaurant], build_affiliations()) == []
