"""Simulate the user inputs (seed questionnaire, free text via LLM, Steam library, and library + free text) on the real knowledge base.

Each path runs Steps 1-4 of the design (understand -> hard filter -> score -> rank) and records every
intermediate number into .cache/simulate_inputs.json, which docs/data_overview.html quotes.
What is simulated rather than real:
  - the Steam library is made up (no real SteamID is queried); GetOwnedGames is mocked with the same JSON shape;
  - prices come from the 2026-10 snapshot, not a live query; there is no seed alias table yet, so the LLM's
    English title is matched against store names;
  - channel weights, delta and the Beta prior are demo values, not tuned.
Library rule (design 4.1, 2026-10-14): only Steam's own record is used. Steam playtime > 0 = launched on Steam
(excluded, anchor weight = playtime percentile); 0 = no Steam record (may be recommended, labelled as such);
play elsewhere is only known when the user says so. Rating floor (design 5.5): Steam positive share < 70%
or missing never reaches the top 5 unless too few games pass it.
The description channel uses the English demo vectors cached by demo_walkthrough.py (run that first).
Review data comes from the merged review table (build_review_tables.py): the co-like channel is the EASE score
summed over anchors (design 5.5), card statistics come from colike_reviews100m, and library anchor weights are
percentiles in playtime_reference_100m.
Usage: uv run python scripts/simulate_inputs.py [--no-llm]
"""
import json
import re
import sys
import time

import numpy as np
import pandas as pd

from check_keys import ROOT, load_env

PROC = ROOT / "data" / "processed"
DER = ROOT / "data" / "derived"
OUT = ROOT / ".cache" / "simulate_inputs.json"
EMB_CACHE = ROOT / ".cache" / "demo_desc_emb_en_512.npz"
MODEL = ROOT / ".cache" / "models" / "Qwen3-Embedding-4B"

WEIGHTS = {"tag": 0.30, "desc": 0.25, "colike": 0.30, "lineage": 0.15}
DELTA, SHORTLIST, PICK, UNKNOWN_SHOW = 0.10, 20, 5, 2
ALPHA, BETA = 24.6, 5.4
RATING_FLOOR = 70  # Steam's line between "Mostly Positive" and "Mixed"
SCHINESE = 6  # Steam ELanguage code for Simplified Chinese
HORROR = {"Horror", "Psychological Horror", "Survival Horror"}

QUESTIONNAIRE = {"seeds": [1145360, 367520], "need_language": "schinese", "avoid_tags": sorted(HORROR)}
SENTENCE = "我以前沉迷《文明6》和《星露谷物语》，今晚想找类似的轻松游戏，60 块以内，最好正在打折"
MOCK_OWNED = {  # IPlayerService/GetOwnedGames response shape, playtime in minutes
    "response": {"game_count": 7, "games": [
        {"appid": 289070, "playtime_forever": 300 * 60},   # Civilization VI
        {"appid": 413150, "playtime_forever": 60 * 60},    # Stardew Valley
        {"appid": 1145360, "playtime_forever": 80 * 60},   # Hades
        {"appid": 1426210, "playtime_forever": 13 * 60},   # It Takes Two
        {"appid": 588650, "playtime_forever": 40},         # Dead Cells, 0.7 h
        {"appid": 646570, "playtime_forever": 0},          # Slay the Spire, bought, no Steam playtime
        {"appid": 4000000, "playtime_forever": 5 * 60},    # not in the core library
    ]}}
MOCK_PRIVATE = {"response": {}}
COMBO_SENTENCE = "想再找几款像《Hades》这样的，别太难，100 块以内"
FEEL_W = 0.25  # design 5.5 feel channel, initial value
SEED_POOL, LIB_BONUS = 50, 0.2  # design 4.1: with explicit seeds the library only re-ranks the seed's top 50


