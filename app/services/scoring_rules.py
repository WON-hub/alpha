from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BenefitScoringRule


@dataclass(frozen=True)
class ScoringRule:
    rule_type: str
    rule_key: str
    label: str
    keywords: tuple[str, ...] = ()
    min_value: float | None = None
    max_value: float | None = None
    score: float = 0
    sort_order: int = 0

    def matches_text(self, text: str) -> bool:
        return bool(self.keywords) and any(keyword.lower() in text.lower() for keyword in self.keywords)

    def matches_value(self, value: float) -> bool:
        return (self.min_value is None or value >= self.min_value) and (self.max_value is None or value < self.max_value)


def _config_path() -> Path:
    return Path(__file__).resolve().parents[2] / "config" / "benefit_scoring_rules.json"


def _from_config(item: dict) -> ScoringRule:
    return ScoringRule(
        rule_type=item["rule_type"],
        rule_key=item["rule_key"],
        label=item["label"],
        keywords=tuple(str(value) for value in item.get("keywords", [])),
        min_value=item.get("min_value"),
        max_value=item.get("max_value"),
        score=float(item.get("score", 0)),
        sort_order=int(item.get("sort_order", 0)),
    )


def load_default_scoring_rules() -> list[ScoringRule]:
    path = _config_path()
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as stream:
        return [_from_config(item) for item in json.load(stream)]


def load_scoring_rules(db: Session) -> list[ScoringRule]:
    rows = db.scalars(
        select(BenefitScoringRule)
        .where(BenefitScoringRule.enabled.is_(True))
        .order_by(BenefitScoringRule.rule_type, BenefitScoringRule.sort_order, BenefitScoringRule.id)
    ).all()
    if not rows:
        return load_default_scoring_rules()
    result: list[ScoringRule] = []
    for row in rows:
        try:
            keywords = tuple(str(value) for value in json.loads(row.keywords_json or "[]"))
        except json.JSONDecodeError:
            keywords = ()
        result.append(
            ScoringRule(
                rule_type=row.rule_type,
                rule_key=row.rule_key,
                label=row.label,
                keywords=keywords,
                min_value=row.min_value,
                max_value=row.max_value,
                score=float(row.score),
                sort_order=row.sort_order,
            )
        )
    return result
