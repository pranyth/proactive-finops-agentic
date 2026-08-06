"""AI-service domain: dataset, recommendations and the Lambda audit trail."""

from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from agents.storage import get_connection
from api.main import app


class AIFinOpsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)

    def test_summary_exposes_normalized_ai_dataset(self) -> None:
        response = self.client.get("/api/ai-finops/summary")
        self.assertEqual(response.status_code, 200)
        profile = response.json()["profile"]
        self.assertEqual(profile["primary_service"], "Amazon Bedrock")
        self.assertEqual(profile["providers"], 3)
        self.assertGreater(profile["usage_events"], 7000)
        self.assertIn("normalized SQLite", profile["storage"])

    def test_model_rightsizing_question_returns_matching_actions(self) -> None:
        response = self.client.post(
            "/api/query",
            json={"question": "Which workloads can use a smaller model?"},
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["domain"], "ai_services")
        self.assertEqual(body["intent"], "model_rightsizing")
        self.assertTrue(body["decisions"])
        self.assertTrue(
            all(
                row["action"] in {"SWITCH_TO_SMALLER_MODEL", "REDUCE_OUTPUT_TOKENS"}
                for row in body["decisions"]
            )
        )

    def test_quality_floor_is_carried_as_evidence(self) -> None:
        """A cost recommendation must always ship the quality it is risking."""
        body = self.client.post(
            "/api/query", json={"question": "Which workloads can use a smaller model?"}
        ).json()
        labels = {metric["label"] for metric in body["decisions"][0]["metrics"]}
        self.assertIn("Quality", labels)
        quality = next(m for m in body["decisions"][0]["metrics"] if m["label"] == "Quality")
        self.assertIn("floor", quality["detail"])

    def test_bedrock_event_creates_lambda_audit_records(self) -> None:
        response = self.client.post("/api/ai-finops/demo-run")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(all(item["status"] == "processed" for item in response.json()["decisions"]))
        with get_connection() as conn:
            ai_actions = conn.execute("SELECT COUNT(1) FROM ai_action_history").fetchone()[0]
            lambda_logs = conn.execute(
                "SELECT COUNT(1) FROM serverless_action_logs WHERE trigger_type = ?",
                ("event_bus",),
            ).fetchone()[0]
        self.assertGreater(ai_actions, 0)
        self.assertGreater(lambda_logs, 0)


if __name__ == "__main__":
    unittest.main()
