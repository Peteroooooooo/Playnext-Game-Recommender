"""Dedicated reranker for the semantic rerank (design 5.5 '精排器选型', section 7 three-way comparison: no rerank /
dedicated reranker / LLM rerank). Qwen3-Reranker is a causal LM that reads one (request, game) pair and answers
"yes" or "no"; the score is P(yes) from those two next-token logits. Prompt format follows the model card exactly.

It sees the same public facts as the LLM rerank (`rerank.facts`: name, top tags, first 200 characters of the
description), so the comparison is fair. Runs locally; nothing leaves the machine. The model loads on first use
(0.6B: about 1.2 GB fp16 on the GPU, 4B: about 8 GB; the 4B does not fit next to Qwen3-Embedding-4B on a 16 GB
card). `local_scores` has the shape of `rerank.llm_scores`, so `rerank.fuse` applies unchanged."""
import threading

from . import config as C
from .kb import KB
from .rerank import facts

MODELS = C.CACHE / "models"

# Fixed by the model card: system turn, user turn layout and the empty think block before the answer token.
PREFIX = ('<|im_start|>system\nJudge whether the Document meets the requirements based on the Query and the Instruct '
          'provided. Note that the answer can only be "yes" or "no".<|im_end|>\n<|im_start|>user\n')
SUFFIX = "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"

# Ours (the card asks for a task-specific instruction, written in English even for other-language queries). It
# judges taste only; hard facts (player counts, price, platform, language) are the rules' job.
INSTRUCTION = ("Given a player's request for a Steam game, judge whether this game matches the gameplay, feel, pace, "
               "theme and mood they ask for and avoids what they say they do not want. Ignore player counts, price, "
               "platform and language, which are checked separately")


def format_pair(instruction, query, doc):
    """The card's `format_instruction`."""
    return f"<Instruct>: {instruction}\n<Query>: {query}\n<Document>: {doc}"


def game_doc(kb: KB, i):
    """Document text for row i of the knowledge base, from the same facts the LLM rerank sends."""
    f = facts(kb, i)
    return f"Name: {f['name']}\nTags: {', '.join(f['tags'])}\nAbout: {f['about']}"


