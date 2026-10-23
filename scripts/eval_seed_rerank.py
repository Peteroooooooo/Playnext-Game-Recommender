"""Seed-only requests ("games like X"), judged blind by a model of another family. 40 most-reviewed core games +
20 sampled from ranks 500-3000.
  gen          : the fused score alone vs the same shortlist reranked against the seed's store facts (design 10.18)
  sweep NAME   : with the seed rerank on, the stage-1 weight tiers in SWEEPS[NAME] (weights: tag share, co-like the
                 rest); also prints how much of the top 80 and of the final top 5 changes against the first tier
  report NAME  : NAME = rerank | weights | desc (desc: the recorded description sweep, see SWEEPS).
                 Reads eval/seed_<NAME>_judge.json ({seed: {cid: 0|1|2}}) and prints the mean
                 judge score per method (bootstrap 95% CI), the paired difference to the first method, and the
                 rating and review count of the picks
Each method's top 5 per seed are merged, shuffled and numbered c1.. in eval/seed_<NAME>_judge_input.json; which method
gave which id is only in eval/seed_<NAME>_key.json.
Usage: uv run python scripts/eval_seed_rerank.py gen|sweep|report rerank|weights"""
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from playnext import config as C, pipeline  # noqa: E402
from playnext.llm import LLM  # noqa: E402
from playnext.rerank import facts  # noqa: E402
from playnext.spec import SessionSpec  # noqa: E402

EV = C.ROOT / "eval"
# Tag share per tier; co-like takes the rest. "weights" (2026-10-23, 0.20 kept) was run with a description share of
# 0.05 taken from co-like (tiers tag/desc 0.05/0.05 ... 0.50/0.05). The description sweep of the same day ("desc", at
# tag 0.20: desc0.05, "again" = desc0.05 repeated for the rerank noise, desc0.00, desc0.20; judge files
# eval/seed_desc_*.json, still readable by `report desc`) found it not to help, and the channel was removed
# (design 10.18), so it can no longer be swept.
SWEEPS = {"weights": {"tag0.05": 0.05, "tag0.20": 0.20, "tag0.35": 0.35, "tag0.50": 0.50},
          # 2026-10-23, after 0.40 was set: how far up the tag share can go without the picks getting worse
          "high": {"tag0.40": 0.40, "tag0.50": 0.50, "tag0.60": 0.60, "tag0.70": 0.70, "tag0.80": 0.80},
          # (fusion, tag share): linear sum vs weighted geometric mean (config.FUSION), which needs both channels
          "balance": {"lin0.40": ("linear", 0.40), "lin0.55": ("linear", 0.55), "lin0.70": ("linear", 0.70),
                      "geo0.50": ("geometric", 0.50), "geo0.70": ("geometric", 0.70)},
          # the tag exponent of the geometric fusion
          "geo": {"geo0.70": ("geometric", 0.70), "geo0.40": ("geometric", 0.40), "geo0.60": ("geometric", 0.60),
                  "geo0.80": ("geometric", 0.80)},   # void: the LLM quota ran out mid-run (2026-10-23)
          "geo2": {"geo0.70": ("geometric", 0.70), "geo0.40": ("geometric", 0.40), "geo0.50": ("geometric", 0.50),
                   "geo0.60": ("geometric", 0.60)}}


def paths(name):
    return EV / f"seed_{name}_judge_input.json", EV / f"seed_{name}_key.json", EV / f"seed_{name}_judge.json"


def seeds(kb):
    order = np.argsort(-kb.review_count, kind="stable")
    rng = np.random.default_rng(0)
    pick = list(order[:40]) + list(rng.choice(order[500:3000], 20, replace=False))
    return [int(kb.appids[i]) for i in pick]


def run(rec, S):
    """seed -> (top-5 appids, reranked shortlist) under the current config, 6 requests in parallel."""
    def one(a):
        res = rec.recommend(SessionSpec(seeds=[a]))
        return [c["appid"] for c in res.picks], res.debug.get("rerank", {}).get("cand", [])
    with ThreadPoolExecutor(6) as ex:
        got = dict(zip(S, ex.map(one, S)))
    if C.RERANK_SEEDS:
        # a failed rerank falls back silently (pipeline note); a tier with failures is not comparable, so stop
        failed = [rec.kb.name[a] for a, v in got.items() if not v[1]]
        if failed:
            raise SystemExit(f"rerank failed for {len(failed)} seeds (LLM quota or outage?): {failed[:5]}")
    return got