class KB:
    def __init__(self):
        g = pd.read_parquet(PROC / "games.parquet").set_index("appid")
        self.games = g
        self.appids = g.index.to_numpy()
        self.pos = {a: i for i, a in enumerate(self.appids)}
        self.name = g["name"]
        self.has_store = g["review_count"].notna()
        tags = pd.read_parquet(PROC / "tags.parquet").set_index("tagid")
        self.tag_en, self.tag_zh = tags["name_en"], tags["name_zh"]
        gt = pd.read_parquet(PROC / "game_tags.parquet")
        self.gt = gt
        self.tagset = gt.groupby("appid")["tagid"].agg(set).to_dict()
        self.core = gt[gt["is_core"]].groupby("appid")["tagid"].agg(list).to_dict()
        self.T = self._tag_matrix(gt)
        self.prices = pd.read_parquet(PROC / "prices.parquet").query("region == 'CN'").set_index("appid")
        self.colike = pd.read_parquet(DER / "colike_reviews100m.parquet")
        z = np.load(DER / "ease_reviews100m.npz")
        col = {a: j for j, a in enumerate(z["items"])}
        self.ease_col = np.array([col.get(a, -1) for a in self.appids])  # EASE column of each core game, -1 = none
        self.ease_B, self.ease_row = z["B"], col
        self.playtime_ref = pd.read_parquet(DER / "playtime_reference_100m.parquet").set_index("app_id")
        comp = pd.read_parquet(PROC / "companies.parquet")
        self.dev = comp[comp["developer"]]
        self.series = pd.read_parquet(PROC / "series.parquet")
        # IGDB numbers collections and franchises separately (collection 10 = Dragon Age, franchise 10 = Sid Meier),
        # so a series is identified by (kind, series_id)
        self.series["key"] = list(zip(self.series["kind"], self.series["series_id"]))
        coll = self.series[self.series["kind"] == "collection"]  # franchises such as "Star Wars" are too broad to fold
        self.series_of = coll.groupby("appid")["key"].agg(set).to_dict()
        self.similar = pd.read_parquet(PROC / "similar.parquet")
        self.E, self.E_has = self._desc()
        pos = g["review_count"].fillna(0) * g["pct_positive"].fillna(0) / 100
        self.quality = ((pos + ALPHA) / (g["review_count"].fillna(0) + ALPHA + BETA)).to_numpy()
        self.rating_ok = (g["pct_positive"] >= RATING_FLOOR).to_numpy()

    def _tag_matrix(self, gt):
        n = len(self.appids)
        df = gt.groupby("tagid")["appid"].nunique()
        idf = np.log(gt["appid"].nunique() / df)
        self.tag_cols = np.array(sorted(df.index))
        M = np.zeros((n, len(self.tag_cols)), np.float32)
        M[gt["appid"].map(self.pos).to_numpy(), np.searchsorted(self.tag_cols, gt["tagid"].to_numpy())] = \
            gt["weight"].to_numpy() * idf.reindex(gt["tagid"]).to_numpy()
        self.T_has = M.any(axis=1)
        M /= np.linalg.norm(M, axis=1, keepdims=True) + 1e-9
        return M

    def _desc(self):
        z = np.load(EMB_CACHE)
        E = np.zeros((len(self.appids), z["emb"].shape[1]), np.float32)
        has = np.zeros(len(self.appids), bool)
        for a, v in zip(z["appids"], z["emb"]):
            if a in self.pos:
                E[self.pos[a]] = v
                has[self.pos[a]] = True
        return E, has


def mm(x, mask):
    out = np.zeros_like(x, dtype=np.float32)
    if mask.any():
        lo, hi = x[mask].min(), x[mask].max()
        out[mask] = (x[mask] - lo) / (hi - lo + 1e-9)
    return out


_MODEL = []


def encode_query(text):
    if not _MODEL:
        import torch
        from sentence_transformers import SentenceTransformer
        _MODEL.append(SentenceTransformer(str(MODEL), model_kwargs={"torch_dtype": torch.float16},
                                          tokenizer_kwargs={"padding_side": "left"}))
    m = _MODEL[0]
    prompt = "Instruct: Given what a player says they want, retrieve games whose store description matches it\nQuery: "
    return m.encode([text], prompt=prompt, normalize_embeddings=True)[0].astype(np.float32)


# ---------- Step 1 helpers ----------

