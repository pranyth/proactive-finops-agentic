"""The merged platform: domain routing, the shared decision contract, fleet reads."""

from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from agents.unified import AI_SERVICES, BOTH, INFRASTRUCTURE, classify_domain
from api.main import app

# Every decision, from either analyst, must carry all of these.
DECISION_FIELDS = {
    "id", "domain", "domain_label", "resource", "resource_kind", "application",
    "provider", "environment", "action", "action_label", "tone", "savings_usd",
    "monthly_cost_usd", "confidence", "risk", "reason", "business_impact",
    "metrics", "lambda_function", "action_payload", "approval_required",
}


class DomainRoutingTests(unittest.TestCase):
    def test_machine_questions_route_to_infrastructure(self) -> None:
        for question in [
            "Which VMs can be shut down during low peak hours?",
            "Which servers are using too much memory?",
            "show me idle instances",
            "Which VMs need scale up?",
        ]:
            self.assertEqual(classify_domain(question), INFRASTRUCTURE, question)

    def test_model_questions_route_to_ai_services(self) -> None:
        for question in [
            "How can we optimize Amazon Bedrock cost safely?",
            "Where are we wasting input or output tokens?",
            "Which workloads can use a smaller model?",
            "is prompt caching enabled anywhere?",
        ]:
            self.assertEqual(classify_domain(question), AI_SERVICES, question)

    def test_broad_cost_questions_reach_both_domains(self) -> None:
        for question in [
            "Where can we save the most money across the estate?",
            "reduce my cloud bill",
            "how do I cut costs",
        ]:
            self.assertEqual(classify_domain(question), BOTH, question)

    def test_word_boundaries_prevent_false_matches(self) -> None:
        # "dbt" must not fire the "db" term, nor "vmware" the "vm" term.
        self.assertEqual(classify_domain("what does the dbt pipeline cost"), BOTH)


class QueryContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)

    def ask(self, question: str, **extra) -> dict:
        response = self.client.post("/api/query", json={"question": question, **extra})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_infrastructure_question_returns_vm_decisions(self) -> None:
        body = self.ask("Which VMs can be shut down during low peak hours?")
        self.assertEqual(body["domain"], INFRASTRUCTURE)
        self.assertTrue(body["decisions"])
        first = body["decisions"][0]
        self.assertEqual(first["resource_kind"], "Virtual machine")
        self.assertEqual(first["action"], "SCHEDULE_SHUTDOWN")
        self.assertTrue(first["lambda_function"])

    def test_both_domains_merge_into_one_ranked_list(self) -> None:
        body = self.ask("Where can we save the most money across the estate?")
        self.assertEqual(body["domain"], BOTH)
        domains = {row["domain"] for row in body["decisions"]}
        self.assertEqual(domains, {INFRASTRUCTURE, AI_SERVICES})

        savings = [row["savings_usd"] for row in body["decisions"]]
        self.assertEqual(savings, sorted(savings, reverse=True), "decisions must be ranked by savings")

        totals = body["totals"]
        self.assertAlmostEqual(
            totals["savings_usd"],
            totals["infrastructure_savings_usd"] + totals["ai_savings_usd"],
            places=2,
        )
        self.assertEqual(len(body["routes"]), 2)

    def test_decision_contract_is_identical_across_domains(self) -> None:
        body = self.ask("Where can we save the most money across the estate?")
        by_domain = {}
        for row in body["decisions"]:
            by_domain.setdefault(row["domain"], row)
        self.assertEqual(len(by_domain), 2)
        for domain, row in by_domain.items():
            self.assertEqual(set(row), DECISION_FIELDS, f"{domain} decision shape drifted")
            self.assertTrue(row["metrics"], f"{domain} decision has no evidence")
            for metric in row["metrics"]:
                self.assertEqual(set(metric), {"label", "value", "detail"})

    def test_caller_can_pin_the_domain(self) -> None:
        body = self.ask("where can we save money", domain=INFRASTRUCTURE)
        self.assertEqual(body["domain"], INFRASTRUCTURE)
        self.assertEqual(body["routing"], "explicit")
        self.assertTrue(all(row["domain"] == INFRASTRUCTURE for row in body["decisions"]))

    def test_application_health_questions_return_application_rows(self) -> None:
        body = self.ask("Which applications are degraded?")
        kinds = {row["resource_kind"] for row in body["decisions"]}
        self.assertIn("Application", kinds)

    def test_short_question_is_rejected(self) -> None:
        self.assertEqual(self.client.post("/api/query", json={"question": "hi"}).status_code, 422)


class FleetReadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)

    def test_overview_sums_both_domains(self) -> None:
        body = self.client.get("/api/overview").json()
        estate, infra, ai = body["estate"], body["infrastructure"], body["ai_services"]
        self.assertAlmostEqual(
            estate["monthly_cost_usd"],
            infra["monthly_cost_usd"] + ai["monthly_cost_usd"],
            places=2,
        )
        self.assertAlmostEqual(
            estate["savings_usd"], infra["savings_usd"] + ai["savings_usd"], places=2
        )
        self.assertEqual(estate["resources"], infra["resources"] + ai["deployments"])

    def test_infra_summary_exposes_all_four_utilization_signals(self) -> None:
        kpi = self.client.get("/api/infra/summary").json()["kpi"]
        for signal in ["avg_cpu", "avg_memory", "avg_disk", "avg_network"]:
            self.assertGreater(kpi[signal], 0, signal)
        self.assertGreater(kpi["resources"], 0)

    def test_resource_detail_returns_four_series(self) -> None:
        summary = self.client.get("/api/infra/summary").json()
        detail = self.client.get(f"/api/infra/resource/{summary['resources'][0]}").json()
        for signal in ["cpu_percent", "memory_percent", "disk_percent", "network_percent"]:
            self.assertGreater(len(detail["series"][signal]), 1, signal)
        self.assertEqual(len(detail["timestamps"]), len(detail["series"]["cpu_percent"]))

    def test_unknown_resource_is_a_404(self) -> None:
        self.assertEqual(self.client.get("/api/infra/resource/does-not-exist").status_code, 404)

    def test_demo_run_drives_both_event_paths(self) -> None:
        body = self.client.post("/api/demo-run").json()
        published = {event["event_type"] for event in body["published_events"]}
        self.assertEqual(published, {"telemetry.received", "ai.usage.received"})
        self.assertTrue(all(item["status"] == "processed" for item in body["decisions"]))


if __name__ == "__main__":
    unittest.main()
