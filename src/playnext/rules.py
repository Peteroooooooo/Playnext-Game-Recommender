"""Step 2: three-valued hard rules (design 4.4, 4.6, 5.2 rule 3). FAIL = 0, UNKNOWN = 1, PASS = 2; a game takes
the worst value over all rules. Each rule keeps its own array so cards can say why a game failed and the conflict
analyser (relax.py) knows which relaxable rule blocked it.
"""
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .i18n import L, sep
from .kb import KB
from .spec import REGION_CURRENCY, Member, SessionSpec

FAIL, UNKNOWN, PASS = 0, 1, 2
LANG = {"english": 0, "schinese": 6, "tchinese": 7, "japanese": 10, "korean": 4}
# Steam store player categories (ids as returned by GetItems)
CAT_ONLINE_COOP, CAT_ONLINE_PVP, CAT_LOCAL_COOP, CAT_LOCAL_PVP, CAT_SHARED, CAT_REMOTE = 38, 36, 39, 37, 24, 44
CAT_SINGLE = 2
GORE_DESCRIPTOR, SEXUAL_DESCRIPTORS = {2}, {1, 3, 4}
GORE_WORDS, SEXUAL_WORDS = ("blood", "gore"), ("sex", "nudity")
MMO_PASS_MAX = 10


def money(v, region):
    if v is None:
        return None
    return f"¥{v:g}" if region == "CN" else f"${v:g}"


@dataclass
class Rule:
    key: str
    label: str
    status: np.ndarray
    relaxable: bool = False
    reason: dict = field(default_factory=dict)  # appid -> short text for FAIL / UNKNOWN
    # appid -> (cause, value) for a FAIL, when the rule has more than one way to fail (the group "setup" rule):
    # players (max players) / mode (setup kind) / region / budget
    cause: dict = field(default_factory=dict)


@dataclass
class Setup:
    """One way to start the game for a group: per game status, cost and who pays."""
    kind: str
    status: np.ndarray
    reason: dict
    max_players: dict            # appid -> (number, source)
    plan: dict                   # appid -> {"buyers": [member idx], "new_copies": int, "cost": {region: amount}}
    cause: dict = field(default_factory=dict)  # appid -> (cause, value) for a FAIL, see Rule.cause


@dataclass
class FilterResult:
    status: np.ndarray
    rules: list
    setups: dict = field(default_factory=dict)   # kind -> Setup (scenario 2)
    best_setup: dict = field(default_factory=dict)  # appid -> kind with the lowest new cost among passing setups

    def summary(self):
        return [{"rule": r.label, "pass": int((r.status == PASS).sum()), "fail": int((r.status == FAIL).sum()),
                 "unknown": int((r.status == UNKNOWN).sum()), "relaxable": r.relaxable} for r in self.rules]

    def why(self, i, appid):
        out = [r.reason.get(appid, r.label) for r in self.rules if r.status[i] == FAIL]
        return out

    def unknown_why(self, i, appid):
        return [r.reason.get(appid, r.label) for r in self.rules if r.status[i] == UNKNOWN]


def _price_cost(kb: KB, appid, region):
    """Snapshot price (design 4.6 'daily snapshot'); None when unknown."""
    if kb.is_free[appid]:
        return 0.0
    p = kb.price(appid, region)
    if p is None or pd.isna(p["final"]):
        return None
    return float(p["final"])


LANG_EN = {"schinese": "Simplified Chinese", "tchinese": "Traditional Chinese", "english": "English",
           "japanese": "Japanese", "korean": "Korean"}


