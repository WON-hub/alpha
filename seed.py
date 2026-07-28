from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import SessionLocal, init_db
from app.models import Affiliation, Partnership, Restaurant


COLLEGE_DEPARTMENTS = {
    "전자정보공과대학": ["전자공학과", "전자통신공학과", "전자융합공학과", "전기공학과", "전자재료공학과", "반도체시스템공학부"],
    "인공지능융합대학": ["컴퓨터정보공학부", "소프트웨어학부", "정보융합학부", "로봇학부", "지능형로봇학과"],
    "공과대학": ["건축학과", "건축공학과", "화학공학과", "환경공학과"],
    "자연과학대학": ["수학과", "전자바이오물리학과", "화학과", "스포츠융합과학과"],
    "인문사회과학대학": ["국어국문학과", "영어산업학과", "미디어커뮤니케이션학부", "산업심리학과", "동북아문화산업학부"],
    "정책법학대학": ["행정학과", "법학부", "국제학부", "자산관리학과"],
    "경영대학": ["경영학부", "국제통상학부"],
    "참빛인재대학": ["금융부동산법무학과", "게임콘텐츠학과", "스마트전기전자학과", "스포츠상담재활학과"],
    "인제니움대학": ["자율전공학부"],
}


RESTAURANT_NAMES = [
    ("광운국수", "식사류"), ("캠퍼스김밥", "식사류"), ("골목제육", "식사류"), ("우동마을", "식사류"), ("라이스랩", "식사류"),
    ("초록카페", "카페/디저트"), ("북카페 쉼", "카페/디저트"), ("밀크티하우스", "카페/디저트"), ("베이크온", "카페/디저트"),
    ("운동장펍", "주점"), ("밤마실", "주점"), ("청춘포차", "주점"), ("보드라운지", "기타"), ("클라이밍월", "기타"), ("동네사진관", "기타"),
    ("월계식당", "식사류"), ("광운밥상", "식사류"), ("석계덮밥", "식사류"), ("오늘의샐러드", "식사류"), ("면과밥", "식사류"),
    ("카페 모퉁이", "카페/디저트"), ("라떼정류장", "카페/디저트"), ("디저트연구소", "카페/디저트"), ("커피사이", "카페/디저트"), ("오후네시", "카페/디저트"),
    ("석계포차", "주점"), ("청춘호프", "주점"), ("소소한술집", "주점"), ("게임스팟", "기타"), ("사진공방", "기타"),
]


def _affiliation(db: Session, name: str, type_: str, parent_id: int | None = None) -> Affiliation:
    row = db.scalar(select(Affiliation).where(Affiliation.name == name, Affiliation.type == type_))
    if not row:
        row = Affiliation(name=name, type=type_, parent_id=parent_id)
        db.add(row)
        db.flush()
    elif parent_id is not None and row.parent_id != parent_id:
        # Reconcile the old MVP's flat college rows with the new hierarchy.
        row.parent_id = parent_id
        db.flush()
    return row


def _demo_partnership(db: Session, restaurant: Restaurant, target: Affiliation, index: int, today: date) -> None:
    start_date = today - timedelta(days=30)
    if db.scalar(select(Partnership.id).where(Partnership.restaurant_id == restaurant.id, Partnership.affiliation_id == target.id, Partnership.start_date == start_date)):
        return
    kind = index % 4
    if kind == 0:
        benefit_type, rate, fixed, service, value = "percentage", 10 + (index % 3) * 5, 0, "", 0
    elif kind == 1:
        benefit_type, rate, fixed, service, value = "fixed", 0, 2000 + (index % 2) * 1000, "", 0
    elif kind == 2:
        benefit_type, rate, fixed, service, value = "service", 0, 0, "음료 1잔", 3500
    else:
        benefit_type, rate, fixed, service, value = "percentage", 10, 0, "", 0
    db.add(Partnership(
        restaurant_id=restaurant.id,
        affiliation_id=target.id,
        benefit_type=benefit_type,
        discount_rate=rate,
        fixed_discount=fixed,
        service_item=service,
        estimated_cash_value=value,
        min_order_amount=20_000 if index % 5 == 0 else 0,
        min_people=2 if index % 6 == 0 else 1,
        payment_method="" if index % 3 else "카드",
        application_scope="ELIGIBLE_MEMBERS_ONLY" if index % 4 == 1 else "ALL_GROUP",
        verification_method="학생증 또는 모바일 학생증",
        eligibility_description=f"{target.name} 학생 대상 DEMO 제휴입니다.",
        start_date=start_date,
        end_date=today + timedelta(days=10 if index == 11 else 180),
        status="active",
        source="DEMO",
    ))


