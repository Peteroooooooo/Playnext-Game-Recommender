"""Fill what Kaggle steam-reviews-100m lacks before each game's crawl window (Data_Sources.md source 5).

Kaggle holds only reviews with purchase_type=steam (every row has steam_purchase=True), and very big games are cut
short (CS2: 0.54M of 4.56M). The crawl uses purchase_type=all, so without a fill the data would change its make-up
at the crawl start. Kaggle period of a game = up to one second before its crawl window (fetch_reviews_increment).
  measure      per game: Steam's counts (majority vote) for steam and non-Steam purchases vs what we hold
               -> data/raw/steam_reviews_increment/kaggle_gaps.json
  nonsteam     fetch every non-Steam-purchase review of the Kaggle period (key activations etc.), then refine
  steam [MIN]  for games whose Steam-purchase reviews are short by >= MIN (default 50) against Kaggle plus earlier
               fills, refetch the short bins (refine: years and months counted, weeks, days, hours fetched)
Files go to data/raw/steam_reviews_increment/kaggle_gaps/<appid>_<start>_<end>_{n,s}.parquet (hashed like the crawl);
build_reviews_merged.py merges them by rec_id.
Usage: uv run python scripts/fill_kaggle_gaps.py measure|nonsteam|steam [MIN]
"""
import json
import sys
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import pyarrow.parquet as pq

from build_reviews_merged import KAGGLE, core_ids
from fetch_reviews_increment import EARLIEST, OUT, Transport, fetch_task, refine, slices, steam_count, windows

GAPS = OUT / "kaggle_gaps"
REPORT = OUT / "kaggle_gaps.json"
COLS = ["rec_id", "appid", "timestamp_created"]
WORKERS = 160


def kaggle_reviews():
    core = core_ids()
    parts = [pq.read_table(f, columns=COLS, filters=[("appid", "in", core)]).to_pandas()
             for f in sorted(KAGGLE.rglob("steam_reviews_*.parquet"))]
    return pd.concat(parts, ignore_index=True).drop_duplicates("rec_id")


def gap_files(tag):
    if not GAPS.exists():
        return pd.DataFrame(columns=COLS)
    parts = [pd.read_parquet(f, columns=COLS) for f in GAPS.glob(f"*_{tag}.parquet") if pq.read_schema(f).names]
    return pd.concat(parts, ignore_index=True).drop_duplicates("rec_id") if parts else pd.DataFrame(columns=COLS)


def periods():
    """Kaggle period per game: from before the oldest review to the second before its crawl window starts."""
    return {a: (EARLIEST, s - 1) for a, (s, e) in windows().items() if s > EARLIEST}


def in_period(df, per):
    n = {}
    for a, g in df.groupby("appid")["timestamp_created"]:
        if a in per:
            n[int(a)] = int(((g >= per[a][0]) & (g <= per[a][1])).sum())
    return n


def measure():
    per = periods()
    tr = Transport()
    with ThreadPoolExecutor(WORKERS) as pool:
        steam = list(pool.map(lambda a: steam_count(tr, a, *per[a], purchase="steam"), per))
        other = list(pool.map(lambda a: steam_count(tr, a, *per[a], purchase="non_steam_purchase"), per))
    have_s = in_period(pd.concat([kaggle_reviews(), gap_files("s")]).drop_duplicates("rec_id"), per)
    have_n = in_period(gap_files("n"), per)
    rep = {str(a): {"steam": s, "have_steam": have_s.get(a, 0), "non_steam": n, "have_non_steam": have_n.get(a, 0)}
           for a, s, n in zip(per, steam, other)}
    REPORT.write_text(json.dumps(rep), encoding="utf-8")
    S, HS = sum(steam), sum(have_s.values())
    N, HN = sum(other), sum(have_n.values())
    short = [r["steam"] - r["have_steam"] for r in rep.values() if r["steam"] > r["have_steam"]]
    print(f"Kaggle period of {len(per):,} games:\n  Steam purchases: Steam {S:,}, held {HS:,} ({HS / max(1, S):.2%}); "
          f"games short {len(short):,} (sum {sum(short):,}), short by >= 50: {sum(g >= 50 for g in short):,} "
          f"(sum {sum(g for g in short if g >= 50):,})\n  non-Steam purchases: Steam {N:,}, held {HN:,} "
          f"({HN / max(1, N):.2%})\n  requests {dict(tr.stats)}", flush=True)
    big = sorted(rep.items(), key=lambda x: x[1]["have_steam"] - x[1]["steam"])[:8]
    print("  largest Steam-purchase gaps:", [(a, r["have_steam"], r["steam"]) for a, r in big], flush=True)


def nonsteam():
    rep = json.loads(REPORT.read_text(encoding="utf-8"))
    per = periods()
    GAPS.mkdir(parents=True, exist_ok=True)
    todo = [dict(x, tag="n", dir=GAPS, purchase="non_steam_purchase")
            for a, r in rep.items() if r["non_steam"]
            for x in slices(int(a), *per[int(a)], r["non_steam"], slice_pages=20)]
    todo = [t for t in todo if not (GAPS / f"{t['appid']}_{t['start']}_{t['end']}_n.parquet").exists()]
    todo.sort(key=lambda t: -t["reviews"])
    tr = Transport()
    print(f"non-Steam purchases: {len(todo):,} windows, ~{sum(t['reviews'] for t in todo):,} reviews", flush=True)
    done = [0]

    def one(t):
        try:
            fetch_task(tr, t, None)
        except RuntimeError:
            pass
        done[0] += 1
        if done[0] % 2000 == 0:
            print(f"  {done[0]:,}/{len(todo):,} windows; {dict(tr.stats)}", flush=True)

    with ThreadPoolExecutor(WORKERS) as pool:
        list(pool.map(one, todo))
    held = gap_files("n")
    have = in_period(held, per)
    short = {int(a): [per[int(a)]] for a, r in rep.items() if have.get(int(a), 0) < r["non_steam"]}
    print(f"fetched {len(held):,}; games short {len(short):,}; refining", flush=True)
    refine(tr, short, lambda: gap_files("n"), "n", GAPS, WORKERS, "non_steam_purchase")


def steam(min_gap=50):
    rep = json.loads(REPORT.read_text(encoding="utf-8"))
    per = periods()
    short = {int(a): [per[int(a)]] for a, r in rep.items() if r["steam"] - r["have_steam"] >= min_gap}
    print(f"Steam purchases: refining {len(short):,} games short by >= {min_gap}", flush=True)
    GAPS.mkdir(parents=True, exist_ok=True)
    kg = kaggle_reviews()
    refine(Transport(), short, lambda: pd.concat([kg, gap_files("s")]).drop_duplicates("rec_id"), "s", GAPS,
           WORKERS, "steam", fetch_from=7 * 86400)  # months of huge games are 300+ pages: fetch by week


if __name__ == "__main__":
    {"measure": measure, "nonsteam": nonsteam,
     "steam": lambda: steam(int(sys.argv[2]) if len(sys.argv) > 2 else 50)}[sys.argv[1]]()
