"""The whole recommendation trunk (design 5.1): Step 1 understand -> 2 hard rules -> 3 scores -> 4 ranking ->
5 cards; Step 6 patches the spec and reruns. Every step is timed for the latency report (design 7)."""
import time
from dataclasses import dataclass, field

import numpy as np

from . import appindex, config as C
from .cards import build_card, price_facts, write_reasons
from .aliases import Resolver
from .kb import KB, minmax
from .pricing import Prices
from .ranking import rank
from .relax import analyse
from .rerank import candidates, fuse, llm_scores, targets_with_words, with_game_names
from .rules import (CAT_LOCAL_COOP, CAT_LOCAL_PVP, CAT_ONLINE_COOP, CAT_ONLINE_PVP, CAT_REMOTE, CAT_SHARED, FAIL, PASS,
                    UNKNOWN, hard_filter)

MP_CATS = {CAT_ONLINE_COOP, CAT_ONLINE_PVP, CAT_LOCAL_COOP, CAT_LOCAL_PVP, CAT_SHARED, CAT_REMOTE}
from .scoring import combine, relevance
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
    def __init__(self, kb: KB | None = None, llm=None, encoder=None, live_prices=True, reasons=True, rerank=True,
                 paths=None):
        self.kb = kb or KB()
        self.llm = llm
        self.encoder = encoder
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
        p = self.understander.patch(parsed, text) if parsed is not None else self.understander.parse(text)
        spec = self.understander.to_spec(p, text if parsed is None else (base.request_text + " / " + text), base)
        return p, spec

    # ---------- Steps 2-5 ----------
    def recommend(self, spec: SessionSpec, rerank_scores: dict | None = None, rerank_w: float | None = None) -> Result:
        """rerank_scores / rerank_w are for evaluation: reuse cached rerank scores ({target: {appid: score}}, from
        any reranker) and try other fusion weights without new model calls."""
        kb, t = self.kb, {}
        t0 = time.time()
        fr = hard_filter(kb, spec)
        notes = []
        secondary = np.zeros(kb.n, bool)
        n_strict = int((fr.status == PASS).sum()) if spec.mechanics else C.PICK
        if n_strict < C.PICK:
            # design 4.3 fallback: too few games have every wanted mechanic as a core tag, so games where at least one
            # is core and the rest are present fill the remaining places, always after the strict ones
            notes.append("没有游戏同时把这几种玩法都作为核心标签，已放宽为“其中一种是核心、其余是次要”" if n_strict == 0 else
                         f"同时把这几种玩法都作为核心标签的只有 {n_strict} 款，后面补上“其中一种是核心、其余是次要”的")
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
            notes.append(f"《{appindex.name_of(a) or a}》在 Steam 上，但不在核心库（评测不到 1,000 条或已下架），"
                         "没有同好数据，只按它的标签和介绍找相似的")
        pool = fr.status >= UNKNOWN
        t1 = time.time()
        rel, details = relevance(kb, spec, pool, self.encoder)
        t["scoring"] = round(time.time() - t1, 3)
        debug = {}
        texts = {k: (with_game_names(kb, spec, v) if C.RERANK_GAME_NAMES else v)
                 for k, v in targets_with_words(spec).items() if k in details.get("norm", {})}
        if rel is not None and texts and (rerank_scores is not None or (self.llm is not None and C.RERANK and self.rerank)):
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
                notes.append("语义精排暂不可用，结果只按标签、介绍与同好打分")
            t["rerank"] = round(time.time() - t1, 3)
        understood = describe(kb, spec)
        if rel is None:
            if not (fr.status == PASS).any():
                return Result(spec, understood, [], [], [], fr.summary(), analyse(kb, spec, fr), timings=t, notes=notes,
                              failed=self.failed_list(spec, fr), debug=debug)
            # no taste at all (design 5.5 'cold start'): the conditions alone still deserve an answer, so rank the
            # passing games by smoothed rating x log(reviews) and ask for a seed on the page
            rel = minmax(_prior(kb), pool)
            details = {}
            notes.append("还不知道你们的口味，先按口碑和评测数排了一版；说一两款喜欢的游戏或想要的感觉，会更准")
        for m in spec.members:
            if m.library and not m.library.is_public:
                notes.append(f"{m.name}的 Steam 游戏详情不公开，读不到库；可以在 Steam 隐私设置里把“游戏详情”改为公开，或直接点选喜欢的游戏")
            elif m.library and m.library.playtime_hidden:
                notes.append(f"{m.name}的游戏时长都是 0，看起来隐藏了游玩时间：库只用来标“已拥有”，不当口味参考")
        if spec.ambiguous:
            for name, cands in spec.ambiguous.items():
                if len(cands) > 1:
                    notes.append(f"“{name}”按《{kb.display_name(cands[0])}》理解，另有 {len(cands) - 1} 个版本，可以改")
        t2 = time.time()
        ranked = rank(kb, spec, rel - 2.0 * secondary if secondary.any() else rel, fr, self.prices)
        t["ranking_and_live_prices"] = round(time.time() - t2, 3)
        t3 = time.time()
        picks = [build_card(kb, spec, i, rel, ranked, details, fr, self.prices, ranked.steps[k])
                 for k, i in enumerate(ranked.picks)]
        for c in picks:
            if secondary[kb.pos[c["appid"]]]:
                c["mechanics_note"] = "其中一种玩法是次要元素（玩家标签票数没到核心标签的线）"
        if self.paths is not None:
            todo = [c for c in picks if c.get("anchor_appid")]
            for c, path in zip(todo, self.paths.many([(c["anchor_appid"], c["appid"]) for c in todo])):
                if path:
                    c["lineage_path"] = {"text": path, "source": "PostgreSQL 递归路径查询（开发商 / 系列 / IGDB 相似）"}
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
                item["label"] = "暂无好评率" if item["pct_positive"] is None else f"口碑褒贬不一：{item['pct_positive']}% 好评"
            if any(m.library and a in m.library.owned for m in spec.members):
                item["owned"] = "已在 Steam 库里，Steam 上没有游玩记录" if spec.party_size == 1 else "有成员已拥有"
            if ranked.folded.get(i):
                item["same_series"] = len(ranked.folded[i])
                item["series_names"] = [kb.display_name(int(kb.appids[j])) for j in ranked.folded[i]]
            if spec.party_size > 1 and fr.best_setup.get(a):
                item["setup"] = fr.best_setup[a]
            backups.append(item)
        unknown = [{"appid": int(kb.appids[i]), "name": kb.display_name(int(kb.appids[i])),
                    "why": fr.unknown_why(i, int(kb.appids[i]))} for i in ranked.unknown]
        relax = []
        if not picks:
            relax = analyse(kb, spec, fr, rel)
        dropped = [{"name": kb.display_name(int(kb.appids[i])), "why": w} for i, w in ranked.dropped_live]
        if dropped:
            notes.append("实时价格复核后移出：" + "；".join(f"《{d['name']}》{d['why']}" for d in dropped[:3]))
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
            if r.key in ("exclude", "exclude_owned"):
                skip |= r.status == FAIL
            else:
                broke |= r.status == FAIL
        cand = broke & ~skip
        if spec.party_size > 1:
            # for a group, "no multiplayer mode at all" is not a near miss worth showing; games that have one but
            # fall short (players, mode, budget, content) are
            mp = np.array([bool(kb.categories.get(int(a), set()) & MP_CATS) for a in kb.appids])
            cand &= mp
        if not cand.any():
            return []
        wide = (fr.status >= UNKNOWN) | cand
        rel, _ = relevance(kb, spec, wide, self.encoder)
        if rel is None:
            rel = minmax(_prior(kb), wide)
        idx = np.flatnonzero(cand)
        idx = idx[np.argsort(-rel[idx], kind="stable")][:C.FAILED_SHOW]
        keys = {"exclude", "exclude_owned"}
        out = []
        for i in idx:
            a = int(kb.appids[i])
            why = [r.reason.get(a, r.label) for r in fr.rules if r.status[i] == FAIL and r.key not in keys]
            out.append({"appid": a, "name": kb.display_name(a), "why": why, "relevance": round(float(rel[i]), 3)})
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


def _prior(kb):
    return (kb.quality * np.log1p(kb.review_count)).astype(np.float32)


def _budget_notes(spec: SessionSpec):
    """Say when a stated budget could not be applied: prices are compared only within one store currency."""
    notes = []
    u = spec.budget_unsupported
    if u is not None:
        notes.append(f"预算写的是 {u.amount:g} {u.currency}：目前只有国区（人民币）和美区（美元）的价格，不做汇率换算，"
                     "这次没有按预算筛。可以用人民币或美元再说一次预算")
    b = spec.budget
    if b is not None and spec.party_size > 1:
        regions = {m.region for m in spec.members}
        if b.scope == "team_total" and len(regions) > 1:
            notes.append("成员在不同的商店区，团队总额没法跨币种相加，这次只在同一区的花费里核对；可以改成每人预算")
        skipped = [m.name for m in spec.members if not b.applies_to(m.region)]
        if b.scope == "per_person" and skipped:
            notes.append(f"预算是 {b.currency}，{'、'.join(skipped)}所在区用别的币种，没有按这个预算核对他们的花费")
    return notes


def _pct(kb, a):
    v = kb.games.at[a, "pct_positive"]
    return None if v != v else int(v)
