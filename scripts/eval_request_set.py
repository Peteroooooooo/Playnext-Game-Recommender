"""Request-set evaluation (design section 7): 32 real requests collected from public forums (eval/request_set_raw.jsonl).

For every request:
  system   : the full pipeline (LLM understanding, query encoder, rules, scores, ranking; snapshot prices so runs repeat)
  baseline : "ask a general LLM directly" with the same model (design 5.2 model point 7)
Measures:
  - real-user labels: games the original poster later said they loved / will try (positive) or rejected / had
    already played (negative); the thread's most suggested games (community consensus, weaker)
  - hard-constraint violations (CVR, design 7): each list checked against the knowledge base with the system's
    parsed SessionSpec (FAIL = violation, UNKNOWN = not checkable); share of names that are not core Steam games
  - blind LLM judge (0 / 1 / 2 per game, sources hidden and shuffled, facts from the KB given), supplementary only:
    the judge is the same model family as the baseline
  - latency per step; reason consistency (LLM reasons that passed the fact check)
Writes eval/request_set_results.json and eval/request_set_report.md. Only post text and game facts go to the LLM.
Usage: uv run python scripts/eval_request_set.py [run|report]
"""
import json
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from playnext import config as C  # noqa: E402
from playnext.cards import write_reasons  # noqa: E402
from playnext.encoder import Encoder  # noqa: E402
from playnext.llm import LLM, chat_json  # noqa: E402
from playnext.pipeline import Recommender  # noqa: E402
from playnext.rules import FAIL, PASS, UNKNOWN, hard_filter  # noqa: E402

EV = C.ROOT / "eval"
RAW = EV / "request_set_raw.jsonl"
OUT = EV / "request_set_results.json"
REPORT = EV / "request_set_report.md"
K = 5

BASELINE_SYS = """You are an expert on PC games on Steam. Recommend exactly 5 Steam PC games for the player's request below. Respect every constraint they state (players, local or online, budget, content they dislike, games they already played). Return JSON {"games": [{"title": "<official English Steam store title>", "why": "<one sentence>"}]}."""

NORMALISE_SYS = """Map each game name (any language, may be Traditional Chinese, nicknames or series names) to the official English Steam store title of the game most likely meant. If it is a series, give its best-known Steam entry. If it is not a PC/Steam game, give null. Return JSON {"<name as given>": "<English Steam title or null>"}."""

JUDGE_SYS = """You judge game recommendations for a real player's request. For each candidate you get facts from the Steam store (tags, multiplayer modes and limits, price, rating, short description). Score each candidate: 2 = clearly fits what the player asked (taste, feel and constraints), 1 = partly fits, 0 = does not fit or breaks a stated constraint. Judge only against the request; do not reward popularity. Return JSON {"<candidate id>": <0|1|2>, ...}."""


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def resolve_names(rec, llm, names):
    """Names -> appid via alias table; unknown ones normalised by the LLM to English titles, then resolved."""
    out, todo = {}, []
    for n in names:
        m = rec.resolver.resolve(n)
        if m.appid is not None:
            out[n] = m.appid
        else:
            todo.append(n)
    for i in range(0, len(todo), 60):
        batch = todo[i:i + 60]
        try:
            mp = chat_json(llm, NORMALISE_SYS, json.dumps(batch, ensure_ascii=False), "normalise")
        except Exception:
            mp = {}
        for n in batch:
            t = mp.get(n) if isinstance(mp, dict) else None
            m = rec.resolver.resolve(t) if t else None
            out[n] = m.appid if m and m.appid is not None else None
    return out


