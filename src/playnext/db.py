"""PostgreSQL knowledge base (design 6.2): entities and relations as tables, lineage paths by recursive CTE.

The recommender scores from in-memory arrays (kb.py); PostgreSQL holds the same facts with their source and
fetch date, answers path questions ("how is X linked to Y") for the evidence cards at request time (PathFinder),
and keeps the slow-loop feedback and fact-error reports (profiles.py).
Load: uv run python scripts/load_postgres.py   (connection from .env: PGHOST / PGPORT / PGDATABASE / PGUSER / PGPASSWORD)
"""
import io

import pandas as pd

from . import config as C
from .i18n import L, carry
from .pricing import load_env

SCHEMA = """
DROP TABLE IF EXISTS price_snapshot, co_liked, similar_to, has_mode, has_tag, in_series, developed_by, series,
                     studio, tag, game CASCADE;
CREATE TABLE game (appid int PRIMARY KEY, name text NOT NULL, name_zh text, release_year int, review_count int,
                   pct_positive int, is_free bool, windows bool, mac bool, linux bool, deck_compat int, cn_blocked bool,
                   store_region text, igdb_id int, source text DEFAULT 'steam_store', fetched date);
CREATE TABLE studio (company_id int PRIMARY KEY, name text NOT NULL);
CREATE TABLE developed_by (appid int REFERENCES game, company_id int REFERENCES studio, developer bool, publisher bool,
                           source text DEFAULT 'igdb', PRIMARY KEY (appid, company_id));
CREATE TABLE series (kind text, series_id int, name text, PRIMARY KEY (kind, series_id));
CREATE TABLE in_series (appid int REFERENCES game, kind text, series_id int, source text DEFAULT 'igdb',
                        PRIMARY KEY (appid, kind, series_id), FOREIGN KEY (kind, series_id) REFERENCES series);
CREATE TABLE tag (tagid int PRIMARY KEY, name_en text, name_zh text);
CREATE TABLE has_tag (appid int REFERENCES game, tagid int REFERENCES tag, votes int, weight real, is_core bool,
                      source text DEFAULT 'steam_store', PRIMARY KEY (appid, tagid));
CREATE TABLE has_mode (appid int REFERENCES game, mode text, max_players int, max_source text,
                       status text CHECK (status IN ('PASS', 'FAIL', 'UNKNOWN')), PRIMARY KEY (appid, mode));
CREATE TABLE similar_to (appid int REFERENCES game, similar_appid int REFERENCES game, source text DEFAULT 'igdb',
                         PRIMARY KEY (appid, similar_appid));
CREATE TABLE co_liked (appid int REFERENCES game, neighbor int REFERENCES game, sim real, co_count int,
                       source text DEFAULT 'reviews_merged_2026-10-13', PRIMARY KEY (appid, neighbor));
CREATE TABLE price_snapshot (appid int REFERENCES game, region text, currency text, final real, original real,
                             discount_pct int, is_free bool, steam_low real, steam_low_time text,
                             source text DEFAULT 'steam_store+itad', fetched date, PRIMARY KEY (appid, region));
CREATE INDEX ON developed_by (company_id);
CREATE INDEX ON in_series (kind, series_id);
CREATE INDEX ON co_liked (neighbor);
"""

# Edges of the lineage graph: game <-> studio (developer), game <-> series (collection), game -> IGDB similar.
# Paths are found breadth-first up to max_depth hops, never revisiting a node.
PATH_SQL = """
WITH RECURSIVE edges(src, dst, label) AS (
    SELECT 'g' || appid, 's' || company_id, '开发' FROM developed_by WHERE developer
    UNION ALL SELECT 's' || company_id, 'g' || appid, '开发' FROM developed_by WHERE developer
    UNION ALL SELECT 'g' || appid, 'c' || series_id, '系列' FROM in_series WHERE kind = 'collection'
    UNION ALL SELECT 'c' || series_id, 'g' || appid, '系列' FROM in_series WHERE kind = 'collection'
    UNION ALL SELECT 'g' || appid, 'g' || similar_appid, 'IGDB 相似' FROM similar_to
),
walk(node, path, labels, depth) AS (
    SELECT 'g' || %(src)s::text, ARRAY['g' || %(src)s::text], ARRAY[]::text[], 0
    UNION ALL
    SELECT e.dst, w.path || e.dst, w.labels || e.label, w.depth + 1
    FROM walk w JOIN edges e ON e.src = w.node
    WHERE w.depth < %(max_depth)s AND NOT e.dst = ANY(w.path) AND w.node <> 'g' || %(dst)s::text
)
SELECT path, labels FROM walk WHERE node = 'g' || %(dst)s::text ORDER BY depth LIMIT %(limit)s
"""