def member_rules(kb: KB, spec: SessionSpec, m: Member, who: str) -> list:
    g = kb.games
    rules = []
    # `who` ("" or "name：") is part of the rule keys; `pre` is its display form in the request language
    name = who.rstrip("：")
    pre = L(who, f"{name}: " if name else "")
    if m.language:
        code = LANG.get(m.language, None)
        st = np.array([UNKNOWN if len(c) == 0 else (PASS if code in set(c) else FAIL) for c in g["language_codes"]], np.int8)
        rules.append(Rule(f"lang:{who}", L(f"{who}支持{'简体中文' if m.language == 'schinese' else m.language}",
                                           f"{pre}supports {LANG_EN.get(m.language, m.language)}"), st))
    if m.platform:
        if m.platform == "deck":
            d = g["deck_compat"].to_numpy()
            st = np.where(np.isin(d, [2, 3]), PASS, np.where(d == 1, FAIL, UNKNOWN)).astype(np.int8)
            label = L("Steam Deck 可玩或已验证", "Steam Deck playable or verified")
        else:
            st = np.where(g[m.platform].to_numpy(), PASS, FAIL).astype(np.int8)
            label = {"windows": L("支持 Windows", "supports Windows"), "mac": L("支持 macOS", "supports macOS"),
                     "linux": L("支持 Linux / SteamOS", "supports Linux / SteamOS")}[m.platform]
        rules.append(Rule(f"platform:{who}", f"{pre}{label}", st))
    if m.avoid_tags or m.avoid_content:
        bad_tags = set(m.avoid_tags)
        st = np.full(kb.n, PASS, np.int8)
        reason = {}
        gore_hit = L("暴力血腥（Steam 内容描述 / 分级描述）", "gore (Steam content / rating descriptors)")
        sexual_hit = L("性内容（Steam 内容描述 / 分级描述）", "sexual content (Steam content / rating descriptors)")
        prefix = L("雷区：", "content you avoid: ")
        for i, a in enumerate(kb.appids):
            hits = [kb.tag_name(t) for t in kb.tagset.get(a, set()) & bad_tags]
            cd = set(g.at[a, "content_descriptor_ids"])
            rd = " ".join(g.at[a, "rating_descriptors"]).lower()
            if "gore" in m.avoid_content and (cd & GORE_DESCRIPTOR or any(w in rd for w in GORE_WORDS)):
                hits.append(gore_hit)
            if "sexual" in m.avoid_content and (cd & SEXUAL_DESCRIPTORS or any(w in rd for w in SEXUAL_WORDS)):
                hits.append(sexual_hit)
            if hits:
                st[i] = FAIL
                reason[int(a)] = prefix + sep().join(hits)
        content = {"gore": L("暴力血腥", "gore"), "sexual": L("性内容", "sexual content")}
        names = [kb.tag_name(t) for t in bad_tags] + [content[c] for c in m.avoid_content]
        head = (L(f"{name}的雷区：", f"{name} avoids: ") if who else L("雷区：", "Content to avoid: "))
        rules.append(Rule(f"avoid:{who}", head + " / ".join(names), st, reason=reason))
    if m.age_limit is not None:
        age = g["required_age"].to_numpy(np.float64)
        rating = pd.to_numeric(g["rating"], errors="coerce").to_numpy(np.float64)
        known = np.where(~np.isnan(age) & (age > 0), age, rating)
        st = np.where(np.isnan(known), UNKNOWN, np.where(known <= m.age_limit, PASS, FAIL)).astype(np.int8)
        rules.append(Rule(f"age:{who}", L(f"{who}年龄分级 ≤ {m.age_limit}", f"{pre}age rating ≤ {m.age_limit}"), st))
    return rules


def _mode_status(kb: KB, appid, kind, interaction, n, per_site):
    """Design 4.4 table + 10.2 fill rules. Returns (status, reason, (max, source))."""
    return _mode_check(kb, appid, kind, interaction, n, per_site)[:3]


