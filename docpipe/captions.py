"""
captions.py: Defines what a caption looks like, and finds where a table's
title really sits.

Stage 2 links a caption block to a table by distance, and in a plan whose
tables carry a rounding footnote it links the footnote instead. The
sentence that names the table then stands unlinked in the section text, a
few words before the table's own placeholder. Measured over Kassel, 15 of
89 tables were captioned with the rounding footnote's own sentence rather
than their real title.

Both ends of the pipeline need the same rule about that: Stage 3, which
assembles the section text when the placeholder is written, and the read
side, which has only the finished database. A second copy of the rule is
how the section text and the stored title start disagreeing, the defect
this module exists to fix. So the rule lives above both.

Author: Felix Vossel
"""
from __future__ import annotations

import os
import re

from .profile import ENV_VAR, load_profile


# A placeholder as Stage 3 writes it: [p85_tbl0], [p17_img1].
_ITEM_PLACEHOLDER = re.compile(r"\[p\d+_(?:tbl|img)\d+\]")
# Past this a "caption" is a paragraph that happens to start with one.
_CAPTION_LIMIT = 300

# How a caption opens is a fact about the language a corpus is written in,
# so the core holds no pattern of it. The profile lists them in
# `preprocessing.CAPTION_START`, each with its own anchor, and a text opens a
# caption when any of them matches. Compiled once per profile.
_openers: dict = {}


def _compile(name: str, patterns) -> "re.Pattern":
    """One pattern out of a profile's list. A list that is empty would match
    every text, so would an empty pattern among the others, and a bare string
    would be read letter by letter; all three are the profile's mistake and
    are said so."""
    if (not isinstance(patterns, (list, tuple)) or not patterns
            or not all(isinstance(each, str) for each in patterns)):
        raise ValueError(
            f"profile {name!r}: preprocessing.CAPTION_START must be a "
            f"non-empty list of patterns, got {patterns!r}")
    try:
        opener = re.compile("|".join(f"(?:{each})" for each in patterns))
    except re.error as exc:
        raise ValueError(f"profile {name!r}: a pattern of "
                         f"preprocessing.CAPTION_START does not compile: "
                         f"{exc}") from exc
    if opener.match(""):
        raise ValueError(
            f"profile {name!r}: a pattern of preprocessing.CAPTION_START "
            f"matches the empty text, so every text would open a caption: "
            f"{patterns!r}")
    return opener


def _caption_start() -> "re.Pattern":
    """What opens a caption under the profile in force. Where none is named,
    the read side still runs, on the profile the package brings itself."""
    name = os.environ.get(ENV_VAR) or "default"
    if name not in _openers:
        profile = load_profile(name)
        _openers[name] = _compile(
            profile.name, profile.require("preprocessing", "CAPTION_START"))
    return _openers[name]


def looks_like_a_caption(text) -> bool:
    """Does this text open the way a caption opens?"""
    return bool(_caption_start().match((text or "").strip()))


def resolve_title(caption, content, block_id) -> str:
    """The caption of one table or figure, from the section that holds it.

    Stage 2 links a caption block to an item by distance, and in a plan whose
    tables carry a rounding footnote it links the footnote: measured over
    Kassel, 15 of 89 tables were captioned "Hinweis: Wegen der Rundung von
    Zahlenwerten ..." while the sentence that names them stood unlinked in the
    section text, three words before their own placeholder. The consequence
    was not cosmetic. The caption is the only line of a table a model can
    quote for the table's own year, so 240 of 379 tuples from the twelve
    titled target tables carried a year read off another table's caption, and
    88 of Kassel's 100 contested value identities were that.

    The sentence is taken from between the PREVIOUS item's placeholder and
    this one's, because that is where a caption sits and everything before
    the previous placeholder belongs to the previous item. A stored caption
    that already opens like a caption is never replaced: it was linked, and a
    link beats a guess.
    """
    if looks_like_a_caption(caption):
        return caption
    if not content or not block_id:
        return caption
    at = content.find(f"[{block_id}")
    if at == -1:
        return caption
    before = content[:at]
    ends = [m.end() for m in _ITEM_PLACEHOLDER.finditer(before)]
    tail = before[ends[-1]:] if ends else before
    starts = list(_caption_start().finditer(tail))
    if not starts:
        return caption
    title = tail[starts[-1].start():].strip()
    # Where the caption ends is not always where the placeholder starts. In a
    # plan whose text layer was transcribed page by page, the caption and the
    # paragraph after it are one run and the placeholder follows the
    # paragraph: measured over the three textless plans of the corpus (795
    # Leipzig, 1082 Grevesmuehlen, 210 VG Maikammer), 23 of 169 tables
    # resolved a title and one of them carried 60 characters of prose behind
    # it. When Stage 2 stored a caption of its own -- the vision model's
    # reading of the same line -- and the document's sentence contains it,
    # that is where the caption ends.
    stored = (caption or "").strip()
    if stored and stored in title:
        title = title[:title.index(stored) + len(stored)]
    return title[:_CAPTION_LIMIT] if title else caption
