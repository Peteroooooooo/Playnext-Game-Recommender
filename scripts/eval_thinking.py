"""Does each LLM step need the model's thinking? Default thinking vs reasoning_effort=none, step by step.

Inputs: the request-set posts (eval/request_set_raw.jsonl); default-thinking answers are the cached ones from
eval_request_set.py where they exist.
  understand (step 1): parse every post again with effort none; both parses go through the current to_spec and are
      checked against the per-post gold conditions (intent_accuracy: people, setup, budget, played / excluded games,
      avoided content); also field agreement between the two parses and the top 5 without rerank from each spec.
  reasons (step 5): the production top 5 of every post (cached rerank scores, w_r 0.9) get reasons with default
      thinking and with effort none; fact-check pass rate, length, time; a few pairs printed side by side.
The rerank step (step 3) is scripts/eval_rerank_speed.py with configs 1:none 8:none.
Calls cached in eval/cache/thinking.json. Usage: uv run python scripts/eval_thinking.py [understand|reasons|all]
"""
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import eval_request_set as E  # noqa: E402
from eval_rerank_speed import LLMx  # noqa: E402
from playnext.cards import write_reasons  # noqa: E402
from playnext.kb import KB  # noqa: E402
from playnext.spec import SessionSpec  # noqa: E402
from playnext.understand import ParsedRequest, Understander  # noqa: E402


def understand(kb, cache):
    rows = E.rows()
    gold = __import__("json").loads(E.GOLD.read_text(encoding="utf-8"))
    und = E.load("understand.json", {})
    u_none = Understander(kb, LLMx("none"))
    u_def = Understander(kb, LLMx(None))
    c = cache.setdefault("understand_none", {})
    c2 = cache.setdefault("understand_default_again", {})   # run-to-run noise floor of the default parse

    def one(job):
        r, u, dst = job
        if r["id"] in dst:
            return
        t0 = time.time()
        try:
            p = u.parse(r["text"])
            dst[r["id"]] = {"parsed": p.model_dump(), "seconds": round(time.time() - t0, 1), "error": None}
        except Exception as e:
            dst[r["id"]] = {"parsed": None, "seconds": round(time.time() - t0, 1), "error": str(e)[:200]}

    with ThreadPoolExecutor(16) as ex:
        list(ex.map(one, [(r, u_none, c) for r in rows] + [(r, u_def, c2) for r in rows]))
    E.save("thinking.json", cache)
    rec = E.make_rec()
    specs = {"default": {}, "none": {}, "default_again": {}}
    for r in rows:
        for arm, src in (("default", und), ("none", c), ("default_again", c2)):
            p = (src.get(r["id"]) or {}).get("parsed")
            if p:
                specs[arm][r["id"]] = rec_spec(u_none, p, r["text"])
    print("\n== step 1: understand ==")
    srcs = {"default": und, "none": c, "default_again": c2}
    for arm in ("default", "none", "default_again"):
        acc = E.intent_accuracy(kb, gold, {k: {"spec": v.model_dump()} for k, v in specs[arm].items()})
        secs = [x["seconds"] for x in srcs[arm].values() if x.get("parsed")]
        fails = sum(1 for r in rows if r["id"] not in specs[arm])
        print(f"{arm:13s} people {fmt(acc['party_size'])} | setup {fmt(acc['setup'])} | budget {fmt(acc['budget'])} | "
              f"played/excluded recall {fmt(acc['played_excluded_recall'])} precision "
              f"{fmt(acc['played_excluded_precision'])} | avoid recall {fmt(acc['avoid_recall'])} | parse failed {fails} "
              f"| seconds median {np.median(secs):.1f}")
    for other in ("none", "default_again"):
        agreement(rec, specs["default"], specs[other], f"default vs {other}")