def _mode_check(kb: KB, appid, kind, interaction, n, per_site):
    """_mode_status plus the cause of a FAIL: ("players", the limit that was too small) or ("mode", kind)."""
    cats = kb.categories.get(appid, set())
    p = kb.pc.get(appid)
    get = lambda f: None if p is None or pd.isna(p[f]) else int(p[f])
    if kind in ("online", "hybrid"):
        want = {"coop": [(CAT_ONLINE_COOP, "onlinecoopmax")], "versus": [(CAT_ONLINE_PVP, "onlinemax")],
                "any": [(CAT_ONLINE_COOP, "onlinecoopmax"), (CAT_ONLINE_PVP, "onlinemax")]}[interaction]
        label = L("在线", "online")
    else:
        want = {"coop": [(CAT_LOCAL_COOP, "offlinecoopmax")], "versus": [(CAT_LOCAL_PVP, "offlinemax")],
                "any": [(CAT_LOCAL_COOP, "offlinecoopmax"), (CAT_LOCAL_PVP, "offlinemax")]}[interaction]
        label = L("同屏", "local")
    has_cat = [f for c, f in want if c in cats]
    if kind == "remote" and CAT_REMOTE not in cats:
        return FAIL, L("没有 Steam 远程同乐分类", "no Steam Remote Play Together category"), None, ("mode", kind)
    if not has_cat:
        # generic "Shared/Split Screen" stands for a local mode only when the game names no specific one: with only
        # "local PvP" it is that PvP mode, not co-op (Pummel Party)
        if kind in ("local", "remote") and CAT_SHARED in cats and not (cats & {CAT_LOCAL_COOP, CAT_LOCAL_PVP}):
            has_cat = [f for _, f in want]
        elif any(get(f) for _, f in want):
            return UNKNOWN, L(f"IGDB 有{label}人数，但 Steam 没有{label}分类（两源冲突）",
                              f"IGDB has a {label} player count but Steam has no {label} category (sources disagree)"), None, None
        else:
            what = L({"coop": "合作", "versus": "对抗"}.get(interaction, "多人"),
                     {"coop": "co-op", "versus": "versus"}.get(interaction, "multiplayer"))
            return FAIL, L(f"没有{label}{what}模式（Steam 分类）", f"no {label} {what} mode (Steam categories)"), None, ("mode", kind)
    need = n
    counts = [get(f) for f in has_cat if get(f)]
    # IGDB counts from a non-PC record (console or unlabelled; no PC record exists) agree with PC 96% of the time and
    # are too low in 3%, mostly for big online games (scripts/build_processed.py, 2026-10-16), so they may PASS a
    # request but never FAIL it: above the count the fill rules below decide, else UNKNOWN
    other = p is not None and p.get("count_platform") == "other"
    src = L("IGDB（非 PC 版记录）", "IGDB (non-PC record)") if other else "IGDB"
    nonpc = L("IGDB 只有非 PC 版记录：", "IGDB only has a non-PC record: ")
    short = lambda mx: L(f"差 {need - mx} 个位", f"{need - mx} short")
    if counts:
        mx = max(counts)
        if kind == "hybrid":
            flag = None if p is None else p["splitscreenonline"]
            if not (CAT_LOCAL_COOP in cats or CAT_LOCAL_PVP in cats or CAT_SHARED in cats):
                return FAIL, L("没有同屏模式，无法部分人同屏", "no local mode, so some players cannot share a screen"), (mx, src), ("mode", kind)
            off = [get(f) for f in ("offlinecoopmax", "offlinemax") if get(f)]
            if need > mx:
                if other:
                    return UNKNOWN, nonpc + L(f"在线最多 {mx} 人", f"up to {mx} players online"), (mx, src), None
                return FAIL, L(f"在线最多 {mx} 人，", f"up to {mx} players online, ") + short(mx), (mx, src), ("players", mx)
            if off and max(per_site) > max(off):
                if other:
                    return UNKNOWN, nonpc + L(f"同屏最多 {max(off)} 人", f"up to {max(off)} players on one screen"), (mx, src), None
                return FAIL, L(f"同屏最多 {max(off)} 人", f"up to {max(off)} players on one screen"), (mx, src), ("players", max(off))
            if flag is not True:
                return UNKNOWN, L("IGDB 没有标注“同屏 + 在线”混合开局", "IGDB does not list mixed local + online play"), (mx, src), None
            return PASS, None, (mx, src), None
        if need <= mx:
            return PASS, None, (mx, src), None
        if not other:
            return FAIL, L(f"{label}最多 {mx} 人，", f"up to {mx} players {label}, ") + short(mx), (mx, src), ("players", mx)
        fill = _fill_rules(p, kind, need, label, cats)
        if fill[0] == PASS:
            return (*fill, None)
        return UNKNOWN, nonpc + L(f"{label}最多 {mx} 人", f"up to {mx} players {label}"), (mx, src), None
    return (*_fill_rules(p, kind, need, label, cats), None)

