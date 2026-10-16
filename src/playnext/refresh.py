"""Daily price snapshot (design 4.6 "价格时效" step 1): current Steam price and ITAD Steam-store record low for every
core game, per region, written to data/processed/prices.parquet with the columns scripts/build_processed.py writes.

Requests: Steam IStoreBrowseService/GetItems, 100 games each (~74 per region); ITAD lookup/id/shop/61, 200 AppIDs each
(~37, once for all regions); ITAD storelow, 200 ITAD ids each (~37 per region). ITAD calls are 1 s apart; HTTP 429
waits for Retry-After (60 s without one). Requests go out directly, no proxy.

The new file replaces the old one only if check() passes: one row per core game for every refreshed region, the share
of games with a price and with a record low at most MARGIN below the old snapshot, and prices in the region's currency.
Regions not refreshed keep their old rows. The replaced file is kept as prices_backup_<its snapshot date>.parquet
(newest KEEP_BACKUPS). The snapshot time is stored in the parquet schema metadata (key "playnext", per region); a file
without it falls back to its modification time.
"""
import json
import math
import os
import re
import shutil
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from . import config as C

PATH = C.PROC / "prices.parquet"
GAMES = C.PROC / "games.parquet"
RAW = C.ROOT / "data" / "raw"
ITAD_MAP = RAW / "itad" / "id_map.json"  # cached map from scripts/fetch_itad.py (read only)
# what scripts/build_processed.py builds prices.parquet from: a file without our metadata is that build, and its prices
# are as old as these pulls, however recent the file's mtime
RAW_PRICE_INPUTS = (("steam_items", "cn_en_*.json"), ("steam_items", "us_[0-9]*.json"), ("itad", "low_*.json"))
COLUMNS = ["appid", "region", "final", "original", "discount_pct", "is_free", "currency", "steam_low", "steam_low_time"]
DTYPES = {"appid": "int64", "final": "float64", "original": "float64", "discount_pct": "int64", "is_free": "bool",
          "steam_low": "float64"}
CURRENCY = {"CN": "CNY", "US": "USD"}
SYMBOL = {"CNY": "¥", "USD": "$"}
META_KEY = b"playnext"
MARGIN = 0.02            # allowed drop in the share of games with a price / a record low vs the old snapshot
CURRENCY_TOLERANCE = 0.01
NEW_REGION_FLOOR = 0.5   # a region without an old snapshot needs at least this share of priced games
KEEP_BACKUPS = 7
STEAM_BATCH, ITAD_BATCH = 100, 200
TIMEOUT, TRIES = 30, 6
UA = "BacklogBreaker/0.1 (NUS-ISS student project)"
STEAM_ITEMS = "https://api.steampowered.com/IStoreBrowseService/GetItems/v1/?input_json="
ITAD = "https://api.isthereanydeal.com"

_sleep = time.sleep
_lock = threading.Lock()
_bg = {"thread": None}
LAST: dict = {}          # status of the last refresh_if_stale call, for a health endpoint


class FetchError(RuntimeError):
    """A data source failed after retries. Messages never contain URLs (ITAD keys travel in the query string)."""


# ---------- HTTP ----------

def _env(name):
    if os.environ.get(name):
        return os.environ[name]
    f = C.ROOT / ".env"
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                if k.strip() == name:
                    return v.strip().strip('"').strip("'")
    return None


def _scrub(msg):
    msg = re.sub(r"(?i)(key=)[^&\s'\"]+", r"\1***", str(msg))
    for name in ("ITAD_API_KEY", "STEAM_API_KEY"):
        v = _env(name)
        if v:
            msg = msg.replace(v, "***")
    return msg


def _retry_after(value):
    try:
        return max(1.0, float(value))
    except (TypeError, ValueError):
        return None


_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # direct, ignoring system / env proxies


def _request(url, body=None, what="request"):
    data = None if body is None else json.dumps(body).encode()
    status = None
    for attempt in range(TRIES):
        req = urllib.request.Request(url, data=data, method="GET" if body is None else "POST",
                                     headers={"User-Agent": UA, "Content-Type": "application/json"})
        try:
            with _opener.open(req, timeout=TIMEOUT) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            status = f"HTTP {e.code}"
            if e.code == 429:
                wait = _retry_after(e.headers.get("Retry-After")) or 60.0
            elif 400 <= e.code < 500 and e.code != 408:
                raise FetchError(f"{what}: {status}") from None
            else:
                wait = 5.0 * (attempt + 1)
        except (urllib.error.URLError, OSError, ValueError) as e:  # network errors, timeouts, bad JSON
            status = type(e).__name__
            wait = 5.0 * (attempt + 1)
        _sleep(wait)
    raise FetchError(f"{what}: gave up after {TRIES} tries ({status})")


