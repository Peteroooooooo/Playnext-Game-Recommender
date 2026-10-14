"""Quick end-to-end check of src/playnext without the LLM, the encoder or live prices.
Usage: uv run python scripts/smoke_pipeline.py"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from playnext.pipeline import Recommender  # noqa: E402
from playnext.spec import Budget, Library, Member, SessionSpec, Site  # noqa: E402


def show(title, res):
    print(f"\n== {title}  ({res.timings})")
    for r in res.rules:
        print("   rule", r)
    for n in res.notes:
        print("   note", n)
    for c in res.picks:
        print(f"   {c['name']:<40} rel {c['relevance']:.2f}  {c['price']['text']}  {c.get('setup', {}) and c['setup'].get('mode_text')}"
              f"  | {c['reason'][:70]}")
        if c.get("setup"):
            print("        ", c["setup"].get("purchase"))
    print("   backups", [b["name"] for b in res.backups[:8]])
    print("   unknown", res.unknown)
    if res.relax:
        print("   relax", res.relax)
    if res.need_input:
        print("   need", res.need_input)


def main():
    t0 = time.time()
    rec = Recommender(live_prices=False)
    print(f"kb {time.time() - t0:.1f}s")
    show("seed Hades", rec.recommend(SessionSpec(seeds=[1145360])))
    lib = Library(owned={289070: 300, 413150: 60, 1145360: 80, 1426210: 13, 588650: 0.7, 646570: 0})
    show("library only", rec.recommend(SessionSpec(members=[Member(library=lib)])))
    show("library + seed Hades, budget 100", rec.recommend(SessionSpec(members=[Member(library=lib)], seeds=[1145360],
                                                                       budget=Budget(amount=100))))
    five = [Member(name=n) for n in ["我", "小张", "小李", "小王", "小陈"]]
    five[1].library = Library(owned={548430: 20})  # Deep Rock Galactic
    show("5 online coop like It Takes Two, 50 each",
         rec.recommend(SessionSpec(members=five, seeds=[1426210], interaction="coop", budget=Budget(amount=50),
                                   sites=[Site(members=[i]) for i in range(5)])))
    show("4 local couch", rec.recommend(SessionSpec(members=[Member(name=f"P{i}") for i in range(4)],
                                                    sites=[Site(members=[0, 1, 2, 3])], preference_text=None,
                                                    feel_want=[1664], interaction="any")))
    show("impossible: 9 people local coop budget 5", rec.recommend(SessionSpec(
        members=[Member(name=f"P{i}") for i in range(9)], sites=[Site(members=list(range(9)))], interaction="coop",
        seeds=[1426210], budget=Budget(amount=5))))


if __name__ == "__main__":
    main()
