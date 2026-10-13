"""Merge the review sources into one table (Data_Sources.md sources 5 and 6).

- Kaggle steam-reviews-100m (exact author_id, scraped 2025-08, Steam purchases only) for core games.
- Our crawl, already hashed: data/raw/steam_reviews_increment/reviews/ (after the Kaggle scrape, and full history of
  games Kaggle lacks) and kaggle_gaps/ (non-Steam purchases and the parts Kaggle cut short, fill_kaggle_gaps.py).
Author IDs are hashed in memory with the project salt, the same function as the crawler, so one person has one
user_hash in both sources. Duplicates are removed by rec_id; when a review is in both, the crawled copy wins
(it is newer: playtime is up to date). Review text is not kept. Files are streamed twice (ids, then rows) so the
whole table never sits in memory. Also prints consistency checks on the reviews present in both sources.
Output: data/derived/reviews_merged/{kaggle,crawl}_NNN.parquet
  columns rec_id, user_hash, appid, voted_up, timestamp_created, playtime_forever, playtime_at_review (minutes),
          num_games_owned, num_reviews, language, source (0 = Kaggle, 1 = crawl); a count of 0 can mean unknown
Usage: uv run python scripts/build_reviews_merged.py   (about 20 minutes)
"""
import shutil
import time

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from check_keys import ROOT
from fetch_reviews_increment import REV, uhash

KAGGLE = ROOT / "data" / "raw" / "kaggle_reviews100m" / "extracted"
OUT = ROOT / "data" / "derived" / "reviews_merged"
COLS = ["rec_id", "appid", "voted_up", "timestamp_created", "playtime_forever", "playtime_at_review",
        "num_games_owned", "num_reviews", "language"]
TYPES = {"rec_id": "int64", "user_hash": "int64", "appid": "int32", "voted_up": "bool", "timestamp_created": "int64",
         "playtime_forever": "int32", "playtime_at_review": "int32", "num_games_owned": "int32",
         "num_reviews": "int32", "source": "int8"}
CHECK = ["rec_id", "user_hash", "appid", "voted_up", "timestamp_created", "playtime_forever"]
CHUNK = 5_000_000


def core_ids():
    return pd.read_parquet(ROOT / "data" / "processed" / "games.parquet", columns=["appid"])["appid"].astype(int).tolist()


def hash_many(ids):
    u, inv = np.unique(ids, return_inverse=True)
    h = np.fromiter((uhash(x) for x in u.tolist()), dtype=np.int64, count=len(u))
    return h[inv]


def tidy(df, source):
    df["source"] = source
    # Kaggle leaves some counts empty (num_games_owned in about half the rows); the crawl writes 0 for missing
    unknown = ["playtime_forever", "playtime_at_review", "num_games_owned", "num_reviews"]
    df[unknown] = df[unknown].fillna(0)
    df = df.astype(TYPES)
    df["language"] = df["language"].fillna("").astype(str)
    return df[["rec_id", "user_hash"] + COLS[1:] + ["source"]]


def first_mask(ids):
    """True at the first occurrence of each id."""
    _, first = np.unique(ids, return_index=True)
    keep = np.zeros(len(ids), bool)
    keep[first] = True
    return keep


def member(sorted_ids, x):
    pos = np.searchsorted(sorted_ids, x).clip(max=len(sorted_ids) - 1)
    return sorted_ids[pos] == x


class Writer:
    def __init__(self, prefix):
        self.prefix, self.buf, self.part, self.rows = prefix, [], 0, 0

    def add(self, df, force=False):
        if len(df):
            self.buf.append(df)
        if self.buf and (force or sum(map(len, self.buf)) >= CHUNK):
            out = pd.concat(self.buf, ignore_index=True)
            pq.write_table(pa.Table.from_pandas(out, preserve_index=False), OUT / f"{self.prefix}_{self.part:03d}.parquet")
            self.rows += len(out)
            self.part += 1
            self.buf = []