# ---------- fetchers (module level so tests can replace them) ----------

def fetch_steam(appids, region):
    """{appid: GetItems store item} for one region, same request shape as scripts/fetch_steam_items.py ('us' pass)."""
    out = {}
    for b, i in enumerate(range(0, len(appids), STEAM_BATCH)):
        inp = {"ids": [{"appid": int(a)} for a in appids[i:i + STEAM_BATCH]],
               "context": {"language": "english", "country_code": region, "steam_realm": 1},
               "data_request": {"include_all_purchase_options": True}}
        d = _request(STEAM_ITEMS + urllib.parse.quote(json.dumps(inp)), what=f"Steam GetItems {region} batch {b}")
        for it in d.get("response", {}).get("store_items", []):
            if it.get("appid"):
                out[int(it["appid"])] = it
        _sleep(0.5)
    return out


def lookup_itad(appids, key):
    """{appid: ITAD game id} via lookup/id/shop/61 (Steam)."""
    out = {}
    url = f"{ITAD}/lookup/id/shop/61/v1?" + urllib.parse.urlencode({"key": key})
    for b, i in enumerate(range(0, len(appids), ITAD_BATCH)):
        res = _request(url, [f"app/{a}" for a in appids[i:i + ITAD_BATCH]], what=f"ITAD lookup batch {b}")
        out.update({int(k.split("/")[1]): v for k, v in res.items() if v})
        _sleep(1)
    return out


def fetch_itad_lows(gids, region, key):
    """{ITAD id: (amount, currency, timestamp)} of the Steam-store low in one region (storelow, shops = 61)."""
    out = {}
    url = f"{ITAD}/games/storelow/v2?" + urllib.parse.urlencode({"country": region, "shops": 61, "key": key})
    for b, i in enumerate(range(0, len(gids), ITAD_BATCH)):
        for r in _request(url, gids[i:i + ITAD_BATCH], what=f"ITAD storelow {region} batch {b}"):
            steam = [l for l in r.get("lows", []) if l["shop"]["id"] == 61]
            if steam:
                out[r["id"]] = (steam[0]["price"]["amount"], steam[0]["price"].get("currency"), steam[0]["timestamp"])
        _sleep(1)
    return out


def core_games():
    """Core games in games.parquet order: appid, name, is_free (fallback where the store returns no item)."""
    return pd.read_parquet(GAMES, columns=["appid", "name", "is_free"])


def cached_itad_map():
    try:
        return {int(k): v for k, v in json.loads(ITAD_MAP.read_text(encoding="utf-8")).items() if v}
    except Exception:
        return {}


# ---------- snapshot date ----------

def _now():
    return datetime.now().astimezone()


def _raw_inputs_mtime():
    ts = [f.stat().st_mtime for d, pat in RAW_PRICE_INPUTS for f in (RAW / d).glob(pat)]
    return max(ts) if ts else None


def snapshot_info(path=None):
    """{"fetched_at", "snapshot_date", "regions": {region: fetched_at}, "source"}; None if no file.
    source "metadata": written by refresh_prices (fetched_at / snapshot_date are those of the oldest region);
    "raw_inputs": a build_processed.py file, dated by its raw price pulls; "mtime": the file's modification time."""
    path = Path(path or PATH)
    if not path.exists():
        return None
    try:
        raw = (pq.read_schema(path).metadata or {}).get(META_KEY)
        if raw:
            info = json.loads(raw)
            info["source"] = "metadata"
            return info
    except Exception:
        pass
    m, raw = path.stat().st_mtime, _raw_inputs_mtime()
    src = "raw_inputs" if raw is not None and raw < m else "mtime"
    t = datetime.fromtimestamp(raw if src == "raw_inputs" else m).astimezone()
    return {"fetched_at": t.isoformat(timespec="seconds"), "snapshot_date": t.strftime("%Y-%m-%d"), "regions": {},
            "source": src}


def snapshot_age_days(path=None, region=None):
    """Days since the snapshot (of `region`, else of its oldest region) was fetched; None without a readable file or
    when `region` was never fetched into a file that records regions."""
    try:
        info = snapshot_info(path)
        if info is None:
            return None
        ts = info["fetched_at"]
        if region is not None and info.get("regions"):
            ts = info["regions"].get(region)
            if ts is None:
                return None
        return (_now() - datetime.fromisoformat(ts)).total_seconds() / 86400
    except Exception:
        return None


