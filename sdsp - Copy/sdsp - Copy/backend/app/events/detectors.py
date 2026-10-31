"""Pure event detectors for under-performance and comment surges."""
import math
from dataclasses import dataclass

import numpy as np


@dataclass
class Detection:
    """A detected event with the numbers that triggered it."""

    kind: str
    payload: dict


def growth_curve(hours: float, tau: float = 8.0, horizon: float = 24.0) -> float:
    """Expected fraction of the horizon engagement already accumulated after the given hours."""
    return min(1.0, (1.0 - math.exp(-max(hours, 0.0) / tau)) / (1.0 - math.exp(-horizon / tau)))


def detect_underperformance(observed: float, baseline: float, predicted_relative: float, hours: float, ratio_threshold: float, min_hours: float) -> Detection | None:
    """Fire when observed engagement is far below the forecast trajectory."""
    if hours < min_hours or hours > 48:
        return None
    expected_final = (baseline + 1.0) * math.exp(predicted_relative) - 1.0
    expected_now = expected_final * growth_curve(hours)
    if expected_now <= 0:
        return None
    ratio = observed / expected_now
    if ratio < ratio_threshold:
        return Detection("underperformance", {"observed": round(observed, 1), "expected_now": round(expected_now, 1), "ratio": round(ratio, 3), "hours": round(hours, 2), "expected_final": round(expected_final, 1)})
    return None


def detect_comment_surge(series: list[tuple[float, int]], z_threshold: float, min_new: int) -> Detection | None:
    """Fire when the latest comment rate is a statistical outlier versus the post's earlier rates."""
    if len(series) < 4:
        return None
    rates, news = [], []
    for (h0, c0), (h1, c1) in zip(series, series[1:]):
        dt = max(h1 - h0, 1e-3)
        rates.append(max(c1 - c0, 0) / dt)
        news.append(max(c1 - c0, 0))
    latest, history = rates[-1], np.asarray(rates[:-1])
    spread = max(float(history.std()), 0.5 * float(history.mean()), 1.0)
    z = (latest - float(history.mean())) / spread
    if news[-1] >= min_new and z >= z_threshold:
        return Detection("comment_surge", {"new_comments": int(news[-1]), "rate_per_hour": round(latest, 2), "typical_rate_per_hour": round(float(history.mean()), 2), "z_score": round(z, 2), "hours": round(series[-1][0], 2)})
    return None
