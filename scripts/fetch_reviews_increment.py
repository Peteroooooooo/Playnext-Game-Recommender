"""Incremental Steam review crawl through a rotating proxy entry (Data_Sources.md source 6).

Fills two gaps of the Kaggle steam-reviews-100m data: reviews written after each game's scrape date there,
and the full history of core games missing from it.

Transport: one local SOCKS5 entry that switches to the next upstream node on every new connection (the user's
mihomo pool, round-robin over ~2,800 nodes; default socks5h://127.0.0.1:17892, override with PLAYNEXT_PROXY).
Every request opens a fresh connection, so consecutive requests leave from different nodes and no single
exit IP gets near Steam's ~200 requests / 5 min limit. Concurrency is the only throttle. A failed request
(timeout, dead node, HTTP 429, non-JSON reply) is simply retried; the retry lands on another node.
Free nodes are run by unknown third parties: they only carry Steam's public review API over HTTPS with
certificate checks, never anything personal.

Reviewer Steam IDs are hashed in memory with the project salt (same scheme as the co-like builds); only the
hash is written. Review text is not kept.

  plan                 one summary request per core game -> data/raw/steam_reviews_increment/plan.json
  test [SECONDS] [N]   fetch real pages for SECONDS (default 120) with N parallel requests (default 96);
                       prints in-window rate, latency, error mix and the projected time for what is left
  run [N]              fetch every task not done yet with N parallel requests (resumable)
  check                compare fetched counts with the plan per game (quick look; repair is the real check)
  repair               verify counts by majority vote, refetch short games in ever smaller time bins
                       (Steam's paging stops early in long windows; run this after every run)
Output: data/raw/steam_reviews_increment/reviews/<appid>_<start>_<end>.parquet
Usage: uv run python scripts/fetch_reviews_increment.py plan|test|run|check|repair [SECONDS] [N]
"""
import hashlib
import json
import math
import os
import random
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
import pyarrow.dataset as ds
import pyarrow.parquet as pq
import requests

from check_keys import ROOT

OUT = ROOT / "data" / "raw" / "steam_reviews_increment"
REV = OUT / "reviews"
PLAN = OUT / "plan.json"
PROGRESS = OUT / "progress.json"
VERIFIED = OUT / "verified_counts.json"
KAGGLE = ROOT / "data" / "raw" / "kaggle_reviews100m" / "extracted"
SALT = bytes.fromhex((ROOT / ".cache" / "review_salt").read_text(encoding="utf-8").strip())
PROXY = os.environ.get("PLAYNEXT_PROXY", "socks5h://127.0.0.1:17892")
PAGE, SLICE_PAGES, TRIES, TIMEOUT, DEADLINE = 100, 100, 12, (10, 25), 45
API = "https://store.steampowered.com/appreviews/{}"
FIRST_REVIEW = 1291161600  # 2010-12-01, lower bound when slicing full histories (kept so slice names stay stable)
EARLIEST = 1283299200  # 2010-09-01, before the oldest review timestamps (2010-10); lower bound for repair bins
NOW = int(time.time())


def uhash(steamid):
    return int.from_bytes(hashlib.blake2b(int(steamid).to_bytes(8, "little"), key=SALT, digest_size=8).digest(),
                          "little", signed=True)


class Transport:
    """Thread-safe request helper with counters. A new requests call = a new connection = the next node."""

    def __init__(self):
        self.lock = threading.Lock()
        self.stats = Counter()
        self.latency = []
        self.done_at = []

    def count(self, key, n=1):
        with self.lock:
            self.stats[key] += n

    @staticmethod
    def _fetch(appid, params):
        """One HTTP request with a hard deadline. requests' read timeout restarts with every byte, so a node that
        trickles data can hold a call forever (a whole run stalled on that on 2026-10-13). The call runs in a daemon
        thread; if it is not back in DEADLINE seconds it is abandoned and counted as a timeout."""
        box = {}

        def call():
            try:
                box["r"] = requests.get(API.format(appid), params=params, timeout=TIMEOUT,
                                        proxies={"https": PROXY, "http": PROXY}, headers={"User-Agent": "Mozilla/5.0"})
            except Exception as e:  # handed back to the caller's except clauses
                box["e"] = e

        th = threading.Thread(target=call, daemon=True)
        th.start()
        th.join(DEADLINE)
        if th.is_alive():
            raise requests.exceptions.Timeout("deadline")
        if "e" in box:
            raise box["e"]
        return box["r"]

    def get(self, appid, params):
        for attempt in range(TRIES):
            t = time.time()
            try:
                r = self._fetch(appid, params)
                if r.status_code != 200:
                    self.count(f"http{r.status_code}")
                    time.sleep(0.5)
                    continue
                d = r.json()
                if d.get("success") != 1:
                    self.count("not_success")
                    continue
            except requests.exceptions.Timeout:
                self.count("timeout")
                continue
            except (requests.exceptions.RequestException, ValueError):
                self.count("neterr")  # dead node, reset connection, or a non-JSON page from a broken node
                continue
            with self.lock:
                self.stats["ok"] += 1
                self.latency.append(time.time() - t)
                self.done_at.append(time.time())
            return d
        self.count("gave_up")
        raise RuntimeError("gave up")


