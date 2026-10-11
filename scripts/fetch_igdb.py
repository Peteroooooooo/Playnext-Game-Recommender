"""Fetch IGDB data for the core library.

Saves raw lists under data/raw/igdb/:
  external_games.json   Steam AppID -> IGDB game id
  games.json            series (collections / franchises), companies, similar_games
  multiplayer_modes.json
  time_to_beat.json
Usage: python scripts/fetch_igdb.py
"""
import json
import time

from check_keys import ENV_FILE, ROOT, load_env, request, twitch_token

CORE = ROOT / "data" / "core_candidates.json"
RAW = ROOT / "data" / "raw" / "igdb"
CHUNK = 500


def make_query(headers):
    def q(endpoint, body):
        for attempt in range(5):
            time.sleep(0.3)  # 4 requests / second limit
            st, res = request(f"https://api.igdb.com/v4/{endpoint}", "POST", body, headers)
            if st == 200:
                return res
            time.sleep(2 * (attempt + 1))
        raise RuntimeError(f"IGDB {endpoint} HTTP {st}: {str(res)[:150]}")
    return q


def fetch_by_ids(q, endpoint, fields, key, ids):
    out = []
    for i in range(0, len(ids), CHUNK):
        part = ",".join(map(str, ids[i:i + CHUNK]))
        offset = 0
        while True:  # one id can have several rows (e.g. multiplayer modes per platform)
            res = q(endpoint, f"fields {fields}; where {key} = ({part}); limit 500; offset {offset};")
            out += res
            if len(res) < 500:
                break
            offset += 500
    return out


def save(name, rows):
    (RAW / f"{name}.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    print(f"{name}: {len(rows)} rows", flush=True)


def main():
    env = load_env(ENV_FILE)
    q = make_query({"Client-ID": env["TWITCH_CLIENT_ID"], "Authorization": f"Bearer {twitch_token(env)}"})
    RAW.mkdir(parents=True, exist_ok=True)
    appids = [g["appid"] for g in json.loads(CORE.read_text(encoding="utf-8"))]

    ext = []
    for i in range(0, len(appids), CHUNK):
        uids = ",".join(f'"{a}"' for a in appids[i:i + CHUNK])
        offset = 0
        while True:
            res = q("external_games", f"fields game,uid; where uid = ({uids}) & external_game_source = 1; "
                                      f"limit 500; offset {offset};")
            ext += res
            if len(res) < 500:
                break
            offset += 500
    save("external_games", ext)
    gids = sorted({r["game"] for r in ext})

    save("games", fetch_by_ids(q, "games",
         "id,name,collections.name,franchises.name,franchise.name,similar_games,"
         "involved_companies.company.name,involved_companies.developer,involved_companies.publisher",
         "id", gids))
    save("multiplayer_modes", fetch_by_ids(q, "multiplayer_modes",
         "game,platform,onlinecoop,onlinecoopmax,onlinemax,offlinecoop,offlinecoopmax,offlinemax,"
         "splitscreen,splitscreenonline,lancoop,dropin,campaigncoop", "game", gids))
    save("time_to_beat", fetch_by_ids(q, "game_time_to_beats", "game_id,hastily,normally,completely,count",
         "game_id", gids))


if __name__ == "__main__":
    main()
