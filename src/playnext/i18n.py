"""Output language of user-facing text (zh / en), set once per API request.

Text is written next to the code that builds it as L("中文", "English"), so each message keeps both versions in one
place. The language lives in a context variable: FastAPI runs each sync endpoint in a worker thread with its own
copy of the context, so concurrent requests do not see each other's language. Worker pools started inside a
request do not inherit it; submit work there through `carry`.
"""
from contextvars import ContextVar, copy_context
from typing import Literal

Lang = Literal["zh", "en"]
LANGS = ("zh", "en")
_lang: ContextVar[str] = ContextVar("playnext_lang", default="zh")


def set_lang(lang: str | None) -> None:
    _lang.set(lang if lang in LANGS else "zh")


def lang() -> str:
    return _lang.get()


def L(zh: str, en: str) -> str:
    return en if _lang.get() == "en" else zh


def sep() -> str:
    """List separator: "、" in Chinese, ", " in English."""
    return ", " if _lang.get() == "en" else "、"


def carry(fn):
    """fn bound to the caller's context, for ThreadPoolExecutor.map / submit inside a request."""
    ctx = copy_context()
    return lambda *a, **k: ctx.copy().run(fn, *a, **k)
