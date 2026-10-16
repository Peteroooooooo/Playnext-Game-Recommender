"""Group 'already played', budget currencies, cross-region purchases, the failed list, the per-target rerank, the
library playtime fallback and the slow-loop store."""
import json

import numpy as np

from conftest import CIV6, DEEP_ROCK, HADES, IT_TAKES_TWO, STARDEW, TERRARIA, FakeLLM
from playnext import profiles
from playnext.pipeline import Recommender
from playnext.rerank import fuse, llm_scores, targets_with_words
from playnext.rules import FAIL, PASS, UNKNOWN, hard_filter, over_budget
from playnext.scoring import combine, library_anchors, relevance
from playnext.spec import Budget, Library, Member, SessionSpec, Site
from playnext.understand import ParsedRequest, Understander


def group(n, **kw):
    return SessionSpec(members=[Member(name=f"P{i}") for i in range(n)], **kw)


def test_group_excludes_games_said_played(kb):
    spec = group(3, interaction="coop")
    spec.members[0].played_elsewhere = [TERRARIA]
    fr = hard_filter(kb, spec)
    assert fr.status[kb.pos[TERRARIA]] == FAIL
    assert "说过已经玩过" in fr.rules[0].reason[TERRARIA]
    # Steam playtime alone does not exclude for a group
    spec = group(3, interaction="coop")
    spec.members[1].library = Library(owned={DEEP_ROCK: 50})
    assert hard_filter(kb, spec).rules[0].status[kb.pos[DEEP_ROCK]] == PASS


def test_budget_currency_mapping(kb):
    u = Understander(kb, None)
    p = ParsedRequest.model_validate({"budget": {"amount": 20, "currency": "eur"}, "party": {"size": 3}})
    spec = u.to_spec(p, "x")
    assert spec.budget is None and spec.budget_unsupported.currency == "EUR"
    res = Recommender(kb=kb, live_prices=False, reasons=False).recommend(spec)
    assert any("20 EUR" in n for n in res.notes)
    p = ParsedRequest.model_validate({"budget": {"amount": 14, "currency": "USD"}})
    spec = u.to_spec(p, "x")
    assert spec.members[0].region == "US" and spec.budget.currency == "USD"
    fr = hard_filter(kb, spec)
    label = next(r.label for r in fr.rules if r.key == "budget")
    assert "$14" in label and "¥" not in label


def test_single_player_only_when_asked(kb):
    from playnext.rules import CAT_SINGLE
    mp_only = next(int(a) for a in kb.appids if kb.categories.get(int(a)) and CAT_SINGLE not in kb.categories[int(a)])
    assert hard_filter(kb, SessionSpec()).status[kb.pos[mp_only]] == PASS     # one person asking is not "alone"
    assert hard_filter(kb, SessionSpec(single_player=True)).status[kb.pos[mp_only]] == FAIL
    u = Understander(kb, None)
    assert u.to_spec(ParsedRequest.model_validate({"single_player": True}), "x").single_player
    assert not u.to_spec(ParsedRequest.model_validate({"single_player": True, "party": {"size": 3}}), "x").single_player


def test_outside_seed_is_a_content_anchor(kb, monkeypatch):
    from playnext import outside
    fake = 9_999_990
    monkeypatch.setattr(outside, "fetch", lambda a, timeout=5: {"appid": fake, "name": "Some Roguelite", "text": "",
                                                               "tags": {kb.tag_by_name("Roguelike") if hasattr(kb, "tag_by_name") else
                                                                        int(kb.tag_en[kb.tag_en == "Roguelike"].index[0]): 100.0,
                                                                        int(kb.tag_en[kb.tag_en == "Action"].index[0]): 80.0}})
    spec = SessionSpec(outside_seeds=[fake])
    rel, details = relevance(kb, spec, np.ones(kb.n, bool))
    assert rel is not None and details["me"][0].outside[0]["name"] == "Some Roguelite"
    roguelike = int(kb.tag_en[kb.tag_en == "Roguelike"].index[0])
    top = np.argsort(-rel)[:20]
    assert sum(roguelike in kb.tagset.get(int(kb.appids[i]), set()) for i in top) >= 15
    res = Recommender(kb=kb, live_prices=False, reasons=False).recommend(spec)
    assert res.picks and any("不在核心库" in n for n in res.notes)


def test_excluded_names_and_party_of_two(kb):
    u = Understander(kb, None)
    p = ParsedRequest.model_validate({"excluded": ["Terraria"], "party": {"size": 2}})
    spec = u.to_spec(p, "x")
    assert TERRARIA in spec.excluded and spec.party_size == 2
    assert hard_filter(kb, spec).status[kb.pos[TERRARIA]] == FAIL


