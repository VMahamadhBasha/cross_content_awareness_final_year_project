"""REST endpoints for the dashboard."""
import logging
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from app import repository as repo
from app.agent.types import AgentContext
from app.config import get_settings
from app.db import get_session
from app.evaluation.metrics import grounding_rate, latency_summary
from app.forecasting.service import ForecastProviderError, ForecasterNotReadyError
from app.models import (
    Account,
    Creator,
    EngagementSnapshot,
    Event,
    ForecastRecord,
    Post,
    Recommendation,
    RecommendationFeedback,
)
from app.schemas import CreatorAccountCreate, InstagramAccountResolve, RecommendationFeedbackCreate, WhatIfRequest, WhatIfResponse
from app.serializers import post_out, rec_out

router = APIRouter(prefix="/api", tags=["api"])
log = logging.getLogger(__name__)


@router.get("/health")
def health(request: Request) -> dict:
    """Report service status and active backends."""
    s = get_settings()
    p = request.app.state.pipeline
    return {"status": "ok", "demo_mode": s.demo_mode, "bus": type(p.bus).__name__, "llm": p.agent.llm.name, "langgraph": p.agent._graph is not None, "connectors": sorted(request.app.state.ingestion.connectors), "forecaster": p.forecasts.status()}


@router.get("/creators")
def creators(s: Session = Depends(get_session)) -> list[dict]:
    """List creators with their connected platforms."""
    return [_creator_out(c) for c in s.scalars(select(Creator).order_by(Creator.id))]


def _creator_out(creator: Creator) -> dict:
    return {"id": creator.id, "name": creator.name, "platforms": sorted({a.platform for a in creator.accounts}), "followers": {a.platform: a.followers for a in creator.accounts}}


@router.post("/creators", status_code=201)
def add_creator(body: CreatorAccountCreate, s: Session = Depends(get_session)) -> dict:
    """Register a creator with a real YouTube or Instagram account identity."""
    existing_account = s.scalar(select(Account).where(Account.platform == body.platform.value, Account.external_id == body.external_id))
    if existing_account:
        owner = s.get(Creator, existing_account.creator_id)
        raise HTTPException(409, f"This {body.platform.value} account is already registered to {owner.name if owner else 'another creator'}.")

    account = repo.get_or_create_account(s, body.name, body.platform.value, body.external_id, body.handle)
    creator = s.get(Creator, account.creator_id)
    if creator is None:
        raise HTTPException(500, "Creator registration did not persist.")
    return _creator_out(creator)


@router.delete("/creators/{creator_id}")
def remove_creator(creator_id: int, s: Session = Depends(get_session)) -> dict:
    """Remove a tracked creator and its locally stored account and post history."""
    creator = s.get(Creator, creator_id)
    if creator is None:
        raise HTTPException(404, "creator not found")

    post_ids = list(s.scalars(select(Post.id).where(Post.creator_id == creator_id)))
    event_ids = list(s.scalars(select(Event.id).where(Event.creator_id == creator_id)))
    recommendation_ids = list(
        s.scalars(
            select(Recommendation.id).where(
                or_(
                    Recommendation.creator_id == creator_id,
                    Recommendation.post_id.in_(post_ids),
                    Recommendation.event_id.in_(event_ids),
                )
            )
        )
    )

    if recommendation_ids:
        s.execute(
            delete(RecommendationFeedback).where(
                RecommendationFeedback.recommendation_id.in_(recommendation_ids)
            )
        )
        s.execute(
            delete(Recommendation).where(Recommendation.id.in_(recommendation_ids))
        )
    if event_ids:
        s.execute(delete(Event).where(Event.id.in_(event_ids)))
    if post_ids:
        s.execute(
            delete(EngagementSnapshot).where(EngagementSnapshot.post_id.in_(post_ids))
        )
        s.execute(delete(ForecastRecord).where(ForecastRecord.post_id.in_(post_ids)))
        s.execute(delete(Post).where(Post.id.in_(post_ids)))

    s.execute(delete(Account).where(Account.creator_id == creator_id))
    s.delete(creator)
    return {"creator_id": creator_id, "deleted": True}


