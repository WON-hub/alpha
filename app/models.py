from datetime import date, datetime
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Affiliation(Base):
    __tablename__ = "affiliations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    parent_id: Mapped[Optional[int]] = mapped_column(ForeignKey("affiliations.id", ondelete="SET NULL"))

    parent: Mapped[Optional["Affiliation"]] = relationship(remote_side="Affiliation.id", back_populates="children")
    children: Mapped[list["Affiliation"]] = relationship(back_populates="parent")
    partnerships: Mapped[list["Partnership"]] = relationship(back_populates="affiliation")


class Restaurant(Base):
    __tablename__ = "restaurants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    address: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    phone: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    place_id: Mapped[str] = mapped_column(String(255), default="", nullable=False, index=True)
    place_provider: Mapped[str] = mapped_column(String(20), default="", nullable=False)
    opening_hours: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    menu_summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    ai_summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    image_url: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    rating_average: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    review_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    bayesian_satisfaction_score: Mapped[float] = mapped_column(Float, default=60, nullable=False)
    satisfaction_preprocessed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    partnerships: Mapped[list["Partnership"]] = relationship(back_populates="restaurant", cascade="all, delete-orphan")
    reviews: Mapped[list["Review"]] = relationship(back_populates="restaurant", cascade="all, delete-orphan")
    reports: Mapped[list["Report"]] = relationship(back_populates="restaurant")


class Partnership(Base):
    __tablename__ = "partnerships"
    __table_args__ = (UniqueConstraint("restaurant_id", "affiliation_id", "start_date", name="uq_partnership_scope_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False, index=True)
    affiliation_id: Mapped[int] = mapped_column(ForeignKey("affiliations.id", ondelete="CASCADE"), nullable=False, index=True)
    benefit_type: Mapped[str] = mapped_column(String(30), nullable=False)
    benefit_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    benefit_ai_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    benefit_base_score: Mapped[float] = mapped_column(Float, default=20, nullable=False)
    benefit_bonus_score: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    benefit_condition_penalty: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    benefit_score_cached: Mapped[float] = mapped_column(Float, default=20, nullable=False)
    benefit_preprocessed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    discount_rate: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    fixed_discount: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    service_item: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    estimated_cash_value: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    min_order_amount: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    min_people: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    payment_method: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    application_scope: Mapped[str] = mapped_column(String(30), default="ALL_GROUP", nullable=False)
    verification_method: Mapped[str] = mapped_column(String(160), default="학생증", nullable=False)
    eligibility_description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(80), default="admin", nullable=False)
    last_verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    restaurant: Mapped[Restaurant] = relationship(back_populates="partnerships")
    affiliation: Mapped[Affiliation] = relationship(back_populates="partnerships")


class Review(Base):
    __tablename__ = "reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False, index=True)
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, default="", nullable=False)
    author_name: Mapped[str] = mapped_column(String(80), default="익명", nullable=False)
    is_hidden: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    admin_reply: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    restaurant: Mapped[Restaurant] = relationship(back_populates="reviews")


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False, index=True)
    report_type: Mapped[str] = mapped_column(String(40), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    restaurant: Mapped[Restaurant] = relationship(back_populates="reports")


class UsageEvent(Base):
    __tablename__ = "usage_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    restaurant_id: Mapped[Optional[int]] = mapped_column(ForeignKey("restaurants.id", ondelete="SET NULL"), index=True)
    event_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False, index=True)


class ImportBatch(Base):
    __tablename__ = "import_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="preview", nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    errors_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)


class AdminSession(Base):
    __tablename__ = "admin_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)


class User(Base):
    """A lightweight profile mirror for users authenticated by Supabase Auth."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    auth_user_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    name: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    avatar_url: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    favorites: Mapped[list["Favorite"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Favorite(Base):
    __tablename__ = "favorites"
    __table_args__ = (UniqueConstraint("user_id", "restaurant_id", name="uq_favorite_user_restaurant"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    user: Mapped[User] = relationship(back_populates="favorites")
    restaurant: Mapped[Restaurant] = relationship()
