"""Library-only requests (no words, no seeds, so no LLM rerank): the stage-1 tag share (co-like the rest) on 30 made-up
libraries (eval/synthetic_libraries.json, written by an LLM; no real player data).
  gen SET    : top 5 per library and tier of TIERS[SET]; "off-taste" picks = tag cosine to every played library game
               below 0.10 / 0.20 (Counter-Strike 2 for a sandbox library); blind judge input in
               eval/library_<SET>_judge_input.json, key in eval/library_<SET>_key.json
  report SET : reads eval/library_<SET>_judge.json ({library: {cid: 0|1|2}}) and prints the mean judge score per tier
               (bootstrap 95% CI), the paired difference to the first tier, and the rating / review count of the picks
SET: tag (0.20 / 0.30 / 0.40) or high (0.40 ... 0.80).
Usage: uv run python scripts/eval_library_tag.py gen|report [tag|high]"""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from playnext import config as C  # noqa: E402
from playnext.aliases import Resolver  # noqa: E402
from playnext.pipeline import Recommender  # noqa: E402
from playnext.rerank import facts  # noqa: E402
from playnext.spec import Library, Member, SessionSpec  # noqa: E402

EV = C.ROOT / "eval"
LIBS = EV / "synthetic_libraries.json"
TIERS = {"tag": {"tag0.20": 0.20, "tag0.30": 0.30, "tag0.40": 0.40},
         "high": {"tag0.40": 0.40, "tag0.50": 0.50, "tag0.60": 0.60, "tag0.70": 0.70, "tag0.80": 0.80},
         # (fusion, tag share): linear sum vs weighted geometric mean (config.FUSION), which needs both channels
         "balance": {"lin0.40": ("linear", 0.40), "lin0.55": ("linear", 0.55), "lin0.70": ("linear", 0.70),
                     "geo0.50": ("geometric", 0.50), "geo0.70": ("geometric", 0.70)},
         # the tag exponent of the geometric fusion
         "geo": {"geo0.70": ("geometric", 0.70), "geo0.40": ("geometric", 0.40), "geo0.60": ("geometric", 0.60),
                 "geo0.80": ("geometric", 0.80)}}


def tier(v):
    return v if isinstance(v, tuple) else ("linear", v)


def paths(name):
    return EV / f"library_{name}_judge_input.json", EV / f"library_{name}_key.json", EV / f"library_{name}_judge.json"


def gen(name):
    inp_p, key_p, _ = paths(name)
    tiers = TIERS[name]
    rec = Recommender(llm=None, live_prices=False, reasons=False)
    kb = rec.kb
    res = Resolver(kb.games)
    Tn = kb.T / np.maximum(np.linalg.norm(kb.T, axis=1, keepdims=True), 1e-9)
    libs, missing = {}, []
    for n, games in json.loads(LIBS.read_text(encoding="utf-8")).items():
        owned = {}
        for title, h in games.items():
            m = res.resolve(title)
            if m.appid is None or m.appid not in kb.pos:
                missing.append(title)
            else:
                owned[m.appid] = float(h)
        libs[n] = owned
    print(f"{len(libs)} libraries; {len(missing)} titles not in the core library: {missing}")
    base, base_fusion = dict(C.WEIGHTS), C.FUSION
    co_rows = {n: kb.ease_rows([a for a, h in o.items() if h > 0]) for n, o in libs.items()}
    out = {}
    for t, v in tiers.items():
        fusion, tag = tier(v)
        C.FUSION = fusion
        C.WEIGHTS.update(tag=tag, colike=round(1 - tag, 2))
        out[t] = {n: [c["appid"] for c in rec.recommend(SessionSpec(members=[Member(name="me", library=Library(owned=o))])).picks]
                  for n, o in libs.items()}
        sims = np.array([float((Tn[kb.pos[a]] @ Tn[[kb.pos[g] for g, h in libs[n].items() if h > 0]].T).max())
                         for n in libs for a in out[t][n]])
        # no co-like support: the game is in none of the played library games' co-like neighbour lists
        no_co = sum(1 for n in libs for a in out[t][n] if not (co_rows[n][:, kb.pos[a]] > 0).any())
        q = np.array([kb.quality[kb.pos[a]] for n in libs for a in out[t][n]])
        rc = np.array([kb.review_count[kb.pos[a]] for n in libs for a in out[t][n]])
        print(f"{t} {fusion} {dict(C.WEIGHTS)}: off-taste < 0.10: {int((sims < 0.10).sum())}, < 0.20: "
              f"{int((sims < 0.20).sum())}; no co-like support {no_co} of {len(sims)}; rating {q.mean():.3f}, "
              f"median reviews {np.median(rc):,.0f}")
        for n in libs:
            low = [kb.name[a] for a in out[t][n]
                   if float((Tn[kb.pos[a]] @ Tn[[kb.pos[g] for g in libs[n]]].T).max()) < 0.10]
            if low:
                print(f"    {n}: {low}")
    C.WEIGHTS.clear()
    C.WEIGHTS.update(base)
    C.FUSION = base_fusion
    rng = np.random.default_rng(1)
    inp, key = {}, {}
    for n, owned in libs.items():
        games = list(dict.fromkeys(g for t in tiers for g in out[t][n]))
        rng.shuffle(games)
        cid = {g: f"c{k + 1}" for k, g in enumerate(games)}
        inp[n] = {"library": {kb.name[a]: h for a, h in sorted(owned.items(), key=lambda x: -x[1])},
                  "candidates": {cid[g]: facts(kb, kb.pos[g]) for g in games}}
        key[n] = {**{t: [cid[g] for g in out[t][n]] for t in tiers}, "appid": {cid[g]: g for g in games}}
    inp_p.write_text(json.dumps(inp, ensure_ascii=False, indent=1), encoding="utf-8")
    key_p.write_text(json.dumps(key, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"-> {inp_p}")


def report(name):
    _, key_p, judge_p = paths(name)
    key = json.loads(key_p.read_text(encoding="utf-8"))
    judge = json.loads(judge_p.read_text(encoding="utf-8"))
    rng = np.random.default_rng(2)
    tiers = TIERS[name]
    per = {t: np.array([np.mean([judge[n][c] for c in key[n][t]]) for n in key if n in judge]) for t in tiers}

    def ci(v):
        b = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(1000)]
        return f"{v.mean():+.3f} [{np.percentile(b, 2.5):+.3f}, {np.percentile(b, 97.5):+.3f}]"
    first = next(iter(tiers))
    for t, v in per.items():
        line = f"{t} judge {ci(v)} n={len(v)}"
        if t != first:
            d = v - per[first]
            line += f"  vs {first} {ci(d)} better {int((d > 0).sum())} / worse {int((d < 0).sum())}"
        print(line)


if __name__ == "__main__":
    {"gen": gen, "report": report}[sys.argv[1]](sys.argv[2] if len(sys.argv) > 2 else "tag")
