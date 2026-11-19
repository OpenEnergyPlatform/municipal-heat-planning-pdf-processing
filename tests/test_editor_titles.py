"""
test_editor_titles.py: every setting `docpipe edit` shows has a name in
words (owner request 2026-11-19, A5: "jede Einstellung bekommt einen
deutschen Namen, der Schlüssel steht klein daneben").

The promise, in one sentence: every rule of every profile (those of the run
and those of the graph), every number of the flow, every key of the spec's
form, every setting of a brick of the graph and every key of a source has a
name in words that is not its key, has no underscore and is short enough to
stand above its help; that name has a German entry in the page's catalogue
(tests/test_editor_i18n.py, part 3). A setting without one is caught by
construction.

Author: Felix Vossel
"""
from __future__ import annotations

from dataclasses import replace

import pytest

from docpipe import graphfile, rules, sources
from docpipe.editor import graphpage, specs
from docpipe.extraction import flow as flow_map
from docpipe.profile import load_profile

PROFILES = (None, "kwp", "scenarios")
MOST_WORDS = 8


def settings_shown() -> list:
    """(where, key, title) of every setting the page shows."""
    out = []
    for name in PROFILES:
        profile = load_profile(name) if name else None
        for one in rules.registry(profile).values():
            out.append((f"rule of {name or 'default'}", one.name, one.title))
        if profile is not None:
            for key, one in graphfile.declared(profile).items():
                out.append((f"graph rule of {name}", key, one.title))
            for brick in graphpage.bricks_of(profile):
                for setting in brick["settings"]:
                    out.append((f"brick {brick['name']} of {name}",
                                setting["key"], setting.get("title")))
    for number in flow_map.NUMBERS:
        out.append(("number of the flow", number.name, number.title))
    for kind, fields in specs.form().items():
        for one in fields:
            out.append((f"spec form {kind}", one["key"], one.get("title")))
    for needed, optional in sources.KEYS.values():
        for key in needed + optional:
            out.append(("source", key, sources.TITLES.get(key)))
    return out


def faults(shown: list) -> list:
    """(where, key, why) of every setting whose name in words is missing or
    is no name."""
    out = []
    for where, key, title in shown:
        if not title:
            out.append((where, key, "no name"))
        elif title == key or "_" in title:
            out.append((where, key, "the key, not a name"))
        elif len(title.split()) > MOST_WORDS:
            out.append((where, key, "longer than a name"))
    return out


def test_every_setting_the_page_shows_has_a_name_in_words():
    shown = settings_shown()
    assert len(shown) > 450
    assert faults(shown) == []


@pytest.mark.parametrize("broken, why", [
    ("", "no name"),
    ("decimal_mark", "the key, not a name"),
    ("How the documents write the decimal mark of a number", "longer than a name"),
])
def test_a_setting_without_a_name_is_caught(broken, why):
    one = replace(rules.BY_NAME["decimal_mark"], title=broken)
    assert faults([("rule", one.name, one.title)]) == [("rule", one.name, why)]


def test_a_rule_declared_without_a_name_has_none():
    # by construction: what a declaration leaves out stays out
    made = rules.rule("x", "flow", "Group", "switch", "On: x.")
    assert made.title == ""
    assert faults([("rule", made.name, made.title)])
