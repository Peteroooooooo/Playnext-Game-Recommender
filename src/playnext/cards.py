"""Step 5: evidence cards from deterministic facts (design 4.3 / 4.4 card examples); the LLM only writes a short
reason, which must not contain numbers or game names absent from the facts (else one retry, then a template)."""
import json
import re

import numpy as np
import pandas as pd

from . import config as C
from .i18n import L, lang, sep
from .kb import KB
from .llm import chat_json
from .rules import PASS, FilterResult, money, setup_names
from .spec import SessionSpec


def controller_names():
    return {28: L("完全支持控制器", "Full controller support"), 18: L("部分支持控制器", "Partial controller support")}


def setup_steps():
    return {
        "online": [L("房主开启游戏并建房", "The host starts the game and opens a lobby"),
                   L("通过 Steam 好友邀请其余成员", "Invite everyone else through Steam friends"),
                   L("房间与入局细节以游戏说明为准", "For lobby and joining details, follow the game's own instructions")],
        "local": [L("一台电脑连接显示器或电视", "Connect one PC to a monitor or TV"),
                  L("按人数准备手柄（同屏多人通常每人一个）",
                    "Have enough controllers for everyone (same-screen play usually needs one each)"),
                  L("在游戏内选择本地 / 分屏模式，细节以游戏说明为准",
                    "Pick the local / split-screen mode in the game; follow the game's instructions for details")],
        "remote": [L("主机在 Steam 好友列表右键来宾，选“远程畅玩邀请”",
                     "The host right-clicks each guest in the Steam friends list and picks \"Invite to Remote Play Together\""),
                   L("来宾无需购买，用 Steam 客户端或 Steam Link 加入",
                     "Guests do not need to buy the game; they join with the Steam client or Steam Link"),
                   L("网络与延迟以实际为准", "Network quality and latency depend on your connection")],
        "hybrid": [L("同屏的成员在同一台电脑上加入", "Players sharing a screen join on the same PC"),
                   L("其余成员各自在家，经 Steam 好友邀请在线加入",
                     "Everyone else joins online from home through a Steam friends invite"),
                   L("混合开局细节以游戏说明为准", "For mixed local + online details, follow the game's instructions")],
    }


def _q(name):
    """A game name in running text: 《name》 in Chinese, "name" in English."""
    return L(f"《{name}》", f"\"{name}\"")


_money = money


def price_facts(prices, appid, region):
    p = prices.get(appid, region)
    if p is None:
        return {"text": L("价格未知", "Price unknown"), "region": region}
    if p["is_free"]:
        return {"text": L("免费", "Free"), "free": True, "region": region, "source": p["source"], "as_of": p["as_of"]}
    out = {"region": region, "final": p["final"], "low": p["low"], "low_time": p["low_time"],
           "discount_pct": p["discount_pct"], "source": p["source"], "as_of": p["as_of"]}
    parts = []
    if p["final"] is not None:
        now, pct = _money(p["final"], region), p["discount_pct"]
        parts.append(L(f"现价 {now}" + (f"（-{pct}%）" if pct else ""), f"Now {now}" + (f" (-{pct}%)" if pct else "")))
    else:
        parts.append(L(f"{region} 区现价未知", f"No current price in the {region} store"))
    if p["low"]:
        low, when = _money(p["low"], region), p["low_time"][:7] if p["low_time"] else None
        parts.append(L(f"史低 {low}" + (f"（{when}）" if when else ""), f"Record low {low}" + (f" ({when})" if when else "")))
        if p["final"] is not None:
            gap = p["final"] / p["low"] - 1
            out["near_low"] = bool(gap <= C.NEAR_LOW - 1)
            parts.append(L("已在史低", "At its record low") if out["near_low"]
                         else L(f"距史低 +{gap * 100:.0f}%", f"+{gap * 100:.0f}% above the record low"))
    else:
        parts.append(L("史低未知", "Record low unknown"))
    out["text"] = L(" ／ ", " / ").join(parts)
    out["note"] = L("实时价格", "Live price") if p["source"] == "live" else \
        L(f"价格取于 {p['as_of']}（每日快照）", f"Price as of {p['as_of']} (daily snapshot)")
    return out


