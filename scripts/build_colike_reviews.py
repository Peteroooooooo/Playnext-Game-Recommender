"""Item-item co-like neighbours from recent Steam reviews (data/raw/appreviews/).

Same similarity as build_colike_kaggle.py: co_count / sqrt(n_i * n_j) on
binary likes, pairs with co_count >= MIN_CO, TOP_K neighbours per game.
Output: data/derived/colike_reviews.parquet (app_id, neighbor, sim, co_count)
Usage: python scripts/build_colike_reviews.py
"""
import json

import numpy as np
import pandas as pd
import scipy.sparse as sp

from check_keys import ROOT

RAW = ROOT / "data" / "raw" / "appreviews"
OUT = ROOT / "data" / "derived" / "colike_reviews.parquet"
TOP_K, MIN_CO = 200, 3


def main():
    apps, users = [], []
    for f in RAW.glob("*.json"):
        a = int(f.stem)
        for h, _ in json.loads(f.read_text(encoding="utf-8")):
            apps.append(a)
            users.append(h)
    df = pd.DataFrame({"app_id": apps, "user": users}).drop_duplicates()
    items = np.array(sorted(df["app_id"].unique()))
    col = np.searchsorted(items, df["app_id"].to_numpy())
    _, row = np.unique(df["user"].to_numpy(), return_inverse=True)
    X = sp.csr_matrix((np.ones(len(df), dtype=np.float32), (row, col)), shape=(row.max() + 1, len(items)))
    n = np.asarray(X.sum(axis=0)).ravel()
    C = (X.T @ X).toarray()
    np.fill_diagonal(C, 0)
    sim = C / np.sqrt(np.outer(n, n))
    sim[C < MIN_CO] = 0
    rows = []
    for i in range(len(items)):
        nz = np.flatnonzero(sim[i])
        if len(nz):
            top = nz[np.argsort(-sim[i, nz])[:TOP_K]]
            rows.append(pd.DataFrame({"app_id": items[i], "neighbor": items[top],
                                      "sim": sim[i, top].astype("float32"), "co_count": C[i, top].astype("int32")}))
    out = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=["app_id", "neighbor", "sim", "co_count"])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(OUT, index=False)
    print(f"games {len(items):,}; reviews {len(df):,}; games with >=1 neighbour {out['app_id'].nunique():,}")


if __name__ == "__main__":
    main()
