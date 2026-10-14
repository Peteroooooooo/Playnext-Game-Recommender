"""Encode every core game's store description in English and Simplified Chinese (design 5.5 description channel).

Text = short description + full description (BBCode already cleaned by build_processed). Model Qwen3-Embedding-4B
from .cache/models, fp16, documents encoded without an instruction (queries get one, see simulate_inputs.py).
Writes data/derived/desc_emb_qwen3_4b.npz: appids (same order as games.parquet), en, zh (float16, L2-normalised),
has_en, has_zh, max_tokens.
Vectors are cached per (appid, text hash) in .cache/desc_emb_cache_<lang>_<max_tokens>.npz, so a rerun after the
game list changes only encodes new or changed texts, and an interrupted run resumes.
Usage: uv run python scripts/build_desc_embeddings.py [max_tokens]
"""
import hashlib
import sys
import time

import numpy as np
import pandas as pd

from check_keys import ROOT

MODEL = ROOT / ".cache" / "models" / "Qwen3-Embedding-4B"
PROC = ROOT / "data" / "processed"
OUT = ROOT / "data" / "derived" / "desc_emb_qwen3_4b.npz"
MAX_TOKENS = int(sys.argv[1]) if len(sys.argv) > 1 else 1024
CHUNK, BATCH, MIN_CHARS, DIM = 400, 8, 20, 2560


def text_hash(t):
    return hashlib.blake2b(t.encode("utf-8"), digest_size=8).hexdigest()


def load_cache(path):
    if not path.exists():
        return {}
    z = np.load(path)
    return {(int(a), str(h)): v for a, h, v in zip(z["appids"], z["hashes"], z["vecs"])}


def save_cache(path, cache):
    keys = list(cache)
    np.savez(path, appids=np.array([k[0] for k in keys], np.int64), hashes=np.array([k[1] for k in keys]),
             vecs=np.stack([cache[k] for k in keys]) if keys else np.zeros((0, DIM), np.float16))


def main():
    appids = pd.read_parquet(PROC / "games.parquet", columns=["appid"])["appid"].to_numpy()
    d = pd.read_parquet(PROC / "descriptions.parquet")
    d["text"] = (d["short"].fillna("") + "\n" + d["full"].fillna("")).str.strip()
    texts = {lang: d[d["lang"] == lang].set_index("appid")["text"].reindex(appids).fillna("") for lang in ("en", "zh")}

    model = None
    out = {}
    for lang, s in texts.items():
        path = ROOT / ".cache" / f"desc_emb_cache_{lang}_{MAX_TOKENS}.npz"
        cache = load_cache(path)
        keys = [(int(a), text_hash(t)) for a, t in zip(appids, s)]
        has = (s.str.len() >= MIN_CHARS).to_numpy()
        todo = [i for i in np.where(has)[0] if keys[i] not in cache]
        print(f"{lang}: {has.sum():,} texts, {len(todo):,} to encode ({len(cache):,} cached)", flush=True)
        if todo and model is None:
            import torch
            from sentence_transformers import SentenceTransformer
            model = SentenceTransformer(str(MODEL), model_kwargs={"torch_dtype": torch.float16},
                                        tokenizer_kwargs={"padding_side": "left"})
            model.max_seq_length = MAX_TOKENS
        t0 = time.time()
        for c in range(0, len(todo), CHUNK):
            sub = todo[c:c + CHUNK]
            vec = model.encode(s.iloc[sub].tolist(), batch_size=BATCH, normalize_embeddings=True).astype(np.float16)
            cache.update({keys[i]: v for i, v in zip(sub, vec)})
            save_cache(path, cache)
            print(f"  {lang} {c + len(sub):,}/{len(todo):,}  {time.time() - t0:.0f}s", flush=True)
        emb = np.zeros((len(appids), DIM), np.float16)
        for i in np.where(has)[0]:
            emb[i] = cache[keys[i]]
        out[lang], out["has_" + lang] = emb, has
    np.savez(OUT, appids=appids, max_tokens=MAX_TOKENS, **out)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
