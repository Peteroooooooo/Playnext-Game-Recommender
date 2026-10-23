"""Slim co-like table for the web service (design 10.16): each core game's top config.NEIGHBORS_K co-like (EASE)
neighbours, instead of the dense 7,412 x 7,412 EASE matrix (210 MB). scripts/eval_slim.py: K = 200 changes held-out
Recall@20 by less than +-0.005 (the service fills co-like with 0 outside the neighbours).
The description-similarity neighbours this file used to hold were dropped with that channel (design 10.18).

Input: data/derived/ease_reviews100m.npz (offline only from here on).
Writes config.NEIGHBORS: rows in games.parquet order; ease_idx (int16 core row), ease_val (float16, descending),
ease_has (bool), appids.
Rerun after build_processed.py or build_review_tables.py.
Usage: uv run python scripts/build_neighbors.py
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from playnext import config as C  # noqa: E402
from playnext.kb import KB  # noqa: E402


def top_rows(M, k):
    part = np.argpartition(-M, k, axis=1)[:, :k]
    val = np.take_along_axis(M, part, 1)
    order = np.argsort(-val, axis=1, kind="stable")
    return np.take_along_axis(part, order, 1), np.take_along_axis(val, order, 1)


def main():
    kb = KB()
    k = C.NEIGHBORS_K
    assert kb.n < 2**15, "row indices are stored as int16"
    B = kb.ease_core()
    ease_has = kb._ease[2] >= 0
    ease_idx, ease_val = top_rows(B, k)
    del B
    np.savez_compressed(C.NEIGHBORS, appids=kb.appids, ease_idx=ease_idx.astype(np.int16),
                        ease_val=ease_val.astype(np.float16), ease_has=ease_has)
    print(f"wrote {C.NEIGHBORS.relative_to(C.ROOT)}: {kb.n:,} games x {k} neighbours, "
          f"{C.NEIGHBORS.stat().st_size / 2**20:.1f} MB")


if __name__ == "__main__":
    main()
