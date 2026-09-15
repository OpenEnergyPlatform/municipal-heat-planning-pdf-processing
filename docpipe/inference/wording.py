"""
wording.py – What the answer loop says around the prompts.

The prompts belong to the profile; so does everything the loop wraps around
them — the heading over the user's task, the labels inside the history block,
the sentence that tells the model to answer NOW. The core assembles those
pieces and does not write them: it cannot know whether the reader is holding a
German heat plan or an English scenario study.

A profile contributes them in `profiles/<name>/inference.py`.

Author: Felix Vossel
"""
from __future__ import annotations

from typing import Optional

from ..profile import ENV_VAR, Profile, active_profile

# Checked as a set at load time: a profile that forgets one should hear about
# it when the stage is imported, not three hours into a batch.
REQUIRED = frozenset({
    "task_heading", "history_heading", "history_task", "history_phrase",
    "history_answer", "empty_reply", "parse_error",
    "code_heading", "exec_stdout", "exec_empty", "exec_failed",
    "exec_unknown", "exec_recover",
    "compute_heading", "compute_guide", "compute_guide_final",
    "image_heading", "image_uncaptioned", "image_unavailable",
    "image_guide", "image_guide_final", "image_part", "readoff_heading",
    "citation_quotes", "citation_page", "citation_page_unknown",
    "citation_section", "citation_table", "citation_figure",
})


def _component(attr: str, profile: Optional[Profile] = None):
    profile = profile or active_profile()
    if profile is None:
        raise LookupError(f"the answer loop needs a profile; set ${ENV_VAR}")
    return profile.require("inference", attr)


_checked: dict = {}


def phrases(profile: Optional[Profile] = None) -> dict:
    """The profile's labels and guides, complete.

    Cached: citation_label asks once per retrieval hit, and the completeness
    check has nothing new to say the second time.
    """
    profile = profile or active_profile()
    key = profile.name if profile is not None else None
    if key in _checked:
        return _checked[key]
    got = _component("PHRASES", profile)
    missing = sorted(REQUIRED - set(got))
    if missing:
        raise LookupError(f"inference.PHRASES is missing {missing}")
    _checked[key] = got
    return got


def readoff(profile: Optional[Profile] = None) -> tuple:
    """(marker, note) for values the model read off a figure.

    The note is appended unless the answer already says so itself, and the
    marker is how that is recognised — both in the answer's own language.
    """
    return _component("READOFF_MARKER", profile), _component("READOFF_NOTE", profile)
