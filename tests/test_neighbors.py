"""The service's top-K co-like neighbour table against the dense matrix it was cut from (design 10.16)."""
import numpy as np
import pytest

from conftest import CIV6, HADES
from playnext import config as C
from playnext.kb import DenseKB
from playnext.scoring import Taste, channel_scores

HADES_II = 1145350


@pytest.fixture(scope="module")
def dense():
    if not (C.DER / "ease_reviews100m.npz").exists():
        pytest.skip("dense matrices not present (server install)")
    return DenseKB()


def test_ease_rows_keep_the_top_neighbours(kb, dense):
    a, b = kb.ease_rows([HADES, CIV6]), dense.ease_rows([HADES, CIV6])
    for r in range(2):
        top = np.argsort(-b[r])[:C.NEIGHBORS_K]
        assert np.allclose(a[r, top], b[r, top], rtol=2e-3, atol=1e-6)
        assert (np.delete(a[r], top) == 0).all()
        assert a[r].argmax() == b[r].argmax()
    assert (kb.ease_has == dense.ease_has).all()
    assert (kb.ease_rows([10**9]) == 0).all()


def test_no_description_channel(kb):
    # design 10.18: the description-similarity channel and its neighbours were removed from the service
    with np.load(C.NEIGHBORS) as z:
        assert set(z.files) == {"appids", "ease_idx", "ease_val", "ease_has"}
    assert not hasattr(kb, "desc_sim") and not hasattr(kb, "E_has") and not hasattr(kb, "E_lang")
    assert "desc" not in C.WEIGHTS and not hasattr(C, "DESC_AGG")


def test_seed_scoring_without_description(kb):
    pool = np.ones(kb.n, bool)
    pool[kb.pos[HADES]] = False
    s = channel_scores(kb, Taste(anchors={HADES: 1.0}), pool)
    assert set(s.parts) == {"tag", "colike", "lineage"} and "desc_hit" not in s.evidence
    assert np.isfinite(s.score).all() and s.score[pool].max() > 0
    assert int(kb.appids[np.argmax(np.where(pool, s.score, -1))]) == HADES_II


def test_colike_pair_and_texts(kb):
    n, rank = kb.colike_pair(HADES, HADES_II)
    assert rank == 1 and n > 1000
    assert kb.colike_pair(HADES, 10**9) is None
    assert "Hades" in kb.descriptions.get((HADES, "en"), "") and (HADES, "en") in kb.descriptions
    assert kb.descriptions.get((10**9, "en"), "x") == "x"
