"""Step 1 (request -> SessionSpec) and Step 6 fast loop (follow-up -> patched SessionSpec), design 4.3 / 5.4.

The LLM fills a ParsedRequest (only what the user said); Python then resolves game names through the alias table
and tag names against the 446 Steam tags. Names that match nothing are listed in spec.unresolved, never guessed.
"""
import json
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

from .aliases import Resolver
from .kb import KB
from .llm import chat_json
from .spec import Budget, Member, SessionSpec, Site


class PersonIn(BaseModel):
    name: str
    likes: list[str] = []
    owns: list[str] = []
    preference_text: Optional[str] = None
    feel_want: list[str] = []
    feel_avoid: list[str] = []
    avoid_tags: list[str] = []
    avoid_content: list[Literal["gore", "sexual"]] = []


class BudgetIn(BaseModel):
    amount: float = Field(ge=0)
    scope: Literal["per_person", "team_total"] = "per_person"
    currency: Literal["CNY", "USD"] = "CNY"


class PartyIn(BaseModel):
    size: Optional[int] = Field(default=None, ge=1, le=16)
    interaction: Literal["coop", "versus", "any"] = "any"
    setup: Optional[Literal["online", "local", "remote", "hybrid"]] = None
    groups: Optional[list[int]] = None  # people per location, e.g. [2, 1, 1, 1]


class ParsedRequest(BaseModel):
    seeds: list[str] = []
    played: list[str] = []
    preference_text: Optional[str] = None
    feel_want: list[str] = []
    feel_avoid: list[str] = []
    mechanics: list[str] = []
    avoid_tags: list[str] = []
    avoid_content: list[Literal["gore", "sexual"]] = []
    budget: Optional[BudgetIn] = None
    price_intent: Literal["none", "cheap", "near_record_low"] = "none"
    only_discounted: bool = False
    library_policy: Literal["none", "prefer_owned", "exclude_owned"] = "none"
    language: Optional[Literal["schinese", "tchinese", "english", "japanese", "korean"]] = None
    platform: Optional[Literal["windows", "mac", "linux", "deck"]] = None
    age_limit: Optional[int] = None
    max_hours: Optional[float] = None
    same_studio: bool = False
    party: PartyIn = PartyIn()
    people: list[PersonIn] = []

    @field_validator("feel_want", "feel_avoid", "mechanics", "avoid_tags")
    @classmethod
    def _cap(cls, v):
        return v[:6]


SYSTEM = """You turn a Steam PC player's game request into JSON. Fill ONLY what the user actually said; leave everything else empty, null or default. Never invent games or constraints.
Fields:
- seeds: games named as the taste reference for THIS request ("like Hades", "我喜欢文明6"), as the user wrote them or the official English Steam title.
- played: games the user says they already played or finished (on any platform). A game they liked goes in both seeds and played.
- preference_text: only the words describing the experience wanted, copied verbatim (drop game names, budget, price, people count, filler such as "similar"). null if none.
- feel_want / feel_avoid: up to 4 Steam tag names each for the feel, pace or difficulty wanted / not wanted ("别太难" -> feel_avoid Difficult, Souls-like, Unforgiving; "轻松" -> feel_want Relaxing, Casual, Cozy).
- mechanics: only when the user asks for a combination of gameplay types that must BOTH be central ("肉鸽 + 基地经营" -> Roguelike, Base Building).
- avoid_tags: content refused outright (horror, gore-themed tags, ...); hard exclusion. avoid_content: "gore" and/or "sexual" when refused.
- budget {amount, scope per_person|team_total, currency CNY|USD}: only if stated. "60块" = 60 CNY; "$20" = USD.
- price_intent: near_record_low for "打折 / on sale / 史低 / discount", cheap for "便宜 / cheap"; only_discounted true only for "只看打折的 / must be on sale".
- library_policy: prefer_owned for "库里已有的优先 / from my library", exclude_owned for "不要我已经有的".
- language: required language only if stated ("要有中文" -> schinese). platform: mac / linux / deck only if stated.
- age_limit: number if they say the game must suit an age. max_hours: for "短一点 / 一个周末能通关" give hours (e.g. 10).
- same_studio: true if they ask for the same developer.
- party: size = number of players including the user, if stated; interaction coop|versus|any; setup online (each at home), local (same screen / couch), remote (Remote Play Together), hybrid (some together, some online); groups = people per location for hybrid, e.g. "2 人客厅 + 3 人在线" -> [2, 1, 1, 1].
- people: other players mentioned with their own taste or ownership ("小张喜欢射击", "我朋友有 Deep Rock") -> name, likes, owns, preference_text, feel_want, feel_avoid, avoid_tags ("小张晕 3D" -> feel_avoid First-Person / avoid_tags as fitting).
Tag names must be English names from this list (English=Chinese): {tags}
Return only the JSON object."""

