"""Core orchestration: ingestion into the unified schema, content extraction, forecasting and event emission."""
import uuid
from datetime import datetime, timedelta

from app import repository as repo
from app.agent.graph import RecommendationAgent
from app.content.extractor import ContentExtractor
from app.db import session_scope
from app.events.bus import make_bus
from app.forecasting.service import ForecastService
from app.models import Account, Event, Post, utcnow
from app.schemas import BusEvent, EventType, RawPost

NEW_UPLOAD_MAX_AGE_HOURS = 2.0


class Pipeline:
    """Holds the shared services and implements the ingest-and-publish flow."""

    def __init__(self, bus=None, forecasts: ForecastService | None = None, extractor: ContentExtractor | None = None, agent: RecommendationAgent | None = None) -> None:
        self.bus = bus or make_bus()
        self.forecasts = forecasts or ForecastService()
        self.extractor = extractor or ContentExtractor()
        self.agent = agent or RecommendationAgent()

    def ensure_features(self, s, post: Post) -> None:
        """Extract and store multimodal features for a post when missing."""
        if post.features_at is not None:
            return
        feats = self.extractor.extract(post.caption, post.kind, post.duration_s, post.published_at, post.hashtags, thumbnail_url=post.thumbnail_url)
        post.descriptors, post.text_embedding, post.visual_embedding = feats.descriptors, feats.text_embedding, feats.visual_embedding
        post.transcript, post.hashtags, post.features_at = feats.transcript, feats.hashtags, utcnow()
        s.flush()

    def ingest(self, s, account: Account, raws: list[RawPost], captured_at: datetime | None = None) -> list[BusEvent]:
        """Upsert posts and snapshots and return the bus events to publish after the transaction commits."""
        events: list[BusEvent] = []
        now = utcnow()
        for raw in raws:
            post, is_new = repo.upsert_post(s, account, raw)
            self.ensure_features(s, post)
            repo.add_snapshot(s, post, raw.metrics, captured_at or now)
            if is_new and (now - post.published_at) <= timedelta(hours=NEW_UPLOAD_MAX_AGE_HOURS):
                ev = Event(id=uuid.uuid4().hex, type=EventType.NEW_UPLOAD.value, creator_id=post.creator_id, post_id=post.id, payload={}, occurred_at=now)
                s.add(ev)
                events.append(BusEvent(id=ev.id, type=EventType.NEW_UPLOAD, creator_id=post.creator_id, post_id=post.id, occurred_at=now))
            events.append(BusEvent(id=uuid.uuid4().hex, type=EventType.METRICS_UPDATED, creator_id=post.creator_id, post_id=post.id, occurred_at=now))
        s.flush()
        return events

    def ingest_and_publish(self, account_id: int, raws: list[RawPost], captured_at: datetime | None = None) -> int:
        """Run ingest in its own transaction and publish the resulting events once committed."""
        with session_scope() as s:
            account = s.get(Account, account_id)
            events = self.ingest(s, account, raws, captured_at)
        for e in events:
            self.bus.publish(e)
        return len(events)
