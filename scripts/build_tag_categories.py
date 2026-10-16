"""Sort the 446 Steam tags into gameplay / theme / mood / other, once (design 5.3 step 6, 6.2, 6.3).

The LLM gets the tags in batches of ~80 (tagid | English name | Chinese name; only tag names are sent) at
temperature 0. Every reply must cover each tagid of its batch exactly once with one of the four values; a bad reply
is retried once with the error, then the run stops. OVERRIDES, checked by hand against the full list, is applied
last and wins.
Writes data/processed/tag_categories.parquet: tagid, category (final), llm_category (the LLM's answer).
Usage: uv run python scripts/build_tag_categories.py              ask the LLM, apply OVERRIDES, write
       uv run python scripts/build_tag_categories.py overrides    re-apply OVERRIDES to the stored LLM answers
"""
import sys

import numpy as np
import pandas as pd

from check_keys import ROOT

sys.path.insert(0, str(ROOT / "src"))
from playnext.llm import LLM, chat_json  # noqa: E402

PROC = ROOT / "data" / "processed"
OUT = PROC / "tag_categories.parquet"
CATS = ("gameplay", "theme", "mood", "other")
BATCH = 80

SYSTEM = """You sort Steam user tags into four groups for a game recommender. Every tag goes into exactly one group.
- gameplay: what the player does and how the game plays. Genres and sub-genres (RPG, Roguelike, FPS, Puzzle, Platformer, Souls-like, Visual Novel, Strategy), mechanics and systems (Deckbuilding, Base Building, Crafting, Turn-Based Combat, Stealth, Physics, Procedural Generation, Open World, Loot), structure (Linear, Nonlinear, Choices Matter, Multiple Endings, Story Rich), camera and viewpoint (First-Person, Third Person, Isometric, Side Scroller, Top-Down, 2D, 3D), and the activity or sport that is played (Driving, Fishing, Farming, Cooking, Golf, Football (Soccer)).
- theme: what the game is about. Setting, world, era, subject matter, creatures and characters (Fantasy, Sci-fi, Zombies, Medieval, Space, Cyberpunk, Post-apocalyptic, World War II, Pirates, Dragons, Mythology, Crime, Romance, Horror, Female Protagonist, Robots, Cats).
- mood: how the game feels. Tone, emotion, pace, difficulty and visual look (Relaxing, Cozy, Dark, Atmospheric, Funny, Emotional, Wholesome, Cute, Difficult, Unforgiving, Fast-Paced, Surreal, Epic, Pixel Graphics, Hand-drawn, Colorful, Beautiful, Minimalist).
- other: anything that is not about gameplay, theme or mood. Player count and play mode (Singleplayer, Multiplayer, Co-op, Online Co-Op, Local Co-Op, Split Screen, PvP, PvE, Massively Multiplayer), business and release status (Indie, Early Access, Free to Play, Sequel, Remake, Episodic, Classic), praise and verdicts (Great Soundtrack, Masterpiece, Addictive, Replay Value, Short), hardware and platform features (VR, Controller, TrackIR, Moddable, Mouse Only), content warnings (Nudity, Sexual Content, Gore, Violent, Blood), audience (Kids, Family Friendly), and non-game software (Utilities, Video Production, Design & Illustration, Benchmark).
When a tag could fit two groups, pick the one a player usually means when asking for it."""
USER = ('Tags (tagid | English | Chinese):\n{rows}\n\nReturn only a JSON object mapping every tagid above (as a string) '
        'to "gameplay", "theme", "mood" or "other", e.g. {{"1716": "gameplay", "1684": "theme"}}.')

# Hand check of the LLM answers (2026-10-16), applied last.
OVERRIDES = {
    597: "mood",       # Casual (LLM: gameplay): design 5.5 lists 休闲 with 放松 / 温馨惬意 as a feel tag ("想玩点轻松的")
    3854: "theme",     # Lore-Rich (LLM: gameplay): about the world, not how the game plays
    7108: "gameplay",  # Party (LLM: theme): Jackbox-style party games, same meaning as Party Game
    42089: "mood",     # Jump Scare (LLM: other): a scare device, how the game feels, not a content rating
    150626: "other",   # Gaming (LLM: theme): 5 games, none as a core tag, no shared meaning
}


def ask(llm, batch):
    want = {str(t) for t in batch["tagid"]}

    def validate(obj):
        if not isinstance(obj, dict):
            raise ValueError("expected a JSON object")
        got = {str(k).strip(): str(v).strip().lower() for k, v in obj.items()}
        missing, extra = want - set(got), set(got) - want
        if missing or extra:
            raise ValueError(f"tagids missing {sorted(missing)[:20]}, unexpected {sorted(extra)[:20]}")
        bad = {k: v for k, v in got.items() if v not in CATS}
        if bad:
            raise ValueError(f"values must be one of {CATS}; got {dict(list(bad.items())[:10])}")
        return {int(k): v for k, v in got.items()}

    rows = "\n".join(f"{t} | {en.strip()} | {zh if isinstance(zh, str) else ''}"
                     for t, en, zh in batch[["tagid", "name_en", "name_zh"]].itertuples(index=False))
    return chat_json(llm, SYSTEM, USER.format(rows=rows), purpose="tag_categories", validate=validate)


def main():
    tags = pd.read_parquet(PROC / "tags.parquet").sort_values("tagid").reset_index(drop=True)
    if sys.argv[1:] == ["overrides"]:
        llm_cat = dict(zip(*pd.read_parquet(OUT)[["tagid", "llm_category"]].to_numpy().T))
    else:
        llm, llm_cat = LLM(), {}
        n_batches = -(-len(tags) // BATCH)
        for i, idx in enumerate(np.array_split(np.arange(len(tags)), n_batches)):
            llm_cat.update(ask(llm, tags.iloc[idx]))
            print(f"batch {i + 1}/{n_batches}: {len(idx)} tags ({llm.calls[-1][1]} s)")
    assert set(llm_cat) == set(tags["tagid"]), "LLM answers do not cover every tag"
    unknown = set(OVERRIDES) - set(tags["tagid"])
    assert not unknown and set(OVERRIDES.values()) <= set(CATS), f"bad OVERRIDES entries {unknown}"

    df = pd.DataFrame({"tagid": tags["tagid"].astype("int64"),
                       "category": [OVERRIDES.get(t, llm_cat[t]) for t in tags["tagid"]],
                       "llm_category": [llm_cat[t] for t in tags["tagid"]]})
    df.to_parquet(OUT, index=False)

    name = dict(zip(tags["tagid"], tags["name_en"].str.strip()))
    changed = df[df["category"] != df["llm_category"]]
    print(f"overrides changed {len(changed)} of {len(OVERRIDES)} listed: "
          + ", ".join(f"{name[t]} {a}->{b}" for t, a, b in changed[["tagid", "llm_category", "category"]].itertuples(index=False)))
    for c in CATS:
        sub = df[df["category"] == c]
        print(f"\n{c} ({len(sub)}): " + "; ".join(name[t] for t in sub["tagid"]))
    print(f"\nwrote {OUT.relative_to(ROOT)}: {df['category'].value_counts().reindex(list(CATS)).to_dict()}")


if __name__ == "__main__":
    main()
