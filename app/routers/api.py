from __future__ import annotations

import json
from io import BytesIO
from datetime import date, datetime, timedelta
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload
import httpx

from app.config import get_settings
from app.database import get_db
from app.models import Affiliation, Favorite, Partnership, Report, Restaurant, Review, UsageEvent, User
from app.schemas import AuthSync, RecommendationRequest, ReportCreate, RestaurantDetail, ReviewCreate, UsageEventCreate
from app.services.geocoding import geocode_address
from app.services.import_service import commit_rows, parse_upload, preview_rows
from app.services.recommendation import recommend
from app.security import get_admin_session, verify_password, create_admin_session, revoke_admin_session
from app.schemas import AdminLogin, ImportCommit, PartnershipBulkApprove, PartnershipCreate, PartnershipUpdate, ReportUpdate


router = APIRouter()
admin_router = APIRouter()


def _affiliation_tree(db: Session) -> list[dict]:
    affiliations = db.scalars(select(Affiliation).order_by(Affiliation.type, Affiliation.name)).all()
    by_parent: dict[int | None, list[Affiliation]] = {}
    for affiliation in affiliations:
        by_parent.setdefault(affiliation.parent_id, []).append(affiliation)

    def build(parent_id: int | None) -> list[dict]:
        return [
            {"id": item.id, "name": item.name, "type": item.type, "parent_id": item.parent_id, "children": build(item.id)}
            for item in by_parent.get(parent_id, [])
        ]

    return build(None)


def _require_admin(request: Request, db: Session) -> None:
    if not get_admin_session(db, request.cookies.get("admin_session")):
        raise HTTPException(status_code=401, detail="관리자 로그인이 필요합니다.")


@router.get("/health")
def health() -> dict:
    return {"ok": True}


def _supabase_profile(access_token: str) -> dict:
    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_anon_key:
        raise HTTPException(status_code=503, detail="Supabase 로그인 설정이 아직 없습니다.")
    endpoint = f"{settings.supabase_url.rstrip('/')}/auth/v1/user"
    try:
        response = httpx.get(endpoint, headers={"apikey": settings.supabase_anon_key, "Authorization": f"Bearer {access_token}"}, timeout=8)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="로그인 서버에 연결하지 못했습니다.") from exc
    if response.status_code != 200:
        raise HTTPException(status_code=401, detail="로그인 세션이 유효하지 않습니다.")
    return response.json()


def _sync_user(access_token: str, db: Session) -> User:
    profile = _supabase_profile(access_token)
    metadata = profile.get("user_metadata") or {}
    auth_user_id = str(profile.get("id") or "").strip()
    if not auth_user_id:
        raise HTTPException(status_code=401, detail="로그인 사용자 정보를 확인하지 못했습니다.")
    user = db.scalar(select(User).where(User.auth_user_id == auth_user_id))
    if not user:
        user = User(auth_user_id=auth_user_id)
        db.add(user)
    user.email = str(profile.get("email") or "")
    user.name = str(metadata.get("full_name") or metadata.get("name") or user.email.split("@", 1)[0] or "광운대 사용자")
    user.avatar_url = str(metadata.get("avatar_url") or metadata.get("picture") or "")
    user.last_login_at = datetime.utcnow()
    db.commit()
    db.refresh(user)
    return user


@router.get("/auth/config")
def auth_config() -> dict:
    settings = get_settings()
    return {"enabled": bool(settings.supabase_url and settings.supabase_anon_key), "supabase_url": settings.supabase_url, "supabase_anon_key": settings.supabase_anon_key}


@router.post("/auth/sync")
def auth_sync(payload: AuthSync, db: Session = Depends(get_db)) -> dict:
    user = _sync_user(payload.access_token, db)
    return {"ok": True, "user": {"id": user.id, "email": user.email, "name": user.name, "avatar_url": user.avatar_url}}


