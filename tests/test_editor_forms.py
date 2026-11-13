"""The forms of `docpipe edit` that replace typed JSON (docpipe/editor/web/
forms.js), held to their promise for both profiles' real files:

1. a form given a value and no edit gives back the identical value, key order
   included, so the file is written back byte for byte;
2. an edit through one field of a form changes only the key that field shows;
3. a key the form does not know is kept, where it stood.

The conversion is the page's own JavaScript, run through node; the tests are
skipped where node is not on the path. Each promise has a case that breaks it
by construction (a converter that drops an unknown key, reorders keys or
turns an empty text into a missing key), which the checks must catch.
"""
import copy
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from docpipe import rules as rule_files
from docpipe.editor import rulespage, specs
from docpipe.profile import load_profile

ROOT = Path(__file__).resolve().parent.parent
DRIVER = ROOT / "tests" / "editor_forms_driver.js"
PROFILES = ("kwp", "scenarios")
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node is not on PATH")
UNKNOWN = {"zz_unknown": {"a": [1, "x"]}}


def run_node(jobs):
    done = subprocess.run([NODE, str(DRIVER)], input=json.dumps(jobs),
                          capture_output=True, text=True, encoding="utf-8",
                          timeout=120)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


# -- the real values each form is given -----------------------------------------

def spec_of(name):
    return json.loads((ROOT / "profiles" / name / "extraction_spec.json")
                      .read_text(encoding="utf-8"))


def cases(name):
    """[(label, recipe, value)] for every JSON-typed value of the profile's
    spec and rules files."""
    profile = load_profile(name)
    spec = spec_of(name)
    out = []
    for parameter in spec["parameters"]:
        uri = parameter["uri"]
        coordinates = list((parameter.get("axes") or {}))
        if "example" in parameter:
            numeric = parameter.get("value_type", "float") in ("float", "int")
            out.append((f"{name}:{uri}.example", {
                "recipe": "example", "coordinates": coordinates,
                "value": parameter["example"], "numeric": numeric},
                parameter["example"]))
        for axis, block in (parameter.get("axes") or {}).items():
            if "derive" in block:
                out.append((f"{name}:{uri}.{axis}.derive",
                            {"recipe": "derive"}, block["derive"]))
    for key, field in (spec.get("plan_fields") or {}).items():
        if "of" in field:
            out.append((f"{name}:plan_fields.{key}.of",
                        {"recipe": "entry_of"}, field["of"]))
    known = rule_files.registry(profile)
    taken = rule_files.load(profile, environ={})
    for rule_name, one in known.items():
        if one.kind in ("map", "table", "range"):
            out.append((f"{name}:rule {rule_name}", {
                "recipe": "rule", "rule": {
                    "kind": one.kind, "columns": list(one.columns),
                    "of": one.of}}, taken.values[rule_name]))
    return out


ALL = [case for name in PROFILES for case in cases(name)]


def ids(items):
    return [label for label, _recipe, _value in items]


# -- how a value is compared ---------------------------------------------------

def flat(value, where=()):
    """{path: leaf} of a value; an empty container is a leaf of its own."""
    if isinstance(value, dict) and value:
        return {p: v for k, x in value.items()
                for p, v in flat(x, where + (k,)).items()}
    if isinstance(value, list) and value:
        return {p: v for i, x in enumerate(value)
                for p, v in flat(x, where + (i,)).items()}
    return {where: value}


def same_order(before, after):
    """Keys both have stand in the order the file has them, at every depth."""
    if isinstance(before, dict) and isinstance(after, dict):
        common = [k for k in before if k in after]
        if common != [k for k in after if k in before]:
            return False
        return all(same_order(before[k], after[k]) for k in common)
    if isinstance(before, list) and isinstance(after, list):
        return all(same_order(a, b) for a, b in zip(before, after))
    return True


def roundtrip_problems(before, after):
    """What breaks the first promise: the value is not the identical text."""
    if json.dumps(before, ensure_ascii=False) != json.dumps(
            after, ensure_ascii=False):
        return ["the value is not the identical one, key order included"]
    return []


