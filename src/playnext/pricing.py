"""Live prices for the shortlist (design 4.6 'price freshness'): Steam GetItems + ITAD storelow, per region,
one batch request each, 3 s timeout, 10 minute cache. Falls back to the daily snapshot and says so.
"""
import json
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pandas as pd

from . import config as C
from .kb import KB

TIMEOUT, TTL = 3.0, 600
UA = "BacklogBreaker/0.1 (NUS-ISS student project)"


def load_env():
    env = {}
    f = C.ROOT / ".env"
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def _http(url, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, "Content-Type": "application/json"},
                                 method="POST" if body is not None else "GET")
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode())


class Prices:
    """price(appid, region) -> dict(final, original, discount_pct, is_free, low, low_time, source, as_of)."""

    def __init__(self, kb: KB, live=True):
        self.kb, self.live = kb, live
        self.cache, self.lock = {}, threading.Lock()
        self.env = load_env() if live else {}
        f = C.ROOT / "data" / "raw" / "itad" / "id_map.json"
        self.itad = json.loads(f.read_text(encoding="utf-8")) if (live and f.exists()) else {}
        # the date the prices were fetched (parquet metadata written by refresh.py), not the file's mtime: a
        # rebuild or copy changes the mtime but not the prices
        from .refresh import snapshot_info
        info = snapshot_info()
        snap = C.PROC / "prices.parquet"
        self.snapshot_date = (info or {}).get("snapshot_date") or \
            datetime.fromtimestamp(snap.stat().st_mtime).strftime("%Y-%m-%d")

    def snapshot(self, appid, region):
        p = self.kb.price(appid, region)
        if p is None:
            return None
        free = bool(p["is_free"])
        return {"final": None if pd.isna(p["final"]) else float(p["final"]),
                "original": None if pd.isna(p["original"]) else float(p["original"]),
                "discount_pct": int(p["discount_pct"] or 0), "is_free": free,
                "low": None if free or pd.isna(p["steam_low"]) else float(p["steam_low"]),
                "low_time": None if pd.isna(p["steam_low_time"]) else str(p["steam_low_time"])[:10],
                "currency": p["currency"], "source": "snapshot", "as_of": self.snapshot_date}

    def _steam(self, appids, region):
        inp = {"ids": [{"appid": int(a)} for a in appids],
               "context": {"language": "english", "country_code": region, "steam_realm": 1},
               "data_request": {"include_all_purchase_options": True}}
        url = "https://api.steampowered.com/IStoreBrowseService/GetItems/v1/?input_json=" + urllib.parse.quote(json.dumps(inp))
        out = {}
        for it in _http(url)["response"].get("store_items", []):
            bp = it.get("best_purchase_option") or {}
            if it.get("appid") and "final_price_in_cents" in bp:
                out[it["appid"]] = {"final": int(bp["final_price_in_cents"]) / 100,
                                    "original": int(bp.get("original_price_in_cents") or bp["final_price_in_cents"]) / 100,
                                    "discount_pct": int(bp.get("discount_pct") or 0)}
        return out

    def _itad(self, appids, region):
        key = self.env.get("ITAD_API_KEY")
        gid = {str(a): self.itad.get(str(a)) for a in appids}
        gids = sorted({g for g in gid.values() if g})
        if not key or not gids:
            return {}
        url = "https://api.isthereanydeal.com/games/storelow/v2?" + urllib.parse.urlencode(
            {"country": region, "shops": 61, "key": key})
        rows = _http(url, gids)
        low = {}
        for r in rows:
            steam = [l for l in r.get("lows", []) if l["shop"]["id"] == 61]
            if steam:
                low[r["id"]] = (steam[0]["price"]["amount"], steam[0]["timestamp"][:10])
        return {int(a): low[g] for a, g in gid.items() if g in low}

    def fetch(self, appids, region):
        """Refresh the cache for these games in one region; never raises."""
        now = time.time()
        todo = [a for a in appids if (a, region) not in self.cache or now - self.cache[(a, region)][0] > TTL]
        if not self.live or not todo:
            return
        with ThreadPoolExecutor(2) as ex:
            fs, fi = ex.submit(self._steam, todo, region), ex.submit(self._itad, todo, region)
            try:
                steam = fs.result()
            except Exception:
                steam = None
            try:
                itad = fi.result()
            except Exception:
                itad = {}
        if steam is None:
            return
        stamp = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
        with self.lock:
            for a in todo:
                snap = self.snapshot(a, region) or {"is_free": bool(self.kb.is_free.get(a)), "currency": None}
                rec = dict(snap)
                if a in steam:
                    rec.update(steam[a])
                elif not rec["is_free"]:
                    rec.update(final=None, original=None, discount_pct=0)
                if a in itad and not rec["is_free"]:
                    rec["low"], rec["low_time"] = itad[a]
                rec["source"], rec["as_of"] = "live", stamp
                self.cache[(a, region)] = (now, rec)

    def get(self, appid, region):
        hit = self.cache.get((appid, region))
        if hit and time.time() - hit[0] <= TTL:
            return hit[1]
        return self.snapshot(appid, region)


def price_pref(p):
    """<= record low x 1.05 -> 1, >= 2x -> 0, linear in between; None without a comparable low (design 5.5)."""
    if p is None or p.get("is_free") or p.get("final") is None or not p.get("low"):
        return None
    r = p["final"] / p["low"]
    return float(min(1.0, max(0.0, (2 - r) / (2 - C.NEAR_LOW))))
