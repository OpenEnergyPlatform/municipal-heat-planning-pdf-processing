"""
reading.py: The one JSON object a stage asked a model for, or why there is none.

Refinement, the visuals stage and page transcription ask for a JSON object
inside a reply schema. What comes back is read here, and read strictly: the
reply is that object and nothing else. Nothing is stripped (code fences, think
blocks), nothing is cut out of surrounding text, no bracket is closed, and
nothing is salvaged from a reply that was cut off. Every softener of that kind
turned a defective answer into content that then stood in a file as if it had
been read. A reply that is not exactly the object is classified instead, and
the stage asks again with the cause named (`say`), splits the request when the
reply was cut off, or ends the unit as a `Hole` that carries the cause.

The causes are the harvest's (`extraction.runner._reply_fault`), in its order;
a test holds the two against each other, so neither can drift. The harvest does
not call this module: it keeps its own reader and its own sentences.

The sentences the model hears are the profile's, in the language of that
profile's prompts for these stages (`profiles/<name>/reading.py: PHRASES`).

Author: Felix Vossel
"""
from __future__ import annotations

import contextlib
import contextvars
import json
from dataclasses import dataclass
from typing import Optional

from .profile import ENV_VAR, Profile, active_profile

# Why a reply is not the object that was asked for. `wrong_shape` is the
# label of an object that was read well and is no use to the stage (a window
# whose list holds no section); `read` itself never gives it.
CAUSES = ("cut_off", "reasoning_only", "empty", "no_object", "syntax",
          "outside_text", "not_an_object", "missing_key", "wrong_shape")

# Why a unit ended without a result: a cause above, the server refusing the
# request itself (a 4xx), the server not answering at all, or an error of the
# stage's own after the reply had arrived.
HOLE_CAUSES = CAUSES + ("refused", "not_served", "error")


@dataclass(frozen=True)
class Hole:
    """A unit (a window, a cut request, an item, a page) that has no result,
    and the reason it has none. *detail* is for the log, not for a decision."""
    cause: str
    detail: str = ""

    def __post_init__(self) -> None:
        if self.cause not in HOLE_CAUSES:
            raise ValueError(f"{self.cause!r} is no cause of a hole; one of: "
                             f"{', '.join(HOLE_CAUSES)}")


# Checked as a set when first read: a profile that forgets one hears about it
# before the first request, not when that sentence is first needed.
REQUIRED = frozenset({
    "shape_rule", "reasoning_only", "empty", "no_object", "syntax",
    "outside_text", "not_an_object", "key_missing", "key_not_a_list",
    "key_not_text",
})

_checked: dict = {}

# The profile that speaks where none is in force. The stages that write a
# corpus stop without a profile; the chat does not, it answers on the built-in
# one, and says so (`inference.wording.chat_profile`).
_SPEAKER: contextvars.ContextVar = contextvars.ContextVar(
    "reading_profile", default=None)


@contextlib.contextmanager
def speaking(profile: Profile):
    """Inside the block the sentences are *profile*'s, where a caller has a
    profile that is not the ambient one. A profile that is in force still
    speaks for the calls that name none outside the block."""
    token = _SPEAKER.set(profile)
    try:
        yield
    finally:
        _SPEAKER.reset(token)


def phrases(profile: Optional[Profile] = None) -> dict:
    """The profile's sentences, complete. Read once per profile."""
    profile = profile or _SPEAKER.get() or active_profile()
    if profile is None:
        raise LookupError(f"reading a model's reply needs a profile; set "
                          f"${ENV_VAR}")
    if profile.name in _checked:
        return _checked[profile.name]
    nearest = profile.require("reading", "PHRASES")
    got: dict = {}
    for layer in reversed(profile.layers("reading", "PHRASES")[1:]):
        got.update(layer)                   # those of the profiles it extends
    got.update(nearest)
    missing = sorted(REQUIRED - set(got))
    if missing:
        raise LookupError(f"reading.PHRASES of profile {profile.name!r} "
                          f"is missing {missing}")
    _checked[profile.name] = got
    return got


def say(phrase: str, /, **values) -> str:
    """One sentence of the ambient profile, with its names filled in."""
    text = phrases()[phrase]
    return text.format(**values) if values else text


def loads_object(text) -> Optional[dict]:
    """The one JSON object a reply was asked for, or None.

    Whitespace around it is no text. Anything else around it, a fence, a think
    block, a second object, prose, is not this object.
    """
    text = (text or "").strip()
    if not text:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def first(response):
    """The first choice of a response; None when it carries none."""
    choices = getattr(response, "choices", None)
    return choices[0] if choices else None


_DECODER = json.JSONDecoder()


def _shape() -> str:
    """What is said back whatever went wrong: the shape that was asked for.
    Looked up when a reply failed, so a reply that is fine needs no table."""
    return say("shape_rule")


_KEY_NOT = {list: "key_not_a_list", str: "key_not_text"}


def read(choice, key: Optional[str] = None, of: type = list) -> tuple:
    """(object, "", "") for a reply that is exactly one JSON object; else
    (None, cause, sentence) for the retry.

    *key*, when given, has to be in the object as an instance of *of* (a list
    for a window's sections, text for a table's markdown). The sentence is
    empty for a reply that was cut off: that reply is never asked again as it
    stands, the stage splits the request or gives the unit more room.

    *choice* is the first choice of a response (`first`), None for a response
    without one, which is an empty reply.
    """
    message = getattr(choice, "message", None)
    content = getattr(message, "content", None)
    text = content.strip() if isinstance(content, str) else ""
    thought = getattr(message, "reasoning_content", None)
    thought = thought.strip() if isinstance(thought, str) else ""
    ran_out = getattr(choice, "finish_reason", None) == "length"

    data = loads_object(text)
    if data is not None:
        # Present first: for `of=object` (a key of any kind) a missing key
        # would otherwise be the None that `.get` hands back, an instance of
        # object, and a reply without its answer would read as one.
        if key is None or (key in data and isinstance(data[key], of)):
            return data, "", ""
        which = "key_missing" if key not in data else _KEY_NOT[of]
        return None, "missing_key", say(which, key=key) + _shape()

    if not text and thought:
        # The answer went into the think block and the reply stayed empty.
        return None, "reasoning_only", say("reasoning_only") + _shape()
    if not text:
        return ((None, "cut_off", "") if ran_out
                else (None, "empty", say("empty") + _shape()))
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        # A reply that ran into its limit is unreadable BECAUSE it was cut, so
        # its syntax error is the consequence and not the cause.
        if ran_out:
            return None, "cut_off", ""
        start = text.find("{")
        if start == -1:
            return None, "no_object", say("no_object") + _shape()
        try:
            _obj, end = _DECODER.raw_decode(text, start)
        except json.JSONDecodeError:
            around = text[max(start, exc.pos - 60):exc.pos + 20]
            return None, "syntax", say(
                "syntax", position=exc.pos - start, message=exc.msg,
                around=around) + _shape()
        extra = (text[:start] + text[end:]).strip()
        return None, "outside_text", say("outside_text",
                                         extra=extra[:200]) + _shape()
    # It parsed, and `loads_object` did not take it: not an object.
    return None, "not_an_object", say(
        "not_an_object", kind=type(parsed).__name__) + _shape()
