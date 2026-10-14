"""Conflict analyser (design 5.5): when nothing passes, find the cheapest relaxations.

Step 2 runs once; each game gets a bit mask of the relaxable rules it fails (UNKNOWN counts as its own bit).
A game becomes available under relaxation set S when its mask is a subset of S and it fails no fixed rule.
Counts for all 2^k subsets come from one subset-sum (zeta) transform, O(k 2^k). Content avoidance is never relaxed.
Changing the setup or dropping a member re-runs Step 2 with the changed spec, as those change the rules themselves.
"""
import numpy as np

from .kb import KB
from .rules import FAIL, PASS, UNKNOWN, FilterResult, hard_filter
from .spec import Budget, SessionSpec

COST = {"unknown": 1, "mechanics": 1, "discount": 1, "budget": 2, "setup": 3, "people": 4}
LABEL = {"unknown": "接受“待确认”的游戏（有字段缺失）", "mechanics": "允许其中一种玩法是次要元素",
         "discount": "不限“正在打折”"}


def subset_counts(masks, k):
    f = np.bincount(masks, minlength=1 << k).astype(np.int64)
    for b in range(k):
        bit = 1 << b
        for s in range(1 << k):
            if s & bit:
                f[s] += f[s ^ bit]
    return f


def analyse(kb: KB, spec: SessionSpec, fr: FilterResult, rel=None, limit=5):
    rules = [r for r in fr.rules if r.relaxable and r.key in ("budget", "mechanics", "discount")]
    fixed = [r for r in fr.rules if not (r.relaxable and r.key in ("budget", "mechanics", "discount"))]
    keys = [r.key for r in rules] + ["unknown"]
    k = len(keys)
    fixed_fail = np.zeros(kb.n, bool)
    unknown_any = np.zeros(kb.n, bool)
    for r in fixed:
        fixed_fail |= r.status == FAIL
        unknown_any |= r.status == UNKNOWN
    masks = np.zeros(kb.n, np.int64)
    for b, r in enumerate(rules):
        masks |= (r.status == FAIL).astype(np.int64) << b
        unknown_any |= r.status == UNKNOWN
    masks |= unknown_any.astype(np.int64) << (k - 1)
    ok = ~fixed_fail
    counts = subset_counts(masks[ok], k)
    out = []
    for s in range(1, 1 << k):
        if counts[s] == 0:
            continue
        names = [keys[b] for b in range(k) if s >> b & 1]
        avail = ok & ((masks & ~s) == 0)
        items = []
        for key in names:
            if key == "budget":
                need = _min_budget(kb, spec, fr, avail)
                items.append({"key": "budget", "text": f"预算提高到 ¥{need:g}" if need else "放宽预算", "value": need})
            else:
                items.append({"key": key, "text": LABEL[key]})
        out.append({"changes": items, "count": int(counts[s]), "cost": sum(COST[x] for x in names),
                    "examples": _examples(kb, avail, rel)})
    if spec.party_size > 1:
        out += _setup_alternatives(kb, spec, rel)
    out.sort(key=lambda x: (x["cost"], -x["count"]))
    # drop supersets of an already listed cheaper suggestion
    keep = []
    for o in out:
        ks = {c["key"] for c in o["changes"]}
        if not any({c["key"] for c in p["changes"]} <= ks for p in keep):
            keep.append(o)
    return keep[:limit]


def _min_budget(kb, spec, fr, avail):
    r = next((r for r in fr.rules if r.key == "budget"), None)
    if r is None:
        return None
    vals = []
    m = spec.members[0]
    for i in np.flatnonzero(avail & (r.status == FAIL)):
        p = kb.price(int(kb.appids[i]), m.region)
        if p is not None and p["final"] == p["final"]:
            vals.append(float(p["final"]))
    return min(vals) if vals else None


def _examples(kb, avail, rel, n=3):
    idx = np.flatnonzero(avail)
    if rel is not None:
        idx = idx[np.argsort(-rel[idx])]
    else:
        idx = idx[np.argsort(-kb.quality[idx] * np.log1p(kb.review_count[idx]))]
    return [kb.display_name(int(kb.appids[i])) for i in idx[:n]]


def _setup_alternatives(kb, spec, rel):
    out = []
    current = set(spec.setup_types)
    for kind, text in (("remote", "改用远程同乐（只需主机拥有）"), ("online", "改成各自在家在线联机")):
        if kind in current:
            continue
        alt = spec.model_copy(update={"sites": None, "setup_hint": kind})
        fr = hard_filter(kb, alt)
        n = int((fr.status == PASS).sum())
        if n:
            out.append({"changes": [{"key": "setup", "text": text}], "count": n, "cost": COST["setup"],
                        "examples": _examples(kb, fr.status == PASS, rel)})
    if spec.budget is not None:
        alt = spec.model_copy(update={"budget": None})
        fr = hard_filter(kb, alt)
        n = int((fr.status == PASS).sum())
        if n:
            out.append({"changes": [{"key": "budget", "text": "不设预算"}], "count": n, "cost": COST["budget"],
                        "examples": _examples(kb, fr.status == PASS, rel)})
    if spec.party_size > 2:
        alt = spec.model_copy(update={"members": spec.members[:-1], "sites": None})
        fr = hard_filter(kb, alt)
        n = int((fr.status == PASS).sum())
        if n:
            out.append({"changes": [{"key": "people", "text": f"少 1 人（{spec.party_size - 1} 人）"}], "count": n,
                        "cost": COST["people"], "examples": _examples(kb, fr.status == PASS, rel)})
    if not spec.accept_unknown:
        alt = spec.model_copy(update={"accept_unknown": True})
        fr = hard_filter(kb, alt)
        n = int((fr.status == PASS).sum())
        if n:
            out.append({"changes": [{"key": "unknown", "text": LABEL["unknown"]}], "count": n, "cost": COST["unknown"],
                        "examples": _examples(kb, fr.status == PASS, rel)})
    return out
