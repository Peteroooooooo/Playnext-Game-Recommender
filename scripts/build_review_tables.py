"""Derived review tables from the merged reviews (build_reviews_merged.py), replacing the Kaggle-2024 builds.

Reviewers with user_hash % 10 == 0 are held out for offline evaluation and never enter the tables below.
- eval_reviews100m_test.parquet  held-out reviewers' reviews: user_hash, app_id, date, voted_up, hours (at review),
                                 hours_total (playtime_forever)
- colike_reviews100m.parquet     card statistics, same format as before: app_id, neighbor, sim, co_count
                                 (sim = co_count / sqrt(n_i n_j), co_count >= 5, top 200 per game)
- ease_reviews100m.npz           EASE weights for the co-like channel (Steck 2019, lambda 10,000):
                                 items (appids), B (float32, row = anchor game, column = candidate), n (positives)
- playtime_reference_100m.parquet  per game: n reviewers with playtime > 0 (positive and negative reviews),
                                 median_hours, q (101 quantiles of hours, 0..100%) for the playtime percentile
Only aggregates are printed.
Usage: uv run python scripts/build_review_tables.py   (about 10 minutes, ~10 GB RAM)
"""
import time

import numpy as np
import pandas as pd
import pyarrow.dataset as ds
import scipy.sparse as sp

from check_keys import ROOT

MERGED = ROOT / "data" / "derived" / "reviews_merged"
DER = ROOT / "data" / "derived"
TOP_K, MIN_CO, LAMBDA, MIN_PLAYERS = 200, 5, 10_000, 50


def load(columns):
    return ds.dataset(str(MERGED), format="parquet").to_table(columns=columns).to_pandas()


def cooccurrence(user, item, n_items, chunk=4_000_000):
    """Binary user x item matrix -> dense item x item co-occurrence counts (float64) and per-item counts."""
    users, r = np.unique(user, return_inverse=True)
    X = sp.csr_matrix((np.ones(len(r), np.float32), (r, item)), shape=(len(users), n_items))
    X.data[:] = 1.0  # duplicates collapse to binary
    C = np.zeros((n_items, n_items))
    for i in range(0, X.shape[0], chunk):
        x = X[i:i + chunk]
        C += (x.T @ x).toarray()
    return C, np.asarray(X.sum(axis=0)).ravel()


def ease(C, lam=LAMBDA):
    G = C.copy()
    G[np.diag_indices_from(G)] += lam
    P = np.linalg.inv(G)
    B = -P / np.diag(P)
    np.fill_diagonal(B, 0)
    return B.astype(np.float32)


def main():
    t0 = time.time()
    # each stage reads only the columns it needs, so the 160M-row table is never fully in memory
    df = load(["user_hash", "appid", "voted_up", "timestamp_created", "playtime_forever", "playtime_at_review"])
    test = (df["user_hash"].to_numpy() % 10) == 0
    print(f"reviews {len(df):,}; held out {test.mean():.1%} of reviews ({time.time() - t0:.0f}s)", flush=True)
    t = df[test]
    del df
    pd.DataFrame({"user_hash": t["user_hash"].to_numpy(), "app_id": t["appid"].to_numpy(),
                  "date": pd.to_datetime(t["timestamp_created"].to_numpy(), unit="s"),
                  "voted_up": t["voted_up"].to_numpy(),
                  "hours": (t["playtime_at_review"].to_numpy() / 60).astype("float32"),
                  "hours_total": (t["playtime_forever"].to_numpy() / 60).astype("float32")}
                 ).to_parquet(DER / "eval_reviews100m_test.parquet", index=False)
    print(f"held-out reviewers {t['user_hash'].nunique():,}, reviews {len(t):,} -> eval_reviews100m_test.parquet", flush=True)
    del t

    df = load(["user_hash", "appid", "playtime_forever"])
    keep = ((df["user_hash"].to_numpy() % 10) != 0) & (df["playtime_forever"].to_numpy() > 0)
    app, mins = df["appid"].to_numpy()[keep], df["playtime_forever"].to_numpy()[keep]
    del df, keep
    o = np.lexsort((mins, app))
    app, mins = app[o], mins[o]
    del o
    starts = np.flatnonzero(np.r_[True, app[1:] != app[:-1]])
    ends = np.r_[starts[1:], len(app)]
    rows = []
    for s, e in zip(starts, ends):
        if e - s >= MIN_PLAYERS:
            q = (np.quantile(mins[s:e], np.linspace(0, 1, 101)) / 60).astype("float32")  # values already sorted
            rows.append({"app_id": int(app[s]), "n": int(e - s), "median_hours": float(q[50]), "q": q})
    del app, mins
    ref = pd.DataFrame(rows)
    ref.to_parquet(DER / "playtime_reference_100m.parquet", index=False)
    print(f"playtime reference: {len(ref):,} games with >= {MIN_PLAYERS} reviewers who played ({time.time() - t0:.0f}s)",
          flush=True)

    df = load(["user_hash", "appid", "voted_up"])
    keep = ((df["user_hash"].to_numpy() % 10) != 0) & df["voted_up"].to_numpy()
    user, app = df["user_hash"].to_numpy()[keep], df["appid"].to_numpy()[keep]
    del df, keep
    items = np.unique(app)
    C, n = cooccurrence(user, np.searchsorted(items, app), len(items))
    print(f"train positives {len(user):,} on {len(items):,} games; co-occurrence ready ({time.time() - t0:.0f}s)", flush=True)
    del user, app

    np.savez(DER / "ease_reviews100m.npz", items=items.astype(np.int32), B=ease(C), n=n.astype(np.int64))
    print(f"EASE lambda={LAMBDA} -> ease_reviews100m.npz ({time.time() - t0:.0f}s)", flush=True)

    np.fill_diagonal(C, 0)
    sim = C / np.sqrt(np.outer(n, n))
    sim[C < MIN_CO] = 0
    out = []
    for i in range(len(items)):
        nz = np.flatnonzero(sim[i])
        if len(nz):
            top = nz[np.argsort(-sim[i, nz])[:TOP_K]]
            out.append(pd.DataFrame({"app_id": items[i], "neighbor": items[top], "sim": sim[i, top].astype("float32"),
                                     "co_count": C[i, top].astype("int32")}))
    out = pd.concat(out, ignore_index=True)
    out.to_parquet(DER / "colike_reviews100m.parquet", index=False)
    per = out.groupby("app_id").size()
    games = pd.read_parquet(ROOT / "data" / "processed" / "games.parquet", columns=["appid", "release_year"])
    nb = per.reindex(games["appid"]).fillna(0).to_numpy()
    yr = games["release_year"].to_numpy()
    print(f"colike_reviews100m.parquet: games with >= 1 neighbour {len(per):,}; >= 20 {(per >= 20).sum():,} of "
          f"{len(games):,} core games")
    for label, m in [("<= 2022", yr <= 2022), ("2023", yr == 2023), ("2024", yr == 2024), ("2025", yr == 2025),
                     ("2026", yr == 2026), ("unknown", pd.isna(yr))]:
        if m.sum():
            print(f"  released {label:>8}: {m.sum():>5} games, >= 20 neighbours {(nb[m] >= 20).mean():.0%}")
    print(f"done {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
