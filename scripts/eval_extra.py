"""Offline experiments from design section 7 that had not been run yet, all through the real src/playnext code.

  mech    : mechanics combination hit (scenario 1). ~60 realistic gameplay tag pairs (both tags core in >= 10 core
            games) plus a "rare" set (both core in <= 4 games) that exercises the fallback. System = the real
            mechanics path (SessionSpec(mechanics=[t1, t2]) -> Recommender, no LLM); baseline = the same trunk with
            the mechanics rule replaced by "both tags present at any weight". Two request shapes: mechanics only
            (cold-start ranking by smoothed rating x log reviews) and mechanics + a held-out reviewer's library.
  rank    : on the held-out reviewers of eval_ranking_groups.py (same seed, same time split, library-profile path):
            (a) price_intent none / near_record_low / cheap with the CN snapshot prices (no live calls);
            (b) rating smoothing: Beta prior from config vs the old placeholder (24.6, 5.4) vs the Wilson 95 % lower
                bound vs no quality term, by swapping kb.quality in this script (package files untouched).
  latency : scoring.channel_scores / relevance serial vs the independent channels (tag, co-like, lineage; the
            description channel of the recorded runs was removed, design 10.18) in a ThreadPoolExecutor (variant
            written here), plus member-level concurrency for a 4-member group. Median of 30 interleaved runs after
            warm-up.
Bootstrap 95 % CIs (400 resamples) over reviewers (paired where a difference is reported) or over tag pairs.
Results: data/derived/eval_extra.json; log: data/derived/eval_extra.log.
  pricecurve : near_record_low price-preference curve (zero point 2x / 3x / 4x / 6x of the record low, linear, plus
            a log curve to 4x) vs no price intent, by swapping ranking.price_pref in this script.
Usage: uv run python scripts/eval_extra.py [mech|rank|latency|pricecurve|all, or comma-separated] [N users, default 3000]
"""
import itertools
import json
import os
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
from playnext import config as C  # noqa: E402
from playnext import pipeline, scoring  # noqa: E402
from playnext.kb import KB, minmax  # noqa: E402
from playnext.pipeline import Recommender  # noqa: E402
from playnext.pricing import Prices  # noqa: E402
from playnext.ranking import rank  # noqa: E402
from playnext.rules import FAIL, PASS, UNKNOWN, Rule, hard_filter  # noqa: E402
from playnext.scoring import Scored, _wagg, group_aggregate, member_taste, personal, relevance  # noqa: E402
from playnext.spec import Library, Member, SessionSpec  # noqa: E402
from eval_ranking_groups import ci, users  # noqa: E402  same reviewers / split / CI as design 5.5

OUT = C.DER / "eval_extra.json"
LOG = C.DER / "eval_extra.log"


