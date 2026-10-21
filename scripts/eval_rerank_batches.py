"""Can the LLM rerank be split into parallel batches (design 5.5 '语义精排')? Measures how far the batched scores drift
from one full call, whether per-batch normalisation fixes it, and how much time it saves.

For each request-set post that had a rerank (eval/cache/system.json), on the same rerank candidates and the same query
text (with the mentioned games' English names, as in production):
  ref  : the cached full-batch scores (eval/cache/llm_named.json, one call with every candidate)
  rep  : the full batch again (run-to-run noise floor: same input, a new call)
  rand : candidates shuffled into B batches, called in parallel
  intl : candidates dealt round-robin by fused rank into B batches (every batch gets a similar quality mix)
Every batch also carries A anchor games (spread over the fused ranking) so batches can be calibrated against each
other without the full call. Stitching methods applied to the same batched calls:
  raw      : batch scores as returned
  minmax   : min-max inside each batch, rescaled to 0-10
  zscore   : z-score inside each batch
  anchor   : shift each batch so its anchors' mean equals the anchors' mean over all batches
  anchorlin: least-squares line from the batch's anchor scores to the anchors' mean over all batches (slope clipped)
Metrics: Spearman of stitched vs ref scores; batch drift = mean |batch-mean of (stitched - ref)| on z-scored data;
overlap of the final top 5 (fused with w_r 0.9 exactly like eval_request_set.py sweep) with ref's top 5; hits of the
posts' community picks and the posters' liked games; wall time of the full call vs the parallel batches.
Requests are run one after another so the timings are not mixed with other calls. Answers are cached in
eval/cache/rerank_batches.json. Usage: uv run python scripts/eval_rerank_batches.py [batches=4] [anchors=4]
"""
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import eval_request_set as E  # noqa: E402
from playnext.kb import KB  # noqa: E402
from playnext.llm import LLM  # noqa: E402
from playnext.rerank import llm_scores  # noqa: E402
from playnext.spec import SessionSpec  # noqa: E402

W = 0.9
METHODS = ["raw", "minmax", "zscore", "anchor", "anchorlin"]


def spearman(a, b):
    ra, rb = np.argsort(np.argsort(a)), np.argsort(np.argsort(b))
    return float(np.corrcoef(ra, rb)[0, 1]) if len(a) > 2 else float("nan")


def stitch(batches, method, anchors):
    """batches: list of {appid: score} (each includes the anchors). Returns {appid: score}."""
    out = {}
    if method in ("anchor", "anchorlin"):
        amean = {a: np.mean([b[a] for b in batches if a in b]) for a in anchors}
    for b in batches:
        ids = list(b)
        s = np.array([b[a] for a in ids], float)
        if method == "minmax":
            s = (s - s.min()) / (s.max() - s.min() + 1e-9) * 10
        elif method == "zscore":
            s = (s - s.mean()) / (s.std() + 1e-9)
        elif method == "anchor":
            got = [a for a in anchors if a in b]
            s = s - (np.mean([b[a] for a in got]) - np.mean([amean[a] for a in got]))
        elif method == "anchorlin":
            got = [a for a in anchors if a in b]
            x, y = np.array([b[a] for a in got], float), np.array([amean[a] for a in got], float)
            if np.ptp(x) > 0:
                k, c = np.polyfit(x, y, 1)
                k = float(np.clip(k, 0.5, 2.0))
                c = float(y.mean() - k * x.mean())
            else:
                k, c = 1.0, float(y.mean() - x.mean())
            s = k * s + c
        for a, v in zip(ids, s):
            out.setdefault(a, []).append(float(v))
    return {a: float(np.mean(v)) for a, v in out.items()}


