"""Every Steam game by AppID and name (design 6.1 light index, about 190,000 games), to recognise library and seed
games outside the core library. Built by scripts/build_app_index.py; loaded once on first use.

Without data/processed/app_index.parquet every lookup returns None / [] instead of raising.
"""
import threading
from bisect import bisect_left

import pandas as pd

from . import config as C
from .aliases import norm

PATH = C.PROC / "app_index.parquet"
_lock = threading.Lock()
_index = None  # dict with names (appid -> name), exact (norm -> [appid]), keys (sorted norms), key_ids


def _load():
    global _index
    if _index is None:
        with _lock:
            if _index is None:
                try:
                    df = pd.read_parquet(PATH, columns=["appid", "name"])
                except Exception:  # missing or unreadable file: behave as an empty index
                    df = pd.DataFrame({"appid": pd.Series([], dtype="int64"), "name": pd.Series([], dtype=str)})
                ids = df["appid"].astype("int64").tolist()
                names = df["name"].fillna("").astype(str).tolist()
                normed = [norm(n) for n in names]
                exact = {}
                for a, k in zip(ids, normed):
                    if k:
                        exact.setdefault(k, []).append(a)
                order = sorted((k, a) for k, a in zip(normed, ids) if k)
                _index = {"names": dict(zip(ids, names)), "exact": exact,
                          "keys": [k for k, _ in order], "key_ids": [a for _, a in order]}
    return _index


def reload():
    """Drop the cached index; the next call reads the file again."""
    global _index
    with _lock:
        _index = None


def available() -> bool:
    return bool(_load()["names"])


def name_of(appid) -> str | None:
    try:
        n = _load()["names"].get(int(appid))
    except (TypeError, ValueError):
        return None
    return n or None


def search(name, limit=10) -> list[tuple[int, str]]:
    """Games whose normalised name equals `name` (lowest AppID first), then those starting with it (shortest name
    first). Normalisation is aliases.norm: case, width, punctuation and spaces ignored."""
    n = norm(name or "")
    if not n or limit <= 0:
        return []
    ix = _load()
    names = ix["names"]
    hits = sorted(ix["exact"].get(n, []))
    if len(hits) < limit:
        keys, key_ids = ix["keys"], ix["key_ids"]
        lo = bisect_left(keys, n)
        hi = bisect_left(keys, n + "\U0010ffff", lo)
        seen = set(hits)
        pre = [(len(keys[i]), key_ids[i]) for i in range(lo, min(hi, lo + 5000)) if key_ids[i] not in seen]
        hits += [a for _, a in sorted(pre)]
    return [(a, names[a]) for a in hits[:limit]]
