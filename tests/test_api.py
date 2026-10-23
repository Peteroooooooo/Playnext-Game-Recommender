import pytest
from fastapi.testclient import TestClient

from conftest import HADES, IT_TAKES_TWO
from playnext import api
from playnext.pipeline import Recommender
from playnext.spec import Budget, Library, Member, SessionSpec


@pytest.fixture(scope="module")
def client(kb):
    api._state["rec"] = Recommender(kb=kb, llm=None, live_prices=False, reasons=False)
    return TestClient(api.app)


def test_search_and_tags(client):
    r = client.get("/api/search", params={"q": "hades"}).json()
    assert r and r[0]["appid"] in (HADES, 1145350)
    t = client.get("/api/tags").json()
    assert any(x["name_en"] == "Relaxing" for x in t["common"])


def test_form_single_and_card_action(client):
    r = client.post("/api/recommend", json={"form": {"seeds": [HADES]}}).json()
    assert len(r["picks"]) == 5
    sid, first = r["session_id"], r["picks"][0]["appid"]
    r2 = client.post("/api/card", json={"session_id": sid, "appid": first, "action": "played"}).json()
    assert first not in [c["appid"] for c in r2["picks"]]


def test_form_group(client):
    form = {"members": [{"name": "A", "site": 0}, {"name": "B", "site": 1}, {"name": "C", "site": 2}],
            "seeds": [IT_TAKES_TWO], "interaction": "coop", "budget": 100}
    r = client.post("/api/recommend", json={"form": form}).json()
    assert r["picks"] and all(c["setup"]["kind"] == "online" for c in r["picks"])


def test_near_misses_carry_poster_facts_and_relax(client):
    form = {"members": [{"name": "A", "site": 0, "avoid_tags": [1667]}, {"name": "B", "site": 1}],
            "seeds": [IT_TAKES_TWO], "interaction": "coop", "budget": 1}
    r = client.post("/api/recommend", json={"form": form}).json()
    assert r["failed"]
    for f in r["failed"]:
        assert "price" in f and "pct_positive" in f and f["miss"]["cause"]
        assert not any("雷区" in w for w in f["why"])   # what the user ruled out is never a near miss
    budget = [f for f in r["failed"] if f["miss"]["cause"] == "budget"]
    assert budget and all(f["relax"] == "budget" for f in budget)
    r2 = client.post("/api/relax", json={"session_id": r["session_id"], "key": "budget"}).json()
    assert len(r2["picks"]) == 5 and r2["understood"]["budget"] is None


def test_rerun_after_library_import_drops_played_picks(client):
    r = client.post("/api/recommend", json={"form": {"seeds": [HADES]}}).json()
    sid, picks = r["session_id"], [c["appid"] for c in r["picks"]]
    played, owned_only = picks[0], picks[1]
    api.SESSIONS[sid]["libraries"][0] = Library(is_public=True, owned={played: 120.0, owned_only: 0.0})
    r2 = client.post("/api/rerun", json={"session_id": sid}).json()
    now = [c["appid"] for c in r2["picks"]]
    assert played not in now and r2["played_out"] == [played]
    assert owned_only in now   # owned but never played stays in, marked on the card
    assert r2["libraries"]["0"]["owned"] == 2
    assert client.post("/api/rerun", json={"session_id": "nope"}).status_code == 404


def test_english_output(client):
    r = client.post("/api/recommend", json={"form": {"seeds": [HADES]}, "lang": "en"}).json()
    c = r["picks"][0]
    assert c["name"] == c["name_en"]
    assert client.post("/api/followup", json={"session_id": "nope", "text": "x", "lang": "en"}).json()["detail"] \
        == "Session expired, please send your request again"


def test_merge_form_region_covers_people_from_text():
    spec = SessionSpec(members=[Member(name="我"), Member(name="成员2"), Member(name="成员3")])
    form = api.FormIn(members=[api.MemberIn(region="US")])
    out = api.merge_form(spec, form, {})
    assert [m.region for m in out.members] == ["US", "US", "US"]


def test_merge_form_keeps_currency_said_in_text():
    spec = SessionSpec(members=[Member(name="我", region="US"), Member(name="成员2", region="US")],
                       budget=Budget(amount=20, currency="USD"))
    form = api.FormIn(members=[api.MemberIn(region="CN")])
    out = api.merge_form(spec, form, {})
    assert [m.region for m in out.members] == ["US", "US"]


def test_text_needs_llm(client):
    assert client.post("/api/recommend", json={"text": "像 Hades 的"}).status_code == 503


def _lines(resp):
    import json
    return [json.loads(x) for x in resp.text.splitlines() if x.strip()]


def test_stream_reports_real_steps_then_the_result(client):
    resp = client.post("/api/recommend?stream=1", json={"form": {"seeds": [HADES]}})
    assert resp.headers["content-type"].startswith("application/x-ndjson")
    ev = _lines(resp)
    assert ev[0] == {"type": "plan", "steps": ["pick", "rerank", "prices"]}
    steps = [(e["step"], e["state"]) for e in ev if e["type"] == "step"]
    # no LLM in the test client, so the rerank is skipped; every other step starts before it is done
    assert steps == [("pick", "start"), ("pick", "done"), ("rerank", "skip"), ("prices", "start"), ("prices", "done")]
    assert ev[-1]["type"] == "result" and len(ev[-1]["data"]["picks"]) == 5
    plain = client.post("/api/recommend", json={"form": {"seeds": [HADES]}}).json()
    assert [c["appid"] for c in plain["picks"]] == [c["appid"] for c in ev[-1]["data"]["picks"]]


def test_stream_turns_http_errors_into_an_error_line(client):
    ev = _lines(client.post("/api/rerun?stream=1", json={"session_id": "nope", "lang": "en"}))
    assert ev[-1]["type"] == "error" and ev[-1]["status"] == 404 and "expired" in ev[-1]["detail"]