@router.post("/creators/instagram", status_code=201)
def add_instagram_creator(
    body: InstagramAccountResolve,
    request: Request,
    s: Session = Depends(get_session),
) -> dict:
    """Resolve and register the Instagram professional account authorized by the token."""
    connector = request.app.state.ingestion.connectors.get("instagram")
    if connector is None:
        raise HTTPException(
            400,
            "Instagram is not connected. Configure INSTAGRAM_ACCESS_TOKEN in the backend environment and restart the API.",
        )
    try:
        profile = connector.resolve_account(body.identifier)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except httpx.HTTPStatusError as exc:
        response = exc.response
        try:
            error = response.json().get("error", {})
        except (ValueError, AttributeError):
            error = {}
        if not isinstance(error, dict):
            error = {}
        provider_message = error.get("message")
        provider_code = error.get("code")
        token = getattr(connector, "token", None)
        if isinstance(provider_message, str):
            if token:
                provider_message = provider_message.replace(token, "[redacted]")
            provider_message = provider_message[:300]
        log.warning(
            "Instagram account lookup rejected by provider (status=%s, code=%s)",
            response.status_code,
            provider_code,
        )
        detail = f"Instagram rejected the account lookup (HTTP {response.status_code}"
        if provider_code is not None:
            detail += f", code {provider_code}"
        detail += ")."
        if provider_message:
            detail += f" {provider_message}"
        detail += " Check the token, required permissions, and Meta app setup."
        raise HTTPException(502, detail) from exc
    except httpx.RequestError as exc:
        log.warning("Instagram account lookup failed because the provider request could not complete")
        raise HTTPException(
            502,
            "Could not reach Instagram to look up the account. Check the backend network connection and try again.",
        ) from exc

    account = repo.get_or_create_account(
        s,
        body.name or profile["name"],
        "instagram",
        profile["id"],
        profile["username"],
    )
    account.followers = profile["followers"]
    creator = s.get(Creator, account.creator_id)
    if creator is None:
        raise HTTPException(500, "Creator registration did not persist.")
    return {
        "creator": _creator_out(creator),
        "instagram_account": {
            "id": profile["id"],
            "username": profile["username"],
            "followers": profile["followers"],
        },
    }


@router.get("/posts")
def posts(creator_id: int | None = None, limit: int = 30, s: Session = Depends(get_session)) -> list[dict]:
    """List the most recent posts with metrics, forecast and status."""
    q = select(Post).order_by(Post.published_at.desc()).limit(min(limit, 100))
    if creator_id:
        q = q.where(Post.creator_id == creator_id)
    return [post_out(s, p) for p in s.scalars(q)]


@router.get("/posts/{post_id:path}")
def post_detail(post_id: str, s: Session = Depends(get_session)) -> dict:
    """Return one post with its timeline, expected curve and forecast explanation."""
    post = s.get(Post, post_id)
    if not post:
        raise HTTPException(404, "post not found")
    return post_out(s, post, detail=True)


@router.get("/events")
def events(limit: int = 30, s: Session = Depends(get_session)) -> list[dict]:
    """List recent events."""
    from app.serializers import event_out

    return [event_out(e) for e in s.scalars(select(Event).order_by(Event.occurred_at.desc()).limit(min(limit, 100)))]


@router.get("/recommendations")
def recommendations(creator_id: int | None = None, limit: int = 20, s: Session = Depends(get_session)) -> list[dict]:
    """List recent event-driven recommendations with their events and posts."""
    q = select(Recommendation).where(Recommendation.event_id.is_not(None)).order_by(Recommendation.created_at.desc()).limit(min(limit, 100))
    if creator_id:
        q = q.where(Recommendation.creator_id == creator_id)
    return [rec_out(r, s.get(Event, r.event_id), s.get(Post, r.post_id)) for r in s.scalars(q)]


@router.post("/recommendations/{recommendation_id}/feedback")
def recommendation_feedback(
    recommendation_id: int,
    body: RecommendationFeedbackCreate,
    s: Session = Depends(get_session),
) -> dict:
    """Create or replace a creator's usefulness rating for a recommendation."""
    recommendation = s.get(Recommendation, recommendation_id)
    if recommendation is None or recommendation.event_id is None:
        raise HTTPException(404, "recommendation not found")
    feedback = s.get(RecommendationFeedback, recommendation_id)
    if feedback is None:
        feedback = RecommendationFeedback(
            recommendation_id=recommendation_id, helpful=body.helpful
        )
        s.add(feedback)
    else:
        feedback.helpful = body.helpful
        feedback.submitted_at = datetime.now(timezone.utc)
    s.flush()
    return {
        "recommendation_id": recommendation_id,
        "helpful": feedback.helpful,
        "submitted_at": feedback.submitted_at.isoformat(),
    }