def main():
    t0 = time.time()
    core = core_ids()
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    cfiles = [f for d in (REV, REV.parent / "kaggle_gaps") if d.exists() for f in sorted(d.glob("*.parquet"))
              if pq.read_schema(f).names]
    cids = [pq.read_table(f, columns=["rec_id"])["rec_id"].to_numpy() for f in cfiles]
    cb = np.cumsum([0] + [len(x) for x in cids])
    call = np.concatenate(cids)
    del cids
    ckeep = first_mask(call)
    inc_ids = np.unique(call)
    print(f"crawl: {len(cfiles):,} files, {len(call):,} rows, {len(inc_ids):,} unique ({time.time() - t0:.0f}s)", flush=True)
    del call

    kfiles = sorted(KAGGLE.rglob("steam_reviews_*.parquet"))
    flt = [("appid", "in", core)]
    kids = [pq.read_table(f, columns=["rec_id"], filters=flt)["rec_id"].to_numpy() for f in kfiles]
    kb = np.cumsum([0] + [len(x) for x in kids])
    kall = np.concatenate(kids)
    del kids
    kkeep = first_mask(kall)
    k_in_c = member(inc_ids, kall)
    print(f"Kaggle: {len(kfiles)} files, {len(kall):,} core rows, {kkeep.sum():,} unique, of which also crawled "
          f"{(kkeep & k_in_c).sum():,} ({time.time() - t0:.0f}s)", flush=True)
    kkeep &= ~k_in_c
    k_ids = np.unique(kall[k_in_c])  # the overlap, for the consistency check
    del kall, inc_ids

    w, ov_k = Writer("kaggle"), []
    for i, f in enumerate(kfiles):
        t = pq.read_table(f, columns=["author_id"] + COLS, filters=flt).to_pandas()
        t["user_hash"] = hash_many(t["author_id"].to_numpy())
        both = k_in_c[kb[i]:kb[i + 1]]
        if both.any():
            ov_k.append(t.loc[both, CHECK])
        w.add(tidy(t.loc[kkeep[kb[i]:kb[i + 1]]].drop(columns="author_id"), 0))
        if i % 100 == 0:
            print(f"  Kaggle file {i}/{len(kfiles)} ({time.time() - t0:.0f}s)", flush=True)
    w.add(pd.DataFrame(), force=True)
    del kkeep, k_in_c

    wc, ov_c, core_set = Writer("crawl"), [], set(core)
    for i, f in enumerate(cfiles):
        t = pd.read_parquet(f, columns=["rec_id", "user_hash"] + COLS[1:])
        m = ckeep[cb[i]:cb[i + 1]] & t["appid"].isin(core_set).to_numpy()
        t = t.loc[m]
        both = member(k_ids, t["rec_id"].to_numpy()) if len(k_ids) else np.zeros(len(t), bool)
        if both.any():
            ov_c.append(t.loc[both, CHECK])
        wc.add(tidy(t, 1))
        if i % 10000 == 0:
            print(f"  crawl file {i:,}/{len(cfiles):,} ({time.time() - t0:.0f}s)", flush=True)
    wc.add(pd.DataFrame(), force=True)

    ov = pd.concat(ov_k).drop_duplicates("rec_id").merge(pd.concat(ov_c).drop_duplicates("rec_id"), on="rec_id",
                                                           suffixes=("_k", "_c"))
    print(f"\nreviews in both sources: {len(ov):,}")
    for c in CHECK[1:-1]:
        print(f"  same {c}: {(ov[c + '_k'] == ov[c + '_c']).mean():.4%}")
    print(f"  crawl playtime >= Kaggle playtime: {(ov['playtime_forever_c'] >= ov['playtime_forever_k']).mean():.2%}")
    print(f"merged: {w.rows + wc.rows:,} reviews ({w.rows:,} Kaggle only + {wc.rows:,} crawl) in {OUT}; "
          f"{time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