def base_params(start, end, cursor="*", n=PAGE, purchase="all"):
    p = {"json": 1, "filter": "recent", "language": "all", "review_type": "all", "purchase_type": purchase,
         "num_per_page": n, "cursor": cursor}
    if start or end:
        p.update(start_date=start, end_date=end, date_range_type="include")
    return p


def slices(appid, start, end, n, now=NOW, slice_pages=SLICE_PAGES):
    """Split one window into time slices of about slice_pages pages so many requests can share a big game.
    `now` must be the plan's creation time, so slice names stay the same from run to run."""
    pages = math.ceil(n / PAGE)
    if pages <= slice_pages:
        return [{"appid": appid, "start": start, "end": end, "reviews": n}]
    lo, hi = (start, end) if start else (FIRST_REVIEW, now)
    k = math.ceil(pages / slice_pages)
    edges = [lo + (hi - lo) * i // k for i in range(k + 1)]
    return [{"appid": appid, "start": edges[i], "end": edges[i + 1] - 1 if i < k - 1 else hi, "reviews": n // k}
            for i in range(k)]


def plan(workers=96):
    games = pd.read_parquet(ROOT / "data" / "processed" / "games.parquet")[["appid", "review_count"]]
    t = ds.dataset(str(KAGGLE), format="parquet").to_table(columns=["appid", "scrape_date"],
                                                            filter=ds.field("appid").isin(games["appid"].tolist()))
    sd = t.to_pandas()
    sd["scrape_date"] = pd.to_datetime(sd["scrape_date"], errors="coerce")  # some rows have no scrape date
    scraped = sd.dropna().groupby("appid")["scrape_date"].min()
    jobs = []
    for a in games["appid"]:
        if a in scraped.index:  # one day of overlap; duplicates are removed by recommendation id later
            jobs.append((int(a), int(pd.Timestamp(scraped[a]).tz_localize("UTC").timestamp()) - 86400, NOW))
        else:
            jobs.append((int(a), 0, 0))  # missing from Kaggle: whole history
    tr = Transport()
    t0 = time.time()

    def count(job):
        a, s, e = job
        try:
            d = tr.get(a, base_params(s, e, n=0))
        except RuntimeError:
            return a, s, e, None
        return a, s, e, int((d.get("query_summary") or {}).get("total_reviews") or 0)

    with ThreadPoolExecutor(workers) as pool:
        res = list(pool.map(count, jobs))
    failed = [r for r in res if r[3] is None]
    tasks = [x for a, s, e, n in res if n for x in slices(a, s, e, n)]
    OUT.mkdir(parents=True, exist_ok=True)
    PLAN.write_text(json.dumps({"made": NOW, "game_totals": {str(a): n for a, s, e, n in res if n},
                                "tasks": tasks}), encoding="utf-8")
    print(f"plan: {len(tasks):,} tasks; pages ~{sum(math.ceil(t['reviews'] / PAGE) for t in tasks):,}; "
          f"games without an answer {len(failed)}; {time.time() - t0:.0f}s; {dict(tr.stats)}", flush=True)


COLUMNS = ["rec_id", "user_hash", "appid", "voted_up", "timestamp_created", "timestamp_updated", "playtime_forever",
           "playtime_at_review", "num_games_owned", "num_reviews", "language"]


def task_file(t):
    tag = f"_{t['tag']}" if t.get("tag") else ""
    return (t.get("dir") or REV) / f"{t['appid']}_{t['start']}_{t['end']}{tag}.parquet"


def read_ids(f):
    t = pd.read_parquet(f)
    return t["rec_id"] if "rec_id" in t.columns else pd.Series([], dtype="int64")


def load_tasks():
    """Plan tasks, with old unsliced full-history tasks re-sliced unless they were already fetched whole."""
    out = []
    p = json.loads(PLAN.read_text(encoding="utf-8"))
    for t in p["tasks"]:
        if t["start"] == 0 and math.ceil(t["reviews"] / PAGE) > SLICE_PAGES and not task_file(t).exists():
            out += slices(t["appid"], 0, 0, t["reviews"], now=p["made"])
        else:
            out.append(t)
    return out


def fetch_task(tr, t, stop_at):
    rows, cursor, seen, pages, empty_tries = [], "*", set(), 0, 0
    while True:
        if stop_at and time.time() > stop_at:
            return {"task": t, "rows": len(rows), "pages": pages, "complete": False}
        d = tr.get(t["appid"], base_params(t["start"], t["end"], cursor, purchase=t.get("purchase", "all")))
        pages += 1
        revs = d.get("reviews") or []
        for r in revs:
            a = r["author"]
            rows.append({"rec_id": int(r["recommendationid"]), "user_hash": uhash(a["steamid"]), "appid": t["appid"],
                         "voted_up": bool(r["voted_up"]), "timestamp_created": int(r["timestamp_created"]),
                         "timestamp_updated": int(r.get("timestamp_updated") or 0),
                         "playtime_forever": int(a.get("playtime_forever") or 0),
                         "playtime_at_review": int(a.get("playtime_at_review") or 0),
                         "num_games_owned": int(a.get("num_games_owned") or 0),
                         "num_reviews": int(a.get("num_reviews") or 0), "language": r.get("language", "")})
        if not revs and empty_tries < 3:
            empty_tries += 1  # a broken node can answer success=1 with no reviews; ask other nodes before stopping
            continue
        empty_tries = 0
        cursor = d.get("cursor")
        if not revs or not cursor or cursor in seen:
            break
        seen.add(cursor)
    REV.mkdir(parents=True, exist_ok=True)
    tmp = task_file(t).with_suffix(".tmp")
    pd.DataFrame(rows, columns=COLUMNS).to_parquet(tmp, index=False)  # explicit columns: a window may be empty
    tmp.replace(task_file(t))  # write-then-rename, so an interrupted run never leaves a half file
    return {"task": t, "rows": len(rows), "pages": pages, "complete": True}


def crawl(seconds=None, workers=96):
    tasks = load_tasks()
    todo = [t for t in tasks if not task_file(t).exists()]
    if seconds:
        random.seed(int(time.time()))
        todo = random.sample(todo, min(len(todo), workers * 20))  # enough work that nobody runs dry in the window
    else:
        todo.sort(key=lambda t: -t["reviews"])  # big ones first, so the end of the run is not one long task
    tr = Transport()
    t0 = time.time()
    stop_at = t0 + seconds if seconds else None
    print(f"{len(todo):,} tasks, {workers} parallel requests via {PROXY}" + (f", window {seconds}s" if seconds else ""),
          flush=True)
    results, lock = [], threading.Lock()
    left = [len(todo)]

    def one(t):
        try:
            r = fetch_task(tr, t, stop_at)
        except RuntimeError:
            r = {"task": t, "rows": 0, "pages": 0, "complete": False}
        with lock:
            results.append(r)
            left[0] -= 1

    stop_flag = threading.Event()

    def reporter():
        last = 0
        while not stop_flag.wait(60):
            with tr.lock:
                ok, st = tr.stats["ok"], dict(tr.stats)
            done = sum(1 for r in results if r["complete"])
            el = time.time() - t0
            print(f"  {el / 60:5.1f} min: pages {ok:,} ({(ok - last) / 60:.1f}/s last minute), tasks done {done:,}, "
                  f"left {left[0]:,}, errors { {k: v for k, v in st.items() if k != 'ok'} }", flush=True)
            PROGRESS.write_text(json.dumps({"at": int(time.time()), "pages": ok, "tasks_done": done, "left": left[0],
                                            "stats": st}), encoding="utf-8")
            last = ok

    rep = threading.Thread(target=reporter, daemon=True)
    rep.start()
    with ThreadPoolExecutor(workers) as pool:
        list(pool.map(one, todo))
    stop_flag.set()
    el = time.time() - t0
    st = dict(tr.stats)
    done = [r for r in results if r["complete"]]
    lat = sorted(tr.latency)
    tries = sum(st.values())
    print(f"{el:.0f}s total: requests ok {st.get('ok', 0):,} of {tries:,} attempts "
          f"({st.get('ok', 0) / max(1, tries):.0%} first-or-retry success); errors "
          f"{ {k: v for k, v in st.items() if k != 'ok'} }", flush=True)
    print(f"tasks finished {len(done):,}, reviews {sum(r['rows'] for r in results):,}; latency of good requests "
          f"median {lat[len(lat) // 2] if lat else 0:.2f}s, p90 {lat[int(len(lat) * .9)] if lat else 0:.2f}s", flush=True)
    if seconds:
        per_game = Counter(t["appid"] for t in tasks)
        whole = [r for r in done if per_game[r["task"]["appid"]] == 1]  # unsliced tasks carry Steam's exact count
        if whole:
            g, w = sum(r["rows"] for r in whole), sum(r["task"]["reviews"] for r in whole)
            print(f"completeness on {len(whole)} finished whole-game tasks: {g:,} of {w:,} = {g / max(1, w):.1%}",
                  flush=True)
        n = sum(1 for x in tr.done_at if x <= t0 + seconds)
        rate = n / seconds
        rest = sum(math.ceil(t["reviews"] / PAGE) for t in load_tasks() if not task_file(t).exists())
        print(f"in the {seconds}s window: {n:,} pages = {rate:.1f}/s; {rest:,} pages left -> about "
              f"{rest / max(rate, 1e-9) / 3600:.2f} h at this rate", flush=True)


def check():
    """Per game: fetched reviews (deduplicated) vs the planned total. Short games go to recheck.json."""
    p = json.loads(PLAN.read_text(encoding="utf-8"))
    totals = {int(k): v for k, v in p.get("game_totals", {}).items()}
    if not totals:
        for t in p["tasks"]:
            totals[t["appid"]] = totals.get(t["appid"], 0) + t["reviews"]
    by_game = {}
    for f in REV.glob("*.parquet"):  # match by game, not by exact slice name
        by_game.setdefault(int(f.name.split("_")[0]), []).append(f)
    got = {a: pd.concat([read_ids(f) for f in fs]).nunique() for a, fs in by_game.items()}
    short = {a: (got.get(a, 0), n) for a, n in totals.items() if got.get(a, 0) < 0.98 * n}
    (OUT / "recheck.json").write_text(json.dumps({str(a): v for a, v in short.items()}), encoding="utf-8")
    print(f"games planned {len(totals):,}; games with files {len(by_game):,}; games below 98% of Steam's count "
          f"{len(short):,} -> recheck.json; reviews fetched {sum(got.values()):,} of {sum(totals.values()):,} planned")


def steam_count(tr, appid, s, e, purchase="all"):
    """Steam's review count for a window, by majority vote over different nodes. About 1 node in 40 answers
    with a much smaller count (e.g. 377 instead of 59,269), so one answer is not enough."""
    votes = Counter()
    for _ in range(5):
        votes[int((tr.get(appid, base_params(s, e, n=0, purchase=purchase)).get("query_summary") or {}).get("total_reviews") or 0)] += 1
        n, k = votes.most_common(1)[0]
        if k >= 2:
            return n
    return max(votes, key=lambda n: (votes[n], n))


def fetched(cols=("appid", "rec_id", "timestamp_created")):
    parts = [pd.read_parquet(f, columns=list(cols)) for f in REV.glob("*.parquet") if pq.read_schema(f).names]
    return pd.concat(parts, ignore_index=True).drop_duplicates("rec_id")


def windows():
    p = json.loads(PLAN.read_text(encoding="utf-8"))
    win = {}
    for t in p["tasks"]:
        w = win.setdefault(t["appid"], [t["start"], t["end"]])
        w[0], w[1] = min(w[0], t["start"]), max(w[1], t["end"])
    return {a: ((s, e) if s else (EARLIEST, p["made"])) for a, (s, e) in win.items()}


def refine(tr, short, held, tag, folder, workers=96, purchase="all", fetch_from=30 * 86400):
    """Bin-by-bin refetch. short: {appid: [(start, end), ...]} still below Steam's count; held(): the reviews we
    already have (appid, timestamp_created). Each level compares every bin with Steam's count (majority vote),
    refetches the short bins as whole windows, and passes what is still short on to the next, smaller bin size.
    Bins larger than fetch_from are only counted: fetching a whole year (or, for huge games, a month of 300+
    sequential pages) is slow and lossy again."""
    df = held()
    for size in [365 * 86400, 30 * 86400, 7 * 86400, 86400, 3600]:
        bins = [(a, x, min(x + size, e + 1) - 1) for a, spans in short.items() for s, e in spans
                for x in range(s, e + 1, size)]
        with ThreadPoolExecutor(workers) as pool:
            counts = list(pool.map(lambda b: steam_count(tr, *b, purchase=purchase), bins))
        ts = {a: np.sort(g.to_numpy()) for a, g in df[df.appid.isin(short)].groupby("appid")["timestamp_created"]}
        have = lambda a, s, e: int(np.searchsorted(ts.get(a, []), e, "right") - np.searchsorted(ts.get(a, []), s))
        # a short bin with many reviews (a launch week of Cyberpunk 2077 has 1,000+ pages) is split into
        # sub-windows of about 20 pages, so it is fetched in parallel instead of one long sequential walk
        short_bins = [(a, s, e, n) for (a, s, e), n in zip(bins, counts) if have(a, s, e) < n]
        todo = [dict(x, tag=tag, dir=folder, purchase=purchase)
                for a, s, e, n in short_bins for x in slices(a, s, e, n, slice_pages=20)]

        def one(t):
            try:
                fetch_task(tr, t, None)
            except RuntimeError:  # gave up after all retries; the bin stays short and is retried one level down
                pass

        if size <= fetch_from:
            with ThreadPoolExecutor(workers) as pool:
                list(pool.map(one, todo))
        df = held()
        ts = {a: np.sort(g.to_numpy()) for a, g in df[df.appid.isin(short)].groupby("appid")["timestamp_created"]}
        still = [(a, s, e, n) for a, s, e, n in short_bins if have(a, s, e) < n]
        short = {}
        for a, s, e, _ in still:
            short.setdefault(a, []).append((s, e))
        print(f"bins of {size // 3600} h: checked {len(bins):,}, short {len(short_bins):,} "
              f"({len(todo):,} windows {'fetched' if size <= fetch_from else 'not fetched'}), still short {len(still):,} "
              f"(gap {sum(n - have(a, s, e) for a, s, e, n in still):,}); {dict(tr.stats)}", flush=True)
        if not short:
            break


def repair(workers=96):
    """Steam's review paging is lossy over long windows: pages come back short and then empty although
    query_summary says there is more. Smaller windows restart the paging and recover the rest.
    1. Verify every game's count by majority vote (verified_counts.json); the plan's single answers can be wrong.
    2. For games still short, refine() narrows the gap down from years to months, weeks, days and hours.
    Repair files are named <appid>_<start>_<end>_r.parquet; duplicates are removed by rec_id when merging.
    What stays short at the hour level is listed by Steam's count but never served (hidden or removed reviews)."""
    tr = Transport()
    win = windows()
    with ThreadPoolExecutor(workers) as pool:
        totals = dict(zip(win, pool.map(lambda a: steam_count(tr, a, *win[a]), win)))
    VERIFIED.write_text(json.dumps({str(a): n for a, n in totals.items()}), encoding="utf-8")
    df = fetched()
    got = df.groupby("appid").size()
    short = {a: [win[a]] for a, n in totals.items() if got.get(a, 0) < n}
    print(f"verified counts for {len(totals):,} games: Steam {sum(totals.values()):,}, fetched {len(df):,}; "
          f"short games {len(short):,} (gap {sum(totals[a] - got.get(a, 0) for a in short):,})", flush=True)
    refine(tr, short, lambda: fetched(), "r", None, workers)
    df = fetched()
    got = df.groupby("appid").size()
    gap = {a: n - got.get(a, 0) for a, n in totals.items() if got.get(a, 0) < n}
    print(f"after repair: fetched {len(df):,} of Steam's {sum(totals.values()):,} "
          f"({len(df) / sum(totals.values()):.4%}); games short {len(gap):,}, largest gaps "
          f"{sorted(gap.items(), key=lambda x: -x[1])[:8]}", flush=True)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "plan"
    if mode == "repair":
        repair()
    elif mode == "plan":
        plan()
    elif mode == "test":
        crawl(int(sys.argv[2]) if len(sys.argv) > 2 else 120, int(sys.argv[3]) if len(sys.argv) > 3 else 96)
    elif mode == "run":
        crawl(None, int(sys.argv[2]) if len(sys.argv) > 2 else 96)
    elif mode == "check":
        check()
