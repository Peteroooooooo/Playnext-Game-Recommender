"""Request-set evaluation (design section 7): 32 real requests collected from public forums (eval/request_set_raw.jsonl).

Hard conditions are checked against GOLD conditions written by reading each post (eval/request_set_gold.json),
not against the system's own parse, so a condition the parser misses counts against the system. Stages, each
cached in eval/cache/ so later stages make no new model calls for earlier work:
  run     Step 1 understanding; the system with the LLM rerank (default w_r) and without rerank; the direct-LLM
          baseline ("ask a general LLM", same model, design 5.2 model point 7); rerank candidates and raw scores
  local   dedicated reranker (Qwen3-Reranker, src/playnext/local_rerank.py) scores on the same candidates
  sweep   rerank fusion weight w_r x reranker type, recomputed from the cached scores (snapshot prices)
  judge   blind LLM judge, 0 / 1 / 2 per game over the union of all lists, sources hidden and shuffled; also writes
          eval/cache/judge_input.json for a second, independent judge (eval/cache/judge_claude.json if present)
  report  eval/request_set_report.md and eval/request_set_results.json
Dev / test split (design 7): within each scenario, alternate requests by id; w_r and the reranker are chosen on the
dev half by the mean judge score, the test half is reported.
Only post text and public game facts go to the LLMs.
Usage: uv run python scripts/eval_request_set.py [run|local|sweep|judge|report|all]
"""
import hashlib
import json
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from playnext import config as C  # noqa: E402
from playnext.cards import write_reasons  # noqa: E402
from playnext.llm import LLM, chat_json  # noqa: E402
from playnext.pipeline import Recommender  # noqa: E402
from playnext.rules import CAT_SINGLE, FAIL, PASS, UNKNOWN, _mode_status  # noqa: E402
from playnext.spec import SessionSpec  # noqa: E402
from playnext.understand import ParsedRequest  # noqa: E402

EV = C.ROOT / "eval"
CACHE = EV / "cache"
RAW, GOLD = EV / "request_set_raw.jsonl", EV / "request_set_gold.json"
OUT, REPORT = EV / "request_set_results.json", EV / "request_set_report.md"
K = 5
W_GRID = (0.3, 0.45, 0.6, 0.75, 0.9)
LOCAL_MODEL = "Qwen3-Reranker-4B"
# llm = LLM rerank on the request as is (production), llmn = with the mentioned games' English names appended,
# local / localn = the same two for Qwen3-Reranker
RERANKERS = ("llm", "llmn", "local", "localn")

BASELINE_SYS = """You are an expert on PC games on Steam. Recommend exactly 5 Steam PC games for the player's request below. Respect every constraint they state (players, local or online, budget, content they dislike, games they already played). Return JSON {"games": [{"title": "<official English Steam store title>", "why": "<one sentence>"}]}."""

NORMALISE_SYS = """Map each game name (any language, may be Traditional Chinese, nicknames or series names) to the official English Steam store title of the game most likely meant. If it is a series, give its best-known Steam entry. If it is not a PC/Steam game, give null. Return JSON {"<name as given>": "<English Steam title or null>"}."""

JUDGE_SYS = """You judge game recommendations for a real player's request. For each candidate you get facts from the Steam store (tags, multiplayer modes and limits, price, rating, short description). Score each candidate: 2 = clearly fits what the player asked (taste, feel and constraints), 1 = partly fits, 0 = does not fit or breaks a stated constraint. Judge only against the request; do not reward popularity. Return JSON {"<candidate id>": <0|1|2>, ...}."""

# gold avoid_hard concepts that map to Steam tags; a game breaks one when such a tag is a core tag (weight >= 0.5)
AVOID_TAGS = {
    "platformer": ["Platformer", "2D Platformer", "3D Platformer", "Precision Platformer"], "linear": ["Linear"],
    "soulslike": ["Souls-like"], "violence": ["Violent"], "gore": ["Gore"], "zombie": ["Zombies"],
    "horror": ["Horror", "Psychological Horror", "Survival Horror"], "sci-fi/space": ["Sci-fi", "Space"],
    "RTS": ["RTS"], "Japanese-style turn-based (JRPG)": ["JRPG"], "first-person": ["First-Person", "FPS"],
    "automation/factory": ["Automation"], "realistic": ["Realistic"], "sports": ["Sports"], "racing": ["Racing"],
    "inventory management": ["Inventory Management"], "cute party/group games": ["Party Game", "Party"],
}  # not mapped (no unambiguous tag): "XCOM-style squad tactics" (Turn-Based Tactics also covers the turn-based
   # strategy r20 asks for), "punishing", "linear story", "survival pressure", "friendslop" and similar
