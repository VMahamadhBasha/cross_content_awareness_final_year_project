import json
import math
import unittest
import base64
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from app.content.extractor import ContentFeatures
from app.forecasting import service as forecast_service
from app.forecasting.service import (
    ForecastProviderError,
    ForecastService,
    ForecasterNotReadyError,
)
from app import llm_client
from app.schemas import WhatIfRequest


class OpenAIForecastingTests(unittest.TestCase):
    def _service(self, api_key="configured"):
        settings = SimpleNamespace(
            openai_api_key=api_key,
            openai_model="gpt-4o-mini",
        )
        getter = patch.object(forecast_service, "get_settings", return_value=settings)
        getter.start()
        self.addCleanup(getter.stop)
        return ForecastService()

    @staticmethod
    def _features():
        return ContentFeatures(
            descriptors={
                "hour": 12.0,
                "caption_words": 8.0,
                "has_question": 0.0,
                "has_cta": 0.0,
                "hashtag_count": 0.0,
            },
            text_embedding=[],
        )

    def test_forecast_uses_openai_multiplier_and_validated_explanation(self):
        service = self._service()
        captured = {}

        def fake_chat(system_prompt, user_prompt):
            captured["prompt"] = json.loads(user_prompt)
            return json.dumps(
                {
                    "relative_multiplier": 1.25,
                    "explanation": [
                        {"feature": "caption_words", "contribution": 0.15},
                    ],
                }
            )

        with patch.object(forecast_service, "chat_completion_json", side_effect=fake_chat):
            result = service.forecast(
                "youtube",
                self._features(),
                baseline=20.0,
                followers=1000,
                caption="A real draft",
            )

        self.assertAlmostEqual(result.predicted_relative, math.log(1.25))
        self.assertAlmostEqual(result.predicted_value, 25.25)
        self.assertEqual(result.explanation[0].feature, "caption_words")
        self.assertEqual(result.explanation[0].value, 8.0)
        self.assertEqual(result.model_version, "openai:gpt-4o-mini:mm1")
        self.assertEqual(captured["prompt"]["caption"], "A real draft")
        self.assertEqual(captured["prompt"]["creator_baseline_weighted_engagement"], 20.0)

    def test_forecast_sends_image_and_embedding_inputs_when_available(self):
        service = self._service()
        captured = {}

        def fake_chat(system_prompt, user_prompt, image_url=None):
            captured["prompt"] = json.loads(user_prompt)
            captured["image_url"] = image_url
            return json.dumps(
                {
                    "relative_multiplier": 1.0,
                    "explanation": [{"feature": "caption_words", "contribution": 0.0}],
                }
            )

        with patch.object(forecast_service, "chat_completion_json", side_effect=fake_chat):
            service.forecast(
                "instagram",
                self._features(),
                baseline=20.0,
                followers=1000,
                caption="A draft",
                image_url="data:image/png;base64,aW1hZ2U=",
            )

        self.assertEqual(captured["image_url"], "data:image/png;base64,aW1hZ2U=")
        self.assertEqual(captured["prompt"]["text_embedding"], [])
        self.assertIsNone(captured["prompt"]["visual_embedding"])

    def test_thumbnail_forwarding_only_accepts_known_https_cdn_hosts(self):
        self.assertEqual(
            ForecastService._safe_thumbnail_url(
                "https://i.ytimg.com/vi/example/hqdefault.jpg"
            ),
            "https://i.ytimg.com/vi/example/hqdefault.jpg",
        )
        self.assertIsNone(ForecastService._safe_thumbnail_url(None))
        with self.assertRaisesRegex(ValueError, "supported media CDN"):
            ForecastService._safe_thumbnail_url("http://127.0.0.1/private")
        with self.assertRaisesRegex(ValueError, "supported media CDN"):
            ForecastService._safe_thumbnail_url("https://attacker.example/image.jpg")

    def test_what_if_rejects_invalid_image_data(self):
        with self.assertRaisesRegex(ValueError, "does not match"):
            WhatIfRequest(
                creator_id=1,
                platform="instagram",
                caption="Draft",
                image_data_url=(
                    "data:image/png;base64,"
                    + base64.b64encode(b"not an image").decode("ascii")
                ),
            )

        WhatIfRequest(
            creator_id=1,
            platform="instagram",
            caption="Draft",
            image_data_url=(
                "data:image/png;base64,"
                + base64.b64encode(b"\x89PNG\r\n\x1a\ncontent").decode("ascii")
            ),
        )

    def test_forecast_requires_configured_openai_key(self):
        service = self._service(api_key=None)
        with patch.object(
            forecast_service,
            "chat_completion_json",
            side_effect=AssertionError("OpenAI must not be called without a key"),
        ):
            with self.assertRaisesRegex(ForecasterNotReadyError, "OPENAI_API_KEY"):
                service.forecast("youtube", self._features(), baseline=20.0, followers=1000)

        self.assertFalse(service.status()["ready"])

    def test_forecast_rejects_unknown_explanation_features(self):
        service = self._service()
        output = json.dumps(
            {
                "relative_multiplier": 1.0,
                "explanation": [{"feature": "invented_metric", "contribution": 0.1}],
            }
        )
        with patch.object(forecast_service, "chat_completion_json", return_value=output):
            with self.assertLogs(forecast_service.log, level="ERROR"):
                with self.assertRaisesRegex(ForecastProviderError, "valid forecast"):
                    service.forecast(
                        "youtube", self._features(), baseline=20.0, followers=1000
                    )

    def test_what_if_requests_all_variants_once_and_returns_ranked_results(self):
        service = self._service()
        captured = {}

        def fake_chat(_, user_prompt):
            payload = json.loads(user_prompt)
            captured["payload"] = payload
            return json.dumps(
                {
                    "predictions": [
                        {
                            "label": item["label"],
                            "relative_multiplier": 1.2 if item["label"].startswith("Post at ") else 2.0,
                        }
                        for item in payload["variants"]
                    ]
                }
            )

        with patch.object(forecast_service, "chat_completion_json", side_effect=fake_chat):
            results = service.what_if_variants(
                "youtube",
                self._features(),
                baseline=20.0,
                followers=1000,
                base_rel=0.0,
                scheduled_at=datetime.now(timezone.utc),
                caption="A real draft",
            )

        self.assertGreater(len(captured["payload"]["variants"]), len(results))
        self.assertEqual(len(results), 6)
        self.assertTrue(any(item.label.startswith("Post at ") for item in results))
        self.assertEqual(results, sorted(results, key=lambda item: item.delta_pct, reverse=True))

    def test_shared_openai_client_uses_configured_model_and_json_mode(self):
        settings = SimpleNamespace(
            openai_api_key="configured-test-key",
            openai_base_url="https://api.openai.com/v1/",
            openai_model="gpt-4o-mini",
        )
        response = SimpleNamespace(
            json=lambda: {"choices": [{"message": {"content": '{"ok": true}'}}]},
            raise_for_status=lambda: None,
        )
        with patch.object(llm_client, "get_settings", return_value=settings):
            with patch.object(llm_client.httpx, "post", return_value=response) as post:
                result = llm_client.chat_completion_json("system", "user")

        self.assertEqual(result, '{"ok": true}')
        args, kwargs = post.call_args
        self.assertEqual(args[0], "https://api.openai.com/v1/chat/completions")
        self.assertEqual(
            kwargs["headers"]["Authorization"], "Bearer configured-test-key"
        )
        self.assertEqual(kwargs["json"]["model"], "gpt-4o-mini")
        self.assertEqual(kwargs["json"]["response_format"], {"type": "json_object"})

    def test_shared_openai_client_includes_multimodal_image_content(self):
        settings = SimpleNamespace(
            openai_api_key="configured-test-key",
            openai_base_url="https://api.openai.com/v1",
            openai_model="gpt-4o-mini",
        )
        response = SimpleNamespace(
            json=lambda: {"choices": [{"message": {"content": '{"ok": true}'}}]},
            raise_for_status=lambda: None,
        )
        image_url = "data:image/png;base64,cG5n"
        with patch.object(llm_client, "get_settings", return_value=settings):
            with patch.object(llm_client.httpx, "post", return_value=response) as post:
                llm_client.chat_completion_json("system", "prompt", image_url=image_url)

        content = post.call_args.kwargs["json"]["messages"][1]["content"]
        self.assertEqual(content[0], {"type": "text", "text": "prompt"})
        self.assertEqual(
            content[1],
            {"type": "image_url", "image_url": {"url": image_url, "detail": "low"}},
        )


if __name__ == "__main__":
    unittest.main()
