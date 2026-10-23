import json

import pytest

from conftest import CIV6, STARDEW, FakeLLM
from playnext.cards import _consistent, write_reasons
from playnext.library import parse_owned, resolve_steamid
from playnext.llm import LLMError, chat_json, strip_json
from playnext.pricing import price_pref
from playnext.understand import ParsedRequest, Understander


def test_strip_json():
    assert json.loads(strip_json('```json\n{"a": 1}\n```')) == {"a": 1}
    assert json.loads(strip_json('Here: {"a": [1]} ok')) == {"a": [1]}


def test_chat_json_retries_once():
    llm = FakeLLM(["not json", '{"x": 2}'])
    assert chat_json(llm, "s", "u") == {"x": 2}
    assert len(llm.calls) == 2
    with pytest.raises(LLMError):
        chat_json(FakeLLM(["bad", "still bad"]), "s", "u")


def test_parse_validates_tags_and_nulls(kb):
    good = {"seeds": ["文明6", "星露谷"], "feel_want": ["Relaxing"], "same_studio": None, "budget": {"amount": 60}}
    llm = FakeLLM(['{"feel_want": ["NotATag"]}', json.dumps(good)])
    u = Understander(kb, llm)
    p = u.parse("x")
    assert p.feel_want == ["Relaxing"] and not p.same_studio
    spec = u.to_spec(p, "x")
    assert spec.seeds == [CIV6, STARDEW]
    assert spec.budget.amount == 60


def test_to_spec_group_and_unresolved(kb):
    u = Understander(kb, None)
    p = ParsedRequest.model_validate({"seeds": ["一个不存在的游戏名字xyz"], "party": {"size": 5, "setup": "hybrid",
                                                                              "groups": [2, 1, 1, 1], "interaction": "coop"},
                                      "people": [{"name": "小张", "likes": ["Deep Rock Galactic"]}]})
    spec = u.to_spec(p, "x")
    assert spec.party_size == 5 and spec.setup_types == ["hybrid"]
    assert spec.members[1].name == "小张" and spec.members[1].seeds == [548430]
    assert spec.unresolved == ["一个不存在的游戏名字xyz"]


def test_parse_owned_privacy_states():
    assert not parse_owned({"response": {}}).is_public
    lib = parse_owned({"response": {"game_count": 2, "games": [{"appid": 1, "playtime_forever": 0},
                                                                {"appid": 2, "playtime_forever": 0}]}})
    assert lib.playtime_hidden and lib.played == set()
    lib = parse_owned({"response": {"game_count": 2, "games": [{"appid": 1, "playtime_forever": 90},
                                                                {"appid": 2, "playtime_forever": 0}]}})
    assert lib.played == {1} and lib.unplayed == {2} and lib.owned[1] == 1.5


def test_resolve_steamid_offline_forms():
    sid = "7656119" + "0000000001"
    assert resolve_steamid(f"https://steamcommunity.com/profiles/{sid}/", "k") == sid
    assert resolve_steamid(sid, "k") == sid
    assert resolve_steamid("bad name with spaces", "k") is None


def test_reason_consistency_check():
    card = {"name": "X", "like": {"anchor": "Hades", "shared_core_tags": ["动作"]}, "rating": {"pct_positive": 95}}
    assert _consistent("和《Hades》一样以动作为核心，好评 95%", card)
    assert not _consistent("好评 99%", card)
    assert not _consistent("像《Dark Souls》", card)
    cards = [dict(card, appid=1)]
    write_reasons(cards, FakeLLM(['{"1": "好评 99%"}', '{"1": "也是 99%"}']))
    assert cards[0]["reason_source"] == "template"   # inconsistent twice -> template


def test_single_mechanic_becomes_a_wish(kb):
    u = Understander(kb, None)
    one = u.to_spec(ParsedRequest.model_validate({"feel_want": ["Atmospheric"], "mechanics": ["Exploration"]}), "x")
    assert one.mechanics == [] and one.feel_want == u.tags(["Atmospheric", "Exploration"])
    two = u.to_spec(ParsedRequest.model_validate({"mechanics": ["Roguelike", "Base Building"]}), "x")
    assert two.mechanics == u.tags(["Roguelike", "Base Building"]) and two.feel_want == []


def test_recommender_ask(kb):
    from playnext.pipeline import Recommender
    rec = Recommender(kb=kb, llm=FakeLLM(['{"seeds": ["Hades"]}']), live_prices=False, reasons=False, rerank=False)
    p, res = rec.ask("像 Hades")
    assert p.seeds == ["Hades"] and res.picks and "understand" in res.timings


def test_price_pref():
    assert price_pref({"is_free": False, "final": 10, "low": 10}) == 1.0
    assert price_pref({"is_free": False, "final": 20, "low": 10}) == 0.0
    assert price_pref({"is_free": True, "final": 0, "low": None}) is None
