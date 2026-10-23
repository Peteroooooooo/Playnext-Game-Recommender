"""CPU / memory benchmark of the recommendation trunk without the LLM, for sizing a deployment server (design 10.15).

Loads the knowledge base, then times Steps 2-5 (rules, scoring, ranking, cards; snapshot prices, no LLM rerank) for
a few request shapes, one at a time and 4 in parallel, and prints peak memory. Linux and Windows.
Usage: uv run python scripts/bench_server.py
"""
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def rss_mb():
    """(current, peak) resident memory in MB."""
    if sys.platform == "win32":
        import ctypes
        import ctypes.wintypes as w

        class PMC(ctypes.Structure):
            _fields_ = [("cb", w.DWORD), ("faults", w.DWORD), ("peak", ctypes.c_size_t), ("rss", ctypes.c_size_t)] + \
                       [(f"x{i}", ctypes.c_size_t) for i in range(6)]
        p = PMC()
        p.cb = ctypes.sizeof(p)
        k = ctypes.windll.kernel32
        k.GetCurrentProcess.restype = ctypes.c_void_p
        f = ctypes.windll.psapi.GetProcessMemoryInfo
        f.argtypes = [ctypes.c_void_p, ctypes.c_void_p, w.DWORD]
        f(k.GetCurrentProcess(), ctypes.byref(p), p.cb)
        return p.rss / 2**20, p.peak / 2**20
    cur = peak = 0.0
    for line in open("/proc/self/status"):
        if line.startswith("VmRSS:"):
            cur = int(line.split()[1]) / 1024
        elif line.startswith("VmHWM:"):
            peak = int(line.split()[1]) / 1024
    return cur, peak


def main():
    from playnext.pipeline import Recommender
    from playnext.spec import Library, Member, SessionSpec, Site
    print(f"cpus {os.cpu_count()}, start rss {rss_mb()[0]:.0f} MB", flush=True)
    t0 = time.time()
    rec = Recommender(llm=None, live_prices=False, reasons=False)
    kb = rec.kb
    print(f"knowledge base loaded in {time.time() - t0:.1f} s, rss {rss_mb()[0]:.0f} MB", flush=True)

    relaxing = next(t for t, n in kb.tag_en.items() if n == "Relaxing")
    top = [int(a) for a in kb.appids[(-kb.review_count).argsort()[:200]]]
    library = Library(owned={a: float(5 + i % 40) for i, a in enumerate(top[:150])})
    shapes = {
        "one seed": lambda: SessionSpec(seeds=[1145360]),
        "two seeds + feel": lambda: SessionSpec(seeds=[1145360, 413150], feel_want=[relaxing]),
        "150-game library": lambda: SessionSpec(members=[Member(name="me", library=library)]),
        "words only": lambda: SessionSpec(preference_text="想找剧情好的游戏"),
        "4 players online co-op": lambda: SessionSpec(members=[Member(name=f"P{i}", seeds=[top[i]]) for i in range(4)],
                                                      interaction="coop", sites=[Site(members=[i]) for i in range(4)]),
    }
    rec.recommend(shapes["one seed"]())  # first call warms caches
    for name, make in shapes.items():
        times = []
        for _ in range(5):
            t = time.time()
            rec.recommend(make())
            times.append(time.time() - t)
        times.sort()
        print(f"{name:<24} median {times[2] * 1000:6.0f} ms   max {times[-1] * 1000:6.0f} ms", flush=True)
    t = time.time()
    with ThreadPoolExecutor(4) as ex:
        list(ex.map(lambda k: rec.recommend(list(shapes.values())[k % len(shapes)]()), range(20)))
    print(f"20 requests, 4 at a time: {time.time() - t:.1f} s total", flush=True)
    cur, peak = rss_mb()
    print(f"rss now {cur:.0f} MB, peak {peak:.0f} MB", flush=True)


if __name__ == "__main__":
    main()
