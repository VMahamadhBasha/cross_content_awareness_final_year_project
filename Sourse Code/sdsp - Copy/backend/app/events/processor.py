"""Event processor: consumes bus events, runs detectors, the forecaster and the recommendation agent."""
import asyncio
import logging
import uuid

from app import repository as repo
from app.agent.types import AgentContext
from app.config import get_settings
from app.db import session_scope
from app.events.detectors import Detection, detect_comment_surge, detect_underperformance
from app.forecasting.service import ForecasterNotReadyError
from app.models import Event, ForecastRecord, Post, Recommendation, utcnow
from app.schemas import BusEvent, EventType, FeatureContribution, ForecastResult
from app.serializers import rec_out

log = logging.getLogger(__name__)
ALERT_TYPES = {EventType.NEW_UPLOAD, EventType.UNDERPERFORMANCE, EventType.COMMENT_SURGE}


def forecast_result(fc: ForecastRecord) -> ForecastResult:
    """Convert a stored forecast into the schema used by the agent."""
    return ForecastResult(baseline=fc.baseline, predicted_relative=fc.predicted_relative, predicted_value=fc.predicted_value, explanation=[FeatureContribution(**c) for c in fc.explanation], cold_start=fc.cold_start, model_version=fc.model_version)


class EventProcessor:
    """Consumes events from the bus and broadcasts finished recommendations."""

    def __init__(self, pipeline, broadcast) -> None:
        self.pipeline, self.broadcast, self.settings = pipeline, broadcast, get_settings()

    async def run(self) -> None:
        """Process events until cancelled."""
        async for token, event in self.pipeline.bus.consume():
            try:
                for message in await asyncio.to_thread(self.handle, event):
                    await self.broadcast(message)
            except ForecasterNotReadyError as exc:
                log.info("skipping event %s until forecasting is configured: %s", event.id, exc)
            except Exception:
                log.exception("failed to process event %s", event.id)
            finally:
                self.pipeline.bus.ack(token)

    def _detect(self, s, post: Post, fc: ForecastRecord) -> list[Detection]:
        """Run the detectors on the post's latest snapshots while respecting per-type cooldowns."""
        snaps = repo.snapshots_for(s, post.id)
        if not snaps:
            return []
        cfg, last, found = self.settings, snaps[-1], []
        if not repo.recent_event_exists(s, post.id, EventType.UNDERPERFORMANCE.value, cfg.event_cooldown_hours):
            d = detect_underperformance(last.weighted, fc.baseline, fc.predicted_relative, last.hours_since_publish, cfg.underperformance_ratio, cfg.underperformance_min_hours)
            if d:
                found.append(d)
        if not repo.recent_event_exists(s, post.id, EventType.COMMENT_SURGE.value, cfg.event_cooldown_hours):
            d = detect_comment_surge([(x.hours_since_publish, x.comments) for x in snaps], cfg.comment_surge_z, cfg.comment_surge_min_new)
            if d:
                found.append(d)
        return found

    def _recommend(self, s, post: Post, fc: ForecastRecord, ev: Event, occurred_at) -> dict:
        """Run the agent for an alert event, store the recommendation and build the WebSocket message."""
        det = ev.payload if ev.type in (EventType.UNDERPERFORMANCE.value, EventType.COMMENT_SURGE.value) else None
        ctx = AgentContext("event", ev.type, post.platform, post.caption, forecast_result(fc), post.descriptors, post.text_embedding, post.creator_id, post.id, det)
        result = self.pipeline.agent.run(s, ctx)
        rec = Recommendation(event_id=ev.id, post_id=post.id, creator_id=post.creator_id, summary=result.summary, actions=result.actions, evidence=[{"id": e.id, "text": e.text} for e in result.evidence], grounding_score=result.grounding_score, fallback_used=result.fallback_used, llm_backend=result.backend, latency_ms=(utcnow() - occurred_at).total_seconds() * 1000.0)
        s.add(rec)
        s.flush()
        return {"type": "alert", "recommendation": rec_out(rec, ev, post)}

    def handle(self, event: BusEvent) -> list[dict]:
        """Handle one bus event synchronously and return WebSocket messages to broadcast."""
        with session_scope() as s:
            post = s.get(Post, event.post_id)
            if post is None:
                return []
            self.pipeline.ensure_features(s, post)
            fc = self.pipeline.forecasts.forecast_post(s, post)
            if event.type == EventType.METRICS_UPDATED:
                out = []
                for det in self._detect(s, post, fc):
                    ev = Event(id=uuid.uuid4().hex, type=det.kind, creator_id=post.creator_id, post_id=post.id, payload=det.payload, occurred_at=event.occurred_at)
                    s.add(ev)
                    s.flush()
                    out.append(self._recommend(s, post, fc, ev, event.occurred_at))
                return out
            ev = s.get(Event, event.id)
            return [self._recommend(s, post, fc, ev, event.occurred_at)] if ev else []
