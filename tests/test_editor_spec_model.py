"""
test_editor_spec_model.py: what the Spec tab of `docpipe edit` draws of a
field and the edits it makes (docpipe/editor/ui/src/spec/model.ts and
layout.ts), and how a box of a drawing is moved by hand (lib/moved.ts, as
the Spec, Graph and Flow tabs use it).

The promise, in one sentence: for every field of both profiles' real specs
the drawing gives each list of the ontology that a list of the field draws
its entries from a box with an arrow into exactly the rows it gives
entries to, AND marks a dimension shared exactly where the file writes
"shared", AND shows on the right what falls under the field (its own list,
else the quantity, else the row chosen) with every entry that has words of
the plans and exactly those words, the rest folded into one box that
counts them, AND draws an arrow from the units into each dimension the
unit decides, naming the entry it decides, AND leaves the spec as it was;
a word moved leaves its entry AND lands on the other one, nothing else
changing; a field that stops sharing a dimension gets its own copy AND the
others keep sharing; the order of the questions takes only an order of the
same dimensions; a dimension marked as asked only where the value stands is
no longer read once with the number; untangling never leaves more
crossings than before AND the drawing keeps the order it found; a box
moved by hand stays where it was put AND no other box moves AND the layout
stays as it was, and the frame of the entries takes its entries along.
Each AND is a test with a case that breaks it by construction.

The drawing is the page's own TypeScript, run by node with its types
stripped; the tests are skipped where node cannot do that.

Author: Felix Vossel
"""
from __future__ import annotations

import copy
import functools
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from docpipe.extraction import spec as spec_module

ROOT = Path(__file__).resolve().parent.parent
DRIVER = ROOT / "tests" / "editor_spec_model_driver.mjs"
PROFILES = ("kwp", "scenarios")
VALUE = "@value"
NODE = shutil.which("node")


def _strips_types() -> bool:
    if NODE is None:
        return False
    done = subprocess.run([NODE, "-p", "process.features.typescript"],
                          capture_output=True, text=True, timeout=30)
    return done.returncode == 0 and done.stdout.strip() in ("strip",
                                                            "transform")


pytestmark = pytest.mark.skipif(not _strips_types(),
                                reason="no node that strips TypeScript types")


def run_node(jobs: list) -> list:
    done = subprocess.run([NODE, str(DRIVER)], input=json.dumps(jobs),
                          capture_output=True, text=True, encoding="utf-8",
                          timeout=120)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


@functools.lru_cache(maxsize=None)
def _served(name: str) -> str:
    """What the page gets of the profile's spec (GET /api/spec): the spec,
    the snapshot's terms it uses and the lists of the ontology."""
    from docpipe.editor import server
    from docpipe.profile import load_profile

    profile = load_profile(name)
    app = server.App(profile, None, ROOT)
    app.spec_path = Path(profile.package_dir) / "extraction_spec.json"
    status, got = app.call("GET", "/api/spec", {}, None)
    assert status == 200, got
    return json.dumps({"data": got["data"], "onto": got["ontology"],
                       "pin": got["pin"]})


def served(name: str) -> dict:
    return json.loads(_served(name))


# -- what the file says, read here without the page ---------------------------

def term_of(key: str) -> str:
    m = re.search(r"[/#]([^/#]+)$", key)
    return m.group(1) if m else key


def words_of(raw) -> list:
    if isinstance(raw, list):
        return [str(x) for x in raw[1:]]
    if isinstance(raw, dict):
        return [str(x) for x in raw.get("spellings") or []]
    return []


def label_of(raw) -> str:
    if isinstance(raw, list):
        return "" if not raw or raw[0] is None else str(raw[0])
    return str(raw.get("label") or "") if isinstance(raw, dict) else ""


def axes_of(data: dict, field: dict) -> dict:
    """The field's dimensions as the run asks them, a shared one written
    out."""
    shared = data.get("shared_axes") or {}
    return {n: (shared[n] if a == "shared" else a)
            for n, a in (field.get("axes") or {}).items()}


