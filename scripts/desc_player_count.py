"""Test whether Steam store descriptions can fill IGDB's missing player counts.

Same sample as igdb_mp_coverage.py (SteamSpy pages 0 and 5, >= 1000 reviews,
Steam multiplayer category). For each game:
  - IGDB max players (any mode) from multiplayer_modes
  - max players stated in the English store description (regex)
  - whether it carries the "Massively Multiplayer" tag
Reports recall on IGDB-missing games and agreement on IGDB-known games.
Raw pulls are cached in .cache/ so reruns skip the network.
Usage: python scripts/desc_player_count.py
"""
import json
import re
import time
import urllib.parse
from collections import Counter

from check_keys import ENV_FILE, ROOT, load_env, request, twitch_token

PAGES = [0, 5]
MP_CATS = {36, 37, 38, 39}
CACHE = ROOT / ".cache" / "desc_sample.json"

WORDS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve "
    "thirteen fourteen fifteen sixteen".split())}
NUM = r"(\d{1,3}|" + "|".join(WORDS) + r")"
PLAYERS = r"(?:players?|people|gamers|survivors|participants)"
PATTERNS = [
    # "up to 4 players", "for up to eight players", "supports 2-4 players"
    (re.compile(rf"up\s+to\s+{NUM}\s+(?:\w+\s+)?{PLAYERS}", re.I), 0),
    (re.compile(rf"{NUM}\s*(?:-|–|to)\s*{NUM}\s+(?:\w+\s+)?{PLAYERS}", re.I), "range"),
    # "4-player co-op", "4 player online", "8-player"
    (re.compile(rf"\b{NUM}[\s-]player\b", re.I), 0),
    # "with up to 3 friends" -> 3 friends + you
    (re.compile(rf"up\s+to\s+{NUM}\s+(?:other\s+)?(?:friends|others)", re.I), "plus1"),
    # "5v5", "4 vs 4"
    (re.compile(r"\b(\d{1,2})\s*(?:v|vs\.?|versus)\s*(\d{1,2})\b", re.I), "versus"),
]


def to_int(tok):
    tok = tok.lower()
    return int(tok) if tok.isdigit() else WORDS.get(tok)


def extract_max_players(text):
    best = None
    for pat, kind in PATTERNS:
        for m in pat.finditer(text):
            if kind == "range":
                n = to_int(m.group(2))
            elif kind == "versus":
                a, b = int(m.group(1)), int(m.group(2))
                n = a + b if a <= 50 and b <= 50 else None
            else:
                n = to_int(m.group(1))
                if n is not None and kind == "plus1":
                    n += 1
            if n and 2 <= n <= 100:
                best = max(best or 0, n)
    return best


def clean(bbcode):
    text = re.sub(r"\[/?[^\]]+\]", " ", bbcode or "")
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text)


def get_items(appids):
    out = {}
    for i in range(0, len(appids), 50):
        inp = {"ids": [{"appid": a} for a in appids[i:i + 50]],
               "context": {"language": "english", "country_code": "US", "steam_realm": 1},
               "data_request": {"include_basic_info": True, "include_tag_count": 20,
                                "include_full_description": True}}
        st, d = request("https://api.steampowered.com/IStoreBrowseService/GetItems/v1/?input_json="
                        + urllib.parse.quote(json.dumps(inp)))
        if st != 200:
            continue
        for it in d["response"].get("store_items", []):
            c = it.get("categories") or {}
            out[it["appid"]] = {
                "cats": sorted(set(c.get("supported_player_categoryids", []))),
                "tags": [t["tagid"] for t in it.get("tags", [])],
                "desc": clean(it.get("full_description_bbcode", "")) + " "
                        + clean((it.get("basic_info") or {}).get("short_description", "")),
            }
    return out


