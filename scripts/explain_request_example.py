"""Run the two request examples of docs/pipeline_architecture.html section 四 through the real code and record every
number the page shows: ② the sentence "像 Hades，但别太难" alone, ③ the same sentence with the mocked Steam library of
simulate_inputs.py (the library of explain_library_example.py, attached to member 0 the way pipeline.ask keeps a
connected library).
The sentence is understood once (one LLM call) and the same ParsedRequest / SessionSpec is used for both cases. The
LLM rerank is not deterministic, so it is called once on the union of both cases' rerank candidates; each case then
reuses those shared scores for its own candidates (Recommender.recommend(rerank_scores=...)), and ② and ③ differ
only because of the library. Recorded: the parsed request, round-1 scores (tag, co-like, feel, fused, rank), the
library bonus, the LLM scores, the post-rerank scores and ranks, and the final picks.
Uses the service's top-200 neighbour tables (kb.KB), not --dense.
--reuse: no LLM call; take the parsed request and the rerank scores from the existing output (same date and model),
so the explanation can be extended without changing the numbers on the page.
Usage: uv run python scripts/explain_request_example.py [--reuse]   -> .cache/explain_request_example.json
"""
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from playnext import config as C  # noqa: E402
from playnext.kb import minmax  # noqa: E402
from playnext.library import parse_owned  # noqa: E402
from playnext.llm import LLM  # noqa: E402
from playnext.pipeline import Recommender  # noqa: E402
from playnext.ranking import rank  # noqa: E402
from playnext.rerank import candidates, fuse, llm_scores, targets_with_words, with_game_names  # noqa: E402
from playnext.rules import PASS, UNKNOWN, hard_filter  # noqa: E402
from playnext.scoring import combine, relevance  # noqa: E402
from playnext.spec import Library  # noqa: E402
from playnext.understand import ParsedRequest  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from explain_library_example import r3  # noqa: E402
from simulate_inputs import MOCK_OWNED  # noqa: E402

OUT = C.CACHE / "explain_request_example.json"
TEXT = "像 Hades，但别太难"
TOP = 20   # games listed per ranking in the output (the page picks a few of them)


def round1(kb, spec):
    """Steps 2-3 exactly as Recommender.recommend does them, kept for the explanation."""
    fr = hard_filter(kb, spec)
    assert not spec.mechanics, "mechanics fallback not handled here"
    pool = fr.status >= UNKNOWN
    rel, details = relevance(kb, spec, pool)
    cand = candidates(kb, rel, fr.status == PASS, details)
    return fr, pool, rel, details, cand


