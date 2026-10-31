"""OpenAI-backed engagement forecasts for stored posts and drafts."""
import json
import logging
import math
from datetime import datetime

import httpx
from sqlalchemy.orm import Session

from app import repository as repo
from app.config import get_settings
from app.content.extractor import ContentFeatures
from app.forecasting.model import to_value
from app.llm_client import chat_completion_json
from app.models import ForecastRecord, Post, utcnow
from app.schemas import FeatureContribution, ForecastResult, WhatIfVariant

log = logging.getLogger(__name__)
MODEL_FILE = "forecaster.joblib"
MIN_RELATIVE_MULTIPLIER = 0.01
MAX_RELATIVE_MULTIPLIER = 100.0

FORECAST_SYSTEM_PROMPT = (
    "You are estimating social-media engagement relative to a creator's own baseline. "
    "Use the supplied post content, available image, embeddings, and numeric descriptors; "
    "do not invent audience or platform facts. Treat an absent image as unavailable. "
    "A relative_multiplier of 1 means the post is expected to match the baseline. "
    "Make a conservative estimate between 0.01 and 100. "
    'Return JSON only: {"relative_multiplier": number, "explanation": '
    '[{"feature": "descriptor key", "contribution": number}]}. '
    "Use one to four explanation entries. Each feature must be one of the supplied descriptor keys, "
    "and each contribution must be a signed estimate in log-relative-engagement units."
)

VARIANT_SYSTEM_PROMPT = (
    "You estimate social-media engagement relative to a creator's own baseline. "
    "For each supplied what-if variant, use its proposed change, descriptor values, embeddings, "
    "and the provided image when available. "
    "Keep estimates conservative and return a multiplier from 0.01 to 100. "
    'Return JSON only: {"predictions": [{"label": "exact input label", '
    '"relative_multiplier": number}]} with exactly one prediction for each input variant.'
)


class ForecasterNotReadyError(RuntimeError):
    """Raised when the OpenAI API key required for forecasts is missing."""


class ForecastProviderError(RuntimeError):
    """Raised when OpenAI fails or returns an invalid forecast."""


def _number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"OpenAI forecast field {field!r} must be numeric.")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"OpenAI forecast field {field!r} must be finite.")
    return result


def _relative_log(multiplier: object) -> float:
    value = _number(multiplier, "relative_multiplier")
    if not MIN_RELATIVE_MULTIPLIER <= value <= MAX_RELATIVE_MULTIPLIER:
        raise ValueError(
            f"OpenAI relative_multiplier must be between "
            f"{MIN_RELATIVE_MULTIPLIER} and {MAX_RELATIVE_MULTIPLIER}."
        )
    return math.log(value)


def _json_object(raw: str) -> dict:
    try:
        result = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("OpenAI did not return valid JSON.") from exc
    if not isinstance(result, dict):
        raise ValueError("OpenAI forecast response must be a JSON object.")
    return result


