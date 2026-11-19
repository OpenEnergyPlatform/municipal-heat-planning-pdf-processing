"""
test_editor_field_form.py: the form of a field in the Spec tab of
`docpipe edit` shows what the field's value type reads (owner request
2026-11-19, A6: "das Formular zeigt nur, was der gewählte Werttyp liest").

The promise, in one sentence: for every value type a spec can have, the
form of a field shows a key exactly where the loader of the spec
(`spec.load`) takes that key into a field of that type: a key the form
hides is one the loader refuses or leaves aside for the type, AND a key it
shows is one the loader takes into the field. The form decides by the
server's `specs.READ_FOR` (the keys read only under some settings of a
value type) and the page's `spec/model.ts typeReads`; both halves are
tests of their own, each with a case that breaks it by construction.

The page's part is its own TypeScript, run by node with its types stripped;
that test is skipped where node cannot do that.

Author: Felix Vossel
"""
from __future__ import annotations

import copy
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from docpipe.editor import specs
from docpipe.extraction import spec as spec_module

ROOT = Path(__file__).resolve().parent.parent
DRIVER = ROOT / "tests" / "editor_spec_model_driver.mjs"
NODE = shutil.which("node")

DESCRIPTION = ("Ein Wert, den das Dokument für seine Gemeinde nennt, mit dem "
               "Jahr und der Art, in der er dort gedruckt steht, und mit dem "
               "Wortlaut, den das Dokument für ihn verwendet.")
SOURCE = ("Im Jahr 2022 lag der Wert der Fernwärme bei zwölf Einheiten, so "
          "steht es in der Tabelle des Plans auf Seite drei.")
CHECK = {"name": "kurz", "refuse": {"all": [
    {"of": "quote", "is": "length", "op": "less", "value": 20}]},
    "sentence": "Quote the whole line."}


def value_types() -> dict:
    """Every value type a spec can give a field, by the settings the loader
    accepts (`spec._validate_value_types`): a number with or without units,
    converted or not, found as a number or as words; an entry; words."""
    out = {}
    for answer in spec_module.ANSWERS:
        if answer == "number":
            settings = [(False, False), (True, False), (True, True)]
        else:
            settings = [(None, None)]
        for units, converts in settings:
            for in_quote in spec_module.IN_QUOTE[answer]:
                one = {"answer": answer, "in_quote": in_quote}
                if answer == "number":
                    one.update(units=units, converts=converts)
                out[f"t{len(out)}"] = one
    return out


TYPES = value_types()


def field_of(name: str, settings: dict) -> dict:
    """A field of the value type *name* that the loader takes as it is."""
    out = {"uri": "f", "label": "F", "description": DESCRIPTION,
           "value_type": name}
    if settings["answer"] == "number" and settings.get("units"):
        out["unit_target"] = "UO_1"
        out["units_accepted"] = {"E": {"factor": 1.0, "names_period": False}}
    if settings["answer"] == "entry":
        out["vocabulary"] = {"a": {"label": "Bestand", "spellings": [],
                                   "definition": "Was heute steht."}}
    value = 12 if settings["answer"] == "number" else (
        "a" if settings["answer"] == "entry" else "zwölf")
    out["example"] = {"source": SOURCE,
                      "tuples": [{"value": value, "quote": "zwölf Einheiten"}]}
    return out


# What each key of a field is set to, to see whether the loader takes it:
# (how the field is changed, what the loaded field then has where it took
# the key). The keys every type has are set to another value the loader
# accepts; value_type is the type itself and is not probed.
def _units_probe(field):
    field["units_accepted"] = {"P": {"factor": 2.0, "names_period": False}}


def _dynamic_probe(field):
    field.pop("vocabulary", None)
    field["vocabulary_dynamic"] = True


PROBES = {
    "uri": (lambda f: f.update(uri="g"), lambda p: p.uri == "g"),
    "label": (lambda f: f.update(label="G"), lambda p: p.label == "G"),
    "description": (lambda f: f.update(description=DESCRIPTION + " Mehr."),
                    lambda p: p.description.endswith("Mehr.")),
    "brief": (lambda f: f.update(brief="Kurz."), lambda p: p.brief == "Kurz."),
    "once_per_document": (lambda f: f.update(once_per_document=True),
                          lambda p: p.once_per_document is True),
    "takes_group": (lambda f: f.update(takes_group=False),
                    lambda p: p.takes_group is False),
    "merged": (lambda f: f.update(merged="Bündel"),
               lambda p: p.merged == "Bündel"),
    "vocabulary_dynamic": (_dynamic_probe,
                           lambda p: p.vocabulary_dynamic is True),
    "unit_target": (lambda f: f.update(unit_target="UO_2"),
                    lambda p: p.unit_target == "UO_2"),
    "integrated": (lambda f: f.update(integrated=False),
                   lambda p: p.integrated is False),
    "units_accepted": (_units_probe, lambda p: "P" in p.units_accepted),
    "example": (lambda f: f["example"].update(source=SOURCE + " Noch."),
                lambda p: p.example["source"].endswith("Noch.")),
    "checks": (lambda f: f.update(checks=[CHECK]),
               lambda p: [c["name"] for c in p.checks] == ["kurz"]),
}


