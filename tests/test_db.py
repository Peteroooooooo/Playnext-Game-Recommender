import pytest

from conftest import HADES


def _conn():
    try:
        from playnext.db import connect
        return connect()
    except Exception:
        return None


@pytest.fixture(scope="module")
def conn():
    c = _conn()
    if c is None:
        pytest.skip("PostgreSQL not running (docker compose up -d, then scripts/load_postgres.py)")
    with c.cursor() as cur:
        cur.execute("SELECT to_regclass('game')")
        if cur.fetchone()[0] is None:
            pytest.skip("knowledge base not loaded (scripts/load_postgres.py)")
    yield c
    c.close()


def test_counts_match_kb(conn, kb):
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM game")
        assert cur.fetchone()[0] == kb.n
        cur.execute("SELECT count(*) FROM has_mode WHERE status NOT IN ('PASS', 'UNKNOWN')")
        assert cur.fetchone()[0] == 0


def test_lineage_path_same_studio(conn):
    from playnext.db import lineage_paths
    paths = lineage_paths(conn, HADES, 237930)  # Transistor
    assert paths and "Supergiant Games" in paths[0]
