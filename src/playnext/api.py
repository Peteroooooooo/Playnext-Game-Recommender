"""FastAPI backend (design 5.1). Run: uv run uvicorn --app-dir src playnext.api:app --host 127.0.0.1 --port 8000

No accounts: a session is an in-memory id. Steam IDs never leave library.py; sessions keep only appid -> hours.
Binds to 127.0.0.1 by default; there is no authentication, so do not expose it to a network as is.
"""
import secrets
import threading
import time
from pathlib import Path
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import appindex, config as C
from .cards import write_reasons
from .i18n import L, set_lang
from .library import LibraryError, fetch_library, library_from_profile, openid_login_url, openid_verify
from .profiles import Store, apply as apply_feedback, profile_key
from .spec import REGION_CURRENCY, Budget, Library, Member, SessionSpec, Site

SESSION_TTL = 6 * 3600
WEB_DIST = C.ROOT / "web" / "dist"

app = FastAPI(title="Playnext / Backlog Breaker")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])

_state = {"rec": None, "lock": threading.Lock()}
SESSIONS: dict = {}


def rec():
    with _state["lock"]:
        if _state["rec"] is None:
            from .pipeline import Recommender
            try:
                from .llm import LLM
                llm = LLM()
            except Exception:
                llm = None  # no LLM: free text unavailable, forms still work
            from .db import PathFinder
            paths = PathFinder()
            _state["rec"] = Recommender(llm=llm, live_prices=True, reasons=False,
                                        paths=paths if paths.available() else None)
            _state["store"] = Store()
            # design 4.6 'daily snapshot': a background thread refreshes the whole-library prices when the
            # snapshot is older than a day and swaps them into this process; set PLAYNEXT_NO_REFRESH to skip
            import os
            if not os.environ.get("PLAYNEXT_NO_REFRESH"):
                from .refresh import start_background
                start_background(_state["rec"].kb, _state["rec"].prices)
        return _state["rec"]


def store() -> Store:
    rec()
    return _state["store"]


def with_feedback(spec: SessionSpec, s) -> SessionSpec:
    """Slow loop: saved feedback of bound accounts goes into their members before every run."""
    for i, key in s["accounts"].items():
        if i < len(spec.members):
            apply_feedback(spec.members[i], store().load(key))
    return spec


def session(sid: Optional[str], create=True):
    now = time.time()
    for k in [k for k, v in SESSIONS.items() if now - v["t"] > SESSION_TTL]:
        SESSIONS.pop(k, None)
    if sid and sid in SESSIONS:
        SESSIONS[sid]["t"] = now
        return sid, SESSIONS[sid]
    if not create:
        raise HTTPException(404, L("会话已过期，请重新提交一次需求", "Session expired, please send your request again"))
    sid = secrets.token_urlsafe(12)
    SESSIONS[sid] = {"t": now, "libraries": {}, "accounts": {}, "spec": None, "parsed": None, "result": None,
                     "lang": "zh"}
    return sid, SESSIONS[sid]


Lang = Literal["zh", "en"]


def begin(s, lang: Optional[str]):
    """The session remembers the page language; every text this request builds uses it."""
    if lang:
        s["lang"] = lang
    set_lang(s["lang"])


def begin_existing(sid: str, lang: Optional[str]):
    set_lang(lang)  # the 404 below is already in the page language
    sid, s = session(sid, create=False)
    begin(s, lang)
    return sid, s


# ---------- reference data ----------

@app.get("/api/health")
def health():
    r = rec()
    from .refresh import LAST
    return {"ok": True, "games": r.kb.n, "llm": r.llm is not None,
            "pg": r.paths is not None, "feedback_saved": store().persistent, "price_snapshot": r.prices.snapshot_date,
            "price_refresh": dict(LAST)}