def loader_takes(key: str, name: str, probes=PROBES) -> bool:
    """Whether the loader takes *key* into a field of the value type
    *name*: the field with the key set loads, and the loaded field has what
    the key says."""
    change, has = probes[key]
    field = field_of(name, TYPES[name])
    change(field)
    try:
        loaded = spec_module.load({"value_types": TYPES,
                                   "parameters": [field]})
    except spec_module.SpecError:
        return False
    return bool(has(loaded.parameters[0]))


def form_keys() -> list:
    """The keys of a field's form, each with its `when` (None where the
    form shows it under every value type)."""
    return [(one["key"], one.get("when")) for one in specs.form()["parameter"]
            if one["key"] != "value_type"]


def server_shows(when, settings: dict) -> bool:
    """The rule the page follows (`typeReads`), as the server states it."""
    if when is None:
        return True
    return all((settings.get(key, False)) in want
               for key, want in when.items())


def mismatches(shows, keys=None, probes=PROBES) -> list:
    """(key, value type, shown, taken) wherever the form and the loader
    disagree."""
    out = []
    for key, when in keys if keys is not None else form_keys():
        for name, settings in TYPES.items():
            shown = shows(key, when, settings)
            taken = loader_takes(key, name, probes)
            if shown != taken:
                out.append((key, name, shown, taken))
    return out


def test_every_key_of_the_form_has_a_probe():
    assert {key for key, _ in form_keys()} == set(PROBES)


def test_the_value_types_cover_every_answer_and_every_unit_setting():
    seen = {(s["answer"], s.get("units"), s.get("converts"), s["in_quote"])
            for s in TYPES.values()}
    assert len(seen) == len(TYPES) == 8
    assert {s["answer"] for s in TYPES.values()} == set(spec_module.ANSWERS)


def test_a_key_the_form_keeps_for_some_types_is_marked_with_them():
    said = dict(form_keys())
    for key, when in specs.READ_FOR.items():
        assert said[key] == when


def test_the_form_shows_a_key_exactly_where_the_loader_takes_it():
    assert mismatches(lambda key, when, s: server_shows(when, s)) == []


def test_a_form_that_shows_every_key_everywhere_is_caught():
    # by construction: the form as it was before A6 shows the units of a
    # number to a category, which the loader refuses
    broken = mismatches(lambda key, when, s: True)
    assert ("unit_target", "t6", True, False) in broken
    assert any(key == "merged" for key, *_ in broken)


def test_a_form_that_hides_what_a_type_reads_is_caught():
    # by construction: the unit hidden from every value type, the numbers
    # with units too
    keys = [(key, {"answer": []} if key == "unit_target" else when)
            for key, when in form_keys()]
    broken = mismatches(lambda key, when, s: server_shows(when, s), keys)
    assert [(k, n) for k, n, shown, taken in broken] \
        == [("unit_target", n) for n, s in TYPES.items()
            if s["answer"] == "number" and s.get("units")]


def test_a_loader_that_lets_a_number_carry_a_list_is_caught():
    # by construction: a probe that keeps the field's list where the
    # loader refuses it shows the half of the promise about refusals can
    # fail; a number with units carries no list of entries
    for name, settings in TYPES.items():
        if settings["answer"] == "number" and settings.get("units"):
            assert loader_takes("vocabulary_dynamic", name) is False
    probes = dict(PROBES, vocabulary_dynamic=(_dynamic_probe,
                                              lambda p: True))
    assert loader_takes("vocabulary_dynamic", "t2", probes) is False


# -- the page ---------------------------------------------------------------------


def _strips_types() -> bool:
    if NODE is None:
        return False
    done = subprocess.run([NODE, "-p", "process.features.typescript"],
                          capture_output=True, text=True, timeout=30)
    return done.returncode == 0 and done.stdout.strip() in ("strip",
                                                            "transform")


needs_node = pytest.mark.skipif(not _strips_types(),
                                reason="no node that strips TypeScript types")


def page_shows(broken: str = "") -> dict:
    """{(key, value type): whether the page's form shows it}."""
    when = {key: one for key, one in form_keys() if one is not None}
    jobs = [{"op": "reads", "when": when, "settings": settings,
             **({"broken": broken} if broken else {})}
            for settings in TYPES.values()]
    done = subprocess.run([NODE, str(DRIVER)], input=json.dumps(jobs),
                          capture_output=True, text=True, encoding="utf-8",
                          timeout=120)
    assert done.returncode == 0, done.stderr
    out = {}
    for name, answer in zip(TYPES, json.loads(done.stdout)):
        for key, _ in form_keys():
            out[(key, name)] = answer.get(key, True)
    return out


@needs_node
def test_the_page_shows_a_key_exactly_where_the_loader_takes_it():
    shown = page_shows()
    assert mismatches(lambda key, when, s: shown[(key, _name(s))]) == []


@needs_node
def test_a_page_that_shows_every_key_is_caught():
    shown = page_shows("every")
    broken = mismatches(lambda key, when, s: shown[(key, _name(s))])
    assert ("unit_target", "t6", True, False) in broken


def _name(settings: dict) -> str:
    return next(name for name, one in TYPES.items() if one == settings)


def test_the_built_in_types_are_among_those_checked():
    built = [kind.settings() for kind in spec_module.BUILTIN_TYPES.values()]
    for one in built:
        assert any(all(s.get(k, False) == v for k, v in one.items())
                   for s in TYPES.values()), one
    assert copy.deepcopy(TYPES) == value_types()