@router.get("/stats")
def stats(request: Request, s: Session = Depends(get_session)) -> dict:
    """Aggregate platform, event, latency and grounding statistics."""
    recs = list(s.scalars(select(Recommendation).where(Recommendation.event_id.is_not(None))))
    by_type = dict(s.execute(select(Event.type, func.count()).group_by(Event.type)).all())
    by_platform = dict(s.execute(select(Post.platform, func.count()).group_by(Post.platform)).all())
    feedback_count = s.scalar(
        select(func.count())
        .select_from(RecommendationFeedback)
        .join(Recommendation)
        .where(Recommendation.event_id.is_not(None))
    ) or 0
    helpful_count = s.scalar(
        select(func.count())
        .select_from(RecommendationFeedback)
        .join(Recommendation)
        .where(
            Recommendation.event_id.is_not(None),
            RecommendationFeedback.helpful.is_(True),
        )
    ) or 0
    model_version = request.app.state.pipeline.forecasts.status()["model_version"]
    return {"posts": sum(by_platform.values()), "posts_by_platform": by_platform, "events_by_type": by_type, "latency": latency_summary([r.latency_ms for r in recs if r.latency_ms is not None]), "grounding": grounding_rate([r.grounding_score for r in recs], get_settings().grounding_threshold), "usefulness": {"rated": feedback_count, "helpful": helpful_count, "helpful_share": helpful_count / feedback_count if feedback_count else 0.0}, "fallback_share": (sum(r.fallback_used for r in recs) / len(recs)) if recs else 0.0, "model_version": model_version}


@router.post("/whatif", response_model=WhatIfResponse)
def what_if(body: WhatIfRequest, request: Request, s: Session = Depends(get_session)) -> WhatIfResponse:
    """Forecast a draft post before publishing, test counterfactual edits and generate recommendations."""
    pipe = request.app.state.pipeline
    creator = s.get(Creator, body.creator_id)
    if not creator:
        raise HTTPException(404, "creator not found")
    when = body.scheduled_at or datetime.now(timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    feats = pipe.extractor.extract(body.caption, body.kind, body.duration_s, when, media_path=body.media_path)
    baseline, cold = repo.creator_baseline(s, body.creator_id, body.platform.value, when)
    followers = repo.followers_of(s, body.creator_id, body.platform.value)
    try:
        fc = pipe.forecasts.forecast(body.platform.value, feats, baseline, followers, cold, body.caption, body.image_data_url)
    except ForecasterNotReadyError as exc:
        raise HTTPException(503, str(exc)) from exc
    except ForecastProviderError as exc:
        raise HTTPException(502, str(exc)) from exc
    try:
        variants = pipe.forecasts.what_if_variants(body.platform.value, feats, baseline, followers, fc.predicted_relative, when, body.caption, body.image_data_url)
    except ForecasterNotReadyError as exc:
        raise HTTPException(503, str(exc)) from exc
    except ForecastProviderError as exc:
        raise HTTPException(502, str(exc)) from exc
    ctx = AgentContext("draft", None, body.platform.value, body.caption, fc, feats.descriptors, feats.text_embedding, body.creator_id)
    result = pipe.agent.run(s, ctx)
    rec = {"summary": result.summary, "actions": result.actions, "evidence": [{"id": e.id, "text": e.text} for e in result.evidence], "grounding_score": result.grounding_score, "llm_backend": result.backend, "fallback_used": result.fallback_used}
    return WhatIfResponse(forecast=fc, variants=variants, recommendation=rec)


@router.post("/sync")
def sync(request: Request, tasks: BackgroundTasks) -> dict:
    """Trigger a manual sync of all connected accounts."""
    ing = request.app.state.ingestion
    if not ing.enabled:
        raise HTTPException(400, "no platform connector configured; set YOUTUBE_API_KEY or INSTAGRAM_ACCESS_TOKEN")
    tasks.add_task(ing.sync_all)
    return {"status": "started"}
