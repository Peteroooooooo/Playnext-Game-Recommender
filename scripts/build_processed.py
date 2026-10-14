"""Turn raw pulls into normalised tables under data/processed/ (parquet).

Tables: games, tags, game_tags, game_categories, descriptions, prices,
player_counts, companies, series, similar, time_to_beat.
Prints a coverage summary at the end.
Usage: python scripts/build_processed.py
"""
import json
import re
from datetime import datetime, timezone

import pandas as pd

from build_aliases import norm
from check_keys import ROOT
from desc_player_count import clean, extract_max_players

RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "processed"
CORE_TAG_RATIO = 0.5
PC_PLATFORM = 6
STORE_TYPES = {1: "试玩版", 6: "软件", 14: "旧版跳转页 / 广告页"}  # Steam store item types; 0 = game
NOT_STANDALONE = re.compile(r"(?i)dedicated server|test server|free trial")
PROLOGUE = re.compile(r"(?i)[\s:：\-–]*\b(christmas\s+)?prologue\b(\s*\(\d{4}\))?")
# Steam's schinese tag list returns the English name for these; 4X, 2D, 3D, 2.5D, TrackIR, LGBTQ+ stay as they are
TAG_ZH_FILL = {"Dog": "狗", "Unforgiving": "严苛", "Rail Shooter": "轨道射击", "Kids": "儿童", "Assassin": "刺客",
               "Blood": "血液", "Dwarf": "矮人", "Boss Rush": "头目连战", "Conversation": "对话", "Pool": "台球",
               "Fox": "狐狸", "Combat Flight Simulator": "空战模拟", "Sexual Themes": "性主题", "Coding": "编程",
               "Jet": "喷气机", "Elf": "精灵", "ATV": "全地形车", "Snooker": "斯诺克", "Clicker": "点击"}
CAT_GROUPS = {"supported_player_categoryids": "player", "feature_categoryids": "feature",
              "controller_categoryids": "controller"}


def load_pass(name):
    out = {}
    for f in sorted((RAW / "steam_items").glob(f"{name}_*.json")):
        for it in json.loads(f.read_text(encoding="utf-8")):
            if it.get("appid"):
                out[it["appid"]] = it
    return out


