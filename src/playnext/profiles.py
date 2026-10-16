"""Slow loop (design 5.3 Step 6): feedback given on cards is kept per bound Steam account and applied the next time
the same account connects; fact-error reports are only recorded, to be checked against the sources at the next
data refresh.

Privacy: the account is stored as a keyed hash (BLAKE2b with a secret kept in .cache/, which git ignores). The raw
SteamID is never written anywhere. Hashes are stable across restarts on this machine (that is what lets the
feedback come back) and cannot be recomputed without the secret. Guests have no key: their feedback lives only in
the session. Reports carry no account or session data at all.
Storage: PostgreSQL tables member_feedback and fact_report (created on first use, not touched by db.load);
without a database the feedback stays in this process only and the caller is told so.
"""
import hashlib
import json
import math
import os
import threading
import time

from . import config as C

SIGNALS = ("played", "liked", "disliked")
FIELDS = ("players", "modes", "price", "tags", "other")
DDL = """
CREATE TABLE IF NOT EXISTS member_feedback (account text NOT NULL, appid int NOT NULL, signal text NOT NULL,
                                            created timestamptz NOT NULL DEFAULT now(), PRIMARY KEY (account, appid));
CREATE TABLE IF NOT EXISTS fact_report (id bigserial PRIMARY KEY, appid int NOT NULL, field text NOT NULL,
                                        text text NOT NULL, created timestamptz NOT NULL DEFAULT now());
"""
_lock = threading.Lock()


def _secret():
    path = C.CACHE / "profile_secret"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(os.urandom(32))
    return path.read_bytes()


def profile_key(steamid) -> str:
    return hashlib.blake2b(str(steamid).encode(), key=_secret(), digest_size=16).hexdigest()


def decay(age_days: float) -> float:
    """Weight of a 'liked' game as a taste anchor: 1.0 when fresh, halving every LIKED_HALF_LIFE_DAYS."""
    return 0.5 ** (max(age_days, 0.0) / C.LIKED_HALF_LIFE_DAYS)


class Store:
    def __init__(self):
        self.mem = {}          # fallback: account -> {appid: (signal, time)}
        self.reports = []
        self.db = None
        try:
            from .db import connect
            conn = connect()
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(DDL)
            self.db = conn
        except Exception:
            self.db = None

    @property
    def persistent(self):
        return self.db is not None

    def save(self, account: str, appid: int, signal: str):
        if signal not in SIGNALS:
            raise ValueError(signal)
        with _lock:
            if self.db is not None:
                try:
                    with self.db.cursor() as cur:
                        cur.execute("INSERT INTO member_feedback (account, appid, signal) VALUES (%s, %s, %s) "
                                    "ON CONFLICT (account, appid) DO UPDATE SET signal = EXCLUDED.signal, created = now()",
                                    (account, int(appid), signal))
                    return True
                except Exception:
                    self.db = None
            self.mem.setdefault(account, {})[int(appid)] = (signal, time.time())
            return False

    def load(self, account: str) -> dict:
        """-> {"played": [appid], "disliked": [appid], "liked": {appid: decayed weight}}"""
        rows = []
        with _lock:
            if self.db is not None:
                try:
                    with self.db.cursor() as cur:
                        cur.execute("SELECT appid, signal, extract(epoch FROM created) FROM member_feedback WHERE account = %s",
                                    (account,))
                        rows = cur.fetchall()
                except Exception:
                    self.db = None
            if self.db is None:
                rows = [(a, s, t) for a, (s, t) in self.mem.get(account, {}).items()]
        out = {"played": [], "disliked": [], "liked": {}}
        now = time.time()
        for appid, signal, t in rows:
            if signal == "liked":
                out["liked"][int(appid)] = round(decay((now - float(t)) / 86400), 3)
            else:
                out[signal].append(int(appid))
        return out

    def report(self, appid: int, field: str, text: str):
        field = field if field in FIELDS else "other"
        text = (text or "").strip()[:300]
        with _lock:
            if self.db is not None:
                try:
                    with self.db.cursor() as cur:
                        cur.execute("INSERT INTO fact_report (appid, field, text) VALUES (%s, %s, %s)",
                                    (int(appid), field, text))
                    return True
                except Exception:
                    self.db = None
            path = C.CACHE / "fact_reports.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"appid": int(appid), "field": field, "text": text,
                                    "created": time.strftime("%Y-%m-%d %H:%M:%S")}, ensure_ascii=False) + "\n")
            return True


def apply(member, fb: dict):
    """Put saved feedback into a Member (excluded played / disliked, liked as decayed anchors)."""
    member.played_elsewhere = list(dict.fromkeys(member.played_elsewhere + fb["played"]))
    member.disliked = list(dict.fromkeys(member.disliked + fb["disliked"]))
    member.liked = {**member.liked, **{a: w for a, w in fb["liked"].items() if not math.isclose(w, 0)}}
    return member
