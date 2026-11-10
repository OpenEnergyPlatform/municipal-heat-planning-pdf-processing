"""What the editor promises of a profile's spec (`docpipe edit`, owner decision
2026-11-10), held to in `docpipe.editor.specs` without a page:

  1. only a spec the run's loader takes is written;
  2. a save changes the lines an edit changed and no others;
  3. what an edit costs is said with the run's own fingerprints;
  4. what the form does not know stays in the file;
  7. a copy has a key of its own and no example;
  8. a removal says what it costs and is written only when confirmed.

Each promise has a case that breaks it by construction beside the one that
keeps it. (5, that bringing both specs into the one writing form changed no
question, was shown once when they were rewritten: all 64 and 44 keys equal.
It is no test, because a later edit of a spec moves its keys by right. 6 and
10, the file guard and the harvest folder, are the server's:
test_editor_server.py.)"""
import copy
import json
from pathlib import Path

import pytest

from docpipe.editor import specs
from docpipe.extraction.spec import fingerprints, load

ROOT = Path(__file__).resolve().parent.parent
FILES = {name: ROOT / "profiles" / name / "extraction_spec.json"
         for name in ("kwp", "scenarios")}
RAW = {name: path.read_bytes() for name, path in FILES.items()}
KWP = specs.parse(RAW["kwp"])


def edited(change, name: str = "kwp") -> dict:
    data = specs.parse(RAW[name])
    change(data)
    return data


def quantity(data: dict) -> dict:
    """The list of the coordinate that says which quantity a number is."""
    return data["parameters"][0]["axes"]["quantity"]["vocabulary"]


def one_more_spelling(data: dict) -> None:
    # Where the page puts a new spelling: right after the entry's name.
    quantity(data)["OEO_00050016"]["spellings"].insert(0, "Endenergieeinsatz")


# -- 1. only what the loader takes is written -----------------------------------

def test_a_spec_the_loader_refuses_is_not_written_and_names_the_field():
    broken = edited(lambda d: d["parameters"][0].update(value_type="money"))
    report, written = specs.save(RAW["kwp"], broken)
    assert written is None
    assert (report["saved"], report["reason"]) == (False, "check")
    assert report["error"]["where"] == "spec.parameters[0].value_type"
    # the same edit with a kind of value the loader knows is written
    report, written = specs.save(RAW["kwp"], edited(one_more_spelling))
    assert report["saved"] and specs.parse(written) == edited(
        one_more_spelling)


def test_a_key_a_browser_would_move_is_refused():
    numbered = edited(lambda d: d["parameters"][0]["kg"].update({"2021": 1}))
    assert specs.problem(numbered)["where"].endswith(".kg.2021")
    assert specs.problem(KWP) is None


# -- 2. a save changes the edited lines only -------------------------------------

@pytest.mark.parametrize("name", sorted(FILES))
def test_an_unchanged_spec_is_written_as_the_file_it_was_read_from(name):
    raw = RAW[name]
    assert specs.dump(specs.parse(raw), specs.newline_of(raw)).encode(
        "utf-8") == raw
    report, written = specs.save(raw, specs.parse(raw))
    assert written == raw and report["lines"] == {"added": 0, "removed": 0}


def through_a_browser(node):
    """A spec as a page sends it back: JavaScript has one kind of number,
    so the file's 1.0 comes back as 1."""
    if isinstance(node, dict):
        return {key: through_a_browser(value) for key, value in node.items()}
    if isinstance(node, list):
        return [through_a_browser(value) for value in node]
    if isinstance(node, float) and node.is_integer():
        return int(node)
    return node