def edit_problems(before, after, vpath, newkey=None):
    """What breaks the second promise: something other than the key the
    field shows changed, or an untouched key moved."""
    out = []
    allowed = [tuple(vpath)]
    if newkey is not None:
        allowed.append(tuple(vpath[:-1]) + (newkey,))
    old, new = flat(before), flat(after)
    for path in set(old) | set(new):
        if old.get(path, ...) != new.get(path, ...) and not any(
                path[:len(a)] == a for a in allowed):
            out.append(f"changed {path}")
    if not same_order(before, after):
        out.append("keys moved")
    return out


def with_unknown(value):
    """The value with a key the form does not know, second in its object,
    and one inside the first nested object."""
    if not isinstance(value, dict) or not value:
        return None
    keys = list(value)
    out = {}
    for i, key in enumerate(keys):
        if i == 1 or (i == 0 and len(keys) == 1):
            out.update(UNKNOWN)
        out[key] = value[key]
    if len(keys) == 1:
        out = {**value, **UNKNOWN}
    for key, inner in out.items():
        if key != "zz_unknown" and isinstance(inner, dict) and inner:
            first = next(iter(inner))
            out[key] = {first: inner[first], "zz_inner": 1,
                        **{k: v for k, v in inner.items() if k != first}}
            break
    return out


# -- 1. no edit, the identical value --------------------------------------------

@needs_node
def test_every_form_gives_back_the_identical_value_of_the_real_files():
    assert len(ALL) > 40
    answers = run_node([{"op": "roundtrip", "recipe": r, "value": v}
                        for _l, r, v in ALL])
    bad = {label: roundtrip_problems(value, answer.get("value"))
           for (label, _r, value), answer in zip(ALL, answers)}
    assert {k: v for k, v in bad.items() if v} == {}


def test_the_roundtrip_check_can_fail():
    value = {"a": 1, "b": {"c": 2}}
    assert roundtrip_problems(value, copy.deepcopy(value)) == []
    assert roundtrip_problems(value, {"b": {"c": 2}, "a": 1})     # order
    assert roundtrip_problems(value, {"a": 1})                    # dropped
    assert roundtrip_problems(value, {"a": 1, "b": {"c": 3}})     # changed


@needs_node
@pytest.mark.parametrize("defect", ["drop_unknown", "reorder", "drop_empty"])
def test_a_converter_that_breaks_the_promise_is_caught(defect):
    pool = [c for c in ALL if isinstance(c[2], dict) and len(c[2]) > 1]
    answers = run_node([{"op": "roundtrip", "recipe": r, "value": v,
                         "broken": defect} for _l, r, v in pool])
    caught = [label for (label, _r, value), answer in zip(pool, answers)
              if roundtrip_problems(value, answer.get("value"))]
    assert caught, f"{defect} was not noticed"


@needs_node
def test_a_value_that_does_not_fit_its_form_is_kept_as_it_is():
    odd = [({"recipe": "rule", "rule": {"kind": "range", "columns": [],
                                        "of": "text"}}, "1900-2100")]
    answers = run_node([{"op": "roundtrip", "recipe": r, "value": v}
                        for r, v in odd])
    assert [a["value"] for a in answers] == [v for _r, v in odd]
    assert unfit([("odd", a) for a in answers]) == ["odd"]


def unfit(results):
    """The labels whose value its form, given it again, keeps as it is
    instead of showing it as a form."""
    return [label for label, answer in results if answer.get("odd")]