def parse_with_llm(kb, sentence):
    from openai import OpenAI
    from pydantic import BaseModel, Field, field_validator
    from typing import Literal, Optional

    tag_names = set(kb.tag_en)

    class Budget(BaseModel):
        amount: float = Field(gt=0)
        scope: Literal["per_person", "team_total"]

    class Spec(BaseModel):
        seeds: list[str] = []
        preference_text: Optional[str] = None
        feel_want: list[str] = []
        feel_avoid: list[str] = []
        avoid_tags: list[str] = []
        budget: Optional[Budget] = None
        price_intent: Literal["none", "cheap", "near_record_low"] = "none"
        party_size: Optional[int] = None

        @field_validator("feel_want", "feel_avoid", "avoid_tags")
        @classmethod
        def known_tags(cls, v):
            bad = [t for t in v if t not in tag_names]
            if bad:
                raise ValueError(f"unknown tags {bad}")
            return v

    tag_list = "; ".join(f"{kb.tag_en[t]}={kb.tag_zh[t]}" for t in kb.tag_en.index)
    system = (
        "You turn a Steam player's request into JSON. Only fill fields the user actually said; leave others empty/null.\n"
        "Fields: seeds (games the user names as taste anchors, give each game's official English Steam store title), "
        "preference_text (only the words describing the feel they want, copied verbatim; drop game names, budget, "
        "price words and filler like 'similar'), "
        "feel_want (up to 4 tag names for the feel, pace or difficulty the user wants), "
        "feel_avoid (up to 4 tag names for a feel the user does not want, e.g. 'not too hard' -> Difficult, Souls-like, Unforgiving), "
        "avoid_tags (content the user refuses outright such as horror or gore; these are hard exclusions), "
        "budget {amount, scope: per_person|team_total} in CNY, price_intent (none|cheap|near_record_low; "
        "'on sale' or 'discount' means near_record_low), party_size (only if stated).\n"
        f"Tag names must be English names from this list (English=Chinese): {tag_list}\nReturn only the JSON object.")
    env = load_env(ROOT / ".env")
    client = OpenAI(base_url=env["LLM_BASE_URL"], api_key=env["LLM_API_KEY"])
    t0 = time.time()
    for attempt in range(2):
        r = client.chat.completions.create(model=env["LLM_MODEL"], temperature=0,
                                           messages=[{"role": "system", "content": system},
                                                     {"role": "user", "content": sentence}])
        raw = r.choices[0].message.content.strip()
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw)
        try:
            spec = Spec.model_validate_json(raw)
            return spec.model_dump(), round(time.time() - t0, 1), attempt + 1
        except Exception as e:  # validation failed: retry once, as the design says
            err = str(e)
    raise RuntimeError(f"LLM output failed validation twice: {err[:200]}")


def match_title(kb, title):
    norm = lambda s: re.sub(r"[^0-9a-z]", "", s.lower())
    n = norm(title)
    names = kb.name.map(norm)
    exact = names[names == n]
    if len(exact) == 1:
        return int(exact.index[0])
    part = names[names.str.contains(n, regex=False)]
    return int(part.index[0]) if len(part) == 1 else None


def playtime_percentiles(kb, owned_hours):
    """Share of the game's training reviewers (playtime > 0) who played less, read off the 101 stored quantiles."""
    out = {}
    for a, h in owned_hours.items():
        if a not in kb.playtime_ref.index:
            out[a] = None
            continue
        r = kb.playtime_ref.loc[a]
        q = np.asarray(r["q"], np.float64)
        out[a] = {"median": round(float(r["median_hours"]), 1),
                  "pct": round(float(np.interp(h, q, np.linspace(0, 1, 101))), 2), "n": int(r["n"])}
    return out


# ---------- Step 2: three-valued rules ----------

def hard_filter(kb, exclude, need_language=None, avoid_tags=(), budget=None):
    n = len(kb.appids)
    status = np.full(n, 2, np.int8)  # 0 FAIL, 1 UNKNOWN, 2 PASS; a game takes its worst rule
    rules = []

    def apply(name, st):
        nonlocal status
        rules.append({"rule": name, "pass": int((st == 2).sum()), "fail": int((st == 0).sum()), "unknown": int((st == 1).sum())})
        status = np.minimum(status, st)

    st = np.where(np.isin(kb.appids, list(exclude)), 0, 2).astype(np.int8)
    apply("去掉种子 / 已玩过的", st)
    if need_language:
        langs = kb.games["language_codes"]
        st = np.array([1 if not kb.has_store[a] else (2 if SCHINESE in list(langs[a]) else 0) for a in kb.appids], np.int8)
        apply("支持简体中文", st)
    if avoid_tags:
        bad = set(kb.tag_en[kb.tag_en.isin(avoid_tags)].index)
        st = np.array([1 if a not in kb.tagset else (0 if kb.tagset[a] & bad else 2) for a in kb.appids], np.int8)
        apply("雷区：" + " / ".join(kb.tag_zh[t] for t in bad), st)
    if budget:
        p = kb.prices.reindex(kb.appids)
        cost = np.where(p["is_free"].fillna(False), 0.0, p["final"].to_numpy())
        st = np.where(np.isnan(cost), 1, np.where(cost <= budget, 2, 0)).astype(np.int8)
        apply(f"预算 ≤ ¥{budget:g}（每日快照）", st)
    return status, rules