# ---------- build / check / compare ----------

def _cents(x):
    return None if x in (None, "") else int(x) / 100


def build_region(region, games, items, lows_by_app, currency):
    """Rows for one region, the way scripts/build_processed.py builds them (original is null when not discounted)."""
    rows, wrong_symbol = [], 0
    sym = SYMBOL.get(currency)
    for a, free0 in zip(games["appid"].tolist(), games["is_free"].tolist()):
        it = items.get(int(a)) or {}
        listed = it.get("success") == 1 and not it.get("unvailable_for_country_restriction")
        bp = it.get("best_purchase_option") or {}
        final = _cents(bp.get("final_price_in_cents"))
        if final is not None and sym and sym not in str(bp.get("formatted_final_price", sym)):
            wrong_symbol += 1
        low = lows_by_app.get(int(a)) or (None, None, None)
        rows.append({"appid": int(a), "region": region, "final": final,
                     "original": _cents(bp.get("original_price_in_cents")),
                     "discount_pct": int(bp.get("discount_pct") or 0),
                     "is_free": bool(it.get("is_free")) if listed else bool(free0),
                     "currency": currency, "steam_low": low[0], "steam_low_time": low[2]})
    return rows, wrong_symbol


def _region_currency(region, lows):
    if region in CURRENCY:
        return CURRENCY[region]
    cur = pd.Series([c for _, c, _ in lows.values() if c])
    return cur.mode().iloc[0] if len(cur) else None


def assemble(rows, games, old, regions):
    """New rows for `regions` + old rows of the other regions, core games only, games.parquet order."""
    new = pd.DataFrame(rows, columns=COLUMNS)
    if old is not None:
        keep = old[~old["region"].isin(regions) & old["appid"].isin(games["appid"])]
        new = pd.concat([new, keep[COLUMNS]], ignore_index=True)
    order = (list(old["region"].drop_duplicates()) if old is not None else []) + [r for r in regions]
    rank = {r: i for i, r in enumerate(dict.fromkeys(order))}
    pos = {int(a): i for i, a in enumerate(games["appid"])}
    new = new.assign(_p=new["appid"].map(pos), _r=new["region"].map(rank)).sort_values(["_p", "_r"], kind="stable")
    new = new.drop(columns=["_p", "_r"]).reset_index(drop=True)
    for c, t in DTYPES.items():
        new[c] = new[c].astype(t)
    if old is not None:  # same dtypes as the file being replaced
        new = new.astype({c: old[c].dtype for c in COLUMNS if c in old})
    return new


def _shares(d):
    n = max(len(d), 1)
    return {"rows": len(d), "games": int(d["appid"].nunique()), "priced": round(float(d["final"].notna().sum()) / n, 4),
            "free": int(d["is_free"].sum()), "low": round(float(d["steam_low"].notna().sum()) / n, 4),
            "discounted": int((d["discount_pct"] > 0).sum())}


def check(new, old, regions, n_games, stats, margin=MARGIN):
    """(ok, problems, report). report[region] has the new and old shares."""
    problems, report = [], {}
    for r in regions:
        d = new[new["region"] == r]
        rep = {"new": _shares(d), **stats.get(r, {})}
        if len(d) != n_games or d["appid"].duplicated().any():
            problems.append(f"{r}: {len(d)} rows for {n_games} core games")
        o = old[old["region"] == r] if old is not None else None
        if o is not None and len(o):
            rep["old"] = _shares(o)
            for k, label in (("priced", "games with a price"), ("low", "games with a record low")):
                if rep["new"][k] < rep["old"][k] - margin:
                    problems.append(f"{r}: share of {label} fell from {rep['old'][k]:.1%} to {rep['new'][k]:.1%}")
        elif rep["new"]["priced"] < NEW_REGION_FLOOR:
            problems.append(f"{r}: only {rep['new']['priced']:.1%} of games have a price")
        priced = int(d["final"].notna().sum())
        if priced and stats.get(r, {}).get("wrong_symbol", 0) / priced > CURRENCY_TOLERANCE:
            problems.append(f"{r}: {stats[r]['wrong_symbol']} of {priced} Steam prices are not in {stats[r]['currency']}")
        nl = stats.get(r, {}).get("low_currencies", {})
        other = sum(v for k, v in nl.items() if k != stats.get(r, {}).get("currency"))
        if sum(nl.values()) and other / sum(nl.values()) > CURRENCY_TOLERANCE:
            problems.append(f"{r}: ITAD lows came back in {nl}")
        report[r] = rep
    return not problems, problems, report