def write_blind(kb, S, lists, name):
    inp_p, key_p, _ = paths(name)
    rng = np.random.default_rng(1)
    inp, key = {}, {}
    for a in S:
        games = list(dict.fromkeys(g for m in lists for g in lists[m][a]))
        rng.shuffle(games)
        cid = {g: f"c{k + 1}" for k, g in enumerate(games)}
        inp[kb.name[a]] = {"request": f"想找类似《{kb.name[a]}》的游戏", "reference": facts(kb, kb.pos[a]),
                           "candidates": {cid[g]: facts(kb, kb.pos[g]) for g in games}}
        key[kb.name[a]] = {**{m: [cid[g] for g in lists[m][a]] for m in lists}, "appid": {cid[g]: g for g in games}}
    inp_p.write_text(json.dumps(inp, ensure_ascii=False, indent=1), encoding="utf-8")
    key_p.write_text(json.dumps(key, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(S)} seeds -> {inp_p}")


def gen():
    rec = pipeline.Recommender(llm=LLM(timeout=120), live_prices=False, reasons=False)
    S = seeds(rec.kb)
    C.RERANK_SEEDS = False
    now = {a: v[0] for a, v in run(rec, S).items()}
    C.RERANK_SEEDS = True
    rr = {a: v[0] for a, v in run(rec, S).items()}
    write_blind(rec.kb, S, {"now": now, "rerank": rr}, "rerank")


def sweep(name):
    tiers = SWEEPS[name]
    rec = pipeline.Recommender(llm=LLM(timeout=120), live_prices=False, reasons=False)
    S = seeds(rec.kb)
    C.RERANK_SEEDS = True
    base, base_fusion = dict(C.WEIGHTS), C.FUSION
    kb = rec.kb
    out, short = {}, {}
    for m, v in tiers.items():
        fusion, tag = v if isinstance(v, tuple) else ("linear", v)
        C.FUSION = fusion
        C.WEIGHTS.update(tag=tag, colike=round(1 - tag, 2), lineage=0.0)
        got = run(rec, S)
        out[m] = {a: x[0] for a, x in got.items()}
        short[m] = {a: x[1] for a, x in got.items()}
        # picks in none of the seed's co-like neighbour lists
        no_co = sum(1 for a in S for g in out[m][a] if not kb.ease_rows([a])[0, kb.pos[g]] > 0)
        print(f"{m}: {fusion} {C.WEIGHTS}; no co-like support {no_co} of {sum(len(x) for x in out[m].values())}",
              flush=True)
    C.WEIGHTS.clear()
    C.WEIGHTS.update(base)
    C.FUSION = base_fusion
    first = next(iter(tiers))
    for m in tiers:
        ov = [len(set(short[m][a]) & set(short[first][a])) / max(len(short[first][a]), 1) for a in S]
        same5 = [len(set(out[m][a]) & set(out[first][a])) for a in S]
        print(f"  {m}: top-80 shortlist shared with {first}: {np.mean(ov):.2f}; final top 5 shared {np.mean(same5):.2f} / 5")
    write_blind(rec.kb, S, out, name)


def report(name):
    from playnext.kb import KB
    kb = KB()
    _, key_p, judge_p = paths(name)
    key = json.loads(key_p.read_text(encoding="utf-8"))
    judge = json.loads(judge_p.read_text(encoding="utf-8"))
    methods = [m for m in next(iter(key.values())) if m != "appid"]
    rng = np.random.default_rng(2)
    per = {m: [] for m in methods}
    stats = {m: [] for m in methods}
    for s, k in key.items():
        j = judge.get(s)
        if not j:
            continue
        for m in methods:
            per[m].append(np.mean([j[c] for c in k[m]]))
            for c in k[m]:
                a = k["appid"][c]
                stats[m].append((kb.quality[kb.pos[a]], kb.review_count[kb.pos[a]]))

    def ci(v):
        b = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(1000)]
        return f"{v.mean():+.3f} [{np.percentile(b, 2.5):+.3f}, {np.percentile(b, 97.5):+.3f}]"
    first = np.array(per[methods[0]])
    for m in methods:
        v = np.array(per[m])
        st = np.array(stats[m])
        line = f"{m:8s} judge {ci(v)}  rating {st[:, 0].mean():.3f}  median reviews {np.median(st[:, 1]):,.0f}  n={len(v)}"
        if m != methods[0]:
            d = v - first
            line += f"  vs {methods[0]} {ci(d)} better {int((d > 0).sum())} / worse {int((d < 0).sum())}"
        print(line)


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "report":
        report(sys.argv[2])
    elif cmd == "sweep":
        sweep(sys.argv[2] if len(sys.argv) > 2 else "weights")
    else:
        gen()