def game_facts(kb, a):
    g = kb.games.loc[a]
    p = kb.pc.get(a, {})
    tags = [kb.tag_en[t] for t in sorted(kb.tagset.get(a, set()), key=lambda t: -kb.tag_weight.get((a, t), 0))[:12]]
    cats = sorted(kb.categories.get(a, set()))
    modes = {38: "online co-op", 36: "online PvP", 39: "local co-op", 37: "local PvP", 24: "shared/split screen", 44: "Remote Play Together"}
    pr = kb.price(a, "US") or {}
    desc = (kb.descriptions.get((a, "en")) or "")[:300]
    return {"name": kb.name[a], "year": None if g["release_year"] != g["release_year"] else int(g["release_year"]),
            "tags": tags, "modes": [modes[c] for c in cats if c in modes],
            "max_players": {k: (None if p.get(k) != p.get(k) else p.get(k)) for k in ("onlinecoopmax", "offlinecoopmax")},
            "price_usd": None if pr.get("final") != pr.get("final") else pr.get("final"), "free": bool(g["is_free"]),
            "pct_positive": None if g["pct_positive"] != g["pct_positive"] else int(g["pct_positive"]), "description": desc}


def run():
    rows = [json.loads(l) for l in RAW.read_text(encoding="utf-8").splitlines() if l.strip()]
    llm = LLM(timeout=120)
    rec = Recommender(llm=llm, encoder=Encoder(), live_prices=False, reasons=False)
    kb = rec.kb
    rec.encoder("warm up")
    log(f"{len(rows)} requests")

    def understand(r):
        t0 = time.time()
        try:
            p, spec = rec.understand(r["text"])
            return p, spec, round(time.time() - t0, 1), None
        except Exception as e:
            return None, None, round(time.time() - t0, 1), str(e)[:200]

    def baseline(r):
        t0 = time.time()
        try:
            out = chat_json(llm, BASELINE_SYS, r["text"], "baseline")
            return [g.get("title") for g in out.get("games", [])][:K], round(time.time() - t0, 1)
        except Exception:
            return [], round(time.time() - t0, 1)

    with ThreadPoolExecutor(6) as ex:
        und = list(ex.map(understand, rows))
        base = list(ex.map(baseline, rows))
    log("understood + baseline done")
    results = []
    label_names = set()
    for r, (p, spec, secs, err), (btitles, bsecs) in zip(rows, und, base):
        item = {"id": r["id"], "scenario": r["scenario"], "lang": r["lang"], "understand_seconds": secs,
                "baseline_seconds": bsecs, "baseline_titles": btitles, "error": err}
        if spec is not None:
            res = rec.recommend(spec)
            item["understood"] = res.understood
            item["system"] = [c["appid"] for c in res.picks]
            item["system_names"] = [c["name_en"] for c in res.picks]
            item["backups"] = [b["appid"] for b in res.backups]
            item["unknown_group"] = [u["appid"] for u in res.unknown]
            item["timings"] = res.timings
            item["relax"] = res.relax
            item["notes"] = res.notes
            item["_cards"] = res.picks
            item["_spec"] = spec
        results.append(item)
        for f in (r.get("op_feedback") or []):
            label_names.add(f["game"])
        label_names.update(r.get("top_community_suggestions") or [])
        label_names.update(r.get("already_played") or [])
        label_names.update(btitles)
    names = resolve_names(rec, llm, sorted(n for n in label_names if n))
    log(f"resolved {sum(v is not None for v in names.values())} of {len(names)} names")

    def reasons(item):
        cards = item.get("_cards") or []
        t0 = time.time()
        write_reasons(cards, llm, "")
        return round(time.time() - t0, 1), sum(c["reason_source"] == "llm" for c in cards), len(cards)

    with ThreadPoolExecutor(6) as ex:
        rs = list(ex.map(reasons, results))
    for item, (secs, ok, n) in zip(results, rs):
        item["reasons_seconds"], item["reasons_llm_ok"], item["reasons_total"] = secs, ok, n

    judge_jobs = []
    for r, item in zip(rows, results):
        item["baseline"] = [names.get(t) for t in item["baseline_titles"]]
        fb = r.get("op_feedback") or []
        item["labels"] = {
            "positive": sorted({names.get(f["game"]) for f in fb if f["reaction"] in ("loved", "will_try")} - {None}),
            "negative": sorted({names.get(f["game"]) for f in fb if f["reaction"] in ("rejected", "already_played")} - {None}),
            "community": sorted({names.get(n) for n in (r.get("top_community_suggestions") or [])} - {None}),
            "played": sorted({names.get(n) for n in (r.get("already_played") or [])} - {None}),
        }
        spec = item.get("_spec")
        if spec is not None:
            fr = hard_filter(kb, spec)
            for src in ("system", "baseline"):
                st = []
                for a in item.get(src) or []:
                    if a is None:
                        st.append("not_core")
                    else:
                        v = int(fr.status[kb.pos[a]])
                        st.append({FAIL: "fail", UNKNOWN: "unknown", PASS: "pass"}[v])
                        if v == FAIL:
                            item.setdefault(f"{src}_violations", []).append(
                                {"game": kb.name[a], "why": fr.why(kb.pos[a], a)})
                item[f"{src}_rule_status"] = st
        cand = sorted({a for a in (item.get("system") or []) + [a for a in item["baseline"] if a]})
        judge_jobs.append((r, item, cand))

    def judge(job):
        r, item, cand = job
        if not cand:
            return {}
        ids = list(cand)
        random.Random(r["id"]).shuffle(ids)
        facts = {f"c{k}": game_facts(kb, a) for k, a in enumerate(ids)}
        user = f"Player request:\n{r['text']}\n\nCandidates:\n{json.dumps(facts, ensure_ascii=False)}"
        try:
            out = chat_json(llm, JUDGE_SYS, user, "judge")
        except Exception:
            return {}
        return {ids[k]: int(out.get(f"c{k}")) for k in range(len(ids)) if isinstance(out.get(f"c{k}"), (int, float))}

    with ThreadPoolExecutor(6) as ex:
        js = list(ex.map(judge, judge_jobs))
    for (r, item, cand), j in zip(judge_jobs, js):
        item["judge"] = {str(a): v for a, v in j.items()}
        item.pop("_cards", None)
        item.pop("_spec", None)
    OUT.write_text(json.dumps({"model": llm.model, "date": time.strftime("%Y-%m-%d"), "weights": C.WEIGHTS,
                               "results": results}, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    log(f"wrote {OUT}")


def report():
    d = json.loads(OUT.read_text(encoding="utf-8"))
    R = d["results"]
    lines = [f"# 请求集评估结果（{d['date']}，模型 {d['model']}）", ""]

    def stats(items, src):
        n_req = len(items)
        lists = [i.get(src) or [] for i in items]
        pos_hit = sum(len(set(l) & set(i["labels"]["positive"])) for l, i in zip(lists, items))
        neg_hit = sum(len(set(l) & set(i["labels"]["negative"] + i["labels"]["played"])) for l, i in zip(lists, items))
        has_pos = [i for i in items if i["labels"]["positive"]]
        req_pos = sum(bool(set(i.get(src) or []) & set(i["labels"]["positive"])) for i in has_pos)
        comm = [i for i in items if i["labels"]["community"]]
        comm_hit = sum(len(set(i.get(src) or []) & set(i["labels"]["community"])) for i in comm)
        st = [s for i in items for s in i.get(f"{src}_rule_status", [])]
        jd = [i["judge"].get(str(a)) for i in items for a in (i.get(src) or []) if a is not None and i["judge"].get(str(a)) is not None]
        n_games = sum(len(l) for l in lists)
        return {"requests": n_req, "games": n_games,
                "pos_hits": pos_hit, "req_with_pos_hit": f"{req_pos}/{len(has_pos)}",
                "neg_hits": neg_hit, "community_hits": f"{comm_hit}（{len(comm)} 条请求）",
                "fail": st.count("fail"), "unknown": st.count("unknown"), "not_core": st.count("not_core"),
                "checked": len(st), "judge_mean": round(float(np.mean(jd)), 2) if jd else None,
                "judge_2_share": round(float(np.mean([x == 2 for x in jd])), 2) if jd else None}

    for scen, title in ((None, "全部 32 条"), (1, "场景一：找下一款"), (2, "场景二：一起玩")):
        items = [i for i in R if scen is None or i["scenario"] == scen]
        lines += [f"## {title}", "", "| 指标 | 系统 | 直接问 LLM |", "|---|---|---|"]
        s, b = stats(items, "system"), stats(items, "baseline")
        rows = [("推荐的游戏数", "games"), ("命中原帖主说喜欢 / 想试的游戏（款）", "pos_hits"),
                ("有正面反馈的请求里命中至少一款", "req_with_pos_hit"),
                ("推荐了原帖主拒绝或已玩过的（款）", "neg_hits"), ("命中社区最多人推荐的游戏（款）", "community_hits"),
                ("违反硬条件（按知识库判 FAIL）", "fail"), ("无法判断（UNKNOWN）", "unknown"),
                ("不在核心库 / 认不出的名字", "not_core"), ("盲评平均分（0~2，补充参考）", "judge_mean"),
                ("盲评 2 分占比", "judge_2_share")]
        for label, k in rows:
            lines.append(f"| {label} | {s[k]} | {b[k]} |")
        lines.append("")
    kinds = {"已玩过 / 种子本身": "种子或已玩过", "多人模式或人数": ("在线", "同屏", "远程", "人数", "个位", "模式"),
             "预算": ("预算", "现价"), "区域不卖": "CN 区", "雷区内容": "雷区", "语言 / 平台": "支持",
             "机制组合（本系统自己的严格规则）": "机制组合"}
    count = {k: [0, 0] for k in kinds}
    for i in R:
        for col, src in ((0, "system"), (1, "baseline")):
            for v in i.get(f"{src}_violations", []):
                why = " ".join(v["why"])
                for k, pat in kinds.items():
                    if any(p in why for p in ([pat] if isinstance(pat, str) else pat)):
                        count[k][col] += 1
    lines += ["## 违规按类型（一款游戏可能同时违反几条）", "", "| 类型 | 系统 | 直接问 LLM |", "|---|---|---|"]
    lines += [f"| {k} | {a} | {b} |" for k, (a, b) in count.items()]
    lines.append("")
    ok = [i for i in R if i.get("system")]
    t_und = [i["understand_seconds"] for i in R]
    t_rec = [i["timings"]["total"] for i in ok]
    t_rs = [i["reasons_seconds"] for i in ok]
    lines += ["## 耗时与解释一致性", "",
              f"- 需求理解（LLM）中位 {np.median(t_und):.1f} 秒；规则 + 打分 + 排序 + 卡片中位 {np.median(t_rec):.2f} 秒；"
              f"推荐理由（LLM，结果出来后再补）中位 {np.median(t_rs):.1f} 秒；直接问 LLM 中位 {np.median([i['baseline_seconds'] for i in R]):.1f} 秒。",
              f"- LLM 理由通过事实校验的比例：{sum(i['reasons_llm_ok'] for i in ok)}/{sum(i['reasons_total'] for i in ok)}"
              "（不通过的改用模板理由）。",
              f"- 需求理解失败（LLM 两次都没给出有效 JSON）：{sum(1 for i in R if i.get('error'))} 条；"
              f"系统没给出推荐的：{sum(1 for i in R if not i.get('system'))} 条。", ""]
    lines += ["## 逐条", "", "| id | 场景 | 系统推荐 | 直接问 LLM | 正面反馈 | 系统违规 | LLM 违规 |", "|---|---|---|---|---|---|---|"]
    for i in R:
        v = lambda src: "；".join(f"{x['game']}（{'、'.join(x['why'])[:40]}）" for x in i.get(f"{src}_violations", [])) or "—"
        lines.append(f"| {i['id']} | {i['scenario']} | {'、'.join(i.get('system_names') or ['—'])} | "
                     f"{'、'.join(t or '?' for t in i['baseline_titles'])} | {len(i['labels']['positive'])} | {v('system')} | {v('baseline')} |")
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:60]))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "run":
        run()
    report()
