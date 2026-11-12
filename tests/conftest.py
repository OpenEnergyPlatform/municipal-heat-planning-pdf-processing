"""The profile every test reads its spec, wording and decimal mark from,
and the stand-in for a model that answers in turn."""
import os

import pytest

os.environ.setdefault("DOCPIPE_PROFILE", "kwp")

_NO_REPLY = object()


def step_node(kind: str, ident: str = "x") -> dict:
    """A step of *kind* as a flow draws it: a step of "Ask the model" with
    the preset of that name, else the box of the library of that name
    (owner decision 2026-11-12 evening: every question is "Ask the
    model")."""
    from docpipe.extraction import blocks
    from docpipe.extraction.presets import PRESETS
    blocks.LIBRARY.get("ask")           # the profiles' presets are read
    if kind in PRESETS:
        return {"id": ident, "box": "ask", "preset": kind}
    return {"id": ident, "box": kind}


def in_turn(said, what: str = "the model"):
    """A callable giving the replies *said* one by one. Asked once more
    than the test gave replies, it ends the test as failed: `pytest.fail`
    passes through the code's `except Exception`, which takes any other
    exception without a status for the server's failure and asks again
    without end (owner decision 2026-11-09), so a stand-in that ran dry
    would loop until the machine's memory is gone."""
    told = iter(said)
    count = len(said)

    def next_reply():
        got = next(told, _NO_REPLY)
        if got is _NO_REPLY:
            pytest.fail(f"{what} was asked more often than the test gave it "
                        f"replies ({count})", pytrace=False)
        return got

    return next_reply
