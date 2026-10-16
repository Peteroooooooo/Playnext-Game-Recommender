"""Local dedicated reranker (Qwen3-Reranker). Model tests run only when the model folder exists and CUDA works;
set PLAYNEXT_RERANKER=Qwen3-Reranker-4B to run them on the larger model."""
import os

import numpy as np
import pytest

from conftest import IT_TAKES_TWO, STARDEW
from playnext.local_rerank import MODELS, LocalReranker, game_doc, local_scores
from playnext.rerank import facts, fuse

NAME = os.environ.get("PLAYNEXT_RERANKER", "Qwen3-Reranker-0.6B")
ELDEN_RING, CS2, DOOM_ETERNAL, CUPHEAD = 1245620, 730, 782330, 268910


def _cuda():
    try:
        import torch
        return torch.cuda.is_available()
    except Exception:
        return False


needs_model = pytest.mark.skipif(not (MODELS / NAME / "config.json").exists() or not _cuda(),
                                 reason=f"{NAME} not in .cache/models or no CUDA")


@pytest.fixture(scope="module")
def rr():
    m = LocalReranker(NAME)
    yield m
    m.unload()


def test_game_doc_uses_the_llm_rerank_facts(kb):
    i = kb.pos[STARDEW]
    f, doc = facts(kb, i), game_doc(kb, i)
    assert doc.startswith(f"Name: {f['name']}\n")
    assert ", ".join(f["tags"]) in doc and f["about"] in doc and len(f["about"]) <= 200


@needs_model
def test_scores_are_probabilities_in_input_order(kb, rr):
    docs = [game_doc(kb, kb.pos[a]) for a in (STARDEW, ELDEN_RING, CS2)]
    q = "a cozy farming game I can take slowly"
    p = rr.score(q, docs)
    assert len(p) == 3 and all(0 <= v <= 1 for v in p)
    assert rr.score(q, docs[::-1]) == pytest.approx(p[::-1], abs=1e-2)
    assert rr.score(q, []) == []


@needs_model
def test_shared_prefix_matches_card_loop(kb, rr):
    docs = [game_doc(kb, i) for i in np.argsort(-kb.review_count)[:24]]
    q = "想找轻松的种田游戏，慢慢经营农场，不想打打杀杀；最好能和朋友一起玩，价格别太贵"
    a = np.array(rr.score(q, docs, logit=True, batch_size=8))
    b = np.array(rr.score(q, docs, logit=True, batch_size=8, share_prefix=False))
    assert np.abs(a - b).max() < 0.3


@needs_model
def test_obvious_cases_rank_sensibly(kb, rr):
    farm = [STARDEW, ELDEN_RING, CS2, DOOM_ETERNAL]
    p = rr.score("想找輕鬆的種田遊戲，慢慢經營農場，不想打打殺殺", [game_doc(kb, kb.pos[a]) for a in farm])
    assert p[0] > 0.5 and p[0] > 5 * max(p[1:])
    coop = [IT_TAKES_TWO, ELDEN_RING, CUPHEAD]
    p = rr.score("两个人一起玩、需要互相配合的轻松合作游戏", [game_doc(kb, kb.pos[a]) for a in coop])
    assert p[0] == max(p)


@needs_model
def test_local_scores_plug_into_fuse(kb, rr):
    cand = [kb.pos[a] for a in (STARDEW, ELDEN_RING, CS2)]
    texts = {"me": "a cozy farming game I can take slowly", 0: "fast competitive shooter"}
    scores = local_scores(kb, rr, texts, cand)
    assert set(scores) == {"me", 0} and all(set(s) == set(cand) for s in scores.values())
    assert max(scores["me"], key=scores["me"].get) == kb.pos[STARDEW]
    out = fuse(kb, np.full(kb.n, 0.5, np.float32), scores["me"], w=0.6)
    assert out[kb.pos[STARDEW]] == pytest.approx(0.4 * 0.5 + 0.6, abs=1e-4)   # best candidate gets the full w
    assert np.allclose(out[np.setdiff1d(np.arange(kb.n), cand)], 0.4 * 0.5)
