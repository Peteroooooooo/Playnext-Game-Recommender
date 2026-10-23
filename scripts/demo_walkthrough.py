"""End-to-end walkthrough of Steps 1-4 for one example user, on the real knowledge base.

Example user (made up): a Steam library + one sentence. Shows every intermediate number:
anchor weights (playtime percentile), each channel's raw similarity and the anchor it came from,
min-max normalisation, the weighted fusion, then the Step 4 window + quality + MMR pick.
Channel weights and the lineage rule are demo values, not tuned (production: config.WEIGHTS). The description
channel compares the precomputed English vectors from build_desc_embeddings.py; the sentence only reaches the
scores through the feel tags Step 1 picks for it (no text model runs here, design 10.15).
Usage: uv run python scripts/demo_walkthrough.py
"""
import sys

import numpy as np
import pandas as pd

from check_keys import ROOT

sys.path.insert(0, str(ROOT / "src"))
from playnext import config as C  # noqa: E402

LIBRARY = {289070: 300, 413150: 60, 1145360: 80, 1426210: 13}  # appid -> hours: Civ VI, Stardew, Hades, It Takes Two
SENTENCE = "最近有点累，想玩点轻松的"
WEIGHTS = {"tag": 0.30, "desc": 0.25, "colike": 0.30, "lineage": 0.15}
FEEL = {"want": ["Relaxing", "Casual", "Cozy", "Wholesome"],  # what Step 1's LLM would pick for SENTENCE
        "avoid": ["Difficult", "Souls-like", "Horror", "Psychological Horror"]}
FEEL_WEIGHT = float(sys.argv[1]) if len(sys.argv) > 1 else 0.25
DELTA, TOP_SHOW, PICK = 0.10, 10, 5
ALPHA, BETA = C.ALPHA, C.BETA  # smoothed-rating Beta prior fitted on the core library (playnext.config)
PROC = ROOT / "data" / "processed"
DER = ROOT / "data" / "derived"
DESC_EMB = DER / "desc_emb_qwen3_4b.npz"


def anchor_weights(names):
    """Percentile of the user's hours among each game's training reviewers (playtime_reference_100m)."""
    ref = pd.read_parquet(DER / "playtime_reference_100m.parquet").set_index("app_id")
    out = {}
    for a, h in LIBRARY.items():
        q = np.asarray(ref.loc[a, "q"], np.float64)
        pct = float(np.interp(h, q, np.linspace(0, 1, 101)))
        out[a] = pct if h > 0 else 0.0
        print(f"  {names[a]:<28} you {h:>4} h | other players' median {ref.loc[a, 'median_hours']:6.1f} h | "
              f"you played more than {pct:.0%} of them -> weight {out[a]:.2f}")
    return out


def tag_matrix(appids):
    gt = pd.read_parquet(PROC / "game_tags.parquet")
    gt = gt[gt["appid"].isin(appids)]
    df = gt.groupby("tagid")["appid"].nunique()
    idf = np.log(len(appids) / df)
    tags = np.array(sorted(df.index))
    row = {a: i for i, a in enumerate(appids)}
    M = np.zeros((len(appids), len(tags)), np.float32)
    M[gt["appid"].map(row).to_numpy(), np.searchsorted(tags, gt["tagid"].to_numpy())] = \
        (gt["weight"].to_numpy() * idf.reindex(gt["tagid"]).to_numpy())
    M /= np.linalg.norm(M, axis=1, keepdims=True) + 1e-9
    return M


def desc_vectors(appids):
    """English vectors from build_desc_embeddings.py, in the order of appids."""
    z = np.load(DESC_EMB)
    row = {a: i for i, a in enumerate(z["appids"])}
    return z["en"][[row[a] for a in appids]].astype(np.float32)


def weighted_max(sim, w):
    """sim: anchors x games. Returns per-game best weighted similarity and which anchor gave it."""
    ws = sim * w[:, None]
    return ws.max(axis=0), ws.argmax(axis=0)