PATCH = """The user is refining an earlier request. Current request as JSON:
{current}
The user now says: {text}
Return the FULL updated JSON object in the same schema: change only what the new message changes, keep everything else."""


def _drop_nulls(x):
    """The LLM writes null for fields it leaves empty; treat that as 'not said' so defaults apply."""
    if isinstance(x, dict):
        return {k: _drop_nulls(v) for k, v in x.items() if v is not None}
    if isinstance(x, list):
        return [_drop_nulls(v) for v in x if v is not None]
    return x


class Understander:
    def __init__(self, kb: KB, llm):
        self.kb, self.llm = kb, llm
        self.resolver = Resolver(kb.games)
        self.tag_by_name = {n.lower(): int(t) for t, n in kb.tag_en.items()}
        self.tag_by_name.update({str(n).lower(): int(t) for t, n in kb.tag_zh.items() if isinstance(n, str)})
        self.system = SYSTEM.replace("{tags}", "; ".join(f"{kb.tag_en[t]}={kb.tag_zh[t]}" for t in kb.tag_en.index))

    def _validate(self, obj):
        p = ParsedRequest.model_validate(_drop_nulls(obj))
        bad = [t for f in ("feel_want", "feel_avoid", "mechanics", "avoid_tags") for t in getattr(p, f)
               if t.lower() not in self.tag_by_name]
        bad += [t for person in p.people for f in ("feel_want", "feel_avoid", "avoid_tags") for t in getattr(person, f)
                if t.lower() not in self.tag_by_name]
        if bad:
            raise ValueError(f"unknown tag names {bad}; use names from the list")
        return p

    def parse(self, text) -> ParsedRequest:
        return chat_json(self.llm, self.system, text, "understand", self._validate)

    def patch(self, parsed: ParsedRequest, text) -> ParsedRequest:
        user = PATCH.format(current=parsed.model_dump_json(), text=text)
        return chat_json(self.llm, self.system, user, "patch", self._validate)

    # ---------- ParsedRequest -> SessionSpec ----------
    def tags(self, names):
        return [self.tag_by_name[n.lower()] for n in names if n.lower() in self.tag_by_name]

    def games(self, names, spec_unresolved, spec_ambiguous):
        out = []
        for n in names:
            m = self.resolver.resolve(n)
            if m.appid is None:
                if m.how == "ambiguous":
                    spec_ambiguous[n] = m.candidates
                else:
                    spec_unresolved.append(n)
                continue
            if m.candidates:
                spec_ambiguous[n] = [m.appid] + m.candidates
            out.append(m.appid)
        return list(dict.fromkeys(out))

    def to_spec(self, p: ParsedRequest, text="", base: SessionSpec | None = None) -> SessionSpec:
        unresolved, ambiguous = [], {}
        seeds = self.games(p.seeds, unresolved, ambiguous)
        played = self.games(p.played, unresolved, ambiguous)
        size = max(p.party.size or 1, 1 + len(p.people), len(base.members) if base else 1)
        old = base.members if base else []
        members = []
        region = "US" if p.budget and p.budget.currency == "USD" else (old[0].region if old else "CN")
        for i in range(size):
            prev = old[i] if i < len(old) else None
            m = Member(name=prev.name if prev else ("我" if i == 0 else f"成员{i + 1}"), region=prev.region if prev else region,
                       library=prev.library if prev else None, owned_extra=list(prev.owned_extra) if prev else [])
            members.append(m)
        me = members[0]
        me.played_elsewhere = played
        me.language, me.platform, me.age_limit = p.language, p.platform, p.age_limit
        me.avoid_tags, me.avoid_content = self.tags(p.avoid_tags), list(p.avoid_content)
        for k, person in enumerate(p.people):
            m = members[k + 1]
            m.name = person.name
            m.seeds = self.games(person.likes, unresolved, ambiguous)
            m.owned_extra = list(dict.fromkeys(m.owned_extra + self.games(person.owns, unresolved, ambiguous)))
            m.preference_text = person.preference_text
            m.feel_want, m.feel_avoid = self.tags(person.feel_want), self.tags(person.feel_avoid)
            m.avoid_tags, m.avoid_content = self.tags(person.avoid_tags), list(person.avoid_content)
            m.language, m.platform, m.age_limit = p.language, p.platform, p.age_limit
        if size > 1:  # shared constraints apply to every member
            for m in members[1:]:
                m.avoid_tags = list(dict.fromkeys(m.avoid_tags + me.avoid_tags))
                m.avoid_content = list(dict.fromkeys(m.avoid_content + me.avoid_content))
        sites = None
        if size > 1 and p.party.groups and sum(p.party.groups) == size:
            sites, k = [], 0
            for g in p.party.groups:
                sites.append(Site(members=list(range(k, k + g))))
                k += g
        elif size > 1 and p.party.setup == "local":
            sites = [Site(members=list(range(size)))]
        budget = Budget(amount=p.budget.amount, scope=p.budget.scope) if p.budget else None
        spec = SessionSpec(
            request_text=text, members=members, seeds=seeds, preference_text=p.preference_text,
            feel_want=self.tags(p.feel_want), feel_avoid=self.tags(p.feel_avoid), mechanics=self.tags(p.mechanics),
            same_studio=p.same_studio, max_hours=p.max_hours, interaction=p.party.interaction, budget=budget,
            price_intent=p.price_intent, only_discounted=p.only_discounted, library_policy=p.library_policy,
            sites=sites, setup_hint=p.party.setup if size > 1 else None, unresolved=unresolved, ambiguous=ambiguous)
        return spec


