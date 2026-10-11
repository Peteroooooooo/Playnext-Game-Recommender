"""Check that the Steam, IGDB (Twitch) and ITAD keys in .env work.

Usage: python scripts/check_keys.py
Never prints key values. The Twitch access token is fetched automatically
and cached in .cache/twitch_token.json until shortly before it expires.
"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"
TOKEN_FILE = ROOT / ".cache" / "twitch_token.json"
UA = "BacklogBreaker/0.1 (NUS-ISS student project)"
TEST_APPID = 1426210  # It Takes Two


def load_env(path: Path) -> dict:
    env = {}
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def request(url, method="GET", data=None, headers=None):
    h = {"User-Agent": UA}
    h.update(headers or {})
    if isinstance(data, (dict, list)):
        data = json.dumps(data).encode()
        h["Content-Type"] = "application/json"
    elif isinstance(data, str):
        data = data.encode()
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:200].decode("utf-8", "replace")
    except Exception as e:  # network errors
        return None, repr(e)[:200]


def twitch_token(env) -> str:
    if TOKEN_FILE.exists():
        cached = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
        if cached.get("expires_at", 0) > time.time() + 3600:
            return cached["access_token"]
    q = urllib.parse.urlencode({
        "client_id": env["TWITCH_CLIENT_ID"],
        "client_secret": env["TWITCH_CLIENT_SECRET"],
        "grant_type": "client_credentials",
    })
    st, body = request("https://id.twitch.tv/oauth2/token?" + q, method="POST")
    if st != 200:
        raise RuntimeError(f"Twitch token request failed: HTTP {st} {body}")
    TOKEN_FILE.parent.mkdir(exist_ok=True)
    TOKEN_FILE.write_text(json.dumps({
        "access_token": body["access_token"],
        "expires_at": time.time() + body["expires_in"],
    }), encoding="utf-8")
    return body["access_token"]


def check_steam(env):
    st, body = request("https://api.steampowered.com/IStoreService/GetAppList/v1/?"
                       + urllib.parse.urlencode({"key": env["STEAM_API_KEY"], "max_results": 5}))
    if st == 200:
        n = len(body.get("response", {}).get("apps", []))
        return True, f"GetAppList OK, returned {n} apps"
    return False, f"HTTP {st}: {str(body)[:120]}"


def check_igdb(env):
    token = twitch_token(env)
    days = (json.loads(TOKEN_FILE.read_text())["expires_at"] - time.time()) / 86400
    headers = {"Client-ID": env["TWITCH_CLIENT_ID"], "Authorization": f"Bearer {token}"}
    body = f'fields game,uid; where uid = "{TEST_APPID}" & external_game_source = 1; limit 5;'
    st, res = request("https://api.igdb.com/v4/external_games", "POST", body, headers)
    if st != 200:
        # older field name, in case the source filter differs
        body = f'fields game,uid,category; where uid = "{TEST_APPID}"; limit 5;'
        st, res = request("https://api.igdb.com/v4/external_games", "POST", body, headers)
    if st != 200 or not res:
        return False, f"external_games HTTP {st}: {str(res)[:120]}"
    game_id = res[0]["game"]
    body = f"fields onlinecoopmax,offlinecoopmax,onlinemax,offlinemax,splitscreen,platform; where game = {game_id};"
    st, modes = request("https://api.igdb.com/v4/multiplayer_modes", "POST", body, headers)
    if st != 200:
        return False, f"multiplayer_modes HTTP {st}: {str(modes)[:120]}"
    return True, f"token OK (expires in {days:.0f} days); IGDB game {game_id}; multiplayer_modes: {modes}"


def check_itad(env):
    key = env["ITAD_API_KEY"]
    st, res = request("https://api.isthereanydeal.com/games/lookup/v1?"
                      + urllib.parse.urlencode({"key": key, "appid": TEST_APPID}))
    if st != 200 or not res.get("found"):
        return False, f"lookup HTTP {st}: {str(res)[:120]}"
    gid = res["game"]["id"]
    st, low = request("https://api.isthereanydeal.com/games/historylow/v1?"
                      + urllib.parse.urlencode({"key": key, "country": "CN"}), "POST", [gid])
    if st != 200:
        return False, f"historylow HTTP {st}: {str(low)[:120]}"
    return True, f"lookup OK; CN history low: {json.dumps(low[0].get('low') if low else None, ensure_ascii=False)}"


def main():
    env = load_env(ENV_FILE)
    checks = [
        ("Steam Web API", ["STEAM_API_KEY"], check_steam),
        ("IGDB / Twitch", ["TWITCH_CLIENT_ID", "TWITCH_CLIENT_SECRET"], check_igdb),
        ("IsThereAnyDeal", ["ITAD_API_KEY"], check_itad),
    ]
    for name, needed, fn in checks:
        missing = [k for k in needed if not env.get(k)]
        if missing:
            print(f"[SKIP] {name}: missing {', '.join(missing)} in {ENV_FILE}")
            continue
        try:
            ok, msg = fn(env)
        except Exception as e:
            ok, msg = False, str(e)[:200]
        print(f"[{'OK' if ok else 'FAIL'}] {name}: {msg}")


if __name__ == "__main__":
    main()
