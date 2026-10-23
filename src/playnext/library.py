"""Paths A and B (design 4.1): read a Steam library with the project key.

The SteamID only lives inside these functions: callers get a Library (appid -> hours) and a keyed hash of the
account (profiles.profile_key), never the ID itself. Nothing here logs or stores it.
"""
import hashlib
import json
import os
import re
import urllib.parse
import urllib.request

from .i18n import L
from .pricing import load_env
from .profiles import profile_key
from .spec import Library

API = "https://api.steampowered.com"
OPENID = "https://steamcommunity.com/openid/login"
UA = "BacklogBreaker/0.1 (NUS-ISS student project)"
_SALT = os.urandom(16)  # per process: hashes cannot be linked across restarts


class LibraryError(Exception):
    pass


def _get(url, timeout=10):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def resolve_steamid(text, key):
    """Profile link, 17-digit id or custom name -> SteamID (str) or None."""
    text = (text or "").strip().rstrip("/")
    m = re.search(r"/profiles/(\d{17})", text) or re.fullmatch(r"(\d{17})", text)
    if m:
        return m.group(1)
    m = re.search(r"/id/([^/?#]+)", text)
    name = m.group(1) if m else text
    if not re.fullmatch(r"[A-Za-z0-9_-]{2,64}", name or ""):
        return None
    body = _get(f"{API}/ISteamUser/ResolveVanityURL/v1/?" + urllib.parse.urlencode({"key": key, "vanityurl": name}))
    r = body.get("response", {})
    return r.get("steamid") if r.get("success") == 1 else None


def parse_owned(owned: dict) -> Library:
    """GetOwnedGames JSON -> Library. No game_count = game details not public (design 4.1)."""
    resp = owned.get("response", {}) if isinstance(owned, dict) else {}
    if "game_count" not in resp:
        return Library(is_public=False)
    games = {int(g["appid"]): g.get("playtime_forever", 0) / 60 for g in resp.get("games", [])}
    hidden = bool(games) and all(h == 0 for h in games.values())
    return Library(is_public=True, owned=games, playtime_hidden=hidden)


def fetch_library(steamid, key=None) -> Library:
    key = key or load_env().get("STEAM_API_KEY")
    if not key:
        raise LibraryError("STEAM_API_KEY missing")
    owned = _get(f"{API}/IPlayerService/GetOwnedGames/v1/?" + urllib.parse.urlencode(
        {"key": key, "steamid": steamid, "include_played_free_games": 1}))
    return parse_owned(owned)


def library_from_profile(text) -> tuple[Library, str]:
    """Path B. Returns (library, profile key of the account: keyed hash for the slow loop, see profiles.py)."""
    key = load_env().get("STEAM_API_KEY")
    if not key:
        raise LibraryError("STEAM_API_KEY missing")
    sid = resolve_steamid(text, key)
    if not sid:
        raise LibraryError(L("没认出这个 Steam 账号：请检查主页链接或自定义名",
                             "Could not find this Steam account: check the profile link or custom name"))
    return fetch_library(sid, key), profile_key(sid)


def account_hash(steamid):
    return hashlib.blake2b(str(steamid).encode(), key=_SALT, digest_size=8).hexdigest()


# ---------- Path A: Steam OpenID 2.0 ----------

def openid_login_url(return_to, realm):
    q = {"openid.ns": "http://specs.openid.net/auth/2.0", "openid.mode": "checkid_setup",
         "openid.return_to": return_to, "openid.realm": realm,
         "openid.identity": "http://specs.openid.net/auth/2.0/identifier_select",
         "openid.claimed_id": "http://specs.openid.net/auth/2.0/identifier_select"}
    return OPENID + "?" + urllib.parse.urlencode(q)


def openid_verify(params: dict):
    """Ask Steam to confirm the signed assertion; returns the SteamID or None."""
    if params.get("openid.mode") != "id_res":
        return None
    check = dict(params)
    check["openid.mode"] = "check_authentication"
    data = urllib.parse.urlencode(check).encode()
    req = urllib.request.Request(OPENID, data=data, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=10) as r:
        body = r.read().decode()
    if "is_valid:true" not in body:
        return None
    m = re.fullmatch(r"https://steamcommunity\.com/openid/id/(\d{17})", params.get("openid.claimed_id", ""))
    return m.group(1) if m else None