def compare(new, old, region, names, examples=5):
    """How the region's prices changed against the old snapshot."""
    if old is None or not (old["region"] == region).any():
        return None
    o = old[old["region"] == region].set_index("appid")
    n = new[new["region"] == region].set_index("appid")
    j = n.join(o, lsuffix="", rsuffix="_old", how="inner")
    both = j["final"].notna() & j["final_old"].notna()
    changed = both & ((j["final"] - j["final_old"]).abs() > 0.005)
    lows = j["steam_low"].notna() & j["steam_low_old"].notna()
    ch = j[changed].assign(rel=lambda x: (x["final"] - x["final_old"]) / x["final_old"])
    ch = ch.reindex(ch["rel"].abs().sort_values(ascending=False).index)
    return {"games": len(j), "both_priced": int(both.sum()), "price_changed": int(changed.sum()),
            "cheaper": int((changed & (j["final"] < j["final_old"])).sum()),
            "dearer": int((changed & (j["final"] > j["final_old"])).sum()),
            "price_appeared": int((j["final"].notna() & j["final_old"].isna()).sum()),
            "price_gone": int((j["final"].isna() & j["final_old"].notna()).sum()),
            "discount_changed": int((j["discount_pct"] != j["discount_pct_old"]).sum()),
            "discounted_now": int((j["discount_pct"] > 0).sum()), "discounted_before": int((j["discount_pct_old"] > 0).sum()),
            "new_record_low": int((lows & (j["steam_low"] < j["steam_low_old"] - 0.005)).sum()),
            "low_appeared": int((j["steam_low"].notna() & j["steam_low_old"].isna()).sum()),
            "low_gone": int((j["steam_low"].isna() & j["steam_low_old"].notna()).sum()),
            "examples": [{"appid": int(a), "name": names.get(a), "old": float(r["final_old"]), "new": float(r["final"]),
                          "discount_old": int(r["discount_pct_old"]), "discount_new": int(r["discount_pct"])}
                         for a, r in ch.head(examples).iterrows()]}


# ---------- write ----------

def _write(df, target, info):
    table = pa.Table.from_pandas(df, preserve_index=False)
    table = table.replace_schema_metadata({**(table.schema.metadata or {}), META_KEY: json.dumps(info).encode()})
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=target.name + ".", suffix=".tmp", dir=target.parent)
    os.close(fd)
    try:
        pq.write_table(table, tmp)
        for attempt in range(5):  # Windows refuses the replace while a reader holds the file open
            try:
                os.replace(tmp, target)
                break
            except PermissionError:
                if attempt == 4:
                    raise
                _sleep(0.5)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def _backup(old_info):
    dst = PATH.with_name(f"prices_backup_{old_info['snapshot_date']}.parquet")
    shutil.copy2(PATH, dst)
    for f in sorted(PATH.parent.glob("prices_backup_*.parquet"))[:-KEEP_BACKUPS]:
        f.unlink()
    return dst


def read_snapshot(path=None):
    path = Path(path or PATH)
    return pd.read_parquet(path) if path.exists() else None


# ---------- entry points ----------