def explain(rec, spec, shared, fr, pool, rel, details, cand):
    kb = rec.kb
    name = lambda i: kb.display_name(int(kb.appids[i]))
    taste, s = details["me"]
    own = {i: shared[i] for i in cand}                 # this case's own candidates, shared LLM scores
    norm = dict(details["norm"])
    after = combine({"me": fuse(kb, norm["me"], own)}, pool)
    ranked = rank(kb, spec, after, fr, rec.prices)
    res = rec.recommend(spec, rerank_scores={"me": {int(kb.appids[i]): v for i, v in own.items()}})
    picks = [c["appid"] for c in res.picks]
    assert picks == [int(kb.appids[i]) for i in ranked.picks], "explain drifted from Recommender.recommend"

    pidx = np.flatnonzero(fr.status == PASS)
    rank_of = lambda arr, i: int((arr[pidx] > arr[i]).sum()) + 1 if fr.status[i] == PASS else None
    bonus = s.evidence.get("lib_bonus")
    lib_anchor = s.evidence.get("lib_anchor")

    fused = s.score - (C.LIB_BONUS * bonus if bonus is not None else 0)   # channel fusion before the library bonus

    def row(i):
        i = int(i)
        out = {"appid": int(kb.appids[i]), "name": name(i),
               "tag": r3(s.parts["tag"][i]), "colike": r3(s.parts["colike"][i]),
               "feel": r3(s.parts["feel"][i]) if "feel" in s.parts else None,
               "fused": r3(fused[i]), "with_bonus": r3(s.score[i]),
               "round1": r3(rel[i]), "round1_rank": rank_of(rel, i),
               "in_rerank": i in own, "llm": own.get(i),
               "after": r3(after[i]), "after_rank": rank_of(after, i),
               "picked": int(kb.appids[i]) in picks,
               "quality": r3(kb.quality[i])}
        if bonus is not None:
            out["lib_bonus"] = r3(bonus[i])                         # 0-1 inside the seed pool, x LIB_BONUS added
            out["lib_added"] = r3(C.LIB_BONUS * bonus[i])
            out["lib_anchor"] = kb.display_name(int(lib_anchor[i])) if bonus[i] > 0 else None
        return out

    # MMR rounds, the same loop as ranking.rank
    rounds, chosen, remaining = [], [], set(ranked.shortlist)
    base = ranked.base
    while len(chosen) < C.PICK and remaining:
        rated = {r for r in remaining if kb.rating_ok[r]} or remaining
        top = max(after[r] for r in rated)
        window = [r for r in rated if after[r] >= top - C.DELTA]
        red = {r: max((float(kb.T[r] @ kb.T[c]) for c in chosen), default=0.0) for r in window}
        closest = {r: (name(max(chosen, key=lambda c: float(kb.T[r] @ kb.T[c]))) if chosen else None) for r in window}
        mmr = {r: C.MMR_LAMBDA * base[r] - (1 - C.MMR_LAMBDA) * red[r] for r in window}
        best = max(window, key=lambda r: (mmr[r], after[r]))
        rounds.append({"chosen": name(best), "window": [
            {"name": name(r), "after": r3(after[r]), "base": r3(base[r]), "redundancy": r3(red[r]),
             "closest": closest[r], "mmr": r3(mmr[r])} for r in sorted(window, key=lambda r: -mmr[r])]})
        chosen.append(best)
        remaining.discard(best)
    assert chosen == list(ranked.picks), "MMR loop drifted from ranking.rank"

    order1 = pidx[np.argsort(-rel[pidx], kind="stable")]
    order2 = pidx[np.argsort(-after[pidx], kind="stable")]
    show = list(dict.fromkeys([int(i) for i in order1[:TOP]] + [int(i) for i in order2[:TOP]] + list(ranked.picks)))
    out = {"pool": int(pool.sum()), "pass": int((fr.status == PASS).sum()),
           "round1_range": {"min": r3(s.score[pool].min()), "max": r3(s.score[pool].max())},   # min-max -> 第一轮分
           "llm_range": {"min": min(own.values()), "max": max(own.values())},
           "excluded": {kb.display_name(int(a)): w for a, w in
                        next(r for r in fr.rules if r.key == "exclude").reason.items() if int(a) in kb.pos},
           "anchors": {kb.display_name(int(a)): w for a, w in taste.anchors.items()},
           "library_anchors": {kb.display_name(int(a)): w for a, w in taste.library.items()},
           "rerank_candidates": [name(i) for i in cand],
           "games": [row(i) for i in show],
           "round1_top": [name(i) for i in order1[:TOP]],
           "after_top": [name(i) for i in order2[:TOP]],
           "shortlist": [name(i) for i in ranked.shortlist],
           "rounds": rounds,
           "picks": [kb.display_name(a) for a in picks]}
    if bonus is not None:
        sp = np.flatnonzero(bonus > 0)
        out["seed_pool"] = {"size": C.SEED_POOL, "with_bonus": int(len(sp))}
        # games whose round-1 rank the library changed: rank without the bonus vs with it
        no_bonus = minmax(s.score - C.LIB_BONUS * bonus, pool)
        moved = []
        for i in np.flatnonzero(bonus > 0):
            a, b = rank_of(no_bonus, i), rank_of(rel, i)
            if a is not None:
                moved.append({**row(i), "rank_without_lib": a, "score_without_lib": r3(no_bonus[i])})
        out["lib_moved"] = sorted(moved, key=lambda x: x["round1_rank"])
    ranks = {int(kb.appids[i]): (rank_of(rel, i), rank_of(after, i)) for i in pidx}
    return out, ranks


