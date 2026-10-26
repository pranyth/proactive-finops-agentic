"""Multi-horizon capacity forecasting: leak-free, able to extrapolate, wired in."""

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd
from fastapi.testclient import TestClient

from agents import capacity
from agents.capacity import Series, forecast, quantile_band, training_set
from agents.unified import CAPACITY, INFRASTRUCTURE, classify_domain
from api.main import app


def growing_series(days: int = 600, start: float = 30.0, end: float = 90.0) -> Series:
    """Steady growth plus a weekly rhythm: the case a tree ensemble cannot follow."""
    rng = np.random.default_rng(0)
    t = np.arange(days)
    daily = np.linspace(start, end, days) * (1 + 0.08 * np.sin(2 * np.pi * t / 7)) + rng.normal(0, 1, days)
    return Series(daily, pd.Timestamp("2024-01-01"))


class CapacityModelTests(unittest.TestCase):
    def test_training_targets_never_pass_the_origin(self) -> None:
        s = growing_series()
        for h in capacity.HORIZONS.values():
            train = training_set(s, 400, h)
            self.assertLessEqual(train.max() + h, 400)

    def test_trend_only_sees_the_past(self) -> None:
        s = growing_series()
        before = (s.slope[300], s.intercept[300])
        s.daily[301:] = 0.0
        recomputed = Series(s.daily, pd.Timestamp("2024-01-01"))
        self.assertAlmostEqual(recomputed.slope[300], before[0])
        self.assertAlmostEqual(recomputed.intercept[300], before[1])

    def test_hybrid_extrapolates_where_random_forest_cannot(self) -> None:
        s = growing_series()
        origin, h = len(s) - 1 - 182, 182
        result = forecast(s, origin, h, models=("rf", "hybrid", "linear"))
        seen = np.nanmax(s.wk[:origin + 1])
        actual = s.wk[origin + h]
        self.assertGreater(actual, seen)
        # A forest averages leaves it was trained on; it cannot pass the training maximum.
        self.assertLessEqual(result["rf"], seen + 1e-6)
        self.assertGreater(result["hybrid"], seen)
        self.assertLess(abs(result["hybrid"] - actual), abs(result["rf"] - actual))

    def test_quantile_band_is_ordered(self) -> None:
        band = quantile_band(growing_series(), 450, 91)
        self.assertLessEqual(band[0.1], band[0.5])
        self.assertLessEqual(band[0.5], band[0.9])

    def test_commitment_reads_the_floor_not_the_peak(self) -> None:
        horizons = [{"label": "1 month", "date": "2026-04-01", "p10": 50.0, "p50": 60.0, "p90": 70.0,
                     "breach": False},
                    {"label": "12 months", "date": "2027-03-01", "p10": 20.0, "p50": 60.0, "p90": 95.0,
                     "breach": True}]
        actions = [d["action"] for d in capacity._decisions(horizons, monthly_cost=500.0)]
        self.assertIn("PLAN_SCALE_UP", actions)
        # High p90 but a 20% floor: committing would pay for capacity that may sit idle.
        self.assertNotIn("COMMIT_CAPACITY", actions)


    def test_already_over_is_not_reported_as_a_forecast(self) -> None:
        horizons = [{"label": "1 month", "date": "2026-04-13", "p10": 85.0, "p50": 90.0, "p90": 95.0, "breach": True}]
        decisions = capacity._decisions(horizons, monthly_cost=0.0, current_peak=92.0)
        self.assertEqual([(d["horizon"], d["action"]) for d in decisions], [("now", "SCALE_UP")])


class CapacityRoutingTests(unittest.TestCase):
    def test_questions_about_the_future_route_to_capacity(self) -> None:
        for question in [
            "Which machines will run out of capacity in the next 3 months?",
            "forecast CPU for the next quarter",
            "Where is it safe to commit to a 1-year savings plan?",
            "which VMs are trending up",
        ]:
            self.assertEqual(classify_domain(question), CAPACITY, question)

    def test_present_tense_capacity_stays_with_infrastructure(self) -> None:
        self.assertEqual(classify_domain("Which VMs need more capacity?"), INFRASTRUCTURE)


class CapacityApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)

    def test_plan_covers_all_four_horizons(self) -> None:
        resource = capacity._history()["resource_id"].iloc[0]
        body = self.client.get(f"/api/capacity/{resource}").json()
        self.assertEqual([row["label"] for row in body["horizons"]], list(capacity.HORIZONS))
        for row in body["horizons"]:
            self.assertLessEqual(row["p10"], row["p90"])
        self.assertEqual(len(body["history"]["dates"]), len(body["history"]["weekly_peak"]))
        for row in body["horizons"]:
            # The shown p90 is the model's p90 plus a non-negative fleet margin.
            self.assertGreaterEqual(row["p90"], row["p90_model"])
        backtest = body["backtest"]
        self.assertEqual(len(backtest["dates"]), len(backtest["actual"]))
        self.assertEqual(set(backtest["mae"]), set(capacity.BACKTEST_MODELS))

    def test_unknown_resource_is_a_404(self) -> None:
        self.assertEqual(self.client.get("/api/capacity/nope").status_code, 404)


if __name__ == "__main__":
    unittest.main()