def agreement(rec, A, B, label):
    both = [k for k in A if k in B]
    same = {f: 0 for f in ("party_size", "budget", "seeds", "gone", "has_pref", "feel")}
    ov = []
    for k in both:
        a, b = A[k], B[k]
        same["party_size"] += a.party_size == b.party_size
        same["budget"] += (a.budget.model_dump() if a.budget else None) == (b.budget.model_dump() if b.budget else None)
        same["seeds"] += set(a.seeds) == set(b.seeds)
        same["gone"] += gone(a) == gone(b)
        same["has_pref"] += bool(a.preference_text) == bool(b.preference_text)
        fa, fb = set(a.feel_want) | set(a.feel_avoid), set(b.feel_want) | set(b.feel_avoid)
        same["feel"] += len(fa & fb) / max(len(fa | fb), 1)
        pa = [x["appid"] for x in rec.recommend(a).picks]
        pb = [x["appid"] for x in rec.recommend(b).picks]
        ov.append(len(set(pa) & set(pb)))
    print(f"{label}, {len(both)} posts: " + ", ".join(f"{f} {v:.0f}/{len(both)}" if f != "feel" else
                                                          f"feel tags jaccard {v / len(both):.2f}" for f, v in same.items())
          + f" | top 5 without rerank same {np.mean(ov):.2f}/5")


def rec_spec(u, parsed, text):
    return u.to_spec(ParsedRequest.model_validate(parsed), text)


def gone(s: SessionSpec):
    out = set(s.excluded)
    for m in s.members:
        out |= set(m.played_elsewhere)
    return out


def fmt(x):
    return f"{x[0]}/{x[1]}"


def reasons(kb, cache):
    rows = {r["id"]: r for r in E.rows()}
    sysrun, named = E.load("system.json", {}), E.load("llm_named.json", {})
    rec = E.make_rec()
    c = cache.setdefault("reasons", {})
    jobs = []
    for rid, s in sorted(sysrun.items()):
        spec = SessionSpec.model_validate(s["spec"])
        sc = {k: {int(a): v for a, v in d.items()} for k, d in named[rid]["scores"].items()} if rid in named else None
        res = rec.recommend(spec, sc, 0.9) if sc else rec.recommend(spec)
        for arm in ("default", "none"):
            jobs.append((rid, arm, spec.request_text, res.picks))
    llms = {"default": LLMx(None), "none": LLMx("none")}

    def one(job):
        rid, arm, text, picks = job
        key = f"{rid}|{arm}"
        if key in c:
            return
        cards = [dict(p) for p in picks]
        t0 = time.time()
        write_reasons(cards, llms[arm], text)
        c[key] = {"seconds": round(time.time() - t0, 1),
                  "cards": [{"name": x["name"], "source": x["reason_source"], "reason": x["reason"]} for x in cards]}

    # interleave the two arms so both see the same relay load
    with ThreadPoolExecutor(4) as ex:
        list(ex.map(one, jobs))
    E.save("thinking.json", cache)
    print("\n== step 5: reasons ==")
    for arm in ("default", "none"):
        v = [c[f"{rid}|{arm}"] for rid in sorted(sysrun) if f"{rid}|{arm}" in c]
        cards = [x for r in v for x in r["cards"]]
        llm_ok = [x for x in cards if x["source"] == "llm"]
        print(f"{arm:8s} posts {len(v)} | cards {len(cards)} | passed fact check {len(llm_ok)} | "
              f"mean length {np.mean([len(x['reason']) for x in llm_ok]):.0f} chars | seconds median "
              f"{np.median([r['seconds'] for r in v]):.1f}, p90 {np.percentile([r['seconds'] for r in v], 90):.1f}")
    for rid in ("r01", "r10", "r22"):
        a, b = c.get(f"{rid}|default"), c.get(f"{rid}|none")
        if a and b:
            print(f"\n[{rid}] {rows[rid]['text'][:80]}…")
            for x, y in list(zip(a["cards"], b["cards"]))[:2]:
                print(f"  《{x['name']}》\n    default: {x['reason']}\n    none   : {y['reason']}")


def main():
    stage = sys.argv[1] if len(sys.argv) > 1 else "all"
    kb = KB()
    cache = E.load("thinking.json", {})
    if stage in ("understand", "all"):
        understand(kb, cache)
    if stage in ("reasons", "all"):
        reasons(kb, cache)


if __name__ == "__main__":
    main()