def tag_diff(kb: KB, a, anchor, k=3):
    """'差在哪': tags whose weight differs most between candidate and anchor (from the tag weights, not opinion)."""
    wa = {t: kb.tag_weight.get((a, t), 0) for t in kb.tagset.get(a, set()) | kb.tagset.get(anchor, set())}
    wb = {t: kb.tag_weight.get((anchor, t), 0) for t in wa}
    more = sorted((t for t in wa if wa[t] - wb[t] >= 0.4), key=lambda t: -(wa[t] - wb[t]))[:k]
    less = sorted((t for t in wa if wb[t] - wa[t] >= 0.4), key=lambda t: -(wb[t] - wa[t]))[:k]
    return [kb.tag_name(t) for t in more], [kb.tag_name(t) for t in less]


def best_sentence(kb: KB, appid, words):
    """A description sentence that shares the most characters / words with the preference text (evidence quote)."""
    if not words:
        return None
    first, second = ("en", "zh") if lang() == "en" else ("zh", "en")
    d = kb.descriptions.get((appid, first)) or kb.descriptions.get((appid, second))
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
        shared = [kb.tag_name(t) for t in kb.core.get(a, []) if t in set(kb.core.get(hit, []))][:4]
        like = {"anchor": kb.display_name(hit), "shared_core_tags": shared}
        card["anchor_appid"] = int(anchors[int(ev["co_hit"][i])])
        more, less = tag_diff(kb, a, hit)
        card["diff"] = {"more": more, "less": less, "anchor": kb.display_name(hit)}
        k = int(ev["co_hit"][i])
        co_anchor = anchors[k]
        pair = kb.colike_pair(co_anchor, a)
        if pair is not None:
            (n, rank), co = pair, _q(kb.display_name(co_anchor))
            card["colike"] = {"anchor": kb.display_name(co_anchor), "co_count": n, "rank": rank,
                              "text": L(f"{n:,} 名玩家同时推荐了{co}和本作（在{co}的同好邻居中排第 {rank}）",
                                        f"{n:,} players recommended both {co} and this game "
                                        f"(#{rank} among the games fans of {co} also like)")}
        lin = []
        if a in ev.get("same_dev", ()):
            devs = [kb.dev_name.get(x, ["?"])[0] for x in anchors if set(kb.dev_of.get(x, ())) & set(kb.dev_of.get(a, ()))]
            src = next((x for x in anchors if set(kb.dev_of.get(x, ())) & set(kb.dev_of.get(a, ()))), None)
            if src:
                lin.append(f"{_q(kb.display_name(src))} → {devs[0]} → {_q(kb.display_name(a))}"
                           + L("（同工作室，IGDB）", " (same studio, IGDB)"))
        if a in ev.get("same_ser", ()):
            for x in anchors:
                common = kb.series_all.get(x, set()) & kb.series_all.get(a, set())
                if common:
                    key = sorted(common)[0]
                    lin.append(f"{_q(kb.display_name(x))} → {kb.series_name.get(key)} → {_q(kb.display_name(a))}"
                               + L("（同系列，IGDB）", " (same series, IGDB)"))
                    break
        if a in ev.get("igdb_sim", ()):
            src = next((x for x in anchors if a in kb.similar_of.get(x, set())), None)
            if src:
                lin.append(L(f"IGDB 把本作列为《{kb.display_name(src)}》的相似游戏",
                             f"IGDB lists this game as similar to \"{kb.display_name(src)}\""))
        if lin:
            card["lineage"] = lin
        if ev.get("lib_bonus") is not None and ev["lib_bonus"][i] > 0:
            nm = kb.display_name(ev["lib_anchor"][i])
            card["library_hint"] = L(f"也像你常玩的《{nm}》", f"Also close to \"{nm}\", which you play a lot")
    elif kb.core.get(a):
        like = {"anchor": None, "shared_core_tags": [kb.tag_name(t) for t in kb.core.get(a, [])][:4]}
    if ev.get("feel_tags"):
        want, avoid = ev["feel_tags"]
        mine = kb.tagset.get(a, set())
        like["feel_hits"] = [kb.tag_name(t) for t in want if t in mine]
        like["feel_bad"] = [kb.tag_name(t) for t in avoid if t in mine]
    if taste and taste.preference_text:
        like["quote"] = best_sentence(kb, a, taste.preference_text)
    card["like"] = like
    pct = None if pd.isna(g["pct_positive"]) else int(g["pct_positive"])
    card["rating"] = {"pct_positive": pct, "reviews": int(kb.review_count[i]), "smoothed": round(float(kb.quality[i]), 3),
                      "text": (L(f"Steam 好评率 {pct}%（{int(kb.review_count[i]):,} 篇评测）",
                                 f"{pct}% positive on Steam ({int(kb.review_count[i]):,} reviews)")
                               if pct is not None else L("暂无好评率", "No rating yet")),
                      "below_floor": not bool(kb.rating_ok[i])}
    region = spec.members[0].region
    card["price"] = price_facts(prices, a, region)
    owned_by = [m.name for m in spec.members if m.owns(a)]
    if spec.party_size == 1:
        m = spec.members[0]
        card["library"] = (L("已在你的 Steam 库里，Steam 上没有游玩记录",
                             "Already in your Steam library, with no playtime recorded on Steam")
                           if m.library and a in m.library.owned
                           else (L("已拥有", "Already owned") if a in m.owned_extra else L("未拥有", "Not owned")))
    if kb.time_to_beat is not None and a in kb.time_to_beat.index:
        t = kb.time_to_beat.loc[a, "normally"]
        if t == t:
            card["time_to_beat"] = L(f"通关约 {t:.0f} 小时（IGDB）", f"About {t:.0f} hours to finish (IGDB)")
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
    kind_name = setup_names()[kind]
    out = {"kind": kind, "kind_zh": kind_name, "players": spec.party_size,
           "max_players": None if not mx or mx[0] is None else mx[0], "max_source": mx[1] if mx else None,
           "steps": setup_steps()[kind], "controller": next((v for k, v in controller_names().items() if k in cats), None)}
    members = spec.members
    alts = plan.get("alternatives") or []
    if alts:
        host_buy = plan.get("rule") == "host_only"
        verb = L("当主机并购买" if host_buy else "购买", "host and buy it" if host_buy else "buy it")
        out["alternatives"] = [L(f"也可以由{members[j].name}{verb}：{_money(v, members[j].region)}（{members[j].region} 区）",
                                 f"Or {members[j].name} can {verb}: {_money(v, members[j].region)} ({members[j].region} store)")
                               for j, v in alts]
    if plan.get("rule") == "free":
        out["purchase"] = L("免费游戏，无需购买", "Free to play, nothing to buy")
    elif plan.get("rule") == "host_only":
        host = plan.get("host")
        hn = members[host].name
        if plan["new_copies"] == 0:
            out["purchase"] = L(f"仅主机需拥有：{hn}已有，无需新购；其余成员作为来宾加入",
                                f"Only the host needs a copy: {hn} already has it, nothing to buy; "
                                "everyone else joins as a guest")
        else:
            cost = _money(plan["per_member"][host], members[host].region)
            out["purchase"] = L(f"仅主机需拥有：{hn}购买（{cost}）并当主机，其余成员作为来宾加入",
                                f"Only the host needs a copy: {hn} buys it ({cost}) and hosts; "
                                "everyone else joins as a guest")
    elif plan:
        buyers = plan["buyers"]
        own = L("、".join(owned_by) + "已有；", ", ".join(owned_by) + " already have it; ") if owned_by else ""
        if buyers:
            pays = sep().join(f"{members[b].name} {_money(plan['per_member'][b], members[b].region)}" for b in buyers)
            total = L("；", "; ").join(L(f"{r} 区合计 {_money(v, r)}", f"{r} store total {_money(v, r)}")
                                     for r, v in plan["cost"].items())
            per_machine = plan["rule"] == "per_machine"
            out["purchase"] = L(f"{own}需购买：{pays}（{total}）" + ("，每台机器一份" if per_machine else ""),
                                f"{own}{'to buy' if own else 'To buy'}: {pays} ({total})"
                                + (", one copy per machine" if per_machine else ""))
        else:
            out["purchase"] = L(f"{own}无需新购", f"{own}nothing new to buy" if own else "Nothing new to buy")
    if mx and mx[0]:
        out["mode_text"] = L(f"{kind_name} · 最多 {mx[0]} 人（{mx[1]}）", f"{kind_name} · up to {mx[0]} players ({mx[1]})")
    else:
        out["mode_text"] = f"{kind_name} · {mx[1] if mx else L('人数上限未收录', 'player limit not recorded')}"
    if re.search(r"(?i)friend'?s pass|好友通行证", kb.descriptions.get((a, "en"), "") + kb.descriptions.get((a, "zh"), "")):
        out["friends_pass"] = L("介绍提到好友通行证（Friend's Pass），以商店页为准",
                                "The description mentions a Friend's Pass; check the store page")
    out["note"] = L("私人房间、入局方式、手柄分配等细节以游戏说明为准",
                    "For private lobbies, how to join and controller setup, follow the game's instructions")
    return out


