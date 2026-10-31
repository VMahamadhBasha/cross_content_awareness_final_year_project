import unittest
from datetime import datetime, timedelta, timezone
import math
from types import SimpleNamespace

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.agent.grounding import verify
from app.api.routes import recommendation_feedback, remove_creator, stats
from app.db import Base
from app.events.detectors import detect_comment_surge, detect_underperformance
from app.evaluation.metrics import backtest_forecasts
from app.models import (
    Account,
    Creator,
    EngagementSnapshot,
    Event,
    ForecastRecord,
    Post,
    Recommendation,
    RecommendationFeedback,
)
from app.serializers import rec_out
from app.schemas import RecommendationFeedbackCreate


class QualityMetricsTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        creator = Creator(name="Test Creator")
        self.session.add(creator)
        self.session.flush()
        account = Account(
            creator_id=creator.id,
            platform="youtube",
            external_id="UCtest",
            handle="test",
            followers=1000,
        )
        self.session.add(account)
        self.session.flush()
        published = datetime.now(timezone.utc) - timedelta(days=20)
        post = Post(
            id="youtube:post1",
            creator_id=creator.id,
            account_id=account.id,
            platform="youtube",
            external_id="post1",
            kind="video",
            caption="Test post",
            published_at=published,
        )
        self.session.add(post)
        self.session.flush()
        event = Event(
            id="event1",
            type="new_upload",
            creator_id=creator.id,
            post_id=post.id,
        )
        self.session.add(event)
        self.session.flush()
        recommendation = Recommendation(
            event_id=event.id,
            post_id=post.id,
            creator_id=creator.id,
            summary="Try a shorter introduction.",
            actions=[],
            evidence=[],
            grounding_score=1.0,
        )
        self.session.add(recommendation)
        self.session.flush()
        self.recommendation = recommendation
        self.post = post
        self.forecast_time = datetime.now(timezone.utc) - timedelta(days=14)
        self.session.add(
            ForecastRecord(
                post_id=post.id,
                baseline=50,
                predicted_relative=0.2,
                predicted_value=61,
                explanation=[],
                cold_start=False,
                model_version="test",
                created_at=self.forecast_time,
            )
        )
        self.session.add(
            EngagementSnapshot(
                post_id=post.id,
                captured_at=published + timedelta(days=8),
                hours_since_publish=18 * 24,
                views=1000,
                likes=40,
                comments=10,
                shares=2,
                weighted=66,
            )
        )
        self.session.commit()

    def tearDown(self):
        self.session.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_underperformance_detector_respects_minimum_age(self):
        self.assertIsNone(
            detect_underperformance(0, 100, 0, 1, ratio_threshold=0.5, min_hours=2)
        )
        detection = detect_underperformance(
            0, 100, 0, 8, ratio_threshold=0.5, min_hours=2
        )
        self.assertEqual(detection.kind, "underperformance")

    def test_comment_surge_detector_fires_for_a_large_latest_jump(self):
        detection = detect_comment_surge(
            [(0, 0), (1, 1), (2, 2), (3, 20)],
            z_threshold=3,
            min_new=10,
        )
        self.assertEqual(detection.kind, "comment_surge")
        self.assertEqual(detection.payload["new_comments"], 18)

    def test_grounding_checker_rejects_unknown_evidence_ids(self):
        report = verify(
            {
                "actions": [
                    {
                        "action": "Review the post",
                        "rationale": "The post has 12 comments.",
                        "evidence": ["missing"],
                    }
                ]
            },
            [],
        )
        self.assertEqual(report.score, 0)
        self.assertIn("unknown evidence ids", report.issues[0])

    def test_grounding_checker_accepts_supported_numeric_claims(self):
        from app.agent.types import Evidence

        report = verify(
            {
                "actions": [
                    {
                        "action": "Review the post",
                        "rationale": "It has 12 comments.",
                        "evidence": ["comments"],
                    }
                ]
            },
            [Evidence("comments", "Post has 12 comments.")],
        )
        self.assertEqual(report.score, 1)

    def test_feedback_api_saves_and_updates_one_rating(self):
        first = recommendation_feedback(
            self.recommendation.id,
            RecommendationFeedbackCreate(helpful=True),
            self.session,
        )
        self.session.commit()
        second = recommendation_feedback(
            self.recommendation.id,
            RecommendationFeedbackCreate(helpful=False),
            self.session,
        )
        self.session.commit()

        ratings = list(
            self.session.scalars(select(RecommendationFeedback))
        )
        self.assertTrue(first["helpful"])
        self.assertFalse(second["helpful"])
        self.assertEqual(len(ratings), 1)
        self.assertFalse(ratings[0].helpful)
        self.assertFalse(rec_out(self.recommendation)["helpful"])

    def test_stats_endpoint_includes_latest_helpfulness_vote(self):
        recommendation_feedback(
            self.recommendation.id,
            RecommendationFeedbackCreate(helpful=True),
            self.session,
        )
        self.session.commit()
        request = SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(
                    pipeline=SimpleNamespace(
                        forecasts=SimpleNamespace(
                            status=lambda: {"model_version": "test"}
                        )
                    )
                )
            )
        )

        result = stats(request, self.session)

        self.assertEqual(result["usefulness"]["rated"], 1)
        self.assertEqual(result["usefulness"]["helpful"], 1)
        self.assertEqual(result["usefulness"]["helpful_share"], 1)

    def test_remove_creator_deletes_local_history_and_preserves_other_creators(self):
        creator_id = self.post.creator_id
        post_id = self.post.id
        recommendation_id = self.recommendation.id
        recommendation_feedback(
            recommendation_id,
            RecommendationFeedbackCreate(helpful=True),
            self.session,
        )
        other_creator = Creator(name="Other Creator")
        self.session.add(other_creator)
        self.session.flush()
        other_account = Account(
            creator_id=other_creator.id,
            platform="youtube",
            external_id="UCother",
            followers=50,
        )
        self.session.add(other_account)
        self.session.commit()

        result = remove_creator(creator_id, self.session)
        self.session.commit()

        self.assertEqual(result, {"creator_id": creator_id, "deleted": True})
        self.assertIsNone(self.session.get(Creator, creator_id))
        self.assertIsNone(self.session.get(Post, post_id))
        self.assertIsNone(self.session.get(Event, "event1"))
        self.assertIsNone(self.session.get(ForecastRecord, post_id))
        self.assertIsNone(self.session.get(Recommendation, recommendation_id))
        self.assertIsNone(self.session.get(RecommendationFeedback, recommendation_id))
        self.assertEqual(
            list(
                self.session.scalars(
                    select(EngagementSnapshot).where(
                        EngagementSnapshot.post_id == post_id
                    )
                )
            ),
            [],
        )
        self.assertIsNotNone(self.session.get(Creator, other_creator.id))
        self.assertIsNotNone(self.session.get(Account, other_account.id))

    def test_remove_creator_returns_404_for_unknown_creator(self):
        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as raised:
            remove_creator(9999, self.session)

        self.assertEqual(raised.exception.status_code, 404)

    def test_forecast_backtest_uses_observation_after_target_horizon(self):
        result = backtest_forecasts(self.session, horizon_days=7, max_lag_days=3)
        self.assertEqual(result["evaluated"], 1)
        self.assertAlmostEqual(result["engagement_mae"], 5.0)
        self.assertAlmostEqual(result["relative_mae"], abs(0.2 - math.log(67 / 51)))


if __name__ == "__main__":
    unittest.main()