def _fill_rules(p, kind, need, label, cats=frozenset()):
    """Category present, no usable PC count: design 10.2 fill rules."""
    if need == 2:
        return PASS, None, (None, L("2 人请求：有多人分类即可", "2 players: a multiplayer category is enough"))
    d = None if p is None or pd.isna(p["desc_max_players"]) else int(p["desc_max_players"])
    if d:
        # the description does not say which mode its number is for; for a local / remote setup it may be the
        # online count (Stardew Valley: "up to 8 players" online, 4 on one screen), so it only PASSes when the game
        # has no online mode the number could belong to
        if need <= d and (kind in ("online", "hybrid") or not (cats & {CAT_ONLINE_COOP, CAT_ONLINE_PVP})):
            return PASS, None, (d, L("商店介绍", "store description"))
        return UNKNOWN, L(f"商店介绍写最多 {d} 人（未说明是哪种模式），IGDB 未收录{label}人数",
                          f"the store description says up to {d} players (mode not stated); IGDB has no {label} count"), \
            (d, L("商店介绍", "store description"))
    if kind in ("online", "hybrid") and p is not None and bool(p["mmo_tag"]) and need <= MMO_PASS_MAX:
        return PASS, None, (None, L("大型多人标签", "Massively Multiplayer tag"))
    return UNKNOWN, L(f"IGDB 未收录{label}人数上限", f"IGDB has no {label} player limit"), None


def _plan(kb: KB, spec: SessionSpec, appid, kind, sites):
    """Entitlement rules (design 5.5): per_player / per_machine / host_only / free. Returns plan or None (unknown)."""
    members = spec.members
    if kb.is_free[appid]:
        return {"rule": "free", "buyers": [], "new_copies": 0, "cost": {}, "per_member": {}}
    if kind == "online":
        groups = [[i] for i in range(len(members))]
        rule = "per_player"
    elif kind == "remote":
        owners = [i for i, m in enumerate(members) if m.owns(appid)]
        if owners:
            return {"rule": "host_only", "buyers": [], "host": owners[0], "new_copies": 0, "cost": {}, "per_member": {},
                    "alternatives": []}
        # nobody owns it: one member buys and hosts
        prices = {i: _price_cost(kb, appid, m.region) for i, m in enumerate(members)}
        known = {i: p for i, p in prices.items() if p is not None and not _blocked(kb, appid, members[i].region)}
        if not known:
            return None
        host, alts = _cheapest(known, members)
        return {"rule": "host_only", "buyers": [host], "host": host, "new_copies": 1,
                "cost": {members[host].region: known[host]}, "per_member": {host: known[host]}, "alternatives": alts}
    else:
        groups = [s.members for s in sites]
        rule = "per_machine"
    buyers, per_member, alternatives = [], {}, []
    for grp in groups:
        if any(members[i].owns(appid) for i in grp):
            continue
        cands = {i: _price_cost(kb, appid, members[i].region) for i in grp if not _blocked(kb, appid, members[i].region)}
        cands = {i: p for i, p in cands.items() if p is not None}
        if not cands:
            return None
        b, alts = _cheapest(cands, members)
        buyers.append(b)
        per_member[b] = cands[b]
        alternatives += alts
    cost = {}
    for b, v in per_member.items():
        cost[members[b].region] = cost.get(members[b].region, 0) + v
    return {"rule": rule, "buyers": buyers, "new_copies": len(buyers), "cost": cost, "per_member": per_member,
            "alternatives": alternatives}


