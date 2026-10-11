"""Build the core-library candidate list from SteamSpy 'all' pages.

Fetches pages 0, 1, 2, ... (1 request / 60 s per SteamSpy's limit), caches each
page under data/raw/steamspy/, and stops after two consecutive pages with fewer
than STOP_BELOW games at or above the review threshold.
Writes data/core_candidates.json: [{appid, name, positive, negative}].
Usage: python scripts/fetch_core_list.py [--min-reviews 1000]
"""
import argparse
import json
import time

from check_keys import ROOT, request

RAW = ROOT / "data" / "raw" / "steamspy"
OUT = ROOT / "data" / "core_candidates.json"
STOP_BELOW = 5


def page(p):
    f = RAW / f"all_{p:03d}.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8")), False
    for attempt in range(3):
        st, d = request(f"https://steamspy.com/api.php?request=all&page={p}")
        if st == 200 and isinstance(d, dict):
            RAW.mkdir(parents=True, exist_ok=True)
            f.write_text(json.dumps(d), encoding="utf-8")
            return d, True
        time.sleep(65)
    raise RuntimeError(f"SteamSpy page {p} failed: HTTP {st}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-reviews", type=int, default=1000)
    args = ap.parse_args()
    core, low_streak, p = {}, 0, 0
    while low_streak < 2:
        d, fetched = page(p)
        hits = [v for v in d.values() if v["positive"] + v["negative"] >= args.min_reviews]
        for v in hits:
            core[v["appid"]] = {k: v[k] for k in ("appid", "name", "positive", "negative")}
        print(f"page {p}: {len(d)} apps, {len(hits)} >= {args.min_reviews} reviews, total {len(core)}", flush=True)
        low_streak = low_streak + 1 if len(hits) < STOP_BELOW else 0
        if not d:
            break
        p += 1
        if fetched:
            time.sleep(61)
    OUT.write_text(json.dumps(sorted(core.values(), key=lambda x: -(x["positive"] + x["negative"]))), encoding="utf-8")
    print(f"done: {len(core)} candidates -> {OUT}")


if __name__ == "__main__":
    main()