def refresh_prices(regions=("CN", "US"), out=None, margin=MARGIN) -> dict:
    """Fetch, check and write the snapshot. out=None replaces data/processed/prices.parquet (with a backup); any other
    path receives the new snapshot instead (dry run), the live file is left alone. Nothing is written when the check
    fails ("rejected") or a source fails ("error")."""
    t0 = time.time()
    regions = list(dict.fromkeys(r.upper() for r in regions))
    target = PATH if out is None else Path(out)
    live = Path(target).resolve() == PATH.resolve()
    old, old_info = read_snapshot(), snapshot_info()
    res = {"status": None, "regions": regions, "target": str(target), "old_snapshot": old_info, "problems": []}
    try:
        games = core_games()
        appids = [int(a) for a in games["appid"]]
        key = _env("ITAD_API_KEY")
        if not key:
            raise FetchError("ITAD_API_KEY missing in .env")
        id_map = cached_itad_map()
        try:
            id_map.update(lookup_itad(appids, key))
        except FetchError as e:
            res["problems"].append(f"ITAD lookup failed, used the cached id map: {e}")
        gids = sorted({id_map[a] for a in appids if a in id_map})
        rows, stats, fetched = [], {}, {}
        for r in regions:
            fetched[r] = _now().isoformat(timespec="seconds")
            items = fetch_steam(appids, r)
            lows = fetch_itad_lows(gids, r, key)
            currency = _region_currency(r, lows)
            lows_by_app = {a: lows[id_map[a]] for a in appids if id_map.get(a) in lows}
            rr, wrong = build_region(r, games, items, lows_by_app, currency)
            rows += rr
            stats[r] = {"currency": currency, "steam_items": len(items), "wrong_symbol": wrong,
                        "cn_store_blocked": sum(1 for it in items.values() if it.get("unvailable_for_country_restriction")),
                        "low_currencies": {str(k): int(v) for k, v in pd.Series(
                            [c for _, c, _ in lows_by_app.values()], dtype=object).value_counts().items()}}
    except FetchError as e:
        res.update(status="error", error=_scrub(e), seconds=round(time.time() - t0, 1))
        return res
    new = assemble(rows, games, old, regions)
    ok, problems, report = check(new, old, regions, len(games), stats, margin)
    names = dict(zip(games["appid"].astype(int), games["name"]))
    present = set(new["region"])
    region_times = {}
    if old_info:  # regions kept from the old file keep their old fetch time
        region_times = {r: old_info["fetched_at"] for r in present}
        region_times.update(old_info.get("regions") or {})
    region_times.update(fetched)
    region_times = {r: t for r, t in region_times.items() if r in present}
    oldest = min(region_times.values(), key=datetime.fromisoformat)
    info = {"fetched_at": oldest, "snapshot_date": oldest[:10], "regions": region_times}
    res.update(check=report, problems=res["problems"] + problems, new_snapshot=info,
               comparison={r: compare(new, old, r, names) for r in regions},
               requests={"steam_getitems_per_region": math.ceil(len(appids) / STEAM_BATCH),
                         "itad_lookup": math.ceil(len(appids) / ITAD_BATCH),
                         "itad_storelow_per_region": math.ceil(len(gids) / ITAD_BATCH)})
    if not ok:
        res.update(status="rejected", seconds=round(time.time() - t0, 1))
        return res
    if live and old_info is not None:
        res["backup"] = str(_backup(old_info))
    _write(new, target, info)
    res.update(status="ok", rows=len(new), seconds=round(time.time() - t0, 1))
    return res


def apply_snapshot(kb, prices=None, path=None):
    """Load the snapshot into a running KB (the two tables KB.__init__ builds from prices.parquet) and set
    Prices.snapshot_date, so a server picks up a refresh without a restart."""
    pr = pd.read_parquet(path or PATH)
    tables = {r: d.set_index("appid") for r, d in pr.groupby("region")}
    price_d = {r: d.to_dict("index") for r, d in tables.items()}
    kb.prices, kb.price_d = tables, price_d  # plain attribute swaps: readers see the old or the new table
    info = snapshot_info(path)
    if prices is not None and info:
        prices.snapshot_date = info["snapshot_date"]


def refresh_if_stale(max_age_days=1, regions=("CN", "US"), kb=None, prices=None) -> dict:
    """Refresh the regions whose snapshot is at least max_age_days old; with kb (and prices) also load the result
    into them. Never raises; returns a status dict (status: fresh | busy | ok | rejected | error)."""
    try:
        ages = {r: snapshot_age_days(region=r) for r in regions}
        stale = [r for r, a in ages.items() if a is None or a >= max_age_days]
        if not stale:
            out = {"status": "fresh", "age_days": {r: round(a, 2) for r, a in ages.items()}}
        elif not _lock.acquire(blocking=False):
            out = {"status": "busy"}
        else:
            try:
                res = refresh_prices(stale)
            finally:
                _lock.release()
            out = {k: res.get(k) for k in ("status", "regions", "problems", "error", "backup", "new_snapshot",
                                           "old_snapshot", "seconds") if res.get(k) is not None}
            out["check"] = {r: v.get("new") for r, v in (res.get("check") or {}).items()}
            if res["status"] == "ok" and kb is not None:
                apply_snapshot(kb, prices)
                out["applied"] = True
    except Exception as e:  # noqa: BLE001 - a background job must not die
        out = {"status": "error", "error": _scrub(f"{type(e).__name__}: {e}")}
    out["checked_at"] = _now().isoformat(timespec="seconds")
    LAST.clear()
    LAST.update(out)
    return out


def start_background(kb=None, prices=None, every_hours=1.0, max_age_days=1, regions=("CN", "US")):
    """Daemon thread calling refresh_if_stale every `every_hours`; starts once per process, returns the thread."""
    t = _bg["thread"]
    if t is not None and t.is_alive():
        return t

    def loop():
        while True:
            refresh_if_stale(max_age_days, regions, kb, prices)
            time.sleep(every_hours * 3600)

    t = threading.Thread(target=loop, name="price-refresh", daemon=True)
    t.start()
    _bg["thread"] = t
    return t
