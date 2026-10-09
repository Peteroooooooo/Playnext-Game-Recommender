"""Estimate how often IGDB provides player-count limits for Steam multiplayer games.

Samples SteamSpy 'all' pages (popular head and a mid-tail page), keeps games
with >= 1000 reviews and a Steam multiplayer category, then checks IGDB
external_games + multiplayer_modes. Prints aggregate rates only.
Usage: python scripts/igdb_mp_coverage.py
"""
import json
import time
import urllib.parse
from collections import Counter

from check_keys import ENV_FILE, load_env, request, twitch_token

PAGES = [0, 5]
# Steam category ids: 36 online PvP, 37 shared/split PvP, 38 online co-op,
# 39 shared/split co-op, 44 remote play together, 47 LAN PvP, 48 LAN co-op
ONLINE_COOP, ONLINE_PVP, LOCAL_COOP, LOCAL_PVP, RPT = 38, 36, 39, 37, 44


def steamspy_page(p):
    st, d = request(f"https://steamspy.com/api.php?request=all&page={p}")
    return [v for v in d.values() if v["positive"] + v["negative"] >= 1000] if st == 200 else []


def steam_categories(appids):
    out = {}
    for i in range(0, len(appids), 100):
        inp = {"ids": [{"appid": a} for a in appids[i:i + 100]],
               "context": {"language": "english", "country_code": "US", "steam_realm": 1},
               "data_request": {"include_basic_info": False}}
        st, d = request("https://api.steampowered.com/IStoreBrowseService/GetItems/v1/?input_json="
                        + urllib.parse.quote(json.dumps(inp)))
        if st != 200:
            continue
        for it in d["response"].get("store_items", []):
            c = it.get("categories") or {}
            out[it.get("appid")] = set(c.get("supported_player_categoryids", [])) | set(c.get("feature_categoryids", []))
    return out


def igdb(endpoint, body, headers):
    for _ in range(3):
        st, res = request(f"https://api.igdb.com/v4/{endpoint}", "POST", body, headers)
        if st == 200:
            return res
        time.sleep(1)
    raise RuntimeError(f"IGDB {endpoint} HTTP {st}: {str(res)[:120]}")


def main():
    env = load_env(ENV_FILE)
    headers = {"Client-ID": env["TWITCH_CLIENT_ID"], "Authorization": f"Bearer {twitch_token(env)}"}
    stats = {}
    for idx, p in enumerate(PAGES):
        if idx:
            time.sleep(61)  # SteamSpy all: 1 request / 60 s
        games = steamspy_page(p)
        cats = steam_categories([g["appid"] for g in games])
        mp = {a: c for a, c in cats.items() if c & {ONLINE_COOP, ONLINE_PVP, LOCAL_COOP, LOCAL_PVP}}
        appids = list(mp)

        steam2igdb = {}
        for i in range(0, len(appids), 400):
            uids = ",".join(f'"{a}"' for a in appids[i:i + 400])
            res = igdb("external_games", f"fields game,uid; where uid = ({uids}) & external_game_source = 1; limit 500;", headers)
            for r in res:
                steam2igdb.setdefault(int(r["uid"]), r["game"])
            time.sleep(0.3)

        modes = {}
        gids = list(set(steam2igdb.values()))
        for i in range(0, len(gids), 400):
            ids = ",".join(map(str, gids[i:i + 400]))
            res = igdb("multiplayer_modes", f"fields game,onlinecoopmax,offlinecoopmax,onlinemax,offlinemax,splitscreen,splitscreenonline; where game = ({ids}); limit 500;", headers)
            for r in res:
                modes.setdefault(r["game"], []).append(r)
            time.sleep(0.3)

        c = Counter()
        for a, cat in mp.items():
            c["mp_games"] += 1
            g = steam2igdb.get(a)
            c["mapped"] += g is not None
            rows = modes.get(g, []) if g else []
            c["has_mode_row"] += bool(rows)

            def any_val(field):
                return any((r.get(field) or 0) > 0 for r in rows)

            for cid, field, label in [(ONLINE_COOP, "onlinecoopmax", "online_coop"),
                                      (ONLINE_PVP, "onlinemax", "online_pvp"),
                                      (LOCAL_COOP, "offlinecoopmax", "local_coop"),
                                      (LOCAL_PVP, "offlinemax", "local_pvp")]:
                if cid in cat:
                    c[f"{label}_n"] += 1
                    c[f"{label}_has_max"] += any_val(field)
            c["rpt_n"] += RPT in cat
        stats[f"page {p}"] = (len(games), c)

    for page, (n_rev, c) in stats.items():
        print(f"\n== SteamSpy {page}: {n_rev} games with >=1000 reviews, {c['mp_games']} with a Steam multiplayer category ==")
        pct = lambda a, b: f"{c[a]}/{c[b]} ({100 * c[a] / c[b]:.0f}%)" if c[b] else "n/a"
        print("mapped to IGDB          ", pct("mapped", "mp_games"))
        print("has any multiplayer row ", pct("has_mode_row", "mp_games"))
        for label in ["online_coop", "online_pvp", "local_coop", "local_pvp"]:
            print(f"{label:<11} has max count ", pct(f"{label}_has_max", f"{label}_n"))
        print("remote play together    ", c["rpt_n"])


if __name__ == "__main__":
    main()