def test_cross_region_purchase_is_not_compared_across_currencies(kb):
    from playnext.rules import CAT_LOCAL_COOP, CAT_REMOTE, _price_cost
    a = next(int(x) for x in kb.appids if {CAT_REMOTE, CAT_LOCAL_COOP} <= kb.categories.get(int(x), set())
             and not kb.is_free[int(x)] and _price_cost(kb, int(x), "CN") and _price_cost(kb, int(x), "US"))
    spec = SessionSpec(members=[Member(name="A", region="CN"), Member(name="B", region="US")],
                       interaction="coop", setup_hint="remote", budget=Budget(amount=1, scope="team_total", currency="CNY"))
    fr = hard_filter(kb, spec)
    plan = fr.setups["remote"].plan[a]
    assert plan["host"] == 0 and [j for j, _ in plan["alternatives"]] == [1]
    # team total across currencies: not summed, so it cannot fail the budget
    mixed = {"per_member": {0: 30.0, 1: 9.99}, "cost": {"CN": 30.0, "US": 9.99}}
    assert over_budget(spec, mixed) is None
    one = {"per_member": {0: 30.0}, "cost": {"CN": 30.0}}
    assert over_budget(spec, one) == 30.0
    per = spec.model_copy(update={"budget": Budget(amount=5, scope="per_person", currency="USD")})
    assert over_budget(per, mixed) == 9.99      # only B's dollar price is compared with a dollar budget


def test_failed_list_explains_near_misses(kb):
    rec = Recommender(kb=kb, live_prices=False, reasons=False)
    spec = group(5, seeds=[IT_TAKES_TWO], interaction="coop", sites=[Site(members=[i]) for i in range(5)])
    res = rec.recommend(spec)
    assert res.failed and all(f["why"] for f in res.failed)
    assert IT_TAKES_TWO not in {f["appid"] for f in res.failed}   # the seed itself is not a "near miss"
    assert any("个位" in w or "模式" in w for f in res.failed for w in f["why"])


def test_mechanics_top_up_after_strict_matches(kb):
    from itertools import combinations
    from collections import Counter
    both = Counter(p for a in kb.appids for p in combinations(sorted(kb.core.get(int(a), [])), 2))
    pair = next(p for p, n in sorted(both.items(), key=lambda kv: -kv[1]) if 1 <= n <= 3)
    res = Recommender(kb=kb, live_prices=False, reasons=False).recommend(SessionSpec(mechanics=list(pair)))
    strict = [c for c in res.picks if "mechanics_note" not in c]
    assert strict and len(res.picks) > len(strict)
    assert res.picks[:len(strict)] == strict          # strict matches first, top-ups after
    assert any("后面补上" in n for n in res.notes)


def test_rerank_per_target_and_combine(kb):
    spec = group(2, preference_text="轻松合作", interaction="coop")
    spec.members[1].preference_text = "想要射击"
    texts = targets_with_words(spec)
    assert set(texts) == {"shared", 1}
    pool = hard_filter(kb, spec).status >= UNKNOWN
    rel, details = relevance(kb, spec, pool)
    assert set(details["norm"]) == {"shared", 1}
    cand = [int(i) for i in np.flatnonzero(pool)[:3]]
    reply = json.dumps({"r0": {"g0": 10, "g1": 0, "g2": 5}, "r1": {"g0": 0, "g1": 10, "g2": 5}})
    scores = llm_scores(kb, FakeLLM([reply]), texts, cand)
    assert scores["shared"][cand[0]] == 10 and scores[1][cand[1]] == 10
    norm = dict(details["norm"])
    for t, sc in scores.items():
        norm[t] = fuse(kb, norm[t], sc)
    out = combine(norm, pool)
    assert out.shape == rel.shape and float(out[pool].max()) <= 1.0 + 1e-6


def test_library_fallback_percentile_and_liked(kb):
    m = Member(library=Library(owned={CIV6: 300, STARDEW: 20}), liked={HADES: 0.5})
    a = library_anchors(kb, m)
    assert HADES in a and a[HADES] == 0.5
    orig = kb.playtime_pct
    kb.playtime_pct = lambda appid, h: None          # no reference distribution at all
    try:
        a = library_anchors(kb, Member(library=Library(owned={CIV6: 300, STARDEW: 20})))
    finally:
        kb.playtime_pct = orig
    assert a.get(CIV6) == 1.0 and STARDEW not in a  # own-library percentile: the shortest scores 0


def test_profile_store_memory_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(profiles.C, "CACHE", tmp_path)
    k1, k2 = profiles.profile_key("76561190000000001"), profiles.profile_key("76561190000000001")
    assert k1 == k2 and "7656119" not in k1
    s = profiles.Store.__new__(profiles.Store)
    s.mem, s.reports, s.db = {}, [], None
    assert s.save(k1, HADES, "liked") is False       # no database: kept in memory only
    s.save(k1, TERRARIA, "played")
    fb = s.load(k1)
    assert fb["liked"][HADES] == 1.0 and fb["played"] == [TERRARIA]
    m = profiles.apply(Member(), fb)
    assert TERRARIA in m.played_elsewhere and m.liked[HADES] == 1.0
    assert profiles.decay(180) == 0.5
    assert s.report(HADES, "players", "x" * 400)
    line = json.loads((tmp_path / "fact_reports.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert line["appid"] == HADES and len(line["text"]) == 300 and "account" not in line
