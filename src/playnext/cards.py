"""Step 5: evidence cards from deterministic facts (design 4.3 / 4.4 card examples); the LLM only writes a short
reason, which must not contain numbers or game names absent from the facts (else one retry, then a template)."""
import json
import re

import numpy as np
import pandas as pd

from . import config as C
from .kb import KB
from .llm import chat_json
from .rules import PASS, FilterResult
from .spec import SessionSpec

SETUP_ZH = {"online": "在线组队", "local": "本地同屏", "remote": "远程同乐", "hybrid": "混合开局"}
CONTROLLER = {28: "完全支持控制器", 18: "部分支持控制器"}
STEPS = {
    "online": ["房主开启游戏并建房", "通过 Steam 好友邀请其余成员", "房间与入局细节以游戏说明为准"],
    "local": ["一台电脑连接显示器或电视", "按人数准备手柄（同屏多人通常每人一个）", "在游戏内选择本地 / 分屏模式，细节以游戏说明为准"],
    "remote": ["主机在 Steam 好友列表右键来宾，选“远程畅玩邀请”", "来宾无需购买，用 Steam 客户端或 Steam Link 加入",
               "网络与延迟以实际为准"],
    "hybrid": ["同屏的成员在同一台电脑上加入", "其余成员各自在家，经 Steam 好友邀请在线加入", "混合开局细节以游戏说明为准"],
}


def _money(v, region):
    if v is None:
        return None
    return (f"¥{v:g}" if region == "CN" else f"${v:g}")


def price_facts(prices, appid, region):
    p = prices.get(appid, region)
    if p is None:
        return {"text": "价格未知", "region": region}
    if p["is_free"]:
        return {"text": "免费", "free": True, "region": region, "source": p["source"], "as_of": p["as_of"]}
    out = {"region": region, "final": p["final"], "low": p["low"], "low_time": p["low_time"],
           "discount_pct": p["discount_pct"], "source": p["source"], "as_of": p["as_of"]}
    parts = []
    if p["final"] is not None:
        parts.append(f"现价 {_money(p['final'], region)}" + (f"（-{p['discount_pct']}%）" if p["discount_pct"] else ""))
    else:
        parts.append(f"{region} 区现价未知")
    if p["low"]:
        parts.append(f"史低 {_money(p['low'], region)}" + (f"（{p['low_time'][:7]}）" if p["low_time"] else ""))
        if p["final"] is not None:
            gap = p["final"] / p["low"] - 1
            parts.append("已在史低" if gap <= C.NEAR_LOW - 1 else f"距史低 +{gap * 100:.0f}%")
    else:
        parts.append("史低未知")
    out["text"] = " ／ ".join(parts)
    out["note"] = "实时价格" if p["source"] == "live" else f"价格取于 {p['as_of']}（每日快照）"
    return out


def tag_diff(kb: KB, a, anchor, k=3):
    """'差在哪': tags whose weight differs most between candidate and anchor (from the tag weights, not opinion)."""
    wa = {t: kb.tag_weight.get((a, t), 0) for t in kb.tagset.get(a, set()) | kb.tagset.get(anchor, set())}
    wb = {t: kb.tag_weight.get((anchor, t), 0) for t in wa}
    more = sorted((t for t in wa if wa[t] - wb[t] >= 0.4), key=lambda t: -(wa[t] - wb[t]))[:k]
    less = sorted((t for t in wa if wb[t] - wa[t] >= 0.4), key=lambda t: -(wb[t] - wa[t]))[:k]
    return [kb.tag_zh[t] for t in more], [kb.tag_zh[t] for t in less]


def best_sentence(kb: KB, appid, words):
    """A description sentence that shares the most characters / words with the preference text (evidence quote)."""
    if not words:
        return None
    d = kb.descriptions.get((appid, "zh")) or kb.descriptions.get((appid, "en"))
    if not d:
        return None
    sents = [s.strip() for s in re.split(r"(?<=[。！？!?.])\s*", d) if 8 <= len(s.strip()) <= 160]
    if not sents:
        return None
    toks = set(re.findall(r"[a-zA-Z]{4,}", words.lower())) | set(re.findall(r"[㐀-鿿]{2}", words))
    if not toks:
        return None
    score = [sum(t in s.lower() for t in toks) for s in sents]
    i = int(np.argmax(score))
    return sents[i] if score[i] > 0 else None


