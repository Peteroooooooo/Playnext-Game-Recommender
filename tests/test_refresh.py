"""Offline tests for the daily price snapshot: every fetcher is replaced, nothing touches the network or data/."""
import os
from datetime import datetime
from types import SimpleNamespace

import pandas as pd
import pyarrow.parquet as pq
import pytest

from playnext import refresh as R

GAMES = pd.DataFrame({"appid": [10, 20, 30, 40], "name": ["Ten", "Twenty", "Thirty", "Forty"],
                      "is_free": [False, False, True, False]})
OLD_DATE = "2026-10-14"


def old_snapshot():
    rows = []
    for region, cur in (("CN", "CNY"), ("US", "USD")):
        rows += [
            {"appid": 10, "region": region, "final": 20.0, "original": None, "discount_pct": 0, "is_free": False,
             "currency": cur, "steam_low": 8.0, "steam_low_time": "2024-01-01T00:00:00+01:00"},
            {"appid": 20, "region": region, "final": 30.0, "original": None, "discount_pct": 0, "is_free": False,
             "currency": cur, "steam_low": 12.0, "steam_low_time": "2024-02-01T00:00:00+01:00"},
            {"appid": 30, "region": region, "final": None, "original": None, "discount_pct": 0, "is_free": True,
             "currency": cur, "steam_low": None, "steam_low_time": None},
            {"appid": 40, "region": region, "final": None, "original": None, "discount_pct": 0, "is_free": False,
             "currency": cur, "steam_low": None, "steam_low_time": None},
        ]
    df = pd.DataFrame(rows).sort_values("appid", kind="stable").reset_index(drop=True)  # game-major, like the real file
    return df.astype({"final": "float64", "original": "float64", "steam_low": "float64"})


class Fake:
    """Store answers: game 10 is half price today and has a new record low in CN."""

    def __init__(self):
        self.calls = []
        self.empty = set()       # regions whose Steam answer is empty
        self.symbol = {"CN": "¥", "US": "$"}
        self.low_currency = {"CN": "CNY", "US": "USD"}
        self.fail = None         # exception raised by the Steam fetcher

    def steam(self, appids, region):
        self.calls.append(("steam", region))
        if self.fail:
            raise self.fail
        if region in self.empty:
            return {}
        s = self.symbol[region]
        price = {10: (1000, 2000, 50), 20: (3000, None, 0)}
        out = {30: {"appid": 30, "success": 1, "is_free": True}, 40: {"appid": 40, "success": 1}}
        for a, (f, o, d) in price.items():
            bp = {"final_price_in_cents": str(f), "formatted_final_price": f"{s}{f / 100:.2f}", "discount_pct": d}
            if o:
                bp["original_price_in_cents"] = str(o)
            out[a] = {"appid": a, "success": 1, "best_purchase_option": bp}
        return {a: v for a, v in out.items() if a in appids}

    def lookup(self, appids, key):
        self.calls.append(("lookup", None))
        return {10: "g10", 20: "g20", 30: "g30"}

    def lows(self, gids, region, key):
        self.calls.append(("lows", region))
        c = self.low_currency[region]
        return {"g10": (5.0, c, "2026-10-15T10:00:00+02:00"), "g20": (12.0, c, "2024-02-01T00:00:00+01:00")}


@pytest.fixture
def fake(tmp_path, monkeypatch):
    path = tmp_path / "prices.parquet"
    old_snapshot().to_parquet(path, index=False)
    ts = datetime.fromisoformat(f"{OLD_DATE}T12:00:00").timestamp()
    os.utime(path, (ts, ts))
    f = Fake()
    monkeypatch.setattr(R, "PATH", path)
    monkeypatch.setattr(R, "RAW", tmp_path / "raw")  # no raw pulls: the old file is dated by its mtime
    monkeypatch.setattr(R, "core_games", lambda: GAMES)
    monkeypatch.setattr(R, "cached_itad_map", lambda: {})
    monkeypatch.setattr(R, "_env", lambda name: "test-key")
    monkeypatch.setattr(R, "_sleep", lambda s: None)
    monkeypatch.setattr(R, "fetch_steam", f.steam)
    monkeypatch.setattr(R, "lookup_itad", f.lookup)
    monkeypatch.setattr(R, "fetch_itad_lows", f.lows)
    return f


def today():
    return datetime.now().astimezone().strftime("%Y-%m-%d")


def test_refresh_replaces_with_backup(fake, tmp_path):
    old = pd.read_parquet(R.PATH)
    res = R.refresh_prices()
    assert res["status"] == "ok", res["problems"]
    backup = tmp_path / f"prices_backup_{OLD_DATE}.parquet"
    assert res["backup"] == str(backup) and pd.read_parquet(backup).equals(old)
    new = pd.read_parquet(R.PATH)
    assert list(new.columns) == R.COLUMNS and new.dtypes.equals(old.dtypes)
    assert list(zip(new["appid"], new["region"])) == list(zip(old["appid"], old["region"]))
    cn = new[new["region"] == "CN"].set_index("appid")
    assert cn.loc[10, "final"] == 10.0 and cn.loc[10, "original"] == 20.0 and cn.loc[10, "discount_pct"] == 50
    assert cn.loc[10, "steam_low"] == 5.0 and cn.loc[10, "currency"] == "CNY"
    assert pd.isna(cn.loc[20, "original"])  # like build_processed: original only when discounted
    assert bool(cn.loc[30, "is_free"]) and pd.isna(cn.loc[40, "final"])
    info = R.snapshot_info()
    assert info["source"] == "metadata" and info["snapshot_date"] == today() and set(info["regions"]) == {"CN", "US"}
    assert R.snapshot_age_days() < 0.01
    c = res["comparison"]["CN"]
    assert c["price_changed"] == 1 and c["cheaper"] == 1 and c["new_record_low"] == 1
    assert c["examples"][0]["appid"] == 10