# ---------- Step 3: channels ----------

def feel_score(kb, want, avoid):
    """Design 5.5 feel channel: mean weight of wanted tags minus mean weight of avoided tags (absent tag = 0)."""
    def mean_w(tags):
        if not tags:
            return np.zeros(len(kb.appids), np.float32)
        sub = kb.gt[kb.gt["tagid"].isin(tags)]
        s = sub.groupby("appid")["weight"].sum().reindex(kb.appids).fillna(0).to_numpy(np.float32)
        return s / len(tags)
    return mean_w(want) - mean_w(avoid)


def score(kb, anchors, weights, cand_mask, pref_vec=None, feel=None):
    """anchors: {appid: weight}, may be empty (mood-only request). feel: (want_ids, avoid_ids) or None."""
    a_ids = list(anchors)
    ai = [kb.pos[a] for a in a_ids]
    n = len(kb.appids)
    w = np.array([anchors[a] for a in a_ids], np.float32)[:, None]

    def wmax(sim):
        if not a_ids:
            return np.zeros(n, np.float32), np.zeros(n, int)
        ws = sim * w
        return ws.max(axis=0), ws.argmax(axis=0)

    tag_raw, tag_hit = wmax(kb.T[ai] @ kb.T.T)
    a_desc = [i for i in ai if kb.E_has[i]]
    d_anchor, d_hit = wmax(kb.E[ai] @ kb.E.T)
    d_pref = kb.E @ pref_vec if pref_vec is not None else None

    # co-like channel: EASE, sum over anchors of weight x B[anchor, candidate]; co_hit = the anchor contributing most
    has_col = kb.ease_col >= 0
    contrib = np.zeros((len(a_ids), n), np.float32)
    for k, a in enumerate(a_ids):
        if a in kb.ease_row:
            contrib[k, has_col] = anchors[a] * kb.ease_B[kb.ease_row[a], kb.ease_col[has_col]]
    co_raw = contrib.sum(axis=0)
    co_hit = contrib.argmax(axis=0) if a_ids else np.zeros(n, int)
    co_has = has_col & any(a in kb.ease_row for a in a_ids)
    CO = np.zeros((len(a_ids), n), np.int32)  # card statistic: people who recommended both
    for k, a in enumerate(a_ids):
        sub = kb.colike[(kb.colike["app_id"] == a) & kb.colike["neighbor"].isin(kb.pos)]
        CO[k, sub["neighbor"].map(kb.pos).to_numpy()] = sub["co_count"].to_numpy()

    dev_ids = set(kb.dev[kb.dev["appid"].isin(a_ids)]["company_id"])
    ser_keys = set(kb.series[kb.series["appid"].isin(a_ids)]["key"])
    same_dev = set(kb.dev[kb.dev["company_id"].isin(dev_ids)]["appid"])
    same_ser = set(kb.series[kb.series["key"].isin(ser_keys)]["appid"])
    igdb_sim = set(kb.similar[kb.similar["appid"].isin(a_ids)]["similar_appid"])
    lineage = np.array([1.0 if a in same_dev or a in same_ser or a in igdb_sim else 0.0 for a in kb.appids], np.float32)

    if d_pref is not None and a_desc:
        desc = 0.5 * mm(d_anchor, cand_mask & kb.E_has) + 0.5 * mm(d_pref, cand_mask & kb.E_has)
    elif d_pref is not None:
        desc = d_pref
    else:
        desc = d_anchor
    none = np.zeros(n, bool)
    has = {"tag": kb.T_has if a_ids else none, "desc": kb.E_has if (a_desc or d_pref is not None) else none,
           "colike": co_has, "lineage": np.ones(n, bool) if a_ids else none}
    parts = {"tag": mm(tag_raw, cand_mask & kb.T_has), "desc": mm(desc, cand_mask & kb.E_has),
             "colike": mm(co_raw, cand_mask & co_has), "lineage": lineage}
    wsum = sum(weights[c] * has[c] for c in weights)
    # lineage is a 0/1 set feature: a game with no tag, description or co-like data must not score on it alone
    content = has["tag"] | has["desc"] | has["colike"]
    fused = content * sum(weights[c] * parts[c] * has[c] for c in weights) / np.maximum(wsum, 1e-9)
    feel_norm = None
    if feel and (feel[0] or feel[1]):
        feel_norm = mm(feel_score(kb, *feel), cand_mask & kb.T_has)
        fused = np.where(content, (1 - FEEL_W) * fused + FEEL_W * feel_norm, FEEL_W * feel_norm * kb.T_has)
    detail = {"tag_raw": tag_raw, "tag_hit": tag_hit, "d_anchor": d_anchor, "d_hit": d_hit, "d_pref": d_pref,
              "co_raw": co_raw, "co_hit": co_hit, "co_contrib": contrib, "co_count": CO, "parts": parts, "has": has, "feel": feel_norm,
              "feel_tags": feel, "same_dev": same_dev, "same_ser": same_ser, "igdb_sim": igdb_sim, "anchors": a_ids}
    return fused, detail


