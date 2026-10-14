"""Game name and alias table, so seeds written as Chinese short names ("文明6", "老头环") resolve to the right game.

Sources, in order of trust:
  store_en / store_zh : the English and Simplified Chinese store names (games.name / games.name_zh)
  llm                 : names Chinese players commonly use, asked from the LLM in batches (only game names are sent);
                        raw replies are cached under .cache/alias_llm/; a rerun only asks about games not asked before
An LLM alias that equals another game's store name is dropped. One alias may still point to several games
(e.g. an original and its remake); resolve() then takes the one with the most reviews.
Writes data/processed/aliases.parquet: alias (normalised), appid, source.
Usage: uv run python scripts/build_aliases.py         build the table
       uv run python scripts/build_aliases.py test    check 50 common Chinese short names
"""
import json
import re
import sys
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from check_keys import ROOT, load_env

PROC = ROOT / "data" / "processed"
OUT = PROC / "aliases.parquet"
CACHE = ROOT / ".cache" / "alias_llm"
BATCH, WORKERS = 40, 6

PROMPT = (
    "For each Steam game below (appid | English store name | Chinese store name if any), list the names that "
    "Chinese-speaking players commonly use for it: the official Chinese name, widely used Chinese nicknames and "
    "short forms (e.g. 老头环 or 艾尔登法环 for ELDEN RING, 文明6 for Sid Meier's Civilization VI, 大镖客2 for Red Dead "
    "Redemption 2), and common English short forms (e.g. RDR2, BG3, CS2). Rules: only names you are confident are "
    "really used for THIS game; no literal translations nobody uses; no bare series names that cover several games "
    "(e.g. just 文明 or 刺客信条); at most 6 names per game; an empty list is fine.\n"
    'Return only a JSON object mapping appid (string) to a list of names, e.g. {"1245620": ["艾尔登法环", "老头环"]}.')

# (what a player might type, English store name of the intended game) for `test`
TEST = [
    ("文明6", "Sid Meier’s Civilization® VI"), ("文明5", "Sid Meier's Civilization® V"),
    ("星露谷", "Stardew Valley"), ("星露谷物语", "Stardew Valley"), ("双人成行", "It Takes Two"),
    ("老头环", "ELDEN RING"), ("艾尔登法环", "ELDEN RING"), ("空洞骑士", "Hollow Knight"), ("哈迪斯", "Hades"),
    ("黑神话", "Black Myth: Wukong"), ("黑神话悟空", "Black Myth: Wukong"), ("只狼", "Sekiro™: Shadows Die Twice - GOTY Edition"),
    ("巫师3", "The Witcher 3: Wild Hunt — Remastered"), ("2077", "Cyberpunk 2077"), ("赛博朋克2077", "Cyberpunk 2077"),
    ("大镖客2", "Red Dead Redemption 2"), ("荒野大镖客2", "Red Dead Redemption 2"), ("GTA5", "Grand Theft Auto V Legacy"),
    ("CS2", "Counter-Strike 2"), ("吃鸡", "PUBG: BATTLEGROUNDS"), ("泰拉瑞亚", "Terraria"), ("饥荒", "Don't Starve"), ("饥荒联机版", "Don't Starve Together"),
    ("杀戮尖塔", "Slay the Spire"), ("怪猎世界", "Monster Hunter: World"), ("怪物猎人崛起", "MONSTER HUNTER RISE"),
    ("博德之门3", "Baldur's Gate 3"), ("BG3", "Baldur's Gate 3"), ("鬼泣5", "Devil May Cry 5"), ("死亡细胞", "Dead Cells"),
    ("茶杯头", "Cuphead"), ("蔚蓝", "Celeste"), ("胡闹厨房2", "Overcooked! 2"), ("糖豆人", "Fall Guys"),
    ("雨中冒险2", "Risk of Rain 2"), ("以撒", "The Binding of Isaac: Rebirth"), ("无人深空", "No Man's Sky"),
    ("幻兽帕鲁", "Palworld"), ("英灵神殿", "Valheim"), ("森林之子", "Sons Of The Forest"), ("群星", "Stellaris"),
    ("钢铁雄心4", "Hearts of Iron IV"), ("钢4", "Hearts of Iron IV"), ("十字军之王3", "Crusader Kings III"),
    ("欧陆风云4", "Europa Universalis IV"), ("骑砍2", "Mount & Blade II: Bannerlord"), ("环世界", "RimWorld"),
    ("缺氧", "Oxygen Not Included"), ("异星工厂", "Factorio"), ("戴森球计划", "Dyson Sphere Program"),
    ("传送门2", "Portal 2"), ("求生之路2", "Left 4 Dead 2"), ("永劫无间", "NARAKA: BLADEPOINT"),
    ("P5R", "Persona 5 Royal"), ("八方旅人", "OCTOPATH TRAVELER™"), ("双点医院", "Two Point Hospital"),
    ("全战三国", "Total War: THREE KINGDOMS"), ("Hades2", "Hades II"), ("哈迪斯2", "Hades II"),
]


