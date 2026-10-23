"""The rerank fusion weight w_r (config.RERANK_W: 0.9 x LLM score + 0.1 x stage-1 score), judged blind by a model of
another family on three groups:
  seed  : the 60 "games like X" requests of eval_seed_rerank.py
  words : 31 made-up sentences (eval/synthetic_requests.json, written by an LLM; one per synthetic library)
  lib   : the same sentences with the matching made-up library (eval/synthetic_libraries.json) connected
The LLM rerank scores do not depend on w_r, so every request is reranked once and each tier re-fuses those scores
(Recommender.recommend(rerank_scores=, rerank_w=)); a second LLM call at the current w_r ("again") gives the
run-to-run noise.
  gen            : the LLM calls, then eval/rerankw_raw.json (specs, both score sets) and the blind judge files
  regen          : the same from eval/rerankw_raw.json without LLM calls (other tiers)
  report GROUP   : reads eval/rerankw_<GROUP>_judge.json ({item: {cid: 0|1|2}}); mean judge score per tier (bootstrap
                   95% CI), the paired difference to the first tier
Printed by gen / regen per group and tier: picks with no co-like support (in none of the anchors' co-like neighbour
lists; anchors = seeds and played library games), mean rating, median reviews, and for lib the picks that differ
from the same sentence without the library.
Usage: uv run python scripts/eval_rerank_weight.py gen|regen|report [seed|words|lib]"""
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from playnext import config as C  # noqa: E402
from playnext.aliases import Resolver  # noqa: E402
from playnext.llm import LLM  # noqa: E402
from playnext.pipeline import Recommender  # noqa: E402
from playnext.rerank import facts  # noqa: E402
from playnext.spec import Library, SessionSpec  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from eval_seed_rerank import seeds  # noqa: E402

EV = C.ROOT / "eval"
RAW = EV / "rerankw_raw.json"
TIERS = {"w0.9": 0.9, "w0.7": 0.7, "w0.5": 0.5, "w0.3": 0.3}
GROUPS = ("seed", "words", "lib")


def paths(g):
    return EV / f"rerankw_{g}_judge_input.json", EV / f"rerankw_{g}_key.json", EV / f"rerankw_{g}_judge.json"


def libraries(kb):
    res = Resolver(kb.games)
    out = {}
    for n, games in json.loads((EV / "synthetic_libraries.json").read_text(encoding="utf-8")).items():
        out[n] = {m.appid: float(h) for t, h in games.items() if (m := res.resolve(t)).appid in kb.pos}
    return out


def items(rec, llm_specs=None):
    """group -> {item: SessionSpec}. The sentences are understood by the LLM unless llm_specs (from RAW) is given."""
    kb = rec.kb
    req = json.loads((EV / "synthetic_requests.json").read_text(encoding="utf-8"))
    if llm_specs is None:
        with ThreadPoolExecutor(8) as ex:
            words = dict(zip(req, ex.map(lambda t: rec.understand(t)[1], req.values())))
    else:
        words = {n: SessionSpec.model_validate(s) for n, s in llm_specs.items()}
    libs = libraries(kb)
    lib = {}
    for n, s in words.items():
        s2 = s.model_copy(deep=True)
        s2.members[0].library = Library(owned=libs[n])
        lib[n] = s2
    return {"seed": {kb.name[a]: SessionSpec(seeds=[a]) for a in seeds(kb)}, "words": words, "lib": lib}


def anchors(kb, spec):
    a = list(spec.seeds) + [x for m in spec.members for x in m.seeds]
    for m in spec.members:
        if m.library:
            a += [g for g, h in m.library.owned.items() if h > 0]
    return [x for x in dict.fromkeys(a) if x in kb.pos]