# ---------- Step 4 ----------

def price_pref(kb, a):
    p = kb.prices.loc[a] if a in kb.prices.index else None
    if p is None or bool(p["is_free"]) or pd.isna(p["final"]) or pd.isna(p["steam_low"]):
        return None
    r = p["final"] / p["steam_low"]
    return float(np.clip((2 - r) / (2 - 1.05), 0, 1))


def fold_series(kb, order, limit):
    """Design 5.5 step 0: keep the best game of each IGDB series, fold the rest under it."""
    kept, folded, seen = [], {}, {}
    for i in order:
        s = kb.series_of.get(kb.appids[i], set())
        owner = next((seen[x] for x in s if x in seen), None)
        if owner is not None:
            folded.setdefault(owner, []).append(int(i))
            continue
        if len(kept) < limit:  # past the limit, keep scanning only to count folded games of kept series
            kept.append(int(i))
            for x in s:
                seen[x] = int(i)
    return np.array(kept), folded


def rank(kb, fused, status, price_intent):
    pass_idx = np.where(status == 2)[0]
    rel_all = mm(fused, status == 2)
    order = pass_idx[np.argsort(-rel_all[pass_idx])]
    short, folded = fold_series(kb, order[:SHORTLIST * 10], SHORTLIST)
    rel = rel_all
    base = {}
    for i in short:
        terms = [(0.5, rel[i]), (0.3, kb.quality[i])]
        pp = price_pref(kb, kb.appids[i]) if price_intent != "none" else None
        if pp is not None:
            terms.append((0.2, pp))
        base[i] = sum(w * v for w, v in terms) / sum(w for w, _ in terms)
    chosen, remaining, log = [], set(short.tolist()), []
    while len(chosen) < PICK and remaining:
        # rating floor: below RATING_FLOOR or no rating only fills the top 5 when nothing above it is left
        rated = {r for r in remaining if kb.rating_ok[r]} or remaining
        top = max(rel[r] for r in rated)
        window = [r for r in rated if rel[r] >= top - DELTA]

        def mmr(r):
            red = max((float(kb.T[r] @ kb.T[c]) for c in chosen), default=0.0)
            return 0.65 * base[r] - 0.35 * red, red
        best = max(window, key=lambda r: mmr(r)[0])
        log.append({"window": len(window), "redundancy": round(mmr(best)[1], 2)})
        chosen.append(best)
        remaining.remove(best)
    unk_idx = np.where(status == 1)[0]
    rel_unk = mm(fused, status == 1)
    unknown = unk_idx[np.argsort(-rel_unk[unk_idx])][:UNKNOWN_SHOW]
    return chosen, log, short, base, rel, unknown, folded


# ---------- cards ----------

