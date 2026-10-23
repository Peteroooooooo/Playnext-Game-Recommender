"""The whole recommendation trunk (design 5.1): Step 1 understand -> 2 hard rules -> 3 scores -> 4 ranking ->
5 cards; Step 6 patches the spec and reruns. Every step is timed for the latency report (design 7)."""
import time
from dataclasses import dataclass, field

import numpy as np

from . import appindex, config as C, progress
from .cards import build_card, price_facts, write_reasons
from .aliases import Resolver
from .i18n import L
from .kb import KB, minmax
from .pricing import Prices
from .ranking import rank
from .relax import analyse
from .rerank import candidates, fuse, llm_scores, targets_with_words, with_game_names
from .rules import (CAT_LOCAL_COOP, CAT_LOCAL_PVP, CAT_ONLINE_COOP, CAT_ONLINE_PVP, CAT_REMOTE, CAT_SHARED, FAIL, PASS,
                    UNKNOWN, hard_filter)

MP_CATS = {CAT_ONLINE_COOP, CAT_ONLINE_PVP, CAT_LOCAL_COOP, CAT_LOCAL_PVP, CAT_SHARED, CAT_REMOTE}
NEVER_NEAR_MISS = ("avoid", "lang", "platform", "age")
from .scoring import combine, prior, relevance
from .spec import SessionSpec
from .understand import ParsedRequest, Understander, describe


@dataclass
class Result:
    spec: SessionSpec
    understood: dict
    picks: list
    backups: list
    unknown: list
    rules: list
    relax: list = field(default_factory=list)
    timings: dict = field(default_factory=dict)
    notes: list = field(default_factory=list)
    need_input: str | None = None
    failed: list = field(default_factory=list)   # well-liked games that broke a hard rule, with the reasons
    debug: dict = field(default_factory=dict)    # evaluation only (rerank candidates and raw scores); not sent

    def to_dict(self):
        return {"understood": self.understood, "picks": self.picks, "backups": self.backups, "unknown": self.unknown,
                "rules": self.rules, "relax": self.relax, "timings": self.timings, "notes": self.notes,
                "need_input": self.need_input, "failed": self.failed}