def main():
    llm = LLM()
    rec = Recommender(llm=llm, live_prices=False, reasons=False)
    kb = rec.kb
    old = json.loads(OUT.read_text(encoding="utf-8")) if "--reuse" in sys.argv else None
    t0 = time.time()
    if old:   # the recorded parse, no LLM call
        p = ParsedRequest(**old["parsed"])
        spec2 = rec.understander.to_spec(p, TEXT)
    else:
        p, spec2 = rec.understand(TEXT)
    t_understand = round(time.time() - t0, 1)
    spec3 = spec2.model_copy(deep=True)
    spec3.members[0].library = Library(owned=parse_owned(MOCK_OWNED).owned)

    r2 = round1(kb, spec2)
    r3_ = round1(kb, spec3)
    texts = {k: (with_game_names(kb, spec2, v) if C.RERANK_GAME_NAMES else v)
             for k, v in targets_with_words(spec2, kb).items()}
    union = list(dict.fromkeys(r2[-1] + r3_[-1]))
    t0 = time.time()
    if old:   # the recorded rerank scores
        shared = {kb.pos[int(a)]: v for a, v in old["llm_scores_by_appid"].items()}
        assert set(union) <= set(shared), "rerank candidates changed since the recorded run"
    else:
        shared = llm_scores(kb, llm, texts, union)["me"]
    t_rerank = round(time.time() - t0, 1)

    tag = lambda ids: [kb.tag_name(t) for t in ids]
    out = {
        "date": old["date"] if old else time.strftime("%Y-%m-%d"), "model": old["model"] if old else llm.model,
        "text": TEXT,
        "config": {"weights": dict(C.WEIGHTS), "fusion": C.FUSION, "fusion_eps": C.FUSION_EPS, "feel_w": C.FEEL_W,
                   "seed_pool": C.SEED_POOL, "lib_bonus": C.LIB_BONUS, "rerank_n": C.RERANK_N,
                   "rerank_extra": C.RERANK_EXTRA, "rerank_w": C.RERANK_W, "pick": C.PICK, "delta": C.DELTA,
                   "mmr_lambda": C.MMR_LAMBDA},
        "seconds": old["seconds"] if old else {"understand": t_understand, "rerank": t_rerank},
        "parsed": p.model_dump(exclude_defaults=True),
        "spec": {"seeds": [kb.display_name(a) for a in spec2.seeds], "feel_want": tag(spec2.feel_want),
                 "feel_avoid": tag(spec2.feel_avoid), "preference_text": spec2.preference_text,
                 "mechanics": tag(spec2.mechanics), "avoid_tags": tag(spec2.members[0].avoid_tags),
                 "library_policy": spec2.library_policy},
        "rerank_text": texts.get("me"),
        "rerank_union": len(union),
        "llm_scores": {kb.display_name(int(kb.appids[i])): v for i, v in shared.items()},
        "llm_scores_by_appid": {str(int(kb.appids[i])): v for i, v in shared.items()},
    }
    out["words_only"], ranks2 = explain(rec, spec2, shared, *r2)
    out["words_and_library"], _ = explain(rec, spec3, shared, *r3_)
    for g in out["words_and_library"]["games"] + out["words_and_library"]["lib_moved"]:   # the same game in ②
        g["words_only_round1_rank"], g["words_only_after_rank"] = ranks2.get(g["appid"], (None, None))
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("wrote", OUT)
    for k in ("words_only", "words_and_library"):
        print(k, out[k]["picks"])


if __name__ == "__main__":
    main()