def card(kb, i, det, rel, base, step_log, owned, folded):
    a = int(kb.appids[i])
    g = kb.games.loc[a]
    anchors = det["anchors"]
    hit = anchors[int(det["tag_hit"][i])] if anchors else None
    shared = [kb.tag_zh[t] for t in kb.core.get(a, []) if t in set(kb.core.get(hit, []))][:3] if hit else []
    co_k = int(det["co_hit"][i])
    co_anchor = anchors[co_k] if anchors else None
    co_n = int(det["co_count"][co_k, i]) if anchors else 0
    feel_hits, feel_bad = [], []
    if det["feel_tags"]:
        mine = kb.tagset.get(a, set())
        feel_hits = [kb.tag_zh[t] for t in det["feel_tags"][0] if t in mine]
        feel_bad = [kb.tag_zh[t] for t in det["feel_tags"][1] if t in mine]
    co_rank = None
    if co_n:
        nb = kb.colike[kb.colike["app_id"] == co_anchor].sort_values("sim", ascending=False)["neighbor"].tolist()
        co_rank = nb.index(a) + 1 if a in nb else None
    devs = kb.dev[kb.dev["appid"] == a]["company"].tolist()
    lineage = []
    if a in det["same_dev"]:
        lineage.append("同工作室")
    if a in det["same_ser"]:
        lineage.append("同系列")
    if a in det["igdb_sim"]:
        lineage.append("IGDB 相似列表")
    p = kb.prices.loc[a] if a in kb.prices.index else None
    price = None
    if p is not None:
        price = {"is_free": bool(p["is_free"]), "final": None if pd.isna(p["final"]) else float(p["final"]),
                 "low": None if pd.isna(p["steam_low"]) or bool(p["is_free"]) else float(p["steam_low"]),
                 "low_date": None if pd.isna(p["steam_low_time"]) else str(p["steam_low_time"])[:7]}
    parts = {c: round(float(det["parts"][c][i]), 2) if det["has"][c][i] else None for c in WEIGHTS}
    return {"appid": a, "name": g["name"], "year": None if pd.isna(g["release_year"]) else int(g["release_year"]),
            "developer": devs[0] if devs else (list(g["developers"])[0] if len(g["developers"]) else None),
            "best_anchor": kb.name[hit] if hit else None, "shared_core_tags": shared,
            "feel_hits": feel_hits, "feel_bad": feel_bad,
            "feel": None if det["feel"] is None else round(float(det["feel"][i]), 2),
            "colike": {"anchor": kb.name[co_anchor], "co_count": co_n, "rank": co_rank} if co_n else None,
            "lineage": lineage, "pct_positive": None if pd.isna(g["pct_positive"]) else int(g["pct_positive"]),
            "review_count": None if pd.isna(g["review_count"]) else int(g["review_count"]),
            "quality": round(float(kb.quality[i]), 3), "relevance": round(float(rel[i]), 2),
            "base": round(float(base.get(i, 0)), 3), "parts": parts, "price_cn": price,
            "owned": a in owned, "owned_note": "已在你的 Steam 库里，Steam 上没有游玩记录" if a in owned else None,
            "rating_ok": bool(kb.rating_ok[i]), "window": step_log["window"] if step_log else None,
            "redundancy": step_log["redundancy"] if step_log else None,
            "same_series_folded": [kb.name[kb.appids[j]] for j in folded.get(int(i), [])],
            "lib_bonus": None if det.get("lib_bonus") is None else round(float(det["lib_bonus"][i]), 2),
            "lib_anchor": det["lib_anchor"][i] if det.get("lib_anchor") is not None and det["lib_bonus"][i] > 0 else None}


def score_with_library(kb, seeds, library, status, pref_vec, feel):
    """Design 4.1: with explicit seeds, the library adds at most LIB_BONUS inside the seed's top SEED_POOL."""
    fused, det = score(kb, seeds, WEIGHTS, status >= 1, pref_vec, feel)
    lib = {a: w for a, w in library.items() if a not in seeds}
    lib_fused, lib_det = score(kb, lib, WEIGHTS, status >= 1)
    pool = np.zeros(len(kb.appids), bool)
    pool[np.argsort(-np.where(status >= 1, fused, -np.inf))[:SEED_POOL]] = True
    bonus = mm(lib_fused, pool) * pool
    names = [kb.name[a] for a in lib]
    det["lib_bonus"] = bonus
    det["lib_anchor"] = [names[k] for k in lib_det["co_hit"]]  # library game contributing most co-like score
    det["lib_pool"] = int(pool.sum())
    return fused + LIB_BONUS * bonus, det


