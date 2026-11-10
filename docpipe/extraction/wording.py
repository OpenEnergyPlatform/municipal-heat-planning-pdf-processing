"""
wording.py: What the extraction stage says to the model outside its prompts.

The prompts belong to the profile, and so does every sentence the stage
writes itself: why an answer was not taken, what was wrong with a reply
that could not be read, what stands beside an image, how the closed list
names a meaning. These go back to the model in the next request, so they
are in the language of the prompts, and the core does not know which that
is. They stood in the core as German sentences, which nobody saw until a
profile wrote its prompts in another language. The two keys of an entry of
a closed list are the exception: they are keys of the request, English in
every profile.

A profile writes them in `profiles/<name>/prompts/extraction/phrases.json`
(`docpipe/phrases.py`; a table in its `extraction.py` until 2026-11-10). A
profile that extends another one writes only the ones it words differently.
A phrase is a template for `str.format`: the names in braces are filled by
the stage, `!r` shows a value the way the model wrote it, and a brace that
is meant as a brace is doubled.

Author: Felix Vossel
"""
from __future__ import annotations

from typing import Optional

from .. import phrases as phrase_files
from ..profile import ENV_VAR, Profile, active_profile

MODULE = "extraction"

# Checked as a set when first read: a profile that forgets one hears about
# it before the first request, not when that sentence is first needed.
REQUIRED = frozenset({
    "option_means", "option_spellings", "unstated_means", "unstated_spelling",
    "kind_whole_number", "kind_year", "kind_text", "not_an_option",
    "name_not_listed", "wrong_type", "quote_not_in_source",
    "quote_not_in_passage", "quote_too_short", "answer_not_in_quote",
    "answer_not_in_quote_text", "or_unstated", "frame_missing",
    "frame_no_quote", "frame_quote_not_in_source", "frame_answer_not_in_quote",
    "frame_not_an_option", "frame_not_a_year", "frame_options", "shape_rule",
    "cut_off", "shorter", "shorter_frame", "shorter_rows", "shorter_field",
    "shorter_review", "reasoning_only", "empty", "no_object", "syntax",
    "outside_text", "not_an_object", "key_missing", "key_not_a_list",
    "wrong_shape", "code_failed", "code_error_unknown", "code_silent",
    "code_output", "image_for", "anchor_parameter", "anchor_unit",
    "value_in_several_rows", "compute_output", "compute_needs_code",
    "not_an_address", "words_not_in_line", "compute_taken",
    "compute_not_taken", "compute_quote", "compute_rejected",
})

# What a comment said above a sentence while the sentences were tables in
# the profiles' modules, each above the sentence it stood before: said once
# here, and shown there by the editor (`docpipe edit`).
NOTES = {
    "option_means": (
        "the closed list as a request shows it: protocol keys, so English "
        "in every profile"),
    "kind_whole_number": "why a coordinate's answer was not taken",
    "answer_not_in_quote": (
        "A correction names every way of answering that passes in the "
        "request (owner decision 2026-11-06): the document's own word as "
        "the wording where the request asks one, the answer as its quote "
        "prints it where the answer is its own wording; \"not stated\" only "
        "where the request offers it, else leaving it out."),
    "frame_options": (
        "The key of the frame request that holds the entries of a closed "
        "frame coordinate, one list per coordinate. The correction below "
        "is handed the key that was sent, so a profile that words this one "
        "phrase differently has moved all of it."),
    "frame_missing": "why a pair of the document's frame was not taken",
    "shape_rule": "a reply that could not be read",
    "not_an_address": "a round of the values of a passage, one value each",
    "code_failed": "what the model gets back after a calculation",
    "image_for": "labels inside a request",
}

_checked: dict = {}


def phrases(profile: Optional[Profile] = None) -> dict:
    """The profile's sentences, complete. Read once per profile."""
    profile = profile or active_profile()
    if profile is None:
        raise LookupError(f"the extraction stage needs a profile; set "
                          f"${ENV_VAR}")
    if profile.name in _checked:
        return _checked[profile.name]
    got = phrase_files.table(profile, MODULE)
    missing = sorted(REQUIRED - set(got))
    if missing:
        raise LookupError(
            f"the extraction sentences of profile {profile.name!r} are "
            f"missing {missing} ({phrase_files.path_of(profile, MODULE)})")
    _checked[profile.name] = got
    return got


def say(phrase: str, /, **values) -> str:
    """One sentence of the ambient profile, with its names filled in."""
    text = phrases()[phrase]
    return text.format(**values) if values else text