def connect():
    import psycopg
    env = load_env()
    return psycopg.connect(host=env.get("PGHOST", "127.0.0.1"), port=env.get("PGPORT", "5432"),
                           dbname=env.get("PGDATABASE"), user=env.get("PGUSER"), password=env.get("PGPASSWORD"),
                           connect_timeout=3)


def _copy(cur, table, df, cols):
    buf = io.StringIO()
    df[cols].to_csv(buf, index=False, header=False, na_rep="\\N")
    buf.seek(0)
    with cur.copy(f"COPY {table} ({', '.join(cols)}) FROM STDIN WITH (FORMAT csv, NULL '\\N')") as cp:
        cp.write(buf.read())


def load(kb):
    """Rebuild every table from the processed parquet files and the derived co-like table."""
    from .rules import UNKNOWN, PASS, FAIL, _mode_status
    fetched = pd.Timestamp((C.PROC / "games.parquet").stat().st_mtime, unit="s").strftime("%Y-%m-%d")
    g = kb.games.reset_index()
    g["fetched"] = fetched
    for c in ("release_year", "igdb_id"):
        g[c] = g[c].astype("Int64")
    with connect() as conn, conn.cursor() as cur:
        cur.execute(SCHEMA)
        _copy(cur, "game", g, ["appid", "name", "name_zh", "release_year", "review_count", "pct_positive", "is_free",
                                "windows", "mac", "linux", "deck_compat", "cn_blocked", "store_region", "igdb_id", "fetched"])
        comp = pd.read_parquet(C.PROC / "companies.parquet")
        comp = comp[comp["appid"].isin(kb.pos)]
        _copy(cur, "studio", comp.drop_duplicates("company_id").rename(columns={"company": "name"}), ["company_id", "name"])
        _copy(cur, "developed_by", comp.drop_duplicates(["appid", "company_id"]), ["appid", "company_id", "developer", "publisher"])
        s = kb.series[kb.series["appid"].isin(kb.pos)]
        _copy(cur, "series", s.drop_duplicates(["kind", "series_id"]), ["kind", "series_id", "name"])
        _copy(cur, "in_series", s.drop_duplicates(["appid", "kind", "series_id"]), ["appid", "kind", "series_id"])
        t = pd.read_parquet(C.PROC / "tags.parquet")
        _copy(cur, "tag", t, ["tagid", "name_en", "name_zh"])
        _copy(cur, "has_tag", kb.gt[kb.gt["tagid"].isin(t["tagid"])], ["appid", "tagid", "votes", "weight", "is_core"])
        modes = []
        for a in kb.appids:
            a = int(a)
            for mode, kind, inter in (("online_coop", "online", "coop"), ("online_pvp", "online", "versus"),
                                      ("local_coop", "local", "coop"), ("local_pvp", "local", "versus"),
                                      ("remote_play", "remote", "any")):
                st, _, mx = _mode_status(kb, a, kind, inter, 2, [2])
                if st == FAIL:
                    continue
                modes.append({"appid": a, "mode": mode, "max_players": None if not mx or mx[0] is None else int(mx[0]),
                              "max_source": mx[1] if mx else None, "status": {PASS: "PASS", UNKNOWN: "UNKNOWN"}[st]})
        md = pd.DataFrame(modes)
        md["max_players"] = md["max_players"].astype("Int64")
        _copy(cur, "has_mode", md, ["appid", "mode", "max_players", "max_source", "status"])
        sim = pd.read_parquet(C.PROC / "similar.parquet")
        sim = sim[sim["appid"].isin(kb.pos) & sim["similar_appid"].isin(kb.pos)]
        _copy(cur, "similar_to", sim, ["appid", "similar_appid"])
        co = kb.colike.rename(columns={"app_id": "appid"})
        _copy(cur, "co_liked", co, ["appid", "neighbor", "sim", "co_count"])
        from .refresh import snapshot_info
        pr = pd.read_parquet(C.PROC / "prices.parquet")
        pr = pr[pr["appid"].isin(kb.pos)].copy()
        pr["fetched"] = (snapshot_info() or {}).get("snapshot_date") or fetched
        _copy(cur, "price_snapshot", pr, ["appid", "region", "currency", "final", "original", "discount_pct", "is_free",
                                          "steam_low", "steam_low_time", "fetched"])
        conn.commit()
        cur.execute("SELECT relname, n_live_tup FROM pg_stat_user_tables ORDER BY relname")
        return dict(cur.fetchall())


