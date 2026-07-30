from __future__ import annotations

import io
import json
import math
import re
from datetime import date, datetime
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.services.ai import AIConfigurationError, AIServiceError, analyze_benefit, generate_store_summary
from app.models import Affiliation, ImportBatch, Partnership, Restaurant
from app.services.places import PlaceSearchConfigurationError, PlaceSearchError, resolve_place
from app.services.recommendation import benefit_score_components
from app.services.scoring_rules import load_scoring_rules


COLUMN_ALIASES = {
    "college": "college",
    "단과대": "college",
    "department": "department",
    "학과": "department",
    "category": "category",
    "카테고리": "category",
    "업종": "category",
    "분류": "category",
    "restaurant_name": "restaurant_name",
    "가게명": "restaurant_name",
    "업체명": "restaurant_name",
    "상호명": "restaurant_name",
    "상호": "restaurant_name",
    "name": "restaurant_name",
    "address": "address",
    "주소": "address",
    "위치": "address",
    "phone": "phone",
    "전화번호": "phone",
    "eligibility": "eligibility",
    "할인조건": "eligibility",
    "할인조건_상세": "eligibility_detail",
    "할인조건상세": "eligibility_detail",
    "제휴_대상_조건": "eligibility",
    "제휴대상조건": "eligibility",
    "제휴대상": "target_affiliations",
    "target_affiliations": "target_affiliations",
    "혜택": "benefit_text",
    "혜택_내용": "benefit_text",
    "혜택내용": "benefit_text",
    "benefit_type": "benefit_type",
    "혜택유형": "benefit_type",
    "혜택_분류": "benefit_type",
    "혜택분류": "benefit_type",
    "제휴_혜택": "benefit_type",
    "제휴혜택": "benefit_type",
    "제휴_혜택_상세": "benefit_detail",
    "제휴혜택상세": "benefit_detail",
    "discount_rate": "discount_rate",
    "할인율": "discount_rate",
    "fixed_discount": "fixed_discount",
    "정액할인": "fixed_discount",
    "service_item": "service_item",
    "서비스품목": "service_item",
    "서비스_혜택": "service_item",
    "서비스혜택": "service_item",
    "estimated_cash_value": "estimated_cash_value",
    "min_order_amount": "min_order_amount",
    "min_people": "min_people",
    "payment_method": "payment_method",
    "결제_조건": "payment_method",
    "결제조건": "payment_method",
    "application_scope": "application_scope",
    "verification_method": "verification_method",
    "start_date": "start_date",
    "시작일": "start_date",
    "end_date": "end_date",
    "종료일": "end_date",
    "partnership_period": "partnership_period",
    "제휴기간": "partnership_period",
    "제휴_기간": "partnership_period",
    "notes": "notes",
    "비고": "notes",
    "latitude": "latitude",
    "위도": "latitude",
    "longitude": "longitude",
    "경도": "longitude",
}


def _normalise_key(key: Any) -> str:
    return str(key).strip().lower().replace(" ", "_")


def _date_or_none(value: Any) -> date | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date()


def _split_targets(value: Any) -> list[str]:
    return [part.strip() for part in re.split(r"[,/\n]+", str(value or "")) if part.strip()]


def _benefit_fields(value: Any) -> dict[str, Any]:
    text = str(value or "").strip()
    rate = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
    fixed = re.search(r"([\d,]+)\s*원\s*할인", text)
    if rate:
        return {"benefit_type": "percentage", "discount_rate": float(rate.group(1))}
    if fixed:
        return {"benefit_type": "fixed", "fixed_discount": int(fixed.group(1).replace(",", ""))}
    if text:
        return {"benefit_type": "service", "service_item": text, "estimated_cash_value": 0}
    return {}