REASON_SYS = """You write a short Chinese recommendation reason (60-120 Chinese characters) for each game card, using ONLY the facts given. Do not add numbers, game names, studios or claims that are not in the facts. No purchase advice ("值得买" etc.). Return JSON {"<appid>": "<reason>", ...}."""
REASON_SYS_EN = """You write a short English recommendation reason (about 40-80 words) for each game card, using ONLY the facts given. Do not add numbers, game names, studios or claims that are not in the facts. Put game names in double quotes, spelled exactly as in the facts. No purchase advice ("worth buying" etc.). Return JSON {"<appid>": "<reason>", ...}."""

# English reasons: a run of two or more capitalised words is taken as a proper name (a game, studio or series)
_CAP_RUN = re.compile(r"[A-Z][\w'’&\-]*(?:[ :]+[A-Z0-9][\w'’&\-]*)+")


def _fact_text(card):
    return json.dumps({k: card.get(k) for k in ("name", "like", "diff", "colike", "lineage", "lineage_path", "rating",
                                                "time_to_beat", "setup", "library_hint")}, ensure_ascii=False)


def _consistent(reason, card):
    facts = _fact_text(card)
    for num in re.findall(r"\d+(?:\.\d+)?", reason):
        if num not in facts:
            return False
    for name in re.findall(r"《([^》]+)》", reason):
        if name not in facts:
            return False
    if lang() == "en":
        low = facts.lower()
        # quoted names must appear as written (case aside)
        for name in re.findall(r"\"([^\"]+)\"|“([^”]+)”", reason):
            name = (name[0] or name[1]).strip(" .,;:!?")
            if name and name.lower() not in low:
                return False
        # capitalised runs ("Dark Souls", "Like Hades"): the run, or the run without its first word (a sentence
        # opener such as "Like" / "The"), must appear in the facts
        for run in _CAP_RUN.findall(reason):
            words = run.split()
            if run.lower() not in low and " ".join(words[1:]).lower().strip(" :") not in low:
                return False
    return True