def main():
    games = pd.read_parquet(PROC / "games.parquet").set_index("appid")
    names = games["name"]
    desc = pd.read_parquet(PROC / "descriptions.parquet")
    desc = desc[desc["lang"] == "en"].set_index("appid")
    text = (desc["short"].fillna("") + "\n" + desc["full"].fillna("")).str.strip()
    appids = np.array(sorted(a for a in games.index if len(text.get(a, "")) > 0))

    print("STEP 1  what we know about the user")
    print(f"  sentence: {SENTENCE!r}  -> preference_text; no budget, no player count, anchor = library profile")
    print("  library from Steam (GetOwnedGames), anchor weights:")
    w = anchor_weights(names)
    anchors = [a for a in LIBRARY if w[a] > 0]
    wv = np.array([w[a] for a in anchors], np.float32)

    cand = np.array([a for a in appids if a not in LIBRARY])
    print(f"\nSTEP 2  hard filter: {len(appids):,} games with a description -> drop the 4 owned -> {len(cand):,} candidates")

    idx = {a: i for i, a in enumerate(appids)}
    ai, ci = [idx[a] for a in anchors], [idx[a] for a in cand]

    T = tag_matrix(appids)
    tag_raw, tag_hit = weighted_max(T[ai] @ T[ci].T, wv)

    E = desc_vectors(appids)
    d_anchor, d_hit = weighted_max(E[ai] @ E[ci].T, wv)

    z = np.load(DER / "ease_reviews100m.npz")
    col = {a: j for j, a in enumerate(z["items"])}
    cj = np.array([col.get(a, -1) for a in cand])
    contrib = np.zeros((len(anchors), len(cand)), np.float32)
    for k, a in enumerate(anchors):
        if a in col:
            contrib[k, cj >= 0] = wv[k] * z["B"][col[a], cj[cj >= 0]]
    co_raw, co_hit = contrib.sum(axis=0), contrib.argmax(axis=0)  # EASE: anchors add up (design 5.5)

    comp = pd.read_parquet(PROC / "companies.parquet")
    dev = comp[comp["developer"]]
    ser = pd.read_parquet(PROC / "series.parquet")
    ser["key"] = list(zip(ser["kind"], ser["series_id"]))  # collection and franchise ids overlap in IGDB
    sim = pd.read_parquet(PROC / "similar.parquet")
    same_dev = set(dev[dev["company_id"].isin(dev[dev["appid"].isin(anchors)]["company_id"])]["appid"])
    same_ser = set(ser[ser["key"].isin(ser[ser["appid"].isin(anchors)]["key"])]["appid"])
    igdb_sim = set(sim[sim["appid"].isin(anchors)]["similar_appid"])
    lineage = np.array([1.0 if (a in same_dev or a in same_ser or a in igdb_sim) else 0.0 for a in cand], np.float32)

    mm = lambda x: (x - x.min()) / (x.max() - x.min() + 1e-9)
    parts = {"tag": mm(tag_raw), "desc": mm(d_anchor), "colike": mm(co_raw), "lineage": lineage}
    score = sum(WEIGHTS[k] * v for k, v in parts.items())

    an = [names[a] for a in anchors]
    print("\nSTEP 3  four channels, each candidate vs each anchor: tag and description keep the best weighted anchor, "
          "co-like (EASE) adds the anchors up; the anchor shown is the largest contributor")
    print(f"  weights: {WEIGHTS}  (demo values, to be tuned offline)")
    order = np.argsort(-score)
    rows = []
    for j in order[:TOP_SHOW]:
        a = cand[j]
        rows.append({"game": names[a][:30],
                     "tag": f"{tag_raw[j]:.2f} ({an[tag_hit[j]][:10]})",
                     "desc": f"{d_anchor[j]:.2f} ({an[d_hit[j]][:10]})",
                     "colike(EASE)": f"{co_raw[j]:.4f} ({an[co_hit[j]][:10]})",
                     "lineage": int(lineage[j]),
                     "norm t/d/c/l": "/".join(f"{parts[k][j]:.2f}" for k in WEIGHTS),
                     "fit": f"{score[j]:.3f}"})
    with pd.option_context("display.width", 250, "display.max_columns", 20):
        print(pd.DataFrame(rows).to_string(index=False))

    j = order[0]
    a = cand[j]
    print(f"\n  how #{1} {names[a]} got its tag score, anchor by anchor:")
    for k, b in enumerate(anchors):
        s = float(T[idx[b]] @ T[idx[a]])
        print(f"    vs {names[b]:<28} similarity {s:.2f} x weight {wv[k]:.2f} = {s * wv[k]:.2f}")
    print(f"    keep the largest -> {tag_raw[j]:.2f}")
    print(f"  fit = " + " + ".join(f"{WEIGHTS[k]} x {parts[k][j]:.2f}" for k in WEIGHTS) + f" = {score[j]:.3f}")

    tags = pd.read_parquet(PROC / "tags.parquet").set_index("name_en")
    gt = pd.read_parquet(PROC / "game_tags.parquet")
    gt = gt[gt["appid"].isin(cand)]

    def tag_mean(names_en):
        ids = tags.loc[names_en, "tagid"].tolist()
        w = gt[gt["tagid"].isin(ids)].groupby("appid")["weight"].sum() / len(ids)
        return w.reindex(cand).fillna(0).to_numpy(np.float32)

    feel = tag_mean(FEEL["want"]) - tag_mean(FEEL["avoid"])
    zh = tags["name_zh"]
    print(f"\nSTEP 3b feel channel: want {[zh[t] for t in FEEL['want']]}, avoid {[zh[t] for t in FEEL['avoid']]}")
    print(f"  fit = {1 - FEEL_WEIGHT:.2f} x (four channels above) + {FEEL_WEIGHT} x feel (normalised)")
    before = order[:TOP_SHOW]
    score = (1 - FEEL_WEIGHT) * score + FEEL_WEIGHT * mm(feel)
    order = np.argsort(-score)
    print(f"  {'rank':<5}{'before (no feel)':<34}{'after (with feel)':<34}{'feel raw':>8}")
    for k in range(TOP_SHOW):
        b, a = cand[before[k]], cand[order[k]]
        print(f"  {k + 1:<5}{names[b][:32]:<34}{names[a][:32]:<34}{feel[order[k]]:>8.2f}")

    print(f"\nSTEP 4  window delta={DELTA} on normalised fit, then 0.625 x fit + 0.375 x quality, then MMR on tag similarity")
    rel = mm(score)
    pos = games["review_count"].reindex(cand).fillna(0).to_numpy() * games["pct_positive"].reindex(cand).fillna(0).to_numpy() / 100
    tot = games["review_count"].reindex(cand).fillna(0).to_numpy()
    quality = (pos + ALPHA) / (tot + ALPHA + BETA)
    base = 0.625 * rel + 0.375 * quality
    chosen, remaining = [], set(np.argsort(-rel)[:200].tolist())
    while len(chosen) < PICK:
        top = max(rel[r] for r in remaining)
        window = [r for r in remaining if rel[r] >= top - DELTA]
        def mmr(r):
            red = max((float(T[idx[cand[r]]] @ T[idx[cand[c]]]) for c in chosen), default=0.0)
            return 0.65 * base[r] - 0.35 * red
        best = max(window, key=mmr)
        chosen.append(best)
        remaining.remove(best)
        print(f"  pick {len(chosen)}: {names[cand[best]]:<32} fit {rel[best]:.2f}  quality {quality[best]:.2f}  "
              f"(window had {len(window)} games)")


if __name__ == "__main__":
    main()