def gen(raw=None):
    rec = Recommender(llm=LLM(timeout=120), live_prices=False, reasons=False)
    kb = rec.kb
    its = items(rec, raw and raw["specs"])
    if raw is None:
        def two(spec):
            got = [rec.recommend(spec).debug.get("rerank", {}).get("scores") for _ in range(2)]
            return got
        raw = {"specs": {n: s.model_dump(mode="json") for n, s in its["words"].items()}, "scores": {}}
        for g in GROUPS:
            with ThreadPoolExecutor(8) as ex:
                got = dict(zip(its[g], ex.map(two, its[g].values())))
            failed = [n for n, v in got.items() if not v[0] or not v[1]]
            if failed:
                raise SystemExit(f"{g}: rerank failed or skipped for {len(failed)}: {failed[:5]}")
            raw["scores"][g] = got
            print(f"{g}: {len(got)} requests reranked twice", flush=True)
        RAW.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    picks = {}
    for g in GROUPS:
        picks[g] = {}
        for t, w in {**TIERS, "again": C.RERANK_W}.items():
            k = 1 if t == "again" else 0
            picks[g][t] = {n: [c["appid"] for c in rec.recommend(s, rerank_scores=raw["scores"][g][n][k], rerank_w=w).picks]
                           for n, s in its[g].items()}
    rng = np.random.default_rng(1)
    for g in GROUPS:
        print(f"\n[{g}]")
        rows = {n: kb.ease_rows(anchors(kb, s)) if anchors(kb, s) else None for n, s in its[g].items()}
        for t, by in picks[g].items():
            flat = [(n, a) for n, v in by.items() for a in v]
            sup = [(rows[n][:, kb.pos[a]] > 0).any() for n, a in flat if rows[n] is not None]
            q = np.array([kb.quality[kb.pos[a]] for _, a in flat])
            rc = np.array([kb.review_count[kb.pos[a]] for _, a in flat])
            line = (f"  {t:6s} no co-like support {len(sup) - sum(sup)} of {len(sup)}; rating {q.mean():.3f}; "
                    f"median reviews {np.median(rc):,.0f}")
            if g == "lib":
                diff = sum(len(set(v) - set(picks["words"][t][n])) for n, v in by.items())
                line += f"; picks not in the words-only top 5: {diff} of {len(flat)}"
            print(line)
        inp, key = {}, {}
        for n, s in its[g].items():
            games = list(dict.fromkeys(a for t in picks[g] for a in picks[g][t][n]))
            rng.shuffle(games)
            cid = {a: f"c{k + 1}" for k, a in enumerate(games)}
            e = {"request": f"想找类似《{n}》的游戏" if g == "seed" else s.request_text}
            if g == "seed":
                e["reference"] = facts(kb, kb.pos[s.seeds[0]])
            if g == "lib":
                lib = s.members[0].library.owned
                e["library_hours"] = {kb.name[a]: h for a, h in sorted(lib.items(), key=lambda x: -x[1])}
            e["candidates"] = {cid[a]: facts(kb, kb.pos[a]) for a in games}
            inp[n] = e
            key[n] = {**{t: [cid[a] for a in picks[g][t][n]] for t in picks[g]}, "appid": {cid[a]: a for a in games}}
        inp_p, key_p, _ = paths(g)
        inp_p.write_text(json.dumps(inp, ensure_ascii=False, indent=1), encoding="utf-8")
        key_p.write_text(json.dumps(key, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"  -> {inp_p.name}: {np.mean([len(v['candidates']) for v in inp.values()]):.1f} candidates per item")


def report(g):
    _, key_p, judge_p = paths(g)
    key = json.loads(key_p.read_text(encoding="utf-8"))
    judge = json.loads(judge_p.read_text(encoding="utf-8"))
    tiers = [t for t in next(iter(key.values())) if t != "appid"]
    rng = np.random.default_rng(2)
    per = {t: np.array([np.mean([judge[n][c] for c in key[n][t]]) for n in key if n in judge]) for t in tiers}

    def ci(v):
        b = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(1000)]
        return f"{v.mean():+.3f} [{np.percentile(b, 2.5):+.3f}, {np.percentile(b, 97.5):+.3f}]"
    for t in tiers:
        line = f"{t:6s} judge {ci(per[t])} n={len(per[t])}"
        if t != tiers[0]:
            d = per[t] - per[tiers[0]]
            line += f"  vs {tiers[0]} {ci(d)} better {int((d > 0).sum())} / worse {int((d < 0).sum())}"
        print(line)


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "report":
        report(sys.argv[2])
    elif cmd == "regen":
        gen(json.loads(RAW.read_text(encoding="utf-8")))
    else:
        gen()
