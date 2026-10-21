"""The system vs "just ask the LLM" on held-out Steam reviewers (design 7 offline evaluation).

Held-out reviewers (hash % 10 == 0, never used for EASE or the playtime reference) with 8~60 positive reviews of core
games. Positives sorted by time: the earlier half is the "library" (appid -> hours_total), the later half is hidden.
Each method recommends 20 games not in the library; recall@20 = share of the hidden positives found.
  system  : Recommender.recommend with the library only (no request text, so no rerank), picks + backups
  llm     : the generative LLM gets the library as English titles + hours and names 20 games; names go through the
            alias table, then unmatched ones through an LLM title normaliser, then the alias table again; names still
            unmatched (not on Steam / not in the core library) are dropped and recorded
  llm_core: as llm, but only the resolved games count and the list is judged on the games it did name in the core
            library (shows how much the core-library limit costs the LLM)
  popular : the 20 most-reviewed core games not in the library
Paired bootstrap 95% CI on per-user recall differences. Only game titles and hours are sent to the LLM.
LLM answers are cached in data/derived/eval_vs_llm_cache.json, so a rerun makes no new calls for users already done.
Usage: uv run python scripts/eval_vs_llm.py [n_users=200] [seed=1]
"""
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from playnext import config as C  # noqa: E402
from playnext.llm import LLM, chat_json  # noqa: E402
from playnext.pipeline import Recommender  # noqa: E402
from playnext.spec import Library, Member, SessionSpec  # noqa: E402

K = 20
SYS = ("You are a game recommender. The user lists Steam games they played, with hours. Recommend exactly 20 other "
       "Steam games they are most likely to enjoy next. Do not repeat games from the list. Return JSON only: "
       '{"games": ["<official Steam title>", ...]}')
NORM_SYS = ("Map each game name to the official English Steam store title of the game meant. If it is not on Steam, "
            'give null. Return JSON {"<name as given>": "<Steam title or null>"}.')
CACHE = C.DER / "eval_vs_llm_cache.json"


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def ci(diff, n=2000, seed=0):
    rng = np.random.default_rng(seed)
    d = np.asarray(diff)
    s = [d[rng.integers(0, len(d), len(d))].mean() for _ in range(n)]
    return float(np.percentile(s, 2.5)), float(np.percentile(s, 97.5))


