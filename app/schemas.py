from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AffiliationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    type: str
    parent_id: Optional[int] = None
    children: list["AffiliationOut"] = []


class LocationIn(BaseModel):
    lat: float
    lng: float
    source: str = "campus_default"


class GroupIn(BaseModel):
    affiliation_id: int
    count: int = Field(ge=1, le=50)


class RecommendationRequest(BaseModel):
    location: LocationIn
    category: str = "전체"
    budget_per_person: int = Field(default=12_000, ge=0, le=1_000_000)
    max_distance_m: Optional[int] = Field(default=None, ge=100, le=20_000)
    groups: list[GroupIn] = Field(min_length=1)
    payment_method: Optional[str] = None

    @field_validator("budget_per_person", mode="before")
    @classmethod
    def use_fixed_budget(cls, _value: Any) -> int:
        return 12_000


class ReviewCreate(BaseModel):
    restaurant_id: int
    rating: int = Field(ge=1, le=5)
    content: str = Field(min_length=1, max_length=1000)
    author_name: str = Field(default="익명", max_length=80)


class ReportCreate(BaseModel):
    restaurant_id: int
    report_type: str
    content: str = Field(min_length=1, max_length=1000)


class UsageEventCreate(BaseModel):
    restaurant_id: Optional[int] = None
    event_type: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class AuthSync(BaseModel):
    """Supabase access token sent by the browser after Google OAuth."""

    access_token: str = Field(min_length=20, max_length=4096)


class AdminLogin(BaseModel):
    password: str = Field(min_length=1)


class PartnershipCreate(BaseModel):
    restaurant_id: Optional[int] = None
    restaurant_name: str = Field(min_length=1, max_length=160)
    category: str
    address: str = ""
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    phone: str = ""
    place_id: str = ""
    place_provider: str = ""
    opening_hours: str = ""
    menu_summary: str = ""
    image_url: str = ""
    affiliation_ids: list[int] = Field(min_length=1)
    benefit_type: str
    benefit_text: str = ""
    benefit_ai_json: dict[str, Any] = Field(default_factory=dict)
    discount_rate: float = Field(default=0, ge=0, le=100)
    fixed_discount: int = Field(default=0, ge=0)
    service_item: str = ""
    estimated_cash_value: int = Field(default=0, ge=0)
    min_order_amount: int = Field(default=0, ge=0)
    min_people: int = Field(default=1, ge=1, le=100)
    payment_method: str = ""
    application_scope: str = "ALL_GROUP"
    verification_method: str = "학생증"
    eligibility_description: str = ""
    start_date: date
    end_date: date
    status: str = "pending"
    source: str = "admin"

    @field_validator("end_date")
    @classmethod
    def end_after_start(cls, value: date, info):
        start = info.data.get("start_date")
        if start and value < start:
            raise ValueError("종료일은 시작일 이후여야 합니다.")
        return value


class PartnershipUpdate(BaseModel):
    status: Optional[str] = None
    end_date: Optional[date] = None
    benefit_text: Optional[str] = None
    benefit_ai_json: Optional[dict[str, Any]] = None
    discount_rate: Optional[float] = Field(default=None, ge=0, le=100)
    fixed_discount: Optional[int] = Field(default=None, ge=0)
    eligibility_description: Optional[str] = None
    verification_method: Optional[str] = None


class PartnershipBulkApprove(BaseModel):
    partnership_ids: list[int] = Field(min_length=1)


class BenefitAnalyzeRequest(BaseModel):
    benefit_text: str = Field(min_length=1, max_length=4000)


class ReportUpdate(BaseModel):
    status: str
    admin_note: str = ""


class ImportCommit(BaseModel):
    rows: list[dict[str, Any]] = Field(min_length=1)


class RecommendationResult(BaseModel):
    id: int
    name: str
    category: str
    rating_average: float
    review_count: int
    latitude: float
    longitude: float
    address: str
    phone: str
    opening_hours: str
    menu_summary: str
    distance_m: float
    walking_minutes: int
    eligible_affiliations: list[str]
    eligible_colleges: list[str]
    ai_store_summary: str
    benefit_items: list[str]
    benefit_conditions: list[str]
    benefit_grade: str
    benefit_grade_emoji: str
    benefit_label: str
    application_scope: str
    payment_method: str
    min_order_amount: int
    min_people: int
    verification_method: str
    estimated_total: int
    estimated_savings: int
    final_total: int
    final_per_person: int
    cdi: float
    benefit_score: float
    distance_score: float
    satisfaction_score: float
    review_limited: bool
    reasons: list[str]
    partnership_id: int


class RestaurantDetail(BaseModel):
    id: int
    name: str
    category: str
    address: str
    latitude: float
    longitude: float
    phone: str
    opening_hours: str
    menu_summary: str
    ai_store_summary: str
    image_url: str
    rating_average: float
    review_count: int
    partnerships: list[dict[str, Any]]
    reviews: list[dict[str, Any]]