def run_path(kb, label, anchors, status, rules, price_intent, owned=(), pref_vec=None, feel=None, extra=None, library=None,
             unplayed=()):
    """library: {appid: playtime-percentile weight}; only used together with explicit seeds in anchors.
    unplayed: owned games with no Steam playtime (labelled on cards, not excluded)."""
    t0 = time.time()
    if library and anchors:
        fused, det = score_with_library(kb, anchors, library, status, pref_vec, feel)
    else:
        fused, det = score(kb, anchors, WEIGHTS, status >= 1, pref_vec, feel)
    chosen, log, short, base, rel, unknown, folded = rank(kb, fused, status, price_intent)
    picks = [card(kb, i, det, rel, base, log[k], set(owned), folded) for k, i in enumerate(chosen)]
    def note(i):
        pct = kb.games["pct_positive"].iloc[i]
        out = "" if kb.rating_ok[i] else ("（暂无好评率）" if pd.isna(pct) else f"（口碑褒贬不一：{int(pct)}% 好评）")
        if kb.appids[i] in owned_unplayed:
            out += "（已在你的 Steam 库里，Steam 上没有游玩记录）"
        return out + (f"（同系列另有 {len(folded[i])} 款）" if folded.get(i) else "")
    owned_unplayed = set(unplayed)
    backups = [kb.name[kb.appids[i]] + note(i) for i in short if i not in chosen]
    unk = [{"name": kb.name[kb.appids[i]], "why": "CN 商店无数据（语言 / 价格 / 标签未知）" if not kb.has_store[kb.appids[i]] else "部分字段缺失"}
           for i in unknown]
    picks_share = {"anchor": {}}
    for p in picks:
        picks_share["anchor"][p["best_anchor"]] = picks_share["anchor"].get(p["best_anchor"], 0) + 1
    top = chosen[0]
    a_top = kb.appids[top]
    breakdown = []
    for k, a in enumerate(det["anchors"]):
        s = float(kb.T[kb.pos[a]] @ kb.T[top])
        breakdown.append({"anchor": kb.name[a], "weight": round(float(anchors[a]), 2), "sim": round(s, 2), "weighted": round(s * anchors[a], 2),
                          "ease_weighted": round(float(det["co_contrib"][k, top]), 4)})
    res = {"label": label, "anchors": [{"name": kb.name[a], "weight": round(float(w), 2)} for a, w in anchors.items()],
           "rules": rules, "pass": int((status == 2).sum()), "unknown": int((status == 1).sum()),
           "picks": picks, "backups": backups, "unknown_group": unk,
           "top_tag_breakdown": {"game": kb.name[a_top], "rows": breakdown}, "picks_by_anchor": picks_share["anchor"],
           "seconds_step3_4": round(time.time() - t0, 2)}
    res.update(extra or {})
    return res