def has_units(data: dict, field: dict) -> bool:
    return bool(data.get("unit_question")) and bool(field.get("units_accepted"))


def rows_of(data: dict, field: dict) -> list:
    """The rows a field's box must have: its own list, then its unit and its
    dimensions in the order of the questions."""
    order = (data.get("coordinates") or {}).get("order") or []
    names = (["unit"] if has_units(data, field) else []) \
        + list(field.get("axes") or {})
    at = {n: (order.index(n) if n in order else len(order)) for n in names}
    names = sorted(names, key=lambda n: (at[n], names.index(n)))
    return ([VALUE] if isinstance(field.get("vocabulary"), dict) else []) \
        + names


def lists_of(data: dict, field: dict) -> dict:
    """{row: its list} of every row the model answers from a list."""
    axes = axes_of(data, field)
    out = {}
    for name in rows_of(data, field):
        if name == VALUE:
            out[name] = field["vocabulary"]
        elif isinstance((axes.get(name) or {}).get("vocabulary"), dict):
            out[name] = axes[name]["vocabulary"]
    return out


def origin(listed: dict, name, onto: dict):
    """The list of the ontology a list draws from: the one the sources name
    for its dimension, else the one that holds most of its entries (the
    smaller on a tie); None where none holds any."""
    named = onto["axis_sets"].get(name) if name not in (None, VALUE) else None
    chosen = named if named in onto["sets"] else None
    if chosen is None:
        best = 0
        for set_name, one in onto["sets"].items():
            members = set(one["members"])
            held = sum(term_of(k) in members for k in listed)
            if held > best or (held == best and held and len(one["members"])
                               < len(onto["sets"][chosen]["members"])):
                best, chosen = held, set_name
        if not best:
            return None
    return chosen


def drawn(name: str, **extra) -> list:
    """{field, drawing} for each field of the profile."""
    got = served(name)
    fields = got["data"]["parameters"]
    jobs = [{"op": "layout", "data": got["data"], "onto": got["onto"],
             "pin": got["pin"], "uri": f["uri"], **extra} for f in fields]
    return [(f, a) for f, a in zip(fields, run_node(jobs))]


def field_box(drawing: dict) -> dict:
    return next(n for n in drawing["nodes"] if n["type"] == "field")


# -- 1. the ontology gives the rows their entries -----------------------------

def root_problems(data: dict, onto: dict, field: dict, drawing: dict) -> list:
    want = set()
    for row, listed in lists_of(data, field).items():
        chosen = origin(listed, row, onto)
        if chosen:
            want.add(("root:" + chosen, "r:" + row))
    got = {(e["source"], e["targetHandle"]) for e in drawing["edges"]
           if e["kind"] == "root"}
    boxes = {n["id"] for n in drawing["nodes"] if n["type"] == "root"}
    out = []
    if got != want:
        out.append(f"{field['uri']}: arrows {sorted(got ^ want)}")
    if boxes != {s for s, _ in want}:
        out.append(f"{field['uri']}: boxes {sorted(boxes)}")
    return out


@pytest.mark.parametrize("name", PROFILES)
def test_each_list_of_the_ontology_gives_exactly_its_rows(name):
    got = served(name)
    problems = [p for f, a in drawn(name)
                for p in root_problems(got["data"], got["onto"], f,
                                       a["drawing"])]
    assert not problems, problems
    assert any(e["kind"] == "root" for _, a in drawn(name)
               for e in a["drawing"]["edges"]), "no list draws from the ontology"
    # the failure by construction: every arrow of the ontology drawn from
    # its first list
    spoiled = [p for f, a in drawn(name, broken="root_to_first")
               for p in root_problems(got["data"], got["onto"], f,
                                      a["drawing"])]
    if name == "kwp":
        assert spoiled


