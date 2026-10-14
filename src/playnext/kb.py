"""Knowledge base loaded into memory: processed tables plus the derived matrices (design 6.2, 6.3).

Heavy parts (EASE weights, description vectors) load on first use. Every per-game array is aligned with
`KB.appids` (the 7,304 core games, games.parquet order).
"""
from functools import cached_property

import numpy as np
import pandas as pd

from . import config as C


class KB:
    def __init__(self):
        g = pd.read_parquet(C.PROC / "games.parquet").set_index("appid")
        self.games = g
        self.appids = g.index.to_numpy()
        self.n = len(self.appids)
        self.pos = {int(a): i for i, a in enumerate(self.appids)}
        self.name = g["name"]
        self.name_zh = g["name_zh"]
        tags = pd.read_parquet(C.PROC / "tags.parquet").set_index("tagid")
        self.tag_en, self.tag_zh = tags["name_en"], tags["name_zh"]
        gt = pd.read_parquet(C.PROC / "game_tags.parquet")
        gt = gt[gt["appid"].isin(self.pos)]
        self.gt = gt
        self.tagset = gt.groupby("appid")["tagid"].agg(set).to_dict()
        self.core = gt[gt["is_core"]].groupby("appid")["tagid"].agg(list).to_dict()
        self.tag_weight = {(a, t): w for a, t, w in gt[["appid", "tagid", "weight"]].itertuples(index=False)}
        self.T, self.T_has = self._tag_matrix(gt)
        cats = pd.read_parquet(C.PROC / "game_categories.parquet")
        self.categories = cats[cats["appid"].isin(self.pos)].groupby("appid")["category_id"].agg(set).to_dict()
        pr = pd.read_parquet(C.PROC / "prices.parquet")
        self.prices = {r: d.set_index("appid") for r, d in pr.groupby("region")}
        comp = pd.read_parquet(C.PROC / "companies.parquet")
        self.dev = comp[comp["developer"]]
        self.dev_of = self.dev.groupby("appid")["company_id"].agg(set).to_dict()
        self.dev_name = self.dev.groupby("appid")["company"].agg(list).to_dict()
        s = pd.read_parquet(C.PROC / "series.parquet")
        # IGDB numbers collections and franchises separately (collection 10 = Dragon Age, franchise 10 = Sid Meier)
        s["key"] = list(zip(s["kind"], s["series_id"]))
        self.series = s
        self.series_all = s.groupby("appid")["key"].agg(set).to_dict()
        self.series_of = s[s["kind"] == "collection"].groupby("appid")["key"].agg(set).to_dict()
        self.series_name = dict(zip(s["key"], s["name"]))
        sim = pd.read_parquet(C.PROC / "similar.parquet")
        self.similar_of = sim.groupby("appid")["similar_appid"].agg(set).to_dict()
        self.players = pd.read_parquet(C.PROC / "player_counts.parquet").set_index("appid")
        self.pc = self.players.to_dict("index")
        self.price_d = {r: d.to_dict("index") for r, d in self.prices.items()}
        self.is_free = g["is_free"].to_dict()
        self.cn_blocked = g["cn_blocked"].to_dict()
        ttb = pd.read_parquet(C.PROC / "time_to_beat.parquet").set_index("appid")
        self.time_to_beat = ttb
        rc = g["review_count"].fillna(0).to_numpy(np.float64)
        self.pos_reviews = rc * g["pct_positive"].fillna(0).to_numpy(np.float64) / 100
        self.review_count = rc
        self.quality = (self.pos_reviews + C.ALPHA) / (rc + C.ALPHA + C.BETA)
        self.rating_ok = (g["pct_positive"] >= C.RATING_FLOOR).to_numpy()
        self.popularity = rc

    # ---------- tags ----------
    def _tag_matrix(self, gt):
        df = gt.groupby("tagid")["appid"].nunique()
        idf = np.log(gt["appid"].nunique() / df)
        self.tag_cols = np.array(sorted(df.index))
        M = np.zeros((self.n, len(self.tag_cols)), np.float32)
        M[gt["appid"].map(self.pos).to_numpy(), np.searchsorted(self.tag_cols, gt["tagid"].to_numpy())] = \
            gt["weight"].to_numpy() * idf.reindex(gt["tagid"]).to_numpy()
        has = M.any(axis=1)
        M /= np.linalg.norm(M, axis=1, keepdims=True) + 1e-9
        return M, has

    def tag_weights(self, tagids):
        """(len(tagids), n) matrix of the per-game tag weight (votes / top votes), 0 where the game lacks the tag."""
        out = np.zeros((len(tagids), self.n), np.float32)
        for k, t in enumerate(tagids):
            sub = self.gt[self.gt["tagid"] == t]
            out[k, sub["appid"].map(self.pos).to_numpy()] = sub["weight"].to_numpy()
        return out

    # ---------- description vectors ----------
    @cached_property
    def E_lang(self):
        z = np.load(C.DESC_EMB)
        assert np.array_equal(z["appids"], self.appids), "rerun build_desc_embeddings.py after build_processed.py"
        return {lang: (z[lang].astype(np.float32), z["has_" + lang]) for lang in ("en", "zh")}

    @property
    def E_has(self):
        (_, a), (_, b) = self.E_lang.values()
        return a | b

    def desc_sim(self, rows=None, query=None):
        """Description similarity = larger of the English and Chinese versions (design 5.5); -1 where missing.
        rows: anchor row indices -> (len(rows), n); query: one query vector -> (n,)."""
        best = None
        for E, has in self.E_lang.values():
            if query is not None:
                s = np.where(has, E @ query, -1.0)
            else:
                s = np.where(has[rows][:, None] & has[None, :], E[rows] @ E.T, -1.0)
            best = s if best is None else np.maximum(best, s)
        return best.astype(np.float32)

    @cached_property
    def descriptions(self):
        """(appid, 'en' | 'zh') -> short + full description text (cleaned)."""
        d = pd.read_parquet(C.PROC / "descriptions.parquet")
        return {(int(a), l): f"{s} {f}".strip() for a, l, s, f in d[["appid", "lang", "short", "full"]].itertuples(index=False)
                if (s or f)}

    # ---------- co-like (EASE) ----------
    @cached_property
    def _ease(self):
        z = np.load(C.DER / "ease_reviews100m.npz")
        row = {int(a): j for j, a in enumerate(z["items"])}
        col = np.array([row.get(int(a), -1) for a in self.appids])
        return z["B"], row, col

    @property
    def ease_has(self):
        return self._ease[2] >= 0

    def ease_rows(self, appids):
        """(len(appids), n) EASE weights B[anchor, candidate] over the core games; zero rows for unknown anchors."""
        B, row, col = self._ease
        out = np.zeros((len(appids), self.n), np.float32)
        ok = col >= 0
        for k, a in enumerate(appids):
            if int(a) in row:
                out[k, ok] = B[row[int(a)], col[ok]]
        return out

    def ease_core(self):
        """Full core x core EASE matrix (eval only, ~210 MB)."""
        B, row, col = self._ease
        ok = col >= 0
        M = np.zeros((self.n, self.n), np.float32)
        M[np.ix_(ok, ok)] = B[np.ix_(col[ok], col[ok])]
        return M

    @cached_property
    def colike(self):
        c = pd.read_parquet(C.DER / "colike_reviews100m.parquet")
        return c[c["app_id"].isin(self.pos) & c["neighbor"].isin(self.pos)]

    @cached_property
    def colike_by_app(self):
        return {a: d for a, d in self.colike.groupby("app_id")}

    # ---------- lineage ----------
    @cached_property
    def apps_by_dev(self):
        return self.dev.groupby("company_id")["appid"].agg(set).to_dict()

    @cached_property
    def apps_by_series(self):
        return self.series.groupby("key")["appid"].agg(set).to_dict()

    def lineage(self, anchors):
        """Sets of candidate appids linked to any anchor: same developer, same series, IGDB similar."""
        same_dev, same_ser, sim = set(), set(), set()
        for a in anchors:
            for c in self.dev_of.get(a, ()):
                same_dev |= self.apps_by_dev.get(c, set())
            for k in self.series_all.get(a, ()):
                same_ser |= self.apps_by_series.get(k, set())
            sim |= self.similar_of.get(a, set())
        return same_dev, same_ser, sim

    # ---------- playtime ----------
    @cached_property
    def playtime_ref(self):
        return pd.read_parquet(C.DER / "playtime_reference_100m.parquet").set_index("app_id")

    def playtime_pct(self, appid, hours):
        """Share of the game's training reviewers who played less (design 5.5); None without a reference."""
        if appid not in self.playtime_ref.index:
            return None
        q = np.asarray(self.playtime_ref.loc[appid, "q"], np.float64)
        return float(np.interp(hours, q, np.linspace(0, 1, 101)))

    # ---------- helpers ----------
    def display_name(self, appid, lang="zh"):
        zh = self.name_zh.get(appid)
        return zh if lang == "zh" and isinstance(zh, str) and zh else self.name[appid]

    def price(self, appid, region):
        """Snapshot row as a dict (final, original, discount_pct, is_free, currency, steam_low, steam_low_time)."""
        return self.price_d.get(region, {}).get(appid)


def minmax(x, mask):
    """Min-max normalise x over the candidate pool `mask`; 0 outside it (design 5.5)."""
    out = np.zeros(x.shape, np.float32)
    if mask.any():
        lo, hi = x[mask].min(), x[mask].max()
        out[mask] = (x[mask] - lo) / (hi - lo + 1e-9)
    return out