def main():
    use_llm = "--no-llm" not in sys.argv
    t0 = time.time()
    kb = KB()
    print(f"knowledge base loaded in {time.time() - t0:.1f}s")
    out = {"weights": WEIGHTS, "delta": DELTA, "shortlist": SHORTLIST, "alpha_beta": [ALPHA, BETA]}

    # Path C: seed questionnaire
    q = QUESTIONNAIRE
    status, rules = hard_filter(kb, q["seeds"], need_language=q["need_language"], avoid_tags=q["avoid_tags"])
    out["questionnaire"] = run_path(kb, "C 种子问卷", {a: 1.0 for a in q["seeds"]}, status, rules, "none",
                                    extra={"input": {"seeds": [kb.name[a] for a in q["seeds"]], "language": "简体中文",
                                                     "avoid": [kb.tag_zh[t] for t in kb.tag_en[kb.tag_en.isin(q["avoid_tags"])].index]}})
    print("questionnaire:", [p["name"] for p in out["questionnaire"]["picks"]])

    # Path D: free text through the LLM
    prev = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    llm_cache = {}

    def understand(sentence, key):
        if use_llm:
            spec, secs, tries = parse_with_llm(kb, sentence)
        else:
            spec, secs, tries = prev[key]["spec"], prev[key].get("llm_seconds"), prev[key].get("llm_tries")
        tid = lambda names: [int(kb.tag_en[kb.tag_en == t].index[0]) for t in names]
        t1 = time.time()
        vec = encode_query(spec["preference_text"]) if spec.get("preference_text") else None
        llm_cache[key] = {"spec": spec, "llm_seconds": secs, "llm_tries": tries, "encode_seconds": round(time.time() - t1, 1),
                          "feel_want_zh": [kb.tag_zh[t] for t in tid(spec["feel_want"])],
                          "feel_avoid_zh": [kb.tag_zh[t] for t in tid(spec["feel_avoid"])]}
        return spec, (tid(spec["feel_want"]), tid(spec["feel_avoid"])), vec

    spec, feel, pref_vec = understand(SENTENCE, "llm")
    seeds = {t: match_title(kb, t) for t in spec["seeds"]}
    budget = spec["budget"]["amount"] if spec.get("budget") else None
    anchors = {a: 1.0 for a in seeds.values() if a}
    status, rules = hard_filter(kb, set(anchors), avoid_tags=spec.get("avoid_tags") or (), budget=budget)
    out["llm"] = run_path(kb, "D 对话提取", anchors, status, rules, spec.get("price_intent", "none"),
                          pref_vec=pref_vec, feel=feel,
                          extra={"input": SENTENCE, **llm_cache["llm"],
                                 "seed_match": {t: (kb.name[a] if a else None) for t, a in seeds.items()}})
    print("llm:", spec, [p["name"] for p in out["llm"]["picks"]])

    # Path A/B: Steam library
    priv = MOCK_PRIVATE["response"]
    is_public = "game_count" in priv
    games = MOCK_OWNED["response"]["games"]
    hours = {g["appid"]: g["playtime_forever"] / 60 for g in games}
    in_core = {a: h for a, h in hours.items() if a in kb.pos}
    # every playtime 0 = the profile hides playtime ("keep my total playtime private"): ownership only, no anchors
    playtime_hidden = bool(hours) and all(h == 0 for h in hours.values())
    pcts = playtime_percentiles(kb, in_core)
    played = set() if playtime_hidden else {a for a, h in in_core.items() if h > 0}
    unplayed = set(in_core) - played
    anchors = {a: pcts[a]["pct"] for a in played if pcts[a] and pcts[a]["pct"] > 0}
    status, rules = hard_filter(kb, played)
    lib_rows = [{"name": kb.name[a] if a in kb.pos else f"AppID {a}", "hours": round(h, 1), "in_core": a in kb.pos,
                 "median": (pcts.get(a) or {}).get("median"), "pct": (pcts.get(a) or {}).get("pct"),
                 "anchor_weight": anchors.get(a), "excluded": a in played} for a, h in hours.items()]
    out["library"] = run_path(kb, "A/B Steam 游戏库", anchors, status, rules, "none", owned=unplayed, unplayed=unplayed,
                              extra={"library": lib_rows, "playtime_hidden": playtime_hidden,
                                     "private_check": {"response": priv, "is_library_public": is_public}})
    print("library:", [p["name"] for p in out["library"]["picks"]])

    # Combination A/B + D: same library, plus a sentence that names what the user wants (design 4.1 merge rules).
    spec, feel, pref_vec = understand(COMBO_SENTENCE, "combo")
    out["combo"] = llm_cache["combo"]
    seed_match = {t: match_title(kb, t) for t in spec["seeds"]}
    seeds = {a for a in seed_match.values() if a}
    budget = spec["budget"]["amount"] if spec.get("budget") else None
    status, rules = hard_filter(kb, played | seeds, avoid_tags=spec.get("avoid_tags") or (), budget=budget)
    common = {"input": COMBO_SENTENCE, **llm_cache["combo"],
              "seed_match": {t: (kb.name[a] if a else None) for t, a in seed_match.items()}}
    seed_w = {a: 1.0 for a in seeds}
    if seeds:
        out["combo_merge"] = run_path(kb, "A/B + D", seed_w, status, rules, spec.get("price_intent", "none"),
                                      owned=unplayed, pref_vec=pref_vec, feel=feel, extra=common, library=anchors,
                                      unplayed=unplayed)
    else:  # only a feel: the library stays the taste anchor
        out["combo_merge"] = run_path(kb, "A/B + D", anchors, status, rules, spec.get("price_intent", "none"),
                                      owned=unplayed, pref_vec=pref_vec, feel=feel, extra=common, unplayed=unplayed)
    # reference only: the same request without the library as taste, to see what the library adds
    out["combo_seed_only"] = run_path(kb, "D only (reference)", {a: 1.0 for a in seeds}, status, rules,
                                      spec.get("price_intent", "none"), owned=unplayed, pref_vec=pref_vec, feel=feel,
                                      unplayed=unplayed)
    print("combo:", spec)
    print("  merge:", [p["name"] for p in out["combo_merge"]["picks"]])
    print("  seed only:", [p["name"] for p in out["combo_seed_only"]["picks"]])

    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o)),
                   encoding="utf-8")
    print(f"wrote {OUT} in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