def _move_partnerships(db: Session, old: Affiliation, new: Affiliation) -> None:
    for partnership in db.scalars(select(Partnership).where(Partnership.affiliation_id == old.id)).all():
        duplicate = db.scalar(select(Partnership.id).where(Partnership.restaurant_id == partnership.restaurant_id, Partnership.affiliation_id == new.id, Partnership.start_date == partnership.start_date, Partnership.id != partnership.id))
        if duplicate:
            partnership.status = "ended"
        else:
            partnership.affiliation_id = new.id


def _reconcile_legacy_affiliations(db: Session, university: Affiliation, colleges: dict[str, Affiliation], departments: dict[str, Affiliation]) -> None:
    legacy_universities = db.scalars(select(Affiliation).where(Affiliation.type == "university", Affiliation.id != university.id)).all()
    for legacy in legacy_universities:
        _move_partnerships(db, legacy, university)
        for child in db.scalars(select(Affiliation).where(Affiliation.parent_id == legacy.id)).all():
            child.parent_id = university.id
        db.delete(legacy)

    replacements = {
        ("정책법학대학", "법학과"): "법학부",
        ("인공지능융합대학", "AI전공"): "컴퓨터정보공학부",
    }
    for (college_name, old_name), new_name in replacements.items():
        old = db.scalar(select(Affiliation).where(Affiliation.name == old_name, Affiliation.parent_id == colleges[college_name].id))
        if old:
            _move_partnerships(db, old, departments[new_name])
            db.delete(old)
    db.flush()


def seed_database(db: Session) -> None:
    today = date.today()
    university = db.scalar(select(Affiliation).where(Affiliation.name == "광운대학교", Affiliation.type == "university"))
    if not university:
        legacy_university = db.scalar(select(Affiliation).where(Affiliation.type == "university", Affiliation.name.like("%광운대학교%")))
        if legacy_university:
            legacy_university.name = "광운대학교"
            university = legacy_university
            db.flush()
        else:
            university = _affiliation(db, "광운대학교", "university")
    colleges: list[Affiliation] = []
    colleges_by_name: dict[str, Affiliation] = {}
    departments: list[Affiliation] = []
    departments_by_name: dict[str, Affiliation] = {}
    for college_name, department_names in COLLEGE_DEPARTMENTS.items():
        college = _affiliation(db, college_name, "college", university.id)
        colleges.append(college)
        colleges_by_name[college_name] = college
        for department_name in department_names:
            department = _affiliation(db, department_name, "department", college.id)
            departments.append(department)
            departments_by_name[department_name] = department
    db.flush()
    _reconcile_legacy_affiliations(db, university, colleges_by_name, departments_by_name)

    for index, (name, category) in enumerate(RESTAURANT_NAMES):
        full_name = f"DEMO {name}"
        restaurant = db.scalar(select(Restaurant).where(Restaurant.name == full_name))
        if not restaurant:
            row = index // 5
            restaurant = Restaurant(
                name=full_name,
                category=category,
                address=f"서울 노원구 광운로 {20 + index}",
                latitude=37.6158 + (index % 8) * 0.00105,
                longitude=127.0568 + (index % 7) * 0.00105,
                phone=f"02-0000-{1000 + index:04d}",
                opening_hours="11:00–22:00" if category != "주점" else "17:00–02:00",
                menu_summary="학생 추천 메뉴 · DEMO 샘플 데이터",
                rating_average=round(4.0 + (index % 9) / 10, 1) if index % 6 else 0,
                review_count=0 if index % 6 == 0 else 3 + index % 8,
                status="active",
            )
            db.add(restaurant)
            db.flush()
        _demo_partnership(db, restaurant, departments[index % len(departments)], index, today)
        _demo_partnership(db, restaurant, colleges[(index + 3) % len(colleges)], index + 1, today)
        if index % 5 == 0:
            _demo_partnership(db, restaurant, university, index + 2, today)

    db.commit()
    db.close()


if __name__ == "__main__":
    init_db()
    seed_database(SessionLocal())
    print("DEMO sample data seeded.")
