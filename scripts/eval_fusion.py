"""Offline evaluation of the fused Step 3 score (design 5.5, section 7) and of the Step 4 ranking rules.

Held-out reviewers (hash % 10 == 0, never used for EASE or the playtime reference) with >= 5 positive reviews
of core games. Positives sorted by time; the profile is the earlier part, the targets are the rest.
Settings:
  library : profile = earlier half, anchor weight = playtime percentile of hours_total (design 4.1 / 5.5)
  uniform : same profile, every anchor weight 1.0 (checks the percentile weighting)
  seed1   : profile = first game only, weight 1.0 (mimics "games like <seed>")
  seed2   : first two games
Channels (all scored on every core game except the profile, min-max normalised per user over that pool):
  tag_max / tag_sum, desc_max / desc_sum, colike (EASE sum), lineage (same developer / series / IGDB similar).
Users are split into a dev part (weight search) and a disjoint test part (reported numbers, bootstrap 95% CI).
Only aggregates are printed; results go to data/derived/eval_fusion.json.
Usage: uv run python scripts/eval_fusion.py [features|grid|rank|all]   (all: about 30 minutes, ~20 GB RAM)
"""
import itertools
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from playnext import config as C  # noqa: E402
from playnext.kb import KB  # noqa: E402

OUT = C.DER / "eval_fusion.json"
FEAT_DIR = C.CACHE / "eval_fusion"
N_DEV, N_TEST, SEED = 8_000, 12_000, 0
TOP_PER_CHANNEL = 300
K = 20
CONT = ["tag_max", "tag_sum", "desc_max", "desc_sum", "colike"]
CHANNELS = CONT + ["lin_any", "lin_dev", "lin_ser", "lin_sim"] + ["r_" + c for c in CONT] + ["z_" + c for c in CONT]
SETTINGS = ["library", "uniform", "seed1", "seed2"]
LONGTAIL = 100


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def load_users(kb):
    t = pd.read_parquet(C.DER / "eval_reviews100m_test.parquet")
    t = t[t["voted_up"] & t["app_id"].isin(kb.pos)]
    t = t.sort_values(["user_hash", "date"])
    t = t.drop_duplicates(["user_hash", "app_id"])
    t["row"] = t["app_id"].map(kb.pos)
    g = t.groupby("user_hash")
    sizes = g.size()
    ok = sizes[sizes >= 5].index.to_numpy()
    rng = np.random.default_rng(SEED)
    pick = rng.choice(ok, size=N_DEV + N_TEST, replace=False)
    sub = t[t["user_hash"].isin(pick)]
    users = {u: (d["row"].to_numpy(), d["hours_total"].to_numpy(np.float64), d["app_id"].to_numpy())
             for u, d in sub.groupby("user_hash")}
    order = [u for u in pick]
    log(f"held-out reviewers with >=5 core positives: {len(ok):,}; sampled {len(order):,}")
    return [users[u] for u in order[:N_DEV]], [users[u] for u in order[N_DEV:]], len(ok)


def lineage_matrices(kb):
    n = kb.n
    out = {}
    for name, groups in (("dev", kb.apps_by_dev.values()), ("ser", kb.apps_by_series.values())):
        M = np.zeros((n, n), bool)
        for apps in groups:
            ix = [kb.pos[a] for a in apps if a in kb.pos]
            if len(ix) > 1:
                M[np.ix_(ix, ix)] = True
        np.fill_diagonal(M, False)
        out[name] = M
    M = np.zeros((n, n), bool)
    for a, sims in kb.similar_of.items():
        if a in kb.pos:
            M[kb.pos[a], [kb.pos[s] for s in sims if s in kb.pos]] = True
    out["sim"] = M
    return out


