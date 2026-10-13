"""Why do a few games come back short of Steam's own review count? (fetch_reviews_increment.py check)

For each game: split its planned window into monthly bins, ask Steam's query_summary for each bin, and compare
with the fetched reviews in that bin (by timestamp_created). Then, on the bin with the largest gap, page through
it again with different filters to see which reviews Steam counts but does not list.
Only counts are printed. Usage: uv run python scripts/diagnose_short_games.py [appid ...]
"""
import glob
import json
import sys
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from fetch_reviews_increment import FIRST_REVIEW, OUT, PLAN, REV, Transport, base_params

MONTH = 30 * 86400


def summary(tr, appid, s, e, **extra):
    p = base_params(s, e, n=0)
    p.update(extra)
    return int((tr.get(appid, p).get("query_summary") or {}).get("total_reviews") or 0)


def listed(tr, appid, s, e, **extra):
    ids, cursor, seen = set(), "*", set()
    while True:
        p = base_params(s, e, cursor)
        p.update(extra)
        d = tr.get(appid, p)
        revs = d.get("reviews") or []
        ids |= {int(r["recommendationid"]) for r in revs}
        cursor = d.get("cursor")
        if not revs or not cursor or cursor in seen:
            return ids
        seen.add(cursor)


def main():
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    apps = [int(a) for a in sys.argv[1:]] or [int(a) for a in json.loads((OUT / "recheck.json").read_text())]
    tr = Transport()
    for a in apps:
        ts = [t for t in plan["tasks"] if t["appid"] == a]
        lo = min(t["start"] for t in ts) or 1199145600  # full history: start at 2008-01-01, before FIRST_REVIEW
        hi = max(t["end"] for t in ts) or plan["made"]
        df = pd.concat([pd.read_parquet(f) for f in glob.glob(str(REV / f"{a}_*.parquet"))]).drop_duplicates("rec_id")
        bins = [(s, min(s + MONTH, hi + 1) - 1) for s in range(lo, hi + 1, MONTH)]
        with ThreadPoolExecutor(32) as pool:
            steam = list(pool.map(lambda b: summary(tr, a, *b), bins))
        rows = []
        for (s, e), n in zip(bins, steam):
            got = int(((df.timestamp_created >= s) & (df.timestamp_created <= e)).sum())
            rows.append((s, e, n, got))
        tot_s, tot_g = sum(r[2] for r in rows), sum(r[3] for r in rows)
        print(f"\n{a}: window {pd.to_datetime(lo, unit='s'):%Y-%m-%d}..{pd.to_datetime(hi, unit='s'):%Y-%m-%d}; "
              f"Steam bins sum {tot_s:,}, fetched {tot_g:,} ({tot_g / max(1, tot_s):.1%}); fetched before "
              f"FIRST_REVIEW {(df.timestamp_created < FIRST_REVIEW).sum()}", flush=True)
        gaps = sorted(rows, key=lambda r: r[3] - r[2])[:5]
        for s, e, n, got in gaps:
            print(f"  bin {pd.to_datetime(s, unit='s'):%Y-%m}: Steam {n:,}, fetched {got:,}, gap {n - got:,}")
        s, e, n, got = gaps[0]
        if n - got <= 0:
            continue
        ours = set(df.rec_id[(df.timestamp_created >= s) & (df.timestamp_created <= e)])
        for label, extra in [("recent (as crawled)", {}), ("updated", {"filter": "updated"}),
                             ("offtopic shown", {"filter_offtopic_activity": 0}),
                             ("positive only", {"review_type": "positive"}), ("negative only", {"review_type": "negative"})]:
            cnt = summary(tr, a, s, e, **extra)
            ids = listed(tr, a, s, e, **extra)
            print(f"  worst bin, {label:20s}: summary {cnt:,}, listed {len(ids):,}, listed but not in our files "
                  f"{len(ids - ours):,}", flush=True)
    print(dict(tr.stats))


if __name__ == "__main__":
    main()