def main():
    B = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    A = int(sys.argv[2]) if len(sys.argv) > 2 else 4
    kb = KB()
    llm = LLM(timeout=180)
    sysrun, named, names = E.load("system.json", {}), E.load("llm_named.json", {}), E.load("names.json", {})
    rows = {r["id"]: r for r in E.rows()}
    cache = E.load("rerank_batches.json", {})
    rec = E.make_rec()
    todo = [rid for rid, s in sorted(sysrun.items()) if s.get("rerank") and rid in named]
    rng = np.random.default_rng(0)

    def call(texts, ids):
        sc = llm_scores(kb, llm, texts, [kb.pos[a] for a in ids])
        return {str(k): {int(kb.appids[i]): float(v) for i, v in d.items()} for k, d in sc.items()}

    for n, rid in enumerate(todo):
        key = f"{rid}|B{B}|A{A}"
        if key in cache:
            continue
        s = sysrun[rid]
        spec = SessionSpec.model_validate(s["spec"])
        cand = list(s["rerank"]["cand"])               # fused-rank order, extras appended
        keys = {k: (k if k in ("me", "shared") else int(k)) for k in s["rerank"]["scores"]}
        texts = {keys[k]: E._target_text(kb, spec, k, True) for k in keys}
        anchors = [cand[int(round(q * (len(cand) - 1)))] for q in np.linspace(0, 1, A)]
        rest = [a for a in cand if a not in anchors]
        shuffled = list(rng.permutation(rest))
        splits = {"rand": [shuffled[i::B] for i in range(B)], "intl": [rest[i::B] for i in range(B)]}
        entry = {"anchors": anchors}
        try:
            t0 = time.time()
            entry["rep"] = call(texts, cand)
            entry["t_full"] = round(time.time() - t0, 1)
            for name, parts in splits.items():
                t0 = time.time()
                with ThreadPoolExecutor(B) as ex:
                    got = list(ex.map(lambda p: call(texts, [int(x) for x in p] + anchors), parts))
                entry[name] = got
                entry[f"t_{name}"] = round(time.time() - t0, 1)
        except Exception as e:
            E.log(rid, "failed", str(e)[:120])
            continue
        cache[key] = entry
        E.save("rerank_batches.json", cache)
        E.log(f"{n + 1}/{len(todo)} {rid}: full {entry['t_full']}s, rand {entry['t_rand']}s, intl {entry['t_intl']}s")

    # ---------------- analysis
    res = {}
    times = {"full": [], "rand": [], "intl": []}

    def picks(sc):
        return rec.recommend(spec, {k: {int(a): v for a, v in d.items()} for k, d in sc.items()}, W).picks

    for rid in todo:
        key = f"{rid}|B{B}|A{A}"
        if key not in cache:
            continue
        e = cache[key]
        s = sysrun[rid]
        spec = SessionSpec.model_validate(s["spec"])
        ref = {k: {int(a): v for a, v in d.items()} for k, d in named[rid]["scores"].items()}
        P, N, Cm = labels(rows[rid], names)
        ref_top = [c["appid"] for c in picks(ref)]
        variants = {"rep": {k: {int(a): v for a, v in d.items()} for k, d in e["rep"].items()}}
        for sp in ("rand", "intl"):
            for m in METHODS:
                variants[f"{sp}_{m}"] = {k: stitch([{int(a): v for a, v in b[k].items()} for b in e[sp]], m,
                                                   e["anchors"]) for k in ref}
        for t in ("full", "rand", "intl"):
            times[t].append(e[f"t_{t}"])
        for v, sc in variants.items():
            rhos, drift = [], []
            for k in ref:
                ids = [a for a in ref[k] if a in sc.get(k, {})]
                x = np.array([ref[k][a] for a in ids]); y = np.array([sc[k][a] for a in ids])
                rhos.append(spearman(x, y))
                if True:  # rep: same random groups, no real batching -> the drift that noise alone produces
                    zx = (x - x.mean()) / (x.std() + 1e-9); zy = (y - y.mean()) / (y.std() + 1e-9)
                    part = "rand" if v == "rep" else v.split("_")[0]
                    for b in e[part]:
                        got = {int(x) for x in b[k]}
                        bid = [i for i, a in enumerate(ids) if a in got and a not in e["anchors"]]
                        if bid:
                            drift.append(abs(float(np.mean(zy[bid] - zx[bid]))))
            top = [c["appid"] for c in picks(sc)]
            r = res.setdefault(v, {"rho": [], "drift": [], "overlap": [], "com": 0, "pos": 0})
            r["rho"].append(float(np.nanmean(rhos)))
            r["drift"] += drift
            r["overlap"].append(len(set(top) & set(ref_top)))
            r["com"] += len(set(top) & Cm)
            r["pos"] += len(set(top) & P)
        r = res.setdefault("ref", {"rho": [1.0], "drift": [], "overlap": [], "com": 0, "pos": 0})
        r["overlap"].append(5)
        r["com"] += len(set(ref_top) & Cm)
        r["pos"] += len(set(ref_top) & P)

    print(f"\nrequests {len(next(iter(res.values()))['overlap'])}, batches {B}, anchors {A}")
    print(f"wall time median: full {np.median(times['full']):.1f}s | rand {np.median(times['rand']):.1f}s | "
          f"intl {np.median(times['intl']):.1f}s")
    print(f"{'variant':16s} {'spearman':>8s} {'drift':>6s} {'top5 same':>9s} {'5/5':>4s} {'community':>9s} {'liked':>5s}")
    summary = {}
    for v in ["ref", "rep"] + [f"{sp}_{m}" for sp in ("rand", "intl") for m in METHODS]:
        r = res[v]
        row = {"spearman": round(float(np.mean(r["rho"])), 3),
               "drift": round(float(np.mean(r["drift"])), 3) if r["drift"] else None,
               "top5_overlap": round(float(np.mean(r["overlap"])), 2),
               "top5_identical": int(sum(o == 5 for o in r["overlap"])), "community": r["com"], "liked": r["pos"]}
        summary[v] = row
        print(f"{v:16s} {row['spearman']:8.3f} {row['drift'] if row['drift'] is not None else '-':>6} "
              f"{row['top5_overlap']:9.2f} {row['top5_identical']:4d} {row['community']:9d} {row['liked']:5d}")
    out = E.CACHE / f"rerank_batches_summary_B{B}_A{A}.json"
    out.write_text(json.dumps({"times": times, "summary": summary}, ensure_ascii=False, indent=1), encoding="utf-8")
    E.log("saved", out)


def labels(r, names):
    fb = r.get("op_feedback") or []
    pos = {names.get(f["game"]) for f in fb if f["reaction"] in ("loved", "will_try")} - {None}
    neg = {names.get(f["game"]) for f in fb if f["reaction"] in ("rejected", "already_played")} - {None}
    com = {names.get(n) for n in (r.get("top_community_suggestions") or [])} - {None}
    return pos, neg, com


if __name__ == "__main__":
    main()