def igdb_max(appids, headers):
    def q(endpoint, body):
        for _ in range(3):
            st, res = request(f"https://api.igdb.com/v4/{endpoint}", "POST", body, headers)
            if st == 200:
                return res
            time.sleep(1)
        return []

    s2g = {}
    for i in range(0, len(appids), 400):
        uids = ",".join(f'"{a}"' for a in appids[i:i + 400])
        for r in q("external_games", f"fields game,uid; where uid = ({uids}) & external_game_source = 1; limit 500;"):
            s2g.setdefault(int(r["uid"]), r["game"])
    gmax = {}
    gids = list(set(s2g.values()))
    for i in range(0, len(gids), 400):
        ids = ",".join(map(str, gids[i:i + 400]))
        for r in q("multiplayer_modes", f"fields game,onlinecoopmax,offlinecoopmax,onlinemax,offlinemax; where game = ({ids}); limit 500;"):
            m = max(r.get(f) or 0 for f in ("onlinecoopmax", "offlinecoopmax", "onlinemax", "offlinemax"))
            gmax[r["game"]] = max(gmax.get(r["game"], 0), m)
    return {a: (gmax.get(g) or None) for a, g in s2g.items()}


def collect():
    if CACHE.exists():
        return json.loads(CACHE.read_text(encoding="utf-8"))
    env = load_env(ENV_FILE)
    headers = {"Client-ID": env["TWITCH_CLIENT_ID"], "Authorization": f"Bearer {twitch_token(env)}"}
    rows = []
    for idx, p in enumerate(PAGES):
        if idx:
            time.sleep(61)
        st, d = request(f"https://steamspy.com/api.php?request=all&page={p}")
        appids = [v["appid"] for v in d.values() if v["positive"] + v["negative"] >= 1000]
        items = get_items(appids)
        mp = [a for a, it in items.items() if set(it["cats"]) & MP_CATS]
        imax = igdb_max(mp, headers)
        for a in mp:
            rows.append({"page": p, "appid": a, "igdb_max": imax.get(a), **items[a]})
    st, d = request("https://api.steampowered.com/IStoreService/GetTagList/v1/?language=english")
    mmo_ids = [t["tagid"] for t in d["response"]["tags"] if t["name"].lower() == "massively multiplayer"]
    data = {"rows": rows, "mmo_tag_ids": mmo_ids}
    CACHE.parent.mkdir(exist_ok=True)
    CACHE.write_text(json.dumps(data), encoding="utf-8")
    return data


def main():
    data = collect()
    mmo = set(data["mmo_tag_ids"])
    for p in PAGES:
        rows = [r for r in data["rows"] if r["page"] == p]
        c = Counter()
        for r in rows:
            desc_n = extract_max_players(r["desc"])
            is_mmo = bool(mmo & set(r["tags"]))
            if r["igdb_max"]:
                c["known"] += 1
                if desc_n:
                    c["known_desc"] += 1
                    c["agree"] += desc_n == r["igdb_max"]
                    c["within1"] += abs(desc_n - r["igdb_max"]) <= 1
            else:
                c["missing"] += 1
                c["miss_desc"] += bool(desc_n)
                c["miss_mmo"] += is_mmo and not desc_n
                c["miss_filled"] += bool(desc_n) or is_mmo
        pct = lambda a, b: f"{c[a]}/{c[b]} ({100 * c[a] / c[b]:.0f}%)" if c[b] else "n/a"
        print(f"\n== SteamSpy page {p}: {len(rows)} multiplayer games ==")
        print("IGDB has max players          ", pct("known", "known") if False else f"{c['known']}/{len(rows)}")
        print("-- IGDB missing:", c["missing"])
        print("   description gives a count  ", pct("miss_desc", "missing"))
        print("   + MMO tag (no count in desc)", pct("miss_mmo", "missing"))
        print("   filled by either           ", pct("miss_filled", "missing"))
        print("-- IGDB known, desc also gives a count:", pct("known_desc", "known"))
        print("   exact agreement with IGDB  ", pct("agree", "known_desc"))
        print("   within +-1                 ", pct("within1", "known_desc"))


if __name__ == "__main__":
    main()
