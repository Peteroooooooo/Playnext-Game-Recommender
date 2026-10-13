"""Does Steam's review paging stop early inside big time windows, and do smaller windows recover the rest?

For a game and a window: list it as one window (recording why paging stopped), then as daily / weekly bins,
and compare with Steam's query_summary. Only counts are printed.
Usage: uv run python scripts/diagnose_paging.py APPID START_DATE END_DATE [BIN_DAYS]
"""
import sys
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from fetch_reviews_increment import Transport, base_params


def listed(tr, appid, s, e):
    ids, cursor, seen, pages, last_ts = set(), "*", set(), 0, None
    while True:
        d = tr.get(appid, base_params(s, e, cursor))
        pages += 1
        revs = d.get("reviews") or []
        ids |= {int(r["recommendationid"]) for r in revs}
        if revs:
            last_ts = revs[-1]["timestamp_created"]
        nxt = d.get("cursor")
        if not revs or not nxt or nxt in seen:
            why = "empty page" if not revs else "no cursor" if not nxt else "cursor repeated"
            return ids, pages, why, last_ts
        seen.add(nxt)
        cursor = nxt


def main():
    a = int(sys.argv[1])
    s = int(pd.Timestamp(sys.argv[2], tz="UTC").timestamp())
    e = int(pd.Timestamp(sys.argv[3], tz="UTC").timestamp()) - 1
    step = int(sys.argv[4]) if len(sys.argv) > 4 else 1
    tr = Transport()
    total = int(tr.get(a, base_params(s, e, n=0))["query_summary"]["total_reviews"])
    ids, pages, why, last = listed(tr, a, s, e)
    print(f"{a} {sys.argv[2]}..{sys.argv[3]}: Steam says {total:,}; one window lists {len(ids):,} in {pages} pages, "
          f"stopped by {why}, last review at {pd.to_datetime(last, unit='s')}", flush=True)
    bins = [(x, min(x + step * 86400, e + 1) - 1) for x in range(s, e + 1, step * 86400)]
    with ThreadPoolExecutor(32) as pool:
        res = list(pool.map(lambda b: (int(tr.get(a, base_params(*b, n=0))["query_summary"]["total_reviews"]),
                                       listed(tr, a, *b)), bins))
    got = set().union(*[r[1][0] for r in res])
    short = [(b, n, len(r[0]), r[2]) for b, (n, r) in zip(bins, res) if len(r[0]) < n]
    print(f"  as {len(bins)} bins of {step} day(s): Steam bins sum {sum(r[0] for r in res):,}, listed {len(got):,}; "
          f"bins still short {len(short)}", flush=True)
    for b, n, g, why in sorted(short, key=lambda x: x[2] - x[1])[:5]:
        print(f"    {pd.to_datetime(b[0], unit='s'):%Y-%m-%d}: Steam {n:,}, listed {g:,}, stopped by {why}")
    print(dict(tr.stats))


if __name__ == "__main__":
    main()
