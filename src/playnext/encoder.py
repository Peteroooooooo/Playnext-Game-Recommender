"""Query encoder for the description channel (design 5.2 model point 3): Qwen3-Embedding-4B, same model and
instruction as the offline game vectors. Loaded on first use (about 8 GB fp16 on the GPU)."""
import threading

import numpy as np

from . import config as C


class Encoder:
    def __init__(self, model_path=None):
        self.path = str(model_path or C.EMB_MODEL)
        self.model = None
        self.lock = threading.Lock()
        self.cache = {}

    def _load(self):
        import torch
        from sentence_transformers import SentenceTransformer
        kw = {"torch_dtype": torch.float16} if torch.cuda.is_available() else {}
        self.model = SentenceTransformer(self.path, model_kwargs=kw, tokenizer_kwargs={"padding_side": "left"})
        self.model.max_seq_length = 1024   # as scripts/build_desc_embeddings.py

    def doc(self, text):
        """A game description as a document vector (no query instruction), comparable with the offline vectors."""
        if not text:
            return None
        with self.lock:
            if self.model is None:
                self._load()
            return self.model.encode([text], normalize_embeddings=True)[0].astype(np.float32)

    def __call__(self, text):
        if not text:
            return None
        if text in self.cache:
            return self.cache[text]
        with self.lock:
            if self.model is None:
                self._load()
            v = self.model.encode([text], prompt=C.QUERY_PROMPT, normalize_embeddings=True)[0].astype(np.float32)
        self.cache[text] = v
        return v
