"""Step 3: channels, fusion and personal / group scores (design 5.5).

All channel scores are computed for every core game, then min-max normalised over the candidate pool (games that
passed or are UNKNOWN in Step 2) and fused with convex weights. Each channel keeps the evidence the card needs.
"""
from dataclasses import dataclass, field

import numpy as np

from . import config as C
from .kb import KB, minmax
from .spec import Member, SessionSpec


@dataclass
class Taste:
    """One scoring target: a member, the shared requirement, or the single user."""
    anchors: dict = field(default_factory=dict)      # appid -> weight (seeds 1.0, library = playtime percentile)
    preference_text: str | None = None
    feel_want: list = field(default_factory=list)
    feel_avoid: list = field(default_factory=list)
    library: dict = field(default_factory=dict)      # library anchors used only as a bonus inside the seed pool

    @property
    def empty(self):
        return not (self.anchors or self.preference_text or self.feel_want or self.feel_avoid or self.library)


@dataclass
class Scored:
    score: np.ndarray                 # fused personal score (before pool normalisation)
    parts: dict                       # channel -> normalised array
    has: dict                         # channel -> bool array: channel available for the game
    evidence: dict


def library_anchors(kb: KB, member: Member) -> dict:
    """Design 4.1: Steam playtime > 0 is an anchor with weight = playtime percentile; hidden playtime -> none."""
    lib = member.library
    if lib is None or lib.playtime_hidden:
        return {}
    out = {}
    for a, h in lib.owned.items():
        if h > 0 and a in kb.pos:
            p = kb.playtime_pct(a, h)
            if p is None:
                continue
            if p > 0:
                out[a] = round(p, 3)
    if len(out) > C.MAX_LIBRARY_ANCHORS:
        out = dict(sorted(out.items(), key=lambda kv: -kv[1])[:C.MAX_LIBRARY_ANCHORS])
    return out


def member_taste(kb: KB, m: Member, extra_seeds=(), pref=None, want=(), avoid=()) -> Taste:
    seeds = [a for a in list(m.seeds) + list(extra_seeds) if a in kb.pos]
    lib = library_anchors(kb, m)
    t = Taste(preference_text=pref or m.preference_text, feel_want=list(want) or m.feel_want,
              feel_avoid=list(avoid) or m.feel_avoid)
    if seeds:  # explicit seeds decide the candidates; the library only re-ranks inside the seed pool
        t.anchors = {a: 1.0 for a in seeds}
        t.library = {a: w for a, w in lib.items() if a not in t.anchors}
    else:
        t.anchors = lib
    return t


def _wagg(sim, w, how):
    ws = sim * w[:, None]
    if how == "sum":
        return ws.sum(0), ws.argmax(0)
    return ws.max(0), ws.argmax(0)


def channel_scores(kb: KB, taste: Taste, pool: np.ndarray, pref_vec=None) -> Scored:
    a_ids = [a for a in taste.anchors if a in kb.pos]
    rows = [kb.pos[a] for a in a_ids]
    w = np.array([taste.anchors[a] for a in a_ids], np.float32)
    n = kb.n
    zeros, none = np.zeros(n, np.float32), np.zeros(n, bool)
    ev = {"anchors": a_ids}
    raw, has = {}, {}
    if a_ids:
        raw["tag"], ev["tag_hit"] = _wagg(kb.T[rows] @ kb.T.T, w, C.TAG_AGG)
        has["tag"] = kb.T_has
        d, ev["desc_hit"] = _wagg(kb.desc_sim(rows=rows), w, C.DESC_AGG)
        contrib = kb.ease_rows(a_ids) * w[:, None]
        raw["colike"], ev["co_hit"] = contrib.sum(0), contrib.argmax(0)
        ev["co_contrib"] = contrib
        has["colike"] = kb.ease_has & any(int(a) in kb._ease[1] for a in a_ids)
        same_dev, same_ser, sim = kb.lineage(a_ids)
        parts = {"dev": same_dev, "ser": same_ser, "sim": sim}
        linked = set().union(*(parts[p] for p in C.LINEAGE_PARTS))
        raw["lineage"] = np.isin(kb.appids, list(linked)).astype(np.float32)
        has["lineage"] = np.ones(n, bool)
        ev.update(same_dev=same_dev, same_ser=same_ser, igdb_sim=sim)
    else:
        d = None
        for c in ("tag", "colike", "lineage"):
            raw[c], has[c] = zeros, none
    if pref_vec is not None:
        dp = kb.desc_sim(query=pref_vec)
        ev["d_pref"] = dp
        desc = dp if d is None else (1 - C.PREF_W) * minmax(d, pool & kb.E_has) + C.PREF_W * minmax(dp, pool & kb.E_has)
    else:
        desc = d if d is not None else zeros
    raw["desc"] = desc
    has["desc"] = kb.E_has if (d is not None or pref_vec is not None) else none
    norm = {c: (raw[c] if c == "lineage" else minmax(raw[c], pool & has[c])) for c in raw}
    W = C.WEIGHTS
    wsum = sum(W[c] * has[c] for c in W)
    content = has["tag"] | has["desc"] | has["colike"]  # lineage alone (a 0/1 feature) must not carry a game
    fused = np.where(content, sum(W[c] * norm[c] * has[c] for c in W) / np.maximum(wsum, 1e-9), 0).astype(np.float32)
    if taste.feel_want or taste.feel_avoid:
        f = feel_raw(kb, taste.feel_want, taste.feel_avoid)
        fn = minmax(f, pool & kb.T_has)
        norm["feel"], has["feel"] = fn, kb.T_has
        fused = np.where(content, (1 - C.FEEL_W) * fused + C.FEEL_W * fn, fn * kb.T_has).astype(np.float32)
        ev["feel_tags"] = (list(taste.feel_want), list(taste.feel_avoid))
    return Scored(fused, norm, has, ev)