def _find_header_row(raw: pd.DataFrame) -> int:
    header_tokens = {
        "가게명", "상호", "상호명", "업체명", "restaurant_name", "혜택_내용", "혜택내용",
        "단과대", "분류", "제휴_혜택", "제휴혜택", "제휴기간", "제휴_기간", "category",
    }
    best_index = 0
    best_score = 0
    for index, values in raw.iterrows():
        cells = {_normalise_key(value) for value in values.tolist() if str(value).strip() and str(value) != "nan"}
        score = len(cells & header_tokens)
        if score > best_score:
            best_index, best_score = int(index), score
    return best_index if best_score >= 2 else 0


def _read_upload_frame(suffix: str, content: bytes) -> pd.DataFrame:
    if suffix in {"xlsx", "xls", "xlsm"}:
        raw = pd.read_excel(io.BytesIO(content), header=None)
        header_index = _find_header_row(raw)
        headers = ["" if pd.isna(value) else str(value).strip() for value in raw.iloc[header_index].tolist()]
        frame = raw.iloc[header_index + 1:].copy()
        frame.columns = headers
    elif suffix == "txt":
        frame = pd.read_csv(io.BytesIO(content), sep=None, engine="python")
    else:
        frame = pd.read_csv(io.BytesIO(content))
    return frame.dropna(axis=0, how="all").dropna(axis=1, how="all")


def _normalise_category(value: Any) -> str:
    text = str(value or "").strip()
    compact = text.replace(" ", "")
    if any(word in compact for word in ("카페", "디저트", "베이커리", "와플", "츄러스", "커피")):
        return "카페/디저트"
    if any(word in compact for word in ("주점", "포차", "펍", "맥주", "술집")):
        return "주점"
    if any(word in compact for word in ("식사", "음식", "식당", "한식", "중식", "일식", "치킨", "부대찌개", "연어")):
        return "식사류"
    return text or "기타"


def _period_dates(value: Any) -> tuple[date | None, date | None]:
    text = str(value or "")
    matches = re.findall(r"(20\d{2})\s*[.\-/년]\s*(\d{1,2})\s*[.\-/월]\s*(\d{1,2})", text)
    parsed = [date(int(year), int(month), int(day)) for year, month, day in matches]
    if len(parsed) >= 2:
        return parsed[0], parsed[1]
    if len(parsed) == 1:
        return parsed[0], None
    return None, None


def _join_values(row: dict[str, Any], keys: tuple[str, ...]) -> str:
    values: list[str] = []
    for key in keys:
        value = str(row.get(key) or "").strip()
        if value and value not in values:
            values.append(value)
    return " · ".join(values)


def _normalise_import_row(raw: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    row = {str(key): value for key, value in raw.items()}
    row["restaurant_name"] = str(row.get("restaurant_name") or row.get("name") or "").strip()
    row["category"] = _normalise_category(row.get("category"))
    row["target_affiliations"] = str(row.get("target_affiliations") or row.get("college") or "전체").strip()
    row["address"] = str(row.get("address") or "").strip()

    row["benefit_text"] = _join_values(
        row,
        (
            "benefit_text", "benefit_type", "benefit_detail", "service_item", "eligibility",
            "eligibility_detail", "payment_method", "notes",
        ),
    )

    start_date = _date_or_none(row.get("start_date"))
    end_date = _date_or_none(row.get("end_date"))
    period_start, period_end = _period_dates(row.get("partnership_period"))
    start_date = start_date or period_start
    end_date = end_date or period_end
    if start_date is None:
        start_date = date(2026, 1, 1)
        row["_period_fallback"] = True
    if end_date is None:
        end_date = date(2026, 12, 31)
        row["_period_fallback"] = True
    row["start_date"], row["end_date"] = start_date, end_date

    if row.get("discount_rate") not in (None, ""):
        try:
            rate = float(str(row["discount_rate"]).replace("%", "").strip())
            row["discount_rate"] = rate * 100 if 0 < rate <= 1 else rate
        except ValueError:
            row["discount_rate"] = ""
    if row.get("latitude") in (None, "") or row.get("longitude") in (None, ""):
        row["_coordinate_missing"] = True
    return row


def _valid_coordinate(value: Any, minimum: float, maximum: float) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number) and minimum <= number <= maximum and number != 0


