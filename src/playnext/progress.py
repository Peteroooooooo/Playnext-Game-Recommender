"""Live step events for the streamed API (api.py, ?stream=1): the pipeline marks where it is, a listener set by the
caller receives {"step": name, "state": "start" | "done" | "skip"}. Without a listener every call does nothing.
Steps: understand (LLM) -> pick (rules + scoring) -> rerank (LLM, skipped when there is nothing to compare) ->
prices (ranking + live prices)."""
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Callable

_listener: ContextVar[Callable[[dict], None] | None] = ContextVar("playnext_progress", default=None)


@contextmanager
def listen(fn: Callable[[dict], None]):
    tok = _listener.set(fn)
    try:
        yield
    finally:
        _listener.reset(tok)


def _emit(step: str, state: str):
    fn = _listener.get()
    if fn is not None:
        fn({"step": step, "state": state})


def start(step: str):
    _emit(step, "start")


def done(step: str):
    _emit(step, "done")


def skip(step: str):
    _emit(step, "skip")