def norm(s):
    s = unicodedata.normalize("NFKC", str(s)).lower()
    s = re.sub(r"[®™©]", "", s)
    return re.sub(r"[^0-9a-z㐀-鿿぀-ヿ]", "", s)


def load_cached():
    """All cached replies: (appids asked, reply). Older files hold only the reply, so asked = its keys."""
    asked, replies = set(), []
    for f in sorted(CACHE.glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        rep = d["reply"] if "reply" in d else d
        asked |= {int(a) for a in d.get("asked", rep)}
        replies.append(rep)
    return asked, replies


def ask_llm(client, model, rows, path):
    lines = "\n".join(f"{a} | {n} | {z or ''}" for a, n, z in rows)
    for attempt in range(3):
        try:
            r = client.chat.completions.create(model=model, temperature=0, messages=[
                {"role": "system", "content": PROMPT}, {"role": "user", "content": lines}])
            raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", r.choices[0].message.content.strip())
            out = {str(k): [str(x) for x in v][:6] for k, v in json.loads(raw).items() if isinstance(v, list)}
            path.write_text(json.dumps({"asked": [int(r[0]) for r in rows], "reply": out}, ensure_ascii=False),
                            encoding="utf-8")
            return out
        except Exception as e:  # malformed JSON or relay error: retry
            err = e
            time.sleep(3 * (attempt + 1))
    print(f"  batch {path.name} failed: {str(err)[:120]}", flush=True)
    return {}


def build():
    from openai import OpenAI
    g = pd.read_parquet(PROC / "games.parquet", columns=["appid", "name", "name_zh", "review_count"])
    env = load_env(ROOT / ".env")
    client = OpenAI(base_url=env["LLM_BASE_URL"], api_key=env["LLM_API_KEY"])
    CACHE.mkdir(parents=True, exist_ok=True)
    asked, replies = load_cached()
    rows = [r for r in g[["appid", "name", "name_zh"]].itertuples(index=False, name=None) if r[0] not in asked]
    batches = [rows[i:i + BATCH] for i in range(0, len(rows), BATCH)]
    t0 = time.time()
    with ThreadPoolExecutor(WORKERS) as ex:
        replies += list(ex.map(lambda b: ask_llm(client, env["LLM_MODEL"], b, CACHE / f"games_{b[0][0]}.json"), batches))
    print(f"LLM: {len(asked):,} games already asked; {len(rows):,} new in {len(batches)} batches ({time.time() - t0:.0f}s)")

    recs = [{"alias": norm(n), "appid": a, "source": "store_en"} for a, n in zip(g["appid"], g["name"])]
    recs += [{"alias": norm(z), "appid": a, "source": "store_zh"} for a, z in zip(g["appid"], g["name_zh"]) if z]
    valid = set(g["appid"])
    for rep in replies:
        for a, names in rep.items():
            if a.isdigit() and int(a) in valid:
                recs += [{"alias": norm(n), "appid": int(a), "source": "llm"} for n in names]
    t = pd.DataFrame(recs)
    t = t[t["alias"].str.len() > 0].drop_duplicates(["alias", "appid"])
    store = t[t["source"] != "llm"].groupby("alias")["appid"].agg(set).to_dict()
    clash = [s == "llm" and al in store and a not in store[al] for al, a, s in t.itertuples(index=False, name=None)]
    t = t[~pd.Series(clash, index=t.index)]
    t.to_parquet(OUT, index=False)
    multi = t.groupby("alias")["appid"].nunique()
    print(f"wrote {OUT}: {len(t):,} rows, {t['alias'].nunique():,} aliases, {t['appid'].nunique():,} games; "
          f"by source {t['source'].value_counts().to_dict()}; dropped {sum(clash)} LLM aliases equal to another game's "
          f"store name; aliases pointing to > 1 game: {(multi > 1).sum():,}")


class Resolver:
    def __init__(self):
        self.t = pd.read_parquet(OUT)
        self.reviews = pd.read_parquet(PROC / "games.parquet", columns=["appid", "review_count"]).set_index("appid")["review_count"]
        self.by_alias = self.t.groupby("alias")["appid"].agg(list).to_dict()

    def resolve(self, text):
        """Exact normalised alias; several games -> the most reviewed. Returns (appid or None, candidates)."""
        cands = self.by_alias.get(norm(text), [])
        if not cands:
            return None, []
        cands = sorted(set(cands), key=lambda a: -self.reviews.get(a, 0))
        return cands[0], cands


def test():
    r = Resolver()
    g = pd.read_parquet(PROC / "games.parquet", columns=["appid", "name"])
    by_name = dict(zip(g["name"], g["appid"]))
    ok = 0
    for typed, want_name in TEST:
        want = by_name.get(want_name)
        got, cands = r.resolve(typed)
        hit = want is not None and got == want
        ok += hit
        if not hit:
            print(f"  MISS {typed!r}: want {want_name} ({want}), got "
                  f"{g.set_index('appid')['name'].get(got) if got else None} from {len(cands)} candidates")
    print(f"{ok}/{len(TEST)} resolved to the intended game")


if __name__ == "__main__":
    test() if "test" in sys.argv else build()
