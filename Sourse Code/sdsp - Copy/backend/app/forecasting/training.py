"""Training and cross-platform evaluation routines for the forecaster."""
import numpy as np

from app.evaluation.metrics import forecast_metrics
from app.forecasting.model import EngagementForecaster


def split(rows: list[dict], y: np.ndarray, test_frac: float = 0.2, seed: int = 7):
    """Randomly split rows and targets into train and test partitions."""
    idx = np.random.default_rng(seed).permutation(len(rows))
    cut = int(len(rows) * (1 - test_frac))
    tr, te = idx[:cut], idx[cut:]
    return [rows[i] for i in tr], y[tr], [rows[i] for i in te], y[te]


def evaluate_in_platform(rows: list[dict], y: np.ndarray) -> dict:
    """Train on a random 80 percent split and report test metrics for the model and a zero baseline."""
    Xtr, ytr, Xte, yte = split(rows, y)
    model = EngagementForecaster().fit(Xtr, ytr)
    return {"model": forecast_metrics(yte, model.predict(Xte)), "creator_baseline": forecast_metrics(yte, np.zeros_like(yte))}


def evaluate_cross_platform(rows: list[dict], y: np.ndarray) -> dict:
    """Train on all platforms except one and test on the held-out platform for every platform."""
    results = {}
    for held in sorted({r["platform"] for r in rows}):
        tr = [i for i, r in enumerate(rows) if r["platform"] != held]
        te = [i for i, r in enumerate(rows) if r["platform"] == held]
        if len(tr) < 30 or len(te) < 10:
            continue
        model = EngagementForecaster().fit([rows[i] for i in tr], y[tr])
        results[held] = forecast_metrics(y[te], model.predict([rows[i] for i in te]))
    return results
