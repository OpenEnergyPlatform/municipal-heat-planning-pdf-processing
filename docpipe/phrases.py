"""
phrases.py: The sentences a stage says to the model outside its prompts, read
from a file beside the profile's prompts.

A prompt is a file of the profile, and so is every sentence a stage writes
itself: why an answer was not taken, what was wrong with a reply that could
not be read, the heading over the user's task. They stood as tables in the
profiles' Python modules (`PHRASES`); since 2026-11-10 they are files, so
that they are edited where the prompts are (`docpipe edit`):

    profiles/<name>/prompts/<module>/phrases.json

one per module that speaks (`MODULES`). A file is one JSON object, the name
of a sentence -> its words, or a list of words where the stage takes several
(the two marks around a citation). A profile that extends another one writes
only the sentences it words differently: its file is laid over those of the
profiles it extends, entry by entry (`table`).

A file is read strictly: one object, every name once, every value a string
or a list of strings. What a sentence is filled with and which ones a stage
cannot run without is the stage's to say (`extraction.wording`,
`inference.wording`, `reading`).

Author: Felix Vossel
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

FILE = "phrases.json"
# The modules that speak outside their prompts, each with a file of its own.
MODULES = ("extraction", "inference", "reading")


class PhrasesError(ValueError):
    """A sentence file a stage cannot read. It names the file."""


def path_of(profile, module: str) -> Path:
    """Where *profile* writes its sentences for *module*."""
    return profile.prompts_dir / module / FILE


def parse(raw: str, where) -> dict:
    """The table the text *raw* writes: name -> words, a list of words as a
    tuple. *where* names the file in what is said about it."""
    def once(pairs: list) -> dict:
        out: dict = {}
        for key, value in pairs:
            if key in out:
                raise PhrasesError(f"{where}: {key!r} stands twice")
            out[key] = value
        return out

    try:
        data = json.loads(raw, object_pairs_hook=once)
    except PhrasesError:
        raise
    except ValueError as exc:
        raise PhrasesError(f"{where}: {exc}") from exc
    if not isinstance(data, dict):
        raise PhrasesError(f"{where}: a sentence file is one JSON object, "
                           f"the name of a sentence -> its words")
    out: dict = {}
    for key, value in data.items():
        if not key:
            raise PhrasesError(f"{where}: a sentence without a name")
        if isinstance(value, str):
            out[key] = value
        elif isinstance(value, list) and value \
                and all(isinstance(one, str) for one in value):
            out[key] = tuple(value)
        else:
            raise PhrasesError(f"{where}: {key!r} is neither a string nor a "
                               f"list of strings")
    return out


def own(profile, module: str) -> Optional[dict]:
    """What *profile* words itself for *module*; None where it has no file
    for it, which is not an error: it takes the sentences of the profile it
    extends."""
    path = path_of(profile, module)
    if not path.is_file():
        return None
    return parse(path.read_text(encoding="utf-8"), path)


def layers(profile, module: str) -> list:
    """[(profile, its table)] along the line of profiles, nearest first,
    for those that have a file."""
    found = ((one, own(one, module)) for one in profile.lineage())
    return [(one, got) for one, got in found if got is not None]


def table(profile, module: str) -> dict:
    """The sentences of *module* as *profile* gets them: those of the
    profiles it extends, the farthest first, and its own laid over them
    entry by entry. LookupError where no profile of the line writes any."""
    found = layers(profile, module)
    if not found:
        line = [one.name for one in profile.lineage()]
        where = (f"({path_of(profile, module)})" if len(line) == 1 else
                 f"(nor does {', '.join(line[1:])}, which it extends)")
        raise LookupError(f"profile {profile.name!r} writes no sentences "
                          f"for {module} {where}")
    out: dict = {}
    for _, got in reversed(found):
        out.update(got)
    return out