def feel_raw(kb: KB, want, avoid):
    """Feel(g) = mean wanted-tag weight - mean avoided-tag weight (absent tag = 0)."""
    out = np.zeros(kb.n, np.float32)
    if want:
        out += kb.tag_weights(want).mean(0)
    if avoid:
        out -= kb.tag_weights(avoid).mean(0)
    return out


def personal(kb: KB, taste: Taste, pool, encoder=None) -> Scored:
    pref_vec = encoder(taste.preference_text) if (taste.preference_text and encoder) else None
    s = channel_scores(kb, taste, pool, pref_vec)
    if taste.library and taste.anchors:
        lib = channel_scores(kb, Taste(anchors=taste.library), pool)
        seed_pool = np.zeros(kb.n, bool)
        seed_pool[np.argsort(-np.where(pool, s.score, -np.inf))[:C.SEED_POOL]] = True
        bonus = minmax(lib.score, seed_pool) * seed_pool
        s.evidence["lib_bonus"] = bonus
        s.evidence["lib_anchor"] = [lib.evidence["anchors"][k] for k in lib.evidence["co_hit"]]
        s.score = s.score + C.LIB_BONUS * bonus
    return s


def group_aggregate(user_scores: list, method=None):
    """user_scores: list of pool-normalised arrays. Design 5.5: 0.6 mean + 0.4 min (baseline) or Nash."""
    U = np.stack(user_scores)
    method = method or C.GROUP_METHOD
    if method == "nash":
        return np.exp(np.log(np.maximum(C.NASH_EPS, U)).mean(0))
    if method == "lexmin":
        return U.min(0) + 1e-3 * U.mean(0)
    return C.GROUP_MEAN_W * U.mean(0) + C.GROUP_MIN_W * U.min(0)


def relevance(kb: KB, spec: SessionSpec, pool: np.ndarray, encoder=None):
    """Final liking score per game (design 5.5 'final liking score'), plus per-target details for cards."""
    if spec.party_size == 1:
        m = spec.members[0]
        taste = member_taste(kb, m, spec.seeds, spec.preference_text, spec.feel_want, spec.feel_avoid)
        if taste.empty:
            return None, {}
        s = personal(kb, taste, pool, encoder)
        return minmax(s.score, pool), {"me": (taste, s)}
    details, users = {}, []
    for i, m in enumerate(spec.members):
        if m.has_taste:
            t = member_taste(kb, m)
            s = personal(kb, t, pool, encoder)
            details[i] = (t, s)
            users.append(minmax(s.score, pool))
    shared = None
    if spec.has_shared:
        t = Taste(anchors={a: 1.0 for a in spec.seeds if a in kb.pos}, preference_text=spec.preference_text,
                  feel_want=spec.feel_want, feel_avoid=spec.feel_avoid)
        s = personal(kb, t, pool, encoder)
        details["shared"] = (t, s)
        shared = minmax(s.score, pool)
    if users and shared is not None:
        rel = (1 - C.SHARED_W) * group_aggregate(users) + C.SHARED_W * shared
    elif users:
        rel = group_aggregate(users)
    elif shared is not None:
        rel = shared
    else:
        return None, {}
    details["user_scores"] = users
    return minmax(rel, pool), details
