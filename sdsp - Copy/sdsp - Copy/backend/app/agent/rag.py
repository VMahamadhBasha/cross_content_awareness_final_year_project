"""Retrieval over the creator's own post history and construction of citable evidence."""
import math

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import repository as repo
from app.agent.types import AgentContext, Evidence, SimilarPost
from app.models import Post

NON_ACTIONABLE = {"log_baseline", "log_followers", "platform_youtube", "platform_instagram"}


class SimilarPostRetriever:
    """Finds the creator's most similar mature past posts by caption embedding."""

    def search(self, s: Session, creator_id: int, embedding: list[float], exclude_post_id: str | None, k: int = 3) -> list[SimilarPost]:
        """Return up to k similar posts with their performance relative to the baseline at their publish time."""
        posts = repo.similar_posts_sql(s, creator_id, embedding, exclude_post_id, k * 4)
        if posts is None:
            posts = list(s.scalars(select(Post).where(Post.creator_id == creator_id, Post.text_embedding.is_not(None), Post.id != (exclude_post_id or "")).order_by(Post.published_at.desc()).limit(500)))
        q = np.asarray(embedding, dtype=np.float32)
        scored = []
        for p in posts:
            v = np.asarray(p.text_embedding, dtype=np.float32)
            denom = float(np.linalg.norm(q) * np.linalg.norm(v))
            scored.append((float(q @ v) / denom if denom else 0.0, p))
        out: list[SimilarPost] = []
        for sim, p in sorted(scored, key=lambda t: t[0], reverse=True):
            snap = repo.latest_snapshot(s, p.id)
            if not snap or snap.hours_since_publish < 24:
                continue
            baseline, _ = repo.creator_baseline(s, p.creator_id, p.platform, p.published_at)
            rel = repo.relative_performance(snap.weighted, baseline)
            out.append(SimilarPost(p.id, p.caption, sim, (math.exp(rel) - 1.0) * 100.0, p.descriptors))
            if len(out) == k:
                break
        return out


def build_evidence(ctx: AgentContext) -> list[Evidence]:
    """Turn the context into a numbered list of citable evidence items."""
    f = ctx.forecast
    pct = (math.exp(f.predicted_relative) - 1.0) * 100.0
    ev = [Evidence("F1", f"Forecast: engagement {pct:+.0f}% versus the creator baseline of {f.baseline:.0f} (predicted {f.predicted_value:.0f} weighted interactions)")]
    for i, c in enumerate([c for c in f.explanation if c.feature not in NON_ACTIONABLE][:5], 1):
        ev.append(Evidence(f"X{i}", f"Feature {c.feature}={c.value:.2f} contributes {c.contribution:+.2f} to the log forecast"))
    for i, sp in enumerate(ctx.similar, 1):
        d = sp.descriptors
        ev.append(Evidence(f"S{i}", f"Similar past post (similarity {sp.similarity:.2f}) '{sp.caption[:70]}' performed {sp.relative_pct:+.0f}% versus its baseline with {d.get('hashtag_count', 0):.0f} hashtags, question={int(d.get('has_question', 0))}, cta={int(d.get('has_cta', 0))}, posted at hour {d.get('hour', 0):.0f}"))
    det = ctx.detection or {}
    if ctx.event_type == "underperformance":
        ev.append(Evidence("D1", f"Observed {det['observed']:.0f} engagement after {det['hours']:.1f} hours versus {det['expected_now']:.0f} expected, which is {det['ratio'] * 100:.0f}% of the forecast trajectory"))
    elif ctx.event_type == "comment_surge":
        ev.append(Evidence("D1", f"{det['new_comments']} new comments in the latest interval, a rate of {det['rate_per_hour']:.1f} per hour versus a typical {det['typical_rate_per_hour']:.1f} per hour after {det['hours']:.1f} hours"))
    return ev