@app.get("/api/search")
def search(q: str, limit: int = 8, lang: Lang = "zh"):
    set_lang(lang)
    r = rec()
    kb = r.kb
    from .aliases import norm
    n = norm(q)
    if not n:
        return []
    hits = []
    m = r.resolver.resolve(q)
    if m and m.appid:
        hits.append(m.appid)
    names = kb.name.map(norm)
    zh = kb.name_zh.dropna().map(norm)
    sub = set(names[names.str.contains(n, regex=False)].index) | set(zh[zh.str.contains(n, regex=False)].index)
    hits += sorted(sub - set(hits), key=lambda a: -kb.review_count[kb.pos[a]])
    return [{"appid": int(a), "name": kb.display_name(int(a)), "name_en": kb.name[a],
             "year": None if kb.games.at[a, "release_year"] != kb.games.at[a, "release_year"] else int(kb.games.at[a, "release_year"]),
             "header": f"https://cdn.akamai.steamstatic.com/steam/apps/{a}/capsule_184x69.jpg"} for a in hits[:limit]]


FEEL_TAGS = ["Relaxing", "Casual", "Cozy", "Wholesome", "Cute", "Story Rich", "Atmospheric", "Difficult", "Souls-like",
             "Unforgiving", "Fast-Paced", "Strategy", "Puzzle", "Exploration", "Funny", "Dark", "Horror", "Gore",
             "Sexual Content", "Pixel Graphics", "Turn-Based", "Open World", "Short", "Competitive"]


@app.get("/api/tags")
def tags(lang: Lang = "zh"):
    set_lang(lang)
    kb = rec().kb
    by = {n: int(t) for t, n in kb.tag_en.items()}
    common = [{"tagid": by[n], "name": kb.tag_name(by[n]), "name_en": n} for n in FEEL_TAGS if n in by]
    return {"common": common, "all": [{"tagid": int(t), "name": kb.tag_name(t), "name_en": kb.tag_en[t]} for t in kb.tag_en.index]}


# ---------- library (paths A and B) ----------

class LibraryIn(BaseModel):
    session_id: Optional[str] = None
    member: int = 0
    profile: str
    lang: Lang = "zh"


def lib_summary(lib: Library, kb):
    in_core = [a for a in lib.owned if a in kb.pos]
    top = sorted((a for a in lib.played if a in kb.pos), key=lambda a: -lib.owned[a])[:6]
    outside = sorted((a for a in lib.owned if a not in kb.pos), key=lambda a: -lib.owned[a])
    return {"public": lib.is_public, "owned": len(lib.owned), "in_core": len(in_core), "played": len(lib.played),
            "playtime_hidden": lib.playtime_hidden,
            "top": [{"name": kb.display_name(a), "hours": round(lib.owned[a], 1)} for a in top],
            "outside_top": [n for n in (appindex.name_of(a) for a in outside[:20]) if n][:3]}


@app.post("/api/library")
def connect_library(body: LibraryIn):
    set_lang(body.lang)
    sid, s = session(body.session_id)
    try:
        lib, account = library_from_profile(body.profile)
    except LibraryError as e:
        raise HTTPException(400, str(e))
    except Exception:
        raise HTTPException(502, L("Steam 接口暂时不可用，请稍后再试", "Steam is not answering right now, please try again later"))
    s["libraries"][body.member] = lib
    s["accounts"][body.member] = account
    return {"session_id": sid, "member": body.member, "library": lib_summary(lib, rec().kb)}


@app.get("/api/auth/steam/login")
def steam_login(request: Request, session_id: Optional[str] = None, member: int = 0):
    sid, _ = session(session_id)
    base = str(request.base_url).rstrip("/")
    ret = f"{base}/api/auth/steam/callback?session_id={sid}&member={member}"
    return RedirectResponse(openid_login_url(ret, base))


@app.get("/api/auth/steam/callback")
def steam_callback(request: Request, session_id: str, member: int = 0):
    sid, s = session(session_id)
    params = dict(request.query_params)
    steamid = openid_verify({k: v for k, v in params.items() if k.startswith("openid.")})
    if not steamid:
        raise HTTPException(400, L("Steam 登录校验失败", "Steam sign-in could not be verified"))
    s["libraries"][member] = fetch_library(steamid)
    s["accounts"][member] = profile_key(steamid)
    return RedirectResponse(f"/?session_id={sid}&connected={member}")


# ---------- recommend ----------

