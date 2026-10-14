"""Run one or more requests through the full system (LLM understanding, query encoder, live prices, LLM reasons).
Usage: uv run python scripts/try_request.py "我以前沉迷《文明6》和《星露谷》，今晚想找类似的轻松游戏，60 块以内" ["follow-up" ...]
Later arguments are follow-ups (Step 6 patches) on the first request."""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from playnext.encoder import Encoder  # noqa: E402
from playnext.llm import LLM  # noqa: E402
from playnext.pipeline import Recommender  # noqa: E402


def show(res):
    print(json.dumps(res.understood, ensure_ascii=False))
    for r in res.rules:
        print("  rule", r)
    for n in res.notes:
        print("  note", n)
    for c in res.picks:
        print(f"  * {c['name']}  [{c['price']['text']}]  {c['rating']['text']}")
        if c.get("setup"):
            print(f"      {c['setup'].get('mode_text')} | {c['setup'].get('purchase')}")
        print(f"      {c['reason']}  ({c['reason_source']})")
        if c["like"].get("quote"):
            print(f"      介绍原句：{c['like']['quote']}")
    print("  backups:", [b["name"] for b in res.backups[:8]])
    print("  unknown:", res.unknown)
    if res.relax:
        print("  relax:", json.dumps(res.relax, ensure_ascii=False))
    if res.need_input:
        print("  need:", res.need_input)
    print("  timings:", res.timings)


def main():
    t0 = time.time()
    rec = Recommender(llm=LLM(), encoder=Encoder(), live_prices=True)
    print(f"ready {time.time() - t0:.1f}s")
    texts = sys.argv[1:]
    parsed, res = rec.ask(texts[0])
    show(res)
    for t in texts[1:]:
        print(f"\n--- follow-up: {t}")
        parsed, res = rec.ask(t, base=res.spec, parsed=parsed)
        show(res)


if __name__ == "__main__":
    main()
