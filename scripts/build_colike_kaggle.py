"""Item-item co-like neighbours from the Kaggle recommendations dataset.

- Keeps positive recommendations of core-library games.
- Holds out 10% of users (user_id % 10 == 0) for offline evaluation; they are
  excluded from the matrix and saved to data/derived/eval_kaggle_test.parquet.
- Similarity = co_count / sqrt(n_i * n_j) (cosine on binary likes), pairs with
  co_count >= MIN_CO only; keeps the TOP_K neighbours per game.
Output: data/derived/colike_kaggle.parquet (app_id, neighbor, sim, co_count)
Usage: python scripts/build_colike_kaggle.py
"""
import json
import zipfile

import numpy as np
import pandas as pd
import scipy.sparse as sp

from check_keys import ROOT

ZIP = ROOT / "data" / "raw" / "kaggle_recs" / "archive.zip"
CORE = ROOT / "data" / "core_candidates.json"
DER = ROOT / "data" / "derived"
TOP_K, MIN_CO = 200, 5


def load_positive(core_ids):
    parts = []
    with zipfile.ZipFile(ZIP) as z, z.open("recommendations.csv") as f:
        for ch in pd.read_csv(f, usecols=["app_id", "user_id", "is_recommended", "date", "hours"],
                              dtype={"app_id": "int32", "user_id": "int32", "hours": "float32"},
                              parse_dates=["date"], chunksize=5_000_000):
            ch = ch[ch["is_recommended"] & ch["app_id"].isin(core_ids)]
            parts.append(ch.drop(columns="is_recommended"))
    return pd.concat(parts, ignore_index=True)


def main():
    core_ids = [g["appid"] for g in json.loads(CORE.read_text(encoding="utf-8"))]
    df = load_positive(set(core_ids))
    test_mask = df["user_id"] % 10 == 0
    df[test_mask].to_parquet(DER / "eval_kaggle_test.parquet", index=False)
    train = df[~test_mask]
    print(f"positive recs on core games: {len(df):,}; train {len(train):,}; test {test_mask.sum():,} "
          f"({df.loc[test_mask, 'user_id'].nunique():,} users)", flush=True)

    items = np.array(sorted(train["app_id"].unique()))
    col = np.searchsorted(items, train["app_id"].to_numpy())
    users, row = np.unique(train["user_id"].to_numpy(), return_inverse=True)
    X = sp.csr_matrix((np.ones(len(train), dtype=np.float32), (row, col)), shape=(len(users), len(items)))
    X.data[:] = 1.0  # duplicates collapse to binary
    n = np.asarray(X.sum(axis=0)).ravel()
    C = (X.T @ X).toarray()
    np.fill_diagonal(C, 0)
    sim = C / np.sqrt(np.outer(n, n))
    sim[C < MIN_CO] = 0

    rows = []
    for i in range(len(items)):
        nz = np.flatnonzero(sim[i])
        if not len(nz):
            continue
        top = nz[np.argsort(-sim[i, nz])[:TOP_K]]
        rows.append(pd.DataFrame({"app_id": items[i], "neighbor": items[top],
                                  "sim": sim[i, top].astype("float32"), "co_count": C[i, top].astype("int32")}))
    out = pd.concat(rows, ignore_index=True)
    out.to_parquet(DER / "colike_kaggle.parquet", index=False)
    per = out.groupby("app_id").size()
    print(f"items in matrix {len(items):,}; items with >=1 neighbour {len(per):,}; "
          f">=20 neighbours {(per >= 20).sum():,}; >=200 {(per >= 200).sum():,}")


if __name__ == "__main__":
    main()