class MemberIn(BaseModel):
    name: str = "我"
    region: Literal["CN", "US"] = "CN"
    seeds: list[int] = []
    feel_want: list[int] = []
    feel_avoid: list[int] = []
    avoid_tags: list[int] = []
    avoid_content: list[Literal["gore", "sexual"]] = []
    language: Optional[str] = None
    platform: Optional[Literal["windows", "mac", "linux", "deck"]] = None
    owned_extra: list[int] = []
    site: Optional[int] = None   # same number = same machine / screen
    preference_text: Optional[str] = Field(default=None, max_length=200)


class FormIn(BaseModel):
    members: list[MemberIn] = [MemberIn()]
    seeds: list[int] = []
    feel_want: list[int] = []
    feel_avoid: list[int] = []
    budget: Optional[float] = None
    budget_scope: Literal["per_person", "team_total"] = "per_person"
    price_intent: Literal["none", "cheap", "near_record_low"] = "none"
    interaction: Literal["coop", "versus", "any"] = "any"
    setup: Optional[Literal["online", "local", "remote", "hybrid"]] = None
    library_policy: Literal["none", "prefer_owned", "exclude_owned"] = "none"
    single_player: bool = False


class RecommendIn(BaseModel):
    session_id: Optional[str] = None
    text: Optional[str] = None
    form: Optional[FormIn] = None
    lang: Lang = "zh"


def form_spec(form: FormIn, libraries: dict) -> SessionSpec:
    members = []
    for i, m in enumerate(form.members):
        members.append(Member(name=L("我", "Me") if m.name == "我" else m.name, region=m.region, seeds=m.seeds, feel_want=m.feel_want, feel_avoid=m.feel_avoid,
                              avoid_tags=m.avoid_tags, avoid_content=m.avoid_content, language=m.language,
                              platform=m.platform, owned_extra=m.owned_extra, library=libraries.get(i),
                              preference_text=(m.preference_text or "").strip() or None))
    sites = None
    if len(members) > 1 and any(m.site is not None for m in form.members):
        groups = {}
        for i, m in enumerate(form.members):
            groups.setdefault(m.site if m.site is not None else f"solo{i}", []).append(i)
        sites = [Site(members=g) for g in groups.values()]
        if form.setup == "remote":
            sites = None
    # the form's budget is in the first member's store currency (the page shows ¥ or $ from that member's region)
    budget = (Budget(amount=form.budget, scope=form.budget_scope, currency=REGION_CURRENCY.get(members[0].region))
              if form.budget is not None else None)
    return SessionSpec(members=members, seeds=form.seeds, feel_want=form.feel_want, feel_avoid=form.feel_avoid,
                       budget=budget,
                       price_intent=form.price_intent, interaction=form.interaction, sites=sites,
                       setup_hint=form.setup if len(members) > 1 else None, library_policy=form.library_policy,
                       single_player=form.single_player and len(members) == 1)


def merge_form(spec: SessionSpec, form: FormIn, libraries: dict) -> SessionSpec:
    """Free text + form: the text decides the request, the form adds members' libraries and picks."""
    f = form_spec(form, libraries)
    # a currency said in the text ("$20 以内") names the store; the page's region switch only fills in when it does not
    stated = spec.budget is not None and spec.budget.currency in REGION_CURRENCY.values()
    while len(spec.members) < len(f.members):
        n = len(spec.members) + 1
        spec.members.append(Member(name=L(f"成员{n}", f"Player {n}")))
    for i, m in enumerate(f.members):
        t = spec.members[i]
        if m.name and m.name != "我" or i == 0:
            t.name = m.name if i or m.name != "我" else t.name
        t.library = m.library or t.library
        if not stated:
            t.region = m.region
        t.seeds = list(dict.fromkeys(t.seeds + m.seeds))
        t.avoid_tags = list(dict.fromkeys(t.avoid_tags + m.avoid_tags))
        t.owned_extra = list(dict.fromkeys(t.owned_extra + m.owned_extra))
        t.language, t.platform = t.language or m.language, t.platform or m.platform
        t.preference_text = t.preference_text or m.preference_text
    # people named only in the text ("我们 4 个人") shop in the store region the page has selected
    for t in spec.members[len(f.members):]:
        if not stated:
            t.region = f.members[0].region
    spec.seeds = list(dict.fromkeys(spec.seeds + f.seeds))
    if f.sites and not spec.sites:
        spec.sites = f.sites
    return spec