def _has_coordinates(row: dict[str, Any]) -> bool:
    return _valid_coordinate(row.get("latitude"), -90, 90) and _valid_coordinate(row.get("longitude"), -180, 180)


def parse_upload(filename: str, content: bytes) -> list[dict[str, Any]]:
    suffix = filename.lower().rsplit(".", 1)[-1] if "." in filename else "csv"
    frame = _read_upload_frame(suffix, content)
    frame = frame.rename(columns={column: COLUMN_ALIASES.get(_normalise_key(column), _normalise_key(column)) for column in frame.columns})
    records = frame.astype(object).where(pd.notna(frame), "").to_dict(orient="records")
    return [_normalise_import_row(row) for row in records]


async def enrich_missing_coordinates(db: Session, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fill missing import coordinates from the DB or Kakao/Google place search once per store."""
    resolved_cache: dict[str, dict[str, Any] | None] = {}
    for index, raw in enumerate(rows):
        row = _normalise_import_row(raw)
        if _has_coordinates(row):
            rows[index] = row
            continue

        name = str(row.get("restaurant_name") or "").strip()
        address = str(row.get("address") or "").strip()
        if not name:
            rows[index] = row
            continue
        cache_key = f"{name.casefold()}|{address.casefold()}"
        if cache_key not in resolved_cache:
            existing = db.scalar(select(Restaurant).where(Restaurant.name == name))
            if existing and _has_coordinates({"latitude": existing.latitude, "longitude": existing.longitude}):
                resolved_cache[cache_key] = {
                    "latitude": existing.latitude,
                    "longitude": existing.longitude,
                    "address": existing.address,
                    "phone": existing.phone,
                    "place_id": existing.place_id,
                    "place_provider": existing.place_provider,
                }
            else:
                try:
                    resolved_cache[cache_key] = await resolve_place(name, address)
                except (PlaceSearchConfigurationError, PlaceSearchError) as exc:
                    row["_coordinate_error"] = str(exc)
                    resolved_cache[cache_key] = None

        selected = resolved_cache[cache_key]
        if selected:
            row["latitude"] = selected.get("latitude")
            row["longitude"] = selected.get("longitude")
            if not row.get("address"):
                row["address"] = selected.get("address") or ""
            if not row.get("phone"):
                row["phone"] = selected.get("phone") or ""
            row["place_id"] = selected.get("place_id") or ""
            row["place_provider"] = selected.get("place_provider") or ""
            row["_coordinate_autofilled"] = True
            row.pop("_coordinate_error", None)
        elif not row.get("_coordinate_error"):
            row["_coordinate_error"] = "장소 검색 결과가 없습니다. 가게명이나 주소를 확인해 주세요."
        rows[index] = row
    return rows


def preview_rows(db: Session, rows: list[dict[str, Any]]) -> dict[str, Any]:
    seen_names: set[str] = set()
    preview: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for index, raw in enumerate(rows, start=2):
        row = _normalise_import_row(raw)
        name = str(row.get("restaurant_name", "")).strip()
        row_errors: list[str] = []
        if not name:
            row_errors.append("restaurant_name 필수")
        duplicate_name = bool(name and name in seen_names)
        if name:
            seen_names.add(name)
        if not row.get("category"):
            row_errors.append("category 필수")
        if not row.get("target_affiliations") and not row.get("department") and not row.get("college"):
            row_errors.append("제휴대상 필수")
        if _date_or_none(row.get("start_date")) is None or _date_or_none(row.get("end_date")) is None:
            row_errors.append("날짜 형식 확인 필요")
        if not _has_coordinates(row):
            row_errors.append(f"좌표 자동 생성 실패: {row.get('_coordinate_error') or '가게명이나 주소를 확인해 주세요.'}")
        warnings: list[str] = []
        if duplicate_name:
            warnings.append("같은 업체명이 반복되어 혜택 행별로 등록합니다")
        if row.get("_coordinate_autofilled"):
            warnings.append("카카오 장소 검색으로 좌표를 자동 입력했습니다")
        if row.get("_period_fallback"):
            warnings.append("기간이 없어 2026-01-01~2026-12-31을 임시 사용합니다")
        parsed = dict(row)
        parsed["start_date"] = _date_or_none(row.get("start_date"))
        parsed["end_date"] = _date_or_none(row.get("end_date"))
        parsed.update({key: value for key, value in _benefit_fields(row.get("benefit_text")).items() if not row.get(key)})
        parsed["errors"] = row_errors
        parsed["warnings"] = warnings
        preview.append(parsed)
        if row_errors:
            errors.append({"row": index, "errors": row_errors})
    return {"rows": preview, "errors": errors, "valid_count": len(rows) - len(errors), "total_count": len(rows)}


def _number(value: Any, default: float = 0) -> float:
    if value in (None, ""):
        return default
    try:
        return float(str(value).replace(",", "").replace("%", "").strip())
    except (TypeError, ValueError):
        return default


def _apply_import_ai_analysis(partnership: Partnership, analysis: dict[str, Any]) -> None:
    """Apply one normalized benefit analysis to an imported partnership row."""
    rate = analysis.get("discountRate", analysis.get("discount_rate"))
    amount = analysis.get("discountAmount", analysis.get("fixed_discount"))
    free_item = analysis.get("freeItem", analysis.get("service_item", "")) or ""
    minimum_order = analysis.get("minimumOrder", analysis.get("min_order_amount"))
    required_people = analysis.get("requiredPeople", analysis.get("min_people"))
    conditions = analysis.get("conditions") or []
    needs_review = bool(analysis.get("needsReview") or analysis.get("unknownBenefits") or analysis.get("unknownConditions"))

    if rate not in (None, ""):
        partnership.discount_rate = _number(rate)
    if amount not in (None, ""):
        partnership.fixed_discount = int(_number(amount))
    if free_item not in (None, ""):
        partnership.service_item = str(free_item)
    if minimum_order not in (None, ""):
        partnership.min_order_amount = int(_number(minimum_order))
    if required_people not in (None, ""):
        partnership.min_people = max(1, int(_number(required_people, 1)))
    if conditions:
        partnership.eligibility_description = " / ".join(str(item) for item in conditions)
    if analysis.get("studentVerification") and not partnership.verification_method:
        partnership.verification_method = "학생증 제시"
    if rate not in (None, "", 0):
        partnership.benefit_type = "percentage"
    elif amount not in (None, "", 0):
        partnership.benefit_type = "fixed"
    elif free_item:
        partnership.benefit_type = "service"
    partnership.benefit_ai_json = json.dumps(analysis, ensure_ascii=False)
    partnership.benefit_base_score = float(analysis.get("benefitBaseScore", analysis.get("baseScore", 0)) or 0)
    partnership.benefit_bonus_score = float(analysis.get("benefitBonusScore", analysis.get("bonusScore", 0)) or 0)
    partnership.benefit_condition_penalty = float(analysis.get("benefitConditionPenalty", analysis.get("conditionPenalty", 0)) or 0)
    partnership.benefit_needs_review = needs_review
    partnership.benefit_score_cached = 0 if needs_review else float(analysis.get("finalBenefitScore", analysis.get("benefitScore", 0)) or 0)
    partnership.benefit_preprocessed_at = None if needs_review else datetime.utcnow()
    review_items = [*(str(item) for item in analysis.get("unknownBenefits", [])), *(str(item) for item in analysis.get("unknownConditions", []))]
    partnership.benefit_review_note = " / ".join(review_items) if review_items else ("AI 분석 결과 관리자 확인 필요" if needs_review else "")


def commit_rows(db: Session, rows: list[dict[str, Any]], filename: str = "manual") -> dict[str, int]:
    imported = 0
    scoring_rules = load_scoring_rules(db)
    skipped = 0
    for raw in rows:
        row = _normalise_import_row(raw)
        if row.get("errors"):
            skipped += 1
            continue
        start_date = _date_or_none(row.get("start_date"))
        end_date = _date_or_none(row.get("end_date"))
        if not start_date or not end_date or end_date < start_date:
            skipped += 1
            continue
        if not _has_coordinates(row):
            skipped += 1
            continue
        affiliation_ids: list[int] = []
        labels = _split_targets(row.get("target_affiliations"))
        labels.extend([str(row.get(key, "")).strip() for key in ("department", "college") if str(row.get(key, "")).strip()])
        labels = ["전체" if label == get_settings().campus_name else label for label in labels]
        for label in labels:
            affiliation = db.scalar(select(Affiliation).where(Affiliation.name == label))
            if affiliation and affiliation.id not in affiliation_ids:
                affiliation_ids.append(affiliation.id)
        if not affiliation_ids:
            skipped += 1
            continue
        benefit_text_value = str(row.get("benefit_text") or "").strip()
        ai_analysis = None
        if benefit_text_value:
            try:
                # One AI call per imported row; reuse the normalized result for every affiliation.
                ai_analysis = analyze_benefit(benefit_text_value, scoring_rules)
            except (AIConfigurationError, AIServiceError):
                ai_analysis = None
        restaurant = db.scalar(select(Restaurant).where(Restaurant.name == str(row.get("restaurant_name")).strip()))
        if not restaurant:
            restaurant = Restaurant(
                name=str(row.get("restaurant_name")).strip(), category=str(row.get("category") or "기타"),
                address=str(row.get("address") or ""), latitude=_number(row.get("latitude")), longitude=_number(row.get("longitude")),
                phone=str(row.get("phone") or ""), menu_summary=str(row.get("menu_summary") or row.get("notes") or ""), status="active",
            )
            db.add(restaurant)
            db.flush()
        elif not restaurant.menu_summary and row.get("menu_summary"):
            restaurant.menu_summary = str(row.get("menu_summary"))
        if not restaurant.ai_summary:
            try:
                restaurant.ai_summary = generate_store_summary(restaurant.name, restaurant.category, restaurant.menu_summary, restaurant.address)
            except (AIConfigurationError, AIServiceError):
                pass
        benefit = _benefit_fields(row.get("benefit_text"))
        for affiliation_id in affiliation_ids:
            partnership = Partnership(
                restaurant_id=restaurant.id, affiliation_id=affiliation_id,
                benefit_type=str(row.get("benefit_type") or benefit.get("benefit_type") or "discount"), benefit_text=str(row.get("benefit_text") or ""), discount_rate=_number(row.get("discount_rate") or benefit.get("discount_rate")),
                fixed_discount=int(_number(row.get("fixed_discount") or benefit.get("fixed_discount"))), service_item=str(row.get("service_item") or benefit.get("service_item") or ""),
                estimated_cash_value=int(_number(row.get("estimated_cash_value") or benefit.get("estimated_cash_value"))), min_order_amount=int(_number(row.get("min_order_amount"))),
                min_people=int(_number(row.get("min_people"), 1)), payment_method=str(row.get("payment_method") or ""),
                application_scope=str(row.get("application_scope") or "ALL_GROUP"), verification_method=str(row.get("verification_method") or "학생증"),
                eligibility_description=str(row.get("eligibility") or ""), start_date=start_date, end_date=end_date, status="pending", source="import",
            )
            if ai_analysis:
                _apply_import_ai_analysis(partnership, ai_analysis)
            else:
                base, bonus, penalty, _score = benefit_score_components(partnership, scoring_rules)
                partnership.benefit_base_score = base
                partnership.benefit_bonus_score = bonus
                partnership.benefit_condition_penalty = penalty
                partnership.benefit_score_cached = 0
                partnership.benefit_needs_review = True
                partnership.benefit_review_note = "일괄등록 후 AI 혜택 분석 필요"
            db.add(partnership)
        imported += 1
    batch = ImportBatch(filename=filename, status="committed", row_count=len(rows), errors_json=json.dumps([]))
    db.add(batch)
    db.commit()
    return {"imported": imported, "skipped": skipped}
