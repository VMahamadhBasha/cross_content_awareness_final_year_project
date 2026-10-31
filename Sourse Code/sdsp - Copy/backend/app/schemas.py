"""Pydantic schemas shared by ingestion, the pipeline and the HTTP API."""
import base64
import binascii
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class Platform(StrEnum):
    """Supported social media platforms."""

    YOUTUBE = "youtube"
    INSTAGRAM = "instagram"


class EventType(StrEnum):
    """Event kinds flowing through the event bus."""

    NEW_UPLOAD = "new_upload"
    METRICS_UPDATED = "metrics_updated"
    UNDERPERFORMANCE = "underperformance"
    COMMENT_SURGE = "comment_surge"


class RawMetrics(BaseModel):
    """Engagement counters as reported by a platform."""

    views: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0


class CreatorAccountCreate(BaseModel):
    """A creator name and one real social-platform account to track."""

    name: str = Field(min_length=1, max_length=120)
    platform: Platform
    external_id: str = Field(min_length=1, max_length=120)
    handle: str | None = Field(default=None, max_length=120)

    @field_validator("name", "external_id", mode="before")
    @classmethod
    def strip_required_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("handle", mode="before")
    @classmethod
    def strip_handle(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None
        return value


class InstagramAccountResolve(BaseModel):
    """An Instagram username or professional-account ID to verify with the configured token."""

    identifier: str = Field(min_length=1, max_length=120)
    name: str | None = Field(default=None, max_length=120)

    @field_validator("identifier", mode="before")
    @classmethod
    def strip_identifier(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().lstrip("@")
        return value

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None
        return value


class RawPost(BaseModel):
    """A post normalised into the platform-independent ingestion schema."""

    platform: Platform
    external_id: str
    kind: str = "video"
    caption: str = ""
    hashtags: list[str] = Field(default_factory=list)
    media_url: str | None = None
    thumbnail_url: str | None = None
    permalink: str | None = None
    duration_s: float | None = None
    published_at: datetime
    metrics: RawMetrics = Field(default_factory=RawMetrics)


class BusEvent(BaseModel):
    """An event message carried on the event bus."""

    id: str
    type: EventType
    creator_id: int
    post_id: str
    payload: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime


class FeatureContribution(BaseModel):
    """Signed contribution of one feature to a forecast."""

    feature: str
    value: float
    contribution: float


class ForecastResult(BaseModel):
    """Forecast of a post's engagement relative to the creator's own baseline."""

    baseline: float
    predicted_relative: float
    predicted_value: float
    explanation: list[FeatureContribution]
    cold_start: bool = False
    model_version: str = ""


class WhatIfRequest(BaseModel):
    """A draft post to be analysed before publishing."""

    creator_id: int
    platform: Platform
    caption: str
    kind: str = "video"
    duration_s: float | None = None
    scheduled_at: datetime | None = None
    media_path: str | None = None
    image_data_url: str | None = Field(default=None, max_length=7_000_000)

    @field_validator("image_data_url")
    @classmethod
    def validate_image_data_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        prefix, separator, encoded = value.partition(",")
        if not separator or prefix not in {
            "data:image/jpeg;base64",
            "data:image/png;base64",
            "data:image/webp;base64",
        }:
            raise ValueError("Draft image must be a base64 JPEG, PNG, or WebP image.")
        try:
            image = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("Draft image is not valid base64 data.") from exc
        if not image or len(image) > 5_000_000:
            raise ValueError("Draft image must be between 1 byte and 5 MB.")
        is_jpeg = prefix == "data:image/jpeg;base64" and image.startswith(b"\xff\xd8\xff")
        is_png = prefix == "data:image/png;base64" and image.startswith(
            b"\x89PNG\r\n\x1a\n"
        )
        is_webp = (
            prefix == "data:image/webp;base64"
            and image.startswith(b"RIFF")
            and image[8:12] == b"WEBP"
        )
        if not (is_jpeg or is_png or is_webp):
            raise ValueError("Draft image data does not match its declared image type.")
        return value


class RecommendationFeedbackCreate(BaseModel):
    """A thumbs-up or thumbs-down rating for a recommendation."""

    helpful: bool


class WhatIfVariant(BaseModel):
    """A counterfactual variant of the draft and its forecast change."""

    label: str
    predicted_relative: float
    delta_pct: float


class WhatIfResponse(BaseModel):
    """Forecast, counterfactual variants and recommendation for a draft post."""

    forecast: ForecastResult
    variants: list[WhatIfVariant]
    recommendation: dict[str, Any]