def test_empty_region_is_rejected(fake, tmp_path):
    fake.empty.add("CN")
    before = R.PATH.read_bytes()
    res = R.refresh_prices()
    assert res["status"] == "rejected"
    assert any("CN" in p and "price" in p for p in res["problems"])
    assert R.PATH.read_bytes() == before and not list(tmp_path.glob("prices_backup_*"))


@pytest.mark.parametrize("what", ["steam", "itad"])
def test_wrong_currency_is_rejected(fake, what):
    if what == "steam":
        fake.symbol["CN"] = "$"
    else:
        fake.low_currency["CN"] = "USD"
    before = R.PATH.read_bytes()
    res = R.refresh_prices()
    assert res["status"] == "rejected" and any("CN" in p for p in res["problems"])
    assert R.PATH.read_bytes() == before


def test_one_region_keeps_the_other(fake):
    old = pd.read_parquet(R.PATH)
    res = R.refresh_prices(regions=("CN",))
    assert res["status"] == "ok"
    new = pd.read_parquet(R.PATH)
    us_old = old[old["region"] == "US"].reset_index(drop=True)
    us_new = new[new["region"] == "US"].reset_index(drop=True)
    assert us_new.equals(us_old)
    info = R.snapshot_info()
    assert info["regions"]["CN"][:10] == today() and info["regions"]["US"][:10] == OLD_DATE
    assert info["snapshot_date"] == OLD_DATE  # the oldest region
    assert R.snapshot_age_days(region="CN") < 0.01 and R.snapshot_age_days(region="US") > 1


def test_dry_run_leaves_live_file(fake, tmp_path):
    before, mtime = R.PATH.read_bytes(), R.PATH.stat().st_mtime
    out = tmp_path / "dry" / "p.parquet"
    res = R.refresh_prices(out=out)
    assert res["status"] == "ok" and "backup" not in res
    assert R.PATH.read_bytes() == before and R.PATH.stat().st_mtime == mtime
    assert len(pd.read_parquet(out)) == 8
    assert (pq.read_schema(out).metadata or {}).get(R.META_KEY)
    assert not list(tmp_path.glob("*.tmp")) and not list((tmp_path / "dry").glob("*.tmp"))


def test_source_failure_writes_nothing(fake):
    fake.fail = R.FetchError("Steam GetItems CN batch 0: HTTP 500")
    before = R.PATH.read_bytes()
    res = R.refresh_prices()
    assert res["status"] == "error" and "HTTP 500" in res["error"]
    assert R.PATH.read_bytes() == before


def test_refresh_if_stale(fake):
    kb = SimpleNamespace(prices=None, price_d=None)
    prices = SimpleNamespace(snapshot_date=OLD_DATE)
    st = R.refresh_if_stale(max_age_days=1, kb=kb, prices=prices)
    assert st["status"] == "ok" and st["applied"]
    assert kb.price_d["CN"][10]["final"] == 10.0 and prices.snapshot_date == today()
    assert R.LAST["status"] == "ok"
    n = len(fake.calls)
    st = R.refresh_if_stale(max_age_days=1)
    assert st["status"] == "fresh" and len(fake.calls) == n  # nothing fetched


def test_refresh_if_stale_never_raises(fake, monkeypatch):
    fake.fail = RuntimeError("boom key=secret123")
    st = R.refresh_if_stale(max_age_days=0)
    assert st["status"] == "error" and "secret123" not in st["error"]
    monkeypatch.setattr(R, "core_games", lambda: (_ for _ in ()).throw(OSError("disk")))
    assert R.refresh_if_stale(max_age_days=0)["status"] == "error"


def test_rebuilt_file_is_dated_by_its_raw_pulls(fake, tmp_path):
    # build_processed.py rewrites prices.parquet from old pulls: the file is new, the prices are not
    f = tmp_path / "raw" / "itad" / "low_CN.json"
    f.parent.mkdir(parents=True)
    f.write_text("{}", encoding="utf-8")
    ts = datetime.fromisoformat("2026-10-10T00:20:00").timestamp()
    os.utime(f, (ts, ts))
    info = R.snapshot_info()
    assert info["source"] == "raw_inputs" and info["snapshot_date"] == "2026-10-10"
    res = R.refresh_prices()
    assert res["backup"].endswith("prices_backup_2026-10-10.parquet")
    assert R.snapshot_info()["source"] == "metadata"


def test_missing_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "PATH", tmp_path / "none.parquet")
    assert R.snapshot_info() is None and R.snapshot_age_days() is None


def test_scrub_hides_keys():
    assert "abc123" not in R._scrub("ITAD https://x/y?country=CN&key=abc123&shops=61")
