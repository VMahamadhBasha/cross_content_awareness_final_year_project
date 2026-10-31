"""Tabular feature construction from content descriptors, embeddings and creator context."""
import math

import numpy as np
import pandas as pd
from sklearn.decomposition import PCA

from app.content.descriptors import NUMERIC_DESCRIPTORS

PLATFORMS = ["youtube", "instagram"]


class FeatureBuilder:
    """Turns feature rows into a model matrix, compressing embeddings with PCA."""

    def __init__(self, text_dim: int = 8, visual_dim: int = 8) -> None:
        self.text_dim, self.visual_dim = text_dim, visual_dim
        self.text_pca: PCA | None = None
        self.visual_pca: PCA | None = None

    def fit(self, rows: list[dict]) -> "FeatureBuilder":
        """Fit the PCA projections on the training rows."""
        text = np.asarray([r["text_embedding"] for r in rows], dtype=np.float32)
        self.text_pca = PCA(n_components=min(self.text_dim, text.shape[0], text.shape[1])).fit(text)
        vis = [r["visual_embedding"] for r in rows if r.get("visual_embedding") is not None]
        if len(vis) >= max(20, len(rows) // 2):
            vis = np.asarray(vis, dtype=np.float32)
            self.visual_pca = PCA(n_components=min(self.visual_dim, vis.shape[0], vis.shape[1])).fit(vis)
        return self

    def transform(self, rows: list[dict]) -> pd.DataFrame:
        """Return the feature DataFrame for the given rows."""
        data = {name: [float(r["descriptors"].get(name, 0.0)) for r in rows] for name in NUMERIC_DESCRIPTORS}
        for p in PLATFORMS:
            data[f"platform_{p}"] = [float(r["platform"] == p) for r in rows]
        data["log_baseline"] = [math.log1p(r.get("baseline", 0.0)) for r in rows]
        data["log_followers"] = [math.log1p(r.get("followers", 0)) for r in rows]
        text = self.text_pca.transform(np.asarray([r["text_embedding"] for r in rows], dtype=np.float32))
        for i in range(self.text_pca.n_components_):
            data[f"text_pc{i}"] = text[:, i].tolist()
        if self.visual_pca is not None:
            dim = self.visual_pca.components_.shape[1]
            vis = np.asarray([r["visual_embedding"] if r.get("visual_embedding") is not None else np.zeros(dim) for r in rows], dtype=np.float32)
            comp = self.visual_pca.transform(vis)
            for i in range(self.visual_pca.n_components_):
                data[f"visual_pc{i}"] = comp[:, i].tolist()
        return pd.DataFrame(data)
