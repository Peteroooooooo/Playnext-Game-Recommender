"""LLM speed settings (2026-10-22): thinking per call purpose, and the rerank split into parallel batches."""
import json
import threading
import time
from types import SimpleNamespace

import numpy as np

from playnext import config as C
from playnext.llm import LLM
from playnext.rerank import llm_scores


class FakeClient:
    """Stands in for openai.OpenAI: records the keyword arguments of every completion call."""

    def __init__(self):
        self.kwargs = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kw):
        self.kwargs.append(kw)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="{}"))])


def bare_llm():
    llm = LLM.__new__(LLM)          # skip __init__: no .env, no network
    llm.client, llm.model, llm.calls = FakeClient(), "m", []
    return llm


def test_thinking_effort_follows_the_call_purpose(monkeypatch):
    monkeypatch.setattr(C, "THINKING", {"rerank": "none", "understand": "low"})
    llm = bare_llm()
    llm.chat("s", "u", "rerank")
    llm.chat("s", "u", "understand")
    llm.chat("s", "u", "baseline")  # not listed: the model's own default, no parameter sent
    sent = [kw.get("reasoning_effort") for kw in llm.client.kwargs]
    assert sent == ["none", "low", None]
    assert "reasoning_effort" not in llm.client.kwargs[2]


def test_default_thinking_config_turns_off_the_pipeline_steps():
    for purpose in ("understand", "patch", "rerank", "reasons"):
        assert C.THINKING.get(purpose) == "none"


class KeyedLLM:
    """Scores every candidate by its position in the full list (taken from its name); tracks concurrency."""

    def __init__(self, kb, cand):
        self.order = {kb.name[int(kb.appids[i])]: k for k, i in enumerate(cand)}
        self.calls, self.live, self.peak, self.lock = 0, 0, 0, threading.Lock()

    def chat(self, system, user, purpose="", temperature=0):
        with self.lock:
            self.calls += 1
            self.live += 1
            self.peak = max(self.peak, self.live)
        time.sleep(0.05)
        items = json.loads(user.split("Candidates:\n", 1)[1])
        with self.lock:
            self.live -= 1
        return json.dumps({g: self.order[f["name"]] % 11 for g, f in items.items()})


def test_rerank_batches_merge_raw_scores(kb):
    cand = [int(i) for i in np.arange(0, 400, 17)]          # 24 games
    one = llm_scores(kb, KeyedLLM(kb, cand), {"me": "x"}, cand, batches=1)
    fake = KeyedLLM(kb, cand)
    many = llm_scores(kb, fake, {"me": "x"}, cand, batches=4)
    assert fake.calls == 4 and fake.peak > 1                # four calls, run in parallel
    assert set(many["me"]) == set(cand)                     # every candidate scored once
    assert many == one                                      # raw scores merged unchanged


def test_rerank_batches_never_exceed_candidates(kb):
    cand = [0, 1]
    fake = KeyedLLM(kb, cand)
    out = llm_scores(kb, fake, {"me": "x"}, cand, batches=8)
    assert fake.calls == 2 and set(out["me"]) == set(cand)
