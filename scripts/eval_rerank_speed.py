"""Faster LLM rerank (design 5.5 '语义精排'): thinking effort x number of parallel batches, against the full call.

Same request-set posts, candidates and query text as scripts/eval_rerank_batches.py. Each config is
"<batches>:<effort>": batches 1 = one call with every candidate, B > 1 = candidates shuffled into B batches called in
parallel and their raw scores used as they are (eval_rerank_batches.py: per-batch normalisation and anchors made it
worse); effort = default (model's own thinking) or a reasoning_effort value (none / minimal / low / medium).
Compared with ref (the cached full call at default effort, eval/cache/llm_named.json); rep (the same full call run
again, eval/cache/rerank_batches.json) is the run-to-run noise floor. Metrics: Spearman vs ref, overlap of the final
top 5 (fused with w_r 0.9 as in production), community / liked hits, wall time and completion tokens per request.
Requests run one after another. Calls cached in eval/cache/rerank_speed.json.
Usage: uv run python scripts/eval_rerank_speed.py 1:none 1:low 8:default 8:low 16:low
"""
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import eval_request_set as E  # noqa: E402
from eval_rerank_batches import labels, spearman  # noqa: E402
from playnext.kb import KB  # noqa: E402
from playnext.llm import LLM  # noqa: E402
from playnext.rerank import llm_scores  # noqa: E402
from playnext.spec import SessionSpec  # noqa: E402

W = 0.9


class LLMx(LLM):
    """LLM with an optional reasoning_effort; records completion tokens per call."""

    def __init__(self, effort=None):
        super().__init__(timeout=180)
        self.effort, self.tokens, self.lock = effort, [], threading.Lock()

    def chat(self, system, user, purpose="", temperature=0):
        kw = {"reasoning_effort": self.effort} if self.effort else {}
        r = self.client.chat.completions.create(model=self.model, temperature=temperature, **kw,
                                                messages=[{"role": "system", "content": system},
                                                          {"role": "user", "content": user}])
        with self.lock:
            self.tokens.append(r.usage.completion_tokens if r.usage else 0)
        return r.choices[0].message.content or ""


def main():
    configs = sys.argv[1:] or ["1:none", "1:low", "8:default", "8:low", "16:low"]
    kb = KB()
    sysrun, named, names = E.load("system.json", {}), E.load("llm_named.json", {}), E.load("names.json", {})
    old = E.load("rerank_batches.json", {})
    rows = {r["id"]: r for r in E.rows()}
    cache = E.load("rerank_speed.json", {})
    rec = E.make_rec()
    todo = [rid for rid, s in sorted(sysrun.items()) if s.get("rerank") and rid in named]
    llms = {}

    for n, rid in enumerate(todo):
        s = sysrun[rid]
        spec = SessionSpec.model_validate(s["spec"])
        cand = list(s["rerank"]["cand"])
        keys = {k: (k if k in ("me", "shared") else int(k)) for k in s["rerank"]["scores"]}
        texts = {keys[k]: E._target_text(kb, spec, k, True) for k in keys}
        for cfg in configs:
            key = f"{rid}|{cfg}"
            if key in cache:
                continue
            b, eff = cfg.split(":")
            b = int(b)
            llm = llms.setdefault(eff, LLMx(None if eff == "default" else eff))
            parts = [cand] if b == 1 else [list(x) for x in np.array_split(
                np.random.default_rng(hash(rid) % 2**32).permutation(cand), b)]
            t_before = len(llm.tokens)
            t0 = time.time()
            try:
                with ThreadPoolExecutor(len(parts)) as ex:
                    got = list(ex.map(lambda p: llm_scores(kb, llm, texts, [kb.pos[int(a)] for a in p]), parts))
            except Exception as e:
                E.log(rid, cfg, "failed", str(e)[:120])
                continue
            sec = round(time.time() - t0, 1)
            sc = {}
            for g in got:
                for k, d in g.items():
                    sc.setdefault(str(k), {}).update({int(kb.appids[i]): float(v) for i, v in d.items()})
            cache[key] = {"scores": sc, "sec": sec, "tokens": int(sum(llm.tokens[t_before:]))}
            E.save("rerank_speed.json", cache)
        E.log(f"{n + 1}/{len(todo)} {rid}: " + ", ".join(f"{c} {cache.get(f'{rid}|{c}', {}).get('sec')}s"
                                                       for c in configs))

    def picks(spec, sc):
        return [c["appid"] for c in rec.recommend(spec, {k: {int(a): v for a, v in d.items()} for k, d in sc.items()},
                                                  W).picks]

    res, rep_sec = {}, []
    for rid in todo:
        s = sysrun[rid]
        spec = SessionSpec.model_validate(s["spec"])
        ref = {k: {int(a): v for a, v in d.items()} for k, d in named[rid]["scores"].items()}
        P, _, Cm = labels(rows[rid], names)
        ref_top = picks(spec, ref)
        variants = {"ref (1:default)": {"scores": ref, "sec": named[rid]["seconds"], "tokens": None}}
        o = old.get(f"{rid}|B4|A4")
        if o:
            variants["rep (1:default again)"] = {"scores": o["rep"], "sec": o["t_full"], "tokens": None}
        for cfg in configs:
            if f"{rid}|{cfg}" in cache:
                variants[cfg] = cache[f"{rid}|{cfg}"]
        for v, d in variants.items():
            sc = {k: {int(a): x for a, x in dd.items()} for k, dd in d["scores"].items()}
            rho = []
            for k in ref:
                ids = [a for a in ref[k] if a in sc.get(k, {})]
                rho.append(spearman(np.array([ref[k][a] for a in ids]), np.array([sc[k][a] for a in ids])))
            cover = np.mean([len(sc.get(k, {})) / len(ref[k]) for k in ref])
            top = picks(spec, sc)
            r = res.setdefault(v, {"rho": [], "ov": [], "com": 0, "pos": 0, "sec": [], "tok": [], "cover": []})
            r["rho"].append(float(np.nanmean(rho)))
            r["ov"].append(len(set(top) & set(ref_top)))
            r["com"] += len(set(top) & Cm)
            r["pos"] += len(set(top) & P)
            r["sec"].append(d["sec"])
            r["cover"].append(cover)
            if d.get("tokens") is not None:
                r["tok"].append(d["tokens"])

    print(f"\nrequests {len(todo)}")
    print(f"{'config':24s} {'spearman':>8s} {'top5 same':>9s} {'5/5':>4s} {'community':>9s} {'liked':>5s} "
          f"{'sec med':>7s} {'sec p90':>7s} {'tokens med':>10s} {'scored':>6s}")
    for v, r in res.items():
        tok = f"{np.median(r['tok']):.0f}" if r["tok"] else "-"
        print(f"{v:24s} {np.mean(r['rho']):8.3f} {np.mean(r['ov']):9.2f} {sum(o == 5 for o in r['ov']):4d} "
              f"{r['com']:9d} {r['pos']:5d} {np.median(r['sec']):7.1f} {np.percentile(r['sec'], 90):7.1f} "
              f"{tok:>10s} {np.mean(r['cover']):6.0%}")


if __name__ == "__main__":
    main()
