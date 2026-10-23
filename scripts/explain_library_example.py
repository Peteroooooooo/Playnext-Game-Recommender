"""Run the library example of docs/pipeline_architecture.html (the mocked Steam library of simulate_inputs.py) through
the real Step 2-4 code and record every intermediate number the page shows: anchor weights, per-anchor similarities
for a few candidates, channel sums (tag and co-like; lineage only feeds cards), pool normalisation, fusion, and each
ranking / MMR round.
No LLM is needed: a library alone has no words, so there is no semantic rerank (rerank.targets_with_words).
The page's numbers use --dense (exact tables, kb.DenseKB); without it the service's top-200 neighbour tables are
used (slightly different intermediate scores; at tag 0.70 with geometric fusion the five picks and their order match,
design 10.16 / 10.18).
Usage: uv run python scripts/explain_library_example.py [--dense]   -> .cache/explain_library_example.json
"""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from playnext import config as C  # noqa: E402
from playnext.kb import KB, DenseKB, minmax  # noqa: E402
from playnext.library import parse_owned  # noqa: E402
from playnext.pipeline import Recommender  # noqa: E402
from playnext.ranking import fold_series, rank, window_score  # noqa: E402
from playnext.rules import PASS, UNKNOWN, hard_filter  # noqa: E402
from playnext.scoring import channel_scores, library_anchors, member_taste, relevance  # noqa: E402
from playnext.spec import Member, SessionSpec  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from simulate_inputs import MOCK_OWNED  # noqa: E402

OUT = C.CACHE / "explain_library_example.json"
EXTRA = 3   # besides the picks, show the games each channel alone ranks first


def r3(x):
    return round(float(x), 3)


