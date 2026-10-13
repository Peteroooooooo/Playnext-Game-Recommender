"""Are Steam's early empty review pages deterministic or node-dependent?

Repeats the same request (same window, same cursor) many times through the rotating proxy and counts how often
it comes back with reviews. Only counts are printed.
Usage: uv run python scripts/diagnose_empty_pages.py APPID START_DATE END_DATE [REPEATS]
"""
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from fetch_reviews_increment import Transport, base_params


def main():
    a = int(sys.argv[1])
    s = int(pd.Timestamp(sys.argv[2], tz="UTC").timestamp())
    e = int(pd.Timestamp(sys.argv[3], tz="UTC").timestamp()) - 1
    reps = int(sys.argv[4]) if len(sys.argv) > 4 else 20
    tr = Transport()
    cursor, seen, n = "*", set(), 0
    while True:  # walk the window, keeping the cursor that first gives an empty page
        with ThreadPoolExecutor(reps) as pool:
            res = list(pool.map(lambda _: tr.get(a, base_params(s, e, cursor)), range(reps)))
        sizes = Counter(len(d.get("reviews") or []) for d in res)
        full = [d for d in res if d.get("reviews")]
        if len(full) < reps:
            print(f"page after {n:,} reviews: {reps} identical requests -> page sizes {dict(sizes)}", flush=True)
        if not full:
            break
        d = full[0]
        n += len(d["reviews"])
        nxt = {x.get("cursor") for x in full}
        if len(nxt) > 1:
            print(f"  different cursors returned for the same request: {len(nxt)}", flush=True)
        cursor = d.get("cursor")
        if not cursor or cursor in seen:
            break
        seen.add(cursor)
    total = int(tr.get(a, base_params(s, e, n=0))["query_summary"]["total_reviews"])
    print(f"{a} {sys.argv[2]}..{sys.argv[3]}: walked {n:,} reviews, Steam says {total:,}; {dict(tr.stats)}")


if __name__ == "__main__":
    main()
