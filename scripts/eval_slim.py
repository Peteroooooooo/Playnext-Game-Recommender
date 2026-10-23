"""Data slimming (design 10.16): how much does keeping only each game's top-K neighbours in the co-like (EASE) and
description similarity tables change the Step 3 score?

Same held-out reviewers as eval_fusion.py (test part). Production fusion: min-max over the pool, 0.90 co-like (sum)
+ 0.05 tag (sum) + 0.05 description (sum). Truncated tables: per anchor row keep the K largest entries; co-like
elsewhere = 0, description elsewhere = that row's K-th value. Reported against the full tables: Recall@20 of the
held-out positives (paired difference, bootstrap 95% CI) and the overlap of the top 20 / top 80 (the rerank input).
"group pool" restricts the pool to online co-op games, as a hard filter does, to see whether truncation leaves
filtered requests without co-like scores.
Usage: uv run python scripts/eval_slim.py [n_users]
"""
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from eval_fusion import load_users, log  # noqa: E402
from playnext import config as C  # noqa: E402
from playnext.kb import DenseKB  # noqa: E402
from playnext.rules import CAT_ONLINE_COOP  # noqa: E402

KS = (100, 200, 500, 1000)
OUT = C.DER / "eval_slim.json"
W = {"colike": 0.90, "tag": 0.05, "desc": 0.05}


def truncate(M, k, floor):
    """Keep each row's k largest entries; the rest = 0 (floor False) or the row's k-th value (floor True)."""
    part = np.argpartition(-M, k, axis=1)[:, :k]
    out = np.zeros_like(M) if not floor else np.repeat(np.take_along_axis(M, part, 1).min(1, keepdims=True), M.shape[1], 1)
    np.put_along_axis(out, part, np.take_along_axis(M, part, 1), 1)
    return out


def mm(x, pool):
    lo, hi = x[pool].min(), x[pool].max()
    return (x - lo) / (hi - lo + 1e-9)


def score(P, w, pool, tables):
    S_tag, S_desc, B = tables
    return (W["tag"] * mm(w @ S_tag[P], pool) + W["desc"] * mm(w @ S_desc[P], pool)
            + W["colike"] * mm(w @ B[P], pool))


def top(s, pool, k):
    s = np.where(pool, s, -np.inf)
    t = np.argpartition(-s, k)[:k]
    return t[np.argsort(-s[t])]


def main():
    n_users = int(sys.argv[1]) if len(sys.argv) > 1 else 4000
    kb = DenseKB()   # the description vectors (E_lang) of this historical test live on the offline KB
    _, test, _ = load_users(kb)
    test = test[:n_users]
    log("building full tables")
    S_tag = kb.T @ kb.T.T
    S_desc = None
    for E, has in kb.E_lang.values():
        s = np.where(has[:, None] & has[None, :], E @ E.T, -1.0).astype(np.float32)
        S_desc = s if S_desc is None else np.maximum(S_desc, s)
        del s
    B = kb.ease_core()
    for M, v in ((S_tag, 0.0), (S_desc, -1.0), (B, 0.0)):
        np.fill_diagonal(M, v)
    coop = np.array([CAT_ONLINE_COOP in kb.categories.get(int(a), set()) for a in kb.appids])
    log(f"online co-op games: {coop.sum():,}")
    variants = {f"K{k}": (S_tag, truncate(S_desc, k, True), truncate(B, k, False)) for k in KS}
    log("truncated tables ready")
    rng = np.random.default_rng(0)
    res = {"n_users": len(test), "settings": {}}
    for setting in ("library", "seed1", "seed2"):
        for pool_name in ("all", "group pool"):
            rec = {"full": []}
            ov = {k: ([], []) for k in variants}
            rec.update({k: [] for k in variants})
            for prof, hours, appids in test:
                m = {"seed1": 1, "seed2": 2}.get(setting, len(prof) // 2)
                P, targ = prof[:m], prof[m:]
                if setting == "library":
                    w = np.array([kb.playtime_pct(int(a), h) for a, h in zip(appids[:m], hours[:m])], dtype=object)
                    w = np.array([0.5 if x is None else x for x in w], np.float32)
                    if w.max() <= 0:
                        w[:] = 1.0
                    keep = w > 0
                    P, w = P[keep], w[keep]
                else:
                    w = np.ones(len(P), np.float32)
                pool = np.ones(kb.n, bool)
                pool[prof[:m]] = False
                if pool_name == "group pool":
                    pool &= coop
                tset = set(targ.tolist()) & set(np.flatnonzero(pool).tolist())
                full = score(P, w, pool, (S_tag, S_desc, B))
                f20, f80 = top(full, pool, 20), top(full, pool, 80)
                if tset:
                    rec["full"].append(len(tset & set(f20.tolist())) / min(20, len(tset)))
                for k, tab in variants.items():
                    s = score(P, w, pool, tab)
                    t20, t80 = top(s, pool, 20), top(s, pool, 80)
                    ov[k][0].append(len(set(t20) & set(f20)) / 20)
                    ov[k][1].append(len(set(t80) & set(f80)) / 80)
                    if tset:
                        rec[k].append(len(tset & set(t20.tolist())) / min(20, len(tset)))
            base = np.array(rec["full"])
            row = {"recall20_full": round(float(base.mean()), 4), "users_with_targets": len(base)}
            for k in variants:
                d = np.array(rec[k]) - base
                b = [d[rng.integers(0, len(d), len(d))].mean() for _ in range(500)]
                row[k] = {"recall20": round(float(np.mean(rec[k])), 4),
                          "diff": [round(float(d.mean()), 4), round(float(np.percentile(b, 2.5)), 4),
                                   round(float(np.percentile(b, 97.5)), 4)],
                          "top20_overlap": round(float(np.mean(ov[k][0])), 3),
                          "top80_overlap": round(float(np.mean(ov[k][1])), 3)}
            res["settings"][f"{setting} / {pool_name}"] = row
            log(f"{setting:8s} {pool_name:10s} full {row['recall20_full']:.4f}  " + "  ".join(
                f"{k}: {row[k]['recall20']:.4f} ov20 {row[k]['top20_overlap']:.2f} ov80 {row[k]['top80_overlap']:.2f}"
                for k in variants))
            OUT.write_text(json.dumps(res, indent=1), encoding="utf-8")
    log(f"wrote {OUT}")


if __name__ == "__main__":
    t0 = time.time()
    main()
    log(f"done in {time.time() - t0:.0f}s")