@pytest.mark.parametrize("name", sorted(FILES))
def test_a_spec_that_went_through_a_browser_is_written_as_the_file(name):
    raw = RAW[name]
    sent = through_a_browser(specs.parse(raw))
    report, written = specs.save(raw, sent)
    assert written == raw and report["lines"] == {"added": 0, "removed": 0}
    # A copied field moves the fields after it, and their numbers still are
    # the file's.
    if name == "kwp":
        copied = specs.copy_field(sent, "energy_consumption", "energy_demand")
        copied["parameters"][1]["example"] = copy.deepcopy(
            sent["parameters"][0]["example"])
        lines = specs.judge(raw, copied)["lines"]
        assert lines["removed"] == 0 and lines["added"] > 100
        # the failure by construction: the hazard is real, written as sent
        # the file would lose every ".0"
        assert specs.dump(sent, specs.newline_of(raw)).encode("utf-8") != raw


def test_one_more_spelling_is_one_more_line_in_the_file_s_line_endings():
    report, written = specs.save(RAW["kwp"], edited(one_more_spelling))
    assert report["lines"] == {"added": 1, "removed": 0}
    before = RAW["kwp"].split(b"\n")
    after = written.split(b"\n")
    assert len(after) == len(before) + 1
    known = set(before)
    assert [line for line in after if line not in known] == [
        line for line in after if b"Endenergieeinsatz" in line]
    # The line endings of the file, whichever they are.
    ending = b"\r\n" if b"\r\n" in RAW["kwp"] else b"\n"
    assert all(line.endswith(b"\r") for line in after[:-1]) == (
        ending == b"\r\n")
    # the failure by construction: the same file in the other line ending
    # is written in that one
    other = RAW["kwp"].replace(b"\r\n", b"\n")
    if other == RAW["kwp"]:
        other = RAW["kwp"].replace(b"\n", b"\r\n")
    _, rewritten = specs.save(other, edited(one_more_spelling))
    assert (b"\r\n" in rewritten) == (b"\r\n" in other)


# -- 3. the changed questions, by the run's fingerprints -------------------------

def moved(change, name: str = "kwp") -> dict:
    report = specs.judge(RAW[name], edited(change, name))
    return {c["key"]: (c["state"], c["effect"]) for c in report["changes"]}


def test_a_new_spelling_moves_the_key_of_its_coordinate_and_no_other():
    assert moved(one_more_spelling) == {
        "axis/energy_consumption/quantity": ("changed", specs.REMAP)}


def test_a_changed_definition_moves_the_key_of_its_field():
    assert moved(lambda d: d["parameters"][0].update(
        description=d["parameters"][0]["description"] + " Und mehr.")) == {
        "parameter/energy_consumption": ("changed", specs.READ)}


def test_a_comment_a_graph_note_and_a_settled_text_move_no_key():
    def reworded(data):
        data["_comment"].append("Eine Anmerkung.")
        data["parameters"][0]["kg"]["note"] = "Eine Anmerkung zum Graphen."
        data["plan_fields"]["target_year"]["means"] += " Auch ein Etappenziel."
    assert moved(reworded) == {}
    # and the file still changes, so "no key" is not "no edit"
    assert specs.judge(RAW["kwp"], edited(reworded))["lines"]["added"] > 0


def test_the_keys_named_are_the_ones_the_run_compares():
    data = edited(one_more_spelling)
    before, after = fingerprints(load(KWP)), fingerprints(load(data))
    assert {c["key"] for c in specs.judge(RAW["kwp"], data)["changes"]} == {
        key for key in after if before.get(key) != after[key]}


def test_a_list_that_lost_a_spelling_is_not_said_to_have_grown():
    def one_fewer(data):
        quantity(data)["OEO_00050016"]["spellings"].pop()
    assert moved(one_fewer) == {
        "axis/energy_consumption/quantity": ("changed", specs.READ)}


def test_the_documents_an_edit_makes_stale_are_counted_at_their_stamps(
        tmp_path):
    current = fingerprints(load(KWP))
    (tmp_path / "plan_a.stamp.json").write_text(json.dumps(current),
                                                encoding="utf-8")
    # A stamp that was stale in this key before the edit is not its doing.
    (tmp_path / "plan_b.stamp.json").write_text(json.dumps(
        {**current, "axis/energy_consumption/quantity": "older"}),
        encoding="utf-8")
    stamps = sorted(tmp_path.glob("*.stamp.json"))
    report = specs.judge(RAW["kwp"], edited(one_more_spelling), stamps)
    (change,) = report["changes"]
    assert change["documents"] == ["plan_a"]
    assert report["documents_note"] is None
    # the failure by construction: without a harvest nothing is counted and
    # the report says why
    report = specs.judge(RAW["kwp"], edited(one_more_spelling), None)
    assert report["changes"][0]["documents"] is None
    assert report["documents_note"] == specs.NO_HARVEST


