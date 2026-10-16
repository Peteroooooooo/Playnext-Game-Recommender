"""Data layer: Beta prior fit, tag categories, player-count platform column."""
import numpy as np
import pandas as pd
import pytest

from playnext import config as C
from playnext.kb import TAG_CATEGORIES, fit_beta_prior, load_tag_categories


def test_fit_beta_prior_recovers_synthetic_prior():
    rng = np.random.default_rng(0)
    theta = rng.beta(6.0, 2.0, 20_000)
    n = rng.integers(5, 200, theta.size)  # few reviews: binomial noise is a large share of the spread
    k = rng.binomial(n, theta)
    a, b = fit_beta_prior(k, n)
    assert a / (a + b) == pytest.approx(0.75, abs=0.01)
    assert a + b == pytest.approx(8.0, rel=0.06)
    # without the noise correction the prior would come out clearly weaker
    p = k / n
    naive = 1 / (p.var(ddof=1) / (p.mean() * (1 - p.mean()))) - 1
    assert naive < 0.9 * (a + b)


def test_fit_beta_prior_skips_games_without_reviews_and_rejects_no_spread():
    a, b = fit_beta_prior([80, 30, 0, 95], [100, 50, 0, 100])
    assert a / (a + b) == pytest.approx(np.mean([0.8, 0.6, 0.95]))
    with pytest.raises(ValueError):
        fit_beta_prior([50, 50, 50], [100, 100, 100])  # identical shares: no spread beyond noise
    with pytest.raises(ValueError):
        fit_beta_prior([5], [10])


def test_config_prior_matches_core_library(kb):
    a, b = fit_beta_prior(kb.pos_reviews, kb.review_count)
    assert (C.ALPHA, C.BETA) == (pytest.approx(a, abs=0.01), pytest.approx(b, abs=0.01)), "refit ALPHA, BETA"


def test_load_tag_categories_falls_back_to_other(tmp_path):
    assert load_tag_categories([1, 2], tmp_path / "missing.parquet") == {1: "other", 2: "other"}
    f = tmp_path / "tc.parquet"
    pd.DataFrame({"tagid": [1, 2], "category": ["gameplay", "nonsense"]}).to_parquet(f, index=False)
    assert load_tag_categories([1, 2, 3], f) == {1: "gameplay", 2: "other", 3: "other"}


def test_kb_tag_categories(kb):
    assert set(kb.tag_cat) == set(kb.tag_en.index) and len(kb.tag_cat) == 446
    assert set(kb.tag_cat.values()) <= set(TAG_CATEGORIES)
    by_name = {kb.tag_en[t].strip(): c for t, c in kb.tag_cat.items()}
    expect = {"gameplay": ["Roguelike", "Deckbuilding", "Base Building"], "theme": ["Fantasy", "Sci-fi", "Zombies"],
              "mood": ["Relaxing", "Cozy", "Dark", "Atmospheric"],
              "other": ["Indie", "Singleplayer", "Great Soundtrack", "Early Access"]}
    for cat, names in expect.items():
        for n in names:
            assert by_name[n] == cat, n


def test_player_count_platform_column(kb):
    p = kb.players
    fields = ["onlinecoopmax", "onlinemax", "offlinecoopmax", "offlinemax"]
    has_count = p[fields].notna().any(axis=1)
    assert set(p["count_platform"].dropna()) == {"pc", "other"}
    assert (p["count_platform"].notna() == has_count).all()
    assert (p.loc[p["count_platform"] == "pc", "igdb_source"] == "pc").all()