def _access_token(request: Request) -> str:
    authorization = request.headers.get("authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    return token.strip()


@router.get("/favorites")
def favorites(request: Request, db: Session = Depends(get_db)) -> dict:
    user = _sync_user(_access_token(request), db)
    rows = db.scalars(select(Favorite).options(joinedload(Favorite.restaurant)).where(Favorite.user_id == user.id).order_by(Favorite.created_at.desc())).all()
    return {"items": [{"restaurant_id": row.restaurant_id, "name": row.restaurant.name} for row in rows]}


@router.post("/favorites/{restaurant_id}")
def add_favorite(restaurant_id: int, request: Request, db: Session = Depends(get_db)) -> dict:
    user = _sync_user(_access_token(request), db)
    if not db.get(Restaurant, restaurant_id):
        raise HTTPException(status_code=404, detail="업체를 찾을 수 없습니다.")
    if not db.scalar(select(Favorite).where(Favorite.user_id == user.id, Favorite.restaurant_id == restaurant_id)):
        db.add(Favorite(user_id=user.id, restaurant_id=restaurant_id))
        db.commit()
    return {"ok": True}


@router.delete("/favorites/{restaurant_id}")
def remove_favorite(restaurant_id: int, request: Request, db: Session = Depends(get_db)) -> dict:
    user = _sync_user(_access_token(request), db)
    favorite = db.scalar(select(Favorite).where(Favorite.user_id == user.id, Favorite.restaurant_id == restaurant_id))
    if favorite:
        db.delete(favorite)
        db.commit()
    return {"ok": True}


@router.get("/affiliations")
def affiliations(db: Session = Depends(get_db)) -> list[dict]:
    return _affiliation_tree(db)


@router.get("/restaurants")
def restaurants(category: str | None = None, db: Session = Depends(get_db)) -> list[dict]:
    query = select(Restaurant).where(Restaurant.status == "active").order_by(Restaurant.name)
    if category and category != "전체":
        query = query.where(Restaurant.category == category)
    return [{"id": r.id, "name": r.name, "category": r.category, "latitude": r.latitude, "longitude": r.longitude, "rating_average": r.rating_average, "review_count": r.review_count} for r in db.scalars(query).all()]


@router.get("/restaurants/{restaurant_id}", response_model=RestaurantDetail)
def restaurant_detail(restaurant_id: int, db: Session = Depends(get_db)) -> RestaurantDetail:
    restaurant = db.scalar(select(Restaurant).options(joinedload(Restaurant.partnerships).joinedload(Partnership.affiliation), joinedload(Restaurant.reviews)).where(Restaurant.id == restaurant_id))
    if not restaurant:
        raise HTTPException(status_code=404, detail="업체를 찾을 수 없습니다.")
    partnerships = [
        {"id": p.id, "affiliation": p.affiliation.name, "benefit_label": f"{p.discount_rate:g}% 할인" if p.discount_rate else (f"{p.fixed_discount:,}원 할인" if p.fixed_discount else f"{p.service_item} 제공"), "application_scope": p.application_scope, "start_date": p.start_date, "end_date": p.end_date, "verification_method": p.verification_method, "status": p.status}
        for p in restaurant.partnerships
    ]
    reviews = [{"id": r.id, "rating": r.rating, "content": r.content, "author_name": r.author_name, "admin_reply": r.admin_reply, "created_at": r.created_at} for r in restaurant.reviews if not r.is_hidden]
    return RestaurantDetail(id=restaurant.id, name=restaurant.name, category=restaurant.category, address=restaurant.address, latitude=restaurant.latitude, longitude=restaurant.longitude, phone=restaurant.phone, opening_hours=restaurant.opening_hours, menu_summary=restaurant.menu_summary, image_url=restaurant.image_url, rating_average=restaurant.rating_average, review_count=restaurant.review_count, partnerships=partnerships, reviews=reviews)


@router.post("/recommendations")
def recommendations(payload: RecommendationRequest, db: Session = Depends(get_db)) -> dict:
    restaurants_list = db.scalars(select(Restaurant).options(joinedload(Restaurant.partnerships))).unique().all()
    affiliations_list = db.scalars(select(Affiliation)).all()
    results = recommend(payload, restaurants_list, affiliations_list)
    return {"results": results, "used_default_location": payload.location.source == "campus_default", "location": payload.location.model_dump()}


@router.post("/reviews")
def create_review(payload: ReviewCreate, db: Session = Depends(get_db)) -> dict:
    restaurant = db.get(Restaurant, payload.restaurant_id)
    if not restaurant:
        raise HTTPException(status_code=404, detail="업체를 찾을 수 없습니다.")
    review = Review(**payload.model_dump())
    db.add(review)
    db.flush()
    reviews = db.scalars(select(Review).where(Review.restaurant_id == restaurant.id, Review.is_hidden.is_(False))).all()
    restaurant.review_count = len(reviews)
    restaurant.rating_average = round(sum(item.rating for item in reviews) / len(reviews), 2) if reviews else 0
    db.commit()
    return {"ok": True, "review_id": review.id}


@router.post("/reports")
def create_report(payload: ReportCreate, db: Session = Depends(get_db)) -> dict:
    if not db.get(Restaurant, payload.restaurant_id):
        raise HTTPException(status_code=404, detail="업체를 찾을 수 없습니다.")
    report = Report(**payload.model_dump())
    db.add(report)
    db.commit()
    return {"ok": True, "report_id": report.id}


@router.post("/usage-events")
def usage_event(payload: UsageEventCreate, db: Session = Depends(get_db)) -> dict:
    event = UsageEvent(restaurant_id=payload.restaurant_id, event_type=payload.event_type, metadata_json=json.dumps(payload.metadata, ensure_ascii=False))
    db.add(event)
    db.commit()
    return {"ok": True}


@router.get("/geocode")
async def geocode(q: str) -> dict:
    result = await geocode_address(q)
    if not result:
        raise HTTPException(status_code=404, detail="Geocoding API 키가 없거나 주소를 찾지 못했습니다. 지도의 좌표를 직접 입력해 주세요.")
    return result


@admin_router.post("/login")
def admin_login(payload: AdminLogin, response: Response, db: Session = Depends(get_db)) -> dict:
    settings = get_settings()
    if not settings.admin_password_hash or not verify_password(payload.password, settings.admin_password_hash):
        raise HTTPException(status_code=401, detail="관리자 비밀번호가 올바르지 않습니다.")
    cookie = create_admin_session(db)
    response.set_cookie("admin_session", cookie, httponly=True, samesite="lax", max_age=settings.admin_session_days * 86400)
    return {"ok": True}


@admin_router.post("/logout")
def admin_logout(request: Request, response, db: Session = Depends(get_db)) -> dict:
    revoke_admin_session(db, request.cookies.get("admin_session"))
    response.delete_cookie("admin_session")
    return {"ok": True}


@admin_router.get("/dashboard")
def admin_dashboard(request: Request, db: Session = Depends(get_db)) -> dict:
    _require_admin(request, db)
    today = date.today()
    active_count = db.scalar(select(func.count(Partnership.id)).where(Partnership.status == "active", Partnership.start_date <= today, Partnership.end_date >= today)) or 0
    pending_count = db.scalar(select(func.count(Partnership.id)).where(Partnership.status == "pending")) or 0
    expiring_count = db.scalar(select(func.count(Partnership.id)).where(Partnership.status == "active", Partnership.end_date >= today, Partnership.end_date <= today + timedelta(days=30))) or 0
    views = db.scalar(select(func.count(UsageEvent.id)).where(UsageEvent.event_type == "view")) or 0
    usages = db.scalar(select(func.count(UsageEvent.id)).where(UsageEvent.event_type == "verified_use")) or 0
    avg_rating = db.scalar(select(func.avg(Restaurant.rating_average)).where(Restaurant.review_count > 0)) or 0
    open_reports = db.scalar(select(func.count(Report.id)).where(Report.status == "open")) or 0
    trend = []
    for offset in range(6, -1, -1):
        target = today - timedelta(days=offset)
        start = datetime.combine(target, datetime.min.time())
        end = start + timedelta(days=1)
        trend.append({"date": target.isoformat(), "views": db.scalar(select(func.count(UsageEvent.id)).where(UsageEvent.event_type == "view", UsageEvent.created_at >= start, UsageEvent.created_at < end)) or 0, "uses": db.scalar(select(func.count(UsageEvent.id)).where(UsageEvent.event_type == "verified_use", UsageEvent.created_at >= start, UsageEvent.created_at < end)) or 0})
    return {"active_partnerships": active_count, "pending_partnerships": pending_count, "expiring_partnerships": expiring_count, "views": views, "verified_uses": usages, "average_rating": round(float(avg_rating), 2), "open_reports": open_reports, "trend": trend}


def _partnership_row(partnership: Partnership) -> dict:
    return {"id": partnership.id, "restaurant_id": partnership.restaurant_id, "restaurant_name": partnership.restaurant.name, "category": partnership.restaurant.category, "affiliation": partnership.affiliation.name, "affiliation_id": partnership.affiliation_id, "benefit_type": partnership.benefit_type, "discount_rate": partnership.discount_rate, "fixed_discount": partnership.fixed_discount, "service_item": partnership.service_item, "estimated_cash_value": partnership.estimated_cash_value, "min_order_amount": partnership.min_order_amount, "min_people": partnership.min_people, "payment_method": partnership.payment_method, "application_scope": partnership.application_scope, "verification_method": partnership.verification_method, "start_date": partnership.start_date, "end_date": partnership.end_date, "status": partnership.status, "address": partnership.restaurant.address, "latitude": partnership.restaurant.latitude, "longitude": partnership.restaurant.longitude}


@admin_router.get("/partnerships")
def admin_partnerships(request: Request, status: str | None = None, search: str | None = None, db: Session = Depends(get_db)) -> dict:
    _require_admin(request, db)
    query = select(Partnership).options(joinedload(Partnership.restaurant), joinedload(Partnership.affiliation)).order_by(Partnership.id.desc())
    if status and status != "all":
        query = query.where(Partnership.status == status)
    rows = db.scalars(query).all()
    if search:
        rows = [row for row in rows if search.lower() in row.restaurant.name.lower()]
    return {"items": [_partnership_row(row) for row in rows]}


@admin_router.get("/partnerships/export")
def export_partnerships(request: Request, db: Session = Depends(get_db)):
    _require_admin(request, db)
    rows = admin_partnerships(request, db=db)["items"]
    headers = ["id", "restaurant_name", "category", "affiliation", "benefit_type", "discount_rate", "fixed_discount", "start_date", "end_date", "status"]
    lines = [",".join(headers)] + [",".join(str(row.get(header, "")).replace(",", " ") for header in headers) for row in rows]
    content = "\ufeff" + "\n".join(lines)
    return StreamingResponse(iter([content]), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=partnerships.csv"})


@admin_router.post("/partnerships/bulk-approve")
def bulk_approve_partnerships(payload: PartnershipBulkApprove, request: Request, db: Session = Depends(get_db)) -> dict:
    _require_admin(request, db)
    requested_ids = list(dict.fromkeys(payload.partnership_ids))
    partnerships = db.scalars(select(Partnership).where(Partnership.id.in_(requested_ids))).all()
    found_ids = {partnership.id for partnership in partnerships}
    approved_ids: list[int] = []
    skipped_ids = [partnership_id for partnership_id in requested_ids if partnership_id not in found_ids]
    for partnership in partnerships:
        if partnership.status == "pending":
            partnership.status = "active"
            approved_ids.append(partnership.id)
        else:
            skipped_ids.append(partnership.id)
    db.commit()
    return {
        "ok": True,
        "approved": len(approved_ids),
        "skipped": len(skipped_ids),
        "approved_ids": approved_ids,
        "skipped_ids": skipped_ids,
    }


@admin_router.post("/partnerships")
def create_partnership(payload: PartnershipCreate, request: Request, db: Session = Depends(get_db)) -> dict:
    _require_admin(request, db)
    if payload.restaurant_id:
        restaurant = db.get(Restaurant, payload.restaurant_id)
        if not restaurant:
            raise HTTPException(status_code=404, detail="업체를 찾을 수 없습니다.")
    else:
        restaurant = Restaurant(name=payload.restaurant_name, category=payload.category, address=payload.address, latitude=payload.latitude, longitude=payload.longitude, phone=payload.phone, opening_hours=payload.opening_hours, menu_summary=payload.menu_summary, image_url=payload.image_url, status="active")
        db.add(restaurant)
        db.flush()
    created = []
    for affiliation_id in payload.affiliation_ids:
        if not db.get(Affiliation, affiliation_id):
            raise HTTPException(status_code=400, detail=f"소속 ID {affiliation_id}를 찾을 수 없습니다.")
        partnership = Partnership(restaurant_id=restaurant.id, affiliation_id=affiliation_id, benefit_type=payload.benefit_type, discount_rate=payload.discount_rate, fixed_discount=payload.fixed_discount, service_item=payload.service_item, estimated_cash_value=payload.estimated_cash_value, min_order_amount=payload.min_order_amount, min_people=payload.min_people, payment_method=payload.payment_method, application_scope=payload.application_scope, verification_method=payload.verification_method, eligibility_description=payload.eligibility_description, start_date=payload.start_date, end_date=payload.end_date, status=payload.status, source=payload.source)
        db.add(partnership)
        created.append(partnership)
    db.commit()
    return {"ok": True, "partnership_ids": [item.id for item in created]}


@admin_router.put("/partnerships/{partnership_id}")
def update_partnership(partnership_id: int, payload: PartnershipUpdate, request: Request, db: Session = Depends(get_db)) -> dict:
    _require_admin(request, db)
    partnership = db.get(Partnership, partnership_id)
    if not partnership:
        raise HTTPException(status_code=404, detail="제휴를 찾을 수 없습니다.")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(partnership, key, value)
    db.commit()
    return {"ok": True}


@admin_router.delete("/partnerships/{partnership_id}")
def delete_partnership(partnership_id: int, request: Request, db: Session = Depends(get_db)) -> dict:
    _require_admin(request, db)
    partnership = db.get(Partnership, partnership_id)
    if not partnership:
        raise HTTPException(status_code=404, detail="제휴를 찾을 수 없습니다.")
    partnership.status = "ended"
    db.commit()
    return {"ok": True}


@admin_router.post("/import/preview")
async def import_preview(request: Request, file: UploadFile = File(...), db: Session = Depends(get_db)) -> dict:
    _require_admin(request, db)
    content = await file.read()
    try:
        rows = parse_upload(file.filename or "upload.csv", content)
        result = preview_rows(db, rows)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"파일을 읽지 못했습니다: {exc}") from exc
    result["filename"] = file.filename
    return result


@admin_router.get("/import/template")
def import_template(request: Request, db: Session = Depends(get_db)):
    _require_admin(request, db)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "제휴등록"
    headers = ["가게명", "카테고리", "주소", "위도", "경도", "제휴대상", "혜택", "시작일", "종료일"]
    example = ["예시식당", "식사류", "서울 노원구 광운로 20", 37.6199, 127.0598, "전자공학과", "10% 할인", "2026-01-01", "2026-12-31"]
    sheet.append(headers)
    sheet.append(example)
    sheet.freeze_panes = "A2"
    widths = [20, 16, 32, 12, 12, 30, 28, 14, 14]
    for index, width in enumerate(widths, start=1):
        sheet.column_dimensions[chr(64 + index)].width = width
    guide = workbook.create_sheet("작성안내")
    guide.append(["항목", "작성 방법"])
    guide_rows = [
        ("가게명", "필수. 식당 이름"),
        ("카테고리", "식사류 / 카페/디저트 / 주점 / 기타"),
        ("주소", "도로명 주소"),
        ("위도·경도", "지도 좌표. 모르면 관리자에서 직접 확인"),
        ("제휴대상", "학과·단과대·광운대학교 이름. 여러 개는 쉼표로 구분"),
        ("혜택", "예: 10% 할인, 2,000원 할인, 음료 1잔 제공"),
        ("시작일·종료일", "YYYY-MM-DD 형식"),
    ]
    for row in guide_rows:
        guide.append(row)
    guide.column_dimensions["A"].width = 22
    guide.column_dimensions["B"].width = 70
    output = BytesIO()
    workbook.save(output)
    download_name = quote("광운대 제휴정보 일괄등록용.xlsx")
    return Response(content=output.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f"attachment; filename*=UTF-8''{download_name}"})


