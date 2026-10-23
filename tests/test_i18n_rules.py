"""English output of the rules, relaxations, notes and the 'understood' block (cards are tested elsewhere)."""
import re

import pytest

from conftest import DEEP_ROCK, HADES, IT_TAKES_TWO, STARDEW
from playnext import i18n
from playnext.pipeline import Recommender
from playnext.relax import analyse
from playnext.rules import FAIL, hard_filter
from playnext.spec import Budget, Library, Member, SessionSpec, Site

CJK = re.compile(r"[一-鿿]")
HORROR = 1667


@pytest.fixture
def en():
    i18n.set_lang("en")
    try:
        yield
    finally:
        i18n.set_lang("zh")


@pytest.fixture(scope="module")
def rec(kb):
    return Recommender(kb=kb, llm=None, live_prices=False, reasons=False)


def no_cjk(texts, names=()):
    """Every text is free of CJK once game names (which may exist only in Chinese) are taken out."""
    names = sorted({n for n in names if n}, key=len, reverse=True)
    for t in texts:
        if t is None:
            continue
        s = str(t)
        for n in names:
            s = s.replace(n, "")
        assert not CJK.search(s), t


def rule_texts(fr):
    out = []
    for r in fr.rules:
        out.append(r.label)
        out += list(r.reason.values())
    for s in fr.setups.values():
        out += list(s.reason.values())
        out += [src for _, src in s.max_players.values()]
    return out


def test_group_online_rules_in_english(kb, en):
    spec = SessionSpec(members=[Member(name=f"P{i}") for i in range(5)], seeds=[DEEP_ROCK], interaction="coop",
                       sites=[Site(members=[i]) for i in range(5)], budget=Budget(amount=50, currency="CNY"))
    fr = hard_filter(kb, spec)
    no_cjk(rule_texts(fr))
    assert fr.rules[0].reason[DEEP_ROCK] == "seed game"
    assert "1 short" in fr.setups["online"].reason[DEEP_ROCK]
    setup = next(r for r in fr.rules if r.key == "setup")
    assert setup.label.startswith("5 players · Online") and "per person budget" in setup.label
    no_cjk([c["text"] for o in analyse(kb, spec, fr) for c in o["changes"]])


def test_single_budget_rules_in_english(kb, en):
    spec = SessionSpec(members=[Member(played_elsewhere=[STARDEW], language="schinese", platform="deck", age_limit=12)],
                       seeds=[HADES], budget=Budget(amount=20, currency="CNY"), only_discounted=True,
                       single_player=True, excluded=[IT_TAKES_TWO])
    fr = hard_filter(kb, spec)
    no_cjk(rule_texts(fr))
    labels = {r.key: r.label for r in fr.rules}
    assert labels["budget"] == "Budget ≤ ¥20 (daily snapshot)"
    assert labels["discount"] == "On sale" and labels["lang:"] == "supports Simplified Chinese"
    assert fr.rules[0].reason[STARDEW] == "said already played"
    budget = next(r for r in fr.rules if r.key == "budget")
    assert any(v.startswith("current price ¥") for v in budget.reason.values())


def test_group_local_avoid_in_english(kb, en):
    spec = SessionSpec(members=[Member(name="A", avoid_tags=[HORROR], avoid_content=["gore"]), Member(name="B")],
                       seeds=[IT_TAKES_TWO], interaction="coop", sites=[Site(members=[0, 1])])
    fr = hard_filter(kb, spec)
    no_cjk(rule_texts(fr))
    avoid = next(r for r in fr.rules if r.key.startswith("avoid:"))
    assert avoid.key == "avoid:A："                        # rule keys do not depend on the language
    assert avoid.label.startswith("A avoids: ") and kb.tag_en[HORROR] in avoid.label
    assert any(v.startswith("content you avoid: ") for v in avoid.reason.values())


def test_zh_text_unchanged(kb):
    spec = SessionSpec(members=[Member(name="A", avoid_tags=[HORROR]), Member(name="B")], seeds=[IT_TAKES_TWO],
                       sites=[Site(members=[0, 1])])
    fr = hard_filter(kb, spec)
    assert fr.rules[0].reason[IT_TAKES_TWO] == "种子游戏"
    assert next(r for r in fr.rules if r.key.startswith("avoid:")).label.startswith("A的雷区：")


def result_texts(res):
    d = res.to_dict()
    texts = list(d["notes"]) + [r["rule"] for r in d["rules"]]
    texts += [c["text"] for o in d["relax"] for c in o["changes"]]
    for b in d["backups"]:
        texts += [b.get("label"), b.get("owned")]
    for x in d["failed"] + d["unknown"]:
        texts += x["why"]
    for c in d["picks"]:
        texts += [c.get("mechanics_note"), (c.get("lineage_path") or {}).get("source")]
    u = d["understood"]
    texts += [u["preference_text"]] + u["feel_want"] + u["feel_avoid"] + u["mechanics"]
    for m in u["members"]:
        texts += [m["name"]] + [str(a) for a in m["avoid"]]
    names = [x["name"] for x in d["backups"] + d["failed"] + d["unknown"]]
    names += [n for x in d["backups"] for n in x.get("series_names", [])]
    names += [n for o in d["relax"] for n in o["examples"]]
    names += u["seeds"] + u["excluded"] + [n for v in u["ambiguous"].values() for n in v]
    return texts, names


def test_recommend_in_english(kb, rec, en):
    tid = {v: int(k) for k, v in kb.tag_en.items()}
    spec = SessionSpec(members=[Member(library=Library(is_public=False))], seeds=[HADES],
                       mechanics=[tid["Roguelike"], tid["Base Building"]], feel_want=[tid["Relaxing"]],
                       budget_unsupported=Budget(amount=20, currency="EUR"),
                       ambiguous={"hades": [HADES, 1145350]})
    res = rec.recommend(spec)
    texts, names = result_texts(res)
    no_cjk(texts, names)
    assert res.understood["members"][0]["name"] == "Me"
    assert any("Read “hades” as" in n for n in res.notes)
    assert "Mechanics: Roguelike + Base Building are all core tags" in [r["rule"] for r in res.rules]
    # a combination no game has as core tags: the fallback note and the per-card mechanics note
    res = rec.recommend(spec.model_copy(update={"mechanics": [tid["Dating Sim"], tid["Base Building"]]}))
    texts, names = result_texts(res)
    no_cjk(texts, names)
    assert any("core tags" in n for n in res.notes)


def test_conflict_in_english(kb, rec, en):
    # budget 0 and "on sale only" cannot both hold: nothing passes and the relax suggestions are shown
    spec = SessionSpec(members=[Member(name="P0", avoid_tags=[HORROR]), Member(name="P1"), Member(name="P2")],
                       seeds=[IT_TAKES_TWO], interaction="coop", budget=Budget(amount=0, currency="CNY"),
                       accept_unknown=False)
    res = rec.recommend(spec)
    texts, names = result_texts(res)
    no_cjk(texts, names)
    assert res.failed and all(f["why"] for f in res.failed)
    solo = SessionSpec(members=[Member()], budget=Budget(amount=0, currency="CNY"), only_discounted=True)
    res = rec.recommend(solo)
    assert not res.picks and res.relax
    texts, names = result_texts(res)
    no_cjk(texts, names)
    assert any(c["key"] == "discount" and c["text"] == "Don't require “on sale”" for o in res.relax for c in o["changes"])


def test_lang_reset(kb):
    assert i18n.lang() == "zh" and Member().name == "我"
