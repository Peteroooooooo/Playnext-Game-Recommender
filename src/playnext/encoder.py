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
