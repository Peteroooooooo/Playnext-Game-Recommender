"""Offline comparison for the co-like channel: item cosine (current design) vs EASE.

Same data and split as build_review_tables.py (merged steam-reviews-100m + crawl): positive reviews of core games,
reviewer IDs hashed, hash % 10 == 0 held out. Train matrix = the other 90%. For a sample of held-out reviewers with
>= 5 positive reviews, the earlier half (by review time) is the profile, the later half is the target.
Methods, all scoring every core game and excluding profile games:
  popularity   : number of train positives
  cosine-max   : max over profile games of co_count / sqrt(n_i n_j)   (multi-interest max, as in 5.5)
  cosine-sum   : sum of the same similarities                          (classic item-kNN)
  ease-<lam>   : EASE (Steck, WWW 2019): B = I - P diagMat(1 / diag(P)), P = (X'X + lam I)^-1
Prints Recall@20 and NDCG@20 with bootstrap 95% CIs. Only aggregates are printed.
Optional argument N: long-tail variant that removes the N most popular games from both the candidates and the
targets, so a method cannot score by recommending what everybody plays anyway.
Optional second argument M: profile is the first M games instead of the earlier half (M = 1 mimics "like <seed>").
Usage: uv run python scripts/eval_ease.py [N] [M]   (about 10 minutes, needs ~16 GB RAM)
"""
import sys
import time

import numpy as np
import scipy.sparse as sp

from build_review_tables import load as load_merged

K, SAMPLE, SEED = 20, 50_000, 0
LAMBDAS = [1_000, 10_000, 50_000]
EXCLUDE_TOP = int(sys.argv[1]) if len(sys.argv) > 1 else 0  # long-tail variant: drop the N most popular games
PROFILE_N = int(sys.argv[2]) if len(sys.argv) > 2 else 0  # 1 = single-seed variant: profile is the first game only


def load():
    """Positives as (reviewer row, appid, timestamp) plus the held-out mask (hash % 10 == 0)."""
    df = load_merged(["user_hash", "appid", "voted_up", "timestamp_created"])
    df = df[df["voted_up"]]
    uh, row = np.unique(df["user_hash"].to_numpy(), return_inverse=True)
    return row, df["appid"].to_numpy(), df["timestamp_created"].to_numpy(), ((uh % 10) == 0)[row]


def metrics(scores, prof_rows, targets, banned=None):
    scores = scores.copy()
    for r, p in enumerate(prof_rows):
        scores[r, p] = -np.inf
    if banned is not None:
        scores[:, banned] = -np.inf
    top = np.argpartition(-scores, K, axis=1)[:, :K]
    order = np.take_along_axis(scores, top, 1).argsort(axis=1)[:, ::-1]
    top = np.take_along_axis(top, order, 1)
    disc = 1 / np.log2(np.arange(2, K + 2))
    rec, ndcg = [], []
    for r, t in enumerate(targets):
        hit = np.isin(top[r], t)
        rec.append(hit.sum() / min(K, len(t)))
        ndcg.append((hit * disc).sum() / disc[:min(K, len(t))].sum())
    return np.array(rec), np.array(ndcg)


def ci(x, rng):
    b = [x[rng.integers(0, len(x), len(x))].mean() for _ in range(300)]
    return f"{x.mean():.4f} [{np.percentile(b, 2.5):.4f}, {np.percentile(b, 97.5):.4f}]"


def main():
    t0 = time.time()
    row, app, ts, test_mask = load()
    items = np.array(sorted(np.unique(app)))
    col = np.searchsorted(items, app)
    print(f"loaded {len(row):,} positives, {len(items):,} games ({time.time() - t0:.0f}s)", flush=True)

    tr_users, r = np.unique(row[~test_mask], return_inverse=True)
    X = sp.csr_matrix((np.ones(len(r), np.float32), (r, col[~test_mask])), shape=(len(tr_users), len(items)))
    X.data[:] = 1.0
    n = np.asarray(X.sum(axis=0)).ravel().astype(np.float64)
    C = (X.T @ X).toarray().astype(np.float64)
    del X, tr_users, r
    print(f"train co-occurrence ready ({time.time() - t0:.0f}s)", flush=True)

    # held-out users: time split
    t_row, t_col, t_ts = row[test_mask], col[test_mask], ts[test_mask]
    del row, col, ts, app
    o = np.lexsort((t_ts, t_row))
    t_row, t_col = t_row[o], t_col[o]
    starts = np.flatnonzero(np.r_[True, t_row[1:] != t_row[:-1]])
    ends = np.r_[starts[1:], len(t_row)]
    ok = np.flatnonzero(ends - starts >= 5)
    rng = np.random.default_rng(SEED)
    pick = rng.choice(ok, size=min(SAMPLE, len(ok)), replace=False)
    prof, targ = [], []
    for u in pick:
        seq = t_col[starts[u]:ends[u]]
        _, first = np.unique(seq, return_index=True)
        seq = seq[np.sort(first)]
        h = PROFILE_N or len(seq) // 2
        if h < 1 or len(seq) - h < 1:
            continue
        prof.append(seq[:h]); targ.append(seq[h:])
    banned = None
    if EXCLUDE_TOP:
        banned = np.argsort(-n)[:EXCLUDE_TOP]
        kept = [(p, t[~np.isin(t, banned)]) for p, t in zip(prof, targ)]
        kept = [(p, t) for p, t in kept if len(t)]
        prof, targ = [p for p, _ in kept], [t for _, t in kept]
        print(f"long-tail variant: top {EXCLUDE_TOP} popular games removed from candidates and targets", flush=True)
    print(f"eval users {len(prof):,} (of {len(ok):,} held-out reviewers with >=5 positives)", flush=True)
    P = sp.csr_matrix((np.ones(sum(map(len, prof)), np.float32),
                       (np.repeat(np.arange(len(prof)), [len(p) for p in prof]), np.concatenate(prof))),
                      shape=(len(prof), len(items)))

    S = C / np.sqrt(np.outer(n, n))
    np.fill_diagonal(S, 0)
    S[C < 5] = 0
    S = S.astype(np.float32)
    results = {}
    results["popularity"] = metrics(np.tile(n.astype(np.float32), (len(prof), 1)), prof, targ, banned)
    results["cosine-sum"] = metrics(np.asarray(P @ S), prof, targ, banned)
    cmax = np.stack([S[p].max(axis=0) for p in prof])
    results["cosine-max"] = metrics(cmax, prof, targ, banned)
    del cmax
    for lam in LAMBDAS:
        G = C.copy()
        G[np.diag_indices_from(G)] += lam
        Pinv = np.linalg.inv(G)
        B = -Pinv / np.diag(Pinv)
        np.fill_diagonal(B, 0)
        results[f"ease-{lam}"] = metrics(np.asarray(P @ B.astype(np.float32)), prof, targ, banned)
        print(f"  ease lambda={lam} done ({time.time() - t0:.0f}s)", flush=True)
    rng = np.random.default_rng(1)
    for name, (rec, nd) in results.items():
        print(f"{name:12s} Recall@{K} {ci(rec, rng)}   NDCG@{K} {ci(nd, rng)}")
    base = results["cosine-max"]
    for name, (rec, nd) in results.items():
        if name.startswith("ease"):
            d = rec - base[0]
            print(f"{name} - cosine-max Recall@{K} diff {ci(d, rng)}")
    print(f"done {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