class ForecastService:
    """Produces relative-engagement estimates with the configured OpenAI model."""

    def __init__(self) -> None:
        self.settings = get_settings()

    def status(self) -> dict[str, bool | str | None]:
        """Report whether an OpenAI model is configured; this is not a trained model."""
        ready = bool(self.settings.openai_api_key)
        return {
            "ready": ready,
            "backend": "openai",
            "model_version": self._model_version() if ready else None,
            "mode": "live_llm_estimate",
            "message": "" if ready else "Set OPENAI_API_KEY in the backend environment to enable forecasts.",
        }

    def _model_version(self) -> str:
        return f"openai:{self.settings.openai_model}:mm1"

    def initialize(self) -> bool:
        """Check configuration without making a billable API request."""
        return bool(self.settings.openai_api_key)

    def _require_provider(self) -> None:
        if not self.settings.openai_api_key:
            raise ForecasterNotReadyError(
                "OpenAI forecasts are not configured. Set OPENAI_API_KEY in the backend environment."
            )

    @staticmethod
    def _prompt_payload(
        platform: str,
        caption: str,
        feats: ContentFeatures,
        baseline: float,
        followers: int,
    ) -> str:
        return json.dumps(
            {
                "platform": platform,
                "caption": caption[:2000],
                "transcript": feats.transcript[:1000],
                "descriptors": feats.descriptors,
                "text_embedding": feats.text_embedding,
                "visual_embedding": feats.visual_embedding,
                "creator_baseline_weighted_engagement": baseline,
                "creator_followers": followers,
            },
            ensure_ascii=True,
        )

    @staticmethod
    def _explanation(raw: object, descriptors: dict[str, float]) -> list[FeatureContribution]:
        if not isinstance(raw, list) or not raw:
            raise ValueError("OpenAI forecast must include at least one explanation.")
        result: list[FeatureContribution] = []
        for item in raw[:4]:
            if not isinstance(item, dict):
                raise ValueError("OpenAI explanation entries must be objects.")
            feature = item.get("feature")
            if not isinstance(feature, str) or feature not in descriptors:
                raise ValueError("OpenAI explanation referenced an unknown descriptor.")
            contribution = _number(item.get("contribution"), "explanation.contribution")
            result.append(
                FeatureContribution(
                    feature=feature,
                    value=float(descriptors[feature]),
                    contribution=contribution,
                )
            )
        return result

    def _request_forecast(
        self,
        platform: str,
        caption: str,
        feats: ContentFeatures,
        baseline: float,
        followers: int,
        image_url: str | None = None,
    ) -> tuple[float, list[FeatureContribution]]:
        self._require_provider()
        prompt = self._prompt_payload(platform, caption, feats, baseline, followers)
        raw = (
            chat_completion_json(
                FORECAST_SYSTEM_PROMPT, prompt, image_url=image_url
            )
            if image_url
            else chat_completion_json(FORECAST_SYSTEM_PROMPT, prompt)
        )
        data = _json_object(raw)
        relative = _relative_log(data.get("relative_multiplier"))
        explanation = self._explanation(data.get("explanation"), feats.descriptors)
        return relative, explanation

    def forecast(
        self,
        platform: str,
        feats: ContentFeatures,
        baseline: float,
        followers: int,
        cold_start: bool = False,
        caption: str = "",
        image_url: str | None = None,
    ) -> ForecastResult:
        """Estimate a post's engagement relative to baseline using OpenAI."""
        try:
            relative, explanation = self._request_forecast(
                platform, caption, feats, baseline, followers, image_url
            )
        except ForecasterNotReadyError:
            raise
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            log.exception("OpenAI forecast request failed")
            raise ForecastProviderError(
                "OpenAI could not produce a valid forecast; check backend logs and API configuration."
            ) from exc
        return ForecastResult(
            baseline=baseline,
            predicted_relative=relative,
            predicted_value=to_value(baseline, relative),
            explanation=explanation,
            cold_start=cold_start,
            model_version=self._model_version(),
        )

    def forecast_post(self, s: Session, post: Post, force: bool = False) -> ForecastRecord:
        """Compute and store a post forecast, reusing it unless refresh is requested."""
        existing = repo.post_forecast(s, post.id)
        if existing and not force and existing.model_version == self._model_version():
            return existing
        baseline, cold = repo.creator_baseline(s, post.creator_id, post.platform, post.published_at)
        feats = ContentFeatures(
            post.descriptors or {},
            post.text_embedding or [],
            post.visual_embedding,
            post.transcript or "",
        )
        result = self.forecast(
            post.platform,
            feats,
            baseline,
            repo.followers_of(s, post.creator_id, post.platform),
            cold,
            post.caption,
            self._safe_thumbnail_url(post.thumbnail_url),
        )
        record = existing or ForecastRecord(post_id=post.id)
        record.baseline = result.baseline
        record.predicted_relative = result.predicted_relative
        record.predicted_value = result.predicted_value
        record.explanation = [item.model_dump() for item in result.explanation]
        record.cold_start = result.cold_start
        record.model_version = result.model_version
        record.created_at = utcnow()
        s.add(record)
        s.flush()
        return record

    def what_if_variants(
        self,
        platform: str,
        feats: ContentFeatures,
        baseline: float,
        followers: int,
        base_rel: float,
        scheduled_at: datetime,
        caption: str = "",
        image_url: str | None = None,
    ) -> list[WhatIfVariant]:
        """Estimate ranked counterfactual edits in one OpenAI request."""
        d = feats.descriptors
        edits: list[tuple[str, dict[str, float]]] = []
        for hour in (9, 12, 18, 19, 20, 21):
            if int(d["hour"]) != hour:
                edits.append((f"Post at {hour:02d}:00 UTC", {"hour": float(hour)}))
        if not d["has_question"]:
            edits.append(("End the caption with a question", {"has_question": 1.0}))
        if not d["has_cta"]:
            edits.append(("Add a call to action", {"has_cta": 1.0}))
        for count in (3, 5, 8):
            if int(d["hashtag_count"]) != count:
                edits.append((f"Use {count} hashtags", {"hashtag_count": float(count)}))
        if not edits:
            return []

        self._require_provider()
        expected_labels = [label for label, _ in edits]
        variants = [
            {"label": label, "proposed_change": label, "descriptors": {**d, **patch}}
            for label, patch in edits
        ]
        prompt = json.dumps(
            {
                "platform": platform,
                "caption": caption[:2000],
                "transcript": feats.transcript[:1000],
                "text_embedding": feats.text_embedding,
                "visual_embedding": feats.visual_embedding,
                "baseline_weighted_engagement": baseline,
                "followers": followers,
                "variants": variants,
            },
            ensure_ascii=True,
        )
        try:
            response = (
                chat_completion_json(
                    VARIANT_SYSTEM_PROMPT, prompt, image_url=image_url
                )
                if image_url
                else chat_completion_json(VARIANT_SYSTEM_PROMPT, prompt)
            )
            data = _json_object(response)
            predictions = data.get("predictions")
            if not isinstance(predictions, list) or len(predictions) != len(expected_labels):
                raise ValueError("OpenAI returned an incomplete what-if forecast.")
            by_label: dict[str, float] = {}
            for item in predictions:
                if not isinstance(item, dict):
                    raise ValueError("OpenAI what-if predictions must be objects.")
                label = item.get("label")
                if not isinstance(label, str) or label not in expected_labels or label in by_label:
                    raise ValueError("OpenAI returned an unknown or duplicate what-if label.")
                by_label[label] = _relative_log(item.get("relative_multiplier"))
            if set(by_label) != set(expected_labels):
                raise ValueError("OpenAI did not return a prediction for every what-if variant.")
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            log.exception("OpenAI what-if forecast request failed")
            raise ForecastProviderError(
                "OpenAI could not produce valid what-if forecasts; check backend logs and API configuration."
            ) from exc

        results = [
            WhatIfVariant(
                label=label,
                predicted_relative=by_label[label],
                delta_pct=(math.exp(by_label[label] - base_rel) - 1.0) * 100.0,
            )
            for label in expected_labels
        ]
        ranked = sorted(results, key=lambda variant: variant.delta_pct, reverse=True)
        time_variants = [
            variant
            for variant in ranked
            if variant.label.startswith("Post at ") and variant.label.endswith(" UTC")
        ]
        if time_variants and not any(variant in ranked[:6] for variant in time_variants):
            ranked = sorted(
                [time_variants[0], *[variant for variant in ranked if variant != time_variants[0]][:5]],
                key=lambda variant: variant.delta_pct,
                reverse=True,
            )
        return ranked[:6]

    @staticmethod
    def _safe_thumbnail_url(url: str | None) -> str | None:
        """Allow image forwarding only for known public social-media CDN hosts."""
        if not url:
            return None
        from urllib.parse import urlparse

        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        allowed = (
            host == "i.ytimg.com"
            or host == "yt3.ggpht.com"
            or host.endswith(".yt3.ggpht.com")
            or host.endswith(".cdninstagram.com")
            or host.endswith(".fbcdn.net")
        )
        if parsed.scheme != "https" or not allowed:
            raise ValueError("Post thumbnail URL is not from a supported media CDN.")
        return url
