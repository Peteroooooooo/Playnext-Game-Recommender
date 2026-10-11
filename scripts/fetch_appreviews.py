"""Fetch recent positive Steam reviews to build co-like data for post-2022 games.

Reviewer steamids are replaced by a salted hash before anything is written;
the salt lives in .cache/review_salt and never leaves the machine.
Output: data/raw/appreviews/<appid>.json  -> [[reviewer_hash, unix_time], ...]

Usage:
  python scripts/fetch_appreviews.py trial      # 100 new games x 1000 + 200 popular old games x 300
  python scripts/fetch_appreviews.py full       # all core games (new x 1000, old x 300)
  python scripts/fetch_appreviews.py analyze    # neighbour statistics on whatever is fetched
"""
import hashlib
import json
import random
import secrets
import sys
import threading
import time
import urllib.parse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

from check_keys import ROOT, request

CORE = ROOT / "data" / "core_candidates.json"
REL = ROOT / "data" / "derived" / "release_dates.json"
OUT = ROOT / "data" / "raw" / "appreviews"
SALT_FILE = ROOT / ".cache" / "review_salt"
NEW_YEAR = 2023
NEW_LIMIT, OLD_LIMIT = 1000, 300
MIN_INTERVAL = 1.5  # seconds between requests; parallel workers trigger HTTP 429 (tested)
WORKERS = 1
TRIAL_OLD = 200


def salt():
    if not SALT_FILE.exists():
        SALT_FILE.parent.mkdir(exist_ok=True)
        SALT_FILE.write_text(secrets.token_hex(16), encoding="utf-8")
    return SALT_FILE.read_text(encoding="utf-8").strip()


def split_core():
    core = json.loads(CORE.read_text(encoding="utf-8"))
    years = {int(k): v for k, v in json.loads(REL.read_text(encoding="utf-8")).items()}
    new = [g for g in core if (years.get(g["appid"]) or NEW_YEAR) >= NEW_YEAR]  # unknown year treated as new
    old = [g for g in core if (years.get(g["appid"]) or NEW_YEAR) < NEW_YEAR]
    return new, old


_local = threading.local()


def get_page(appid, cursor):
    q = urllib.parse.urlencode({"json": 1, "filter": "recent", "review_type": "positive", "language": "all",
                                "purchase_type": "all", "num_per_page": 100, "cursor": cursor})
    for attempt in range(5):
        wait = MIN_INTERVAL - (time.time() - getattr(_local, "last", 0.0))
        if wait > 0:
            time.sleep(wait)
        _local.last = time.time()
        st, d = request(f"https://store.steampowered.com/appreviews/{appid}?{q}")
        if st == 200 and isinstance(d, dict):
            return d
        time.sleep(120 if st == 429 else 5 * (attempt + 1))
    return None


def fetch_game(appid, limit, s):
    f = OUT / f"{appid}.json"
    if f.exists():
        return False
    rows, cursor, seen = [], "*", set()
    while len(rows) < limit:
        d = get_page(appid, cursor)
        if d is None:
            return False  # request kept failing (e.g. rate limit): leave no partial file
        if not d.get("reviews"):
            break
        for r in d["reviews"]:
            h = hashlib.sha256((s + r["author"]["steamid"]).encode()).hexdigest()[:16]
            rows.append([h, r["timestamp_created"]])
        cursor = d.get("cursor")
        if not cursor or cursor in seen:
            break
        seen.add(cursor)
    OUT.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(rows[:limit]), encoding="utf-8")
    return True


def run(jobs):
    s = salt()
    t0 = time.time()
    with ThreadPoolExecutor(WORKERS) as pool:
        futures = [pool.submit(fetch_game, appid, limit, s) for appid, limit in jobs]
        for i, fut in enumerate(as_completed(futures), 1):
            fut.result()
            if i % 50 == 0 or i == len(jobs):
                print(f"{i}/{len(jobs)} games, {time.time() - t0:.0f}s", flush=True)


def analyze():
    new, old = split_core()
    new_ids = {g["appid"] for g in new}
    users = defaultdict(set)
    games = 0
    for f in OUT.glob("*.json"):
        a = int(f.stem)
        games += 1
        for h, _ in json.loads(f.read_text(encoding="utf-8")):
            users[a].add(h)
    by_user = defaultdict(set)
    for a, hs in users.items():
        for h in hs:
            by_user[h].add(a)
    multi = sum(1 for gs in by_user.values() if len(gs) >= 2)
    print(f"games fetched {games} (new {len(new_ids & set(users))}); reviews {sum(map(len, users.values())):,}; "
          f"distinct reviewers {len(by_user):,}; reviewers in >=2 games {multi:,}")
    stats = Counter()
    for a in new_ids & set(users):
        co = Counter()
        for h in users[a]:
            for b in by_user[h]:
                if b != a:
                    co[b] += 1
        for k in (3, 10):
            n = sum(1 for v in co.values() if v >= k)
            stats[f"new games with >=20 neighbours sharing >={k} reviewers"] += n >= 20
            stats[f"new games with >=1 neighbour sharing >={k} reviewers"] += n >= 1
        stats["new games"] += 1
    for k, v in sorted(stats.items()):
        print(f"{k}: {v}")


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "trial"
    new, old = split_core()
    pop = lambda g: -(g["positive"] + g["negative"])
    if mode == "trial":
        rng = random.Random(42)
        jobs = [(g["appid"], NEW_LIMIT) for g in rng.sample(new, 100)]
        jobs += [(g["appid"], OLD_LIMIT) for g in sorted(old, key=pop)[:TRIAL_OLD]]
        run(jobs)
        analyze()
    elif mode == "full":
        run([(g["appid"], NEW_LIMIT) for g in new] + [(g["appid"], OLD_LIMIT) for g in sorted(old, key=pop)])
        analyze()
    else:
        analyze()


if __name__ == "__main__":
    main()