def _cheapest(cands: dict, members):
    """Who buys: the cheapest candidate when all share one store region. Prices in different currencies are not
    compared (design 5.5 '多区组队'): the earliest-listed member's region is the default and the cheapest buyer of
    each other region is returned as an alternative (member index, price) for the user to choose."""
    regions = {members[i].region for i in cands}
    if len(regions) == 1:
        return min(cands, key=cands.get), []
    pref = members[min(cands)].region
    same = {i: p for i, p in cands.items() if members[i].region == pref}
    alts = []
    for r in sorted(regions - {pref}):
        other = {i: p for i, p in cands.items() if members[i].region == r}
        j = min(other, key=other.get)
        alts.append((j, other[j]))
    return min(same, key=same.get), alts


def over_budget(spec: SessionSpec, plan) -> float | None:
    """Amount that breaks the budget (in the budget's currency), or None. Per person: each buyer whose store
    currency matches the budget. Team total: only when every cost is in the budget's currency (design 4.6)."""
    b = spec.budget
    if b is None or not plan:
        return None
    if b.scope == "per_person":
        over = [v for m, v in plan["per_member"].items() if b.applies_to(spec.members[m].region) and v > b.amount]
        return max(over) if over else None
    regions = set(plan["cost"])
    if not regions or len(regions) > 1 or not b.applies_to(next(iter(regions))):
        return None
    total = sum(plan["cost"].values())
    return total if total > b.amount else None


NOT_IN_CN = lambda: L("CN 区不卖（Steam 地区限制）", "not sold in the CN store (Steam region lock)")

def setup_names() -> dict:
    return {"online": L("在线组队", "Online"), "local": L("本地同屏", "Same screen"),
            "remote": L("远程同乐", "Remote Play Together"), "hybrid": L("混合开局", "Mixed local + online")}


# when several setups fail for different reasons, the one shown (and offered to relax) first
CAUSE_ORDER = ("budget", "mode", "region", "players")


def _blocked(kb, appid, region):
    return region == "CN" and bool(kb.cn_blocked[appid])


def _sites_for(spec: SessionSpec, kind):
    n = spec.party_size
    if spec.sites:
        return spec.sites
    from .spec import Site
    if kind == "local":
        return [Site(members=list(range(n)))]
    if kind == "remote":
        return [Site(members=[0])] + [Site(members=[i], remote_guest_of=0) for i in range(1, n)]
    return [Site(members=[i]) for i in range(n)]


def group_setup(kb: KB, spec: SessionSpec, kind) -> Setup:
    sites = _sites_for(spec, kind)
    n = spec.party_size
    per_site = [len(s.members) for s in sites if s.remote_guest_of is None] if kind != "remote" else [n]
    status = np.full(kb.n, PASS, np.int8)
    reason, maxp, plans, cause = {}, {}, {}, {}
    budget = spec.budget
    for i, a in enumerate(kb.appids):
        a = int(a)
        st, why, mx, c = _mode_check(kb, a, kind, spec.interaction, n, per_site)
        if mx:
            maxp[a] = mx
        if st == FAIL:
            status[i], reason[a], cause[a] = FAIL, why, c
            continue
        plan = _plan(kb, spec, a, kind, sites)
        if plan is None:
            blocked = any(_blocked(kb, a, m.region) and not m.owns(a) for m in spec.members)
            st2, why2 = (FAIL, NOT_IN_CN()) if blocked else (UNKNOWN, L("需要购买的成员所在区取不到价格",
                                                                         "no price in the store region of the buyer"))
            status[i], reason[a] = min(st, st2), why2 if st2 < st or st == PASS else why
            if st2 == FAIL:
                cause[a] = ("region", "CN")
            continue
        plans[a] = plan
        over = over_budget(spec, plan) if budget is not None else None
        if over is not None:
            region = next((r for r, c in REGION_CURRENCY.items() if c == budget.currency), spec.members[0].region)
            status[i], reason[a] = FAIL, L(f"超出预算（需 {money(over, region)}，每日快照）",
                                           f"over budget (needs {money(over, region)}, daily snapshot)")
            cause[a] = ("budget", over)
            continue
        status[i] = st
        if st == UNKNOWN:
            reason[a] = why
    return Setup(kind, status, reason, maxp, plans, cause)


