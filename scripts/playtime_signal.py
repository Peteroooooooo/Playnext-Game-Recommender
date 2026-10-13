"""Does relative playtime (vs other players of the same game) predict liking better than absolute hours?

For every training reviewer (user_hash % 10 != 0) who has both liked and disliked games, rank that reviewer's
reviewed games by a playtime signal and measure how well it separates liked from disliked ones (within-user AUC):
  hrs    absolute hours (playtime_forever)
  pct    percentile of those hours among the game's other training reviewers (what the library profile uses)
  ratio  hours / the game's median hours
  blend  0.5 x pct + 0.5 x the reviewer's own percentile of hours across their reviewed games
Reads the merged review table (build_reviews_merged.py); IDs there are already salted hashes. Only aggregates are printed.
Usage: uv run python scripts/playtime_signal.py   (about 10 minutes, ~12 GB RAM)
"""
import time

import numpy as np
import pandas as pd

from build_review_tables import load

MIN_PLAYERS = 50


def main():
    t0 = time.time()
    df = load(["user_hash", "appid", "voted_up", "playtime_forever"])
    keep = (df["user_hash"].to_numpy() % 10 != 0) & (df["playtime_forever"].to_numpy() > 0)
    df = df[keep].reset_index(drop=True)
    del keep
    df["hrs"] = (df.pop("playtime_forever").to_numpy() / 60).astype(np.float32)
    df["voted_up"] = df["voted_up"].astype(np.int8)
    size = df.groupby("appid")["hrs"].transform("size")
    df = df[size.to_numpy() >= MIN_PLAYERS].reset_index(drop=True)
    del size
    print(f"training reviews with playtime > 0 on games with >= {MIN_PLAYERS} such reviewers: {len(df):,} "
          f"on {df['appid'].nunique():,} games, positive share {df['voted_up'].mean():.3f} ({time.time() - t0:.0f}s)", flush=True)

    g = df.groupby("appid")["hrs"]
    df["pct"] = g.rank(pct=True).astype(np.float32)
    df["ratio"] = (df["hrs"] / np.maximum(g.transform("median"), 0.1)).astype(np.float32)
    del g
    names = {289070: "Civ VI", 413150: "Stardew", 1145360: "Hades", 1426210: "It Takes Two", 1888930: "TLOU Part I",
             292030: "Witcher 3", 1091500: "Cyberpunk", 588650: "Dead Cells"}
    sub = df[df["appid"].isin(names)]
    for a, s in sub.groupby("appid"):
        print(f"{names[a]}: median hours all reviewers {s['hrs'].median():.1f}, positive reviewers "
              f"{s.loc[s['voted_up'] == 1, 'hrs'].median():.1f}, n={len(s):,}")
    del sub

    u = df.groupby("user_hash")["voted_up"].agg(["size", "sum"])
    mixed = u.index[(u["sum"] > 0) & (u["sum"] < u["size"])]
    del u
    df = df[df["user_hash"].isin(mixed)].reset_index(drop=True)
    df["u"] = pd.factorize(df.pop("user_hash"))[0]
    print(f"training reviewers with both liked and disliked games: {len(mixed):,}; their reviews {len(df):,} "
          f"({time.time() - t0:.0f}s)", flush=True)
    del mixed

    df["upct"] = df.groupby("u")["hrs"].rank(pct=True).astype(np.float32)
    df["blend"] = 0.5 * df["pct"] + 0.5 * df.pop("upct")
    p = df.groupby("u")["voted_up"].sum().to_numpy(np.float64)
    n = df.groupby("u")["voted_up"].size().to_numpy(np.float64) - p
    res = {}
    for s in ["hrs", "pct", "ratio", "blend"]:
        r = df.groupby("u")[s].rank(method="average")
        sr = (r * df["voted_up"]).groupby(df["u"]).sum().to_numpy()
        auc = (sr - p * (p + 1) / 2) / (p * n)
        res[s] = auc
        print(f"within-user AUC [{s}]: mean {auc.mean():.4f}  pairs-weighted {np.average(auc, weights=p * n):.4f}", flush=True)
    rng = np.random.default_rng(0)
    for a, b in [("pct", "hrs"), ("blend", "pct")]:
        d = res[a] - res[b]
        boot = [d[rng.integers(0, len(d), len(d))].mean() for _ in range(200)]
        print(f"{a} - {b} mean diff {d.mean():.4f}, 95% CI [{np.percentile(boot, 2.5):.4f}, {np.percentile(boot, 97.5):.4f}]")
    print(f"done {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