@admin_router.post("/import/commit")
def import_commit(payload: ImportCommit, request: Request, db: Session = Depends(get_db)) -> dict:
    _require_admin(request, db)
    return commit_rows(db, payload.rows)


@admin_router.get("/analytics")
def analytics(request: Request, db: Session = Depends(get_db)) -> dict:
    _require_admin(request, db)
    rows = db.execute(select(Restaurant.name, func.count(UsageEvent.id)).join(UsageEvent, UsageEvent.restaurant_id == Restaurant.id, isouter=True).group_by(Restaurant.id).order_by(func.count(UsageEvent.id).desc()).limit(10)).all()
    return {"top_restaurants": [{"name": name, "events": count} for name, count in rows]}


@admin_router.get("/reports")
def admin_reports(request: Request, db: Session = Depends(get_db)) -> dict:
    _require_admin(request, db)
    rows = db.scalars(select(Report).options(joinedload(Report.restaurant)).order_by(Report.created_at.desc())).all()
    return {"items": [{"id": row.id, "restaurant_id": row.restaurant_id, "restaurant_name": row.restaurant.name, "report_type": row.report_type, "content": row.content, "status": row.status, "created_at": row.created_at} for row in rows]}


@admin_router.put("/reports/{report_id}")
def update_report(report_id: int, payload: ReportUpdate, request: Request, db: Session = Depends(get_db)) -> dict:
    _require_admin(request, db)
    report = db.get(Report, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="신고를 찾을 수 없습니다.")
    report.status = payload.status
    db.commit()
    return {"ok": True}
