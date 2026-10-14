import numpy as np

from conftest import CIV6, HADES, IT_TAKES_TWO, STARDEW
from playnext import config as C
from playnext.pipeline import Recommender
from playnext.ranking import fold_series, rank
from playnext.relax import analyse, subset_counts
from playnext.rules import PASS, UNKNOWN, hard_filter
from playnext.scoring import Taste, group_aggregate, library_anchors, member_taste, personal, relevance
from playnext.spec import Budget, Library, Member, SessionSpec, Site


def test_library_anchor_weights(kb):
    m = Member(library=Library(owned={CIV6: 300, HADES: 0.5, STARDEW: 0}))
    a = library_anchors(kb, m)
    assert STARDEW not in a                      # no Steam playtime -> not an anchor
    assert 0 < a[CIV6] <= 1
    assert a.get(HADES, 0) < a[CIV6]             # 0.5 h of Hades sits near the bottom of its distribution
    hidden = Member(library=Library(owned={CIV6: 0, HADES: 0}, playtime_hidden=True))
    assert library_anchors(kb, hidden) == {}


def test_seed_pool_bonus_is_bounded(kb):
    pool = np.ones(kb.n, bool)
    m = Member(library=Library(owned={CIV6: 300, STARDEW: 100}))
    t = member_taste(kb, m, extra_seeds=[HADES])
    assert set(t.anchors) == {HADES} and set(t.library) == {CIV6, STARDEW}
    with_lib = personal(kb, t, pool)
    without = personal(kb, Taste(anchors={HADES: 1.0}), pool)
    d = with_lib.score - without.score
    assert d.min() >= -1e-6 and d.max() <= C.LIB_BONUS + 1e-6
    assert (d > 0).sum() <= C.SEED_POOL


def test_group_aggregate():
    a, b = np.array([1.0, 0.5, 0.0]), np.array([0.0, 0.5, 1.0])
    mm = group_aggregate([a, b], "mean_min")
    assert np.argmax(mm) == 1                    # the compromise wins over one-sided favourites
    nash = group_aggregate([a, b], "nash")
    assert np.argmax(nash) == 1


def test_fold_series_keeps_one_per_collection(kb):
    order = np.argsort(-kb.popularity)[:400]
    kept, folded = fold_series(kb, order, 50)
    seen = set()
    for i in kept:
        s = kb.series_of.get(int(kb.appids[i]), set())
        assert not (s & seen)
        seen |= s


def test_rank_respects_floor_and_window(kb, prices):
    spec = SessionSpec(seeds=[HADES])
    fr = hard_filter(kb, spec)
    rel, _ = relevance(kb, spec, fr.status >= UNKNOWN)
    r = rank(kb, spec, rel, fr, prices)
    assert len(r.picks) == C.PICK
    assert all(kb.rating_ok[i] for i in r.picks)
    assert all(fr.status[i] == PASS for i in r.picks)
    best = max(rel[i] for i in r.shortlist)
    assert rel[r.picks[0]] >= best - C.DELTA


def test_subset_counts_matches_brute_force():
    rng = np.random.default_rng(0)
    masks = rng.integers(0, 16, 200)
    f = subset_counts(masks, 4)
    for s in range(16):
        assert f[s] == sum(1 for m in masks if (m & ~s) == 0)


def test_relax_suggests_budget(kb):
    spec = SessionSpec(seeds=[HADES], budget=Budget(amount=0), mechanics=[])
    fr = hard_filter(kb, spec)
    sugg = analyse(kb, spec, fr)
    assert sugg and any(c["key"] in ("budget", "unknown") for s in sugg for c in s["changes"])


def test_pipeline_group_and_empty(kb):
    rec = Recommender(kb=kb, live_prices=False)
    res = rec.recommend(SessionSpec(members=[Member(name=f"P{i}") for i in range(4)], seeds=[IT_TAKES_TWO],
                                    interaction="coop", sites=[Site(members=[i]) for i in range(4)]))
    assert res.picks and all(c["setup"]["kind"] == "online" for c in res.picks)
    for c in res.picks:
        mx = c["setup"]["max_players"]
        assert mx is None or mx >= 4             # no hard-constraint violations (design 7, CVR = 0)
    res = rec.recommend(SessionSpec(members=[Member(name=f"P{i}") for i in range(20)], seeds=[IT_TAKES_TWO],
                                    interaction="coop", sites=[Site(members=list(range(20)))], budget=Budget(amount=1)))
    assert not res.picks and res.relax
    res = rec.recommend(SessionSpec())
    assert res.picks and any("口味" in n for n in res.notes)  # cold start: rating prior plus a hint
