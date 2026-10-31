"""Orchestrates the multimodal content pipeline for a single post or draft."""
from dataclasses import dataclass, field
from datetime import datetime

from app.content import asr, visual
from app.content.descriptors import build_descriptors, extract_hashtags
from app.content.embeddings import get_text_embedder


@dataclass
class ContentFeatures:
    """Unified multimodal representation of a post."""

    descriptors: dict[str, float]
    text_embedding: list[float]
    visual_embedding: list[float] | None = None
    transcript: str = ""
    hashtags: list[str] = field(default_factory=list)


class ContentExtractor:
    """Converts caption, image or keyframes and speech into embeddings and descriptors."""

    def extract(self, caption: str, kind: str, duration_s: float | None, published_at: datetime, hashtags: list[str] | None = None, media_path: str | None = None, thumbnail_url: str | None = None) -> ContentFeatures:
        """Build the full feature bundle for a post."""
        tags = hashtags if hashtags else extract_hashtags(caption)
        transcript = asr.transcribe(media_path)
        frames = visual.load_frames(media_path, thumbnail_url)
        stats = visual.image_stats(frames)
        text_vec = get_text_embedder().embed([" ".join([caption or "", transcript])])[0]
        descriptors = build_descriptors(caption, tags, kind, duration_s, published_at, transcript, stats)
        return ContentFeatures(descriptors, text_vec.astype(float).tolist(), visual.clip_embedding(frames), transcript, tags)
