"""What GetOwnedGames returns for a random sample of real reviewers (design 4.1, hidden playtime rule).

Takes N random reviewers from the Kaggle review files (raw author_id, kept in memory only), each with one review
whose Steam playtime was >= 1 hour when the review was scraped. For each account it calls GetPlayerSummaries and
GetOwnedGames and classifies the response:
  private  : no game_count (game details not public)
  all_zero : games listed but every playtime_forever is 0
  normal   : at least one game with playtime > 0
Evidence for "all_zero = playtime hidden": Steam playtime never goes down, so if the reviewed game is listed with 0
while the review recorded >= 1 hour, the API is hiding it.
Prints counts only: no SteamID, game id or hours of any account is printed or written to disk.
Usage: uv run python scripts/probe_owned_sample.py [N]
"""
import random
import sys
import urllib.parse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pyarrow.parquet as pq

from check_keys import ENV_FILE, ROOT, load_env, request

API = "https://api.steampowered.com"
REVIEWS = ROOT / "data" / "raw" / "kaggle_reviews100m" / "extracted" / "reviews"
N = int(sys.argv[1]) if len(sys.argv) > 1 else 600
MIN_MINUTES = 60
FILES, SEED = 12, 20261014


def sample_reviewers():
    rng = random.Random(SEED)
    files = sorted(REVIEWS.rglob("*.parquet"))
    picked = {}
    for f in rng.sample(files, FILES):
        t = pq.read_table(f, columns=["author_id", "appid", "playtime_forever"]).to_pandas()
        t = t[t["playtime_forever"] >= MIN_MINUTES].drop_duplicates("author_id")
        for r in t.sample(min(len(t), N // FILES + 1), random_state=rng.randrange(1 << 30)).itertuples():
            picked[int(r.author_id)] = (int(r.appid), int(r.playtime_forever))
    ids = list(picked)
    rng.shuffle(ids)
    return {i: picked[i] for i in ids[:N]}


def main():
    key = load_env(ENV_FILE)["STEAM_API_KEY"]
    people = sample_reviewers()
    ids = list(people)
    print(f"sampled {len(ids)} reviewers from {FILES} review files (each has a review with >= {MIN_MINUTES} min on Steam)")

    vis = {}
    for k in range(0, len(ids), 100):
        st, body = request(f"{API}/ISteamUser/GetPlayerSummaries/v2/?"
                           + urllib.parse.urlencode({"key": key, "steamids": ",".join(map(str, ids[k:k + 100]))}))
        for p in (body.get("response", {}).get("players", []) if st == 200 else []):
            vis[int(p["steamid"])] = p.get("communityvisibilitystate")

    def owned(sid):
        for _ in range(3):
            st, body = request(f"{API}/IPlayerService/GetOwnedGames/v1/?" + urllib.parse.urlencode(
                {"key": key, "steamid": sid, "include_played_free_games": 1}))
            if st == 200:
                return body
        return None

    with ThreadPoolExecutor(4) as ex:
        results = dict(zip(ids, ex.map(owned, ids)))

    c, ev, fields, two_weeks = Counter(), Counter(), Counter(), Counter()
    for sid in ids:
        res, (appid, review_min) = results[sid], people[sid]
        v = vis.get(sid)
        if res is None:
            c["request failed"] += 1
            continue
        r = res.get("response", {})
        if v is None:
            kind = "account gone"
        elif "game_count" not in r:
            kind = f"private (profile visibility {v})"
        else:
            games = r.get("games", [])
            kind = "empty" if not games else ("all_zero" if all(g.get("playtime_forever", 0) == 0 for g in games) else "normal")
            for g in games:
                fields.update(g.keys())
            two_weeks[kind] += any(g.get("playtime_2weeks", 0) > 0 for g in games)
            mine = next((g for g in games if g["appid"] == appid), None)
            if mine is None:
                ev[(kind, "reviewed game not listed")] += 1
            elif mine.get("playtime_forever", 0) == 0:
                ev[(kind, "reviewed game listed with 0 (review had >= 1 h)")] += 1
            elif mine["playtime_forever"] >= review_min:
                ev[(kind, "listed, hours >= review's")] += 1
            else:
                ev[(kind, "listed, hours < review's")] += 1
        c[kind] += 1

    print("\naccounts by response type:")
    for k, n in c.most_common():
        print(f"  {k:<32} {n:>4}  ({n / len(ids):.1%})")
    print("\nreviewed game vs what GetOwnedGames says:")
    for (kind, what), n in sorted(ev.items()):
        print(f"  {kind:<9} {what:<50} {n:>4}")
    print("\naccounts with any playtime_2weeks > 0:", dict(two_weeks))
    print("fields seen in game rows:", dict(fields))


if __name__ == "__main__":
    main()