def main():
    rec = Recommender(kb=DenseKB() if "--dense" in sys.argv else KB(), live_prices=False, reasons=False)
    kb = rec.kb
    name = lambda a: kb.display_name(int(a))
    lib = parse_owned(MOCK_OWNED)
    spec = SessionSpec(members=[Member(library=lib)])
    m = spec.members[0]

    # Step 2
    fr = hard_filter(kb, spec)
    pool = fr.status >= UNKNOWN
    excluded_owned = [name(a) for a, h in lib.owned.items() if a in kb.pos and fr.status[kb.pos[a]] < UNKNOWN]

    # anchors
    anchors = library_anchors(kb, m)
    anchor_rows = []
    for a, h in lib.owned.items():
        ref = kb.playtime_ref.loc[a] if a in kb.playtime_ref.index else None
        anchor_rows.append({"appid": int(a), "name": name(a) if a in kb.pos else str(a), "hours": round(h, 1),
                            "in_core": a in kb.pos, "median_hours": r3(ref["median_hours"]) if ref is not None else None,
                            "weight": anchors.get(a)})

    # Step 3, channel by channel, exactly as scoring.channel_scores does it
    a_ids = list(anchors)
    rows = [kb.pos[a] for a in a_ids]
    w = np.array([anchors[a] for a in a_ids], np.float32)
    tag_sim = kb.T[rows] @ kb.T.T                        # anchors x games
    ease = kb.ease_rows(a_ids)
    sc = channel_scores(kb, member_taste(kb, m), pool)
    rel, details = relevance(kb, spec, pool)

    # ranking
    ranked = rank(kb, spec, rel, fr, rec.prices)
    picks = list(ranked.picks)

    # which games to show in the matrices: the picks, plus each channel's own top games that were not picked
    show = list(picks)
    channel_top = {}
    pass_idx = np.flatnonzero(pool)
    for ch in ("tag", "colike"):
        order = pass_idx[np.argsort(-sc.parts[ch][pass_idx], kind="stable")]
        channel_top[ch] = [{"name": name(kb.appids[i]), "norm": r3(sc.parts[ch][i])} for i in order[:5]]
        for i in order[:EXTRA]:
            if int(i) not in show:
                show.append(int(i))
    W = dict(C.WEIGHTS)

    def per_anchor(mat, i):
        return [{"anchor": name(a), "sim": r3(mat[k, i]), "weighted": r3(w[k] * mat[k, i])} for k, a in enumerate(a_ids)]

    cand = []
    for i in show:
        has = {c: bool(sc.has[c][i]) for c in W}
        cand.append({
            "appid": int(kb.appids[i]), "name": name(kb.appids[i]), "picked": i in picks,
            "tag": {"per_anchor": per_anchor(tag_sim, i), "raw": r3((w[:, None] * tag_sim[:, i:i + 1]).sum()),
                    "norm": r3(sc.parts["tag"][i])},
            "colike": {"per_anchor": per_anchor(ease, i), "raw": r3((w[:, None] * ease[:, i:i + 1]).sum()),
                       "norm": r3(sc.parts["colike"][i])},
            "lineage": int(sc.parts["lineage"][i]), "has": has,
            "fused": r3(sc.score[i]), "rel": r3(rel[i]),
            "rank_by_rel": int((rel[pass_idx] > rel[i]).sum()) + 1,
            "quality": r3(kb.quality[i]), "reviews": int(kb.review_count[i]),
            "pct_positive": round(100 * kb.pos_reviews[i] / kb.review_count[i], 1) if kb.review_count[i] else None,
        })
    pool_range = {}
    for ch in ("tag", "colike"):
        raw = {"tag": (w[:, None] * tag_sim).sum(0), "colike": (w[:, None] * ease).sum(0)}[ch]
        mask = pool & sc.has[ch]
        pool_range[ch] = {"min": r3(raw[mask].min()), "max": r3(raw[mask].max()), "games": int(mask.sum()),
                          "argmax": name(kb.appids[np.flatnonzero(mask)[np.argmax(raw[mask])]])}

    # ranking detail: folding, shortlist, MMR rounds (same loop as ranking.rank)
    status = fr.status
    pidx = np.flatnonzero(status == PASS)
    order = pidx[np.argsort(-rel[pidx], kind="stable")]
    kept, folded = fold_series(kb, order[:C.SHORTLIST * 10], C.SHORTLIST * 3)
    folded_view = [{"kept": name(kb.appids[k]), "folded": [name(kb.appids[j]) for j in v]}
                   for k, v in folded.items() if k in ranked.shortlist and v]
    short = ranked.shortlist
    base = ranked.base
    rounds, chosen, remaining = [], [], set(short)
    while len(chosen) < C.PICK and remaining:
        rated = {r for r in remaining if kb.rating_ok[r]} or remaining
        top = max(rel[r] for r in rated)
        window = [r for r in rated if rel[r] >= top - C.DELTA]
        rows_ = []
        for r in window:
            red = max((float(kb.T[r] @ kb.T[c]) for c in chosen), default=0.0)
            mmr = C.MMR_LAMBDA * base[r] - (1 - C.MMR_LAMBDA) * red
            closest = max(chosen, key=lambda c: float(kb.T[r] @ kb.T[c])) if chosen else None
            rows_.append({"name": name(kb.appids[r]), "rel": r3(rel[r]), "base": r3(base[r]), "redundancy": r3(red),
                          "closest": name(kb.appids[closest]) if closest is not None else None, "mmr": r3(mmr)})
        best = max(window, key=lambda r: (C.MMR_LAMBDA * base[r] - (1 - C.MMR_LAMBDA) * max(
            (float(kb.T[r] @ kb.T[c]) for c in chosen), default=0.0), rel[r]))
        rows_.sort(key=lambda x: -x["mmr"])
        rounds.append({"top_rel": r3(top), "window_floor": r3(top - C.DELTA), "window": rows_,
                       "chosen": name(kb.appids[best])})
        chosen.append(best)
        remaining.discard(best)
    assert chosen == picks, "explain loop drifted from ranking.rank"
    top_by_rel = [{"name": name(kb.appids[i]), "rel": r3(rel[i]), "picked": int(i) in picks} for i in short]

    out = {
        "config": {"weights": W, "delta": C.DELTA, "mmr_lambda": C.MMR_LAMBDA, "shortlist": C.SHORTLIST, "pick": C.PICK,
                   "base_w": C.BASE_W, "alpha_beta": [C.ALPHA, C.BETA], "rating_floor": C.RATING_FLOOR},
        "step2": {"core": int(kb.n), "pass": int((status == PASS).sum()), "unknown": int((status == UNKNOWN).sum()),
                  "rules": fr.summary(), "excluded_owned": excluded_owned},
        "anchors": anchor_rows,
        "pool_range": pool_range,
        "channel_top": channel_top,
        "candidates": cand,
        "folded": folded_view,
        "shortlist": top_by_rel,
        "rounds": rounds,
        "picks": [name(kb.appids[i]) for i in picks],
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
