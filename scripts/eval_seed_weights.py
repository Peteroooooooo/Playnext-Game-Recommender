"""Stage-1 channel weights on the real request set: how many of the thread's community suggestions and the
original poster's positive games reach the rerank input (top 40) and the top 5, per weighting.
Requests are re-understood by the LLM once (cached in .cache/request_specs.json); no rerank, snapshot prices.
Usage: uv run python scripts/eval_seed_weights.py"""
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from playnext import config as C  # noqa: E402
from playnext.encoder import Encoder  # noqa: E402
from playnext.llm import LLM  # noqa: E402
from playnext.pipeline import Recommender  # noqa: E402
from playnext.rules import PASS, UNKNOWN, hard_filter  # noqa: E402
from playnext.scoring import relevance  # noqa: E402
from playnext.spec import SessionSpec  # noqa: E402

CACHE = C.CACHE / "request_specs.json"
CONFIGS = {
    "colike.90": {"tag": 0.05, "desc": 0.05, "colike": 0.90, "lineage": 0.0},
    "colike.70": {"tag": 0.15, "desc": 0.15, "colike": 0.70, "lineage": 0.0},
    "colike.50": {"tag": 0.25, "desc": 0.25, "colike": 0.50, "lineage": 0.0},
    "colike.30": {"tag": 0.35, "desc": 0.35, "colike": 0.30, "lineage": 0.0},
    "colike.10": {"tag": 0.45, "desc": 0.45, "colike": 0.10, "lineage": 0.0},
}


def main():
    rows = [json.loads(l) for l in (C.ROOT / "eval" / "request_set_raw.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    res = json.loads((C.ROOT / "eval" / "request_set_results.json").read_text(encoding="utf-8"))["results"]
    labels = {r["id"]: r["labels"] for r in res}
    llm = LLM(timeout=120)
    rec = Recommender(llm=llm, encoder=Encoder(), live_prices=False, reasons=False, rerank=False)
    kb = rec.kb
    if CACHE.exists():
        specs = {k: SessionSpec.model_validate(v) for k, v in json.loads(CACHE.read_text(encoding="utf-8")).items()}
    else:
        with ThreadPoolExecutor(6) as ex:
            out = list(ex.map(lambda r: rec.understand(r["text"])[1], rows))
        specs = {r["id"]: s for r, s in zip(rows, out)}
        CACHE.write_text(json.dumps({k: v.model_dump() for k, v in specs.items()}, ensure_ascii=False), encoding="utf-8")
    base = dict(C.WEIGHTS)
    table = {k: {"comm40": 0, "comm5": 0, "pos40": 0, "pos5": 0, "seed_req": 0} for k in CONFIGS}
    for name, w in CONFIGS.items():
        C.WEIGHTS = w
        for r in rows:
            spec = specs[r["id"]]
            has_seed = bool(spec.seeds or any(m.seeds for m in spec.members))
            if not has_seed:
                continue
            table[name]["seed_req"] += 1
            fr = hard_filter(kb, spec)
            rel, _ = relevance(kb, spec, fr.status >= UNKNOWN, rec.encoder)
            if rel is None:
                continue
            idx = np.flatnonzero(fr.status == PASS)
            order = [int(kb.appids[i]) for i in idx[np.argsort(-rel[idx])][:40]]
            lab = labels[r["id"]]
            comm, pos = set(lab["community"]), set(lab["positive"])
            table[name]["comm40"] += len(comm & set(order))
            table[name]["comm5"] += len(comm & set(order[:5]))
            table[name]["pos40"] += len(pos & set(order))
            table[name]["pos5"] += len(pos & set(order[:5]))
    C.WEIGHTS = base
    for k, v in table.items():
        print(k, v)
    (C.DER / "eval_seed_weights.json").write_text(json.dumps(table, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
