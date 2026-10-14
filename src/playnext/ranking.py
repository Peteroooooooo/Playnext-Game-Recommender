"""Step 4: series folding, shortlist with live price re-check, rating floor, relevance window, MMR (design 5.5)."""
from dataclasses import dataclass, field

import numpy as np

from . import config as C
from .kb import KB
from .pricing import Prices, price_pref
from .rules import PASS, UNKNOWN, FilterResult
from .spec import SessionSpec


@dataclass
class Ranked:
    picks: list                      # row indices, in order
    steps: list                      # per pick: window size, redundancy, base score
    shortlist: list                  # row indices after folding and price re-check
    base: dict                       # row -> window score
    folded: dict                     # row -> [rows folded under it]
    unknown: list                    # row indices for the "to confirm" group
    dropped_live: list = field(default_factory=list)  # (row, reason) removed by the live price re-check


def fold_series(kb: KB, order, limit):
    """Keep the best game of each IGDB collection; fold the rest under it (design 5.5 step 0)."""
    kept, folded, seen = [], {}, {}
    for i in order:
        s = kb.series_of.get(int(kb.appids[i]), set())
        owner = next((seen[x] for x in s if x in seen), None)
        if owner is not None:
            folded.setdefault(owner, []).append(int(i))
            continue
        if len(kept) < limit:
            kept.append(int(i))
            for x in s:
                seen[x] = int(i)
    return kept, folded


def _live_ok(kb: KB, spec: SessionSpec, fr: FilterResult, prices: Prices, i):
    """Budget re-check with live prices; returns None when fine, else a reason."""
    if spec.budget is None and not spec.only_discounted:
        return None
    a = int(kb.appids[i])
    if spec.party_size == 1:
        m = spec.members[0]
        if m.owns(a):
            return None
        p = prices.get(a, m.region)
        if p is None or p["is_free"]:
            return None
        if spec.only_discounted and not p["discount_pct"]:
            return "实时价格：已不在打折"
        if spec.budget and p["final"] is not None and p["final"] > spec.budget.amount:
            return f"实时价格 ¥{p['final']:g} 超出预算"
        return None
    kind = fr.best_setup.get(a)
    plan = fr.setups[kind].plan.get(a) if kind else None
    if not plan or spec.budget is None:
        return None
    costs = {}
    for b in plan["buyers"]:
        p = prices.get(a, spec.members[b].region)
        if p and p["final"] is not None:
            costs[b] = p["final"]
    if spec.budget.scope == "per_person" and any(v > spec.budget.amount for v in costs.values()):
        return f"实时价格超出每人预算 ¥{spec.budget.amount:g}"
    if spec.budget.scope == "team_total" and sum(costs.values()) > spec.budget.amount:
        return f"实时价格合计超出团队预算 ¥{spec.budget.amount:g}"
    return None


def window_score(kb: KB, spec: SessionSpec, prices: Prices, i, rel):
    a = int(kb.appids[i])
    terms = [(C.BASE_W["relevance"], float(rel[i])), (C.BASE_W["quality"], float(kb.quality[i]))]
    if spec.price_intent != "none":
        region = spec.members[0].region
        p = prices.get(a, region)
        if spec.price_intent == "near_record_low":
            pp = price_pref(p)
        else:  # cheap: cheaper is better, free = 1, >= 200 = 0
            pp = None if p is None else (1.0 if p["is_free"] else (None if p["final"] is None else max(0.0, 1 - p["final"] / 200)))
        if pp is not None:
            terms.append((C.BASE_W["price"], pp))
    if spec.library_policy == "prefer_owned":
        terms.append((C.PREFER_OWNED_W, 1.0 if any(m.owns(a) for m in spec.members) else 0.0))
    if spec.max_hours:
        ttb = kb.time_to_beat["normally"].get(a) if a in kb.time_to_beat.index else None
        if ttb is not None and ttb == ttb:
            terms.append((C.SHORT_W, 1.0 if ttb <= spec.max_hours else max(0.0, 1 - (ttb - spec.max_hours) / spec.max_hours)))
    return sum(w * v for w, v in terms) / sum(w for w, _ in terms)


def rank(kb: KB, spec: SessionSpec, rel, fr: FilterResult, prices: Prices, delta=None, mmr_lambda=None,
         floor=True, fold=True, pick=None) -> Ranked:
    delta = C.DELTA if delta is None else delta
    lam = C.MMR_LAMBDA if mmr_lambda is None else mmr_lambda
    pick = pick or C.PICK
    status = fr.status
    pass_idx = np.flatnonzero(status == PASS)
    order = pass_idx[np.argsort(-rel[pass_idx], kind="stable")]
    head = order[:C.SHORTLIST * 10]
    if fold:
        kept, folded = fold_series(kb, head, C.SHORTLIST * 3)
    else:
        kept, folded = [int(i) for i in head[:C.SHORTLIST * 3]], {}
    # live prices only for the shortlist (plus a reserve for games the re-check removes)
    regions = {m.region for m in spec.members}
    for r in regions:
        prices.fetch([int(kb.appids[i]) for i in kept[:C.SHORTLIST + 10]], r)
    short, dropped = [], []
    for i in kept:
        why = _live_ok(kb, spec, fr, prices, i)
        if why:
            dropped.append((i, why))
            continue
        short.append(i)
        if len(short) >= C.SHORTLIST:
            break
    base = {i: window_score(kb, spec, prices, i, rel) for i in short}
    chosen, steps, remaining = [], [], set(short)
    while len(chosen) < pick and remaining:
        rated = {r for r in remaining if kb.rating_ok[r]} if floor else set(remaining)
        rated = rated or remaining
        top = max(rel[r] for r in rated)
        window = [r for r in rated if rel[r] >= top - delta]

        def mmr(r):
            red = max((float(kb.T[r] @ kb.T[c]) for c in chosen), default=0.0)
            return lam * base[r] - (1 - lam) * red, red
        best = max(window, key=lambda r: (mmr(r)[0], rel[r]))
        steps.append({"window": len(window), "redundancy": round(mmr(best)[1], 2), "base": round(base[best], 3)})
        chosen.append(best)
        remaining.discard(best)
    unk_idx = np.flatnonzero(status == UNKNOWN)
    unknown = []
    if len(unk_idx):
        # only games that would have reached the shortlist on liking alone
        cut = rel[short[-1]] if short else 0.0
        cand = unk_idx[np.argsort(-rel[unk_idx], kind="stable")]
        unknown = [int(i) for i in cand if rel[i] >= cut][:C.UNKNOWN_SHOW]
    return Ranked(chosen, steps, short, base, folded, unknown, dropped)