def cents(x):
    return None if x in (None, "") else int(x) / 100


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    cn, zh, us = load_pass("cn_en"), load_pass("cn_zh"), load_pass("us")
    us_en, us_zh = load_pass("us_en"), load_pass("us_zh")
    tags_en = {t["tagid"]: t["name"] for t in json.loads((RAW / "steam_tags_english.json").read_text(encoding="utf-8"))}
    tags_zh = {t["tagid"]: t["name"] for t in json.loads((RAW / "steam_tags_schinese.json").read_text(encoding="utf-8"))}
    tags_zh.update({k: TAG_ZH_FILL[v] for k, v in tags_en.items() if v in TAG_ZH_FILL and tags_zh.get(k) in (None, v)})
    mmo_tag = next(k for k, v in tags_en.items() if v.lower() == "massively multiplayer")

    games, gtags, gcats, descs, prices, excluded = [], [], [], [], [], []
    for a, it in cn.items():
        cn_blocked = bool(it.get("unvailable_for_country_restriction"))
        z = zh.get(a, {})
        if cn_blocked:  # not sold in CN: take store data from the US store instead
            it, z = us_en.get(a, it), us_zh.get(a, {})
        if it.get("type") != 0:
            excluded.append({"appid": a, "name": it.get("name"), "type": it.get("type"),
                             "reason": STORE_TYPES.get(it.get("type"), "两个区的商店都没有数据")})
            continue
        bi = it.get("basic_info") or {}
        rv = (it.get("reviews") or {}).get("summary_filtered") or {}
        pf = it.get("platforms") or {}
        rating = it.get("game_rating") or {}
        ts = (it.get("release") or {}).get("steam_release_date")
        name_zh = z.get("name")
        games.append({
            "appid": a, "name": it.get("name"), "name_zh": name_zh if name_zh and name_zh != it.get("name") else None,
            "cn_blocked": cn_blocked, "store_region": "US" if cn_blocked else "CN",
            "release_year": datetime.fromtimestamp(ts, timezone.utc).year if ts else None,
            "review_count": rv.get("review_count"), "pct_positive": rv.get("percent_positive"),
            "is_free": bool(it.get("is_free")),
            "windows": bool(pf.get("windows")), "mac": bool(pf.get("mac")), "linux": bool(pf.get("steamos_linux")),
            "deck_compat": pf.get("steam_deck_compat_category"),
            "developers": [d["name"] for d in bi.get("developers", [])],
            "publishers": [p["name"] for p in bi.get("publishers", [])],
            "content_descriptor_ids": it.get("content_descriptorids", []),
            "required_age": rating.get("required_age"), "rating": rating.get("rating"),
            "rating_descriptors": rating.get("descriptors", []),
            "language_codes": [l["elanguage"] for l in it.get("supported_languages", []) if l.get("supported")],
        })
        tl = it.get("tags", [])
        top = max((t["weight"] for t in tl), default=0)
        for t in tl:
            gtags.append({"appid": a, "tagid": t["tagid"], "votes": t["weight"],
                          "weight": t["weight"] / top if top else 0,
                          "is_core": top > 0 and t["weight"] / top >= CORE_TAG_RATIO})
        for key, grp in CAT_GROUPS.items():
            for c in (it.get("categories") or {}).get(key, []):
                gcats.append({"appid": a, "category_id": c, "group": grp})
        descs.append({"appid": a, "lang": "en", "short": bi.get("short_description", ""),
                      "full": clean(it.get("full_description_bbcode", ""))})
        descs.append({"appid": a, "lang": "zh", "short": (z.get("basic_info") or {}).get("short_description", ""),
                      "full": clean(z.get("full_description_bbcode", ""))})
        for region, src in (("CN", cn[a]), ("US", us.get(a, {}))):
            bp = src.get("best_purchase_option") or {}
            prices.append({"appid": a, "region": region,
                           "final": cents(bp.get("final_price_in_cents")),
                           "original": cents(bp.get("original_price_in_cents")),
                           "discount_pct": bp.get("discount_pct", 0), "is_free": bool(it.get("is_free"))})

    games = pd.DataFrame(games)
    # Steam files these as games, but they are a server tool, a test build, a trial, or a prologue whose full game
    # is also in the library
    full = set(games["name"].map(norm))
    drop = {}
    for a, n in zip(games["appid"], games["name"]):
        if NOT_STANDALONE.search(n):
            drop[a] = "服务器 / 测试服 / 试用版"
        elif PROLOGUE.search(n) and norm(PROLOGUE.sub("", n)) in full:
            drop[a] = "序章（完整版也在库里）"
    excluded += [{"appid": a, "name": n, "type": 0, "reason": drop[a]} for a, n in zip(games["appid"], games["name"]) if a in drop]
    games = games[~games["appid"].isin(drop)].reset_index(drop=True)
    keep = set(games["appid"])
    gtags, gcats = [r for r in gtags if r["appid"] in keep], [r for r in gcats if r["appid"] in keep]
    descs, prices = [r for r in descs if r["appid"] in keep], [r for r in prices if r["appid"] in keep]
    gtags = pd.DataFrame(gtags)
    excluded = pd.DataFrame(excluded)
    excluded.to_parquet(OUT / "excluded_apps.parquet", index=False)
    print(f"excluded {len(excluded)}: {excluded['reason'].value_counts().to_dict()}")
    pd.DataFrame([{"tagid": k, "name_en": v, "name_zh": tags_zh.get(k)} for k, v in tags_en.items()]).to_parquet(OUT / "tags.parquet", index=False)
    pd.DataFrame(gcats).to_parquet(OUT / "game_categories.parquet", index=False)
    pd.DataFrame(descs).to_parquet(OUT / "descriptions.parquet", index=False)

    # ITAD Steam-store lows
    id_map = json.loads((RAW / "itad" / "id_map.json").read_text(encoding="utf-8"))
    itad2app = {}
    for app, gid in id_map.items():
        itad2app.setdefault(gid, []).append(int(app))
    lows = {}
    for region in ("CN", "US"):
        for r in json.loads((RAW / "itad" / f"low_{region}.json").read_text(encoding="utf-8"))["rows"]:
            steam = [l for l in r.get("lows", []) if l["shop"]["id"] == 61]
            if steam:
                for app in itad2app.get(r["id"], []):
                    lows[(app, region)] = (steam[0]["price"]["amount"], steam[0]["price"]["currency"], steam[0]["timestamp"])
    prices = pd.DataFrame(prices)
    prices["currency"] = prices["region"].map({"CN": "CNY", "US": "USD"})
    prices["steam_low"] = [lows.get((a, r), (None,))[0] for a, r in zip(prices["appid"], prices["region"])]
    prices["steam_low_time"] = [lows.get((a, r), (None, None, None))[2] for a, r in zip(prices["appid"], prices["region"])]
    prices.to_parquet(OUT / "prices.parquet", index=False)

    # IGDB
    ext = json.loads((RAW / "igdb" / "external_games.json").read_text(encoding="utf-8"))
    app2g = {}
    keep = set(games["appid"])
    for r in ext:
        if int(r["uid"]) in keep:
            app2g.setdefault(int(r["uid"]), r["game"])
    g2app = {}
    for app, g in app2g.items():
        g2app.setdefault(g, []).append(app)
    games["igdb_id"] = games["appid"].map(app2g)

    igames = json.loads((RAW / "igdb" / "games.json").read_text(encoding="utf-8"))
    comp, series, similar = [], [], []
    for g in igames:
        for app in g2app.get(g["id"], []):
            for ic in g.get("involved_companies", []):
                comp.append({"appid": app, "company_id": ic["company"]["id"], "company": ic["company"]["name"],
                             "developer": ic.get("developer", False), "publisher": ic.get("publisher", False)})
            for kind in ("collections", "franchises"):
                for s in g.get(kind, []):
                    series.append({"appid": app, "kind": kind[:-1], "series_id": s["id"], "name": s["name"]})
            if g.get("franchise"):
                series.append({"appid": app, "kind": "franchise", "series_id": g["franchise"]["id"], "name": g["franchise"]["name"]})
            for sg in g.get("similar_games", []):
                for app2 in g2app.get(sg, []):
                    similar.append({"appid": app, "similar_appid": app2})
    pd.DataFrame(comp).to_parquet(OUT / "companies.parquet", index=False)
    pd.DataFrame(series).drop_duplicates().to_parquet(OUT / "series.parquet", index=False)
    pd.DataFrame(similar).drop_duplicates().to_parquet(OUT / "similar.parquet", index=False)

    ttb = []
    for r in json.loads((RAW / "igdb" / "time_to_beat.json").read_text(encoding="utf-8")):
        for app in g2app.get(r["game_id"], []):
            ttb.append({"appid": app, **{k: (r.get(k) or 0) / 3600 or None for k in ("hastily", "normally", "completely")},
                        "votes": r.get("count")})
    pd.DataFrame(ttb).to_parquet(OUT / "time_to_beat.parquet", index=False)

    # player counts: IGDB (PC row preferred, else max over platforms) + description + MMO tag
    modes = {}
    for m in json.loads((RAW / "igdb" / "multiplayer_modes.json").read_text(encoding="utf-8")):
        modes.setdefault(m["game"], []).append(m)
    fields = ["onlinecoopmax", "onlinemax", "offlinecoopmax", "offlinemax"]
    flags = ["splitscreen", "splitscreenonline", "lancoop", "dropin"]
    cat_sets = pd.DataFrame(gcats).groupby("appid")["category_id"].agg(set).to_dict()
    tag_sets = gtags.groupby("appid")["tagid"].agg(set).to_dict()
    desc_en = {d["appid"]: d["short"] + " " + d["full"] for d in descs if d["lang"] == "en"}
    pcs = []
    for a in games["appid"]:
        rows = modes.get(app2g.get(a), [])
        pc = [r for r in rows if r.get("platform") == PC_PLATFORM]
        use = pc or rows
        rec = {"appid": a, "igdb_source": "pc" if pc else ("other_platform" if rows else None)}
        for f in fields:
            vals = [r.get(f) or 0 for r in use]
            rec[f] = max(vals) if vals and max(vals) > 0 else None
        for f in flags:
            rec[f] = any(r.get(f) for r in use) if use else None
        rec["desc_max_players"] = extract_max_players(desc_en.get(a, ""))
        rec["mmo_tag"] = mmo_tag in tag_sets.get(a, set())
        rec["has_mp_category"] = bool(cat_sets.get(a, set()) & {36, 37, 38, 39, 47, 48})
        pcs.append(rec)
    pcs = pd.DataFrame(pcs)
    pcs.to_parquet(OUT / "player_counts.parquet", index=False)
    games.to_parquet(OUT / "games.parquet", index=False)
    gtags.to_parquet(OUT / "game_tags.parquet", index=False)

    # summary
    n = len(games)
    pct = lambda k: f"{k:,} ({100 * k / n:.0f}%)"
    mp = pcs[pcs["has_mp_category"]]
    igdb_any = mp[fields].notna().any(axis=1)
    filled = igdb_any | mp["desc_max_players"].notna() | mp["mmo_tag"]
    cn_p = prices[prices["region"] == "CN"]
    print(f"games {n:,}; with tags {pct(gtags['appid'].nunique())}; with en full description "
          f"{pct(sum(1 for d in descs if d['lang'] == 'en' and len(d['full']) > 200))}; zh {pct(sum(1 for d in descs if d['lang'] == 'zh' and len(d['full']) > 200))}")
    print(f"CN price {pct(cn_p['final'].notna().sum() + cn_p['is_free'].sum())} (free {cn_p['is_free'].sum():,}); "
          f"CN Steam low {pct(cn_p['steam_low'].notna().sum())}")
    print(f"IGDB mapped {pct(games['igdb_id'].notna().sum())}; developer {pct(pd.DataFrame(comp).query('developer')['appid'].nunique())}; "
          f"series {pct(pd.DataFrame(series)['appid'].nunique())}; similar (in core) {pct(pd.DataFrame(similar)['appid'].nunique())}; "
          f"time-to-beat {pct(pd.DataFrame(ttb)['appid'].nunique())}")
    print(f"multiplayer games {len(mp):,}: IGDB count {igdb_any.sum():,} ({100 * igdb_any.mean():.0f}%); "
          f"after description + MMO fill {filled.sum():,} ({100 * filled.mean():.0f}%)")


if __name__ == "__main__":
    main()
