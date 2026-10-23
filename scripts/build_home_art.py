"""Home-screen backdrop list: the most-reviewed core games that have Steam hero art (web redesign, design 10.14).

Takes core games by Steam review count, drops those with a sexual-content descriptor (Steam content descriptors
1 / 3 / 4, as rules.SEXUAL_DESCRIPTORS), and keeps the first config.HOME_ART_COUNT whose library_hero.jpg exists on
the Steam CDN (checked with a HEAD request; no key, no user data). Gore and horror stay in.
Writes web/src/home_art.json: [appid, ...] in review-count order; the page shuffles it.
Usage: uv run python scripts/build_home_art.py
"""
import json
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from playnext import config as C  # noqa: E402
from playnext.kb import KB  # noqa: E402
from playnext.rules import SEXUAL_DESCRIPTORS  # noqa: E402

OUT = C.ROOT / "web" / "src" / "home_art.json"
HERO = "https://cdn.akamai.steamstatic.com/steam/apps/{}/library_hero.jpg"


def has_hero(appid: int) -> bool:
    req = urllib.request.Request(HERO.format(appid), method="HEAD", headers={"User-Agent": "playnext-build"})
    for _ in range(3):
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.status == 200 and int(r.headers.get("Content-Length") or 1) > 0
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return False
        except (urllib.error.URLError, TimeoutError):
            pass
    return False


def main():
    kb = KB()
    order = np.argsort(-kb.review_count, kind="stable")
    cand = []
    for i in order:
        a = int(kb.appids[i])
        if set(kb.games.at[a, "content_descriptor_ids"]) & SEXUAL_DESCRIPTORS:
            continue
        cand.append(a)
        if len(cand) >= C.HOME_ART_COUNT * 2:
            break
    with ThreadPoolExecutor(8) as ex:
        ok = list(ex.map(has_hero, cand))
    picked = [a for a, h in zip(cand, ok) if h][:C.HOME_ART_COUNT]
    OUT.write_text(json.dumps(picked) + "\n", encoding="utf-8")
    print(f"checked {len(cand)}, with hero art {sum(ok)}, wrote {len(picked)} to {OUT.relative_to(C.ROOT)}")


if __name__ == "__main__":
    main()
