"""Semantic rerank (design 5.5 '语义精排'): when the request states what the player wants in words, one batched LLM
call scores how well each shortlisted game fits those words. It only judges taste and feel; hard facts stay with
the rules. What is sent: the request text and public game facts (name, tags, short description). Never SteamIDs
or library data."""
import json

import numpy as np

from . import config as C
from .kb import KB, minmax
from .llm import chat_json

SYS = """You score how well each candidate Steam game fits what a player asked for, judging taste, feel, gameplay and theme only (player counts, prices and platforms are checked elsewhere; ignore them). Use the store facts given; do not reward popularity. 10 = exactly what they describe, 5 = partly, 0 = not what they want or something they said they dislike. Return JSON {"<id>": <0-10>, ...} covering every id."""


def candidates(kb: KB, rel, status_ok, details, n=None):
    """Top-N by the fused score, plus the best games by the sentence and feel channels alone (design 5.5 union)."""
    n = n or C.RERANK_N
    idx = np.flatnonzero(status_ok)
    pick = list(idx[np.argsort(-rel[idx], kind="stable")][:n])
    for key in ("pref", "feel"):
        for t in details.values():
            if isinstance(t, tuple) and key in t[1].parts:
                part = t[1].parts[key]
                pick += list(idx[np.argsort(-part[idx], kind="stable")][:C.RERANK_EXTRA])
    return list(dict.fromkeys(int(i) for i in pick))


def facts(kb: KB, i):
    a = int(kb.appids[i])
    tags = sorted(kb.tagset.get(a, set()), key=lambda t: -kb.tag_weight.get((a, t), 0))[:8]
    d = (kb.descriptions.get((a, "en")) or kb.descriptions.get((a, "zh")) or "")[:200]
    return {"name": kb.name[a], "tags": [kb.tag_en[t] for t in tags], "about": d}


def rerank(kb: KB, llm, text, rel, cand):
    """Returns a new relevance array: (1 - w_r) * rel + w_r * norm(LLM score) on the candidates, rel elsewhere
    scaled the same way so un-reranked games cannot jump ahead."""
    items = {f"g{k}": facts(kb, i) for k, i in enumerate(cand)}
    user = f"Player request:\n{text}\n\nCandidates:\n{json.dumps(items, ensure_ascii=False)}"

    def ok(obj):
        vals = {k: float(obj[k]) for k in items if k in obj}
        if len(vals) < 0.8 * len(items):
            raise ValueError("missing ids")
        return vals

    scores = chat_json(llm, SYS, user, "rerank", ok)
    s = np.zeros(kb.n, np.float32)
    mask = np.zeros(kb.n, bool)
    for k, i in enumerate(cand):
        if f"g{k}" in scores:
            s[i] = scores[f"g{k}"]
            mask[i] = True
    w = C.RERANK_W
    out = (1 - w) * rel
    out[mask] += w * minmax(s, mask)[mask]
    return out, {int(kb.appids[i]): float(s[i]) for i in np.flatnonzero(mask)}