def log(*a):
    s = time.strftime("%H:%M:%S") + " " + " ".join(str(x) for x in a)
    print(s, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(s + "\n")


def config_snapshot(kb):
    pos, rc = kb.pos_reviews, kb.review_count
    return {"ALPHA": C.ALPHA, "BETA": C.BETA, "WEIGHTS": dict(C.WEIGHTS), "DELTA": C.DELTA, "MMR_LAMBDA": C.MMR_LAMBDA,
            "BASE_W": dict(C.BASE_W), "RATING_FLOOR": C.RATING_FLOOR, "NEAR_LOW": C.NEAR_LOW,
            "CHEAP_ZERO": dict(getattr(C, "CHEAP_ZERO", {})), "TAG_AGG": C.TAG_AGG,
            "MAX_LIBRARY_ANCHORS": C.MAX_LIBRARY_ANCHORS, "SHORTLIST": C.SHORTLIST, "PICK": C.PICK,
            "kb_quality_matches_ALPHA_BETA": bool(np.allclose(kb.quality, (pos + C.ALPHA) / (rc + C.ALPHA + C.BETA))),
            "single_player_rules": [r.key for r in hard_filter(kb, SessionSpec()).rules]}


def cin(x):
    """ci() over the finite entries only (per-user metrics that can be undefined, e.g. no paid pick)."""
    x = np.asarray(x, np.float64)
    x = x[np.isfinite(x)]
    return ci(x) + [int(len(x))] if len(x) else [None, None, None, 0]


def paired(a, b):
    a, b = np.asarray(a, np.float64), np.asarray(b, np.float64)
    return cin(a - b)


# ======================================================================================= 1. mechanics combinations
GAMEPLAY = [
    "Roguelike", "Roguelite", "Action Roguelike", "Perma Death", "Procedural Generation",
    "Deckbuilding", "Card Battler", "Card Game",
    "Turn-Based Strategy", "Turn-Based Tactics", "Turn-Based Combat", "Tactical", "Strategy RPG", "Tactical RPG",
    "RTS", "Real Time Tactics", "Tower Defense", "Grand Strategy", "4X", "Wargame",
    "Base Building", "City Builder", "Building", "Colony Sim",
    "Management", "Resource Management", "Economy", "Time Management", "Automation", "Trading",
    "Survival", "Crafting", "Sandbox", "Open World", "Exploration", "Mining",
    "Farming Sim", "Life Sim", "Dating Sim", "Cooking", "Fishing", "Hunting",
    "Platformer", "Metroidvania", "Puzzle", "Physics",
    "Souls-like", "Hack and Slash", "Action RPG", "JRPG", "CRPG", "Party-Based RPG", "Dungeon Crawler", "Loot",
    "Shooter", "Bullet Hell", "Shoot 'Em Up", "Twin Stick Shooter",
    "Stealth", "Immersive Sim", "Racing", "Driving", "Fighting", "Beat 'em up", "Rhythm",
    "Visual Novel", "Choices Matter", "Point & Click", "Hidden Object", "Detective", "Investigation",
    "Walking Simulator", "Incremental", "Idler", "Creature Collector", "Auto Battler", "Battle Royale",
    "Character Customization", "Space Sim", "Flight", "Parkour", "Destruction",
]
# near-synonyms: a pair inside one family is not a "combination" (Roguelike + Roguelite, Shoot 'Em Up + Bullet Hell)
FAMILIES = [
    ["Roguelike", "Roguelite", "Action Roguelike", "Perma Death", "Procedural Generation"],
    ["Deckbuilding", "Card Battler", "Card Game"],
    ["Turn-Based Strategy", "Turn-Based Tactics", "Turn-Based Combat", "Tactical", "Strategy RPG", "Tactical RPG"],
    ["RTS", "Real Time Tactics"], ["Grand Strategy", "4X", "Wargame"],
    ["Base Building", "City Builder", "Building", "Colony Sim"],
    ["Management", "Resource Management", "Economy", "Time Management", "Trading"],
    ["Open World", "Exploration", "Sandbox"], ["Farming Sim", "Life Sim"], ["Platformer", "Metroidvania"],
    ["Action RPG", "JRPG", "CRPG", "Party-Based RPG"], ["Shooter", "Bullet Hell", "Shoot 'Em Up", "Twin Stick Shooter"],
    ["Racing", "Driving"], ["Fighting", "Beat 'em up"], ["Visual Novel", "Choices Matter"],
    ["Point & Click", "Hidden Object", "Detective", "Investigation"], ["Incremental", "Idler"],
]
FORCED = [("Roguelike", "Base Building"), ("Survival", "Base Building"), ("Deckbuilding", "Roguelike")]
N_MAIN, N_RARE = 60, 15


def pick_pairs(kb):
    by_name = {n: int(t) for t, n in kb.tag_en.items()}
    names = [n for n in GAMEPLAY if n in by_name]
    missing = [n for n in GAMEPLAY if n not in by_name]
    try:  # design 6.3 tag categories, when the file exists: keep only tags classed as gameplay
        from playnext.kb import load_tag_categories
        cat = load_tag_categories([by_name[n] for n in names])
        not_gp = [n for n in names if cat[by_name[n]] != "gameplay"]
        if len(not_gp) < len(names):  # file present
            names = [n for n in names if n not in not_gp]
    except ImportError:
        not_gp = []
    fam = {n: k for k, f in enumerate(FAMILIES) for n in f}
    core_g, pres_g = {}, {}
    for a, ts in kb.core.items():
        for t in ts:
            core_g.setdefault(int(t), set()).add(int(a))
    for a, ts in kb.tagset.items():
        for t in ts:
            pres_g.setdefault(int(t), set()).add(int(a))
    cands = []
    for x, y in itertools.combinations(names, 2):
        if fam.get(x) is not None and fam.get(x) == fam.get(y):
            continue
        tx, ty = by_name[x], by_name[y]
        cands.append({"pair": [x, y], "tags": [tx, ty], "n_core_both": len(core_g.get(tx, set()) & core_g.get(ty, set())),
                      "n_present_both": len(pres_g.get(tx, set()) & pres_g.get(ty, set()))})
    key = lambda c: tuple(sorted(c["pair"]))  # noqa: E731
    forced = [c for c in cands if key(c) in {tuple(sorted(p)) for p in FORCED}]
    rest = sorted([c for c in cands if c["n_core_both"] >= 10 and c not in forced], key=lambda c: -c["n_core_both"])
    idx = np.unique(np.linspace(0, len(rest) - 1, N_MAIN - len(forced)).round().astype(int))
    main = forced + [rest[i] for i in idx]  # spread over the whole range of co-occurrence counts
    rare = sorted([c for c in cands if c["n_core_both"] <= 4 and c["n_present_both"] >= 15],
                  key=lambda c: (-c["n_present_both"], c["pair"]))[:N_RARE]
    log(f"mech: {len(names)} gameplay tags (missing {missing}, not gameplay per tag_categories {not_gp}); "
        f"{len(rest) + len(forced)} candidate pairs with >= 10 core games, picked {len(main)}; rare {len(rare)}")
    return main, rare


_orig_hard_filter = pipeline.hard_filter


def presence_filter(kb, spec):
    """Baseline Step 2: the mechanics rule only asks that every tag be present (any weight)."""
    if not spec.mechanics:
        return _orig_hard_filter(kb, spec)
    fr = _orig_hard_filter(kb, spec.model_copy(update={"mechanics": []}))
    must = set(spec.mechanics)
    st = np.array([PASS if must <= kb.tagset.get(int(a), set()) else FAIL for a in kb.appids], np.int8)
    fr.rules.append(Rule("mechanics", "机制组合（基线）：标签出现即可", st, relaxable=True))
    fr.status = np.minimum(fr.status, st).astype(np.int8)
    return fr


def pick_stats(kb, appids, t1, t2):
    rows = []
    for a in appids:
        core, tags = set(kb.core.get(a, [])), kb.tagset.get(a, set())
        nc = (t1 in core) + (t2 in core)
        both = t1 in tags and t2 in tags
        rows.append({"core_both": nc == 2, "present_both": both, "one_core_one_minor": both and nc == 1,
                     "min_w": min(kb.tag_weight.get((a, t1), 0.0), kb.tag_weight.get((a, t2), 0.0)),
                     "pct": kb.games.at[a, "pct_positive"]})
    if not rows:
        return {"n": 0, "core_both": np.nan, "present_both": np.nan, "one_core_one_minor": np.nan, "min_w": np.nan,
                "pct": np.nan}
    out = {k: float(np.mean([r[k] for r in rows])) for k in ("core_both", "present_both", "one_core_one_minor", "min_w")}
    out["pct"] = float(np.nanmean([r["pct"] for r in rows])) if any(r["pct"] == r["pct"] for r in rows) else np.nan
    out["n"] = len(rows)
    return out


def label(kb, a, t1, t2):
    core, tags = set(kb.core.get(a, [])), kb.tagset.get(a, set())
    nc = (t1 in core) + (t2 in core)
    if nc == 2:
        return "core+core"
    if t1 in tags and t2 in tags:
        return "core+minor" if nc == 1 else "minor+minor"
    return "missing"


def eval_mech(kb, us):
    rec = Recommender(kb=kb, live_prices=False, reasons=False, rerank=False)
    main, rare = pick_pairs(kb)
    lib_users = [u for u in us if len(u["prof"]) >= 3]
    out = {"pairs_main": [c["pair"] for c in main], "pairs_rare": [c["pair"] for c in rare]}
    examples = {}
    for setname, pairs in (("main", main), ("rare", rare)):
        for shape in ("mech_only", "mech+library"):
            per = {"system": [], "baseline": []}
            fallback, fb_zero, pools = [], [], []
            for k, c in enumerate(pairs):
                t1, t2 = c["tags"]
                members = [Member()] if shape == "mech_only" else \
                    [Member(library=Library(owned=lib_users[k % len(lib_users)]["prof"]))]
                spec = SessionSpec(members=members, mechanics=[t1, t2])
                for arm in ("system", "baseline"):
                    if arm == "baseline":
                        pipeline.hard_filter = presence_filter
                    try:
                        r = rec.recommend(spec)
                    finally:
                        pipeline.hard_filter = _orig_hard_filter
                    picks = [p["appid"] for p in r.picks]
                    st = pick_stats(kb, picks, t1, t2)
                    per[arm].append(st)
                    if arm == "system":  # "已放宽": no strict game at all; "后面补上": fewer than PICK, topped up
                        fallback.append(any("已放宽" in n or "后面补上" in n for n in r.notes))
                        fb_zero.append(any("已放宽" in n for n in r.notes))
                    if shape == "mech_only" and (sorted(c["pair"]) in [sorted(p) for p in FORCED] or (setname == "rare" and k < 2)):
                        examples.setdefault(" + ".join(c["pair"]), {})[arm] = [
                            f"{kb.name[a]} [{label(kb, a, t1, t2)}, {kb.games.at[a, 'pct_positive']:.0f}%]" for a in picks]
                pools.append(c["n_core_both"])
            res = {"n_pairs": len(pairs), "fallback_pairs": int(sum(fallback)),
                   "fallback_share": round(float(np.mean(fallback)), 4), "fallback_no_strict_game": int(sum(fb_zero))}
            for arm in ("system", "baseline"):
                res[arm] = {m: cin([s[m] for s in per[arm]]) for m in
                            ("core_both", "present_both", "one_core_one_minor", "min_w", "pct", "n")}
            for m in ("core_both", "min_w", "pct"):
                res[f"system_minus_baseline_{m}"] = paired([s[m] for s in per["system"]], [s[m] for s in per["baseline"]])
            out[f"{setname}|{shape}"] = res
            log(f"  mech {setname:4s} {shape:12s} system core_both {res['system']['core_both'][:3]} "
                f"one-core {res['system']['one_core_one_minor'][0]} pct {res['system']['pct'][0]} picks {res['system']['n'][0]} "
                f"fallback {res['fallback_pairs']}/{len(pairs)} (no strict game {res['fallback_no_strict_game']}) | baseline core_both {res['baseline']['core_both'][:3]} "
                f"present {res['baseline']['present_both'][0]} one-core {res['baseline']['one_core_one_minor'][0]} "
                f"pct {res['baseline']['pct'][0]} | diff core_both {res['system_minus_baseline_core_both'][:3]}")
    out["examples"] = examples
    for p, d in examples.items():
        for arm, names in d.items():
            log(f"  e.g. {p} / {arm}: " + "; ".join(names))
    return out


# ======================================================================================= 2 + 3. price / rating
def wilson_lb(pos, n, z=1.96):
    n = np.asarray(n, np.float64)
    with np.errstate(divide="ignore", invalid="ignore"):
        p = np.where(n > 0, pos / n, 0.0)
        lb = (p + z * z / (2 * n) - z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / (1 + z * z / n)
    return np.where(n > 0, lb, 0.0)


def price_metrics(prices, picks, region="CN"):
    price, ratio, near, within2, free = [], [], [], [], []
    for a in picks:
        p = prices.get(a, region)
        if p is None:
            continue
        free.append(float(bool(p["is_free"])))
        if p["is_free"]:
            price.append(0.0)
            continue
        if p["final"] is None:
            continue
        price.append(p["final"])
        if p.get("low"):
            r = p["final"] / p["low"]
            ratio.append(r)
            near.append(float(r <= C.NEAR_LOW))
            within2.append(float(r < 2))  # price_pref > 0 only below 2 x record low
    m = lambda x: float(np.mean(x)) if x else np.nan  # noqa: E731
    return {"price": m(price), "spend5": float(np.sum(price)) if price else np.nan, "ratio_low": m(ratio),
            "near_low": m(near), "within_2x_low": m(within2), "free": m(free)}


def eval_rank_extra(kb, us):
    prices = Prices(kb, live=False)
    q_cfg = kb.quality.copy()
    pos, rc = kb.pos_reviews, kb.review_count
    quals = {"beta_config": q_cfg, "beta_placeholder_24.6_5.4": (pos + 24.6) / (rc + 24.6 + 5.4),
             "wilson95": wilson_lb(pos, rc)}
    variants = ["price:none", "price:near_record_low", "price:cheap"] + [f"quality:{q}" for q in quals] + ["quality:off"]
    metrics = ["hit5", "any5", "pct", "ild", "price", "spend5", "ratio_low", "near_low", "within_2x_low", "free",
               "overlap_current"]
    res = {v: {m: [] for m in metrics} for v in variants}
    base_w = dict(C.BASE_W)
    t0 = time.time()
    for k, u in enumerate(us):
        spec = SessionSpec(members=[Member(library=Library(owned=u["prof"]))])
        fr = hard_filter(kb, spec)
        rel, _ = relevance(kb, spec, fr.status >= UNKNOWN)
        if rel is None:
            continue
        runs = {}
        try:
            for v in variants:
                kind, name = v.split(":")
                s = spec
                if kind == "price":
                    s = spec.model_copy(update={"price_intent": name})
                    kb.quality = q_cfg
                elif name == "off":
                    kb.quality = q_cfg
                    C.BASE_W = {**base_w, "quality": 0.0}
                else:
                    kb.quality = quals[name]
                runs[v] = [int(kb.appids[i]) for i in rank(kb, s, rel, fr, prices).picks]
                C.BASE_W = base_w
        finally:
            kb.quality, C.BASE_W = q_cfg, base_w
        cur = set(runs["price:none"])
        for v, picks in runs.items():
            d = res[v]
            hits = sum(a in u["targ"] for a in picks)
            d["hit5"].append(hits / min(5, len(u["targ"])))
            d["any5"].append(float(hits > 0))
            d["pct"].append(np.nanmean([kb.games.at[a, "pct_positive"] for a in picks]))
            T = kb.T[[kb.pos[a] for a in picks]]
            S = T @ T.T
            d["ild"].append(float(1 - S[np.triu_indices(len(picks), 1)].mean()) if len(picks) > 1 else np.nan)
            for m, x in price_metrics(prices, picks).items():
                d[m].append(x)
            d["overlap_current"].append(len(cur & set(picks)) / max(1, len(picks)))
        if k % 500 == 0:
            log(f"  rank {k}/{len(us)} ({time.time() - t0:.0f}s)")
    out = {"n_users": len(res["price:none"]["hit5"])}
    for v in variants:
        out[v] = {m: cin(x) for m, x in res[v].items()}
    for v in variants:
        ref = "price:none" if v.startswith("price") else "quality:beta_config"
        if v in (ref, "quality:beta_config"):
            continue
        out[v]["minus_" + ref] = {m: paired(res[v][m], res[ref][m]) for m in
                                  ("hit5", "any5", "pct", "ild", "price", "ratio_low", "near_low", "within_2x_low", "free")}
    # how far the CN snapshot sits from the ITAD Steam record low across the catalogue (price_pref = 0 at >= 2x)
    r = []
    for a in kb.appids:
        p = prices.get(int(a), "CN")
        if p and not p["is_free"] and p["final"] is not None and p.get("low"):
            r.append(p["final"] / p["low"])
    r = np.array(r)
    out["catalogue_cn_price_vs_low"] = {"paid_with_low": int(len(r)), "median_ratio": round(float(np.median(r)), 2),
                                        "share_le_1.05": round(float((r <= C.NEAR_LOW).mean()), 4),
                                        "share_lt_2": round(float((r < 2).mean()), 4)}
    log(f"  CN catalogue current/record-low: {out['catalogue_cn_price_vs_low']}")
    q = {name: arr for name, arr in quals.items()}
    out["quality_arrays"] = {name: {"mean": round(float(a.mean()), 4),
                                    "spearman_vs_config": round(float(_spearman(a, q_cfg)), 4)} for name, a in q.items()}
    for v in variants:
        d = out[v]
        log(f"  {v:34s} hit@5 {d['hit5'][:3]} pct {d['pct'][0]} ILD {d['ild'][0]} price {d['price'][0]} "
            f"cur/low {d['ratio_low'][0]} near-low {d['near_low'][0]} <2x {d['within_2x_low'][0]} free {d['free'][0]} "
            f"overlap {d['overlap_current'][0]}")
        if "minus_price:none" in d or "minus_quality:beta_config" in d:
            diff = d.get("minus_price:none") or d.get("minus_quality:beta_config")
            log(f"  {'':34s} diff hit@5 {diff['hit5'][:3]} pct {diff['pct'][:3]} ILD {diff['ild'][:3]} "
                f"price {diff['price'][:3]} cur/low {diff['ratio_low'][:3]} near-low {diff['near_low'][:3]}")
    return out


def make_pref(z, kind="linear"):
    """price_pref with a different zero point: 1 at <= low x NEAR_LOW, 0 at >= low x z; linear or log in between."""
    lo = C.NEAR_LOW

    def pref(p):
        if p is None or p.get("is_free") or p.get("final") is None or not p.get("low"):
            return None
        r = p["final"] / p["low"]
        v = (z - r) / (z - lo) if kind == "linear" else 1 - np.log(max(r, lo) / lo) / np.log(z / lo)
        return float(min(1.0, max(0.0, v)))
    return pref


CURVES = {"linear_2x(current)": (2, "linear"), "linear_3x": (3, "linear"), "linear_4x": (4, "linear"),
          "linear_6x": (6, "linear"), "log_4x": (4, "log")}


def eval_price_curve(kb, us):
    """near_record_low under several price-preference curves (ranking.price_pref swapped here), vs no price intent."""
    import playnext.ranking as R
    from playnext.pricing import price_pref as pkg_pref
    prices = Prices(kb, live=False)
    snap = [prices.get(int(a), "CN") for a in kb.appids]
    cur = make_pref(2, "linear")
    assert all(cur(p) == pkg_pref(p) for p in snap), "linear_2x must reproduce pricing.price_pref"
    variants = ["none"] + list(CURVES)
    metrics = ["hit5", "any5", "pct", "ild", "price", "spend5", "ratio_low", "near_low", "within_2x_low", "free",
               "overlap_none"]
    res = {v: {m: [] for m in metrics} for v in variants}
    t0 = time.time()
    for k, u in enumerate(us):
        spec = SessionSpec(members=[Member(library=Library(owned=u["prof"]))])
        fr = hard_filter(kb, spec)
        rel, _ = relevance(kb, spec, fr.status >= UNKNOWN)
        if rel is None:
            continue
        runs = {}
        try:
            runs["none"] = [int(kb.appids[i]) for i in rank(kb, spec, rel, fr, prices).picks]
            s = spec.model_copy(update={"price_intent": "near_record_low"})
            for v, (z, kind) in CURVES.items():
                R.price_pref = make_pref(z, kind)
                runs[v] = [int(kb.appids[i]) for i in rank(kb, s, rel, fr, prices).picks]
        finally:
            R.price_pref = pkg_pref
        base = set(runs["none"])
        for v, picks in runs.items():
            d = res[v]
            hits = sum(a in u["targ"] for a in picks)
            d["hit5"].append(hits / min(5, len(u["targ"])))
            d["any5"].append(float(hits > 0))
            d["pct"].append(np.nanmean([kb.games.at[a, "pct_positive"] for a in picks]))
            T = kb.T[[kb.pos[a] for a in picks]]
            S = T @ T.T
            d["ild"].append(float(1 - S[np.triu_indices(len(picks), 1)].mean()) if len(picks) > 1 else np.nan)
            for m, x in price_metrics(prices, picks).items():
                d[m].append(x)
            d["overlap_none"].append(len(base & set(picks)) / max(1, len(picks)))
        if k % 500 == 0:
            log(f"  pricecurve {k}/{len(us)} ({time.time() - t0:.0f}s)")
    out = {"n_users": len(res["none"]["hit5"]), "curves": {k: {"zero_at": z, "shape": s} for k, (z, s) in CURVES.items()}}
    for v in variants:
        out[v] = {m: cin(x) for m, x in res[v].items()}
        if v != "none":
            out[v]["minus_none"] = {m: paired(res[v][m], res["none"][m]) for m in
                                    ("hit5", "any5", "pct", "ild", "price", "ratio_low", "near_low", "within_2x_low", "free")}
    # catalogue view: how many CN paid games get any price score under each curve
    out["catalogue_share_pref_gt0"] = {v: round(float(np.mean([make_pref(z, s)(p) > 0 for p in snap if make_pref(z, s)(p) is not None])), 4)
                                       for v, (z, s) in CURVES.items()}
    for v in variants:
        d = out[v]
        line = (f"  {v:20s} hit@5 {d['hit5'][:3]} near-low {d['near_low'][0]} cur/low {d['ratio_low'][0]} "
                f"price {d['price'][0]} pct {d['pct'][0]} ILD {d['ild'][0]} overlap {d['overlap_none'][0]}")
        log(line)
        if v != "none":
            m = d["minus_none"]
            log(f"  {'':20s} diff hit@5 {m['hit5'][:3]} near-low {m['near_low'][:3]} cur/low {m['ratio_low'][:3]} "
                f"price {m['price'][:3]} pct {m['pct'][:3]}")
    log(f"  catalogue share of CN paid games with price score > 0: {out['catalogue_share_pref_gt0']}")
    return out


def _spearman(a, b):
    ra, rb = np.argsort(np.argsort(a)), np.argsort(np.argsort(b))
    return np.corrcoef(ra, rb)[0, 1]


# ======================================================================================= 4. latency
_orig_channel_scores = scoring.channel_scores
_EX_CH = ThreadPoolExecutor(4, thread_name_prefix="chan")
_EX_MEM = ThreadPoolExecutor(4, thread_name_prefix="member")


def _channel_jobs(kb, a_ids, rows, w):
    def tag():
        return _wagg(kb.T[rows] @ kb.T.T, w, C.TAG_AGG)

    def colike():
        contrib = kb.ease_rows(a_ids) * w[:, None]
        return contrib.sum(0), contrib.argmax(0), contrib, kb.ease_has & bool(kb.ease_has[rows].any())

    def lineage():
        same_dev, same_ser, sim = kb.lineage(a_ids)
        parts = {"dev": same_dev, "ser": same_ser, "sim": sim}
        linked = set().union(*(parts[p] for p in C.LINEAGE_PARTS))
        return np.isin(kb.appids, list(linked)).astype(np.float32), same_dev, same_ser, sim
    return {"tag": tag, "colike": colike, "lineage": lineage}


def channel_scores_concurrent(kb, taste, pool):
    """scoring.channel_scores with the anchor channels computed in parallel threads; same output."""
    a_ids = [a for a in taste.anchors if a in kb.pos]
    if not a_ids or taste.outside or taste.feel_want or taste.feel_avoid:
        return _orig_channel_scores(kb, taste, pool)
    rows = [kb.pos[a] for a in a_ids]
    w = np.array([taste.anchors[a] for a in a_ids], np.float32)
    fut = {k: _EX_CH.submit(f) for k, f in _channel_jobs(kb, a_ids, rows, w).items()}
    r = {k: f.result() for k, f in fut.items()}
    ev, raw, has = {"anchors": a_ids}, {}, {}
    raw["tag"], ev["tag_hit"] = r["tag"]
    has["tag"] = kb.T_has
    raw["colike"], ev["co_hit"], ev["co_contrib"], has["colike"] = r["colike"]
    raw["lineage"], same_dev, same_ser, sim = r["lineage"]
    has["lineage"] = np.ones(kb.n, bool)
    ev.update(same_dev=same_dev, same_ser=same_ser, igdb_sim=sim)
    norm = {c: (raw[c] if c == "lineage" else minmax(raw[c], pool & has[c])) for c in raw}
    W = dict(C.WEIGHTS)
    if taste.same_studio:
        W["lineage"] = C.SAME_STUDIO_W
    wsum = sum(W[c] * has[c] for c in W)
    content = has["tag"] | has["colike"]
    fused = np.where(content, sum(W[c] * norm[c] * has[c] for c in W) / np.maximum(wsum, 1e-9), 0).astype(np.float32)
    return Scored(fused, norm, has, ev)


def relevance_with(kb, spec, pool, chan_concurrent=False, member_concurrent=False):
    if chan_concurrent:
        scoring.channel_scores = channel_scores_concurrent
    try:
        if not member_concurrent or spec.party_size == 1 or spec.has_shared:
            return relevance(kb, spec, pool)[0]
        ms = [m for m in spec.members if m.has_taste]

        def one(m):
            return minmax(personal(kb, member_taste(kb, m), pool).score, pool)
        return minmax(group_aggregate(list(_EX_MEM.map(one, ms))), pool)
    finally:
        scoring.channel_scores = _orig_channel_scores


def bench(fns, reps=30, warm=3):
    for _ in range(warm):
        for f in fns.values():
            f()
    t = {k: [] for k in fns}
    for _ in range(reps):
        for k, f in fns.items():  # interleaved so drift hits every variant alike
            t0 = time.perf_counter()
            f()
            t[k].append((time.perf_counter() - t0) * 1000)
    return {k: {"median_ms": round(statistics.median(v), 2), "p10_ms": round(float(np.percentile(v, 10)), 2),
                "p90_ms": round(float(np.percentile(v, 90)), 2)} for k, v in t.items()}


def eval_latency(kb, us):
    from playnext.scoring import library_anchors
    seed = 413150 if 413150 in kb.pos else int(kb.appids[np.argmax(kb.popularity)])
    n_anc = {id(u): len(library_anchors(kb, Member(library=Library(owned=u["prof"])))) for u in us}
    # a 50-anchor library: the largest held-out profiles merged until library_anchors() reaches its cap
    big = {}
    for u in sorted(us, key=lambda u: -n_anc[id(u)]):
        big.update({a: h for a, h in u["prof"].items() if a not in big})
        if len(library_anchors(kb, Member(library=Library(owned=big)))) >= C.MAX_LIBRARY_ANCHORS:
            break
    group_users = [u for u in us if n_anc[id(u)] >= 10][:4]
    specs = {
        "one_seed": SessionSpec(seeds=[seed]),
        "library50": SessionSpec(members=[Member(library=Library(owned=big))]),
        "group4_libraries": SessionSpec(members=[Member(name=f"m{k}", library=Library(owned=u["prof"]))
                                                 for k, u in enumerate(group_users)]),
    }
    try:
        from threadpoolctl import threadpool_info, threadpool_limits
        blas = [{k: d.get(k) for k in ("internal_api", "num_threads", "version")} for d in threadpool_info()]
    except Exception:  # noqa: BLE001
        blas, threadpool_limits = None, None
    out = {"env": {"cpu_count": os.cpu_count(), "numpy": np.__version__, "blas": blas, "reps": 30, "warmup": 3,
                   "channel_threads": 4, "member_threads": 4}}
    kb.ease_rows([int(kb.appids[0])])  # load the lazy tables before timing
    kb.lineage([int(kb.appids[0])])
    for name, spec in specs.items():
        fr = hard_filter(kb, spec)
        pool = fr.status >= UNKNOWN
        if spec.party_size == 1:
            taste = member_taste(kb, spec.members[0], spec.seeds)
        else:
            taste = member_taste(kb, spec.members[0])
        n_anchors = [len(member_taste(kb, m, spec.seeds if spec.party_size == 1 else ()).anchors) for m in spec.members]
        # outputs must match before timing means anything
        s0, s1 = _orig_channel_scores(kb, taste, pool), channel_scores_concurrent(kb, taste, pool)
        r0 = relevance_with(kb, spec, pool)
        same = {"channel_scores": bool(np.allclose(s0.score, s1.score)),
                "relevance_chan": bool(np.allclose(r0, relevance_with(kb, spec, pool, chan_concurrent=True)))}
        fns = {"channel_scores_serial": lambda: _orig_channel_scores(kb, taste, pool),
               "channel_scores_concurrent": lambda: channel_scores_concurrent(kb, taste, pool),
               "relevance_serial": lambda: relevance_with(kb, spec, pool),
               "relevance_chan_concurrent": lambda: relevance_with(kb, spec, pool, chan_concurrent=True)}
        if spec.party_size > 1:
            same["relevance_members"] = bool(np.allclose(r0, relevance_with(kb, spec, pool, member_concurrent=True)))
            fns["relevance_member_concurrent"] = lambda: relevance_with(kb, spec, pool, member_concurrent=True)
            fns["relevance_both_concurrent"] = lambda: relevance_with(kb, spec, pool, True, True)
        a_ids = [a for a in taste.anchors if a in kb.pos]
        jobs = _channel_jobs(kb, a_ids, [kb.pos[a] for a in a_ids], np.array([taste.anchors[a] for a in a_ids], np.float32))
        for k, f in jobs.items():
            fns[f"part_{k}"] = f
        t = bench(fns)
        out[name] = {"anchors_per_member": n_anchors, "pool": int(pool.sum()), "outputs_equal": same, "timings": t}
        if threadpool_limits is not None:  # same runs with single-threaded BLAS: concurrency is the only parallelism
            with threadpool_limits(1):
                out[name]["timings_blas1"] = bench(fns)
        log(f"  latency {name}: anchors {n_anchors} pool {int(pool.sum())} equal {same}")
        for tk in ("timings", "timings_blas1"):
            if tk not in out[name]:
                continue
            tt = out[name][tk]
            log(f"   [{tk}]")
            for k, v in tt.items():
                log(f"    {k:30s} median {v['median_ms']:8.2f} ms  (p10 {v['p10_ms']}, p90 {v['p90_ms']})")
            log(f"    sum of channel parts {sum(tt[f'part_{k}']['median_ms'] for k in jobs):.2f} ms; "
                f"slowest part {max(tt[f'part_{k}']['median_ms'] for k in jobs):.2f} ms")
    return out


# ======================================================================================= main
def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    cmds = set(cmd.split(","))  # e.g. "mech,rank"
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 3000
    T0 = time.time()
    log(f"===== eval_extra {cmd} (N {n})")
    kb = KB()
    res = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    us = users(kb, n)
    cfg = config_snapshot(kb)
    log(f"{len(us)} held-out reviewers; config {cfg}")
    runtime = res.get("runtime_s", {})
    for name, fn in (("mech", eval_mech), ("rank", eval_rank_extra), ("latency", eval_latency),
                     ("pricecurve", eval_price_curve)):
        if name in cmds or "all" in cmds:
            t0 = time.time()
            res[name] = fn(kb, us)
            res[name]["config"] = cfg
            runtime[name] = round(time.time() - t0, 1)
            res["runtime_s"] = runtime
            OUT.write_text(json.dumps(res, indent=1, ensure_ascii=False, default=float), encoding="utf-8")
            log(f"{name} done in {runtime[name]:.0f}s")
    runtime[f"last_run_{cmd}_total"] = round(time.time() - T0, 1)
    res["runtime_s"] = runtime
    res["config"] = cfg
    OUT.write_text(json.dumps(res, indent=1, ensure_ascii=False, default=float), encoding="utf-8")
    log(f"wrote {OUT} in {time.time() - T0:.0f}s")


if __name__ == "__main__":
    main()
