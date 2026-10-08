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

A profile contributes them in `profiles/<name>/extraction.py: PHRASES`. A
profile that extends another one writes only the ones it words differently.
A phrase is a template for `str.format`: the names in braces are filled by
the stage, `!r` shows a value the way the model wrote it, and a brace that
is meant as a brace is doubled.

Author: Felix Vossel
"""
from __future__ import annotations

from typing import Optional

from ..profile import ENV_VAR, Profile, active_profile

# Checked as a set when first read: a profile that forgets one hears about
# it before the first request, not when that sentence is first needed.
REQUIRED = frozenset({
    "option_means", "option_spellings", "unstated_means",
    "unstated_spelling",
    "kind_whole_number", "kind_text", "not_an_option", "wrong_type",
    "quote_not_in_source", "quote_too_short", "answer_not_in_quote",
    "frame_missing", "frame_no_quote", "frame_quote_not_in_source",
    "frame_answer_not_in_quote", "frame_not_an_option", "frame_not_a_year",
    "frame_options",
    "shape_rule", "cut_off", "shorter", "shorter_frame", "shorter_rows",
    "shorter_field", "shorter_review", "reasoning_only", "empty",
    "no_object", "syntax", "outside_text", "not_an_object", "key_missing",
    "key_not_a_list", "wrong_shape",
    "code_failed", "code_error_unknown", "code_silent", "code_output",
    "image_for", "anchor_parameter", "anchor_unit",
})

_checked: dict = {}


def phrases(profile: Optional[Profile] = None) -> dict:
    """The profile's sentences, complete. Read once per profile."""
    profile = profile or active_profile()
    if profile is None:
        raise LookupError(f"the extraction stage needs a profile; set "
                          f"${ENV_VAR}")
    if profile.name in _checked:
        return _checked[profile.name]
    nearest = profile.require("extraction", "PHRASES")
    got: dict = {}
    for layer in reversed(profile.layers("extraction", "PHRASES")[1:]):
        got.update(layer)                   # those of the profiles it extends
    got.update(nearest)
    missing = sorted(REQUIRED - set(got))
    if missing:
        raise LookupError(f"extraction.PHRASES of profile {profile.name!r} "
                          f"is missing {missing}")
    _checked[profile.name] = got
    return got


def say(phrase: str, /, **values) -> str:
    """One sentence of the ambient profile, with its names filled in."""
    text = phrases()[phrase]
    return text.format(**values) if values else text