def build_card(kb: KB, spec: SessionSpec, i, rel, ranked, details, fr: FilterResult, prices, step=None):
    a = int(kb.appids[i])
    g = kb.games.loc[a]
    tgt = details.get("me") or details.get("shared") or next((v for k, v in details.items() if isinstance(k, int)), None)
    taste, scored = tgt if tgt else (None, None)
    ev = scored.evidence if scored else {}
    anchors = ev.get("anchors", [])
    card = {"appid": a, "name": kb.display_name(a), "name_en": kb.name[a],
            "year": None if pd.isna(g["release_year"]) else int(g["release_year"]),
            "developer": (kb.dev_name.get(a) or list(g["developers"]) or [None])[0],
            "store_url": f"https://store.steampowered.com/app/{a}/",
            "header": f"https://cdn.akamai.steamstatic.com/steam/apps/{a}/header.jpg",
            "relevance": round(float(rel[i]), 3)}
    like = {}
    if anchors:
        hit = anchors[int(ev["tag_hit"][i])]
        shared = [kb.tag_zh[t] for t in kb.core.get(a, []) if t in set(kb.core.get(hit, []))][:4]
        like = {"anchor": kb.display_name(hit), "shared_core_tags": shared}
        more, less = tag_diff(kb, a, hit)
        card["diff"] = {"more": more, "less": less, "anchor": kb.display_name(hit)}
        k = int(ev["co_hit"][i])
        co_anchor = anchors[k]
        nb = kb.colike_by_app.get(co_anchor)
        if nb is not None:
            row = nb[nb["neighbor"] == a]
            if len(row):
                r = row.iloc[0]
                rank = int((nb["sim"] > r["sim"]).sum()) + 1
                card["colike"] = {"anchor": kb.display_name(co_anchor), "co_count": int(r["co_count"]), "rank": rank,
                                  "text": f"{int(r['co_count']):,} 名玩家同时推荐了《{kb.display_name(co_anchor)}》和本作"
                                          f"（在《{kb.display_name(co_anchor)}》的同好邻居中排第 {rank}）"}
        lin = []
        if a in ev.get("same_dev", ()):
            devs = [kb.dev_name.get(x, ["?"])[0] for x in anchors if set(kb.dev_of.get(x, ())) & set(kb.dev_of.get(a, ()))]
            src = next((x for x in anchors if set(kb.dev_of.get(x, ())) & set(kb.dev_of.get(a, ()))), None)
            if src:
                lin.append(f"《{kb.display_name(src)}》 → {devs[0]} → 《{kb.display_name(a)}》（同工作室，IGDB）")
        if a in ev.get("same_ser", ()):
            for x in anchors:
                common = kb.series_all.get(x, set()) & kb.series_all.get(a, set())
                if common:
                    key = sorted(common)[0]
                    lin.append(f"《{kb.display_name(x)}》 → {kb.series_name.get(key)} → 《{kb.display_name(a)}》（同系列，IGDB）")
                    break
        if a in ev.get("igdb_sim", ()):
            src = next((x for x in anchors if a in kb.similar_of.get(x, set())), None)
            if src:
                lin.append(f"IGDB 把本作列为《{kb.display_name(src)}》的相似游戏")
        if lin:
            card["lineage"] = lin
        if ev.get("lib_bonus") is not None and ev["lib_bonus"][i] > 0:
            card["library_hint"] = f"也像你常玩的《{kb.display_name(ev['lib_anchor'][i])}》"
    elif kb.core.get(a):
        like = {"anchor": None, "shared_core_tags": [kb.tag_zh[t] for t in kb.core.get(a, [])][:4]}
    if ev.get("feel_tags"):
        want, avoid = ev["feel_tags"]
        mine = kb.tagset.get(a, set())
        like["feel_hits"] = [kb.tag_zh[t] for t in want if t in mine]
        like["feel_bad"] = [kb.tag_zh[t] for t in avoid if t in mine]
    if taste and taste.preference_text:
        like["quote"] = best_sentence(kb, a, taste.preference_text)
    card["like"] = like
    pct = None if pd.isna(g["pct_positive"]) else int(g["pct_positive"])
    card["rating"] = {"pct_positive": pct, "reviews": int(kb.review_count[i]), "smoothed": round(float(kb.quality[i]), 3),
                      "text": (f"Steam 好评率 {pct}%（{int(kb.review_count[i]):,} 篇评测）" if pct is not None else "暂无好评率"),
                      "below_floor": not bool(kb.rating_ok[i])}
    region = spec.members[0].region
    card["price"] = price_facts(prices, a, region)
    owned_by = [m.name for m in spec.members if m.owns(a)]
    if spec.party_size == 1:
        m = spec.members[0]
        card["library"] = ("已在你的 Steam 库里，Steam 上没有游玩记录" if m.library and a in m.library.owned
                           else ("已拥有" if a in m.owned_extra else "未拥有"))
    if kb.time_to_beat is not None and a in kb.time_to_beat.index:
        t = kb.time_to_beat.loc[a, "normally"]
        if t == t:
            card["time_to_beat"] = f"通关约 {t:.0f} 小时（IGDB）"
    folded = ranked.folded.get(i, [])
    if folded:
        card["same_series_folded"] = [kb.display_name(int(kb.appids[j])) for j in folded]
    if spec.party_size > 1:
        card["setup"] = setup_card(kb, spec, fr, a, owned_by)
    if step:
        card["rank_step"] = step
    if fr.unknown_why(i, a):
        card["unknown"] = fr.unknown_why(i, a)
    return card


