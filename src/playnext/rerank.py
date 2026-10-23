"""Semantic rerank (design 5.5 '语义精排'): when someone states in words what they want, one batched LLM call scores
how well each shortlisted game fits those words. Every target with words gets its own column ('me' for one
player; in a group each member with their own wishes and the shared request), so the group is aggregated after
the rerank (design: "成员的个人偏好句段逐人评分，共同要求另算共同匹配分"). It only judges taste and feel; hard facts
stay with the rules. What is sent: the request words and public game facts (name, tags, short description). Never
SteamIDs or library data."""
import json

import numpy as np

from . import config as C
from .kb import KB, minmax
from .llm import chat_json

SYS = """You score how well each candidate Steam game fits what a player asked for, judging taste, feel, gameplay and theme only (player counts, prices and platforms are checked elsewhere; ignore them). Use the store facts given; do not reward popularity. 10 = exactly what they describe, 5 = partly, 0 = not what they want or something they said they dislike. Return JSON {"<id>": <0-10>, ...} covering every id."""

SYS_MULTI = """You score how well each candidate Steam game fits what each person or group asked for, judging taste, feel, gameplay and theme only (player counts, prices and platforms are checked elsewhere; ignore them). Use the store facts given; do not reward popularity. 10 = exactly what they describe, 5 = partly, 0 = not what they want or something they said they dislike. Score every candidate for every request key. Return JSON {"<request key>": {"<id>": <0-10>, ...}, ...}."""


def candidates(kb: KB, rel, status_ok, details, n=None):
    """Top-N by the fused score, plus the best games by the feel channel alone (design 5.5 union)."""
    n = n or C.RERANK_N
    idx = np.flatnonzero(status_ok)
    pick = list(idx[np.argsort(-rel[idx], kind="stable")][:n])
    for t in details.values():
        if isinstance(t, tuple) and "feel" in t[1].parts:
            part = t[1].parts["feel"]
            pick += list(idx[np.argsort(-part[idx], kind="stable")][:C.RERANK_EXTRA])
    return list(dict.fromkeys(int(i) for i in pick))


def facts(kb: KB, i):
    a = int(kb.appids[i])
    tags = sorted(kb.tagset.get(a, set()), key=lambda t: -kb.tag_weight.get((a, t), 0))[:8]
    d = (kb.descriptions.get((a, "en")) or kb.descriptions.get((a, "zh")) or "")[:200]
    return {"name": kb.name[a], "tags": [kb.tag_en[t] for t in tags], "about": d}


def llm_scores(kb: KB, llm, texts: dict, cand, batches=None):
    """texts: target -> words. Returns target -> {row: 0-10 score}. One LLM call, or `batches` (default
    config.RERANK_BATCHES) parallel calls over consecutive slices of the candidates; the raw 0-10 scores of the
    slices are merged as they are, since the scale is fixed by the prompt (per-batch normalisation drifted more)."""
    b = max(1, min(batches or C.RERANK_BATCHES, len(cand)))
    if b == 1:
        return _llm_scores(kb, llm, texts, cand)
    from concurrent.futures import ThreadPoolExecutor
    parts = [[int(x) for x in p] for p in np.array_split(np.array(cand), b)]
    with ThreadPoolExecutor(b) as ex:
        got = list(ex.map(lambda p: _llm_scores(kb, llm, texts, p), parts))
    out = {}
    for g in got:
        for t, sc in g.items():
            out.setdefault(t, {}).update(sc)
    return out


def _llm_scores(kb: KB, llm, texts: dict, cand):
    items = {f"g{k}": facts(kb, i) for k, i in enumerate(cand)}
    keys = {f"r{j}": t for j, t in enumerate(texts)}

    def ok_one(obj):
        vals = {k: float(obj[k]) for k in items if isinstance(obj.get(k), (int, float))}
        if len(vals) < 0.8 * len(items):
            raise ValueError("missing ids")
        return vals

    if len(texts) == 1:
        (target, text), = texts.items()
        user = f"Player request:\n{text}\n\nCandidates:\n{json.dumps(items, ensure_ascii=False)}"
        out = {target: chat_json(llm, SYS, user, "rerank", ok_one)}
    else:
        reqs = {k: texts[t] for k, t in keys.items()}

        def ok_multi(obj):
            if not isinstance(obj, dict):
                raise ValueError("not an object")
            return {keys[k]: ok_one(obj.get(k) or {}) for k in keys}
        user = (f"Requests:\n{json.dumps(reqs, ensure_ascii=False)}\n\n"
                f"Candidates:\n{json.dumps(items, ensure_ascii=False)}")
        out = chat_json(llm, SYS_MULTI, user, "rerank", ok_multi)
    return {t: {cand[int(g[1:])]: v for g, v in vals.items()} for t, vals in out.items()}


def fuse(kb: KB, norm_t, scores: dict, w=None):
    """(1 - w_r) x the target's score + w_r x norm(LLM score) on the reranked games; the rest keep (1 - w_r) x their
    score, so games outside the rerank cannot jump ahead."""
    w = C.RERANK_W if w is None else w
    s = np.zeros(kb.n, np.float32)
    mask = np.zeros(kb.n, bool)
    for i, v in scores.items():
        s[i], mask[i] = v, True
    out = (1 - w) * norm_t
    out[mask] += w * minmax(s, mask)[mask]
    return out


def with_game_names(kb: KB, spec, text):
    """Append the official English names of the games the request names ("小丑牌" -> Balatro): a reranker model
    may not know local nicknames, the alias table does."""
    names = [kb.name[a] for a in dict.fromkeys(list(spec.seeds) + [x for m in spec.members for x in m.seeds + m.played_elsewhere])
             if a in kb.pos]
    return f"{text}\n(Games mentioned: {', '.join(names[:8])})" if names and text else text


def seed_words(kb: KB, seeds):
    """'Games like X' with no other words: the request the rerank judges is the reference games' own store facts
    (design 10.18; a library alone is still not reranked). None when no seed is in the core library."""
    ref = [facts(kb, kb.pos[a]) for a in dict.fromkeys(seeds) if a in kb.pos]
    if not ref:
        return None
    return "Games like these (the player's reference games, with their store facts):\n" + json.dumps(ref, ensure_ascii=False)


def targets_with_words(spec, kb: KB | None = None):
    """Which scoring targets have words to compare (design 5.5). With `kb` and config.RERANK_SEEDS, a target that
    has reference games but no words is reranked against those games' facts."""
    seeds = kb is not None and C.RERANK_SEEDS
    if spec.party_size == 1:
        m = spec.members[0]
        if spec.preference_text or spec.feel_want or spec.feel_avoid or m.preference_text:
            return {"me": spec.request_text or spec.preference_text or m.preference_text}
        words = seeds and seed_words(kb, list(spec.seeds) + list(m.seeds))
        return {"me": words} if words else {}
    out = {}
    if spec.preference_text or spec.feel_want or spec.feel_avoid:
        out["shared"] = spec.request_text or spec.preference_text
    elif seeds and (words := seed_words(kb, spec.seeds)):
        out["shared"] = words
    for i, m in enumerate(spec.members):
        if m.preference_text:
            out[i] = m.preference_text
        elif seeds and (words := seed_words(kb, m.seeds)):
            out[i] = words
    return out