# -- 2. shared where the file says so -------------------------------------------

def row_problems(data: dict, field: dict, drawing: dict) -> list:
    rows = field_box(drawing)["rows"]
    out = []
    if [r["name"] for r in rows] != rows_of(data, field):
        out.append(f"{field['uri']}: rows {[r['name'] for r in rows]}")
    for r in rows:
        said = (field.get("axes") or {}).get(r["name"]) == "shared"
        if r["shared"] != said:
            out.append(f"{field['uri']}.{r['name']}: shared {r['shared']}")
    return out


@pytest.mark.parametrize("name", PROFILES)
def test_a_dimension_is_shared_where_the_file_says_so(name):
    data = served(name)["data"]
    assert not [p for f, a in drawn(name)
                for p in row_problems(data, f, a["drawing"])]
    # the failure by construction: a dimension of the field's own drawn as a
    # shared one
    assert [p for f, a in drawn(name, broken="own_as_shared")
            for p in row_problems(data, f, a["drawing"])]


# -- 3. what falls under the field, with the words of the plans ---------------

def shown_list(data: dict, field: dict, pick=None):
    lists = lists_of(data, field)
    if pick in lists:
        return pick
    for first in (VALUE, "quantity"):
        if first in lists:
            return first
    return next(iter(lists), None)


def entry_problems(data: dict, field: dict, drawing: dict, pick=None,
                   open_=False) -> list:
    row = shown_list(data, field, pick)
    entries = [n for n in drawing["nodes"] if n["type"] == "entry"]
    more = [n for n in drawing["nodes"] if n["type"] == "more"]
    if row is None:
        return [] if not entries and not more else [f"{field['uri']}: entries"]
    listed = lists_of(data, field)[row]
    want = [(k, words_of(v)) for k, v in listed.items()
            if open_ or words_of(v)]
    folded = sum(1 for v in listed.values() if not words_of(v))
    out = []
    if field_box(drawing)["pick"] != row:
        out.append(f"{field['uri']}: shows {field_box(drawing)['pick']}")
    if [(n["entry"], n["words"]) for n in entries] != want:
        out.append(f"{field['uri']}.{row}: entries")
    if (more[0]["count"] if more else 0) != folded:
        out.append(f"{field['uri']}.{row}: folded")
    return out


@pytest.mark.parametrize("name", PROFILES)
def test_what_falls_under_the_field_is_shown_with_its_words(name):
    data = served(name)["data"]
    problems = []
    for open_ in (False, True):
        for f, a in drawn(name, open=open_):
            problems += entry_problems(data, f, a["drawing"], None, open_)
    # each list the field asks, when its row is chosen
    got = served(name)
    jobs, which = [], []
    for f in got["data"]["parameters"]:
        for row in lists_of(got["data"], f):
            jobs.append({"op": "layout", "data": got["data"], "onto": got["onto"],
                         "pin": got["pin"], "uri": f["uri"], "pick": row})
            which.append((f, row))
    for (f, row), a in zip(which, run_node(jobs)):
        problems += entry_problems(data, f, a["drawing"], row)
    assert not problems, problems
    # the failures by construction: a word left out of its entry, an entry
    # left out of the list
    for broken in ("drop_word", "drop_entry"):
        spoiled = [p for f, a in drawn(name, broken=broken)
                   for p in entry_problems(data, f, a["drawing"])]
        assert spoiled, broken


def test_a_field_whose_value_is_an_entry_shows_its_own_list_first():
    data = served("scenarios")["data"]
    field, answer = next((f, a) for f, a in drawn("scenarios")
                         if f["uri"] == "scenario_type")
    box = field_box(answer["drawing"])
    assert box["rows"][0]["name"] == VALUE and box["pick"] == VALUE
    assert {n["entry"] for n in answer["drawing"]["nodes"]
            if n["type"] == "entry"} <= set(field["vocabulary"])
    # the failure by construction: a field without a list of its own has no
    # such row
    title = next(f for f in data["parameters"] if f["uri"] == "publication_title")
    assert VALUE not in rows_of(data, title)


