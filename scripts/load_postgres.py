"""Load the knowledge base into the local PostgreSQL (design 6.2) and print row counts plus a sample path query.
Start the database first: docker compose up -d
Usage: uv run python scripts/load_postgres.py"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from playnext.db import connect, lineage_paths, load  # noqa: E402
from playnext.kb import KB  # noqa: E402


def main():
    t0 = time.time()
    counts = load(KB())
    print(f"loaded in {time.time() - t0:.0f}s:", counts)
    with connect() as conn:
        for src, dst in ((1145360, 237930), (289070, 8930), (1426210, 1222700)):  # Hades->Transistor, Civ6->Civ5, ITT->A Way Out
            t1 = time.time()
            print(src, dst, lineage_paths(conn, src, dst), f"{(time.time() - t1) * 1000:.0f} ms")


if __name__ == "__main__":
    main()
