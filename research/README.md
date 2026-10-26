# Multi-horizon capacity forecasting study

The research half of the project. The question: **where does the standard
choice for cloud capacity forecasting, a Random Forest on recent utilisation,
stop working as the horizon grows from a month to a year, and what fixes
it?**

## Reproduce

```bash
python tools/fetch_wikimedia_traces.py       # real data: 12 Wikimedia projects, hourly, 2016-2025 (~3 min)
python tools/generate_capacity_history.py    # synthetic: 54 machines x 36 months, known growth regimes
python research/run_experiments.py           # rolling-origin backtest, every model x horizon (~45 min, 10 cores)
python research/analyze.py                   # tables -> results/, figures -> figures/
```

`run_experiments.py --quick` runs 6 series per dataset as a smoke test.

## Data

| Dataset | Series | Length | Why |
|---|---|---|---|
| Wikimedia pageviews (real) | 12 projects | 10 years, hourly → daily peak | Public VM traces (Azure, Google, Alibaba) cover 8–31 days and cannot validate a 12-month forecast. Wikipedia request volume is the standard real web workload in the autoscaling literature, and contains real growth, decline, seasonality and the 2020 COVID shock. |
| Synthetic fleet | 54 machines | 36 months, hourly → daily peak | Controlled experiment: each machine follows a labelled growth regime (flat, linear, exponential, step, decline, quarterly), so accuracy can be reported per regime. |

Demand is expressed as % of current capacity and is **not clipped at 100**:
forecasting demand that exceeds capacity is the point. Wikimedia series are
scaled so the first year's busiest hour ran at 60% of capacity.

## Method

- **Target:** the peak of the 7-day window ending *h* days after the forecast
  origin, for h = 30, 91, 182, 365 days: the monthly review, quarterly plan,
  half-year budget and annual budget (also the term of a 1-year savings plan).
- **Rolling origin:** at each origin every model is retrained on data up to that
  day only. Synthetic origins every 14 days after a 1-year warm-up; Wikimedia
  every 28 days after 2 years.
- **Models** (all in `agents/capacity.py`, the same code the console runs):

| Model | What it is |
|---|---|
| Persistence | Last week's peak. The baseline every forecast must beat. |
| Linear trend | OLS on the trailing year of weekly peaks, extrapolated. |
| Random Forest | 120 trees on absolute levels, direct h-step. The standard choice and the project's original 24 h model. |
| Trend + RF | Trend carries the level; the forest learns only the residual shape. |
| Trend + RF + OOB margin | The above plus the 90th percentile of out-of-bag errors: the usual "forecast plus safety margin" practice. |
| Trend + quantile GBM (p90) | Trend plus gradient boosting with pinball loss at q = 0.9 on the residual. |

- **Scored by the decision, not only the distance.** MAE; under-forecast rate;
  breach recall and false alarms at 80% of capacity; capture of targets beyond
  anything in the training history; and an asymmetric cost where a shortfall
  costs *k* times a surplus. For linear costs the optimal forecast is the
  k/(k+1) quantile (the newsvendor result), so p90 is optimal at k = 9.

## Outputs

- `results/forecasts_<dataset>.csv`: one row per series, horizon and origin, with every model's forecast.
- `results/metrics_by_horizon.csv`, `results/metrics_by_regime.csv`
- `figures/fig1`–`fig7`
- `paper/paper.tex`: IEEE conference draft built from these numbers.