class Recommender:
    def __init__(self, kb: KB | None = None, llm=None, live_prices=True, reasons=True, rerank=True, paths=None):
        self.kb = kb or KB()
        self.llm = llm
        self.paths = paths   # db.PathFinder for request-time lineage paths; None = in-memory lineage only
        self.want_failed = True
        self.prices = Prices(self.kb, live=live_prices)
        self.understander = Understander(self.kb, llm) if llm else None
        self.resolver = self.understander.resolver if self.understander else Resolver(self.kb.games)
        self.reasons = reasons
        self.rerank = rerank

    # ---------- Step 1 / Step 6 ----------
    def understand(self, text, base: SessionSpec | None = None, parsed: ParsedRequest | None = None):
        if self.understander is None:
            raise RuntimeError("no LLM configured: build the SessionSpec directly")
        progress.start("understand")
        p = self.understander.patch(parsed, text) if parsed is not None else self.understander.parse(text)
        spec = self.understander.to_spec(p, text if parsed is None else (base.request_text + " / " + text), base)
        progress.done("understand")
        return p, spec

    # ---------- Steps 2-5 ----------
    def recommend(self, spec: SessionSpec, rerank_scores: dict | None = None, rerank_w: float | None = None) -> Result:
        """rerank_scores / rerank_w are for evaluation: reuse cached rerank scores ({target: {appid: score}}, from
        any reranker) and try other fusion weights without new model calls."""
        kb, t = self.kb, {}
        t0 = time.time()
        progress.start("pick")
        fr = hard_filter(kb, spec)
        notes = []
        secondary = np.zeros(kb.n, bool)
        n_strict = int((fr.status == PASS).sum()) if spec.mechanics else C.PICK
        if n_strict < C.PICK:
            # design 4.3 fallback: too few games have every wanted mechanic as a core tag, so games where at least one
            # is core and the rest are present fill the remaining places, always after the strict ones
            notes.append(L("没有游戏同时把这几种玩法都作为核心标签，已放宽为“其中一种是核心、其余是次要”",
                           "No game has all of these mechanics as core tags, so this was relaxed to "
                           "“one is core, the rest are secondary”") if n_strict == 0 else
                         L(f"同时把这几种玩法都作为核心标签的只有 {n_strict} 款，后面补上“其中一种是核心、其余是次要”的",
                           f"Only {n_strict} games have all of these mechanics as core tags; the rest of the list "
                           "has one core and the others secondary"))
            strict = fr.status
            fr = hard_filter(kb, spec.model_copy(update={"mechanics": []}))
            must = set(spec.mechanics)
            st = fr.status.copy()
            for i, a in enumerate(kb.appids):
                tags, core = kb.tagset.get(int(a), set()), set(kb.core.get(int(a), []))
                if not (must <= tags and must & core):
                    st[i] = FAIL
            secondary = (st >= UNKNOWN) & (strict < UNKNOWN)
            fr.status = st
        t["hard_filter"] = round(time.time() - t0, 3)
        notes += _budget_notes(spec)
        for a in spec.outside_seeds:
            notes.append(L(f"《{appindex.name_of(a) or a}》在 Steam 上，但不在核心库（评测不到 1,000 条或已下架），"
                           "没有同好数据，只按它的标签找相似的",
                           f"{appindex.name_of(a) or a} is on Steam but not in the core library (under 1,000 reviews "
                           "or delisted), so there is no co-player data: similar games are found from its tags "
                           "only"))
        pool = fr.status >= UNKNOWN
        t1 = time.time()
        rel, details = relevance(kb, spec, pool)
        t["scoring"] = round(time.time() - t1, 3)
        progress.done("pick")
        debug = {}
        texts = {k: (with_game_names(kb, spec, v) if C.RERANK_GAME_NAMES else v)
                 for k, v in targets_with_words(spec, kb).items() if k in details.get("norm", {})}
        if rel is not None and texts and (rerank_scores is not None or (self.llm is not None and C.RERANK and self.rerank)):
            progress.start("rerank")
            t1 = time.time()
            try:
                cand = candidates(kb, rel, fr.status == PASS, details)
                if rerank_scores is not None:
                    keys = {str(k): k for k in texts}
                    scores = {keys[k]: {kb.pos[int(a)]: v for a, v in sc.items() if int(a) in kb.pos}
                              for k, sc in rerank_scores.items() if k in keys}
                else:
                    scores = llm_scores(kb, self.llm, texts, cand)
                norm = dict(details["norm"])
                for target, sc in scores.items():
                    norm[target] = fuse(kb, norm[target], sc, rerank_w)
                rel = combine(norm, pool)
                debug["rerank"] = {"cand": [int(kb.appids[i]) for i in cand],
                                   "scores": {str(k): {int(kb.appids[i]): v for i, v in sc.items()} for k, sc in scores.items()}}
            except Exception:
                notes.append(L("语义精排暂不可用，结果只按标签与同好打分",
                               "Semantic reranking is unavailable right now; results are scored by tags and "
                               "co-players only"))
            t["rerank"] = round(time.time() - t1, 3)
            progress.done("rerank")
        else:
            progress.skip("rerank")
        understood = describe(kb, spec)
        if rel is None:
            if not (fr.status == PASS).any():
                progress.skip("prices")
                return Result(spec, understood, [], [], [], fr.summary(), analyse(kb, spec, fr), timings=t, notes=notes,
                              failed=self.failed_list(spec, fr), debug=debug)
            # no taste at all (design 5.5 'cold start'): the conditions alone still deserve an answer, so rank the
            # passing games by smoothed rating x log(reviews) and ask for a seed on the page
            rel = minmax(prior(kb), pool)
            details = {}
            notes.append(L("还不知道你们的口味，先按口碑和评测数排了一版；说一两款喜欢的游戏或想要的感觉，会更准",
                           "No taste to go on yet, so this list is ranked by rating and review count; name a game "
                           "or two you like, or the feel you want, for a closer match"))
        for m in spec.members:
            if m.library and not m.library.is_public:
                notes.append(L(f"{m.name}的 Steam 游戏详情不公开，读不到库；可以在 Steam 隐私设置里把“游戏详情”改为公开，或直接点选喜欢的游戏",
                               f"{m.name}'s Steam game details are private, so the library cannot be read; set "
                               "“Game details” to public in Steam privacy settings, or pick liked games directly"))
            elif m.library and m.library.playtime_hidden:
                notes.append(L(f"{m.name}的游戏时长都是 0，看起来隐藏了游玩时间：库只用来标“已拥有”，不当口味参考",
                               f"All of {m.name}'s playtimes are 0, so playtime looks hidden: the library only marks "
                               "games as owned and is not used for taste"))
        if spec.ambiguous:
            for name, cands in spec.ambiguous.items():
                if len(cands) > 1:
                    shown = kb.display_name(cands[0])
                    notes.append(L(f"“{name}”按《{shown}》理解，另有 {len(cands) - 1} 个版本，可以改",
                                   f"Read “{name}” as {shown}; there are {len(cands) - 1} other versions you can switch to"))
        t2 = time.time()
        progress.start("prices")
        ranked = rank(kb, spec, rel - 2.0 * secondary if secondary.any() else rel, fr, self.prices)
        t["ranking_and_live_prices"] = round(time.time() - t2, 3)
        progress.done("prices")
        t3 = time.time()
        picks = [build_card(kb, spec, i, rel, ranked, details, fr, self.prices, ranked.steps[k])
                 for k, i in enumerate(ranked.picks)]
        for c in picks:
            if secondary[kb.pos[c["appid"]]]:
                c["mechanics_note"] = L("其中一种玩法是次要元素（玩家标签票数没到核心标签的线）",
                                        "One of the mechanics is a secondary element (its player tag votes are "
                                        "below the core-tag line)")
        if self.paths is not None:
            todo = [c for c in picks if c.get("anchor_appid")]
            for c, path in zip(todo, self.paths.many([(c["anchor_appid"], c["appid"]) for c in todo])):
                if path:
                    c["lineage_path"] = {"text": path, "source": L("PostgreSQL 递归路径查询（开发商 / 系列 / IGDB 相似）",
                                                                   "PostgreSQL recursive path query (developer / series / IGDB similar)")}
        write_reasons(picks, self.llm if self.reasons else None, spec.request_text)  # template first, LLM if enabled
        t["cards"] = round(time.time() - t3, 3)
        backups = []
        region = spec.members[0].region
        for i in ranked.shortlist:
            if i in ranked.picks:
                continue
            a = int(kb.appids[i])
            item = {"appid": a, "name": kb.display_name(a), "relevance": round(float(rel[i]), 3),
                    "price": price_facts(self.prices, a, region), "pct_positive": _pct(kb, a)}
            if not kb.rating_ok[i]:
                item["label"] = (L("暂无好评率", "No rating yet") if item["pct_positive"] is None else
                                 L(f"口碑褒贬不一：{item['pct_positive']}% 好评", f"Mixed reviews: {item['pct_positive']}% positive"))
            if any(m.library and a in m.library.owned for m in spec.members):
                item["owned"] = (L("已在 Steam 库里，Steam 上没有游玩记录", "In your Steam library, no playtime on Steam")
                                 if spec.party_size == 1 else L("有成员已拥有", "A member already owns it"))
            if ranked.folded.get(i):
                item["same_series"] = len(ranked.folded[i])
                item["series_names"] = [kb.display_name(int(kb.appids[j])) for j in ranked.folded[i]]
            if spec.party_size > 1 and fr.best_setup.get(a):
                item["setup"] = fr.best_setup[a]
            backups.append(item)
        unknown = []
        for i in ranked.unknown:
            a = int(kb.appids[i])
            players = any(r.key == "setup" and r.status[i] == UNKNOWN for r in fr.rules)
            unknown.append({"appid": a, "name": kb.display_name(a), "why": fr.unknown_why(i, a),
                            "price": price_facts(self.prices, a, region), "pct_positive": _pct(kb, a),
                            "miss": {"cause": "players_unknown" if players else "unknown", "value": None},
                            "relax": "unknown"})
        relax = []
        if not picks:
            relax = analyse(kb, spec, fr, rel)
        dropped = [{"name": kb.display_name(int(kb.appids[i])), "why": w} for i, w in ranked.dropped_live]
        if dropped:
            notes.append(L("实时价格复核后移出：" + "；".join(f"《{d['name']}》{d['why']}" for d in dropped[:3]),
                           "Removed after the live price check: " + "; ".join(f"{d['name']} ({d['why']})" for d in dropped[:3])))
        failed = []
        if self.want_failed:
            t3 = time.time()
            failed = self.failed_list(spec, fr)
            t["failed_list"] = round(time.time() - t3, 3)
        t["total"] = round(time.time() - t0, 3)
        llm_calls = getattr(self.llm, "calls", None)
        if llm_calls:
            t["llm_calls"] = list(llm_calls)
        return Result(spec, understood, picks, backups, unknown, fr.summary(), relax, t, notes, failed=failed,
                      debug=debug)

    def failed_list(self, spec: SessionSpec, fr) -> list:
        """'没通过的': the best-liked games that broke a hard rule other than 'seed / already played', with reasons
        (design 4.4 card example '未通过 《Y》在线合作最多 4 人，差 1 个位'). Liking is scored over a pool widened to
        these games; no rerank."""
        kb = self.kb
        broke = np.zeros(kb.n, bool)
        skip = np.zeros(kb.n, bool)
        for r in fr.rules:
            # what the user ruled out (content they avoid, language, platform, age) is never shown as a near miss
            if r.key in ("exclude", "exclude_owned") or r.key.split(":")[0] in NEVER_NEAR_MISS:
                skip |= r.status == FAIL
            else:
                broke |= r.status == FAIL
        cand = broke & ~skip
        if spec.party_size > 1:
            # for a group, "no multiplayer mode at all" is not a near miss worth showing; games that have one but
            # fall short (players, mode, budget) are
            mp = np.array([bool(kb.categories.get(int(a), set()) & MP_CATS) for a in kb.appids])
            cand &= mp
        if not cand.any():
            return []
        wide = (fr.status >= UNKNOWN) | cand
        rel, _ = relevance(kb, spec, wide)
        if rel is None:
            rel = minmax(prior(kb), wide)
        idx = np.flatnonzero(cand)
        idx = idx[np.argsort(-rel[idx], kind="stable")]
        region = spec.members[0].region
        out = []
        for i in idx:
            if len(out) == C.FAILED_SHOW:
                break
            a = int(kb.appids[i])
            broken = [r for r in fr.rules if r.status[i] == FAIL and r.key not in ("exclude", "exclude_owned")]
            misses = [_miss(r, a, kb, region) for r in broken]
            if not all(_is_near(spec, c, v) for c, v in misses):
                continue
            cause, value = misses[0]
            relax = _relax_key(spec, cause) if len(broken) == 1 else None
            out.append({"appid": a, "name": kb.display_name(a), "why": [r.reason.get(a, r.label) for r in broken],
                        "relevance": round(float(rel[i]), 3), "price": price_facts(self.prices, a, region),
                        "pct_positive": _pct(kb, a), "miss": {"cause": cause, "value": value}, "relax": relax})
        return out

    def ask(self, text, base: SessionSpec | None = None, parsed: ParsedRequest | None = None):
        t0 = time.time()
        p, spec = self.understand(text, base, parsed)
        if base is not None:  # keep what the user connected or ticked
            for m_new, m_old in zip(spec.members, base.members):
                m_new.library = m_new.library or m_old.library
        res = self.recommend(spec)
        res.timings["understand"] = round(time.time() - t0 - res.timings.get("total", 0), 3)
        return p, res


