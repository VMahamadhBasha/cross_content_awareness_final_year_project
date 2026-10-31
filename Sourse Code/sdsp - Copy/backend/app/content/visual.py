"""Visual understanding: keyframe extraction, simple image statistics and optional CLIP embeddings."""
from functools import lru_cache
from io import BytesIO
from pathlib import Path

import numpy as np

from app.config import get_settings

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def extract_keyframes(video_path: str, count: int = 4) -> list[np.ndarray]:
    """Return evenly spaced RGB keyframes of a local video using OpenCV."""
    import cv2

    cap = cv2.VideoCapture(video_path)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    frames: list[np.ndarray] = []
    for idx in np.linspace(0, max(total - 1, 0), count, dtype=int):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(idx))
        ok, frame = cap.read()
        if ok:
            frames.append(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    cap.release()
    return frames


def load_image_from_url(url: str) -> np.ndarray | None:
    """Download a thumbnail and return it as an RGB array, or None on failure."""
    try:
        import httpx
        from PIL import Image

        resp = httpx.get(url, timeout=10, follow_redirects=True)
        resp.raise_for_status()
        return np.asarray(Image.open(BytesIO(resp.content)).convert("RGB"))
    except Exception:
        return None


def load_frames(media_path: str | None, thumbnail_url: str | None) -> list[np.ndarray]:
    """Load frames from a local image or video, otherwise from the thumbnail URL."""
    try:
        if media_path and Path(media_path).exists():
            if Path(media_path).suffix.lower() in IMAGE_SUFFIXES:
                from PIL import Image

                return [np.asarray(Image.open(media_path).convert("RGB"))]
            return extract_keyframes(media_path)
    except Exception:
        return []
    if thumbnail_url:
        img = load_image_from_url(thumbnail_url)
        return [img] if img is not None else []
    return []


def image_stats(frames: list[np.ndarray]) -> dict[str, float]:
    """Compute mean brightness and the Hasler-Suesstrunk colorfulness over frames."""
    if not frames:
        return {}
    brightness, colorfulness = [], []
    for f in frames:
        f = f.astype(np.float32)
        brightness.append(float(f.mean() / 255.0))
        rg, yb = f[..., 0] - f[..., 1], 0.5 * (f[..., 0] + f[..., 1]) - f[..., 2]
        colorfulness.append(float(np.hypot(rg.std(), yb.std()) + 0.3 * np.hypot(rg.mean(), yb.mean())) / 100.0)
    return {"brightness": float(np.mean(brightness)), "colorfulness": float(np.mean(colorfulness))}


@lru_cache
def _clip_model():
    """Load the CLIP model once."""
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer("clip-ViT-B-32")


def clip_embedding(frames: list[np.ndarray]) -> list[float] | None:
    """Return the mean CLIP embedding of frames when the clip backend is enabled."""
    if not frames or get_settings().visual_backend != "clip":
        return None
    try:
        from PIL import Image

        vecs = _clip_model().encode([Image.fromarray(f) for f in frames], normalize_embeddings=True)
        mean = np.asarray(vecs).mean(axis=0)
        return (mean / (np.linalg.norm(mean) or 1.0)).astype(float).tolist()
    except Exception:
        return None
