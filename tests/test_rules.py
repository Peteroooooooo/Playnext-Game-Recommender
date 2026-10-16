import numpy as np

from conftest import AMONG_US, DEEP_ROCK, HADES, IT_TAKES_TWO, ROCKET_LEAGUE, STARDEW, TERRARIA
from playnext.rules import FAIL, PASS, UNKNOWN, hard_filter
from playnext.spec import Budget, Library, Member, SessionSpec, Site


def status(kb, fr, appid):
    return int(fr.status[kb.pos[appid]])


def group(n, **kw):
    return SessionSpec(members=[Member(name=f"P{i}") for i in range(n)], **kw)


def test_setup_types_follow_sites():
    assert group(3, sites=[Site(members=[0]), Site(members=[1]), Site(members=[2])]).setup_types == ["online"]
    assert group(3, sites=[Site(members=[0, 1, 2])]).setup_types == ["local"]
    assert group(3, sites=[Site(members=[0, 1]), Site(members=[2])]).setup_types == ["hybrid"]
    assert group(3).setup_types == ["online", "remote"]  # location not said: check both remote ways
    assert SessionSpec().setup_types == []


def test_player_count_from_igdb(kb):
    online = lambda n: [Site(members=[i]) for i in range(n)]
    fr = hard_filter(kb, group(5, interaction="coop", sites=online(5)))
    # IGDB has only a non-PC record for It Takes Two (max 2): such counts can PASS a request but not FAIL it
    assert kb.pc[IT_TAKES_TWO]["count_platform"] == "other"
    assert status(kb, fr, IT_TAKES_TWO) == UNKNOWN
    assert "非 PC 版记录" in fr.setups["online"].reason[IT_TAKES_TWO]
    assert kb.pc[DEEP_ROCK]["count_platform"] == "pc"
    assert status(kb, fr, DEEP_ROCK) == FAIL              # PC record: max 4
    assert "差 1 个位" in fr.setups["online"].reason[DEEP_ROCK]
    assert status(kb, fr, AMONG_US) == PASS               # max 15
    fr = hard_filter(kb, group(2, interaction="coop", sites=online(2)))
    assert status(kb, fr, IT_TAKES_TWO) == PASS


def test_no_mode_category_fails(kb):
    fr = hard_filter(kb, group(2, sites=[Site(members=[0]), Site(members=[1])]))
    assert status(kb, fr, HADES) == FAIL                  # single-player only


def test_local_and_remote(kb):
    fr = hard_filter(kb, group(2, interaction="coop", sites=[Site(members=[0, 1])]))
    assert status(kb, fr, IT_TAKES_TWO) == PASS
    assert status(kb, fr, DEEP_ROCK) == FAIL              # no local mode
    fr = hard_filter(kb, group(2, interaction="coop", setup_hint="remote"))
    assert status(kb, fr, IT_TAKES_TWO) == PASS           # Remote Play Together category
    assert status(kb, fr, DEEP_ROCK) == FAIL


def test_description_count_only_passes(kb):
    # Stardew: local category, IGDB has no local count, the store description says up to 8. That number is its
    # online count (split screen is 4), and the game also has online co-op, so for a local setup it is not proof
    fr = hard_filter(kb, group(4, interaction="coop", sites=[Site(members=[0, 1, 2, 3])]))
    assert status(kb, fr, STARDEW) == UNKNOWN
    assert fr.setups["local"].max_players[STARDEW][1] == "商店介绍"
    assert "未说明是哪种模式" in fr.setups["local"].reason[STARDEW]


def test_entitlements(kb):
    members = [Member(name="A", library=Library(owned={IT_TAKES_TWO: 10})), Member(name="B")]
    fr = hard_filter(kb, SessionSpec(members=members, interaction="coop", setup_hint="remote"))
    plan = fr.setups["remote"].plan[IT_TAKES_TWO]
    assert plan["rule"] == "host_only" and plan["new_copies"] == 0
    fr = hard_filter(kb, SessionSpec(members=members, interaction="coop", sites=[Site(members=[0]), Site(members=[1])]))
    plan = fr.setups["online"].plan[IT_TAKES_TWO]
    assert plan["rule"] == "per_player" and plan["buyers"] == [1]
    fr = hard_filter(kb, SessionSpec(members=members, interaction="coop", sites=[Site(members=[0, 1])]))
    assert fr.setups["local"].plan[IT_TAKES_TWO]["new_copies"] == 0  # one machine, A owns it


def test_group_budget(kb):
    fr = hard_filter(kb, group(4, interaction="coop", budget=Budget(amount=1),
                               sites=[Site(members=[i]) for i in range(4)]))
    assert status(kb, fr, DEEP_ROCK) == FAIL
    assert "预算" in fr.setups["online"].reason[DEEP_ROCK]
    for a in kb.appids[fr.status == PASS][:50]:
        assert kb.is_free[int(a)]


def test_single_user_rules(kb):
    lib = Library(owned={HADES: 50, STARDEW: 0})
    fr = hard_filter(kb, SessionSpec(members=[Member(library=lib)], budget=Budget(amount=30)))
    assert status(kb, fr, HADES) == FAIL                  # played on Steam
    assert status(kb, fr, STARDEW) == PASS                # owned, no Steam playtime: allowed, costs 0
    assert status(kb, fr, ROCKET_LEAGUE) == FAIL          # not sold in CN
    fr = hard_filter(kb, SessionSpec(members=[Member(library=Library(owned={ROCKET_LEAGUE: 0}))]))
    assert status(kb, fr, ROCKET_LEAGUE) == PASS          # owners are not affected by the region block


def test_hidden_playtime_excludes_nothing(kb):
    lib = Library(owned={HADES: 0, STARDEW: 0}, playtime_hidden=True)
    fr = hard_filter(kb, SessionSpec(members=[Member(library=lib)]))
    assert status(kb, fr, HADES) == PASS


def test_avoid_and_language(kb):
    horror = [int(t) for t, n in kb.tag_en.items() if n == "Horror"]
    m = Member(avoid_tags=horror, avoid_content=["gore"], language="schinese")
    fr = hard_filter(kb, SessionSpec(members=[m]))
    bad = [i for i, a in enumerate(kb.appids) if set(horror) & kb.tagset.get(int(a), set())]
    assert (fr.status[bad] == FAIL).all()
    langs = kb.games["language_codes"]
    for i, a in enumerate(kb.appids[:300]):
        if len(langs[a]) and 6 not in set(langs[a]):
            assert fr.status[i] == FAIL


def test_three_valued_min(kb):
    fr = hard_filter(kb, group(6, interaction="coop", sites=[Site(members=[i]) for i in range(6)]))
    vals = set(np.unique(fr.status).tolist())
    assert vals <= {FAIL, UNKNOWN, PASS} and UNKNOWN in vals
    assert status(kb, fr, TERRARIA) == PASS