def setup_card(kb, spec, fr, a, owned_by):
    kind = fr.best_setup.get(a)
    if not kind:
        return None
    s = fr.setups[kind]
    mx = s.max_players.get(a)
    cats = kb.categories.get(a, set())
    plan = s.plan.get(a, {})
    out = {"kind": kind, "kind_zh": SETUP_ZH[kind], "players": spec.party_size,
           "max_players": None if not mx or mx[0] is None else mx[0], "max_source": mx[1] if mx else None,
           "steps": STEPS[kind], "controller": next((v for k, v in CONTROLLER.items() if k in cats), None)}
    members = spec.members
    if plan.get("rule") == "free":
        out["purchase"] = "免费游戏，每人新增 ¥0"
    elif plan.get("rule") == "host_only":
        host = plan.get("host")
        if plan["new_copies"] == 0:
            out["purchase"] = f"仅主机需拥有：{members[host].name}已有，新增 ¥0；其余成员作为来宾加入"
        else:
            out["purchase"] = (f"仅主机需拥有：{members[host].name}购买（{_money(plan['per_member'][host], members[host].region)}）"
                               "并当主机，其余成员作为来宾加入")
    elif plan:
        buyers = plan["buyers"]
        own = "、".join(owned_by) + "已有；" if owned_by else ""
        if buyers:
            pays = "、".join(f"{members[b].name} {_money(plan['per_member'][b], members[b].region)}" for b in buyers)
            total = "；".join(f"{r} 区合计 {_money(v, r)}" for r, v in plan["cost"].items())
            out["purchase"] = f"{own}需购买：{pays}（{total}）" + ("，每台机器一份" if plan["rule"] == "per_machine" else "")
        else:
            out["purchase"] = f"{own}无需新购"
    if mx and mx[0]:
        out["mode_text"] = f"{SETUP_ZH[kind]} · 最多 {mx[0]} 人（{mx[1]}）"
    else:
        out["mode_text"] = f"{SETUP_ZH[kind]} · {mx[1] if mx else '人数上限未收录'}"
    if re.search(r"(?i)friend'?s pass|好友通行证", kb.descriptions.get((a, "en"), "") + kb.descriptions.get((a, "zh"), "")):
        out["friends_pass"] = "介绍提到好友通行证（Friend's Pass），以商店页为准"
    out["note"] = "私人房间、入局方式、手柄分配等细节以游戏说明为准"
    return out


REASON_SYS = """You write a short Chinese recommendation reason (60-120 Chinese characters) for each game card, using ONLY the facts given. Do not add numbers, game names, studios or claims that are not in the facts. No purchase advice ("值得买" etc.). Return JSON {"<appid>": "<reason>", ...}."""


def _fact_text(card):
    return json.dumps({k: card.get(k) for k in ("name", "like", "diff", "colike", "lineage", "rating", "time_to_beat",
                                                "setup", "library_hint")}, ensure_ascii=False)


def _consistent(reason, card):
    facts = _fact_text(card)
    for num in re.findall(r"\d+(?:\.\d+)?", reason):
        if num not in facts:
            return False
    for name in re.findall(r"《([^》]+)》", reason):
        if name not in facts:
            return False
    return True


def template_reason(card):
    parts = []
    like = card.get("like", {})
    if like.get("anchor") and like.get("shared_core_tags"):
        parts.append(f"和《{like['anchor']}》一样以{'、'.join(like['shared_core_tags'][:3])}为核心")
    elif like.get("shared_core_tags"):
        parts.append(f"核心玩法是{'、'.join(like['shared_core_tags'][:3])}")
    if like.get("feel_hits"):
        parts.append(f"玩家给它打了{'、'.join(like['feel_hits'])}的标签")
    if card.get("colike"):
        parts.append(card["colike"]["text"])
    if card.get("lineage"):
        parts.append(card["lineage"][0])
    return "；".join(parts) + "。" if parts else ""


def write_reasons(cards, llm, request_text=""):
    """One batched LLM call for all cards; failed or inconsistent reasons fall back to the template."""
    for c in cards:
        c["reason"], c["reason_source"] = template_reason(c), "template"
    if llm is None or not cards:
        return
    facts = {str(c["appid"]): json.loads(_fact_text(c)) for c in cards}
    user = f"玩家的要求：{request_text}\n卡片事实：{json.dumps(facts, ensure_ascii=False)}"
    for attempt in range(2):
        try:
            out = chat_json(llm, REASON_SYS, user, "reasons")
        except Exception:
            return
        bad = 0
        for c in cards:
            r = out.get(str(c["appid"])) if isinstance(out, dict) else None
            if c["reason_source"] == "llm":
                continue
            if isinstance(r, str) and r.strip() and _consistent(r, c):
                c["reason"], c["reason_source"] = r.strip(), "llm"
            else:
                bad += 1
        if not bad:
            return