# -- 4. what the form does not know stays ---------------------------------------

def test_a_key_the_form_does_not_know_is_written_back_where_it_stood():
    known = {field["key"] for field in specs.form()["parameter"]}
    assert "mystery" not in known

    def with_mystery(data):
        first = data["parameters"][0]
        data["parameters"][0] = {"uri": first["uri"], "mystery": {"a": [1]},
                                 **{k: v for k, v in first.items()
                                    if k != "uri"}}
    raw = specs.dump(edited(with_mystery)).encode("utf-8")
    report, written = specs.save(raw, edited(
        lambda d: (with_mystery(d), one_more_spelling(d))))
    assert report["saved"] and report["lines"] == {"added": 1, "removed": 0}
    assert list(specs.parse(written)["parameters"][0])[:2] == [
        "uri", "mystery"]


def test_the_form_s_help_is_the_comment_of_the_code():
    by_key = {field["key"]: field for field in specs.form()["axis"]}
    assert by_key["question"]["help"].startswith(
        "The one line the field request asks.")
    assert by_key["several"]["widget"] == "bool"
    # Every key of both specs' coordinates is a key of the form or one of
    # the four kinds a coordinate is, so the form leaves none of today's
    # keys unexplained.
    kinds = {"vocabulary", "type", "enum", "dynamic", "beside"}
    used = {key for raw in RAW.values()
            for parameter in specs.parse(raw)["parameters"]
            for axis in parameter["axes"].values() for key in axis}
    assert used <= set(by_key) | kinds


# -- 7. a copy ---------------------------------------------------------------------

def test_a_copied_field_needs_a_key_and_an_example_of_its_own():
    with pytest.raises(specs.Refused, match="taken"):
        specs.copy_field(KWP, "energy_consumption", "emission")
    with pytest.raises(specs.Refused, match="key of its own"):
        specs.copy_field(KWP, "energy_consumption", " ")
    copied = specs.copy_field(KWP, "energy_consumption", "energy_demand")
    made = copied["parameters"][1]
    original = KWP["parameters"][0]
    assert made["uri"] == "energy_demand" and "example" not in made
    assert made["axes"] == original["axes"]
    # Without an example of its own it is not written, with one it is.
    report, written = specs.save(RAW["kwp"], copied)
    assert written is None and report["error"]["where"] == (
        "spec.parameters[1].example")
    made["example"] = copy.deepcopy(original["example"])
    report, written = specs.save(RAW["kwp"], copied)
    assert report["saved"] and written is not None
    # What it costs is the pass that appends a field, for every key.
    assert {c["effect"] for c in report["changes"]} == {specs.APPEND}
    assert {"parameter/energy_demand", "slot/parameter"} <= {
        c["key"] for c in report["changes"]}
    assert report["removed"] == []


def test_a_copied_coordinate_joins_the_group_of_its_original():
    copied = specs.copy_coordinate(KWP, "energy_consumption", "carrier",
                                   "carrier_of_origin")
    axes = list(copied["parameters"][0]["axes"])
    assert axes[axes.index("carrier") + 1] == "carrier_of_origin"
    (group,) = [name for name, group in KWP["groups"].items()
                if "carrier" in group["coordinates"]]
    listed = copied["groups"][group]["coordinates"]
    assert listed[listed.index("carrier") + 1] == "carrier_of_origin"
    assert specs.problem(copied) is None
    with pytest.raises(specs.Refused, match="taken"):
        specs.copy_coordinate(KWP, "energy_consumption", "carrier", "sector")


# -- 8. a removal -------------------------------------------------------------------