def template_reason(card):
    parts = []
    like = card.get("like", {})
    if like.get("anchor") and like.get("shared_core_tags"):
        tags = sep().join(like["shared_core_tags"][:3])
        parts.append(L(f"和《{like['anchor']}》一样以{tags}为核心", f"Like \"{like['anchor']}\", built around {tags}"))
    elif like.get("shared_core_tags"):
        tags = sep().join(like["shared_core_tags"][:3])
        parts.append(L(f"核心玩法是{tags}", f"Core gameplay: {tags}"))
    if like.get("feel_hits"):
        hits = sep().join(like["feel_hits"])
        parts.append(L(f"玩家给它打了{hits}的标签", f"Players tag it {hits}"))
    if card.get("colike"):
        parts.append(card["colike"]["text"])
    if card.get("lineage"):
        parts.append(card["lineage"][0])
    return L("；", "; ").join(parts) + L("。", ".") if parts else ""


def write_reasons(cards, llm, request_text=""):
    """One batched LLM call for all cards; failed or inconsistent reasons fall back to the template."""
    for c in cards:
        c["reason"], c["reason_source"] = template_reason(c), "template"
    if llm is None or not cards:
        return
    facts = {str(c["appid"]): json.loads(_fact_text(c)) for c in cards}
    en = lang() == "en"
    user = (f"Player's request: {request_text}\nCard facts: " if en else f"玩家的要求：{request_text}\n卡片事实：") \
        + json.dumps(facts, ensure_ascii=False)
    for attempt in range(2):
        try:
            out = chat_json(llm, REASON_SYS_EN if en else REASON_SYS, user, "reasons")
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
