"""Simulate the four ways in (seed questionnaire, free text via the LLM, Steam library, library + free text) with
the real system (src/playnext, current config), plus a private library, and record what each step produced into
.cache/simulate_inputs.json, which docs/data_overview.html quotes.

What is simulated rather than real: the Steam library is made up (no SteamID is queried; GetOwnedGames is mocked
with the same JSON shape and parsed by library.parse_owned); prices come from the daily snapshot, not a live
query. Everything else (rules, scores, rerank, ranking, cards, LLM reasons) is the production code path.
Usage: uv run python scripts/simulate_inputs.py [--no-llm]
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from playnext import config as C  # noqa: E402
from playnext.cards import write_reasons  # noqa: E402
from playnext.library import parse_owned  # noqa: E402
from playnext.pipeline import Recommender  # noqa: E402
from playnext.spec import Member, SessionSpec  # noqa: E402

OUT = C.CACHE / "simulate_inputs.json"
QUESTIONNAIRE = {"seeds": [1145360, 367520],   # Hades, Hollow Knight
                 "language": "schinese", "avoid": ["Horror", "Psychological Horror", "Survival Horror"]}
SENTENCE = "我以前沉迷《文明6》和《星露谷物语》，今晚想找类似的轻松游戏，60 块以内，最好正在打折"
COMBO_SENTENCE = "想再找几款像《Hades》这样的，别太难，100 块以内"
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


def summary(rec, res, extra=None):
    kb = rec.kb
    pick = lambda c: {k: c.get(k) for k in ("appid", "name", "name_en", "relevance", "like", "diff", "colike", "lineage",
                                            "lineage_path", "rating", "price", "library", "rank_step", "reason",
                                            "reason_source", "same_series_folded")}
    return {**(extra or {}), "understood": res.understood, "rules": res.rules, "notes": res.notes,
            "timings": res.timings, "picks": [pick(c) for c in res.picks],
            "backups": res.backups[:6], "unknown": res.unknown, "failed": res.failed[:5],
            "anchors_library": None}


def main(use_llm=True):
    llm = encoder = None
    if use_llm:
        from playnext.encoder import Encoder
        from playnext.llm import LLM
        llm, encoder = LLM(timeout=120), Encoder()
    try:
        from playnext.db import PathFinder
        paths = PathFinder()
        paths = paths if paths.available() else None
    except Exception:
        paths = None
    rec = Recommender(llm=llm, encoder=encoder, live_prices=False, reasons=False, paths=paths)
    kb = rec.kb
    by_name = {n: int(t) for t, n in kb.tag_en.items()}
    lib = parse_owned(MOCK_OWNED)
    out = {"made": time.strftime("%Y-%m-%d %H:%M"), "weights": C.WEIGHTS, "rerank_w": C.RERANK_W,
           "alpha_beta": [C.ALPHA, C.BETA], "llm": use_llm}

    # C: questionnaire, no LLM needed
    q = SessionSpec(members=[Member(language=QUESTIONNAIRE["language"],
                                    avoid_tags=[by_name[n] for n in QUESTIONNAIRE["avoid"]])],
                    seeds=QUESTIONNAIRE["seeds"])
    res = rec.recommend(q)
    write_reasons(res.picks, llm, "")
    out["questionnaire"] = summary(rec, res, {"input": {"seeds": [kb.name[a] for a in QUESTIONNAIRE["seeds"]],
                                                        "language": "简体中文", "avoid": QUESTIONNAIRE["avoid"]}})

    # A / B: library only
    s = SessionSpec(members=[Member(library=lib)])
    res = rec.recommend(s)
    write_reasons(res.picks, llm, "")
    from playnext.scoring import library_anchors
    out["library"] = summary(rec, res, {"input": {"owned": {kb.name.get(a, str(a)): round(h, 1) for a, h in lib.owned.items()}}})
    out["library"]["anchors_library"] = {kb.name[a]: w for a, w in library_anchors(kb, s.members[0]).items()}

    # private library: guided to the questionnaire, not an error
    res = rec.recommend(SessionSpec(members=[Member(library=parse_owned(MOCK_PRIVATE))]))
    out["private"] = {"notes": res.notes, "picks": [c["name"] for c in res.picks]}

    if use_llm:
        # D: one sentence through the LLM
        t0 = time.time()
        p, spec = rec.understand(SENTENCE)
        und = round(time.time() - t0, 1)
        res = rec.recommend(spec)
        write_reasons(res.picks, llm, spec.request_text)
        out["sentence"] = summary(rec, res, {"input": {"text": SENTENCE}, "parsed": p.model_dump(),
                                             "understand_seconds": und})
        # A / B + D: the same library plus a sentence
        t0 = time.time()
        p, spec = rec.understand(COMBO_SENTENCE)
        und = round(time.time() - t0, 1)
        spec.members[0].library = lib
        res = rec.recommend(spec)
        write_reasons(res.picks, llm, spec.request_text)
        out["combo"] = summary(rec, res, {"input": {"text": COMBO_SENTENCE, "library": "同上"}, "parsed": p.model_dump(),
                                          "understand_seconds": und})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    for k in ("questionnaire", "sentence", "library", "combo"):
        if k in out:
            print(k, [c["name"] for c in out[k]["picks"]], out[k]["notes"])
    print("private", out["private"])
    print("wrote", OUT)


if __name__ == "__main__":
    main(use_llm="--no-llm" not in sys.argv)