def build_features(kb, users, setting, mats):
    S_tag, S_desc, B, L = mats
    n = kb.n
    rows = []
    for prof_rows, hours, appids in users:
        m = {"seed1": 1, "seed2": 2}.get(setting, len(prof_rows) // 2)
        P, targ = prof_rows[:m], prof_rows[m:]
        if setting == "library":
            w = np.array([kb.playtime_pct(int(a), h) for a, h in zip(appids[:m], hours[:m])], dtype=object)
            w = np.array([0.5 if x is None else x for x in w], np.float32)
            if w.max() <= 0:
                w[:] = 1.0
            keep = w > 0
            P, w = P[keep], w[keep]
        else:
            w = np.ones(len(P), np.float32)
        pool = np.ones(n, bool)
        pool[prof_rows[:m]] = False
        f = {}
        st = S_tag[P] * w[:, None]
        f["tag_max"], f["tag_sum"] = st.max(0), st.sum(0)
        sd = S_desc[P] * w[:, None]
        f["desc_max"], f["desc_sum"] = sd.max(0), sd.sum(0)
        f["colike"] = w @ B[P]
        f["lin_dev"] = L["dev"][P].any(0).astype(np.float32)
        f["lin_ser"] = L["ser"][P].any(0).astype(np.float32)
        f["lin_sim"] = L["sim"][P].any(0).astype(np.float32)
        f["lin_any"] = np.maximum(np.maximum(f["lin_dev"], f["lin_ser"]), f["lin_sim"])
        npool = pool.sum()
        for c in ("tag_max", "tag_sum", "desc_max", "desc_sum", "colike"):
            x = f[c]
            xp = x[pool]
            lo, hi = xp.min(), xp.max()
            # percentile within the pool (1 = best) and z-score, as alternatives to min-max
            r = np.empty(n, np.float32)
            r[np.flatnonzero(pool)[np.argsort(xp, kind="stable")]] = np.arange(npool) / (npool - 1)
            f["r_" + c] = r
            f["z_" + c] = (x - xp.mean()) / (xp.std() + 1e-9)
            f[c] = (x - lo) / (hi - lo + 1e-9)
        cand = set()
        for c in ("tag_max", "tag_sum", "desc_max", "desc_sum", "colike"):
            s = np.where(pool, f[c], -np.inf)
            cand.update(np.argpartition(-s, TOP_PER_CHANNEL)[:TOP_PER_CHANNEL].tolist())
        lin = np.flatnonzero(pool & (f["lin_any"] > 0))
        if len(lin):
            cand.update(lin[np.argsort(-f["colike"][lin])[:100]].tolist())
        cand = np.array(sorted(cand))
        rows.append((cand, np.stack([f[c][cand] for c in CHANNELS], 1).astype(np.float16),
                     np.isin(cand, targ), targ))
    width = max(len(r[0]) for r in rows)
    U = len(rows)
    idx = np.full((U, width), -1, np.int32)
    X = np.zeros((U, width, len(CHANNELS)), np.float16)
    hit = np.zeros((U, width), bool)
    ntarg = np.zeros(U, np.int32)
    ntarg_lt = np.zeros(U, np.int32)
    pop_top = set(np.argsort(-kb.popularity)[:LONGTAIL].tolist())
    for u, (cand, x, h, targ) in enumerate(rows):
        idx[u, :len(cand)], X[u, :len(cand)], hit[u, :len(cand)] = cand, x, h
        ntarg[u] = len(targ)
        ntarg_lt[u] = sum(1 for t in targ if int(t) not in pop_top)
    return idx, X, hit, ntarg, ntarg_lt


def topk(score, idx, k):
    s = np.where(idx >= 0, score, -np.inf)
    t = np.argpartition(-s, k, axis=1)[:, :k]
    o = np.take_along_axis(s, t, 1).argsort(axis=1)[:, ::-1]
    return np.take_along_axis(t, o, 1)


def metrics(score, idx, hit, ntarg, k=K, banned=None, ntarg_lt=None):
    if banned is not None:
        score = np.where(np.isin(idx, banned), -np.inf, score)
        ntarg = ntarg_lt
    top = topk(score, idx, k)
    h = np.take_along_axis(hit, top, 1)
    disc = 1 / np.log2(np.arange(2, k + 2))
    denom = np.minimum(k, np.maximum(ntarg, 1))
    rec = h.sum(1) / denom
    idcg = np.cumsum(disc)[denom - 1]
    ndcg = (h * disc).sum(1) / idcg
    ok = ntarg > 0
    return rec[ok], ndcg[ok]


def fuse(X, w):
    """w: dict channel -> weight."""
    s = np.zeros(X.shape[:2], np.float32)
    for c, v in w.items():
        if v:
            s += v * X[:, :, CHANNELS.index(c)].astype(np.float32)
    return s


def rrf(X, chans, rho=60, npool=7300):
    """Reciprocal rank fusion from the stored pool percentiles (rank 1 = best)."""
    s = np.zeros(X.shape[:2], np.float32)
    for c in chans:
        r = X[:, :, CHANNELS.index("r_" + c)].astype(np.float32)
        s += 1 / (rho + (1 - r) * (npool - 1) + 1)
    return s


def ci(x, rng, n=500):
    b = [x[rng.integers(0, len(x), len(x))].mean() for _ in range(n)]
    return [round(float(x.mean()), 4), round(float(np.percentile(b, 2.5)), 4), round(float(np.percentile(b, 97.5)), 4)]


def simplex(step, dims):
    k = round(1 / step)
    for c in itertools.product(range(k + 1), repeat=dims - 1):
        if sum(c) <= k:
            yield [x * step for x in c] + [(k - sum(c)) * step]


def features(kb):
    FEAT_DIR.mkdir(parents=True, exist_ok=True)
    dev, test, n_ok = load_users(kb)
    log("building similarity matrices")
    S_tag = kb.T @ kb.T.T
    np.fill_diagonal(S_tag, 0)
    S_desc = None
    for E, has in kb.E_lang.values():
        s = np.where(has[:, None] & has[None, :], E @ E.T, 0.0).astype(np.float32)
        S_desc = s if S_desc is None else np.maximum(S_desc, s)
        del s
    np.fill_diagonal(S_desc, 0)
    B = kb.ease_core()
    L = lineage_matrices(kb)
    log("matrices ready")
    for setting in SETTINGS:
        for part, users in (("dev", dev), ("test", test)):
            t0 = time.time()
            idx, X, hit, nt, ntl = build_features(kb, users, setting, (S_tag, S_desc, B, L))
            np.savez(FEAT_DIR / f"{setting}_{part}.npz", idx=idx, X=X, hit=hit, ntarg=nt, ntarg_lt=ntl)
            log(f"{setting}/{part}: {len(idx):,} users, width {idx.shape[1]}, {time.time() - t0:.0f}s")
    (FEAT_DIR / "meta.json").write_text(json.dumps({"held_out_ok": n_ok, "n_dev": N_DEV, "n_test": N_TEST}))


def load_feat(setting, part):
    z = np.load(FEAT_DIR / f"{setting}_{part}.npz")
    return z["idx"], z["X"], z["hit"], z["ntarg"], z["ntarg_lt"]


DESIGN = {"tag_max": 0.30, "desc_max": 0.25, "colike": 0.30, "lin_any": 0.15}


def grid(kb):
    res = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    banned = np.argsort(-kb.popularity)[:LONGTAIL]
    rng = np.random.default_rng(1)
    for setting in SETTINGS:
        idx, X, hit, nt, ntl = load_feat(setting, "dev")
        log(f"grid {setting}: {len(idx):,} dev users")
        # 1) channel variant (max vs sum, which lineage parts) at three fixed weightings
        probes = [[0.30, 0.25, 0.30, 0.15], [0.15, 0.15, 0.6, 0.1], [0.25, 0.25, 0.25, 0.25]]
        best = {}
        for tag_v, desc_v, lin_v in itertools.product(["tag_max", "tag_sum"], ["desc_max", "desc_sum"],
                                                        ["lin_any", "lin_dev", "lin_ser", "lin_sim"]):
            for w in probes:
                wd = dict(zip([tag_v, desc_v, "colike", lin_v], w))
                r, _ = metrics(fuse(X, wd), idx, hit, nt)
                key = (tag_v, desc_v, lin_v)
                if key not in best or r.mean() > best[key][0]:
                    best[key] = (float(r.mean()), wd)
        top = sorted(best.items(), key=lambda kv: -kv[1][0])
        log(f"  best variant {top[0][0]} R@20 {top[0][1][0]:.4f}")
        # 2) weights of that variant: simplex step 0.1, then step 0.05 within +-0.1 of the best point
        tag_v, desc_v, lin_v = top[0][0]
        names = [tag_v, desc_v, "colike", lin_v]
        cands = []
        for w in simplex(0.1, 4):
            r, _ = metrics(fuse(X, dict(zip(names, w))), idx, hit, nt)
            cands.append((float(r.mean()), dict(zip(names, w))))
        cands.sort(key=lambda x: -x[0])
        wd0 = cands[0][1]
        log(f"  coarse R@20 {cands[0][0]:.4f} {wd0}")
        for w in simplex(0.05, 4):
            wd = dict(zip(names, w))
            if all(abs(wd[c] - wd0[c]) <= 0.1 + 1e-9 for c in wd) and wd != wd0:
                r, _ = metrics(fuse(X, wd), idx, hit, nt)
                cands.append((float(r.mean()), wd))
        cands.sort(key=lambda x: -x[0])
        tuned = {k: round(v, 2) for k, v in cands[0][1].items()}
        log(f"  refined R@20 {cands[0][0]:.4f} {tuned}")
        # report on test users
        idx, X, hit, nt, ntl = load_feat(setting, "test")
        configs = {
            "colike_only": {"colike": 1.0},
            "tag_only": {"tag_max": 1.0},
            "desc_only": {"desc_max": 1.0},
            "tag+desc": {"tag_max": 0.5, "desc_max": 0.5},
            "design_initial": DESIGN,
            "tuned": tuned,
        }
        for c in ("tag_max", "desc_max", "lin_any"):  # leave-one-out from the design weights
            w = {k: v for k, v in DESIGN.items() if k != c}
            s = sum(w.values())
            configs[f"design_minus_{c}"] = {k: v / s for k, v in w.items()}
        out = {"variants_dev": [{"variant": list(k), "recall20": round(v[0], 4), "weights": v[1]} for k, v in top[:6]],
               "tuned": tuned, "test": {}}
        scores = {name: fuse(X, w) for name, w in configs.items()}
        base_r, _ = metrics(scores["colike_only"], idx, hit, nt)
        des_r, _ = metrics(scores["design_initial"], idx, hit, nt)
        for name, s in scores.items():
            r, nd = metrics(s, idx, hit, nt)
            r5, _ = metrics(s, idx, hit, nt, k=5)
            rl, _ = metrics(s, idx, hit, nt, banned=banned, ntarg_lt=ntl)
            row = {"weights": configs[name], "recall20": ci(r, rng), "ndcg20": ci(nd, rng), "recall5": ci(r5, rng),
                   "recall20_longtail": ci(rl, rng)}
            if name != "colike_only":
                row["recall20_minus_colike_only"] = ci(r - base_r, rng)
            if name != "design_initial":
                row["recall20_minus_design"] = ci(r - des_r, rng)
            out["test"][name] = row
            log(f"  {name:28s} R@20 {row['recall20']}  R@5 {row['recall5']}  longtail {row['recall20_longtail']}")
        out["n_test_users"] = int((nt > 0).sum())
        res[setting] = out
        OUT.write_text(json.dumps(res, indent=1), encoding="utf-8")
    log(f"wrote {OUT}")


SMALL = [0, 0.03, 0.07, 0.12, 0.2]


def grid2(kb):
    """Normalisation (min-max / pool percentile / z-score) x small side-channel weights; RRF as the rank control."""
    res = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    rng = np.random.default_rng(2)
    banned = np.argsort(-kb.popularity)[:LONGTAIL]
    for setting in SETTINGS:
        idx, X, hit, nt, ntl = load_feat(setting, "dev")
        found = {}
        for normk, pre in (("minmax", ""), ("percentile", "r_"), ("zscore", "z_")):
            for tag_v, desc_v in (("tag_max", "desc_max"), ("tag_sum", "desc_sum")):
                best = None
                for wt, wdsc, wl in itertools.product(SMALL, SMALL, SMALL):
                    if wt + wdsc + wl > 0.6:
                        continue
                    wd = {pre + tag_v: wt, pre + desc_v: wdsc, pre + "colike": 1 - wt - wdsc - wl, "lin_any": wl}
                    if pre == "z_":  # z-scores are unbounded; scale the 0/1 lineage feature to a comparable size
                        wd["lin_any"] = wl * 3
                    r, _ = metrics(fuse(X, wd), idx, hit, nt)
                    if best is None or r.mean() > best[0]:
                        best = (float(r.mean()), wd)
                found[(normk, tag_v, desc_v)] = best
            log(f"{setting} {normk}: best {max((v for k, v in found.items() if k[0] == normk), key=lambda x: x[0])}")
        (normk, tag_v, desc_v), (dev_r, wd) = max(found.items(), key=lambda kv: kv[1][0])
        idx, X, hit, nt, ntl = load_feat(setting, "test")
        configs = {"colike_only": {"colike": 1.0}, "design_initial": DESIGN, "tuned": wd}
        for normk2, pre in (("minmax", ""), ("percentile", "r_"), ("zscore", "z_")):
            b = max(((k, v) for k, v in found.items() if k[0] == normk2), key=lambda kv: kv[1][0])
            configs[f"best_{normk2}"] = b[1][1]
        scores = {k: fuse(X, w) for k, w in configs.items()}
        scores["rrf_4ch"] = rrf(X, ["tag_max", "desc_max", "colike"]) + (1 / 61) * X[:, :, CHANNELS.index("lin_any")].astype(np.float32)
        scores["rrf_colike_tag"] = rrf(X, ["tag_max", "colike"])
        base_r, _ = metrics(scores["colike_only"], idx, hit, nt)
        out = {"dev_best": {"norm": normk, "tag": tag_v, "desc": desc_v, "recall20": round(dev_r, 4), "weights": wd},
               "dev_by_norm": {f"{k[0]}|{k[1]}|{k[2]}": {"recall20": round(v[0], 4), "weights": v[1]} for k, v in found.items()},
               "test": {}}
        for name, s in scores.items():
            r, nd = metrics(s, idx, hit, nt)
            r5, _ = metrics(s, idx, hit, nt, k=5)
            rl, _ = metrics(s, idx, hit, nt, banned=banned, ntarg_lt=ntl)
            row = {"weights": configs.get(name), "recall20": ci(r, rng), "ndcg20": ci(nd, rng), "recall5": ci(r5, rng),
                   "recall20_longtail": ci(rl, rng), "minus_colike_only": ci(r - base_r, rng)}
            out["test"][name] = row
            log(f"  {setting} {name:18s} R@20 {row['recall20']} R@5 {row['recall5']} LT {row['recall20_longtail']} "
                f"diff {row['minus_colike_only']}")
        res[setting + "_v2"] = out
        OUT.write_text(json.dumps(res, indent=1), encoding="utf-8")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    if cmd == "grid2":
        return grid2(KB())
    t0 = time.time()
    kb = KB()
    if cmd in ("features", "all"):
        features(kb)
    if cmd in ("grid", "all"):
        grid(kb)
    log(f"done in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