def test_a_removed_entry_says_its_key_and_is_written_only_when_confirmed(
        tmp_path):
    (tmp_path / "plan_a.stamp.json").write_text(
        json.dumps(fingerprints(load(KWP))), encoding="utf-8")
    stamps = [tmp_path / "plan_a.stamp.json"]
    without = specs.remove(KWP, "entry", field="energy_consumption",
                           coordinate="quantity", list="vocabulary",
                           entry="OEO_00050016")
    report, written = specs.save(RAW["kwp"], without, stamps=stamps)
    assert written is None and report["reason"] == "confirm"
    assert report["removed"] == [
        "entry OEO_00050016 of coordinate energy_consumption.quantity"]
    assert [(c["key"], c["documents"]) for c in report["changes"]] == [
        ("axis/energy_consumption/quantity", ["plan_a"])]
    report, written = specs.save(RAW["kwp"], without, stamps=stamps,
                                 confirm=True)
    assert report["saved"] and "OEO_00050016" not in quantity(
        specs.parse(written))
    # the failure by construction: an edit that takes nothing away needs no
    # confirmation
    assert specs.save(RAW["kwp"], edited(one_more_spelling))[0]["saved"]


def test_what_follows_from_a_removal_goes_with_it():
    scenarios = specs.parse(RAW["scenarios"])
    without = specs.remove(scenarios, "field", field="study_acronym")
    assert "study_acronym" not in without["works"]["fields"]
    assert specs.problem(without) is None
    assert set(specs.removed(scenarios, without)) == {
        "field study_acronym",
        "question for study_acronym of the list of other works"}
    # A coordinate only one field has leaves its group with the field.
    lone = specs.remove(KWP, "coordinate", field="share", coordinate="whole")
    assert all("whole" not in group["coordinates"]
               for group in lone["groups"].values())
    assert specs.problem(lone) is None
    # One that other fields still have stays in its group.
    shared = specs.remove(KWP, "coordinate", field="share",
                          coordinate="carrier")
    assert any("carrier" in group["coordinates"]
               for group in shared["groups"].values())
    assert specs.problem(shared) is None
    with pytest.raises(specs.Refused, match="no such field"):
        specs.remove(KWP, "field", field="colour")
    with pytest.raises(specs.Refused, match="its name is changed"):
        specs.remove(KWP, "spelling", field="energy_consumption",
                     coordinate="quantity", entry="OEO_00050016",
                     spelling="final energy consumption value")


def test_the_definition_beside_an_entry_is_the_snapshot_s():
    snapshot = {"terms": {"OEO_00050016": {
        "label": "final energy consumption value", "alt_labels": [],
        "definition": "Another sentence than the spec's.",
        "deprecated": False}}}
    (note,) = [n for n in specs.notes(KWP, snapshot)
               if n["where"] == "energy_consumption.quantity"]
    assert (note["id"], note["kind"]) == ("OEO_00050016", "rewritten")
    assert specs.pin(KWP, snapshot)["OEO_00050016"]["definition"] == (
        "Another sentence than the spec's.")
    # the failure by construction: the spec's own sentence is no difference
    same = {"terms": {"OEO_00050016": {
        **snapshot["terms"]["OEO_00050016"],
        "definition": quantity(KWP)["OEO_00050016"]["definition"]}}}
    assert not [n for n in specs.notes(KWP, same)
                if n["where"] == "energy_consumption.quantity"]


def test_a_new_entry_is_found_by_the_words_of_its_term_in_any_order():
    snapshot = {"terms": {
        "OEO_00050016": {"label": "final energy consumption value",
                         "alt_labels": ["Endenergieverbrauch"]},
        "OEO_00140080": {"label": "final energy carrier", "alt_labels": []}}}
    found = specs.terms(snapshot, "consumption final")
    assert [term["id"] for term in found["terms"]] == ["OEO_00050016"]
    assert specs.terms(snapshot, "endenergie")["total"] == 1
    assert specs.terms(snapshot, "")["total"] == 2
    # the failure by construction: a word no term has finds none
    assert specs.terms(snapshot, "final heat")["total"] == 0
