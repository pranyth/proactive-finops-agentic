"""Download real multi-year demand traces for the capacity-forecasting study.

Public VM traces (Azure 2017/2019, Google 2019, Alibaba 2018) cover 8 to 31
days, which cannot validate a 3- or 6-month forecast. Wikimedia publishes the
hourly request volume of every project since mid-2015. Wikipedia request logs
are the standard real web workload in the autoscaling literature (WikiBench,
Urdaneta et al. 2009), and these series contain what a long-horizon model has
to survive: organic growth, decline, holiday seasonality and the 2020 COVID
shock.

Only daily aggregates are kept (peak hour, mean hour). The raw hourly series
is re-fetchable and would be ~25 MB of CSV for no analytical gain.

    python tools/fetch_wikimedia_traces.py
"""

from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

import pandas as pd

OUTPUT = Path("data/research/wikimedia_daily.csv")
PROJECTS = [
    "en.wikipedia", "de.wikipedia", "ja.wikipedia", "es.wikipedia", "fr.wikipedia",
    "ru.wikipedia", "it.wikipedia", "zh.wikipedia", "pt.wikipedia", "pl.wikipedia",
    "commons.wikimedia", "www.wikidata",
]
FIRST_YEAR, LAST_YEAR = 2016, 2025
URL = ("https://wikimedia.org/api/rest_v1/metrics/pageviews/aggregate/"
       "{project}/all-access/user/hourly/{year}010100/{year}123123")
# Wikimedia asks API clients to identify themselves.
HEADERS = {"User-Agent": "proactive-finops-agentic capacity research (github.com/pranyth)"}


def fetch_year(project: str, year: int) -> list[dict]:
    request = urllib.request.Request(URL.format(project=project, year=year), headers=HEADERS)
    for attempt in range(6):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                items = json.load(response)["items"]
            time.sleep(1.5)  # stay well under the API's rate limit
            return items
        except Exception:  # noqa: BLE001 - 429s and transient errors, retried with backoff
            if attempt == 5:
                raise
            time.sleep(10 * 2 ** attempt)
    return []


def main() -> None:
    frames = []
    for project in PROJECTS:
        items = [row for year in range(FIRST_YEAR, LAST_YEAR + 1) for row in fetch_year(project, year)]
        hourly = pd.DataFrame(items)
        hourly["timestamp"] = pd.to_datetime(hourly["timestamp"], format="%Y%m%d%H")
        daily = hourly.groupby(hourly["timestamp"].dt.normalize())["views"].agg(["max", "mean"])
        daily = daily.rename(columns={"max": "peak_hourly_views", "mean": "mean_hourly_views"})
        daily["series"] = project
        frames.append(daily.reset_index().rename(columns={"timestamp": "date"}))
        print(f"{project:<20} {len(hourly):>7,} hours -> {len(daily):>5,} days")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    out = pd.concat(frames, ignore_index=True)[["series", "date", "peak_hourly_views", "mean_hourly_views"]]
    out.to_csv(OUTPUT, index=False)
    print(f"wrote {len(out):,} rows to {OUTPUT}")


if __name__ == "__main__":
    main()