# -- 4. what the unit decides -----------------------------------------------------

def unit_problems(data: dict, field: dict, drawing: dict) -> list:
    out = []
    edges = drawing["edges"]
    units = [e for e in edges if e["kind"] == "unit"]
    if has_units(data, field) != (units == [{**units[0], "source": "units",
                                              "targetHandle": "r:unit"}]
                                  if units else False):
        out.append(f"{field['uri']}: unit arrow {units}")
    want = {}
    for name, axis in axes_of(data, field).items():
        derive = axis.get("derive") if isinstance(axis, dict) else None
        if isinstance(derive, dict) and derive.get("from") == "unit":
            held = (axis.get("vocabulary") or {}).get(derive["value"])
            want["r:" + name] = label_of(held) or derive["value"]
    got = {e["targetHandle"]: e["label"] for e in edges
           if e["kind"] == "derive" and e["source"] == "units"}
    if got != want:
        out.append(f"{field['uri']}: decided {got} not {want}")
    return out


@pytest.mark.parametrize("name", PROFILES)
def test_the_unit_decides_what_its_arrows_name(name):
    data = served(name)["data"]
    assert not [p for f, a in drawn(name)
                for p in unit_problems(data, f, a["drawing"])]
    # the failure by construction: what the unit decides left undrawn
    spoiled = [p for f, a in drawn(name, broken="no_derive")
               for p in unit_problems(data, f, a["drawing"])]
    if name == "kwp":
        assert spoiled


# -- 5. the drawing leaves the spec as it was ----------------------------------

@pytest.mark.parametrize("name", PROFILES)
def test_drawing_leaves_the_spec_as_it_was(name):
    assert all(a["same"] for open_ in (False, True)
               for _, a in drawn(name, open=open_))
    # the failure by construction: a drawing that marks the field it draws
    assert not all(a["same"] for _, a in drawn(name, broken="mutates"))


# -- 6. a word moves --------------------------------------------------------------

def a_move(data: dict):
    """A word of the plans of the shared carrier list, the entry it stands
    on and another entry that has neither it nor it as its name."""
    listed = data["shared_axes"]["carrier"]["vocabulary"]
    source = next(k for k, v in listed.items() if words_of(v))
    word = words_of(listed[source])[0]
    target = next(k for k, v in listed.items()
                  if k != source and word not in words_of(v)
                  and label_of(v) != word)
    return listed, source, word, target


def move_problems(before: dict, after: dict, source: str, word: str,
                  target: str) -> list:
    was = before["shared_axes"]["carrier"]["vocabulary"]
    now = after["shared_axes"]["carrier"]["vocabulary"]
    out = []
    if words_of(now[source]) != [w for w in words_of(was[source]) if w != word]:
        out.append("the word stays where it was")
    if words_of(now[target]) != words_of(was[target]) + [word]:
        out.append("the word is not on the other entry")
    rest_was = {k: v for k, v in was.items() if k not in (source, target)}
    rest_now = {k: v for k, v in now.items() if k not in (source, target)}
    other_was = copy.deepcopy(before)
    other_now = copy.deepcopy(after)
    del other_was["shared_axes"]["carrier"]["vocabulary"]
    del other_now["shared_axes"]["carrier"]["vocabulary"]
    if rest_was != rest_now or other_was != other_now:
        out.append("something else changed")
    return out


