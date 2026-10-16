"""Games outside the core library (design 6.1: "用户库或种子里出现、但不在核心库的游戏按需补全档案").

A name that matches no core game is looked up in the light index of all Steam games (appindex.py). When it is a
Steam game, its store entry is fetched once (IStoreBrowseService/GetItems, the same request as the core library),
and it becomes a content-only taste anchor: its tags in the core tag space and its description vector. It has no
co-like data (it is not in the review matrix), so for such an anchor the co-like weight goes to tags and
descriptions. It is never recommended itself (not in the core library) and the card says the anchor was outside.
"""
import json
import re
import threading
import urllib.parse
import urllib.request

import numpy as np

from . import appindex
from .kb import KB

URL = "https://api.steampowered.com/IStoreBrowseService/GetItems/v1/?input_json="
_cache: dict = {}
_lock = threading.Lock()


def clean(bbcode):
    text = re.sub(r"\[/?[^\]]+\]", " ", bbcode or "")
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def fetch(appid, timeout=5):
    """Store facts of one game: {name, tags: {tagid: votes}, text} or None. Cached for the process."""
    with _lock:
        if appid in _cache:
            return _cache[appid]
    inp = {"ids": [{"appid": int(appid)}], "context": {"language": "english", "country_code": "US", "steam_realm": 1},
           "data_request": {"include_basic_info": True, "include_tag_count": 20, "include_full_description": True}}
    try:
        req = urllib.request.Request(URL + urllib.parse.quote(json.dumps(inp)), headers={"User-Agent": "BacklogBreaker/0.1"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            items = json.loads(r.read().decode()).get("response", {}).get("store_items", [])
    except Exception:
        return None
    it = items[0] if items else {}
    if not it.get("name"):
        out = None
    else:
        bi = it.get("basic_info") or {}
        out = {"appid": int(appid), "name": it["name"],
               "tags": {int(t["tagid"]): float(t["weight"]) for t in it.get("tags", [])},
               "text": (bi.get("short_description", "") + "\n" + clean(it.get("full_description_bbcode", ""))).strip()}
    with _lock:
        _cache[appid] = out
    return out


def _review_counts(appids, timeout=5):
    inp = {"ids": [{"appid": int(a)} for a in appids], "context": {"language": "english", "country_code": "US", "steam_realm": 1},
           "data_request": {"include_reviews": True}}
    try:
        req = urllib.request.Request(URL + urllib.parse.quote(json.dumps(inp)), headers={"User-Agent": "BacklogBreaker/0.1"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            items = json.loads(r.read().decode()).get("response", {}).get("store_items", [])
    except Exception:
        return {}
    return {int(it["appid"]): ((it.get("reviews") or {}).get("summary_filtered") or {}).get("review_count", 0)
            for it in items if it.get("appid")}


_picked: dict = {}


def lookup(name, kb: KB | None = None):
    """A typed name -> (appid, store name) of a Steam game outside the core library whose normalised store name is
    exactly that name, or None (prefix matches are not trusted: "PEAK" would also match "Peaky Blinders"). Several
    games can share a name ("Peak", "PEAK"): the one with the most Steam reviews is meant."""
    from .aliases import norm
    key = norm(name)
    if key in _picked:
        return _picked[key]
    hits = [(a, n) for a, n in appindex.search(name, limit=10) if norm(n) == key and (kb is None or a not in kb.pos)]
    if len(hits) > 1:
        counts = _review_counts([a for a, _ in hits])
        hits.sort(key=lambda h: -counts.get(h[0], 0))
    _picked[key] = hits[0] if hits else None
    return _picked[key]


def anchor(kb: KB, appid, encoder=None):
    """-> {"appid", "name", "tag_vec", "desc_vec"} usable by scoring.channel_scores, or None."""
    f = fetch(appid)
    if not f:
        return None
    tv = kb.tag_vector(f["tags"])
    dv = encoder.doc(f["text"]) if (encoder is not None and hasattr(encoder, "doc") and f["text"]) else None
    if tv is None and dv is None:
        return None
    return {"appid": f["appid"], "name": f["name"], "tag_vec": tv, "desc_vec": dv}
