"""Fetch Steam-store historical lows from IsThereAnyDeal for the core library.

1. Map Steam AppIDs to ITAD game ids in bulk (lookup by shop id, Steam = 61).
2. Steam-store lows per region (storelow, shops=61); falls back to historylow
   (all shops) only if storelow is unavailable, and records which one was used.
Saves data/raw/itad/{id_map,low_CN,low_US}.json
Usage: python scripts/fetch_itad.py
"""
import json
import time
import urllib.parse

from check_keys import ENV_FILE, ROOT, load_env, request

CORE = ROOT / "data" / "core_candidates.json"
RAW = ROOT / "data" / "raw" / "itad"
API = "https://api.isthereanydeal.com"
REGIONS = ["CN", "US"]


def post(path, params, body, key):
    url = f"{API}{path}?" + urllib.parse.urlencode({**params, "key": key})
    for attempt in range(10):
        st, res = request(url, "POST", body)
        if st == 200:
            return res
        time.sleep(60 if st == 429 else 3 * (attempt + 1))
    raise RuntimeError(f"ITAD {path} HTTP {st}: {str(res)[:150]}")


def main():
    key = load_env(ENV_FILE)["ITAD_API_KEY"]
    RAW.mkdir(parents=True, exist_ok=True)
    appids = [g["appid"] for g in json.loads(CORE.read_text(encoding="utf-8"))]

    map_file = RAW / "id_map.json"
    if map_file.exists():
        id_map = json.loads(map_file.read_text(encoding="utf-8"))
    else:
        id_map = {}
        for i in range(0, len(appids), 200):
            res = post("/lookup/id/shop/61/v1", {}, [f"app/{a}" for a in appids[i:i + 200]], key)
            id_map.update({k.split("/")[1]: v for k, v in res.items() if v})
            time.sleep(1)
        map_file.write_text(json.dumps(id_map), encoding="utf-8")
    print(f"mapped {len(id_map)}/{len(appids)} AppIDs to ITAD ids", flush=True)

    gids = sorted(set(id_map.values()))
    for region in REGIONS:
        out = RAW / f"low_{region}.json"
        if out.exists():
            print(f"{region}: cached", flush=True)
            continue
        rows = []
        for i in range(0, len(gids), 200):
            rows += post("/games/storelow/v2", {"country": region, "shops": 61}, gids[i:i + 200], key)
            time.sleep(1)
        out.write_text(json.dumps({"source": "storelow", "rows": rows}), encoding="utf-8")
        print(f"{region}: {len(rows)} rows via storelow", flush=True)


if __name__ == "__main__":
    main()