def test_a_word_moves_from_its_entry_to_the_other_and_nothing_else():
    data = served("kwp")["data"]
    listed, source, word, target = a_move(data)
    where = {"uri": None, "name": "carrier", "key": "vocabulary"}
    args = {"where": where, "from": source, "word": word, "to": target}
    named = next(k for k, v in listed.items() if k != source and label_of(v))
    answers = run_node([
        {"op": "move", "data": data, "args": args},
        # refused: a word the entry does not have, a word that is the other
        # entry's name
        {"op": "move", "data": data, "args": {**args, "word": word + " (made up)"}},
        {"op": "move", "data": data, "args": {**args, "word": label_of(listed[named]),
                                              "to": named}},
        # the failure by construction: the word put on the other entry and
        # left where it was
        {"op": "move", "data": data, "args": args, "broken": "copy"},
    ])
    assert answers[0]["said"] is True
    assert move_problems(data, answers[0]["data"], source, word, target) == []
    assert [a["said"] for a in answers[1:3]] == [False, False]
    assert all(a["data"] == data for a in answers[1:3])
    assert move_problems(data, answers[3]["data"], source, word, target) \
        == ["the word stays where it was"]


# -- 7. a field stops sharing ---------------------------------------------------

def unshare_problems(before: dict, answer: dict, uri: str, name: str) -> list:
    after = answer["data"]
    field = next(f for f in after["parameters"] if f["uri"] == uri)
    out = []
    if field["axes"][name] == "shared":
        out.append("the field still shares")
    if after["shared_axes"].get(name) != before["shared_axes"][name]:
        out.append("the shared dimension changed")
    others = [f["uri"] for f in before["parameters"] if f["uri"] != uri
              and (f.get("axes") or {}).get(name) == "shared"]
    if [f["uri"] for f in after["parameters"] if f["uri"] != uri
            and (f.get("axes") or {}).get(name) == "shared"] != others:
        out.append("another field stopped sharing")
    return out


def test_a_field_that_stops_sharing_gets_its_own_copy():
    data = served("kwp")["data"]
    uri, name = "energy_consumption", "carrier"
    edit = {"uri": uri, "name": name, "set": {"question": "Only for this field?"}}
    answers = run_node([
        {"op": "unshare", "data": data, "args": {"uri": uri, "name": name}},
        {"op": "unshare", "data": data, "args": {"uri": uri, "name": name},
         "then": edit},
        # the failure by construction: the "own copy" is the shared object
        {"op": "unshare", "data": data, "args": {"uri": uri, "name": name},
         "broken": "by_reference", "then": edit},
    ])
    plain, edited, spoiled = answers
    assert plain["said"] is True
    assert unshare_problems(data, plain, uri, name) == []
    # what the run asks stays the same: the copy says what the shared one said
    assert spec_module.expanded(plain["data"]) == spec_module.expanded(data)
    assert unshare_problems(data, edited, uri, name) == []
    assert unshare_problems(data, spoiled, uri, name) \
        == ["the shared dimension changed"]
    # and back: the field shares again, the spec as it was
    again = run_node([{"op": "share", "data": plain["data"],
                       "args": {"uri": uri, "name": name}}])[0]
    assert again["said"] == "joined" and again["data"] == data


# -- 8. the order of the questions ----------------------------------------------

def order_problems(answer: dict, wanted: list) -> list:
    out = []
    if answer["data"]["coordinates"]["order"] != wanted:
        out.append("the order is not the one given")
    try:
        spec_module.load(copy.deepcopy(answer["data"]))
    except spec_module.SpecError as exc:
        out.append(f"the spec does not load: {exc}")
    return out


def test_the_order_takes_only_the_same_dimensions():
    data = served("kwp")["data"]
    order = data["coordinates"]["order"]
    flipped = list(reversed(order))
    answers = run_node([
        {"op": "order", "data": data, "args": {"order": flipped}},
        {"op": "order", "data": data, "args": {"order": order[:-1]}},
        {"op": "order", "data": data, "args": {"order": order[:-1] + order[:1]}},
        {"op": "order", "data": data, "args": {"order": order[:-1] + ["made_up"]}},
        # the failure by construction: an order without one dimension taken
        {"op": "order", "data": data, "args": {"order": order[:-1]},
         "broken": "any_order"},
    ])
    assert answers[0]["said"] is True and order_problems(answers[0], flipped) == []
    assert [a["said"] for a in answers[1:4]] == [False, False, False]
    assert all(a["data"] == data for a in answers[1:4])
    assert order_problems(answers[4], order[:-1])