def _miss(rule, appid, kb, region):
    """Short cause of a near miss for the page badge: (cause, value)."""
    if rule.key == "setup":
        return rule.cause.get(appid, ("mode", None))
    if rule.key == "budget":
        p = kb.price(appid, region)
        return "budget", None if p is None else float(p["final"])
    return {"discount": "discount", "mechanics": "mechanics", "solo": "solo", "region": "region"}.get(rule.key, "other"), None


def _is_near(spec: SessionSpec, cause: str, value) -> bool:
    """Whether a broken rule is only 'a little off' (a near miss is shown) or plainly not what was asked. A play
    setup or interaction the user stated (同屏 / 线上 / 合作) that the game lacks is never near; a player limit is
    near when the mode is really multiplayer (limit >= 2) and at most NEAR_PLAYERS_SHORT seats short, a price when at
    most NEAR_BUDGET_X x the budget. Not sold in the player's store is never near."""
    if cause == "mode":
        return not (spec.sites or spec.setup_hint or spec.interaction != "any")
    if cause == "region":
        return False
    if cause == "players":
        return value is None or (value >= 2 and spec.party_size - value <= C.NEAR_PLAYERS_SHORT)
    if cause == "budget":
        return value is None or spec.budget is None or value <= C.NEAR_BUDGET_X * spec.budget.amount
    return True


