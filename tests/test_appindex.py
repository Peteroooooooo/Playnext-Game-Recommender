import pytest

from playnext import appindex
from playnext import config as C

needs_index = pytest.mark.skipif(not (C.PROC / "app_index.parquet").exists(),
                                 reason="run scripts/build_app_index.py first")


@pytest.fixture
def real_index(monkeypatch):
    monkeypatch.setattr(appindex, "PATH", C.PROC / "app_index.parquet")
    appindex.reload()
    yield
    appindex.reload()


@needs_index
def test_name_of(real_index):
    assert appindex.available()
    assert appindex.name_of(1426210) == "It Takes Two"
    assert appindex.name_of("413150") == "Stardew Valley"
    assert appindex.name_of(-1) is None
    assert appindex.name_of(None) is None


@needs_index
def test_search_exact_then_prefix(real_index):
    assert appindex.search("it takes two")[0] == (1426210, "It Takes Two")
    assert appindex.search("STARDEW VALLEY")[0][0] == 413150
    hits = appindex.search("stardew", limit=20)
    assert 413150 in [a for a, _ in hits]
    assert all(n.lower().replace(" ", "").startswith("stardew") for _, n in hits)
    assert appindex.search("") == [] and appindex.search("   ") == []
    assert len(appindex.search("the", limit=5)) == 5


@needs_index
def test_index_covers_core_games_on_sale(real_index, kb):
    # GetAppList lists only games still on the store: delisted ones (GTA V Legacy, FIFA 23, ...) are absent,
    # so check the core games that have a snapshot price in either region
    sold = [int(a) for a in kb.appids if any((p := kb.price(int(a), r)) is not None and p["final"] == p["final"]
                                             and p["final"] is not None for r in ("CN", "US"))]
    missing = [a for a in sold if appindex.name_of(a) is None]
    assert len(missing) / len(sold) < 0.01


def test_missing_file_is_safe(monkeypatch, tmp_path):
    monkeypatch.setattr(appindex, "PATH", tmp_path / "nope.parquet")
    appindex.reload()
    try:
        assert not appindex.available()
        assert appindex.name_of(1426210) is None
        assert appindex.search("It Takes Two") == []
    finally:
        appindex.reload()