# -- 9. only where the value stands, or once with the number --------------------

def special_problems(answer: dict, name: str, key: str) -> list:
    c = answer["data"]["coordinates"]
    other = "own_value" if key == "own_passage" else "own_passage"
    out = []
    if name not in (c.get(key) or []):
        out.append("not marked")
    if name in (c.get(other) or []):
        out.append("still marked the other way")
    try:
        spec_module.load(copy.deepcopy(answer["data"]))
    except spec_module.SpecError as exc:
        out.append(f"the spec does not load: {exc}")
    return out


def test_marking_one_way_of_reading_takes_away_the_other():
    data = served("kwp")["data"]
    name = data["coordinates"]["own_value"][0]
    args = {"name": name, "key": "own_passage", "on": True}
    answers = run_node([
        {"op": "special", "data": data, "args": args},
        # the failure by construction: a mark that leaves the other standing
        {"op": "special", "data": data, "args": args, "broken": "keep_other"},
    ])
    assert answers[0]["said"] is True
    assert special_problems(answers[0], name, "own_passage") == []
    order = data["coordinates"]["order"]
    marked = answers[0]["data"]["coordinates"]["own_passage"]
    assert marked == sorted(marked, key=order.index)
    assert "still marked the other way" in special_problems(answers[1], name,
                                                            "own_passage")


# -- 10. untangling --------------------------------------------------------------

def tangled() -> dict:
    """A field whose first list draws from one list of the ontology and its
    last three from it too, its second from another: drawn in the order of
    the rows, three arrows cross; the other order leaves one."""
    def listed(*keys):
        return {"vocabulary": {k: {"label": k, "spellings": []} for k in keys}}
    axes = {"d1": listed("A1"), "d2": listed("B1"), "d3": {"type": "text"},
            "d4": {"type": "text"}, "d5": listed("A2"), "d6": listed("A3"),
            "d7": listed("A4")}
    data = {"parameters": [{"uri": "f", "label": "F", "axes": axes}],
            "coordinates": {"order": list(axes)}}
    one = {"kind": "class", "label": None, "definition": None}
    onto = {"sets": {"A": {"root": "A", "members": ["A1", "A2", "A3", "A4"], **one},
                     "B": {"root": "B", "members": ["B1"], **one}},
            "axis_sets": {}}
    return {"op": "untangle", "data": data, "onto": onto, "pin": {}, "uri": "f"}


def untangle_problems(answer: dict) -> list:
    out = []
    if answer["after"] > answer["before"]:
        out.append("more crossings than before")
    if answer["drawn"] != answer["order"]:
        out.append("the drawing does not keep the order found")
    if answer["counted"] != answer["after"]:
        out.append("the drawing has another count than the one said")
    return out


def test_untangling_never_adds_crossings_and_the_drawing_keeps_the_order():
    case = tangled()
    answer = run_node([case])[0]
    assert (answer["before"], answer["after"]) == (3, 1)
    assert answer["drawn"] == ["root:B", "root:A"]
    assert untangle_problems(answer) == []
    for name in PROFILES:
        got = served(name)
        jobs = [{"op": "untangle", "data": got["data"], "onto": got["onto"],
                 "pin": got["pin"], "uri": f["uri"]}
                for f in got["data"]["parameters"]]
        assert not [p for a in run_node(jobs) for p in untangle_problems(a)]
    # the failure by construction: a drawing that ignores the order found
    spoiled = run_node([{**case, "broken": "ignore_kept"}])[0]
    assert untangle_problems(spoiled) == [
        "the drawing does not keep the order found",
        "the drawing has another count than the one said"]


# -- boxes moved by hand (lib/moved.ts, as the Spec, Graph and Flow tabs use it)

