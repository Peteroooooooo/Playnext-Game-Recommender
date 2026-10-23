"""Requests that are only words (no seed, no feel tag) after the query encoder was removed (design 10.15)."""
import numpy as np

from conftest import HADES
from playnext.pipeline import Recommender
from playnext.rerank import candidates
from playnext.rules import PASS, UNKNOWN, hard_filter
from playnext.scoring import prior, relevance
from playnext.spec import SessionSpec


def test_words_only_ranks_by_reviews_for_the_rerank(kb):
    spec = SessionSpec(preference_text="想找剧情好的游戏")
    fr = hard_filter(kb, spec)
    pool = fr.status >= UNKNOWN
    rel, details = relevance(kb, spec, pool)
    assert rel is not None and details["me"][1].evidence.get("prior")
    idx = np.flatnonzero(pool)
    assert idx[np.argmax(rel[idx])] == idx[np.argmax(prior(kb)[idx])]
    cand = candidates(kb, rel, fr.status == PASS, details)
    assert len(cand) == 80


def test_seeds_and_feel_do_not_use_the_prior(kb):
    relaxing = next(t for t, n in kb.tag_en.items() if n == "Relaxing")
    for spec in (SessionSpec(seeds=[HADES], preference_text="类似的"), SessionSpec(preference_text="轻松", feel_want=[relaxing])):
        fr = hard_filter(kb, spec)
        _, details = relevance(kb, spec, fr.status >= UNKNOWN)
        assert not details["me"][1].evidence.get("prior")


def test_words_only_request_is_reranked(kb):
    """The LLM rerank decides among the well-reviewed pool: the game it scores 10 comes first."""
    spec = SessionSpec(preference_text="想找剧情好的游戏")
    rec = Recommender(kb=kb, llm=None, live_prices=False, reasons=False)
    cand = rec.recommend(spec, {}).debug["rerank"]["cand"]
    target = cand[-1]
    res = rec.recommend(spec, {"me": {a: (10 if a == target else 0) for a in cand}})
    assert res.picks[0]["appid"] == target