def main():
    n_users = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    llm = LLM()
    rec = Recommender(llm=None, encoder=None, live_prices=False, reasons=False, rerank=False)
    rec.want_failed = False
    kb = rec.kb
    t = pd.read_parquet(C.DER / "eval_reviews100m_test.parquet")
    t = t[t["voted_up"] & t["app_id"].isin(kb.pos)].sort_values(["user_hash", "date"])
    t = t.drop_duplicates(["user_hash", "app_id"])
    size = t.groupby("user_hash").size()
    ok = size[(size >= 8) & (size <= 60)].index.to_numpy()
    pick = np.random.default_rng(seed).choice(ok, size=n_users, replace=False)
    sub = t[t["user_hash"].isin(pick)]
    groups = dict(tuple(sub.groupby("user_hash")))
    users = []
    for u in pick:
        d = groups[u]
        half = len(d) // 2
        prof, targ = d.iloc[:half], d.iloc[half:]
        users.append(({int(a): float(max(h, 0.1)) for a, h in zip(prof["app_id"], prof["hours_total"])},
                      set(int(a) for a in targ["app_id"])))
    log(f"eligible held-out reviewers {len(ok):,}; sampled {len(users)}")
    popular = [int(kb.appids[i]) for i in np.argsort(-kb.review_count)]
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}

    def key(lib):
        return ",".join(f"{a}:{h:.1f}" for a, h in sorted(lib.items()))

    def ask(lib):
        k = key(lib)
        if k in cache:
            return cache[k]
        lines = "\n".join(f"- {kb.name[a]} ({h:.0f} h)" for a, h in sorted(lib.items(), key=lambda x: -x[1]))
        t0 = time.time()
        try:
            out = chat_json(llm, SYS, f"Games I played:\n{lines}", "vs_llm")
            names = [n for n in out.get("games", []) if isinstance(n, str)][:K]
        except Exception as e:
            names, err = [], str(e)[:100]
        else:
            err = None
        r = {"names": names, "sec": round(time.time() - t0, 1), "err": err}
        cache[k] = r
        return r

    with ThreadPoolExecutor(8) as ex:
        answers = []
        for i, a in enumerate(ex.map(lambda x: ask(x[0]), users)):
            answers.append(a)
            if (i + 1) % 25 == 0:
                log(f"llm answers {i + 1}/{len(users)}")
                CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")

    # resolve names: alias table, then LLM normaliser for the rest (cached), then alias table again
    norm = cache.setdefault("__norm__", {})
    first = {}
    rest = []
    for a in answers:
        for n in a["names"]:
            if n in first:
                continue
            m = rec.resolver.resolve(n)
            first[n] = m.appid
            if m.appid is None and n not in norm:
                rest.append(n)
    rest = list(dict.fromkeys(rest))
    for i in range(0, len(rest), 60):
        batch = rest[i:i + 60]
        try:
            mp = chat_json(llm, NORM_SYS, json.dumps(batch, ensure_ascii=False), "normalise")
        except Exception:
            mp = {}
        for n in batch:
            norm[n] = mp.get(n) if isinstance(mp, dict) else None
    CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")

    def resolve(n):
        if first.get(n) is not None:
            return first[n]
        alt = norm.get(n)
        return rec.resolver.resolve(alt).appid if alt else None

    rows = []
    users_targ = {}
    for idx,((lib, targ), a) in enumerate(zip(users, answers)):
        sids = []
        try:
            spec = SessionSpec(members=[Member(library=Library(owned=lib))])
            res = rec.recommend(spec)
            sids = ([c["appid"] for c in res.picks] + [b["appid"] for b in res.backups])[:K]
        except Exception as e:
            log("system failed", idx, e)
        lids, unres, inlib = [], [], 0
        for n in a["names"]:
            ap = resolve(n)
            if ap is None:
                unres.append(n)
            elif ap in lib:
                inlib += 1
            elif ap not in lids:
                lids.append(ap)
        pids = [x for x in popular if x not in lib][:K]
        r = {"library": len(lib), "hidden": len(targ), "llm_names": len(a["names"]), "llm_unresolved": unres,
             "llm_repeats_library": inlib, "llm_err": a.get("err"), "llm_sec": a.get("sec")}
        for name, ids in (("system", sids), ("llm", lids), ("popular", pids)):
            hits = [x for x in ids if x in targ]
            r[name] = {"n": len(ids), "hits": len(hits), "recall": len(hits) / len(targ), "ids": ids,
                       "hit_titles": [kb.name[x] for x in hits]}
        r["overlap"] = len(set(sids) & set(lids))
        rows.append(r)
        users_targ[id(r)] = targ
    ok_rows = [r for r in rows if not r["llm_err"] and r["system"]["n"]]
    log(f"users with both answers: {len(ok_rows)}/{len(rows)}")

    summ = {}
    for m in ("system", "llm", "popular"):
        rc = np.array([r[m]["recall"] for r in ok_rows])
        summ[m] = {"recall": float(rc.mean()), "any_hit": int(sum(r[m]["hits"] > 0 for r in ok_rows)),
                   "hits": int(sum(r[m]["hits"] for r in ok_rows)), "avg_n": float(np.mean([r[m]["n"] for r in ok_rows]))}
    d_sl = [r["system"]["recall"] - r["llm"]["recall"] for r in ok_rows]
    d_sp = [r["system"]["recall"] - r["popular"]["recall"] for r in ok_rows]
    d_lp = [r["llm"]["recall"] - r["popular"]["recall"] for r in ok_rows]
    summ["diff"] = {"system-llm": [float(np.mean(d_sl)), *ci(d_sl)], "system-popular": [float(np.mean(d_sp)), *ci(d_sp)],
                    "llm-popular": [float(np.mean(d_lp)), *ci(d_lp)]}
    win = sum(x > 0 for x in d_sl); lose = sum(x < 0 for x in d_sl)
    summ["per_user"] = {"system_better": win, "llm_better": lose, "tie": len(d_sl) - win - lose}
    allnames = sum(r["llm_names"] for r in ok_rows)
    unr = [n for r in ok_rows for n in r["llm_unresolved"]]
    summ["llm_names"] = {"total": allnames, "unresolved": len(unr),
                         "repeats_library": int(sum(r["llm_repeats_library"] for r in ok_rows))}
    summ["overlap_mean"] = float(np.mean([r["overlap"] for r in ok_rows]))
    # long tail: hits outside the 100 most-reviewed core games
    top100 = set(popular[:100])
    for m in ("system", "llm", "popular"):
        summ[m]["recs_in_top100"] = float(np.mean([sum(x in top100 for x in r[m]["ids"]) for r in ok_rows]))
        hit_ids = [x for r in ok_rows for x in r[m]["ids"] if x in users_targ[id(r)]]
        summ[m]["hits_outside_top100"] = int(sum(x not in top100 for x in hit_ids))
    print(json.dumps(summ, ensure_ascii=False, indent=1))
    from collections import Counter
    print("unresolved examples:", Counter(unr).most_common(25))
    out = C.DER / "eval_vs_llm.json"
    out.write_text(json.dumps({"date": time.strftime("%Y-%m-%d"), "seed": seed, "n": n_users, "summary": summ,
                               "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    log("saved", out)


if __name__ == "__main__":
    main()
