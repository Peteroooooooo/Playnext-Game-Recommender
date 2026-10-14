import pytest
from fastapi.testclient import TestClient

from conftest import HADES, IT_TAKES_TWO
from playnext import api
from playnext.pipeline import Recommender


@pytest.fixture(scope="module")
def client(kb):
    api._state["rec"] = Recommender(kb=kb, llm=None, encoder=None, live_prices=False, reasons=False)
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


def test_text_needs_llm(client):
    assert client.post("/api/recommend", json={"text": "像 Hades 的"}).status_code == 503