class PathFinder:
    """Request-time lineage paths for the cards (design 6.2 '参数化 CTE 递归查询'): one connection per worker, a
    statement timeout, and silence on any database error so cards fall back to the in-memory lineage."""

    def __init__(self, workers=5, timeout_ms=1500):
        self.workers, self.timeout_ms = workers, timeout_ms
        self.ok = None
        self._local = __import__("threading").local()

    def _conn(self):
        c = getattr(self._local, "conn", None)
        if c is None or c.closed:
            c = connect()
            c.autocommit = True
            with c.cursor() as cur:
                cur.execute(f"SET statement_timeout = {int(self.timeout_ms)}")
            self._local.conn = c
        return c

    def available(self):
        if self.ok is None:
            try:
                with self._conn().cursor() as cur:
                    cur.execute("SELECT count(*) FROM game")
                    self.ok = cur.fetchone()[0] > 0
            except Exception:
                self.ok = False
        return self.ok

    def one(self, src, dst, max_depth=3):
        try:
            paths = lineage_paths(self._conn(), src, dst, max_depth=max_depth, limit=1)
            return paths[0] if paths else None
        except Exception:
            self._local.conn = None
            return None

    def many(self, pairs, max_depth=3):
        """pairs: [(src, dst)] -> [path text or None], queried in parallel."""
        if not pairs or not self.available():
            return [None] * len(pairs)
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(min(self.workers, len(pairs))) as ex:
            # carry: the path text is built in the worker, which must see the request's language
            return list(ex.map(carry(lambda p: self.one(p[0], p[1], max_depth)), pairs))


def _edge_label(label):
    """PATH_SQL edge labels are stored in Chinese; shown in the request's language."""
    return {"开发": L("开发", "developer"), "系列": L("系列", "series"),
            "IGDB 相似": L("IGDB 相似", "IGDB similar")}.get(label, label)


def lineage_paths(conn, src, dst, max_depth=3, limit=3):
    """Shortest lineage paths from game src to game dst, as readable steps."""
    with conn.cursor() as cur:
        cur.execute(PATH_SQL, {"src": int(src), "dst": int(dst), "max_depth": max_depth, "limit": limit})
        rows = cur.fetchall()
        if not rows:
            return []
        ids = {n for p, _ in rows for n in p}
        names = {}
        for kind, table, key in (("g", "game", "appid"), ("s", "studio", "company_id")):
            vals = [int(n[1:]) for n in ids if n[0] == kind]
            if vals:
                cur.execute(f"SELECT {key}, name FROM {table} WHERE {key} = ANY(%s)", (vals,))
                names.update({f"{kind}{k}": v for k, v in cur.fetchall()})
        vals = [int(n[1:]) for n in ids if n[0] == "c"]
        if vals:
            cur.execute("SELECT series_id, name FROM series WHERE kind = 'collection' AND series_id = ANY(%s)", (vals,))
            names.update({f"c{k}": v for k, v in cur.fetchall()})
    out = []
    for path, labels in rows:
        steps = [names.get(path[0], path[0])]
        for node, label in zip(path[1:], labels):
            steps.append(f"—{_edge_label(label)}→ {names.get(node, node)}")
        out.append(" ".join(steps))
    return out