def hard_filter(kb: KB, spec: SessionSpec) -> FilterResult:
    rules = []
    n = kb.n
    single = spec.party_size == 1
    # what was said ("we already played X", "玩过了", "不喜欢") counts for groups too; Steam playtime only excludes for
    # one player, since a group often wants a game some members already know
    why = {}
    seed_why = L("种子游戏", "seed game")
    for a in spec.excluded:
        why[int(a)] = L("这次点过“玩过了 / 不感兴趣”", "marked “played / not interested” this session")
    for m in spec.members:
        for a in m.disliked:
            why[int(a)] = L(f"{'' if single else m.name}标记过不喜欢",
                            "marked as disliked" if single else f"{m.name} marked it as disliked")
        if single and m.library:
            for a in m.library.played:
                why[int(a)] = L("Steam 上有游玩记录", "has playtime on Steam")
        for a in m.played_elsewhere:
            why[int(a)] = (L("说过已经玩过", "said already played") if single
                           else L(f"{m.name}说过已经玩过", f"{m.name} said they already played it"))
        for a in m.seeds:
            why[int(a)] = seed_why
    for a in spec.seeds:
        why[int(a)] = seed_why
    st = np.where(np.isin(kb.appids, list(why)), FAIL, PASS).astype(np.int8)
    rules.append(Rule("exclude", L("去掉种子 / 已玩过的", "Remove seeds / already played"), st, reason=why))
    if spec.library_policy == "exclude_owned":
        owned = {a for m in spec.members for a in (m.library.owned if m.library else {})} | \
                {a for m in spec.members for a in m.owned_extra}
        st = np.where(np.isin(kb.appids, list(owned)), FAIL, PASS).astype(np.int8)
        rules.append(Rule("exclude_owned", L("去掉已拥有的", "Remove games already owned"), st))
    for k, m in enumerate(spec.members):
        who = "" if single else f"{m.name}："
        rules += member_rules(kb, spec, m, who)
    if spec.mechanics:
        st = np.array([PASS if all(t in set(kb.core.get(a, [])) for t in spec.mechanics) else FAIL for a in kb.appids], np.int8)
        mech = " + ".join(kb.tag_name(t) for t in spec.mechanics)
        rules.append(Rule("mechanics", L("机制组合：" + mech + " 都是核心标签", "Mechanics: " + mech + " are all core tags"),
                          st, relaxable=True))
    setups, best = {}, {}
    if single:
        m = spec.members[0]
        if spec.single_player:
            # only when the player says they will play alone ("单机", "singleplayer", "没朋友一起玩"): one person asking
            # is not the same as playing alone, and 12.8% of what held-out reviewers liked next is multiplayer-only
            # (CS2, Apex...), so this is not applied to every one-person request (Steam "Single-player" category)
            cats = [kb.categories.get(int(a), set()) for a in kb.appids]
            st = np.array([UNKNOWN if not c else (PASS if CAT_SINGLE in c else FAIL) for c in cats], np.int8)
            no_solo = L("没有单人模式（Steam 分类）", "no single-player mode (Steam categories)")
            rules.append(Rule("solo", L("能一个人玩（Steam 单人分类）", "Playable alone (Steam Single-player category)"), st,
                              reason={int(a): no_solo for a, s in zip(kb.appids, st) if s == FAIL}))
        blocked = kb.games["cn_blocked"].to_numpy() & (m.region == "CN")
        owned = np.array([m.owns(int(a)) for a in kb.appids])
        st = np.where(blocked & ~owned, FAIL, PASS).astype(np.int8)
        not_cn = NOT_IN_CN()
        rules.append(Rule("region", L(f"{m.region} 区有售", f"Sold in the {m.region} store"), st,
                          reason={int(a): not_cn for a in kb.appids[blocked & ~owned]}))
        if spec.budget is not None and spec.budget.applies_to(m.region):
            cost = np.array([0.0 if o else (_price_cost(kb, int(a), m.region) if _price_cost(kb, int(a), m.region) is not None else np.nan)
                             for a, o in zip(kb.appids, owned)])
            st = np.where(np.isnan(cost), UNKNOWN, np.where(cost <= spec.budget.amount, PASS, FAIL)).astype(np.int8)
            cap = money(spec.budget.amount, m.region)
            rules.append(Rule("budget", L(f"预算 ≤ {cap}（每日快照）", f"Budget ≤ {cap} (daily snapshot)"), st, relaxable=True,
                              reason={int(a): L(f"现价 {money(c, m.region)} 超出预算",
                                                f"current price {money(c, m.region)} is over budget")
                                      for a, c in zip(kb.appids, cost) if c > spec.budget.amount}))
        if spec.only_discounted:
            disc = np.array([(kb.price(int(a), m.region) is not None and kb.price(int(a), m.region)["discount_pct"] > 0)
                             for a in kb.appids])
            st = np.where(disc | owned, PASS, FAIL).astype(np.int8)
            rules.append(Rule("discount", L("正在打折", "On sale"), st, relaxable=True))
    else:
        for kind in spec.setup_types:
            setups[kind] = group_setup(kb, spec, kind)
        comb = np.max([s.status for s in setups.values()], axis=0)
        labels = setup_names()
        reason, cause = {}, {}
        for i, a in enumerate(kb.appids):
            a = int(a)
            ok = [k for k, s in setups.items() if s.status[i] == comb[i]]
            if comb[i] >= UNKNOWN:
                best[a] = min(ok, key=lambda k: sum(setups[k].plan.get(a, {}).get("cost", {}).values()) if a in setups[k].plan else 1e9)
            if comb[i] < PASS:
                reason[a] = L("；", "; ").join(f"{labels[k]}{L('：', ': ')}{s.reason.get(a)}" for k, s in setups.items() if s.reason.get(a))
            if comb[i] == FAIL:
                got = [s.cause[a] for s in setups.values() if a in s.cause]
                if got:
                    cause[a] = min(got, key=lambda c: CAUSE_ORDER.index(c[0]))
        b = spec.budget
        b_region = (next((r for r, c in REGION_CURRENCY.items() if c == b.currency), spec.members[0].region)
                    if b else None)
        budget_text = ""
        if b:
            scope = L("每人" if b.scope == "per_person" else "团队", "per person " if b.scope == "per_person" else "team ")
            budget_text = L(f" · {scope}预算 {money(b.amount, b_region)}", f" · {scope}budget {money(b.amount, b_region)}")
        rules.append(Rule("setup", L(f"{spec.party_size} 人 · ", f"{spec.party_size} players · ") +
                          " / ".join(labels[k] for k in setups) + budget_text,
                          comb.astype(np.int8), relaxable=True, reason=reason, cause=cause))
    status = np.min([r.status for r in rules], axis=0).astype(np.int8)
    if spec.accept_unknown:
        status = np.where(status == UNKNOWN, PASS, status).astype(np.int8)
    return FilterResult(status, rules, setups, best)