class LocalReranker:
    def __init__(self, name="Qwen3-Reranker-0.6B", device="cuda", dtype="float16", max_length=2048):
        """name: folder under .cache/models (or a path). dtype: torch dtype or its name. max_length: tokens per
        pair including the fixed prompt; longer pairs are cut from the end of the document, as in the card."""
        self.path = str(MODELS / name) if (MODELS / name).exists() else str(name)
        self.name = name
        self.device = device
        self.dtype = dtype
        self.max_length = max_length
        self.model = self.tok = None
        self.lock = threading.Lock()

    def _load(self):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        dtype = getattr(torch, self.dtype) if isinstance(self.dtype, str) else self.dtype
        self.tok = AutoTokenizer.from_pretrained(self.path, padding_side="left")
        self.model = AutoModelForCausalLM.from_pretrained(self.path, dtype=dtype).to(self.device).eval()
        self.yes = self.tok.convert_tokens_to_ids("yes")
        self.no = self.tok.convert_tokens_to_ids("no")
        self.prefix_ids = self.tok.encode(PREFIX, add_special_tokens=False)
        self.suffix_ids = self.tok.encode(SUFFIX, add_special_tokens=False)

    def unload(self):
        """Drop the model and return its GPU memory."""
        with self.lock:
            self.model = self.tok = None
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

    def score(self, query: str, docs: list[str], instruction: str | None = None, batch_size=16, logit=False,
              share_prefix=True):
        """P(yes) in 0..1 per document, in input order. logit=True returns the yes-minus-no logit instead (same
        ranking, no saturation at 0 or 1, the sentence-transformers default).

        share_prefix=True runs the tokens every pair shares (system prompt, instruction, query) once and reuses
        their key/value cache for all documents: same tokens and same result as the card's per-pair loop
        (share_prefix=False) up to fp16 rounding, several times faster when the request is long."""
        if not docs:
            return []
        import torch
        with self.lock:
            if self.model is None:
                self._load()
            pairs = [format_pair(instruction or INSTRUCTION, query, d) for d in docs]
            room = self.max_length - len(self.prefix_ids) - len(self.suffix_ids)
            ids = self.tok(pairs, padding=False, truncation="longest_first", return_attention_mask=False,
                           max_length=room)["input_ids"]
            ids = [self.prefix_ids + x + self.suffix_ids for x in ids]
            with torch.inference_mode():
                yn = (self._shared if share_prefix else self._per_pair)(ids, batch_size)   # (n, 2): no, yes
                vals = (yn[:, 1] - yn[:, 0]) if logit else torch.log_softmax(yn, dim=1)[:, 1].exp()
            return vals.tolist()

    def _per_pair(self, ids, batch_size):
        """The card's batched forward: left padding, the answer logits sit at the last position."""
        import torch
        out = torch.empty(len(ids), 2)
        order = sorted(range(len(ids)), key=lambda k: len(ids[k]))   # similar lengths per batch, less padding
        for s in range(0, len(order), batch_size):
            chunk = order[s:s + batch_size]
            batch = self.tok.pad({"input_ids": [ids[k] for k in chunk]}, padding=True, return_tensors="pt")
            batch = {k: v.to(self.model.device) for k, v in batch.items()}
            last = self.model(**batch, logits_to_keep=1).logits[:, -1, :]
            out[chunk] = torch.stack([last[:, self.no], last[:, self.yes]], dim=1).float().cpu()
        return out

    def _shared(self, ids, batch_size):
        """Shared token prefix once, then each document batch on top of a copy of its cache (right padding, the
        answer logits gathered at each row's last real token)."""
        import copy

        import torch
        dev = self.model.device
        base = self.model.model
        head = self.model.lm_head.weight[[self.no, self.yes]]           # only the two answer rows are needed
        P = 0
        while P < min(len(x) for x in ids) - 1 and all(x[P] == ids[0][P] for x in ids):
            P += 1
        cache = base(input_ids=torch.tensor([ids[0][:P]], device=dev), use_cache=True).past_key_values
        out = torch.empty(len(ids), 2)
        order = sorted(range(len(ids)), key=lambda k: len(ids[k]))
        for s in range(0, len(order), batch_size):
            chunk = order[s:s + batch_size]
            tails = [ids[k][P:] for k in chunk]
            B, L = len(chunk), max(len(t) for t in tails)
            inp = torch.full((B, L), self.tok.pad_token_id, dtype=torch.long)
            mask = torch.zeros((B, P + L), dtype=torch.long)
            mask[:, :P] = 1
            for r, t in enumerate(tails):
                inp[r, :len(t)] = torch.tensor(t)
                mask[r, P:P + len(t)] = 1
            c = copy.deepcopy(cache)          # the forward appends to the cache it is given
            c.batch_repeat_interleave(B)
            pos = torch.arange(P, P + L, device=dev).expand(B, L)
            h = base(input_ids=inp.to(dev), attention_mask=mask.to(dev), position_ids=pos, past_key_values=c,
                     use_cache=True).last_hidden_state
            last = h[torch.arange(B, device=dev), torch.tensor([len(t) - 1 for t in tails], device=dev)]
            out[chunk] = (last @ head.T).float().cpu()
            del c, h
        return out


def local_scores(kb: KB, model: LocalReranker, texts: dict, cand, instruction=None, logit=False):
    """Drop-in for `rerank.llm_scores`: texts: target -> words. Returns target -> {row: P(yes)} (or the log-odds
    with logit=True), ready for `rerank.fuse`. Documents are built once and scored once per target."""
    docs = [game_doc(kb, i) for i in cand]
    return {t: dict(zip(cand, model.score(text, docs, instruction, logit=logit))) for t, text in texts.items()}
