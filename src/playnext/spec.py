"""SessionSpec (design 5.4): everything later steps need, filled from the request, the questionnaire and the library."""
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

from .i18n import L


REGION_CURRENCY = {"CN": "CNY", "US": "USD"}   # store regions with price snapshots (design 3, first batch)


class Budget(BaseModel):
    amount: float = Field(ge=0)
    scope: Literal["per_person", "team_total"] = "per_person"
    currency: Optional[str] = None        # ISO code; None = the currency of the member's own store region

    def applies_to(self, region: str) -> bool:
        """Prices are only compared within one currency; no exchange rates (design 4.6)."""
        return self.currency is None or REGION_CURRENCY.get(region) == self.currency


class Library(BaseModel):
    """What GetOwnedGames told us. Only counts and playtimes; the SteamID itself is never stored here."""
    is_public: bool = True
    owned: dict[int, float] = {}          # appid -> Steam playtime in hours (0 = no Steam record)
    playtime_hidden: bool = False         # every playtime 0: the profile hides playtime (design 4.1 rule 4)

    @property
    def played(self) -> set[int]:
        return set() if self.playtime_hidden else {a for a, h in self.owned.items() if h > 0}

    @property
    def unplayed(self) -> set[int]:
        return set(self.owned) - self.played


class Member(BaseModel):
    name: str = Field(default_factory=lambda: L("我", "Me"))   # default name, in the request language
    region: str = "CN"
    library: Optional[Library] = None
    owned_extra: list[int] = []           # guests ticking "I already own this" on a card
    seeds: list[int] = []                 # this member's own liked games (questionnaire or named in the request)
    preference_text: Optional[str] = None
    feel_want: list[int] = []
    feel_avoid: list[int] = []
    avoid_tags: list[int] = []            # content the member refuses (hard)
    avoid_content: list[Literal["gore", "sexual"]] = []
    language: Optional[str] = None        # e.g. "schinese": must support it
    platform: Optional[Literal["windows", "mac", "linux", "deck"]] = None
    age_limit: Optional[int] = None
    played_elsewhere: list[int] = []
    # slow loop (design 5.3 Step 6): feedback saved for a bound account in earlier sessions
    liked: dict[int, float] = {}          # appid -> decayed weight, used like a library anchor
    disliked: list[int] = []              # excluded like played games

    def owns(self, appid: int) -> bool:
        return appid in self.owned_extra or (self.library is not None and appid in self.library.owned)

    @property
    def has_taste(self) -> bool:
        lib = self.library is not None and bool(self.library.played)
        return bool(self.seeds or self.preference_text or self.feel_want or self.feel_avoid or lib or self.liked)


class Site(BaseModel):
    """Members in front of one machine / one screen. remote_guest_of: index of the host site (Remote Play Together)."""
    members: list[int]
    remote_guest_of: Optional[int] = None


SetupType = Literal["online", "local", "remote", "hybrid"]


class SessionSpec(BaseModel):
    request_text: str = ""
    members: list[Member] = Field(default_factory=lambda: [Member()])
    # what this request asks for (shared requirement when there are several members)
    seeds: list[int] = []
    preference_text: Optional[str] = None
    feel_want: list[int] = []
    feel_avoid: list[int] = []
    mechanics: list[int] = []             # tag ids that must all be core tags (design 4.3 "机制组合")
    same_studio: bool = False             # soft preference
    max_hours: Optional[float] = None     # soft: "short game" (IGDB time to beat)
    interaction: Literal["coop", "versus", "any"] = "any"
    single_player: bool = False           # the one player said they will play alone: needs a single-player mode
    budget: Optional[Budget] = None
    price_intent: Literal["none", "cheap", "near_record_low"] = "none"
    only_discounted: bool = False
    library_policy: Literal["none", "prefer_owned", "exclude_owned"] = "none"
    sites: Optional[list[Site]] = None
    setup_hint: Optional[SetupType] = None  # what the user said ("remote play"), used when sites are not given
    accept_unknown: bool = False
    excluded: list[int] = []              # "玩过了 / 不感兴趣" clicked on a card in this session
    unresolved: list[str] = []            # names that matched no core game (shown to the user, never guessed)
    ambiguous: dict[str, list[int]] = {}  # name -> other games the same name may mean
    budget_unsupported: Optional[Budget] = None  # a budget in a currency without a price snapshot: not applied, said so
    outside_seeds: list[int] = []         # named Steam games outside the core library: content-only anchors (outside.py)

    @model_validator(mode="after")
    def _check(self):
        if not self.members:
            raise ValueError("at least one member")
        if self.sites:
            seen = [i for s in self.sites for i in s.members]
            if sorted(seen) != list(range(len(self.members))):
                raise ValueError("sites must place every member exactly once")
        return self

    @property
    def party_size(self) -> int:
        return len(self.members)

    @property
    def setup_types(self) -> list[SetupType]:
        """Setups to check (design 5.5): fixed by the sites; unknown location -> online and remote both."""
        if self.party_size == 1:
            return []
        if self.sites:
            if any(s.remote_guest_of is not None for s in self.sites):
                return ["remote"]
            if len(self.sites) == 1:
                return ["local"]
            if all(len(s.members) == 1 for s in self.sites):
                return ["online"]
            return ["hybrid"]
        if self.setup_hint:
            return [self.setup_hint]
        return ["online", "remote"]

    @property
    def has_shared(self) -> bool:
        return bool(self.seeds or self.preference_text or self.feel_want or self.feel_avoid or self.mechanics
                    or self.outside_seeds)
