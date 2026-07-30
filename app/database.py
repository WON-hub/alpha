from collections.abc import Generator
import json
from pathlib import Path

from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


def _normalise_database_url(url: str) -> str:
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


settings = get_settings()
database_url = _normalise_database_url(settings.database_url)
engine_kwargs: dict = {"pool_pre_ping": True}
if database_url.startswith("sqlite"):
    engine_kwargs["connect_args"] = {"check_same_thread": False}

engine = create_engine(database_url, **engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def init_db() -> None:
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _ensure_optional_columns()
    _ensure_scoring_rules()


def _ensure_optional_columns() -> None:
    """Add MVP fields to databases created before the field was introduced."""
    inspector = inspect(engine)
    if "restaurants" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("restaurants")}
    if "ai_summary" not in columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE restaurants ADD COLUMN ai_summary TEXT NOT NULL DEFAULT ''"))
    for column_name, column_definition in {
        "place_id": "VARCHAR(255) NOT NULL DEFAULT ''",
        "place_provider": "VARCHAR(20) NOT NULL DEFAULT ''",
    }.items():
        if column_name not in columns:
            with engine.begin() as connection:
                connection.execute(text(f"ALTER TABLE restaurants ADD COLUMN {column_name} {column_definition}"))
    partnership_columns = {column["name"] for column in inspector.get_columns("partnerships")}
    if "benefit_text" not in partnership_columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE partnerships ADD COLUMN benefit_text TEXT NOT NULL DEFAULT ''"))
    if "benefit_ai_json" not in partnership_columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE partnerships ADD COLUMN benefit_ai_json TEXT NOT NULL DEFAULT '{}'"))
    optional_partnership_columns = {
        "benefit_base_score": "FLOAT NOT NULL DEFAULT 20",
        "benefit_bonus_score": "FLOAT NOT NULL DEFAULT 0",
        "benefit_condition_penalty": "FLOAT NOT NULL DEFAULT 0",
        "benefit_score_cached": "FLOAT NOT NULL DEFAULT 20",
        "benefit_preprocessed_at": "TIMESTAMP",
        "benefit_needs_review": "BOOLEAN NOT NULL DEFAULT FALSE",
        "benefit_review_note": "TEXT NOT NULL DEFAULT ''",
    }
    for column_name, column_definition in optional_partnership_columns.items():
        if column_name not in partnership_columns:
            with engine.begin() as connection:
                connection.execute(text(f"ALTER TABLE partnerships ADD COLUMN {column_name} {column_definition}"))
    restaurant_columns = {column["name"] for column in inspector.get_columns("restaurants")}
    for column_name, column_definition in {
        "bayesian_satisfaction_score": "FLOAT NOT NULL DEFAULT 60",
        "satisfaction_preprocessed_at": "TIMESTAMP",
    }.items():
        if column_name not in restaurant_columns:
            with engine.begin() as connection:
                connection.execute(text(f"ALTER TABLE restaurants ADD COLUMN {column_name} {column_definition}"))


def _ensure_scoring_rules() -> None:
    """Seed the editable scoring-rule table from the versioned bootstrap JSON once."""
    from app.models import BenefitScoringRule

    config_path = Path(__file__).resolve().parents[1] / "config" / "benefit_scoring_rules.json"
    if not config_path.exists():
        return
    with config_path.open(encoding="utf-8") as stream:
        defaults = json.load(stream)
    with SessionLocal() as db:
        for item in defaults:
            existing = db.scalar(
                select(BenefitScoringRule).where(
                    BenefitScoringRule.rule_type == item["rule_type"],
                    BenefitScoringRule.rule_key == item["rule_key"],
                )
            )
            if existing:
                continue
            db.add(
                BenefitScoringRule(
                    rule_type=item["rule_type"],
                    rule_key=item["rule_key"],
                    label=item["label"],
                    keywords_json=json.dumps(item.get("keywords", []), ensure_ascii=False),
                    min_value=item.get("min_value"),
                    max_value=item.get("max_value"),
                    score=item.get("score", 0),
                    enabled=item.get("enabled", True),
                    sort_order=item.get("sort_order", 0),
                )
            )
        db.commit()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
