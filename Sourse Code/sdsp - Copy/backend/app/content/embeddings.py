"""Text embedding backends producing fixed-size unit vectors."""
import re
import zlib
from functools import lru_cache

import numpy as np

from app.config import get_settings
from app.models import EMBED_DIM

TOKEN_RE = re.compile(r"[a-z0-9']+")


class HashEmbedder:
    """Deterministic signed feature-hashing embedder that needs no model download."""

    def embed(self, texts: list[str]) -> np.ndarray:
        """Embed texts into L2-normalised vectors of EMBED_DIM using hashed unigrams and bigrams."""
        out = np.zeros((len(texts), EMBED_DIM), dtype=np.float32)
        for i, text in enumerate(texts):
            tokens = TOKEN_RE.findall((text or "").lower())
            grams = tokens + [f"{a}_{b}" for a, b in zip(tokens, tokens[1:])]
            for g in grams:
                h = zlib.crc32(g.encode())
                out[i, h % EMBED_DIM] += 1.0 if (h >> 16) & 1 else -1.0
            norm = np.linalg.norm(out[i])
            if norm > 0:
                out[i] /= norm
        return out


class SbertEmbedder:
    """Sentence-Transformers embedder using all-MiniLM-L6-v2 which has 384 dimensions."""

    def __init__(self) -> None:
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

    def embed(self, texts: list[str]) -> np.ndarray:
        """Embed texts into L2-normalised vectors."""
        return np.asarray(self.model.encode(texts, normalize_embeddings=True), dtype=np.float32)


@lru_cache
def get_text_embedder():
    """Return the configured text embedder, falling back to hashing if the model is unavailable."""
    if get_settings().embedding_backend == "sbert":
        try:
            return SbertEmbedder()
        except Exception:  # pragma: no cover
            pass
    return HashEmbedder()


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    """Return the cosine similarity of two vectors."""
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float(np.dot(a, b) / denom) if denom else 0.0
