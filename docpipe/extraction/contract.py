"""
contract.py: The core's half of the extraction prompts: where its templates
are, which languages they come in and the facts the code fills into them.

A prompt of the extraction stage says what the answer has to look like (the
keys, the quote that stands in a source, the answer that stands in the quote,
"not stated", what to do with a closed list) and it says what the corpus is
(the role, the examples, how its tables are written). The first is the same
for every corpus and was copied into every profile's prompts, with the
sentences drifting apart. It is written in `contract/<language>/<name>.md`,
and a profile's prompt that names it (`template: rows`) holds its own half:
its parts, and its own words for a sentence of the template that fits it
less well. docpipe/prompts.py puts them together.

The language of a prompt is a fact about the profile that owns the parts
file, declared there as `extraction.CONTRACT_LANGUAGE` and not inherited: a
profile that extends another and keeps its parts files gets the language
those are in. A profile with no declaration, or one the core has no templates
for, is refused at load and told which languages there are.

A fact is a value the code decides and a prompt only repeats, so the prompt
and the request agree by construction: the least length of a quote
(`verify.MIN_QUOTE_CHARS`), the word for "not stated" (`fields.UNSTATED`),
and the words the closed list is shown in and the key of the frame's list from
the profile's PHRASES. No template carries any of them as a typed number or
word.

Author: Felix Vossel
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, Optional

from .. import prompts

# Where the templates lie: contract/<language>/<name>.md. Read when asked, so a
# test can point it at a folder of its own.
TEMPLATE_ROOT = Path(__file__).resolve().parent / "contract"

# The facts a template or a profile's part may name, `{{name}}`.
FACT_NAMES = ("min_quote_chars", "unstated", "option_means", "option_spellings",
              "unstated_means", "unstated_spelling", "frame_options")
# The ones that are a sentence of the profile's PHRASES, by the same name.
_PHRASE_FACTS = frozenset(FACT_NAMES) - {"min_quote_chars", "unstated"}

_NAME = re.compile(r"[a-z][a-z_0-9]*\Z")


def is_name(text: str) -> bool:
    """Whether *text* can name a template or a language: lower case letters,
    digits and underscores, so that it never leaves the template folder."""
    return bool(_NAME.match(text))


def languages() -> list:
    """The languages the core has templates in: the folders of TEMPLATE_ROOT
    that hold one."""
    if not TEMPLATE_ROOT.is_dir():
        return []
    return sorted(folder.name for folder in TEMPLATE_ROOT.iterdir()
                  if is_name(folder.name) and any(folder.glob("*.md")))


def template_names(language: str) -> list:
    """The templates one language has."""
    folder = TEMPLATE_ROOT / language
    if not (is_name(language) and folder.is_dir()):
        return []
    return sorted(path.stem for path in folder.glob("*.md")
                  if is_name(path.stem))


def template_path(language: str, name: str) -> Path:
    """Where a template of the language lies, whether or not it is there. Both
    names are checked so that no name reaches outside the folder."""
    if not (is_name(language) and is_name(name)):
        raise ValueError(f"{language!r}/{name!r} is not a language and a "
                         f"template name (lower case letters, digits and "
                         f"underscores)")
    return TEMPLATE_ROOT / language / f"{name}.md"


def language_of(owner) -> Optional[str]:
    """The language the parts files of a profile are in, as that profile
    declares it itself, or None."""
    return owner.own("extraction", "CONTRACT_LANGUAGE")


def read(language: str, name: str) -> "prompts.Template":
    """One template of the core, read and checked as a template."""
    return prompts.read_template(template_path(language, name),
                                 language=language, name=name,
                                 fact_names=FACT_NAMES)


def available() -> list:
    """[(language, name)] of every template there is."""
    return [(language, name) for language in languages()
            for name in template_names(language)]


def facts(profile, names: Iterable) -> dict:
    """{name: value} of the facts a prompt names, for this profile. Only the
    ones asked for are read: a profile whose PHRASES are incomplete is told so
    by a prompt that needs them and not by one that does not."""
    from . import fields, verify, wording
    names = list(names)
    unknown = sorted(set(names) - set(FACT_NAMES))
    if unknown:
        raise KeyError(f"{unknown} are not facts of the core {sorted(FACT_NAMES)}")
    phrases = wording.phrases(profile) if _PHRASE_FACTS & set(names) else {}
    out: dict = {}
    for name in names:
        if name == "min_quote_chars":
            out[name] = verify.MIN_QUOTE_CHARS
        elif name == "unstated":
            out[name] = fields.UNSTATED
        elif name == "frame_options":
            # The key the request sends the list of `scenario` under, which is
            # what the frame template says: a phrase that names the slot is
            # filled for it, as the request fills it.
            out[name] = phrases[name].format(slot="scenario")
        else:
            out[name] = phrases[name]
    return out
