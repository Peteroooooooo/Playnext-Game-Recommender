"""Content (tag + description) share vs co-like, and a tag-similarity gate, on the cached eval_fusion features.

Question (2026-10-23): with co-like at 0.90, "games like Terraria" returns Counter-Strike 2. Does a larger content
share or a gate (candidates whose tag similarity to the anchors is below theta, after per-user min-max, drop below
all others) cost the held-out reviewers' later positives, and does it bring the IGDB similar games up?
Metrics on the test users (bootstrap 95% CI): Recall@20, Recall@20 without the 100 most popular games (long tail),
and IGDB@5 = share of the top 5 that IGDB lists as similar to an anchor (an outside view of "is it alike").
Weights and theta are picked on dev users; needs `scripts/eval_fusion.py features` (cached in .cache/eval_fusion/).
Usage: uv run python scripts/eval_content_weight.py
"""
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from eval_fusion import CHANNELS, LONGTAIL, ci, load_feat, metrics, topk  # noqa: E402
from playnext import config as C  # noqa: E402
from playnext.kb import KB  # noqa: E402

OUT = C.DER / "eval_content_weight.json"
CO = [0.90, 0.70, 0.50, 0.30]
GATE = [0.0, 0.1, 0.2, 0.3, 0.4]
SETTINGS = ["seed1", "seed2", "library"]


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def score(X, co, gate):
    ch = lambda c: X[:, :, CHANNELS.index(c)].astype(np.float32)
    content = (1 - co) / 2
    tag = ch("tag_sum")
    s = co * ch("colike") + content * tag + content * ch("desc_sum")
    if gate:
        s = s - (tag < gate)  # below the gate: after every game that passes it, order kept
    return s


def igdb_at(s, idx, X, k=5):
    top = topk(s, idx, k)
    lin = np.take_along_axis(X[:, :, CHANNELS.index("lin_sim")].astype(np.float32), top, 1)
    return lin.mean(1)


def main():
    kb = KB()
    banned = np.argsort(-kb.popularity)[:LONGTAIL]
    rng = np.random.default_rng(3)
    res = {}
    for setting in SETTINGS:
        idx, X, hit, nt, ntl = load_feat(setting, "dev")
        dev = {}
        for co in CO:
            for g in GATE:
                s = score(X, co, g)
                r, _ = metrics(s, idx, hit, nt)
                dev[f"co{co:.2f}_gate{g:.1f}"] = (float(r.mean()), float(igdb_at(s, idx, X).mean()))
        log(setting, "dev", json.dumps({k: [round(a, 4), round(b, 3)] for k, (a, b) in dev.items()}))
        del X
        idx, X, hit, nt, ntl = load_feat(setting, "test")
        base = score(X, 0.90, 0.0)
        base_r, _ = metrics(base, idx, hit, nt)
        base_lt, _ = metrics(base, idx, hit, nt, banned=banned, ntarg_lt=ntl)
        out = {}
        for co in CO:
            for g in GATE:
                s = score(X, co, g)
                r, _ = metrics(s, idx, hit, nt)
                lt, _ = metrics(s, idx, hit, nt, banned=banned, ntarg_lt=ntl)
                ig = igdb_at(s, idx, X)
                key = f"co{co:.2f}_gate{g:.1f}"
                out[key] = {"recall20": ci(r, rng, 200), "longtail20": ci(lt, rng, 200), "igdb5": ci(ig, rng, 200),
                            "recall20_minus_now": ci(r - base_r, rng, 200), "longtail_minus_now": ci(lt - base_lt, rng, 200)}
                log(f"  {setting} {key}  R@20 {out[key]['recall20']}  LT {out[key]['longtail20']}  "
                    f"IGDB@5 {out[key]['igdb5']}  dR {out[key]['recall20_minus_now']}")
        res[setting] = {"dev": dev, "test": out, "n_test_users": int((nt > 0).sum())}
        del X
        OUT.write_text(json.dumps(res, indent=1), encoding="utf-8")
    log(f"wrote {OUT}")


if __name__ == "__main__":
    main()
