"""Resolve a typed game name to a core AppID (design 4.3 step 1): alias table first, then a unique substring.

The alias table (data/processed/aliases.parquet) is built by scripts/build_aliases.py from the store names in
both languages plus the names Chinese players commonly use.
"""
import re
import unicodedata
from dataclasses import dataclass, field

import pandas as pd

from . import config as C


def norm(s):
    s = unicodedata.normalize("NFKC", str(s)).lower()
    s = re.sub(r"[®™©]", "", s)
    return re.sub(r"[^0-9a-z㐀-鿿぀-ヿ]", "", s)


def words_of(s):
    """Lower-case words of a name, single-spaced ("Sid Meier's Civilization® VI" -> "sid meier s civilization vi")."""
    s = unicodedata.normalize("NFKC", str(s)).lower()
    s = re.sub(r"[®™©]", "", s)
    return " ".join(re.findall(r"[0-9a-z]+", s))


@dataclass
class Match:
    text: str
    appid: int | None
    candidates: list = field(default_factory=list)  # other games the same name points to (most reviewed first)
    how: str = "none"  # alias / substring / none


class Resolver:
    def __init__(self, games: pd.DataFrame):
        t = pd.read_parquet(C.PROC / "aliases.parquet")
        t = t[t["appid"].isin(games.index)]
        self.reviews = games["review_count"].fillna(0)
        self.by_alias = t.groupby("alias")["appid"].agg(lambda s: sorted(set(s), key=lambda a: -self.reviews.get(a, 0))).to_dict()
        self.names = games["name"].map(norm)
        self.names_zh = games["name_zh"].dropna().map(norm)
        self.words = games["name"].map(words_of)

    def resolve(self, text) -> Match:
        n = norm(text)
        if not n:
            return Match(text, None)
        cands = self.by_alias.get(n)
        if cands:
            return Match(text, int(cands[0]), [int(a) for a in cands[1:]], "alias")
        if len(n) >= 3:  # whole words of one store name, e.g. "Witcher 3" for the remastered edition
            hits = set()
            if re.search(r"[㐀-鿿぀-ヿ]", n):  # CJK has no word boundaries: plain substring
                hits = set(self.names_zh[self.names_zh.str.contains(n, regex=False)].index)
            words = words_of(text)
            if words:
                pat = r"(?:^| )" + re.escape(words) + r"(?: |$)"
                hits |= set(self.words[self.words.str.contains(pat, regex=True)].index)
            if len(hits) == 1:
                return Match(text, int(hits.pop()), [], "substring")
            if 1 < len(hits) <= 5:
                ranked = sorted(hits, key=lambda a: -self.reviews.get(a, 0))
                return Match(text, None, [int(a) for a in ranked], "ambiguous")
        return Match(text, None)
