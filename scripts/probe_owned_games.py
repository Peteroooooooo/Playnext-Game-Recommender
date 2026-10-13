"""Check what GetOwnedGames returns under each Steam privacy setting (design 4.1, hidden playtime rule).

Run it yourself in a terminal; it asks for a Steam profile link (input is hidden):
    uv run python scripts/probe_owned_games.py
Accepts https://steamcommunity.com/profiles/<17 digits>, https://steamcommunity.com/id/<name>, the 17 digits or the name.
Non-interactive runs can pass it in the environment variable PLAYNEXT_PROBE_PROFILE instead.
Prints only counts and field names: never the SteamID, game ids or hours, and writes nothing to disk.
`--selftest` checks the summary logic on made-up responses without any network call.
"""
import getpass
import os
import re
import sys
import urllib.parse

from check_keys import ENV_FILE, load_env, request

API = "https://api.steampowered.com"
VISIBILITY = {1: "私密（或仅好友）", 2: "仅好友", 3: "公开"}


def resolve(env, text):
    text = text.strip().rstrip("/")
    m = re.search(r"/profiles/(\d{17})", text) or re.fullmatch(r"(\d{17})", text)
    if m:
        return m.group(1)
    m = re.search(r"/id/([^/?#]+)", text)
    name = m.group(1) if m else text
    st, body = request(f"{API}/ISteamUser/ResolveVanityURL/v1/?"
                       + urllib.parse.urlencode({"key": env["STEAM_API_KEY"], "vanityurl": name}))
    if st == 200 and body.get("response", {}).get("success") == 1:
        return body["response"]["steamid"]
    return None


def summarize(owned, visibility=None):
    """owned: the GetOwnedGames JSON. Returns printable lines and a verdict code."""
    lines = [f"资料页公开程度：{VISIBILITY.get(visibility, visibility)}"]
    resp = owned.get("response", {}) if isinstance(owned, dict) else {}
    if "game_count" not in resp:
        lines.append(f"GetOwnedGames 返回：{owned if not resp else sorted(resp)}（没有 game_count）")
        return lines + ["判断：游戏详情不公开 → 走 C 问卷"], "private"
    games = resp.get("games", [])
    fields = sorted({k for g in games for k in g})
    played = sum(1 for g in games if g.get("playtime_forever", 0) > 0)
    two_weeks = sum(1 for g in games if g.get("playtime_2weeks", 0) > 0)
    last = sum(1 for g in games if g.get("rtime_last_played", 0) > 0)
    lines += [f"game_count = {resp['game_count']}，实际返回 {len(games)} 款",
              f"返回的字段：{', '.join(fields) or '（无）'}",
              f"playtime_forever > 0 的：{played} 款",
              f"playtime_2weeks > 0 的：{two_weeks} 款",
              f"rtime_last_played > 0 的：{last} 款"]
    if last:
        lines.append("注意：返回了最后游玩时间。网上说这只在查 API key 主人自己的号时出现，"
                     "那这次结果可能比普通用户看到的多，换一个不是 key 主人的号再测一次")
    if not games:
        return lines + ["判断：库是空的"], "empty"
    if played == 0:
        return lines + ["判断：所有游戏时长都是 0 → 按“隐藏了游玩时间”处理（只标已拥有，不当口味）"], "hidden"
    return lines + ["判断：正常，时长可用"], "normal"


def selftest():
    cases = {
        "private": ({"response": {}}, 1),
        "hidden": ({"response": {"game_count": 2, "games": [{"appid": 1, "playtime_forever": 0},
                                                           {"appid": 2, "playtime_forever": 0}]}}, 3),
        "normal": ({"response": {"game_count": 2, "games": [{"appid": 1, "playtime_forever": 90},
                                                           {"appid": 2, "playtime_forever": 0}]}}, 3),
        "empty": ({"response": {"game_count": 0}}, 3),
    }
    for want, (owned, vis) in cases.items():
        _, got = summarize(owned, vis)
        assert got == want, (want, got)
    print("selftest OK:", ", ".join(cases))


def main():
    if "--selftest" in sys.argv:
        return selftest()
    env = load_env(ENV_FILE)
    if not env.get("STEAM_API_KEY"):
        sys.exit(f"STEAM_API_KEY missing in {ENV_FILE}")
    profile = os.environ.get("PLAYNEXT_PROBE_PROFILE") or getpass.getpass("Steam 主页链接 / 17 位 ID / 自定义名（输入不显示）：")
    sid = resolve(env, profile)
    if not sid:
        sys.exit("没认出这个账号：链接或名字不对")
    key = env["STEAM_API_KEY"]
    st, summ = request(f"{API}/ISteamUser/GetPlayerSummaries/v2/?" + urllib.parse.urlencode({"key": key, "steamids": sid}))
    players = summ.get("response", {}).get("players", []) if st == 200 else []
    vis = players[0].get("communityvisibilitystate") if players else None
    st, owned = request(f"{API}/IPlayerService/GetOwnedGames/v1/?" + urllib.parse.urlencode(
        {"key": key, "steamid": sid, "include_played_free_games": 1}))
    if st != 200:
        sys.exit(f"GetOwnedGames HTTP {st}")
    lines, _ = summarize(owned, vis)
    print("\n".join(lines))


if __name__ == "__main__":
    main()
