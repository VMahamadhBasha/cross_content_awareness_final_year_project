"""LightGBM engagement forecaster predicting performance relative to the creator's baseline."""
import math
from pathlib import Path

import joblib
import numpy as np
from lightgbm import LGBMRegressor

from app.forecasting.features import FeatureBuilder
from app.schemas import FeatureContribution

GROUPS = {"text_pc": "caption_semantics", "visual_pc": "visual_content"}


def _group(name: str) -> str:
    """Map a raw column name to its interpretable feature group."""
    for prefix, group in GROUPS.items():
        if name.startswith(prefix):
            return group
    return name


class EngagementForecaster:
    """Predicts log(engagement / creator baseline) and explains predictions with SHAP-style contributions."""

    def __init__(self, version: str = "lgbm-1", seed: int = 7) -> None:
        self.version = version
        self.builder = FeatureBuilder()
        self.model = LGBMRegressor(n_estimators=400, learning_rate=0.04, num_leaves=15, min_child_samples=12, subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0, random_state=seed, verbose=-1)
        self.columns: list[str] = []

    def fit(self, rows: list[dict], y: np.ndarray) -> "EngagementForecaster":
        """Fit the feature builder and the regressor."""
        X = self.builder.fit(rows).transform(rows)
        self.columns = list(X.columns)
        self.model.fit(X, np.asarray(y, dtype=float))
        return self

    def _matrix(self, rows: list[dict]):
        """Build the aligned feature matrix for inference."""
        return self.builder.transform(rows).reindex(columns=self.columns, fill_value=0.0)

    def predict(self, rows: list[dict]) -> np.ndarray:
        """Predict the relative log engagement for each row."""
        return self.model.predict(self._matrix(rows))

    def explain(self, rows: list[dict], top_k: int = 6) -> list[list[FeatureContribution]]:
        """Return the top signed feature contributions for each row using LightGBM's native SHAP values."""
        X = self._matrix(rows)
        contrib = self.model.predict(X, pred_contrib=True)[:, :-1]
        out = []
        for i in range(len(rows)):
            grouped: dict[str, list[float]] = {}
            for j, col in enumerate(self.columns):
                g = _group(col)
                entry = grouped.setdefault(g, [0.0, float(X.iloc[i, j])])
                entry[0] += float(contrib[i, j])
                if g == col:
                    entry[1] = float(X.iloc[i, j])
            ranked = sorted(grouped.items(), key=lambda kv: abs(kv[1][0]), reverse=True)[:top_k]
            out.append([FeatureContribution(feature=k, value=round(v[1], 4), contribution=round(v[0], 4)) for k, v in ranked])
        return out

    def save(self, path: Path) -> None:
        """Persist the forecaster to disk."""
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, path)

    @staticmethod
    def load(path: Path) -> "EngagementForecaster":
        """Load a persisted forecaster."""
        return joblib.load(path)


def to_value(baseline: float, relative: float) -> float:
    """Convert a relative log prediction back to an absolute weighted engagement value."""
    return float((baseline + 1.0) * math.exp(relative) - 1.0)