@needs_node
def test_every_value_a_form_writes_fits_the_form_again():
    """A form shows what it wrote: every field of every form, set to a value
    and emptied, gives a value the same form takes again as a form."""
    listed = run_node([{"op": "leaves", "recipe": r, "value": v}
                       for _l, r, v in ALL])
    jobs, meta = [], []
    for (label, recipe, value), answer in zip(ALL, listed):
        for leaf in answer["leaves"]:
            for text in (text_for(leaf["kind"]), ""):
                jobs.append({"op": "edit", "recipe": recipe, "value": value,
                             "path": leaf["path"], "text": text})
                meta.append((f"{label} {leaf['path']}={text!r}", recipe))
    assert len(jobs) > 1000
    written = run_node(jobs)
    again = [(label, recipe, answer["value"])
             for (label, recipe), answer in zip(meta, written)
             if "value" in answer]
    shown = run_node([{"op": "roundtrip", "recipe": r, "value": v}
                      for _l, r, v in again])
    assert unfit([(label, a) for (label, _r, _v), a in zip(again, shown)]) == []


# -- 2. an edit changes only its key ------------------------------------------

def text_for(kind):
    return "7" if kind in ("number", "int") else "zz9"   # a key is "zz9" too


@needs_node
@pytest.mark.parametrize("name", PROFILES)
def test_an_edit_through_one_field_changes_only_the_key_it_shows(name):
    pool = [c for c in ALL if c[0].startswith(name + ":")]
    listed = run_node([{"op": "leaves", "recipe": r, "value": v}
                       for _l, r, v in pool])
    jobs, meta = [], []
    for (label, recipe, value), answer in zip(pool, listed):
        for leaf in answer["leaves"]:
            jobs.append({"op": "edit", "recipe": recipe, "value": value,
                         "path": leaf["path"],
                         "text": text_for(leaf["kind"])})
            meta.append((label, value, leaf))
    assert len(jobs) > 250
    done = run_node(jobs)
    bad = []
    for (label, value, leaf), answer in zip(meta, done):
        after = answer.get("value")
        if value is None:           # no bound yet: a bound makes the pair
            want = [7, None] if leaf["path"] == ["lo"] else [None, 7]
            if after != want:
                bad.append((label, leaf["path"], [f"gave {after}"]))
            continue
        problems = edit_problems(
            value, after, leaf["vpath"],
            "zz9" if leaf["kind"] == "key" else None)
        if leaf["kind"] not in ("key",) and not problems:
            shown = flat(after).get(tuple(leaf["vpath"]), ...)
            if shown not in ("zz9", 7):
                problems.append(f"the edit is not at {leaf['vpath']}")
        if problems:
            bad.append((label, leaf["path"], problems))
    assert bad == []


def test_the_edit_check_can_fail():
    before = {"a": 1, "b": 2, "c": 3}
    assert edit_problems(before, {"a": 9, "b": 2, "c": 3}, ["a"]) == []
    assert edit_problems(before, {"a": 9, "b": 8, "c": 3}, ["a"])
    assert edit_problems(before, {"c": 3, "a": 9, "b": 2}, ["a"])  # moved
    assert edit_problems(before, {"a": 1, "b": 2}, ["a"])          # dropped


# -- 3. a key the form does not know is kept ------------------------------------

@needs_node
def test_a_key_the_form_does_not_know_is_kept_where_it_stood():
    pool = [(label, r, with_unknown(v)) for label, r, v in ALL
            if with_unknown(v) is not None]
    assert len(pool) > 30
    answers = run_node([{"op": "roundtrip", "recipe": r, "value": v}
                        for _l, r, v in pool])
    bad = [label for (label, _r, value), a in zip(pool, answers)
           if roundtrip_problems(value, a.get("value"))]
    assert bad == []
    # and after an edit of another field of the same form
    edits = []
    for label, recipe, value in pool:
        leaf = run_node([{"op": "leaves", "recipe": recipe,
                          "value": value}])[0]["leaves"]
        if leaf:
            edits.append((label, recipe, value, leaf[0]))
    done = run_node([{"op": "edit", "recipe": r, "value": v,
                      "path": leaf["path"], "text": text_for(leaf["kind"])}
                     for _l, r, v, leaf in edits])
    for (label, _r, value, leaf), answer in zip(edits, done):
        assert answer["value"]["zz_unknown"] == UNKNOWN["zz_unknown"], label
        assert not edit_problems(
            value, answer["value"], leaf["vpath"],
            "zz9" if leaf["kind"] == "key" else None), label


