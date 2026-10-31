"""Interpretable content descriptors derived from caption, timing, media and speech."""
import re
from datetime import datetime

HASHTAG_RE = re.compile(r"#(\w+)")
CTA_RE = re.compile(r"\b(subscribe|follow|comment|share|link in bio|click|join|sign up|save this|tag a|let me know|dm me|turn on notifications)\b", re.I)
EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF]")

NUMERIC_DESCRIPTORS = ["caption_words", "hashtag_count", "emoji_count", "has_question", "exclamations", "has_cta", "hour", "day_of_week", "is_weekend", "duration_s", "is_video", "is_short_video", "transcript_words", "speech_wpm", "brightness", "colorfulness"]


def extract_hashtags(text: str) -> list[str]:
    """Return the lowercase hashtags found in a text."""
    return [h.lower() for h in HASHTAG_RE.findall(text or "")]


def build_descriptors(caption: str, hashtags: list[str], kind: str, duration_s: float | None, published_at: datetime, transcript: str = "", visual_stats: dict | None = None) -> dict[str, float]:
    """Compute the numeric descriptor dictionary used for forecasting and explanation."""
    caption = caption or ""
    words = len(re.findall(r"\w+", HASHTAG_RE.sub("", caption)))
    duration = float(duration_s or 0.0)
    is_video = float(kind in {"video", "short", "reel"})
    transcript_words = len(re.findall(r"\w+", transcript or ""))
    visual_stats = visual_stats or {}
    return {
        "caption_words": float(words),
        "hashtag_count": float(len(hashtags)),
        "emoji_count": float(len(EMOJI_RE.findall(caption))),
        "has_question": float("?" in caption),
        "exclamations": float(caption.count("!")),
        "has_cta": float(bool(CTA_RE.search(caption))),
        "hour": float(published_at.hour),
        "day_of_week": float(published_at.weekday()),
        "is_weekend": float(published_at.weekday() >= 5),
        "duration_s": duration,
        "is_video": is_video,
        "is_short_video": float(is_video and 0 < duration <= 60),
        "transcript_words": float(transcript_words),
        "speech_wpm": float(transcript_words / (duration / 60.0)) if duration > 0 and transcript_words else 0.0,
        "brightness": float(visual_stats.get("brightness", 0.0)),
        "colorfulness": float(visual_stats.get("colorfulness", 0.0)),
    }