def respond(sid, s, res):
    s["spec"], s["result"] = res.spec, res
    out = res.to_dict()
    out["session_id"] = sid
    out["libraries"] = {i: lib_summary(l, rec().kb) for i, l in s["libraries"].items()}
    return out


@app.post("/api/recommend")
def recommend(body: RecommendIn):
    r = rec()
    sid, s = session(body.session_id)
    begin(s, body.lang)
    if body.text:
        if r.understander is None:
            raise HTTPException(503, L("现在没法理解自然语言，请搜索一款游戏开始", "Free text is unavailable right now; search for a game to start"))
        try:
            parsed, spec = r.understand(body.text)
        except Exception:
            raise HTTPException(502, L("需求理解失败（LLM 无响应或输出无效），请再试一次", "Could not understand the request (no valid answer from the LLM), please try again"))
        s["parsed"] = parsed
        if body.form:
            spec = merge_form(spec, body.form, s["libraries"])
        else:
            for i, lib in s["libraries"].items():
                if i < len(spec.members):
                    spec.members[i].library = lib
    elif body.form:
        s["parsed"] = None
        spec = form_spec(body.form, s["libraries"])
    else:
        raise HTTPException(400, L("请先输入需求", "Please describe what you want first"))
    return respond(sid, s, r.recommend(with_feedback(spec, s)))


class FollowIn(BaseModel):
    session_id: str
    text: str
    lang: Optional[Lang] = None


@app.post("/api/followup")
def followup(body: FollowIn):
    r = rec()
    sid, s = begin_existing(body.session_id, body.lang)
    if s["spec"] is None:
        raise HTTPException(400, L("还没有可以修改的推荐，请先提交一次需求", "No recommendation to change yet, send a request first"))
    if r.understander is None:
        raise HTTPException(503, L("现在没法理解自然语言", "Free text is unavailable right now"))
    from .understand import ParsedRequest
    parsed = s["parsed"] or ParsedRequest()
    try:
        parsed, spec = r.understand(body.text, s["spec"], parsed)
    except Exception:
        raise HTTPException(502, L("没能理解这次修改，请换个说法", "Could not understand that change, try saying it another way"))
    for m_new, m_old in zip(spec.members, s["spec"].members):
        m_new.library = m_new.library or m_old.library
        m_new.owned_extra = list(dict.fromkeys(m_new.owned_extra + m_old.owned_extra))
        m_new.played_elsewhere = list(dict.fromkeys(m_new.played_elsewhere + m_old.played_elsewhere))
        if not m_new.seeds and m_old.seeds:
            m_new.seeds = m_old.seeds
        m_new.liked = {**m_old.liked, **m_new.liked}
        m_new.disliked = list(dict.fromkeys(m_new.disliked + m_old.disliked))
    spec.excluded = list(dict.fromkeys(s["spec"].excluded + spec.excluded))
    if not spec.sites and not parsed.party.setup and s["spec"].sites and spec.party_size == s["spec"].party_size:
        spec.sites = s["spec"].sites
    s["parsed"] = parsed
    return respond(sid, s, r.recommend(with_feedback(spec, s)))


class CardAction(BaseModel):
    session_id: str
    appid: int
    action: Literal["played", "owned", "not_interested", "liked", "disliked"]
    member: int = 0
    lang: Optional[Lang] = None


@app.post("/api/card")
def card_action(body: CardAction):
    """'玩过了' excludes the game (design 4.1 rule 3); 'owned' ticks ownership for a guest; 喜欢 / 不喜欢 feed the
    slow loop (design 5.3 Step 6): saved for a bound account, session-only for guests."""
    r = rec()
    sid, s = begin_existing(body.session_id, body.lang)
    spec = s["spec"]
    if spec is None:
        raise HTTPException(400, L("还没有推荐结果，请先提交一次需求", "No recommendation yet, send a request first"))
    k = min(body.member, len(spec.members) - 1)
    m = spec.members[k]
    if body.action == "owned":
        m.owned_extra = list(dict.fromkeys(m.owned_extra + [body.appid]))
    elif body.action == "liked":
        m.liked = {**m.liked, body.appid: 1.0}
    elif body.action == "disliked":
        m.disliked = list(dict.fromkeys(m.disliked + [body.appid]))
    else:
        spec.excluded = list(dict.fromkeys(spec.excluded + [body.appid]))
    feedback = None
    if body.action in ("played", "liked", "disliked"):
        account = s["accounts"].get(k)
        if account is None:
            feedback = {"saved": False, "message": L("访客的反馈只在这次会话里生效", "As a guest, this only counts for this session")}
        elif store().save(account, body.appid, body.action):
            feedback = {"saved": True, "message": L("已记下，下次用同一个 Steam 账号接入时会用上", "Saved; it will be used the next time you connect this Steam account")}
        else:
            feedback = {"saved": False, "message": L("数据库暂时不可用，这条反馈只在服务运行期间有效", "The database is unavailable; this only counts until the service restarts")}
    out = respond(sid, s, r.recommend(with_feedback(spec, s)))
    if feedback:
        out["feedback"] = feedback
    return out


