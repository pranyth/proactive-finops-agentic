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


class RecommendationPolicyTests(unittest.TestCase):
    """The AI policy must stay derived from evidence, not from deployment names."""

    @classmethod
    def setUpClass(cls) -> None:
        from ai_finops.storage import recommendation_rows
        cls.rows = recommendation_rows()

    def test_quality_breach_blocks_every_cost_action(self) -> None:
        breached = [r for r in self.rows
                    if r["evidence"]["quality_score"] < r["evidence"]["quality_floor"]]
        self.assertTrue(breached, "fixture should contain a deployment under its quality floor")
        for row in breached:
            self.assertEqual(row["action"], "QUALITY_REMEDIATION")
            self.assertEqual(row["estimated_monthly_savings_usd"], 0.0)

    def test_no_model_change_on_high_criticality_or_thin_headroom(self) -> None:
        for row in self.rows:
            if row["action"] not in {"SWITCH_TO_SMALLER_MODEL", "REDUCE_OUTPUT_TOKENS"}:
                continue
            self.assertNotEqual(row["criticality"], "high", row["deployment_key"])
            self.assertGreaterEqual(row["evidence"]["quality_headroom"], 0.04, row["deployment_key"])

    def test_switch_target_clears_the_quality_floor_and_is_cheaper(self) -> None:
        from ai_finops.storage import _model_catalog, get_connection, init_ai_schema
        conn = get_connection()
        init_ai_schema(conn)
        catalog = _model_catalog(conn)
        switches = [r for r in self.rows if r["action"] == "SWITCH_TO_SMALLER_MODEL"]
        self.assertTrue(switches)
        for row in switches:
            target, current = catalog[row["target_model_key"]], catalog[row["model_key"]]
            self.assertGreaterEqual(target["quality_index"], row["evidence"]["quality_floor"])
            self.assertLess(target["input_cost_per_million"], current["input_cost_per_million"])
            self.assertGreater(row["estimated_monthly_savings_usd"], 0.0)

    def test_savings_never_claimed_without_an_action(self) -> None:
        for row in self.rows:
            if row["action"] == "NO_ACTION":
                self.assertEqual(row["estimated_monthly_savings_usd"], 0.0, row["deployment_key"])

    def test_cheap_deployments_are_left_alone(self) -> None:
        from ai_finops.storage import MIN_ACTIONABLE_COST_USD
        for row in self.rows:
            if row["action"] in {"SWITCH_TO_SMALLER_MODEL", "ENABLE_PROMPT_CACHING",
                                 "BATCH_REQUESTS", "REDUCE_OUTPUT_TOKENS"}:
                self.assertGreaterEqual(row["evidence"]["monthly_cost_usd"],
                                        MIN_ACTIONABLE_COST_USD, row["deployment_key"])
