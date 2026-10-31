"""Evaluation metrics for forecasting, recommendation grounding and latency."""
import numpy as np
from scipy.stats import spearmanr

from app.models import EngagementSnapshot, ForecastRecord, Post


def forecast_metrics(y_true, y_pred) -> dict[str, float]:
    """Return Spearman rank correlation, MAE and RMSE for a set of predictions."""
    y_true, y_pred = np.asarray(y_true, dtype=float), np.asarray(y_pred, dtype=float)
    rho = spearmanr(y_true, y_pred).statistic if len(y_true) > 2 and np.ptp(y_pred) > 0 else float("nan")
    return {"spearman": float(rho), "mae": float(np.mean(np.abs(y_true - y_pred))), "rmse": float(np.sqrt(np.mean((y_true - y_pred) ** 2))), "n": int(len(y_true))}


def backtest_forecasts(
    session,
    horizon_days: int = 7,
    max_lag_days: int = 30,
) -> dict:
    """Compare timely stored predictions with the first snapshot at a post-age horizon."""
    from datetime import timedelta

    from sqlalchemy import select

    from app.repository import relative_performance

    forecasts = list(
        session.scalars(select(ForecastRecord).order_by(ForecastRecord.created_at))
    )
    actual_values, predicted_values = [], []
    actual_relative, predicted_relative = [], []
    forecasts_after_horizon = 0
    for forecast in forecasts:
        post = session.get(Post, forecast.post_id)
        if post is None:
            continue
        target_time = post.published_at + timedelta(days=horizon_days)
        if forecast.created_at > target_time:
            forecasts_after_horizon += 1
            continue
        latest_allowed = target_time + timedelta(days=max_lag_days)
        snapshot = session.scalar(
            select(EngagementSnapshot)
            .where(
                EngagementSnapshot.post_id == forecast.post_id,
                EngagementSnapshot.captured_at >= target_time,
                EngagementSnapshot.captured_at <= latest_allowed,
            )
            .order_by(EngagementSnapshot.captured_at)
            .limit(1)
        )
        if snapshot is None:
            continue
        actual_values.append(float(snapshot.weighted))
        predicted_values.append(float(forecast.predicted_value))
        actual_relative.append(relative_performance(snapshot.weighted, forecast.baseline))
        predicted_relative.append(float(forecast.predicted_relative))

    if not actual_values:
        return {
            "horizon_days": horizon_days,
            "max_lag_days": max_lag_days,
            "available_forecasts": len(forecasts),
            "forecasts_after_horizon": forecasts_after_horizon,
            "evaluated": 0,
            "spearman": None,
            "relative_mae": None,
            "relative_rmse": None,
            "engagement_mae": None,
            "engagement_rmse": None,
        }
    relative_metrics = forecast_metrics(actual_relative, predicted_relative)
    engagement_metrics = forecast_metrics(actual_values, predicted_values)
    return {
        "horizon_days": horizon_days,
        "max_lag_days": max_lag_days,
        "available_forecasts": len(forecasts),
        "forecasts_after_horizon": forecasts_after_horizon,
        "evaluated": len(actual_values),
        "spearman": relative_metrics["spearman"],
        "relative_mae": relative_metrics["mae"],
        "relative_rmse": relative_metrics["rmse"],
        "engagement_mae": engagement_metrics["mae"],
        "engagement_rmse": engagement_metrics["rmse"],
    }


def latency_summary(latencies_ms: list[float]) -> dict[str, float]:
    """Return count, mean, p50, p95 and max of event-to-recommendation latencies."""
    if not latencies_ms:
        return {"count": 0, "mean_ms": 0.0, "p50_ms": 0.0, "p95_ms": 0.0, "max_ms": 0.0}
    arr = np.asarray(latencies_ms, dtype=float)
    return {"count": int(len(arr)), "mean_ms": float(arr.mean()), "p50_ms": float(np.percentile(arr, 50)), "p95_ms": float(np.percentile(arr, 95)), "max_ms": float(arr.max())}


def grounding_rate(scores: list[float], threshold: float = 0.8) -> dict[str, float]:
    """Return the mean grounding score and the share of recommendations meeting the threshold."""
    if not scores:
        return {"mean_score": 0.0, "grounded_share": 0.0}
    arr = np.asarray(scores, dtype=float)
    return {"mean_score": float(arr.mean()), "grounded_share": float((arr >= threshold).mean())}
