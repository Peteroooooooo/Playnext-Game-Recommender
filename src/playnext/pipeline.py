"""The whole recommendation trunk (design 5.1): Step 1 understand -> 2 hard rules -> 3 scores -> 4 ranking ->
5 cards; Step 6 patches the spec and reruns. Every step is timed for the latency report (design 7)."""
import time
from dataclasses import dataclass, field

import numpy as np

from . import config as C
from .cards import build_card, price_facts, write_reasons
from .kb import KB
from .pricing import Prices
from .ranking import rank
from .relax import analyse
from .rules import PASS, UNKNOWN, hard_filter
from .scoring import relevance
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

    def to_dict(self):
        return {"understood": self.understood, "picks": self.picks, "backups": self.backups, "unknown": self.unknown,
                "rules": self.rules, "relax": self.relax, "timings": self.timings, "notes": self.notes,
                "need_input": self.need_input}


class Recommender:
    def __init__(self, kb: KB | None = None, llm=None, encoder=None, live_prices=True, reasons=True):
        self.kb = kb or KB()
        self.llm = llm
        self.encoder = encoder
        self.prices = Prices(self.kb, live=live_prices)
        self.understander = Understander(self.kb, llm) if llm else None
        self.reasons = reasons

    # ---------- Step 1 / Step 6 ----------
    def understand(self, text, base: SessionSpec | None = None, parsed: ParsedRequest | None = None):
        if self.understander is None:
            raise RuntimeError("no LLM configured: build the SessionSpec directly")
        p = self.understander.patch(parsed, text) if parsed is not None else self.understander.parse(text)
        spec = self.understander.to_spec(p, text if parsed is None else (base.request_text + " / " + text), base)
        return p, spec

    # ---------- Steps 2-5 ----------
    def recommend(self, spec: SessionSpec) -> Result:
        kb, t = self.kb, {}
        t0 = time.time()
        fr = hard_filter(kb, spec)
        notes = []
        if spec.mechanics and not (fr.status == PASS).any():
            notes.append("没有游戏同时把这几种玩法都作为核心标签，已放宽为“其中一种是核心、其余是次要”")
            relaxed = spec.model_copy(update={"mechanics": []})
            fr = hard_filter(kb, relaxed)
            must = set(spec.mechanics)
            st = fr.status.copy()
            for i, a in enumerate(kb.appids):
                tags, core = kb.tagset.get(int(a), set()), set(kb.core.get(int(a), []))
                if not (must <= tags and must & core):
                    st[i] = 0
            fr.status = st
        t["hard_filter"] = round(time.time() - t0, 3)
        pool = fr.status >= UNKNOWN
        t1 = time.time()
        rel, details = relevance(kb, spec, pool, self.encoder)
        t["scoring"] = round(time.time() - t1, 3)
        understood = describe(kb, spec)
        if rel is None:
            return Result(spec, understood, [], [], [], fr.summary(), timings=t, notes=notes,
                          need_input="还不知道你的口味：说一两款喜欢的游戏、想要的感觉，或者连上 Steam 库")
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
        ranked = rank(kb, spec, rel, fr, self.prices)
        t["ranking_and_live_prices"] = round(time.time() - t2, 3)
        t3 = time.time()
        picks = [build_card(kb, spec, i, rel, ranked, details, fr, self.prices, ranked.steps[k])
                 for k, i in enumerate(ranked.picks)]
        if self.reasons:
            write_reasons(picks, self.llm, spec.request_text)
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
        t["total"] = round(time.time() - t0, 3)
        llm_calls = getattr(self.llm, "calls", None)
        if llm_calls:
            t["llm_calls"] = list(llm_calls)
        return Result(spec, understood, picks, backups, unknown, fr.summary(), relax, t, notes)

    def ask(self, text, base: SessionSpec | None = None, parsed: ParsedRequest | None = None):
        t0 = time.time()
        p, spec = self.understand(text, base, parsed)
        if base is not None:  # keep what the user connected or ticked
            for m_new, m_old in zip(spec.members, base.members):
                m_new.library = m_new.library or m_old.library
        res = self.recommend(spec)
        res.timings["understand"] = round(time.time() - t0 - res.timings.get("total", 0), 3)
        return p, res


def _pct(kb, a):
    v = kb.games.at[a, "pct_positive"]
    return None if v != v else int(v)
