"""English output of the card fields built in cards.py / db.py (L("中文", "English") at the point of construction)."""
import re

import pytest

from conftest import HADES, IT_TAKES_TWO, FakeLLM
from playnext import i18n
from playnext.cards import _consistent, write_reasons
from playnext.db import _edge_label
from playnext.pipeline import Recommender
from playnext.spec import Budget, Member, SessionSpec, Site

CJK = re.compile(r"[一-鿿]")


@pytest.fixture
def en():
    i18n.set_lang("en")
    yield
    i18n.set_lang("zh")


def _texts(card):
    """(field, text) for every user-facing string cards.py builds; rule reasons (unknown, rank_step) and the
    PostgreSQL path source come from other modules and are not checked here."""
    out = [("reason", card.get("reason"))]
    price = card.get("price", {})
    out += [("price.text", price.get("text")), ("price.note", price.get("note")),
            ("rating.text", card["rating"]["text"]), ("library", card.get("library")),
            ("library_hint", card.get("library_hint")), ("time_to_beat", card.get("time_to_beat")),
            ("colike.text", (card.get("colike") or {}).get("text"))]
    out += [("lineage", s) for s in card.get("lineage", [])]
    like = card.get("like", {})
    for k in ("shared_core_tags", "feel_hits", "feel_bad"):
        out += [(f"like.{k}", s) for s in like.get(k) or []]
    out += [("like.quote", like.get("quote"))]
    diff = card.get("diff") or {}
    out += [(f"diff.{k}", s) for k in ("more", "less") for s in diff.get(k, [])]
    setup = card.get("setup") or {}
    for k in ("kind_zh", "controller", "purchase", "friends_pass", "note"):
        out.append((f"setup.{k}", setup.get(k)))
    out += [("setup.steps", s) for s in setup.get("steps", [])]
    out += [("setup.alternatives", s) for s in setup.get("alternatives") or []]
    return [(k, v) for k, v in out if v]


def _cjk_fields(cards):
    bad = []
    for c in cards:
        # a game whose only store name is Chinese keeps it: take card names and quoted names out first
        names = {c["name"], (c.get("like") or {}).get("anchor"), (c.get("colike") or {}).get("anchor")} - {None}
        for k, v in _texts(c):
            for n in names:
                v = v.replace(n, "")
            v = re.sub(r"\"[^\"]*\"", "", v)
            if CJK.search(v):
                bad.append((c["appid"], k, v))
    return bad


def test_single_player_cards_in_english(kb, en):
    rec = Recommender(kb=kb, llm=None, live_prices=False, reasons=False)
    res = rec.recommend(SessionSpec(seeds=[HADES]))
    assert res.picks
    assert all(c["name"] == c["name_en"] for c in res.picks)
    assert any(c.get("reason") for c in res.picks) and any(c.get("colike") for c in res.picks)
    assert _cjk_fields(res.picks) == []


def test_group_cards_in_english(kb, en):
    rec = Recommender(kb=kb, llm=None, live_prices=False, reasons=False)
    spec = SessionSpec(members=[Member(name=n) for n in "ABC"], seeds=[IT_TAKES_TWO], interaction="coop",
                       sites=[Site(members=[i]) for i in range(3)], budget=Budget(amount=100))
    res = rec.recommend(spec)
    assert res.picks and all(c["setup"]["kind"] == "online" for c in res.picks)
    assert all(c["setup"]["kind_zh"] == "Online" and c["setup"]["purchase"] for c in res.picks)
    assert _cjk_fields(res.picks) == []


def test_chinese_stays_default(kb):
    res = Recommender(kb=kb, llm=None, live_prices=False, reasons=False).recommend(SessionSpec(seeds=[HADES]))
    assert "好评率" in res.picks[0]["rating"]["text"]


def test_english_reason_consistency(en):
    card = {"name": "X", "like": {"anchor": "Hades", "shared_core_tags": ["Action", "Roguelike"]},
            "rating": {"pct_positive": 95}}
    assert _consistent("Like \"Hades\", it is built around Action and Roguelike runs; 95% positive.", card)
    assert _consistent("Like Hades, a fast Roguelike.", card)
    assert not _consistent("Rated 99% positive.", card)
    assert not _consistent("Feels like \"Dark Souls\".", card)
    assert not _consistent("Fans of Dark Souls will like it.", card)
    cards = [dict(card, appid=1)]
    llm = FakeLLM(['{"1": "Like \\"Hades\\", built around Action."}'])
    write_reasons(cards, llm)
    assert cards[0]["reason_source"] == "llm"
    assert llm.calls[0][1].startswith("Player's request")


def test_lineage_edge_labels(en):
    assert _edge_label("开发") == "developer" and _edge_label("IGDB 相似") == "IGDB similar"
    i18n.set_lang("zh")
    assert _edge_label("系列") == "系列"
