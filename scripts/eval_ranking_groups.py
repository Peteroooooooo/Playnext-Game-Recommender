"""Offline evaluation of Step 4 ranking rules, the seed-pool library bonus, and scenario 2 group aggregation,
all through the real src/playnext code (design 5.5, section 7).

Same held-out reviewers and time split as eval_fusion.py (hash % 10 == 0, >= 5 core positives, earlier half =
profile, later half = targets). Only aggregates are printed; results go to data/derived/eval_ranking_groups.json.
  rank   : top-5 hit rate, rating, diversity under fold / floor / window delta / MMR / quality variants
  bonus  : seed = last profile game, library = the rest; Recall@20 for seed pool size x library bonus
  groups : synthetic groups (3 and 5 members; random or sharing a profile game); multiplayer pool; compare
           mean+min, Nash, lexmin, mean, min and one merged profile. A member "accepts" a game in their targets.
Usage: uv run python scripts/eval_ranking_groups.py [rank|bonus|groups|all] [N users]
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from playnext import config as C  # noqa: E402
from playnext.kb import KB, minmax  # noqa: E402
from playnext.pricing import Prices  # noqa: E402
from playnext.ranking import rank  # noqa: E402
from playnext.rules import UNKNOWN, hard_filter  # noqa: E402
from playnext.scoring import Taste, channel_scores, group_aggregate, relevance  # noqa: E402
from playnext.spec import Library, Member, SessionSpec  # noqa: E402

OUT = C.DER / "eval_ranking_groups.json"
SEED = 7


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def users(kb, n):
    t = pd.read_parquet(C.DER / "eval_reviews100m_test.parquet")
    t = t[t["voted_up"] & t["app_id"].isin(kb.pos)].sort_values(["user_hash", "date"]).drop_duplicates(["user_hash", "app_id"])
    sizes = t.groupby("user_hash").size()
    ok = sizes[sizes >= 5].index.to_numpy()
    pick = set(np.random.default_rng(SEED).choice(ok, size=n, replace=False).tolist())
    out = []
    for u, d in t[t["user_hash"].isin(pick)].groupby("user_hash"):
        a, h = d["app_id"].to_numpy(), d["hours_total"].to_numpy(np.float64)
        m = len(a) // 2
        out.append({"prof": {int(x): max(float(y), 0.01) for x, y in zip(a[:m], h[:m])}, "targ": set(int(x) for x in a[m:])})
    return out


def ci(x, rng=np.random.default_rng(3)):
    x = np.asarray(x, np.float64)
    b = [x[rng.integers(0, len(x), len(x))].mean() for _ in range(400)]
    return [round(float(x.mean()), 4), round(float(np.percentile(b, 2.5)), 4), round(float(np.percentile(b, 97.5)), 4)]


def eval_rank(kb, us):
    prices = Prices(kb, live=False)
    variants = {
        "plain_top5": dict(delta=0.0, mmr_lambda=1.0, floor=False, fold=False, qual=False),
        "fold": dict(delta=0.0, mmr_lambda=1.0, floor=False, fold=True, qual=False),
        "fold+floor": dict(delta=0.0, mmr_lambda=1.0, floor=True, fold=True, qual=False),
        "design(δ0.1,MMR0.65)": dict(delta=0.10, mmr_lambda=0.65, floor=True, fold=True, qual=True),
        "δ0.05": dict(delta=0.05, mmr_lambda=0.65, floor=True, fold=True, qual=True),
        "δ0.2": dict(delta=0.2, mmr_lambda=0.65, floor=True, fold=True, qual=True),
        "δ0.3": dict(delta=0.3, mmr_lambda=0.65, floor=True, fold=True, qual=True),
        "global(δ1)": dict(delta=1.0, mmr_lambda=0.65, floor=True, fold=True, qual=True),
        "δ0.1,noMMR": dict(delta=0.1, mmr_lambda=1.0, floor=True, fold=True, qual=True),
        "δ0.1,MMR0.8": dict(delta=0.1, mmr_lambda=0.8, floor=True, fold=True, qual=True),
        "δ0.1,MMR0.5": dict(delta=0.1, mmr_lambda=0.5, floor=True, fold=True, qual=True),
    }
    res = {k: {"hit5": [], "any5": [], "pct": [], "ild": [], "floor_ok": []} for k in variants}
    qw = dict(C.BASE_W)
    t0 = time.time()
    for k, u in enumerate(us):
        spec = SessionSpec(members=[Member(library=Library(owned=u["prof"]))])
        fr = hard_filter(kb, spec)
        rel, _ = relevance(kb, spec, fr.status >= UNKNOWN)
        if rel is None:
            continue
        for name, v in variants.items():
            C.BASE_W = qw if v["qual"] else {"relevance": 1.0, "quality": 0.0, "price": 0.0}
            r = rank(kb, spec, rel, fr, prices, delta=v["delta"], mmr_lambda=v["mmr_lambda"], floor=v["floor"], fold=v["fold"])
            picks = [int(kb.appids[i]) for i in r.picks]
            hits = sum(a in u["targ"] for a in picks)
            res[name]["hit5"].append(hits / min(5, len(u["targ"])))
            res[name]["any5"].append(float(hits > 0))
            res[name]["pct"].append(np.mean([kb.games.at[a, "pct_positive"] for a in picks]))
            res[name]["floor_ok"].append(np.mean([kb.rating_ok[i] for i in r.picks]))
            T = kb.T[r.picks]
            S = T @ T.T
            res[name]["ild"].append(float(1 - S[np.triu_indices(len(picks), 1)].mean()))
        C.BASE_W = qw
        if k % 500 == 0:
            log(f"  rank {k}/{len(us)} ({time.time() - t0:.0f}s)")
    out = {name: {m: ci(v) for m, v in d.items()} for name, d in res.items()}
    out["n_users"] = len(res["plain_top5"]["hit5"])
    for name, d in out.items():
        if name != "n_users":
            log(f"  {name:22s} hit@5 {d['hit5']} any {d['any5']} pct {d['pct'][0]} ILD {d['ild'][0]} floor {d['floor_ok'][0]}")
    return out


def eval_bonus(kb, us):
    pools, bonuses = [20, 50, 100, 200, 7304], [0, 0.1, 0.2, 0.3, 0.5, 1.0]
    rec = {(p, b): [] for p in pools for b in bonuses}
    rec_merged = []
    for u in us:
        prof = list(u["prof"])
        if len(prof) < 2:
            continue
        seed = prof[-1]
        lib = {}
        for a in prof[:-1]:
            p = kb.playtime_pct(a, u["prof"][a])
            if p and p > 0:
                lib[a] = p
        if not lib:
            continue
        excl = np.isin(kb.appids, prof)
        pool = ~excl
        s = channel_scores(kb, Taste(anchors={seed: 1.0}), pool).score
        L = channel_scores(kb, Taste(anchors=lib), pool).score
        targ = u["targ"]
        order_s = np.argsort(-np.where(pool, s, -np.inf))
        for p in pools:
            sp = np.zeros(kb.n, bool)
            sp[order_s[:p]] = True
            bonus = minmax(L, sp) * sp
            for b in bonuses:
                f = np.where(pool, s + b * bonus, -np.inf)
                top = np.argpartition(-f, 20)[:20]
                rec[(p, b)].append(sum(int(kb.appids[i]) in targ for i in top) / min(20, len(targ)))
        merged = channel_scores(kb, Taste(anchors={seed: 1.0, **{a: 0.5 * w for a, w in lib.items()}}), pool).score
        top = np.argpartition(-np.where(pool, merged, -np.inf), 20)[:20]
        rec_merged.append(sum(int(kb.appids[i]) in targ for i in top) / min(20, len(targ)))
    out = {f"pool{p}_bonus{b}": ci(v) for (p, b), v in rec.items()}
    out["old_rule_merged_x0.5"] = ci(rec_merged)
    out["n_users"] = len(rec_merged)
    for k, v in out.items():
        log(f"  {k:24s} {v}")
    return out


def eval_groups(kb, us, n_groups=1500):
    rng = np.random.default_rng(11)
    mp = np.array([bool(kb.categories.get(int(a), set()) & {36, 38}) for a in kb.appids])  # online multiplayer pool
    mp_ids = set(int(a) for a in kb.appids[mp])
    elig = [u for u in us if u["targ"] & mp_ids]
    log(f"groups: {len(elig)} of {len(us)} users have a later positive among online multiplayer games")
    by_game = {}
    for k, u in enumerate(elig):
        for a in u["prof"]:
            by_game.setdefault(a, []).append(k)
    cache = {}

    def user_score(k):
        if k not in cache:
            u = elig[k]
            anchors = {a: kb.playtime_pct(a, h) or 0.5 for a, h in u["prof"].items()}
            anchors = {a: w for a, w in anchors.items() if w > 0} or {a: 1.0 for a in u["prof"]}
            cache[k] = channel_scores(kb, Taste(anchors=anchors), mp).score
        return cache[k]

    methods = ["mean_min", "nash", "lexmin", "mean", "min", "merged_profile"]
    out = {}
    for size in (3, 5):
        for kind in ("random", "similar"):
            stats = {m: {"mean_hit10": [], "all_hit10": [], "min_hit10": []} for m in methods}
            made = 0
            tries = 0
            while made < n_groups and tries < n_groups * 20:
                tries += 1
                if kind == "random":
                    g = rng.choice(len(elig), size, replace=False).tolist()
                else:
                    games = [a for a, ks in by_game.items() if len(ks) >= size]
                    a = games[rng.integers(len(games))]
                    g = rng.choice(by_game[a], size, replace=False).tolist()
                profs = set().union(*(elig[k]["prof"] for k in g))
                pool = mp & ~np.isin(kb.appids, list(profs))
                U = [minmax(user_score(k), pool) for k in g]
                scores = {m: group_aggregate(U, m) for m in ("mean_min", "nash", "lexmin")}
                scores["mean"] = np.mean(U, 0)
                scores["min"] = np.min(U, 0)
                merged = {}
                for k in g:
                    for a, h in elig[k]["prof"].items():
                        merged[a] = max(merged.get(a, 0), kb.playtime_pct(a, h) or 0.5)
                scores["merged_profile"] = minmax(channel_scores(kb, Taste(anchors={a: w for a, w in merged.items() if w > 0}), pool).score, pool)
                for m, s in scores.items():
                    top = np.argpartition(-np.where(pool, s, -np.inf), 10)[:10]
                    picks = {int(kb.appids[i]) for i in top}
                    hits = [len(picks & elig[k]["targ"]) > 0 for k in g]
                    stats[m]["mean_hit10"].append(np.mean(hits))
                    stats[m]["all_hit10"].append(float(all(hits)))
                    stats[m]["min_hit10"].append(float(min(len(picks & elig[k]["targ"]) for k in g) > 0))
                made += 1
            key = f"size{size}_{kind}"
            out[key] = {m: {k: ci(v) for k, v in d.items() if k != "min_hit10"} for m, d in stats.items()}
            out[key]["n_groups"] = made
            for m in methods:
                log(f"  {key:16s} {m:15s} share of members with a hit in top-10 {out[key][m]['mean_hit10']}  "
                    f"all members hit {out[key][m]['all_hit10']}")
    return out


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 3000
    kb = KB()
    res = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    us = users(kb, n if cmd != "groups" else max(n, 20000))
    log(f"{len(us)} users; weights {C.WEIGHTS}")
    if cmd in ("rank", "all"):
        res["rank"] = eval_rank(kb, us)
        OUT.write_text(json.dumps(res, indent=1), encoding="utf-8")
    if cmd in ("bonus", "all"):
        res["bonus"] = eval_bonus(kb, us)
        OUT.write_text(json.dumps(res, indent=1), encoding="utf-8")
    if cmd in ("groups", "all"):
        gus = us if cmd == "groups" else users(kb, 20000)
        res["groups"] = eval_groups(kb, gus)
        OUT.write_text(json.dumps(res, indent=1), encoding="utf-8")
    res["weights"] = C.WEIGHTS
    OUT.write_text(json.dumps(res, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
