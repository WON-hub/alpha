from app.services.ai import normalize_benefit_analysis
from app.services.scoring_rules import load_default_scoring_rules


def test_ai_rule_mapping_calculates_canonical_components():
    rules = load_default_scoring_rules()
    analysis = normalize_benefit_analysis(
        {
            "benefitType": "service",
            "discountRate": None,
            "discountAmount": None,
            "freeItem": "\uc74c\ub8cc\uc218 \ud55c\uc794",
            "targetMenu": "\uc74c\ub8cc",
            "minimumOrder": None,
            "availableTime": None,
            "requiredPeople": 1,
            "studentVerification": True,
            "conditions": ["\ud559\uc0dd\uc99d \uc81c\uc2dc"],
            "matchedBenefitRules": [{"ruleKey": "drink_side_noodle", "score": 999, "evidence": "\uc74c\ub8cc\uc218 \ud55c\uc794"}],
            "matchedConditionRules": [],
            "unknownBenefits": [],
            "unknownConditions": [],
            "needsReview": False,
        },
        "\ud559\uc0dd\uc99d \uc81c\uc2dc\uc2dc \uc74c\ub8cc\uc218 \ud55c\uc794 \ubb34\ub8cc",
        rules,
    )

    assert analysis["baseScore"] == 60
    assert analysis["bonusScore"] == 0
    assert analysis["conditionPenalty"] == 0
    assert analysis["finalBenefitScore"] == 60
    assert analysis["matchedBenefitRules"][0]["score"] == 60
    assert analysis["needsReview"] is False


def test_new_condition_is_mapped_to_closest_existing_rule():
    rules = load_default_scoring_rules()
    analysis = normalize_benefit_analysis(
        {
            "benefitType": "percentage",
            "discountRate": 10,
            "discountAmount": None,
            "freeItem": "",
            "conditions": ["\uc608\uc57d \uc571 \uc0ac\uc6a9"],
            "newConditionMappings": [
                {
                    "phrase": "\uc608\uc57d \uc571 \uc0ac\uc6a9",
                    "ruleKey": "phone_reservation",
                    "reason": "\uc608\uc57d\uc774 \ud544\uc694\ud55c \uc870\uac74\uc5d0 \uac00\uc7a5 \uac00\uae4c\uc6b4 \uae30\uc874 \ud56d\ubaa9",
                }
            ],
            "unknownBenefits": [],
            "unknownConditions": [],
            "needsReview": False,
        },
        "10% \ud560\uc778, \uc608\uc57d \uc571 \uc0ac\uc6a9",
        rules,
    )

    assert analysis["baseScore"] == 80
    assert analysis["conditionPenalty"] == 5
    assert analysis["finalBenefitScore"] == 75
    assert analysis["matchedConditionRules"][0]["ruleKey"] == "phone_reservation"
    assert analysis["needsReview"] is False


def test_unknown_rule_key_requires_review_and_cannot_inject_score():
    rules = load_default_scoring_rules()
    analysis = normalize_benefit_analysis(
        {
            "benefitType": "service",
            "freeItem": "\ud2b9\uc218 \uc11c\ube44\uc2a4",
            "matchedBenefitRules": [{"ruleKey": "invented_rule", "score": 100}],
            "unknownBenefits": [],
            "unknownConditions": [],
            "needsReview": False,
        },
        "\ud2b9\uc218 \uc11c\ube44\uc2a4",
        rules,
    )

    assert analysis["baseScore"] == 20
    assert analysis["finalBenefitScore"] == 20
    assert analysis["needsReview"] is True
