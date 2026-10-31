"""Data access helpers shared by ingestion, the pipeline and the API."""
import math
from datetime import datetime, timedelta

import numpy as np
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.models import Account, Creator, EngagementSnapshot, ForecastRecord, Post, utcnow
from app.schemas import RawMetrics, RawPost

DEFAULT_BASELINE = 50.0


def weighted_engagement(m: RawMetrics) -> float:
    """Weighted interaction count: likes plus two times comments plus three times shares."""
    return float(m.likes + 2 * m.comments + 3 * m.shares)


def get_or_create_account(s: Session, creator_name: str, platform: str, external_id: str, handle: str | None = None, followers: int = 0) -> Account:
    """Return the account for a platform identity, creating the creator and account when missing."""
    acc = s.scalar(select(Account).where(Account.platform == platform, Account.external_id == external_id))
    if acc:
        if followers:
            acc.followers = followers
        return acc
    creator = s.scalar(select(Creator).where(Creator.name == creator_name)) or Creator(name=creator_name)
    s.add(creator)
    s.flush()
    acc = Account(creator_id=creator.id, platform=platform, external_id=external_id, handle=handle, followers=followers)
    s.add(acc)
    s.flush()
    return acc


def upsert_post(s: Session, account: Account, raw: RawPost) -> tuple[Post, bool]:
    """Insert or update a post from the ingestion schema and report whether it is new."""
    pid = f"{raw.platform.value}:{raw.external_id}"
    post = s.get(Post, pid)
    if post:
        return post, False
    post = Post(id=pid, creator_id=account.creator_id, account_id=account.id, platform=raw.platform.value, external_id=raw.external_id, kind=raw.kind, caption=raw.caption, hashtags=raw.hashtags, media_url=raw.media_url, thumbnail_url=raw.thumbnail_url, permalink=raw.permalink, duration_s=raw.duration_s, published_at=raw.published_at)
    s.add(post)
    s.flush()
    return post, True


def add_snapshot(s: Session, post: Post, metrics: RawMetrics, captured_at: datetime) -> EngagementSnapshot:
    """Store an engagement snapshot for a post."""
    hours = max((captured_at - post.published_at).total_seconds() / 3600.0, 0.0)
    snap = EngagementSnapshot(post_id=post.id, captured_at=captured_at, hours_since_publish=hours, views=metrics.views, likes=metrics.likes, comments=metrics.comments, shares=metrics.shares, weighted=weighted_engagement(metrics))
    s.add(snap)
    s.flush()
    return snap


def latest_snapshot(s: Session, post_id: str) -> EngagementSnapshot | None:
    """Return the most recent snapshot of a post."""
    return s.scalar(select(EngagementSnapshot).where(EngagementSnapshot.post_id == post_id).order_by(EngagementSnapshot.captured_at.desc()).limit(1))


def snapshots_for(s: Session, post_id: str) -> list[EngagementSnapshot]:
    """Return all snapshots of a post in chronological order."""
    return list(s.scalars(select(EngagementSnapshot).where(EngagementSnapshot.post_id == post_id).order_by(EngagementSnapshot.captured_at)))


def creator_baseline(s: Session, creator_id: int, platform: str, before: datetime, window: int = 20) -> tuple[float, bool]:
    """Median latest engagement of the creator's previous posts on a platform and a cold-start flag."""
    ids = list(s.scalars(select(Post.id).where(Post.creator_id == creator_id, Post.platform == platform, Post.published_at < before).order_by(Post.published_at.desc()).limit(window)))
    values = []
    for pid in ids:
        snap = latest_snapshot(s, pid)
        if snap and snap.weighted > 0:
            values.append(snap.weighted)
    if len(values) < 3:
        return (float(np.median(values)) if values else DEFAULT_BASELINE), True
    return float(np.median(values)), False


def followers_of(s: Session, creator_id: int, platform: str) -> int:
    """Follower count of the creator's account on a platform."""
    return int(s.scalar(select(func.coalesce(func.max(Account.followers), 0)).where(Account.creator_id == creator_id, Account.platform == platform)) or 0)


def post_forecast(s: Session, post_id: str) -> ForecastRecord | None:
    """Return the stored forecast of a post if one exists."""
    return s.get(ForecastRecord, post_id)


def recent_event_exists(s: Session, post_id: str, event_type: str, cooldown_hours: float) -> bool:
    """True when an event of this type was already raised for the post within the cooldown window."""
    from app.models import Event

    cutoff = utcnow() - timedelta(hours=cooldown_hours)
    return s.scalar(select(func.count()).select_from(Event).where(Event.post_id == post_id, Event.type == event_type, Event.occurred_at >= cutoff)) > 0


def similar_posts_sql(s: Session, creator_id: int, embedding: list[float], exclude: str | None, k: int) -> list[Post] | None:
    """Nearest posts by cosine distance using pgvector on PostgreSQL, or None when unsupported."""
    if s.bind.dialect.name != "postgresql":
        return None
    try:
        stmt = select(Post).where(Post.creator_id == creator_id, Post.text_embedding.is_not(None), Post.id != (exclude or "")).order_by(text("text_embedding <=> CAST(:q AS vector)")).limit(k).params(q=str([float(x) for x in embedding]))
        return list(s.scalars(stmt))
    except Exception:
        s.rollback()
        return None


def relative_performance(final_value: float, baseline: float) -> float:
    """Log ratio of a final engagement value against its baseline."""
    return math.log((final_value + 1.0) / (baseline + 1.0))