SOLO_REQUIRED = "co-op-only games that cannot be played solo (It Takes Two-style)"
EUR_USD_MARGIN = 1.25   # EUR caps are checked on US dollar prices: only a price above cap x 1.25 counts (no FX data)


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def load(name, default):
    p = CACHE / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def save(name, obj):
    CACHE.mkdir(parents=True, exist_ok=True)
    tmp = CACHE / (name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    tmp.replace(CACHE / name)


def rows():
    return [json.loads(l) for l in RAW.read_text(encoding="utf-8").splitlines() if l.strip()]


def split(rs):
    out = {}
    for scen in (1, 2):
        ids = sorted(r["id"] for r in rs if r["scenario"] == scen)
        for k, i in enumerate(ids):
            out[i] = "dev" if k % 2 == 0 else "test"
    return out


class Locked:
    """The encoder runs on the GPU; requests run in threads."""

    def __init__(self, f):
        self.f, self.lock = f, threading.Lock()

    def __call__(self, *a, **kw):
        with self.lock:
            return self.f(*a, **kw)

    def doc(self, text):
        with self.lock:
            return self.f.doc(text)


def make_rec(llm=None, encoder=None, **kw):
    rec = Recommender(llm=llm, encoder=encoder, live_prices=False, reasons=False, **kw)
    rec.want_failed = False
    return rec


def resolve_names(rec, llm, names, cache):
    """Names -> appid via the alias table; unknown ones normalised by the LLM to English titles, then resolved."""
    todo = [n for n in names if n not in cache]
    rest = []
    for n in todo:
        m = rec.resolver.resolve(n)
        if m.appid is not None:
            cache[n] = m.appid
        else:
            rest.append(n)
    for i in range(0, len(rest), 60):
        batch = rest[i:i + 60]
        try:
            mp = chat_json(llm, NORMALISE_SYS, json.dumps(batch, ensure_ascii=False), "normalise")
        except Exception:
            mp = {}
        for n in batch:
            t = mp.get(n) if isinstance(mp, dict) else None
            m = rec.resolver.resolve(t) if t else None
            cache[n] = m.appid if m and m.appid is not None else None
    return cache


# ---------------------------------------------------------------- run

def run():
    from playnext.encoder import Encoder
    rs = rows()
    llm = LLM(timeout=180)
    enc = Encoder()
    enc("warm up")
    enc = Locked(enc)
    rec = make_rec(llm, enc)
    plain = make_rec(llm, enc, rerank=False)
    kb = rec.kb
    und = load("understand.json", {})
    sysrun = load("system.json", {})
    base = load("baseline.json", {})
    log(f"{len(rs)} requests; cached understand {len(und)}, system {len(sysrun)}, baseline {len(base)}")

    def understand(r):
        if r["id"] in und:
            return
        t0 = time.time()
        try:
            p = rec.understander.parse(r["text"])
            und[r["id"]] = {"parsed": p.model_dump(), "seconds": round(time.time() - t0, 1), "error": None}
        except Exception as e:
            und[r["id"]] = {"parsed": None, "seconds": round(time.time() - t0, 1), "error": str(e)[:200]}

    def baseline(r):
        if r["id"] in base:
            return
        t0 = time.time()
        try:
            out = chat_json(llm, BASELINE_SYS, r["text"], "baseline")
            titles = [g.get("title") for g in out.get("games", [])][:K]
        except Exception:
            titles = []
        base[r["id"]] = {"titles": titles, "seconds": round(time.time() - t0, 1)}

    with ThreadPoolExecutor(6) as ex:
        list(ex.map(understand, rs))
        save("understand.json", und)
        list(ex.map(baseline, rs))
        save("baseline.json", base)
    log("understood + baseline done")

    def system(r):
        u = und[r["id"]]
        if r["id"] in sysrun or u["parsed"] is None:
            return
        spec = rec.understander.to_spec(ParsedRequest.model_validate(u["parsed"]), r["text"])
        res = rec.recommend(spec)
        res0 = plain.recommend(spec)
        t0 = time.time()
        write_reasons(res.picks, llm, spec.request_text)
        sysrun[r["id"]] = {
            "spec": spec.model_dump(), "understood": res.understood, "notes": res.notes, "timings": res.timings,
            "picks": [c["appid"] for c in res.picks], "no_rerank": [c["appid"] for c in res0.picks],
            "unknown": [u["appid"] for u in res.unknown], "relax": res.relax, "rerank": res.debug.get("rerank"),
            "reasons_seconds": round(time.time() - t0, 1),
            "reasons_llm_ok": sum(c["reason_source"] == "llm" for c in res.picks), "reasons_total": len(res.picks)}

    with ThreadPoolExecutor(6) as ex:
        list(ex.map(system, rs))
    save("system.json", sysrun)
    log(f"system done: {sum(1 for v in sysrun.values() if v['picks'])} with picks")

    names = load("names.json", {})
    want = set()
    for r in rs:
        want |= {f["game"] for f in (r.get("op_feedback") or [])} | set(r.get("top_community_suggestions") or [])
        want |= {t for t in base[r["id"]]["titles"] if t}
    resolve_names(rec, llm, sorted(want), names)
    save("names.json", names)
    log(f"resolved {sum(v is not None for v in names.values())} of {len(names)} names")


# ---------------------------------------------------------------- local reranker

def local():
    """Qwen3-Reranker on the cached candidates, with the request as is and with the English names of the games it
    mentions appended (rerank.with_game_names). Runs without the text encoder: both 4B models do not fit in 16 GB."""
    from playnext.kb import KB
    from playnext.local_rerank import LocalReranker, game_doc
    from playnext.rerank import with_game_names
    kb = KB()
    sysrun = load("system.json", {})
    out = load(f"local_{LOCAL_MODEL}.json", {})
    rr = LocalReranker(LOCAL_MODEL)
    for rid, s in sysrun.items():
        if rid in out or not s.get("rerank"):
            continue
        cand = s["rerank"]["cand"]
        docs = [game_doc(kb, kb.pos[a]) for a in cand]
        spec = SessionSpec.model_validate(s["spec"])
        rec = {}
        for variant, named in (("scores", False), ("scores_named", True)):
            texts = {k: _target_text(kb, spec, k, named) for k in s["rerank"]["scores"]}
            t0 = time.time()
            rec[variant] = {k: dict(zip(map(str, cand), map(float, rr.score(q, docs, batch_size=16))))
                            for k, q in texts.items()}
            rec["seconds" if not named else "seconds_named"] = round(time.time() - t0, 2)
        out[rid] = rec
        log(rid, f"{len(cand)} docs x {len(rec['scores'])} queries in {rec['seconds']} s")
        save(f"local_{LOCAL_MODEL}.json", out)


def llm_named():
    """The LLM rerank again on the same candidates, with the mentioned games' English names appended."""
    from playnext.kb import KB
    from playnext.rerank import llm_scores, with_game_names
    kb = KB()
    llm = LLM(timeout=180)
    sysrun = load("system.json", {})
    out = load("llm_named.json", {})

    def one(item):
        rid, s = item
        if rid in out or not s.get("rerank"):
            return rid, None
        spec = SessionSpec.model_validate(s["spec"])
        cand = [kb.pos[a] for a in s["rerank"]["cand"]]
        keys = {k: (k if k in ("me", "shared") else int(k)) for k in s["rerank"]["scores"]}
        texts = {keys[k]: _target_text(kb, spec, k, True) for k in keys}
        t0 = time.time()
        try:
            sc = llm_scores(kb, llm, texts, cand)
        except Exception:
            return rid, None
        return rid, {"scores": {str(k): {int(kb.appids[i]): v for i, v in d.items()} for k, d in sc.items()},
                     "seconds": round(time.time() - t0, 1)}

    with ThreadPoolExecutor(6) as ex:
        for rid, v in ex.map(one, list(sysrun.items())):
            if v:
                out[rid] = v
    save("llm_named.json", out)
    log(f"llm_named: {len(out)} requests")


def _target_text(kb, spec, k, named=False):
    from playnext.rerank import with_game_names
    text = (spec.request_text or spec.preference_text) if k in ("me", "shared") else spec.members[int(k)].preference_text
    return with_game_names(kb, spec, text) if named else text


# ---------------------------------------------------------------- sweep

def sweep():
    rs = rows()
    sysrun = load("system.json", {})
    loc = load(f"local_{LOCAL_MODEL}.json", {})
    named = load("llm_named.json", {})
    rec = make_rec()
    out = {}
    for r in rs:
        s = sysrun.get(r["id"])
        if not s:
            continue
        spec = SessionSpec.model_validate(s["spec"])
        lists = {"system": s["picks"], "no_rerank": s["no_rerank"]}
        sources = {}
        if s.get("rerank"):
            sources["llm"] = s["rerank"]["scores"]
            if r["id"] in named:
                sources["llmn"] = named[r["id"]]["scores"]
            if r["id"] in loc:
                sources["local"] = loc[r["id"]]["scores"]
                sources["localn"] = loc[r["id"]]["scores_named"]
        for src in RERANKERS:
            for w in W_GRID:
                if src in sources:
                    sc = {k: {int(a): v for a, v in d.items()} for k, d in sources[src].items()}
                    lists[f"{src}_w{w}"] = [c["appid"] for c in rec.recommend(spec, sc, w).picks]
                else:  # no preference words: nothing to rerank, the variant equals the system
                    lists[f"{src}_w{w}"] = s["picks"] if not s.get("rerank") else None
        out[r["id"]] = {k: v for k, v in lists.items() if v is not None}
    save("sweep.json", out)
    log(f"sweep: {len(out)} requests x {len(next(iter(out.values())))} lists")


# ---------------------------------------------------------------- judge

def game_facts(kb, a):
    g = kb.games.loc[a]
    p = kb.pc.get(a, {})
    tags = [kb.tag_en[t] for t in sorted(kb.tagset.get(a, set()), key=lambda t: -kb.tag_weight.get((a, t), 0))[:12]]
    cats = sorted(kb.categories.get(a, set()))
    modes = {2: "single-player", 38: "online co-op", 36: "online PvP", 39: "local co-op", 37: "local PvP",
             24: "shared/split screen", 44: "Remote Play Together"}
    pr = kb.price(a, "US") or {}
    desc = (kb.descriptions.get((a, "en")) or "")[:300]
    nan = lambda v: v != v
    return {"name": kb.name[a], "year": None if nan(g["release_year"]) else int(g["release_year"]),
            "tags": tags, "modes": [modes[c] for c in cats if c in modes],
            "max_players": {k: (None if nan(p.get(k)) else p.get(k)) for k in ("onlinecoopmax", "offlinecoopmax")},
            "price_usd": None if nan(pr.get("final")) else pr.get("final"), "free": bool(g["is_free"]),
            "pct_positive": None if nan(g["pct_positive"]) else int(g["pct_positive"]), "description": desc}


def judge():
    from playnext.kb import KB
    kb = KB()
    rs = rows()
    sw = load("sweep.json", {})
    base = load("baseline.json", {})
    names = load("names.json", {})
    llm = LLM(timeout=180)
    jd = load("judge.json", {})
    inputs = {}
    jobs = []
    for r in rs:
        lists = dict(sw.get(r["id"], {}))
        lists["baseline"] = [names.get(t) for t in base[r["id"]]["titles"] if t]
        cand = sorted({a for l in lists.values() for a in l if a is not None and a in kb.pos})
        ids = list(cand)
        random.Random(r["id"]).shuffle(ids)
        facts = {f"c{k}": game_facts(kb, a) for k, a in enumerate(ids)}
        inputs[r["id"]] = {"request": r["text"], "candidates": facts, "_ids": {f"c{k}": a for k, a in enumerate(ids)}}
        key = hashlib.sha1(json.dumps(ids).encode()).hexdigest()[:12]
        if jd.get(r["id"], {}).get("key") != key:
            jobs.append((r, ids, facts, key))

    def run_one(job):
        r, ids, facts, key = job
        user = f"Player request:\n{r['text']}\n\nCandidates:\n{json.dumps(facts, ensure_ascii=False)}"
        try:
            out = chat_json(llm, JUDGE_SYS, user, "judge")
        except Exception:
            return r["id"], None
        sc = {str(ids[k]): int(out.get(f"c{k}")) for k in range(len(ids)) if isinstance(out.get(f"c{k}"), (int, float))}
        return r["id"], {"key": key, "scores": sc}

    with ThreadPoolExecutor(6) as ex:
        for rid, v in ex.map(run_one, jobs):
            if v:
                jd[rid] = v
    save("judge.json", jd)
    blind = {rid: {"request": v["request"], "candidates": v["candidates"]} for rid, v in inputs.items()}
    save("judge_input.json", blind)
    save("judge_ids.json", {rid: v["_ids"] for rid, v in inputs.items()})
    log(f"judged {len(jobs)} requests; {sum(len(v['candidates']) for v in blind.values())} candidates in total")


# ---------------------------------------------------------------- checks against gold

def gold_check(kb, g, a):
    """-> (status, reasons): 'fail' (breaks a stated condition), 'unknown' (a fact is missing), 'pass', 'not_core'."""
    if a is None or a not in kb.pos:
        return "not_core", ["不在核心库 / 认不出"]
    fails, unk = [], []
    gone = {v for k, v in g["resolved"].items() if v and (k in g["already_played"] or k in g["excluded"])}
    if a in gone:
        fails.append("帖子说玩过或排除")
    tagw = {kb.tag_en[t]: kb.tag_weight.get((a, t), 0) for t in kb.tagset.get(a, set())}
    for concept in g["avoid_hard"]:
        hit = [t for t in AVOID_TAGS.get(concept, []) if tagw.get(t, 0) >= C.CORE_TAG_SHARE]
        if hit:
            fails.append(f"雷区：{concept}（核心标签 {'、'.join(hit)}）")
    cats = kb.categories.get(a, set())
    n = g["party_size"] or (2 if not (g["single_player_required"]) else 1)
    if (g["single_player_required"] or SOLO_REQUIRED in g["avoid_hard"]) and cats and CAT_SINGLE not in cats:
        fails.append("没有单人模式")
    if n >= 2:
        kinds = {"online": ["online"], "local": ["local"], "remote_or_online": ["online", "remote"]}.get(
            g["setup"], ["online", "remote", "local"])
        inter = g["interaction"] or "any"
        st = [_mode_status(kb, a, k, inter, n, [n] if k == "local" else [1] * n) for k in kinds]
        best = max(s[0] for s in st)
        if best == FAIL:
            fails.append("人数 / 模式：" + "；".join(s[1] for s in st if s[1]))
        elif best == UNKNOWN:
            unk.append("人数 / 模式：" + "；".join(s[1] for s in st if s[0] == UNKNOWN and s[1]))
    b = g["budget"]
    if b:
        p = kb.price(a, "US") or {}
        final = 0.0 if kb.is_free[a] else p.get("final")
        if final is None or final != final:
            unk.append("美区价格未知")
        elif b["currency"] == "USD" and final > b["amount"]:
            fails.append(f"超预算：${final:g} > ${b['amount']:g}")
        elif b["currency"] == "EUR" and final > b["amount"] * EUR_USD_MARGIN:
            fails.append(f"超预算：${final:g}，远高于 €{b['amount']:g}")
    if fails:
        return "fail", fails
    if unk:
        return "unknown", unk
    return "pass", []


def intent_accuracy(kb, gold, sysrun):
    """System parse vs gold, per slot (design 7 '意图理解：SessionSpec 槽位 Precision / Recall')."""
    acc = {k: [0, 0] for k in ("party_size", "setup", "budget")}
    excl_tp = excl_gold = excl_sys = 0
    av_tp = av_gold = 0
    misses = []
    for rid, g in gold.items():
        s = sysrun.get(rid)
        if not s:
            continue
        spec = SessionSpec.model_validate(s["spec"])
        if g["party_size"] is not None:
            acc["party_size"][1] += 1
            ok = spec.party_size == g["party_size"]
            acc["party_size"][0] += ok
            if not ok:
                misses.append(f"{rid} 人数：系统 {spec.party_size}，帖子 {g['party_size']}")
        if g["setup"] is not None and g["party_size"] and g["party_size"] > 1:
            acc["setup"][1] += 1
            want = {"local": {"local"}, "online": {"online"}, "remote_or_online": {"online", "remote"}}[g["setup"]]
            ok = bool(set(spec.setup_types)) and set(spec.setup_types) <= want | ({"remote"} if g["setup"] == "online" else set())
            acc["setup"][0] += ok
            if not ok:
                misses.append(f"{rid} 开局：系统 {spec.setup_types}，帖子 {g['setup']}")
        acc["budget"][1] += 1
        sb = spec.budget or spec.budget_unsupported
        gb = g["budget"]
        ok = (sb is None and gb is None) or (sb is not None and gb is not None and abs(sb.amount - gb["amount"]) < 1e-6
                                             and sb.currency == gb["currency"])
        acc["budget"][0] += ok
        if not ok:
            misses.append(f"{rid} 预算：系统 {sb.model_dump() if sb else None}，帖子 {gb}")
        gone = {v for k, v in g["resolved"].items() if v and (k in g["already_played"] or k in g["excluded"])}
        sys_gone = set(spec.seeds) | set(spec.excluded)
        for m in spec.members:
            sys_gone |= set(m.played_elsewhere) | set(m.seeds)
        excl_gold += len(gone)
        excl_sys += len(sys_gone)
        excl_tp += len(gone & sys_gone)
        for x in sorted(gone - sys_gone):
            misses.append(f"{rid} 漏掉玩过 / 排除：{kb.display_name(x)}")
        avoid_sys = {kb.tag_en[t] for m in spec.members for t in m.avoid_tags}
        for concept in g["avoid_hard"]:
            if concept in AVOID_TAGS:
                av_gold += 1
                hit = bool(set(AVOID_TAGS[concept]) & avoid_sys)
                av_tp += hit
                if not hit:
                    misses.append(f"{rid} 漏掉雷区：{concept}")
    return {"party_size": acc["party_size"], "setup": acc["setup"], "budget": acc["budget"],
            "played_excluded_recall": [excl_tp, excl_gold], "played_excluded_precision": [excl_tp, excl_sys],
            "avoid_recall": [av_tp, av_gold], "misses": misses}


# ---------------------------------------------------------------- report

def report():
    from playnext.kb import KB
    kb = KB()
    rs = rows()
    gold = json.loads(GOLD.read_text(encoding="utf-8"))
    sysrun, base, names = load("system.json", {}), load("baseline.json", {}), load("names.json", {})
    und, sw, jd = load("understand.json", {}), load("sweep.json", {}), load("judge.json", {})
    # the second judge scores the blind candidate ids of judge_input.json; map them back to appids
    ids = load("judge_ids.json", {})
    jc = {rid: {str(ids[rid][c]): int(v) for c, v in sc.items() if c in ids.get(rid, {}) and isinstance(v, (int, float))}
          for rid, sc in load("judge_claude.json", {}).items()}
    loc = load(f"local_{LOCAL_MODEL}.json", {})
    sp = split(rs)
    lists = {}
    for r in rs:
        L = dict(sw.get(r["id"], {}))
        L["baseline"] = [names.get(t) for t in base[r["id"]]["titles"] if t]
        lists[r["id"]] = L
    reranked = [f"{s}_w{w}" for s in RERANKERS for w in W_GRID if any(f"{s}_w{w}" in L for L in sw.values())]
    variants = ["system", "no_rerank"] + reranked + ["baseline"]

    def labels(r):
        fb = r.get("op_feedback") or []
        pos = {names.get(f["game"]) for f in fb if f["reaction"] in ("loved", "will_try")} - {None}
        neg = {names.get(f["game"]) for f in fb if f["reaction"] in ("rejected", "already_played")} - {None}
        com = {names.get(n) for n in (r.get("top_community_suggestions") or [])} - {None}
        return pos, neg, com

    def stats(ids, v):
        n_games = fails = unk = notcore = pos = neg = com = 0
        j, jcl, fail_rows = [], [], []
        req_pos = [0, 0]
        for r in rs:
            if r["id"] not in ids:
                continue
            L = lists[r["id"]].get(v) or []
            g = gold[r["id"]]
            P, N, Cm = labels(r)
            n_games += len(L)
            for a in L:
                st, why = gold_check(kb, g, a)
                fails += st == "fail"
                unk += st == "unknown"
                notcore += st == "not_core"
                if st == "fail":
                    fail_rows.append((r["id"], kb.display_name(a), why))
                if a is not None and str(a) in jd.get(r["id"], {}).get("scores", {}):
                    j.append(jd[r["id"]]["scores"][str(a)])
                if a is not None and str(a) in jc.get(r["id"], {}):
                    jcl.append(jc[r["id"]][str(a)])
            pos += len(set(L) & P)
            neg += len(set(L) & N)
            com += len(set(L) & Cm)
            if P:
                req_pos[1] += 1
                req_pos[0] += bool(set(L) & P)
        return {"games": n_games, "fail": fails, "unknown": unk, "not_core": notcore, "pos": pos,
                "req_pos": f"{req_pos[0]}/{req_pos[1]}", "neg": neg, "community": com,
                "judge": round(float(np.mean(j)), 2) if j else None,
                "judge2": round(float(np.mean([x == 2 for x in j])), 2) if j else None,
                "judge_claude": round(float(np.mean(jcl)), 2) if jcl else None, "fail_rows": fail_rows}

    all_ids = {r["id"] for r in rs}
    dev = {i for i, s in sp.items() if s == "dev"}
    test = all_ids - dev
    S = {v: {"all": stats(all_ids, v), "dev": stats(dev, v), "test": stats(test, v)} for v in variants}
    # the LLM rerank and the first judge are the same model, so the choice uses the second judge when there is one
    jkey = "judge_claude" if jc else "judge"
    dev_key = lambda v: (S[v]["dev"][jkey] or 0, S[v]["dev"]["community"])
    best = {src: max((v for v in reranked if v.startswith(src + "_w")), key=dev_key)
            for src in RERANKERS if any(v.startswith(src + "_w") for v in reranked)}
    best_all = max(best.values(), key=dev_key) if best else "system"

    lines = [f"# 请求集评估结果（{time.strftime('%Y-%m-%d')}，生成式模型 {C_model()}）", "",
             "32 条论坛真实求推荐帖（Reddit 16、PTT 15、知乎 1；两个场景各 16 条）。每条帖子交给两方：本系统，和“直接问同一个 LLM 推荐 5 款”。",
             "硬条件按 `eval/request_set_gold.json` 检查：逐帖阅读写下的条件（人数、开局方式、单人、预算、说过玩过或排除的游戏、明确拒绝的内容），"
             "**不用系统自己的理解**，所以系统读漏的条件也算系统违规。雷区只认核心标签（票数占比 ≥ 0.5）；欧元预算没有汇率数据，按美区美元价超过上限 1.25 倍才算违规。", ""]
    main = f"{'llmn' if C.RERANK_GAME_NAMES else 'llm'}_w{C.RERANK_W}"
    main = main if main in S else "system"
    lines += ["## 总表（全部 32 条）", "",
              f"“系统”一列是现行设置（{main}：LLM 精排 w_r = {C.RERANK_W}" + ("，附游戏英文名" if C.RERANK_GAME_NAMES else "") +
              "），它是在开发集上选出来的，所以开发集一半的数字偏乐观，看下面测试集一列更公平。", "",
              "| 指标 | 系统（现行设置） | 不精排 | 直接问 LLM |", "|---|---|---|---|"]
    rowdefs = [("推荐的游戏数", "games"), ("违反帖子里写明的硬条件（款）", "fail"), ("缺事实、无法判断（款）", "unknown"),
               ("不在核心库 / 认不出（款）", "not_core"), ("命中原帖主说喜欢 / 想试的（款）", "pos"),
               ("有正面反馈的请求里命中至少一款", "req_pos"), ("推荐了原帖主后来说拒绝或已玩过的（款）", "neg"),
               ("命中帖子里网友推荐最多的（款）", "community"), ("LLM 盲评平均（0~2）", "judge"), ("LLM 盲评 2 分占比", "judge2"),
               ("第二评委盲评平均（0~2，另一模型家族）", "judge_claude")]
    for label, k in rowdefs:
        lines.append(f"| {label} | {S[main]['all'][k]} | {S['no_rerank']['all'][k]} | {S['baseline']['all'][k]} |")
    lines.append("")
    for scen, title in ((1, "场景一：找下一款"), (2, "场景二：一起玩")):
        ids = {r["id"] for r in rs if r["scenario"] == scen}
        a, b = stats(ids, main), stats(ids, "baseline")
        lines += [f"### {title}", "", "| 指标 | 系统 | 直接问 LLM |", "|---|---|---|"]
        for label, k in rowdefs:
            lines.append(f"| {label} | {a[k]} | {b[k]} |")
        lines.append("")
    lines += ["## 违规明细（按帖子写明的条件）", ""]
    for v, title in ((main, "系统"), ("baseline", "直接问 LLM")):
        fr = S[v]["all"]["fail_rows"]
        lines.append(f"**{title}**（{len(fr)} 款）：" + ("；".join(f"{rid}《{n}》{'、'.join(w)}" for rid, n, w in fr) or "无"))
        lines.append("")
    lines += ["## 精排器与 w_r（开发集选、测试集报告）", "",
              "开发 / 测试按场景内 id 交替拆分（各 16 条）。只在开发集上比较；“不精排”与各精排设置用同一份候选与打分。", "",
              f"按{'第二评委（另一模型家族）' if jc else 'LLM 盲评'}在开发集上选。",
              "", "| 设置 | 开发集盲评（同一 LLM） | 开发集第二评委 | 开发集网友共识 | 测试集盲评（同一 LLM） | 测试集第二评委 | 测试集网友共识 | 测试集违规 |",
              "|---|---|---|---|---|---|---|---|"]
    names_zh = {"llm": "LLM 精排", "llmn": "LLM 精排 + 游戏英文名", "local": LOCAL_MODEL, "localn": f"{LOCAL_MODEL} + 游戏英文名"}
    for v in ["no_rerank"] + reranked:
        d, t = S[v]["dev"], S[v]["test"]
        mark = " ←" if v in best.values() else ""
        lines.append(f"| {v}{mark} | {d['judge']} | {d['judge_claude']} | {d['community']} | {t['judge']} | {t['judge_claude']} | "
                     f"{t['community']} | {t['fail']} |")
    lt = [v["seconds"] for v in loc.values()]
    rr = [s["timings"].get("rerank") for s in sysrun.values() if s["timings"].get("rerank")]
    lines += ["", "开发集上各精排器最好的设置：" + "；".join(f"{names_zh[s]} {v}" for s, v in best.items()) +
              f"。综合最好：{best_all}。"
              f"耗时中位：LLM 精排 {np.median(rr):.1f} 秒" + (f"；{LOCAL_MODEL} {np.median(lt):.1f} 秒（本机 GPU，模型已载入）" if lt else "") +
              "。名字后缀 = 把帖子里提到的游戏的英文官方名附在请求后面（`rerank.with_game_names`）。", ""]
    ia = intent_accuracy(kb, gold, sysrun)
    f = lambda x: f"{x[0]}/{x[1]}（{x[0] / x[1]:.0%}）" if x[1] else "—"
    lines += ["## 需求理解准确率（系统理解 vs 逐帖写下的条件）", "",
              f"- 人数：{f(ia['party_size'])}；开局方式：{f(ia['setup'])}；预算（金额 + 币种，含“没说预算”）：{f(ia['budget'])}",
              f"- 说过玩过 / 排除的游戏：召回 {f(ia['played_excluded_recall'])}，精确 {f(ia['played_excluded_precision'])}"
              "（系统一侧含种子游戏，种子本来也不会被推荐）",
              f"- 能对上 Steam 标签的雷区：召回 {f(ia['avoid_recall'])}", "",
              "<details><summary>逐条漏读</summary>", ""] + [f"- {m}" for m in ia["misses"]] + ["", "</details>", ""]
    ok = [s for s in sysrun.values() if s["picks"]]
    t_und = [u["seconds"] for u in und.values()]
    lines += ["## 耗时与解释一致性", "",
              f"- 需求理解（LLM）中位 {np.median(t_und):.1f} 秒；规则 + 打分 + 精排 + 排序 + 卡片中位 "
              f"{np.median([s['timings']['total'] for s in ok]):.1f} 秒；推荐理由（结果出来后再补）中位 "
              f"{np.median([s['reasons_seconds'] for s in ok]):.1f} 秒；直接问 LLM 中位 "
              f"{np.median([b['seconds'] for b in base.values()]):.1f} 秒。",
              f"- LLM 理由通过事实校验：{sum(s['reasons_llm_ok'] for s in ok)}/{sum(s['reasons_total'] for s in ok)}（不通过的用模板理由）。",
              f"- 需求理解失败：{sum(1 for u in und.values() if u['error'])} 条；系统没给出推荐：{sum(1 for s in sysrun.values() if not s['picks'])} 条。", ""]
    lines += ["## 逐条", "", "| id | 场景 | 拆分 | 系统推荐 | 直接问 LLM | 系统违规 | LLM 违规 |", "|---|---|---|---|---|---|---|"]
    for r in rs:
        rid = r["id"]
        g = gold[rid]
        nm = lambda a: kb.display_name(a) if a in kb.pos else "?"
        v = lambda key: "；".join(f"{nm(a)}（{'、'.join(gold_check(kb, g, a)[1])[:50]}）" for a in lists[rid].get(key, [])
                                  if gold_check(kb, g, a)[0] == "fail") or "—"
        lines.append(f"| {rid} | {r['scenario']} | {sp[rid]} | {'、'.join(nm(a) for a in lists[rid].get(main, [])) or '—'} | "
                     f"{'、'.join(t or '?' for t in base[rid]['titles'])} | {v(main)} | {v('baseline')} |")
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    OUT.write_text(json.dumps({"date": time.strftime("%Y-%m-%d"), "weights": C.WEIGHTS, "rerank_w": C.RERANK_W,
                               "split": sp, "stats": {v: {k: {kk: vv for kk, vv in x.items() if kk != "fail_rows"}
                                                          for k, x in S[v].items()} for v in variants},
                               "best_dev": best, "best_dev_overall": best_all, "intent": ia},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n".join(lines[:40]))


def C_model():
    try:
        from playnext.pricing import load_env
        return load_env().get("LLM_MODEL", "?")
    except Exception:
        return "?"


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    steps = {"run": [run], "local": [local], "llm_named": [llm_named], "sweep": [sweep], "judge": [judge],
             "report": [report], "all": [run, llm_named, local, sweep, judge, report]}[cmd]
    for s in steps:
        s()
