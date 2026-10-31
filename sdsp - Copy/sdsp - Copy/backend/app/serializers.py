"""Conversion of ORM objects into JSON-ready dictionaries for the API and WebSocket."""
import math

from sqlalchemy.orm import Session

from app import repository as repo
from app.events.detectors import growth_curve
from app.models import Creator, Event, Post, Recommendation


def post_status(weighted: float, hours: float, predicted_value: float) -> tuple[str, float]:
    """Classify a post as new, behind, on track or ahead of its forecast trajectory."""
    expected = predicted_value * (growth_curve(hours) if hours <= 48 else 1.0)
    ratio = weighted / expected if expected > 0 else 1.0
    if hours < 2:
        return "new", ratio
    return ("behind" if ratio < 0.5 else "ahead" if ratio > 1.3 else "on_track"), ratio


def post_out(s: Session, post: Post, detail: bool = False) -> dict:
    """Serialize a post with its latest metrics, forecast and status."""
    snaps = repo.snapshots_for(s, post.id)
    last = snaps[-1] if snaps else None
    fc = repo.post_forecast(s, post.id)
    creator = s.get(Creator, post.creator_id)
    out = {"id": post.id, "creator_id": post.creator_id, "creator": creator.name if creator else "", "platform": post.platform, "kind": post.kind, "caption": post.caption, "hashtags": post.hashtags, "published_at": post.published_at.isoformat(), "thumbnail_url": post.thumbnail_url, "permalink": post.permalink, "sparkline": [round(x.weighted, 1) for x in snaps[-12:]]}
    out["metrics"] = {"views": last.views, "likes": last.likes, "comments": last.comments, "shares": last.shares, "weighted": last.weighted, "hours": round(last.hours_since_publish, 2)} if last else None
    out["forecast"] = {"baseline": fc.baseline, "predicted_value": round(fc.predicted_value, 1), "predicted_relative": round(fc.predicted_relative, 3), "pct_vs_baseline": round((math.exp(fc.predicted_relative) - 1) * 100, 1), "cold_start": fc.cold_start} if fc else None
    if last and fc:
        out["status"], ratio = post_status(last.weighted, last.hours_since_publish, fc.predicted_value)
        out["trajectory_ratio"] = round(ratio, 2)
    else:
        out["status"] = "unknown"
    if detail:
        out["descriptors"] = post.descriptors
        out["explanation"] = fc.explanation if fc else []
        out["timeline"] = [{"hours": round(x.hours_since_publish, 2), "weighted": x.weighted, "comments": x.comments, "likes": x.likes, "views": x.views} for x in snaps]
        out["expected_curve"] = [{"hours": h, "expected": round(fc.predicted_value * growth_curve(h), 1)} for h in (0, 1, 2, 4, 6, 12, 24, 48)] if fc else []
    return out


def event_out(ev: Event) -> dict:
    """Serialize an event."""
    return {"id": ev.id, "type": ev.type, "creator_id": ev.creator_id, "post_id": ev.post_id, "payload": ev.payload, "occurred_at": ev.occurred_at.isoformat()}


def rec_out(rec: Recommendation, ev: Event | None = None, post: Post | None = None) -> dict:
    """Serialize a recommendation with its evidence."""
    out = {"id": rec.id, "event_id": rec.event_id, "post_id": rec.post_id, "creator_id": rec.creator_id, "summary": rec.summary, "actions": rec.actions, "evidence": rec.evidence, "grounding_score": round(rec.grounding_score, 3), "fallback_used": rec.fallback_used, "llm_backend": rec.llm_backend, "latency_ms": round(rec.latency_ms, 1) if rec.latency_ms is not None else None, "created_at": rec.created_at.isoformat(), "helpful": rec.feedback.helpful if rec.feedback else None}
    if ev:
        out["event"] = event_out(ev)
    if post:
        out["post"] = {"id": post.id, "platform": post.platform, "caption": post.caption[:140], "thumbnail_url": post.thumbnail_url}
    return out
