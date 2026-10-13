"""How fast can we call the Steam reviews endpoint before HTTP 429?

Pages through one popular game's reviews with no pause between requests (one request at a time),
up to MAX requests; stops at the first non-200 and then checks every 20 s when access returns.
Prints only counts and timings.
Usage: uv run python scripts/rate_limit_probe.py
"""
import time
import urllib.parse

from check_keys import request

APP, MAX = 1145360, 300


def main():
    cursor, t0, n, lat = "*", time.time(), 0, []
    while n < MAX:
        q = urllib.parse.urlencode({"json": 1, "filter": "recent", "language": "all", "review_type": "all",
                                    "purchase_type": "all", "num_per_page": 100, "cursor": cursor})
        t = time.time()
        st, d = request(f"https://store.steampowered.com/appreviews/{APP}?{q}")
        lat.append(time.time() - t)
        n += 1
        if st != 200 or not isinstance(d, dict):
            el = time.time() - t0
            print(f"first refusal: HTTP {st} at request {n}, after {el:.0f}s ({(n - 1) / el:.2f} req/s sustained)", flush=True)
            t1 = time.time()
            while time.time() - t1 < 600:
                time.sleep(20)
                st2, _ = request(f"https://store.steampowered.com/appreviews/{APP}?json=1&num_per_page=1")
                if st2 == 200:
                    print(f"access back after {time.time() - t1:.0f}s", flush=True)
                    break
            else:
                print("still refused after 600s", flush=True)
            return
        cursor = d.get("cursor") or "*"
    el = time.time() - t0
    print(f"{n} requests, no refusal, {el:.0f}s, {n / el:.2f} req/s, median latency {sorted(lat)[len(lat) // 2]:.2f}s")


if __name__ == "__main__":
    main()
