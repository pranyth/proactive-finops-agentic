"""Turn results/forecasts_<dataset>.csv into the paper's tables and figures.

Scoring follows the decision each forecast feeds, not only its distance from
the truth:

- MAE, in percentage points of capacity.
- Under-forecast rate: how often provisioning to the forecast would have
  fallen short.
- Breach recall / false alarms at the 80% capacity threshold.
- Beyond-history capture: of the targets that exceeded everything the model
  had seen, how often the forecast also went past that maximum. This is the
  failure a tree ensemble cannot avoid.
- Asymmetric cost: provisioning to the forecast wastes (f - y) when it is too
  high and costs k * (y - f) in breached SLOs when it is too low. For linear
  costs the optimal forecast is the k/(k+1) quantile of demand (the newsvendor
  result), which is why a p90 forecast is the right target when a shortfall
  costs ~9x a surplus.

Two track-record models are derived here from the backtest itself, using only
forecasts whose targets had already happened by each origin:

- selected: per series and horizon, whichever point model has the lowest past
  MAE so far.
- selected_c90: that forecast plus the 90th percentile of its past errors
  (split-conformal calibration).

Until a series has MIN_TRACK realised forecasts they fall back to the hybrid
and the p90 quantile model, and the share that did is reported.

    python research/analyze.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agents.capacity import ALL_MODELS, BREACH_PCT, HORIZONS  # noqa: E402

RESULTS = Path("research/results")
FIGURES = Path("research/figures")
COST_RATIOS = [1, 2, 4, 9, 19]
POOL = ("persistence", "linear", "rf", "hybrid")
MIN_TRACK = 6
MODELS = ALL_MODELS + ("selected", "selected_c90", "hybrid_q90_cal")
LABELS = {
    "persistence": "Persistence", "linear": "Linear trend", "rf": "Random Forest",
    "hybrid": "Trend + RF", "hybrid_oob90": "Trend + RF + OOB margin", "hybrid_q90": "Trend + quantile GBM (p90)",
    "selected": "Track-record selection", "selected_c90": "Selection + conformal p90",
    "hybrid_q90_cal": "p90 + fleet conformal margin (console)",
}
# Validated categorical order (dataviz palette, slots 1-6). Markers and dashes
# carry identity too, so the figures survive greyscale print.
STYLE = {
    "persistence": ("#2a78d6", "o", ":"), "linear": ("#eb6834", "s", "--"), "rf": ("#1baf7a", "^", "-"),
    "hybrid": ("#eda100", "D", "-"), "hybrid_oob90": ("#e87ba4", "v", "-."), "hybrid_q90": ("#008300", "P", "-"),
    "selected": ("#6250d6", "X", "-"), "selected_c90": ("#e34948", "*", "-"),
    "hybrid_q90_cal": ("#1f1f1d", "h", "--"),
}
HORIZON_LABEL = {h: label for label, h in HORIZONS.items()}


def add_track_record(df: pd.DataFrame) -> pd.DataFrame:
    out = []
    for (_, _, h), g in df.groupby(["dataset", "series", "horizon"]):
        g = g.sort_values("origin").copy()
        selected, calibrated, tracked = [], [], []
        for _, row in g.iterrows():
            past = g[g["origin"] + h <= row["origin"]]
            if len(past) < MIN_TRACK:
                selected.append(row["hybrid"])
                calibrated.append(row["hybrid_q90"])
                tracked.append(False)
                continue
            best = min(POOL, key=lambda m: (past[m] - past["actual"]).abs().mean())
            selected.append(row[best])
            calibrated.append(max(0.0, row[best] + np.quantile(past["actual"] - past[best], 0.9)))
            tracked.append(True)
        g["selected"], g["selected_c90"], g["tracked"] = selected, calibrated, tracked
        out.append(g)
    return pd.concat(out, ignore_index=True)


def add_fleet_calibration(df: pd.DataFrame) -> pd.DataFrame:
    """The console's method, scored honestly: each p90 is widened by the 90th
    percentile of the whole dataset's (actual - p90) errors known by its origin.
    Falls back to the raw p90 until MIN_TRACK errors exist."""
    df = df.copy()
    df["hybrid_q90_cal"] = df["hybrid_q90"]
    for (_, h), g in df.groupby(["dataset", "horizon"]):
        errors = (g["actual"] - g["hybrid_q90"]).to_numpy()
        origins = g["origin"].to_numpy()
        for origin in np.unique(origins):
            known = errors[origins + h <= origin]
            if len(known) >= MIN_TRACK:
                rows = g.index[origins == origin]
                df.loc[rows, "hybrid_q90_cal"] += max(0.0, float(np.quantile(known, 0.9)))
    return df


def score(group: pd.DataFrame, model: str) -> dict[str, float]:
    f, y = group[model].to_numpy(), group["actual"].to_numpy()
    over, under = np.clip(f - y, 0, None), np.clip(y - f, 0, None)
    breach = y >= BREACH_PCT
    beyond = y > group["history_max"].to_numpy()
    row = {
        "mae": np.abs(f - y).mean(),
        "bias": (f - y).mean(),
        "under_rate": (f < y).mean() * 100,
        "coverage": (f >= y).mean() * 100,
        "breach_recall": (f[breach] >= BREACH_PCT).mean() * 100 if breach.any() else np.nan,
        "false_alarm": (f[~breach] >= BREACH_PCT).mean() * 100 if (~breach).any() else np.nan,
        "beyond_n": int(beyond.sum()),
        "beyond_capture": (f[beyond] > group["history_max"].to_numpy()[beyond]).mean() * 100 if beyond.any() else np.nan,
    }
    for k in COST_RATIOS:
        row[f"cost_k{k}"] = (over + k * under).mean()
    return row


def metrics(df: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    rows = []
    for key, group in df.groupby(keys):
        key = key if isinstance(key, tuple) else (key,)
        for model in MODELS:
            rows.append({**dict(zip(keys, key)), "model": model, "n": len(group), **score(group, model)})
    out = pd.DataFrame(rows)
    # Cost relative to persistence at the same key, so datasets on different
    # scales can share a figure.
    base = out[out["model"] == "persistence"].set_index(keys)
    for k in COST_RATIOS:
        out[f"rel_cost_k{k}"] = out.apply(lambda r: r[f"cost_k{k}"] / base.loc[tuple(r[c] for c in keys), f"cost_k{k}"]
                                          if len(keys) > 1 else r[f"cost_k{k}"] / base.loc[r[keys[0]], f"cost_k{k}"], axis=1)
    return out


def _style_axes(ax) -> None:
    ax.grid(axis="y", color="#e4e3df", linewidth=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color("#9a9992")
    ax.tick_params(colors="#55544f", labelsize=8)


def _legend(fig, ax) -> None:
    handles, labels = ax.get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=3, fontsize=7, frameon=False)


def _line(ax, x, y, model) -> None:
    color, marker, dash = STYLE[model]
    ax.plot(x, y, color=color, marker=marker, linestyle=dash, linewidth=2, markersize=6, label=LABELS[model])


def figure_by_horizon(table: pd.DataFrame, column: str, ylabel: str, models, name: str,
                      reference: float | None = None) -> None:
    datasets = list(table["dataset"].unique())
    fig, axes = plt.subplots(1, len(datasets), figsize=(4.2 * len(datasets), 3.2), sharey=False, squeeze=False)
    for ax, dataset in zip(axes[0], datasets):
        part = table[table["dataset"] == dataset]
        for model in models:
            rows = part[part["model"] == model].sort_values("horizon")
            _line(ax, rows["horizon"], rows[column], model)
        if reference is not None:
            ax.axhline(reference, color="#9a9992", linewidth=0.8, linestyle="--")
        ax.set_xscale("log")
        ax.set_xticks(list(HORIZONS.values()), list(HORIZONS), fontsize=8)
        ax.minorticks_off()
        ax.set_title(f"{dataset.capitalize()}", fontsize=10, color="#1f1f1d")
        ax.set_ylabel(ylabel, fontsize=9, color="#55544f")
        _style_axes(ax)
    _legend(fig, axes[0][-1])
    fig.tight_layout(rect=(0, 0.14, 1, 1))
    fig.savefig(FIGURES / name, dpi=200)
    plt.close(fig)


def figure_cost(table: pd.DataFrame, horizon: int, models, name: str) -> None:
    datasets = list(table["dataset"].unique())
    fig, axes = plt.subplots(1, len(datasets), figsize=(4.2 * len(datasets), 3.2), squeeze=False)
    for ax, dataset in zip(axes[0], datasets):
        part = table[(table["dataset"] == dataset) & (table["horizon"] == horizon)]
        for model in models:
            row = part[part["model"] == model].iloc[0]
            _line(ax, COST_RATIOS, [row[f"rel_cost_k{k}"] for k in COST_RATIOS], model)
        ax.axhline(1.0, color="#9a9992", linewidth=0.8)
        ax.set_xscale("log")
        ax.set_xticks(COST_RATIOS, [f"{k}x" for k in COST_RATIOS], fontsize=8)
        ax.minorticks_off()
        ax.set_xlabel("Cost of a shortfall vs a surplus (k)", fontsize=9, color="#55544f")
        ax.set_ylabel("Cost relative to persistence", fontsize=9, color="#55544f")
        ax.set_title(f"{dataset.capitalize()}, {HORIZON_LABEL[horizon]} ahead", fontsize=10, color="#1f1f1d")
        _style_axes(ax)
    _legend(fig, axes[0][-1])
    fig.tight_layout(rect=(0, 0.14, 1, 1))
    fig.savefig(FIGURES / name, dpi=200)
    plt.close(fig)


def figure_example(df: pd.DataFrame, dataset: str, series: str, horizon: int, name: str) -> None:
    part = df[(df["dataset"] == dataset) & (df["series"] == series) & (df["horizon"] == horizon)].copy()
    if part.empty:
        return
    part["target_date"] = pd.to_datetime(part["origin_date"]) + pd.Timedelta(days=horizon)
    fig, ax = plt.subplots(figsize=(8.4, 3.6))
    ax.plot(part["target_date"], part["actual"], color="#1f1f1d", linewidth=2, label="Actual weekly peak")
    for model in ("rf", "linear", "hybrid_q90"):
        color, marker, dash = STYLE[model]
        ax.plot(part["target_date"], part[model], color=color, marker=marker, linestyle=dash, linewidth=1.6,
                markersize=4, label=LABELS[model])
    ax.axhline(BREACH_PCT, color="#9a9992", linewidth=0.8, linestyle="--")
    ax.text(part["target_date"].iloc[-1], BREACH_PCT + 1, f"{BREACH_PCT:.0f}% threshold", fontsize=7,
            color="#55544f", ha="right")
    ax.set_ylabel("Demand, % of capacity", fontsize=9, color="#55544f")
    ax.set_title(f"{series}: forecasts made {HORIZON_LABEL[horizon]} ahead", fontsize=10, color="#1f1f1d")
    _style_axes(ax)
    _legend(fig, ax)
    fig.tight_layout(rect=(0, 0.1, 1, 1))
    fig.savefig(FIGURES / name, dpi=200)
    plt.close(fig)


def main() -> None:
    df = pd.concat([pd.read_csv(RESULTS / f"forecasts_{name}.csv") for name in ("synthetic", "wikimedia")
                    if (RESULTS / f"forecasts_{name}.csv").exists()], ignore_index=True)
    df = add_fleet_calibration(add_track_record(df))
    print("share of forecasts with a track record:")
    print(df.groupby(["dataset", "horizon"])["tracked"].mean().mul(100).round(1).to_string(), "\n")
    FIGURES.mkdir(parents=True, exist_ok=True)

    by_horizon = metrics(df, ["dataset", "horizon"])
    by_horizon.round(3).to_csv(RESULTS / "metrics_by_horizon.csv", index=False)
    synthetic = df[df["dataset"] == "synthetic"]
    by_regime = metrics(synthetic, ["regime", "horizon"])
    by_regime.round(3).to_csv(RESULTS / "metrics_by_regime.csv", index=False)

    point = ["persistence", "linear", "rf", "hybrid", "selected"]
    upper = ["hybrid_oob90", "hybrid_q90", "selected_c90", "hybrid_q90_cal"]
    figure_by_horizon(by_horizon, "mae", "MAE (pp of capacity)", point, "fig1_mae_vs_horizon.png")
    figure_by_horizon(by_horizon[by_horizon["dataset"] == "synthetic"], "beyond_capture",
                      "Beyond-history targets caught (%)", ["persistence", "linear", "rf", "hybrid", "hybrid_q90"],
                      "fig2_beyond_history_capture.png")
    figure_by_horizon(by_horizon, "coverage", "Actual demand at or below forecast (%)", upper,
                      "fig3_p90_coverage.png", reference=90.0)
    cost_models = ["persistence", "linear", "rf", "hybrid_q90", "selected", "selected_c90"]
    figure_cost(by_horizon, HORIZONS["3 months"], cost_models, "fig4_cost_vs_ratio_3m.png")
    figure_cost(by_horizon, HORIZONS["12 months"], cost_models, "fig5_cost_vs_ratio_12m.png")
    if (df["dataset"] == "wikimedia").any():
        wiki = df[df["dataset"] == "wikimedia"]
        growth = wiki.groupby("series")["actual"].agg(lambda s: s.iloc[-1] - s.iloc[0]).idxmax()
        figure_example(df, "wikimedia", growth, HORIZONS["12 months"], "fig6_example_wikimedia_12m.png")
    fastest = synthetic[synthetic["regime"] == "exponential"].groupby("series")["actual"].max().idxmax()
    figure_example(df, "synthetic", fastest, HORIZONS["12 months"], "fig7_example_synthetic_12m.png")

    pd.set_option("display.width", 200)
    cols = ["dataset", "horizon", "model", "n", "mae", "bias", "coverage", "breach_recall", "false_alarm",
            "beyond_n", "beyond_capture", "rel_cost_k1", "rel_cost_k9"]
    print(by_horizon[cols].round(2).to_string(index=False))
    print()
    print(by_regime[by_regime["horizon"] == HORIZONS["12 months"]]
          .pivot(index="regime", columns="model", values="mae")[list(MODELS)].round(2).to_string())


if __name__ == "__main__":
    main()
