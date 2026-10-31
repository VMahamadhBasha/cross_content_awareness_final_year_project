"""Speech-to-text using Whisper through faster-whisper for local media files."""
from functools import lru_cache
from pathlib import Path

from app.config import get_settings


@lru_cache
def _model():
    """Load the Whisper model once."""
    from faster_whisper import WhisperModel

    return WhisperModel("base", compute_type="int8")


def transcribe(media_path: str | None) -> str:
    """Transcribe a local audio or video file, returning an empty string when ASR is disabled or fails."""
    if get_settings().asr_backend != "whisper" or not media_path or not Path(media_path).exists():
        return ""
    try:
        segments, _ = _model().transcribe(media_path)
        return " ".join(s.text.strip() for s in segments)
    except Exception:
        return ""
