"""
Every rule is switched in some test (owner decision 2026-11-11): a
test sets it by name, as a keyword (`name=`, as `rules.overlaid` and
`rules.stepped` take it) or as a key (`"name":`, as a rules file, a graph
file or a step's values hold it). A rule with one choice has nothing to
switch to.

The promise, with a case that breaks it by construction: a rule no test
sets is named.
"""
import re
from pathlib import Path

from docpipe import graphfile, rules
from docpipe.profile import load_profile

TESTS = Path(__file__).resolve().parent
KEYWORD = re.compile(r"\b([a-z_][a-z0-9_]*)\s*=(?!=)")
KEY = re.compile(r"[\"']([a-z_][a-z0-9_]*)[\"']\s*:")


def every_rule() -> dict:
    """The rules of the core, of both profiles and of their graph files."""
    found = {one.name: one for one in rules.RULES}
    for name in ("kwp", "scenarios"):
        made = load_profile(name)
        for table in (rules.registry(made), graphfile.declared(made)):
            for rule_name, one in table.items():
                found.setdefault(rule_name, one)
    return found


def switchable(one) -> bool:
    return not (one.kind == "choice" and len(one.choices or ()) == 1)


def unswitched(names, text: str) -> list:
    """The *names* that *text* never sets."""
    set_ = set(KEYWORD.findall(text)) | set(KEY.findall(text))
    return sorted(name for name in names if name not in set_)


def test_every_rule_is_switched_in_a_test():
    text = "\n".join(path.read_text(encoding="utf-8")
                     for path in sorted(TESTS.glob("test_*.py")))
    found = every_rule()
    assert len(found) > 300
    assert unswitched([name for name, one in found.items()
                       if switchable(one)], text) == []


def test_a_rule_no_test_sets_is_named():
    said = 'rules.get("quote_min_chars")\nwith rules.overlaid(year_range=1):'
    assert unswitched(["quote_min_chars", "year_range"], said) == [
        "quote_min_chars"]
    assert unswitched(["year_range"], '{"year_range": [1, 2]}') == []