def describe(kb: KB, spec: SessionSpec) -> dict:
    """Readable summary of what Step 1 understood (shown on the result page)."""
    name = kb.display_name
    tz = lambda ts: [kb.tag_zh[t] for t in ts]
    out = {"seeds": [name(a) for a in spec.seeds], "preference_text": spec.preference_text,
           "feel_want": tz(spec.feel_want), "feel_avoid": tz(spec.feel_avoid), "mechanics": tz(spec.mechanics),
           "budget": spec.budget.model_dump() if spec.budget else None, "price_intent": spec.price_intent,
           "only_discounted": spec.only_discounted, "library_policy": spec.library_policy,
           "party_size": spec.party_size, "interaction": spec.interaction, "setups": spec.setup_types,
           "unresolved": spec.unresolved,
           "ambiguous": {k: [name(a) for a in v] for k, v in spec.ambiguous.items()},
           "members": []}
    for m in spec.members:
        out["members"].append({
            "name": m.name, "region": m.region, "seeds": [name(a) for a in m.seeds],
            "played_elsewhere": [name(a) for a in m.played_elsewhere], "avoid": tz(m.avoid_tags) + m.avoid_content,
            "language": m.language, "platform": m.platform,
            "library": None if m.library is None else {"public": m.library.is_public, "owned": len(m.library.owned),
                                                       "played": len(m.library.played),
                                                       "playtime_hidden": m.library.playtime_hidden}})
    return out