class RelaxIn(BaseModel):
    session_id: str
    key: Literal["budget", "discount", "mechanics", "solo", "setup", "unknown"]
    lang: Optional[Lang] = None


@app.post("/api/relax")
def relax(body: RelaxIn):
    """'不在乎这条': the last request again with one condition dropped, offered on a near miss. No LLM call."""
    r = rec()
    sid, s = begin_existing(body.session_id, body.lang)
    if s["spec"] is None:
        raise HTTPException(400, L("还没有推荐结果，请先提交一次需求", "No recommendation yet, send a request first"))
    from .pipeline import relax_spec
    return respond(sid, s, r.recommend(with_feedback(relax_spec(s["spec"], body.key), s)))


class RerunIn(BaseModel):
    session_id: str
    lang: Optional[Lang] = None


@app.post("/api/rerun")
def rerun(body: RerunIn):
    """The last request again with the Steam libraries connected since then (the page calls it right after an import).
    No LLM understanding step. `played_out`: earlier picks that are now left out because they have Steam playtime."""
    r = rec()
    sid, s = begin_existing(body.session_id, body.lang)
    spec = s["spec"]
    if spec is None:
        raise HTTPException(400, L("还没有推荐结果，请先提交一次需求", "No recommendation yet, send a request first"))
    before = [c["appid"] for c in s["result"].picks] if s["result"] else []
    for i, lib in s["libraries"].items():
        if i < len(spec.members):
            spec.members[i].library = lib
    out = respond(sid, s, r.recommend(with_feedback(spec, s)))
    now = {c["appid"] for c in out["picks"]}
    # Steam playtime only excludes for one player (rules.py, rule "exclude")
    played = spec.members[0].library.played if spec.party_size == 1 and spec.members[0].library else set()
    out["played_out"] = [a for a in before if a not in now and a in played]
    return out


class ReportIn(BaseModel):
    session_id: Optional[str] = None
    appid: int
    field: Literal["players", "modes", "price", "tags", "other"] = "other"
    text: str = Field(default="", max_length=300)


@app.post("/api/report")
def report(body: ReportIn):
    """A user says a card fact is wrong (design 5.3 Step 6): recorded without any account or session data and
    checked against the sources at the next data refresh; nothing is changed automatically."""
    if body.appid not in rec().kb.pos:
        raise HTTPException(404, L("没有这款游戏", "Unknown game"))
    return {"ok": store().report(body.appid, body.field, body.text)}


class ReasonsIn(BaseModel):
    session_id: str
    lang: Optional[Lang] = None


@app.post("/api/reasons")
def reasons(body: ReasonsIn):
    """LLM reasons for the current picks; called after the cards are shown, so the first answer is fast."""
    r = rec()
    sid, s = begin_existing(body.session_id, body.lang)
    res = s["result"]
    if res is None:
        raise HTTPException(400, L("还没有推荐结果", "No recommendation yet"))
    write_reasons(res.picks, r.llm, res.spec.request_text)
    return {c["appid"]: {"reason": c["reason"], "source": c["reason_source"]} for c in res.picks}


# ---------- built web app ----------

if WEB_DIST.exists():
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        f = WEB_DIST / path
        if path and f.is_file() and WEB_DIST in f.resolve().parents:
            return FileResponse(f)
        return FileResponse(WEB_DIST / "index.html")