def _relax_key(spec: SessionSpec, cause: str):
    """Which condition 'skip this condition' drops for a near miss, or None when it cannot be dropped (player
    counts are a fact; the region is the user's store; content, language and platform never reach here)."""
    if cause in ("budget", "discount", "mechanics", "solo"):
        return cause
    if cause == "mode" and (spec.sites or spec.setup_hint or spec.interaction != "any"):
        return "setup"
    return None


def relax_spec(spec: SessionSpec, key: str) -> SessionSpec:
    """The session's request with one condition dropped (POST /api/relax)."""
    change = {"budget": {"budget": None, "price_intent": "none"}, "discount": {"only_discounted": False},
              "mechanics": {"mechanics": []}, "solo": {"single_player": False},
              "setup": {"sites": None, "setup_hint": None, "interaction": "any"},
              "unknown": {"accept_unknown": True}}[key]
    return spec.model_copy(update=change)


def _budget_notes(spec: SessionSpec):
    """Say when a stated budget could not be applied: prices are compared only within one store currency."""
    notes = []
    u = spec.budget_unsupported
    if u is not None:
        notes.append(L(f"预算写的是 {u.amount:g} {u.currency}：目前只有国区（人民币）和美区（美元）的价格，不做汇率换算，"
                       "这次没有按预算筛。可以用人民币或美元再说一次预算",
                       f"The budget is {u.amount:g} {u.currency}: only CN (CNY) and US (USD) store prices are "
                       "available and there is no currency conversion, so the budget was not applied this time. "
                       "Give the budget in CNY or USD to use it"))
    b = spec.budget
    if b is not None and spec.party_size > 1:
        regions = {m.region for m in spec.members}
        if b.scope == "team_total" and len(regions) > 1:
            notes.append(L("成员在不同的商店区，团队总额没法跨币种相加，这次只在同一区的花费里核对；可以改成每人预算",
                           "Members are in different store regions and a team total cannot add up different "
                           "currencies, so only spending in one region was checked; try a per-person budget"))
        skipped = [m.name for m in spec.members if not b.applies_to(m.region)]
        if b.scope == "per_person" and skipped:
            notes.append(L(f"预算是 {b.currency}，{'、'.join(skipped)}所在区用别的币种，没有按这个预算核对他们的花费",
                           f"The budget is in {b.currency}; {', '.join(skipped)} shop in a store with another "
                           "currency, so their spending was not checked against it"))
    return notes


def _pct(kb, a):
    v = kb.games.at[a, "pct_positive"]
    return None if v != v else int(v)
