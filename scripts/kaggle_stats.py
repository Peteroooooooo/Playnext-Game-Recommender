"""Summarise the Kaggle 'Game Recommendations on Steam' dataset.

Reads recommendations.csv straight from the zip in chunks and writes
data/derived/kaggle_app_stats.csv (app_id, n_recs, n_pos).
Usage: python scripts/kaggle_stats.py
"""
import zipfile

import pandas as pd

from check_keys import ROOT

ZIP = ROOT / "data" / "raw" / "kaggle_recs" / "archive.zip"
OUT = ROOT / "data" / "derived" / "kaggle_app_stats.csv"


def main():
    n_rows, users_pos, dmin, dmax = 0, set(), None, None
    parts = []
    with zipfile.ZipFile(ZIP) as z, z.open("recommendations.csv") as f:
        reader = pd.read_csv(f, usecols=["app_id", "user_id", "is_recommended", "date"],
                             dtype={"app_id": "int32", "user_id": "int32"},
                             parse_dates=["date"], chunksize=5_000_000)
        for ch in reader:
            n_rows += len(ch)
            dmin = min(dmin, ch["date"].min()) if dmin is not None else ch["date"].min()
            dmax = max(dmax, ch["date"].max()) if dmax is not None else ch["date"].max()
            pos = ch[ch["is_recommended"]]
            users_pos.update(pos["user_id"].unique().tolist())
            parts.append(ch.groupby("app_id").agg(n_recs=("user_id", "size"),
                                                  n_pos=("is_recommended", "sum")))
            print(f"read {n_rows:,} rows", flush=True)
    stats = pd.concat(parts).groupby(level=0).sum()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    stats.to_csv(OUT)
    print(f"rows {n_rows:,}; apps {len(stats):,}; users with >=1 positive {len(users_pos):,}")
    print(f"date range {dmin.date()} .. {dmax.date()}")
    print(f"positive share {stats['n_pos'].sum() / stats['n_recs'].sum():.1%}")
    for t in (10, 50, 100, 500):
        print(f"apps with >= {t} positive recs: {(stats['n_pos'] >= t).sum():,}")


if __name__ == "__main__":
    main()
