"""
test_editor_spec_terms.py: the terms of a list of the ontology in the Spec
tab of `docpipe edit` (docpipe/editor/ui/src/spec/terms.ts, the panel of a
list of the ontology and the dialog "Add entry"), and what the page gets of
them (`specs.ontology_lists`).

The promise, in one sentence: the page gets every term the snapshot carries
under each list of the ontology with its name, definition and the terms it
stands under as the snapshot has them; the panel lists each of those terms
once, right under a term it stands under or, where it stands under none of
them, at the top; a term is marked as in the list of the spec exactly where
a key of that list names it, in whatever spelling; the panel compares with
every list of the spec that takes its entries from the list of the ontology
AND first with the one of the row it was opened from; putting terms in adds
exactly the terms the list does not hold, each under the key the list spells
its family with AND with the name and definition of the ontology AND after
the last entry the list takes from that list of the ontology (before its own
answers where it takes none), leaving every entry it had as it was and where
it was. Each part has a case that breaks it by construction.

The modules are the page's own TypeScript, run by node with their types
stripped; those tests are skipped where node cannot do that.

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

ROOT = Path(__file__).resolve().parent.parent
DRIVER = ROOT / "tests" / "editor_spec_terms_driver.mjs"
NODE = shutil.which("node")
OEO = "https://openenergyplatform.org/ontology/oeo/"


def _strips_types() -> bool:
    if NODE is None:
        return False
    done = subprocess.run([NODE, "-p", "process.features.typescript"],
                          capture_output=True, text=True, timeout=30)
    return done.returncode == 0 and done.stdout.strip() in ("strip",
                                                            "transform")


needs_node = pytest.mark.skipif(not _strips_types(),
                                reason="no node that strips TypeScript types")


def run_node(jobs: list) -> list:
    done = subprocess.run([NODE, str(DRIVER)], input=json.dumps(jobs),
                          capture_output=True, text=True, encoding="utf-8",
                          timeout=120)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


@functools.lru_cache(maxsize=None)
def _served(name: str) -> str:
    """What the page gets of the profile's spec (GET /api/spec), and the
    snapshot the server read."""
    from docpipe.editor import server
    from docpipe.profile import load_profile

    profile = load_profile(name)
    app = server.App(profile, None, ROOT)
    app.spec_path = Path(profile.package_dir) / "extraction_spec.json"
    status, got = app.call("GET", "/api/spec", {}, None)
    assert status == 200, got
    return json.dumps({"data": got["data"], "onto": got["ontology"],
                       "pin": got["pin"], "snapshot": app.snapshot()})


def served(name: str) -> dict:
    return json.loads(_served(name))


def term_of(key: str) -> str:
    m = re.search(r"[/#]([^/#]+)$", key)
    return m.group(1) if m else key


# -- 1. the page gets every term with its name ------------------------------------

def given_problems(onto: dict, snapshot: dict) -> list:
    """Where the terms the page got are not the snapshot's terms under its
    lists."""
    terms = snapshot["terms"]
    out = []
    wanted = {m for one in onto["sets"].values() for m in one["members"]}
    if set(onto["terms"]) != wanted:
        out.append(f"terms {sorted(set(onto['terms']) ^ wanted)[:5]}")
    for key in sorted(wanted & set(onto["terms"])):
        got, want = onto["terms"][key], terms[key]
        for part in ("label", "definition", "parents"):
            if got.get(part) != want.get(part):
                out.append(f"{key}: {part}")
    return out


def test_the_page_gets_every_term_under_every_list_with_its_name():
    got = served("kwp")
    onto, snapshot = got["onto"], got["snapshot"]
    assert onto["sets"]["heat_generation_technology"]["members"]
    assert given_problems(onto, snapshot) == []
    # the failure by construction: a term left out, another with a name
    # that is not the snapshot's
    spoiled = copy.deepcopy(onto)
    gone = onto["sets"]["heat_generation_technology"]["members"][0]
    del spoiled["terms"][gone]
    other = onto["sets"]["sector"]["members"][0]
    spoiled["terms"][other]["label"] += " (made up)"
    assert given_problems(spoiled, snapshot) == [f"terms {[gone]}",
                                                f"{other}: label"]


# -- 2. each term once, under a term it stands under ---------------------------------

def tree_problems(one: dict, onto: dict, rows: list) -> list:
    members = one["members"]
    out = []
    ids = [r["id"] for r in rows]
    if sorted(ids) != sorted(members) or len(set(ids)) != len(ids):
        out.append(f"{one['root']}: terms {sorted(set(ids) ^ set(members))}")
    for i, r in enumerate(rows):
        above = [p for p in onto["terms"][r["id"]]["parents"] if p in members]
        if r["depth"] == 0:
            if above:
                out.append(f"{r['id']} at the top, under {above}")
            continue
        parent = next((rows[j]["id"] for j in range(i - 1, -1, -1)
                       if rows[j]["depth"] == r["depth"] - 1), None)
        if parent not in above:
            out.append(f"{r['id']} under {parent}")
    return out


@needs_node
def test_each_term_stands_once_under_a_term_it_stands_under():
    got = served("kwp")
    onto = got["onto"]
    sets = list(onto["sets"].values())
    answers = run_node([{"op": "rows", "set": one, "terms": onto["terms"],
                         "list": {}} for one in sets])
    assert not [p for one, rows in zip(sets, answers)
                for p in tree_problems(one, onto, rows)]
    # the case is real: a list of the ontology whose terms stand under each
    # other
    assert any(r["depth"] > 0 for rows in answers for r in rows)
    # the failures by construction: every term right under the root, a term
    # left out
    for broken in ("flat", "drop"):
        spoiled = run_node([{"op": "rows", "set": one, "terms": onto["terms"],
                             "list": {}, "broken": broken} for one in sets])
        assert [p for one, rows in zip(sets, spoiled)
                for p in tree_problems(one, onto, rows)], broken


# -- 3. in the list under any spelling ---------------------------------------------

def as_iris(listed: dict) -> dict:
    """The list with every key of the OEO written as its IRI, in its order."""
    return {(OEO + k if k.startswith("OEO_") else k): v
            for k, v in listed.items()}


def held_problems(one: dict, listed: dict, rows: list) -> list:
    want = {term_of(k): k for k in listed if term_of(k) in one["members"]}
    got = {r["id"]: r["held"] for r in rows if r["held"] is not None}
    return [] if got == want else [f"held {sorted(set(got.items()) ^ set(want.items()))}"]


@needs_node
def test_a_term_is_in_the_list_under_any_spelling():
    got = served("kwp")
    onto = got["onto"]
    one = onto["sets"]["heat_generation_technology"]
    bare = got["data"]["shared_axes"]["technology"]["vocabulary"]
    partly = {k: v for k, v in list(bare.items())[2:]}
    cases = [bare, as_iris(bare), as_iris(partly)]
    answers = run_node([{"op": "rows", "set": one, "terms": onto["terms"],
                         "list": listed} for listed in cases])
    assert [held_problems(one, listed, rows)
            for listed, rows in zip(cases, answers)] == [[], [], []]
    assert sum(r["held"] is None for r in answers[2]) == 2
    # the failure by construction: a term held only under its bare
    # identifier
    spoiled = run_node([{"op": "rows", "set": one, "terms": onto["terms"],
                         "list": as_iris(bare), "broken": "exact"}])[0]
    assert held_problems(one, as_iris(bare), spoiled)


# -- 4. the lists it is held against -----------------------------------------------

def origin(listed: dict, name, onto: dict):
    """The list of the ontology a list of the spec takes its entries from:
    the one the sources name for its dimension, else the one that holds most
    of its entries (the smaller on a tie); None where none holds any (as
    spec/model.ts originOf)."""
    named = onto["axis_sets"].get(name) if name is not None else None
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


def lists_from(data: dict, onto: dict, set_name: str) -> list:
    out = []
    for name, axis in (data.get("shared_axes") or {}).items():
        if isinstance((axis or {}).get("vocabulary"), dict) \
                and origin(axis["vocabulary"], name, onto) == set_name:
            out.append({"uri": None, "name": name, "key": "vocabulary"})
    for field in data["parameters"]:
        if isinstance(field.get("vocabulary"), dict) \
                and origin(field["vocabulary"], None, onto) == set_name:
            out.append({"uri": field["uri"], "name": None, "key": "vocabulary"})
        for name, axis in (field.get("axes") or {}).items():
            if isinstance(axis, dict) and isinstance(axis.get("vocabulary"), dict) \
                    and origin(axis["vocabulary"], name, onto) == set_name:
                out.append({"uri": field["uri"], "name": name,
                            "key": "vocabulary"})
    return out


@needs_node
def test_the_panel_compares_with_every_list_that_takes_from_it():
    problems = []
    for profile in ("kwp", "scenarios"):
        got = served(profile)
        names = list(got["onto"]["sets"])
        answers = run_node([{"op": "lists", "data": got["data"],
                             "onto": got["onto"], "set": n} for n in names])
        for n, a in zip(names, answers):
            if a["lists"] != lists_from(got["data"], got["onto"], n):
                problems.append(f"{profile} {n}: {a['lists']}")
    assert not problems, problems
    got = served("kwp")
    quantity = lists_from(got["data"], got["onto"], "quantity_value")
    # the case is real: each field asks its own list of quantities
    assert len(quantity) >= 4 and all(w["uri"] for w in quantity)
    # the failure by construction: the fields' own lists left out
    spoiled = run_node([{"op": "lists", "data": got["data"],
                         "onto": got["onto"], "set": "quantity_value",
                         "broken": "shared_only"}])[0]
    assert spoiled["lists"] != quantity


def at_problems(data: dict, field: dict, roots: list) -> list:
    """Where a box of the ontology in a field's drawing is not opened with
    the list of the first row it gives entries to."""
    out = []
    for box in roots:
        row = box["feeds"][0]
        if row == "@value":
            want = {"uri": field["uri"], "name": None, "key": "vocabulary"}
        else:
            shared = (field.get("axes") or {}).get(row) == "shared"
            want = {"uri": None if shared else field["uri"], "name": row,
                    "key": "vocabulary"}
        if box["at"] != want:
            out.append(f"{field['uri']} {box['set']}: {box['at']}")
    return out


@needs_node
def test_the_panel_compares_first_with_the_list_it_was_opened_from():
    got = served("kwp")
    fields = got["data"]["parameters"]
    jobs = [{"op": "roots", "data": got["data"], "onto": got["onto"],
             "pin": got["pin"], "uri": f["uri"]} for f in fields]
    assert not [p for f, roots in zip(fields, run_node(jobs))
                for p in at_problems(got["data"], f, roots)]
    # the panel takes that list among those it compares with
    quantity = lists_from(got["data"], got["onto"], "quantity_value")
    last = quantity[-1]
    chosen = run_node([{"op": "lists", "data": got["data"], "onto": got["onto"],
                        "set": "quantity_value", "at": last}])[0]["chosen"]
    assert chosen == last
    # the failures by construction: every box opened with a shared list, a
    # panel that compares with its first list whatever it was opened from
    spoiled = run_node([{**job, "broken": "at_shared"} for job in jobs])
    assert [p for f, roots in zip(fields, spoiled)
            for p in at_problems(got["data"], f, roots)]
    first = run_node([{"op": "lists", "data": got["data"], "onto": got["onto"],
                       "set": "quantity_value", "at": last,
                       "broken": "first"}])[0]["chosen"]
    assert first != last


# -- 5. putting terms in -------------------------------------------------------------

def put_problems(before: dict, answer: dict, one: dict, terms: dict,
                 ids: list) -> list:
    after, added = answer["list"], answer["added"]
    out = []
    held = {term_of(k) for k in before}
    want = [i for i in dict.fromkeys(ids) if i not in held]
    if [a["id"] for a in added] != want:
        out.append(f"added {[a['id'] for a in added]}, not {want}")
    if len(after) != len(before) + len(want) \
            or sorted({term_of(k) for k in after}) != sorted(held | set(want)):
        out.append("the list holds a term twice or misses one")
    # spelled as the list spells the terms of its family
    spelled = {term_of(k).split("_")[0]: k[:-len(term_of(k))]
               for k in before if term_of(k) != k}
    for a in added:
        if a["key"] != spelled.get(a["id"].split("_")[0], "") + a["id"]:
            out.append(f"{a['id']} under {a['key']}")
    # with the name and definition of the ontology
    for a in added:
        term = terms[a["id"]]
        entry = {"label": term["label"]}
        if term.get("definition"):
            entry["definition"] = term["definition"]
        if after.get(a["key"]) != entry:
            out.append(f"{a['id']}: {after.get(a['key'])}")
    # every entry it had as it was and where it was, the new ones after the
    # last entry from that list of the ontology, else before its own answers
    keys = answer["keys"]
    new = [a["key"] for a in added]
    if [k for k in keys if k not in new] != list(before) \
            or any(after[k] != before[k] for k in before):
        out.append("an entry it had changed or moved")
    if new:
        old = list(before)
        from_it = [i for i, k in enumerate(old) if term_of(k) in one["members"]]
        own = [i for i, k in enumerate(old) if k.startswith("out:")]
        at = from_it[-1] + 1 if from_it else own[0] if own else len(old)
        if keys[at:at + len(new)] != new:
            out.append(f"put in at {keys.index(new[0])}, not {at}")
    if not answer["same"]:
        out.append("the list given changed")
    return out


@needs_node
def test_putting_terms_in_adds_exactly_the_missing_ones_where_they_belong():
    got = served("kwp")
    onto = got["onto"]
    terms = onto["terms"]
    quantity = onto["sets"]["quantity_value"]
    tech = onto["sets"]["heat_generation_technology"]
    asked = got["data"]["parameters"][0]["axes"]["quantity"]["vocabulary"]
    bare = got["data"]["shared_axes"]["technology"]["vocabulary"]
    # two of its terms taken out: they go back before "Summe" and "Sonstige"
    some = {k: v for k, v in list(bare.items())[2:]}
    gone = list(bare)[:2]
    cases = [
        (asked, quantity, quantity["members"]),
        (as_iris(some), tech, tech["members"]),
        (some, tech, gone + gone),
        ({"out:other": {"label": "other"}}, tech, gone),
        ({}, tech, gone),
        (as_iris(bare), tech, gone),
    ]
    jobs = [{"op": "put", "list": listed, "set": one, "ids": ids,
             "terms": terms} for listed, one, ids in cases]
    answers = run_node(jobs)
    assert [put_problems(listed, a, one, terms, ids)
            for (listed, one, ids), a in zip(cases, answers)] == [[]] * len(cases)
    # the cases are real: many quantities missing, the two taken out spelled
    # as IRIs before the list's own answers, nothing put in twice
    assert len(answers[0]["added"]) > 50
    assert [a["key"] for a in answers[1]["added"]] \
        == [OEO + i for i in tech["members"] if i in gone]
    assert answers[1]["keys"][-2:] == ["out:total", "out:other"]
    assert answers[5]["added"] == []
    # the failures by construction: every term under its bare identifier,
    # the new entries at the end, a term put in that the list holds under its
    # IRI
    for broken, case in (("bare", 1), ("at_end", 1), ("twice", 5)):
        listed, one, ids = cases[case]
        spoiled = run_node([{**jobs[case], "broken": broken}])[0]
        assert put_problems(listed, spoiled, one, terms, ids), broken
