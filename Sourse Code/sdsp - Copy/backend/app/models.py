"""ORM models for the platform-independent schema."""
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from app.db import Base

EMBED_DIM = 384

try:
    from pgvector.sqlalchemy import Vector
except ImportError:  # pragma: no cover
    Vector = None


def utcnow() -> datetime:
    """Return the current timezone-aware UTC time."""
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """DateTime that always round-trips as timezone-aware UTC."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value


class EmbeddingType(TypeDecorator):
    """Embedding column stored as pgvector on PostgreSQL and as JSON elsewhere."""

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql" and Vector is not None:
            return dialect.type_descriptor(Vector(EMBED_DIM))
        return dialect.type_descriptor(JSON())

    def process_bind_param(self, value, dialect):
        return None if value is None else [float(x) for x in value]


class Creator(Base):
    """A creator or brand that owns one or more platform accounts."""

    __tablename__ = "creators"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    accounts: Mapped[list["Account"]] = relationship(back_populates="creator")


class Account(Base):
    """A connected platform account such as a YouTube channel or an Instagram professional account."""

    __tablename__ = "accounts"
    __table_args__ = (UniqueConstraint("platform", "external_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    creator_id: Mapped[int] = mapped_column(ForeignKey("creators.id"), index=True)
    platform: Mapped[str] = mapped_column(String(20))
    external_id: Mapped[str] = mapped_column(String(120))
    handle: Mapped[str | None] = mapped_column(String(120), nullable=True)
    followers: Mapped[int] = mapped_column(Integer, default=0)
    creator: Mapped[Creator] = relationship(back_populates="accounts")


class Post(Base):
    """A post normalised across platforms together with its multimodal content features."""

    __tablename__ = "posts"
    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    creator_id: Mapped[int] = mapped_column(ForeignKey("creators.id"), index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    platform: Mapped[str] = mapped_column(String(20), index=True)
    external_id: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(20), default="video")
    caption: Mapped[str] = mapped_column(Text, default="")
    hashtags: Mapped[list] = mapped_column(JSON, default=list)
    media_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    thumbnail_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    permalink: Mapped[str | None] = mapped_column(String(500), nullable=True)
    duration_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    published_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    transcript: Mapped[str] = mapped_column(Text, default="")
    text_embedding: Mapped[list | None] = mapped_column(EmbeddingType, nullable=True)
    visual_embedding: Mapped[list | None] = mapped_column(JSON, nullable=True)
    descriptors: Mapped[dict] = mapped_column(JSON, default=dict)
    features_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    snapshots: Mapped[list["EngagementSnapshot"]] = relationship(back_populates="post", order_by="EngagementSnapshot.captured_at")


class EngagementSnapshot(Base):
    """Engagement counters of a post captured at one point in time."""

    __tablename__ = "snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    post_id: Mapped[str] = mapped_column(ForeignKey("posts.id"), index=True)
    captured_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    hours_since_publish: Mapped[float] = mapped_column(Float)
    views: Mapped[int] = mapped_column(Integer, default=0)
    likes: Mapped[int] = mapped_column(Integer, default=0)
    comments: Mapped[int] = mapped_column(Integer, default=0)
    shares: Mapped[int] = mapped_column(Integer, default=0)
    weighted: Mapped[float] = mapped_column(Float, default=0.0)
    post: Mapped[Post] = relationship(back_populates="snapshots")


class ForecastRecord(Base):
    """The forecast issued for a post together with its feature attributions."""

    __tablename__ = "forecasts"
    post_id: Mapped[str] = mapped_column(ForeignKey("posts.id"), primary_key=True)
    baseline: Mapped[float] = mapped_column(Float)
    predicted_relative: Mapped[float] = mapped_column(Float)
    predicted_value: Mapped[float] = mapped_column(Float)
    explanation: Mapped[list] = mapped_column(JSON, default=list)
    cold_start: Mapped[bool] = mapped_column(default=False)
    model_version: Mapped[str] = mapped_column(String(40), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Event(Base):
    """A user-facing event that triggered the recommendation agent."""

    __tablename__ = "events"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    type: Mapped[str] = mapped_column(String(30), index=True)
    creator_id: Mapped[int] = mapped_column(ForeignKey("creators.id"), index=True)
    post_id: Mapped[str] = mapped_column(ForeignKey("posts.id"), index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)


class Recommendation(Base):
    """An evidence-backed recommendation produced by the agent for an event or a draft."""

    __tablename__ = "recommendations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[str | None] = mapped_column(ForeignKey("events.id"), nullable=True, index=True)
    post_id: Mapped[str | None] = mapped_column(ForeignKey("posts.id"), nullable=True)
    creator_id: Mapped[int] = mapped_column(ForeignKey("creators.id"), index=True)
    summary: Mapped[str] = mapped_column(Text)
    actions: Mapped[list] = mapped_column(JSON, default=list)
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    grounding_score: Mapped[float] = mapped_column(Float, default=0.0)
    fallback_used: Mapped[bool] = mapped_column(default=False)
    llm_backend: Mapped[str] = mapped_column(String(30), default="rules")
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    feedback: Mapped["RecommendationFeedback | None"] = relationship(
        back_populates="recommendation", uselist=False
    )


class RecommendationFeedback(Base):
    """The creator's latest usefulness rating for a recommendation."""

    __tablename__ = "recommendation_feedback"
    recommendation_id: Mapped[int] = mapped_column(
        ForeignKey("recommendations.id"), primary_key=True
    )
    helpful: Mapped[bool] = mapped_column(Boolean)
    submitted_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    recommendation: Mapped[Recommendation] = relationship(back_populates="feedback")