@needs_node
def test_a_converter_that_drops_the_unknown_key_is_caught():
    pool = [(label, r, with_unknown(v)) for label, r, v in ALL
            if with_unknown(v) is not None]
    answers = run_node([{"op": "roundtrip", "recipe": r, "value": v,
                         "broken": "drop_unknown"} for _l, r, v in pool])
    assert any(roundtrip_problems(v, a.get("value"))
               for (_l, _r, v), a in zip(pool, answers))


# -- the rows and pairs of the rules --------------------------------------------

@needs_node
def test_a_new_row_of_a_table_has_every_column_and_a_new_pair_a_key():
    table = {"recipe": "rule", "rule": {
        "kind": "table", "columns": ["shape", "property", "reason"],
        "of": "text"}}
    row = run_node([{"op": "add_row", "recipe": table, "value": [],
                     "path": []}])[0]
    assert row["value"] == [{"shape": "", "property": "", "reason": ""}]
    pairs = {"recipe": "rule", "rule": {"kind": "map", "columns": [],
                                        "of": "text"}}
    one = run_node([{"op": "add_pair", "recipe": pairs, "value": {"a": "b"},
                     "path": []}])[0]
    assert one["index"] == 1 and one["value"] == {"a": "b"}   # no key yet
    named = run_node([{"op": "add_pair", "recipe": pairs, "value": {"a": "b"},
                       "path": []},
                      {"op": "edit", "recipe": pairs, "value": {"a": "b"},
                       "path": [0, "key"], "text": "c"}])
    assert named[1]["value"] == {"c": "b"}


@needs_node
def test_a_range_is_two_numbers_and_empty_is_no_bound():
    recipe = {"recipe": "rule", "rule": {"kind": "range", "columns": [],
                                         "of": "text"}}
    edits = [(None, ["lo"], "1800", [1800, 2100]),
             ([1900, 2100], ["hi"], "", [1900, None]),
             ([1900, 2100], ["lo"], "", [None, 2100])]
    done = run_node([{"op": "edit", "recipe": recipe, "value": v,
                      "path": p, "text": t} for v, p, t, _w in edits[1:]])
    assert [d["value"] for d in done] == [w for _v, _p, _t, w in edits[1:]]
    both = run_node([{"op": "edit", "recipe": recipe, "value": [1900, 2100],
                      "path": ["lo"], "text": ""},
                     {"op": "edit", "recipe": recipe, "value": [1900, 2100],
                      "path": ["lo"], "text": ""}])
    assert both[0]["value"] == [None, 2100]
    empty = run_node([{"op": "roundtrip", "recipe": recipe, "value": None}])[0]
    assert empty["value"] is None


# -- what the Python side declares -----------------------------------------------

def test_the_spec_form_has_no_json_field_and_none_for_the_graph():
    form = specs.form(load_profile("kwp"))
    widgets = {f["widget"] for fields in form.values() for f in fields}
    assert "json" not in widgets
    # what a field becomes in the graph is drawn in the graph file, so the
    # spec's form offers no `kg` and names no keys of one
    assert "kg_keys" not in form
    for kind in ("parameter", "axis"):
        assert "kg" not in {f["key"] for f in form[kind]}
    by_key = {f["key"]: f for f in form["parameter"]}
    assert by_key["example"]["widget"] == "example"
    axis = {f["key"]: f for f in form["axis"]}
    assert axis["derive"]["widget"] == "derive"


def test_every_kind_of_rule_has_a_form_and_none_is_json():
    assert set(rulespage.FORMS) == set(rule_files.KINDS)
    assert "json" not in rulespage.FORMS.values()
    assert {rulespage.FORMS[k] for k in ("map", "table", "range")} == {
        "pairs", "rows", "bounds"}