def boxes(*names) -> list:
    return [{"id": name, "type": "box", "position": {"x": 0, "y": 100 * i},
             "data": {}} for i, name in enumerate(names)]


def places(answer: dict) -> dict:
    return {n["id"]: (n["x"], n["y"]) for n in answer["shown"]}


def drag_problems(answer: dict, layout: dict, moved: dict) -> list:
    """What breaks the promise: a box moved by hand stands where it was put
    (`moved`), every other box where the layout put it, and the layout's
    own boxes are as they were."""
    out = []
    at = places(answer)
    for name, place in moved.items():
        if at[name] != place:
            out.append(f"{name} is not where it was put")
    for name, place in layout.items():
        if name not in moved and at[name] != place:
            out.append(f"{name} moved without being moved")
    if not answer["same"]:
        out.append("the layout's own boxes changed")
    return out


def test_a_box_moved_by_hand_stays_where_it_was_put_and_nothing_else_moves():
    layout = {"a": (0, 0), "b": (0, 100), "c": (0, 200)}
    job = {"op": "drag", "nodes": boxes("a", "b", "c"),
           "drags": [{"id": "b", "x": 50, "y": 60},
                     {"id": "b", "x": 70, "y": 80}]}
    answer = run_node([job])[0]
    assert answer["said"] == [True, True]
    assert drag_problems(answer, layout, {"b": (70, 80)}) == []
    # what the drawing reports that is no move moves nothing
    still = {"op": "drag", "nodes": boxes("a", "b", "c"), "drags": [
        {"changes": [{"type": "select", "id": "b", "selected": True},
                     {"type": "dimensions", "id": "b"},
                     {"type": "position", "id": "b"},
                     {"type": "position", "id": "gone",
                      "position": {"x": 5, "y": 5}}]}]}
    quiet = run_node([still])[0]
    assert quiet["said"] == [False]
    assert drag_problems(quiet, layout, {}) == []
    # the failure by construction: a box that goes back to the layout, all
    # boxes moving with the one dragged, the places written into the layout
    spoiled = run_node([{**job, "broken": broken}
                        for broken in ("no_keep", "move_all", "mutate")])
    assert drag_problems(spoiled[0], layout, {"b": (70, 80)}) \
        == ["b is not where it was put"]
    assert drag_problems(spoiled[1], layout, {"b": (70, 80)}) \
        == ["a moved without being moved", "c moved without being moved"]
    assert drag_problems(spoiled[2], layout, {"b": (70, 80)}) \
        == ["the layout's own boxes changed"]


def test_the_frame_of_the_entries_takes_its_entries_along():
    got = served("scenarios")
    job = {"op": "drag", "data": got["data"], "onto": got["onto"],
           "pin": got["pin"], "uri": "scenario_type"}
    laid = run_node([{**job, "drags": []}])[0]
    layout = places(laid)
    frame = next(n for n in laid["shown"] if n["type"] == "frame")
    carried = set(frame["carries"])
    # the frame carries exactly the boxes drawn inside it
    assert carried == {n["id"] for n in laid["shown"]
                       if n["type"] in ("entry", "more")} and carried
    x, y = layout["frame"]
    moved = {"frame": (x + 100, y + 40)}
    moved.update({name: (layout[name][0] + 100, layout[name][1] + 40)
                  for name in carried})
    answer = run_node([{**job, "drags": [
        {"id": "frame", "x": x + 100, "y": y + 40}]}])[0]
    assert drag_problems(answer, layout, moved) == []
    # the failure by construction: a frame that leaves its entries behind
    spoiled = run_node([{**job, "broken": "no_carry", "drags": [
        {"id": "frame", "x": x + 100, "y": y + 40}]}])[0]
    left = drag_problems(spoiled, layout, moved)
    assert left and all(p.endswith("is not where it was put")
                        for p in left)
    assert len(left) == len(carried)
