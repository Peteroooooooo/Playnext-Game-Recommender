import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from playnext.kb import KB  # noqa: E402
from playnext.pricing import Prices  # noqa: E402

IT_TAKES_TWO, DEEP_ROCK, STARDEW, HADES, AMONG_US, TERRARIA, CIV6 = 1426210, 548430, 413150, 1145360, 945360, 105600, 289070
ROCKET_LEAGUE = 252950  # not sold in the CN store


@pytest.fixture(scope="session")
def kb():
    return KB()


@pytest.fixture(scope="session")
def prices(kb):
    return Prices(kb, live=False)


class FakeLLM:
    """Returns queued replies; records calls."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def chat(self, system, user, purpose="", temperature=0):
        self.calls.append((purpose, user))
        return self.replies.pop(0)
