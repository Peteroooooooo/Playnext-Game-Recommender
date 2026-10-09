"""Coverage of the core library by the Kaggle recommendations dataset.

Joins data/core_candidates.json with data/derived/kaggle_app_stats.csv and
reports, overall and by Steam release year, how many core games have enough
positive recommendations for item-item co-occurrence.
Release years come from Steam GetItems (cached in data/derived/release_dates.json).
Usage: python scripts/kaggle_coverage.py
"""
import json
import urllib.parse
from collections import defaultdict
from datetime import datetime, timezone

import pandas as pd

from check_keys import ROOT, request

CORE = ROOT / "data" / "core_candidates.json"
STATS = ROOT / "data" / "derived" / "kaggle_app_stats.csv"
REL = ROOT / "data" / "derived" / "release_dates.json"
THRESHOLDS = (10, 50, 100)


def release_years(appids):
    cache = json.loads(REL.read_text(encoding="utf-8")) if REL.exists() else {}
    todo = [a for a in appids if str(a) not in cache]
    for i in range(0, len(todo), 100):
        inp = {"ids": [{"appid": a} for a in todo[i:i + 100]],
               "context": {"language": "english", "country_code": "US", "steam_realm": 1},
               "data_request": {"include_release": True}}
        st, d = request("https://api.steampowered.com/IStoreBrowseService/GetItems/v1/?input_json="
                        + urllib.parse.quote(json.dumps(inp)))
        if st != 200:
            continue
        for it in d["response"].get("store_items", []):
            ts = (it.get("release") or {}).get("steam_release_date")
            cache[str(it.get("appid"))] = datetime.fromtimestamp(ts, timezone.utc).year if ts else None
    REL.write_text(json.dumps(cache), encoding="utf-8")
    return {int(k): v for k, v in cache.items()}


def main():
    core = json.loads(CORE.read_text(encoding="utf-8"))
    stats = pd.read_csv(STATS, index_col="app_id")["n_pos"].to_dict()
    years = release_years([g["appid"] for g in core])

    buckets = defaultdict(lambda: [0] + [0] * len(THRESHOLDS))
    for g in core:
        y = years.get(g["appid"])
        key = "unknown" if y is None else ("<=2019" if y <= 2019 else str(y) if y <= 2022 else ">=2023")
        n = stats.get(g["appid"], 0)
        for k in (key, "ALL"):
            buckets[k][0] += 1
            for j, t in enumerate(THRESHOLDS):
                buckets[k][j + 1] += n >= t

    order = ["ALL", "<=2019", "2020", "2021", "2022", ">=2023", "unknown"]
    print(f"core candidates: {len(core)}")
    print("release      games  " + "  ".join(f">={t:<4} pos" for t in THRESHOLDS))
    for k in order:
        if k in buckets:
            tot, *hits = buckets[k]
            print(f"{k:<10} {tot:>7}  " + "  ".join(f"{h:>5} ({100 * h / tot:3.0f}%)" for h in hits))


if __name__ == "__main__":
    main()
