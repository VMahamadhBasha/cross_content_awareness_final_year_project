"""Run repeatable offline evaluation against the configured database."""
import argparse
import json
import math

from sqlalchemy import select

from app.db import init_db, session_scope
from app.evaluation.metrics import backtest_forecasts, grounding_rate, latency_summary
from app.models import Recommendation, RecommendationFeedback
from app.config import get_settings


def evaluate_recommendations(session) -> dict:
    """Summarize stored recommendation grounding, latency, fallback, and creator ratings."""
    recommendations = list(
        session.scalars(
            select(Recommendation).where(Recommendation.event_id.is_not(None))
        )
    )
    ratings = list(
        session.scalars(
            select(RecommendationFeedback)
            .join(Recommendation)
            .where(Recommendation.event_id.is_not(None))
        )
    )
    return {
        "count": len(recommendations),
        "latency": latency_summary(
            [
                recommendation.latency_ms
                for recommendation in recommendations
                if recommendation.latency_ms is not None
            ]
        ),
        "grounding": grounding_rate(
            [recommendation.grounding_score for recommendation in recommendations],
            get_settings().grounding_threshold,
        ),
        "fallback_share": (
            sum(recommendation.fallback_used for recommendation in recommendations)
            / len(recommendations)
            if recommendations
            else 0.0
        ),
        "usefulness": {
            "rated": len(ratings),
            "helpful": sum(rating.helpful for rating in ratings),
            "helpful_share": (
                sum(rating.helpful for rating in ratings) / len(ratings)
                if ratings
                else 0.0
            ),
        },
    }


def json_safe(value):
    """Convert undefined correlation values to JSON null."""
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--kind",
        choices=("all", "recommendations", "forecasts"),
        default="all",
        help="Which stored results to evaluate; no provider calls are made.",
    )
    parser.add_argument(
        "--horizon-days",
        type=int,
        default=7,
        help="Minimum age of the actual forecast outcome snapshot (default: 7).",
    )
    parser.add_argument(
        "--max-lag-days",
        type=int,
        default=30,
        help="Maximum delay after the target horizon for an observed snapshot.",
    )
    args = parser.parse_args()
    if args.horizon_days < 1 or args.max_lag_days < 0:
        parser.error("horizon-days must be positive and max-lag-days non-negative")

    init_db()
    result = {}
    with session_scope() as session:
        if args.kind in ("all", "recommendations"):
            result["recommendations"] = evaluate_recommendations(session)
        if args.kind in ("all", "forecasts"):
            result["forecast_backtest"] = backtest_forecasts(
                session, args.horizon_days, args.max_lag_days
            )
    print(json.dumps(json_safe(result), indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
