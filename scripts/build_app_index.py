"""Light index of every Steam game: AppID + name (design 6.1 "全量轻量索引").

Used to recognise library and seed games that are not in the core library. Source: IStoreService/GetAppList/v1
(Steam Web API key; the old ISteamApps/GetAppList is offline), games only: no DLC, software, videos or hardware.
50,000 apps a page, paged by last_appid.
Writes data/processed/app_index.parquet: appid (int64), name (str), last_modified (int64, Unix seconds, as Steam
returns it).
Usage: uv run python scripts/build_app_index.py
"""
import time
import urllib.parse

import pandas as pd

from check_keys import ENV_FILE, ROOT, load_env, request

OUT = ROOT / "data" / "processed" / "app_index.parquet"
URL = "https://api.steampowered.com/IStoreService/GetAppList/v1/?"
PAGE = 50_000


def page(key, last_appid):
    q = {"key": key, "include_games": "true", "include_dlc": "false", "include_software": "false",
         "include_videos": "false", "include_hardware": "false", "max_results": PAGE}
    if last_appid:
        q["last_appid"] = last_appid
    for attempt in range(5):
        st, body = request(URL + urllib.parse.urlencode(q))  # the URL carries the key: never print it
        if st == 200:
            return body.get("response", {})
        time.sleep(60 if st == 429 else 5 * (attempt + 1))
    raise RuntimeError(f"GetAppList failed after last_appid={last_appid}: HTTP {st}")


def main():
    key = load_env(ENV_FILE).get("STEAM_API_KEY")
    if not key:
        raise SystemExit(f"STEAM_API_KEY missing in {ENV_FILE}")
    rows, last = [], 0
    while True:
        r = page(key, last)
        apps = r.get("apps", [])
        rows += apps
        print(f"page after appid {last}: {len(apps):,} apps (total {len(rows):,})", flush=True)
        if not r.get("have_more_results") or not apps:
            break
        last = r.get("last_appid") or apps[-1]["appid"]
        time.sleep(1)
    df = pd.DataFrame(rows)
    df = df[["appid", "name"] + (["last_modified"] if "last_modified" in df else [])]
    df["appid"] = df["appid"].astype("int64")
    df["name"] = df["name"].fillna("").astype(str).str.strip()
    if "last_modified" in df:
        df["last_modified"] = df["last_modified"].fillna(0).astype("int64")
    df = df.drop_duplicates("appid").sort_values("appid").reset_index(drop=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_name(OUT.name + ".tmp")
    df.to_parquet(tmp, index=False)
    tmp.replace(OUT)
    print(f"wrote {OUT.relative_to(ROOT)}: {len(df):,} games ({(df['name'] == '').sum():,} without a name)")


if __name__ == "__main__":
    main()
