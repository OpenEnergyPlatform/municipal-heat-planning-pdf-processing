"""What a harvest says beyond its accepted values, served.

What is promised, sentence by sentence:

  * the values, the parameter states AND the refusals of a harvest are read
    in one pass over the same files AND a trace file is no document AND a
    line that cannot be used is counted and not served;
  * a parameter of a document has the state its state line says, as the
    harvest wrote it AND where the file has state lines and none for the
    parameter it is never_asked AND where the file has none at all it is
    not_recorded AND no one of the six is taken for another;
  * a document or a parameter the harvest does not have is an error AND
    never an empty answer;
  * the coverage has a cell for every document AND parameter, a plan with
    no value among them AND its tally counts all documents and not the page;
  * a refusal is served with its reason, its source AND its claim, AND a
    request that was not served says so;
  * a value's coordinate carries the quote it was read from AND the quote
    that names its state where it has one AND no key where the row has none;
  * the values table keeps its columns AND appends the quote of each
    coordinate AND states and refusals are tables of their own AND
    `docpipe export` writes them AND takes no level for them AND says what
    a count counts;
  * the HTTP API and the MCP server answer states, coverage and refusals
    from one code path AND say what is missing as a status or a tool result
    and never as an empty answer;
  * the search returns passages from the word index with document, section
    title, page and text AND says it is not available without a database,
    without an index and with a stale one AND is listed as not working then
    AND is held to MAX_LIMIT;
  * the server takes the database as the chat does AND an export does not
    open the passages.
"""
import csv
import io
import json
import sqlite3

import pytest

from docpipe.extraction import fields
from docpipe.extraction.schema import PARAMETER_STATE_DOC
from docpipe.extraction.spec import load as load_spec
from docpipe.extraction.verify import TIER_TEXT
from docpipe.inference import lexical
from docpipe.serve import cli as serve_cli
from docpipe.serve import export, http, mcp, passages, tools
from docpipe.serve.passages import NO_DATABASE, Passages, Unavailable
from docpipe.serve.values import (MAX_LIMIT, MEANINGS, NEVER_ASKED,
                                  NOT_RECORDED, STATES, NotFound, Values,
                                  read_harvest)

E, EM, PEAK, CAP = ("energy_consumption", "emission", "peak_load",
                    "installed_capacity")


def numeric(uri, label, unit):
    shown = f"| {label} | 1 {unit} |"
    return {"uri": uri, "label": label, "description": f"{label} of the town as the plan states it for "
                          f"one year and one carrier.",
            "value_type": "float", "unit_target": unit,
            "units_accepted": {unit: {"factor": 1,
                                      "names_period": unit.endswith("/a")}},
            "axes": {"year": {"type": "int"}},
            "example": {"source": shown, "tuples": [{
                "value": 1.0, "unit_raw": unit, "year": 2040,
                "quote": shown}]}}


SPEC = {"parameters": [numeric(E, "Final energy consumption", "MWh/a"),
                       numeric(EM, "Emission", "t/a"),
                       numeric(PEAK, "Peak load", "MW"),
                       numeric(CAP, "Installed capacity", "MW")]}


def tuple_line(value=241.0, quote="| Erdgas | 241 |", parameter=E, **more):
    made = {"kind": "tuple", "parameter": parameter, "value": value,
            "value_raw": str(int(value)), "unit": "MWh/a",
            "unit_raw": "MWh/a", "value_target": value, "tier": TIER_TEXT,
            "quote": quote,
            "provenance": {"document_id": 1, "owner_kind": "table",
                           "owner_id": 7, "page": 86},
            "year": 2040, "year_state": fields.READ}
    made.update(more)
    return made


def state_line(parameter, state, tuples=0, refusals=0):
    return {"kind": "parameter_state", "document_id": 1,
            "parameter": parameter, "state": state, "tuples": tuples,
            "refusals": refusals}


def refusal_line(parameter, reason, owner=("table", 7), claim=None):
    return {"kind": "refusal", "parameter": parameter, "reason": reason,
            "claim": claim if claim is not None
            else {"value": 9.0, "quote": "| Gas | 9 |"},
            "owner": list(owner)}


NOT_SERVED = refusal_line(None, "claim names no parameter of the spec",
                          owner=("section", 3),
                          claim={"_harvest_failed": True, "_why": "unserved"})


def write(folder, name, lines):
    (folder / f"{name}.jsonl").write_text(
        "".join(json.dumps(line, ensure_ascii=False) + "\n" for line in lines),
        encoding="utf-8")


@pytest.fixture
def folder(tmp_path):
    """Four documents that stand for four things a harvest can say:
    kassel has all four states, marburg was not asked two parameters, old
    is a harvest from before states were kept, bare read nothing."""
    made = tmp_path / "harvest"
    made.mkdir()
    write(made, "kassel", [
        tuple_line(),
        refusal_line(CAP, "quote not found in the source it cites"),
        NOT_SERVED,
        refusal_line(CAP, "value 9 does not occur in the quote",
                     owner=("section", 3)),
        state_line(E, fields.READ, 1, 0),
        state_line(EM, fields.SAID_UNSTATED),
        state_line(PEAK, fields.EXHAUSTED),
        state_line(CAP, fields.UNBACKED, 0, 2),
        {"kind": "summary", "document_id": 1, "tuples": 1, "refusals": 3}])
    write(made, "marburg", [
        tuple_line(value=5.0, quote="| Kohle | 5 |"),
        state_line(E, fields.READ, 1, 0),
        state_line(EM, fields.SAID_UNSTATED)])
    write(made, "old", [tuple_line(value=3.0, quote="| Erdgas | 3 |")])
    write(made, "bare", [state_line(p, fields.SAID_UNSTATED)
                         for p in (E, EM, PEAK, CAP)])
    # what a run leaves beside the harvest, and is not a document of it
    write(made, "kassel.trace", [{"t": "plan", "doc": 1},
                                 {"t": "refusal", "doc": 1}])
    (made / "kassel.stamp.json").write_text("{}", encoding="utf-8")
    return made


@pytest.fixture(scope="module")
def spec():
    return load_spec(SPEC)


@pytest.fixture
def store(folder, spec):
    return Values.load(folder, spec=spec)


def by_parameter(answer):
    return {cell["parameter"]: cell["state"] for cell in answer["states"]}


# ------------------------------------------------------------------ the reading

def test_the_files_are_read_once_into_values_states_and_refusals(folder):
    harvest = read_harvest(folder)
    assert sorted(harvest.tuples) == ["bare", "kassel", "marburg", "old"]
    assert [len(harvest.tuples[n]) for n in sorted(harvest.tuples)] \
        == [0, 1, 1, 1]
    assert len(harvest.refusals["kassel"]) == 3
    assert harvest.states["kassel"][CAP]["state"] == fields.UNBACKED
    assert harvest.states["old"] == {}
    assert harvest.unreadable == 0


def test_a_trace_file_is_no_document_of_the_harvest(store):
    assert "kassel.trace" not in store.harvested
    assert store.harvested == ["bare", "kassel", "marburg", "old"]
    # and what is in it is read as no state and no refusal of kassel
    assert len(store.refusals(document="kassel")["refusals"]) == 3


def test_a_line_that_cannot_be_used_is_counted_and_not_served(tmp_path):
    made = tmp_path / "h"
    made.mkdir()
    (made / "a.jsonl").write_text("\n".join([
        json.dumps(tuple_line()),
        "{this is not json",
        json.dumps([1, 2]),                                  # not an object
        json.dumps({"kind": "parameter_state", "state": "read"}),   # no name
        json.dumps({"kind": "parameter_state", "parameter": E}),    # no state
        json.dumps(state_line(EM, fields.SAID_UNSTATED)),
        ""]), encoding="utf-8")
    loaded = Values.load(made)
    assert loaded.unreadable == 4
    assert len(loaded) == 1
    # the two state lines that named no state or no parameter made no state
    answer = loaded.states(document="a")
    assert by_parameter(answer) == {E: NEVER_ASKED, EM: fields.SAID_UNSTATED}


def test_where_a_file_has_two_lines_for_a_parameter_the_later_stands(tmp_path):
    made = tmp_path / "h"
    made.mkdir()
    write(made, "a", [state_line(E, fields.EXHAUSTED),
                      state_line(E, fields.READ, 1, 0)])
    assert by_parameter(Values.load(made).states()) == {E: fields.READ}


# ---------------------------------------------------------------------- states

def test_a_state_is_the_one_the_harvest_wrote(store):
    assert by_parameter(store.states(document="kassel")) == {
        E: fields.READ, EM: fields.SAID_UNSTATED, PEAK: fields.EXHAUSTED,
        CAP: fields.UNBACKED}
    (cell,) = store.states(document="kassel", parameter=CAP)["states"]
    # the counts are the line's, and say what they count
    assert (cell["tuples"], cell["refusals"]) == (0, 2)
    assert cell["label"] == "Installed capacity"


def test_no_line_is_never_asked_where_the_file_has_lines(store):
    """marburg has two state lines. The other two parameters are not
    unstated: nobody asked, which says nothing of the document."""
    cells = by_parameter(store.states(document="marburg"))
    assert cells[PEAK] == NEVER_ASKED and cells[CAP] == NEVER_ASKED
    assert cells[PEAK] != fields.SAID_UNSTATED
    (cell,) = store.states(document="marburg", parameter=PEAK)["states"]
    assert (cell["tuples"], cell["refusals"]) == (None, None)


def test_no_line_at_all_is_not_recorded_and_not_never_asked(store):
    """old was harvested before states were kept. It has a value, so it
    cannot be said to be unasked either."""
    assert set(by_parameter(store.states(document="old")).values()) \
        == {NOT_RECORDED}
    assert len(store.find(document="old")["values"]) == 1


def test_the_six_states_are_six_different_answers(store):
    seen = {cell["state"] for cell in store.states()["states"]}
    assert seen == set(STATES) - {fields.UNBACKED} | {fields.UNBACKED}
    assert len(STATES) == len(set(STATES)) == 6
    assert len(set(MEANINGS.values())) == 6
    # the four of the harvest are worded as the schema words them
    for state in (fields.READ, fields.UNBACKED, fields.EXHAUSTED,
                  fields.SAID_UNSTATED):
        assert MEANINGS[state] == PARAMETER_STATE_DOC[state]


def test_a_state_can_be_asked_for_and_the_page_says_what_each_means(store):
    answer = store.states(state=fields.SAID_UNSTATED)
    assert {c["document"] for c in answer["states"]} == {
        "bare", "kassel", "marburg"}
    assert all(c["state"] == fields.SAID_UNSTATED for c in answer["states"])
    assert set(answer["meanings"]) == {fields.SAID_UNSTATED}
    assert answer["meanings"][fields.SAID_UNSTATED] \
        == PARAMETER_STATE_DOC[fields.SAID_UNSTATED]
    # a page that holds no unstated cell does not explain it
    page = store.states(document="old")
    assert set(page["meanings"]) == {NOT_RECORDED}
    with pytest.raises(ValueError):
        store.states(state="done")


def test_a_parameter_is_asked_by_its_name_or_its_label(store):
    by_name = store.states(parameter=EM)
    assert by_name == store.states(parameter="  EMISSION ")
    assert by_name["total"] == 4
    assert {c["document"] for c in by_name["states"]} == {
        "bare", "kassel", "marburg", "old"}


def test_what_the_harvest_does_not_have_is_an_error(store):
    """An empty answer for a misspelt parameter would read as 'every plan
    says nothing about it'."""
    with pytest.raises(NotFound, match="no parameter 'emisson'"):
        store.states(parameter="emisson")
    with pytest.raises(NotFound, match="no document 'kasel'"):
        store.states(document="kasel")
    with pytest.raises(NotFound):
        store.coverage(document="kasel")
    with pytest.raises(NotFound):
        store.coverage(parameter="emisson")
    with pytest.raises(NotFound):
        store.refusals(document="kasel")
    with pytest.raises(NotFound):
        store.refusals(parameter="emisson")


def test_a_store_made_of_rows_alone_knows_no_state():
    bare = Values({"a": [tuple_line()]})
    assert by_parameter(bare.states()) == {E: NOT_RECORDED}
    assert bare.refusals()["total"] == 0
    assert bare.harvested == ["a"]


def test_a_document_that_only_a_state_line_or_a_refusal_names_is_harvested():
    """Built from parts and not from files, a store still lists the plan
    that has no value: it is the one the coverage is for."""
    held = Values({}, states={"quiet": {E: state_line(E, fields.SAID_UNSTATED)}},
                  refusals={"refused": [refusal_line(E, "quote missing or too "
                                                     "short to identify "
                                                     "anything")]})
    assert held.harvested == ["quiet", "refused"]
    assert by_parameter(held.states(document="quiet")) == {
        E: fields.SAID_UNSTATED}
    assert held.refusals(document="refused")["total"] == 1
    with pytest.raises(NotFound):
        held.states(document="never_harvested")


# -------------------------------------------------------------------- coverage

def test_the_coverage_has_a_cell_for_every_document_and_parameter(store):
    answer = store.coverage()
    assert answer["total"] == 4
    assert [p["parameter"] for p in answer["parameters"]] == [E, EM, PEAK, CAP]
    assert answer["parameters"][1] == {"parameter": EM, "label": "Emission"}
    cells = {row["document"]: row["states"] for row in answer["documents"]}
    assert cells["kassel"] == {E: "read", EM: "unstated", PEAK: "exhausted",
                               CAP: "unbacked"}
    assert cells["marburg"][PEAK] == NEVER_ASKED
    assert set(cells["old"].values()) == {NOT_RECORDED}
    # bare has no value and is in the coverage all the same: it is the
    # plan that says nothing
    assert set(cells["bare"].values()) == {"unstated"}
    assert "bare" not in [d["document"] for d in store.documents()]
    assert set(answer["meanings"]) == set(STATES)


def test_a_coverage_can_be_asked_for_one_document_or_one_parameter(store):
    (row,) = store.coverage(document="kassel")["documents"]
    assert set(row["states"]) == {E, EM, PEAK, CAP}
    column = store.coverage(parameter="Peak load")
    assert [p["parameter"] for p in column["parameters"]] == [PEAK]
    assert all(set(r["states"]) == {PEAK} for r in column["documents"])


def test_the_tally_counts_all_documents_and_not_the_page(store):
    whole = store.coverage()["tally"]
    first = store.coverage(limit=1)
    assert len(first["documents"]) == 1 and first["total"] == 4
    assert first["tally"] == whole
    assert whole[E] == {"read": 2, "unstated": 1, NOT_RECORDED: 1}
    assert whole[PEAK] == {"unstated": 1, "exhausted": 1, NEVER_ASKED: 1,
                           NOT_RECORDED: 1}
    for counted in whole.values():
        assert sum(counted.values()) == 4           # documents, each once
    rest = store.coverage(limit=10, offset=3)
    assert [r["document"] for r in rest["documents"]] == ["old"]


def test_a_page_of_states_coverage_or_refusals_is_held_to_the_limit():
    many = MAX_LIMIT + 5
    names = [f"d{index:04d}" for index in range(many)]
    big = Values({name: [] for name in names},
                 states={name: {E: state_line(E, fields.SAID_UNSTATED)}
                         for name in names},
                 refusals={"d0000": [refusal_line(E, "quote missing or too "
                                                  "short to identify "
                                                  "anything")] * many})
    assert (len(big.states(limit=10 ** 6)["states"]),
            big.states(limit=10 ** 6)["total"]) == (MAX_LIMIT, many)
    assert len(big.coverage(limit=10 ** 6)["documents"]) == MAX_LIMIT
    assert len(big.refusals(limit=10 ** 6)["refusals"]) == MAX_LIMIT
    # a file is not held to it
    assert len(big.states(limit=None)["states"]) == many
    assert len(big.refusals(limit=None)["refusals"]) == many
    for ask in (big.states, big.coverage, big.refusals):
        with pytest.raises(ValueError):
            ask(limit=-1)


# -------------------------------------------------------------------- refusals

def test_a_refusal_is_served_with_its_reason_its_source_and_its_claim(store):
    answer = store.refusals(document="kassel", parameter=CAP)
    assert answer["total"] == 2
    first, second = answer["refusals"]
    assert first == {
        "document": "kassel", "parameter": CAP,
        "reason": "quote not found in the source it cites", "failed": None,
        "source": {"owner_kind": "table", "owner_id": 7},
        "claim": {"value": 9.0, "quote": "| Gas | 9 |"}}
    assert second["source"] == {"owner_kind": "section", "owner_id": 3}
    # the reason behind the state is one call away
    (cell,) = store.states(document="kassel", parameter=CAP)["states"]
    assert cell["refusals"] == answer["total"]


def test_a_request_that_was_not_served_says_so_and_a_claim_does_not(store):
    everything = store.refusals()
    assert everything["total"] == 3
    failed = {r["failed"] for r in everything["refusals"]}
    assert failed == {None, "unserved"}
    (sentinel,) = [r for r in everything["refusals"] if r["failed"]]
    assert sentinel["claim"] == {"_harvest_failed": True, "_why": "unserved"}


def test_what_only_a_claim_names_is_no_column_but_can_be_asked(spec):
    stray = refusal_line("energy_use", "claim names no parameter of the spec")
    held = Values({"a": []}, spec=spec, refusals={"a": [stray]},
                  states={"a": {E: state_line(E, fields.SAID_UNSTATED)}})
    assert "energy_use" not in [p["parameter"]
                                for p in held.coverage()["parameters"]]
    with pytest.raises(NotFound):
        held.states(parameter="energy_use")
    assert held.refusals(parameter="energy_use")["total"] == 1
    assert held.refusals(parameter=E)["total"] == 0     # asked and empty


def test_a_refusal_is_still_not_a_value(store):
    assert len(store) == 3
    assert all(v["quote"] != "| Gas | 9 |" for v in store.find()["values"])


# ----------------------------------------------------------------- coordinates

def test_a_coordinate_carries_the_quote_it_was_read_from():
    based = tuple_line(
        year_raw="Basisjahr", year_quote="| 2019 | 241 |",
        year_link_quote="im Basisjahr lag der Verbrauch bei",
        carrier="oeo:gas", carrier_state=fields.READ, carrier_quote="")
    plain = tuple_line(value=5.0, quote="| Kohle | 5 |",
                       carrier="oeo:coal", carrier_state=fields.UNBACKED)
    values = Values({"a": [based, plain]}).find()["values"]
    year = values[0]["coordinates"]["year"]
    assert year["quote"] == "| 2019 | 241 |"
    assert year["link_quote"] == "im Basisjahr lag der Verbrauch bei"
    assert year["state"] == fields.READ and year["wording"] == "Basisjahr"
    # an empty quote is no quote, and a row without one has no key
    assert "quote" not in values[0]["coordinates"]["carrier"]
    assert "quote" not in values[1]["coordinates"]["carrier"]
    assert "quote" not in values[1]["coordinates"]["year"]
    assert "link_quote" not in values[1]["coordinates"]["year"]
    # the value's own quote is the value's, not a coordinate's
    assert values[0]["quote"] == "| Erdgas | 241 |"


# ---------------------------------------------------------------------- export

@pytest.fixture
def no_profile(monkeypatch):
    """The commands read the harvest without a profile's spec: what they say
    of the parameters is then what the harvest itself names."""
    monkeypatch.setattr(serve_cli, "resolve_profile", lambda args: None)


def test_the_values_table_appends_the_quote_of_each_coordinate(no_profile):
    value = tuple_line(year_quote="Prognose 2040", carrier="oeo:gas",
                       carrier_state=fields.READ, carrier_label=None)
    other = tuple_line(value=5.0, quote="| Kohle | 5 |", carrier="oeo:coal",
                       carrier_state=fields.READ, carrier_quote="Kohle: 5")
    served = Values({"a": [value, other]}).find()["values"]
    text = export.to_csv(served)
    header = text.splitlines()[0].split(",")
    assert header[:len(export.FIXED)] == list(export.FIXED)
    assert header[len(export.FIXED):] == [
        "carrier", "carrier_label", "carrier_state",
        "year", "year_label", "year_state", "carrier_quote", "year_quote"]
    first, second = csv.DictReader(io.StringIO(text))
    assert first["year_quote"] == "Prognose 2040"
    assert first["carrier_quote"] == "" and second["year_quote"] == ""
    assert second["carrier_quote"] == "Kohle: 5"
    assert first["quote"] == "| Erdgas | 241 |"      # the value's own


def read_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def test_export_writes_the_states_one_line_per_pair(folder, tmp_path,
                                                    no_profile, capsys):
    out = tmp_path / "states.csv"
    assert serve_cli.export_main([str(folder), "--what", "states",
                                  "--out", str(out)]) == 0
    lines = read_csv(out)
    assert len(lines) == 16                             # 4 documents x 4
    assert list(lines[0]) == list(export.STATE_COLUMNS)
    cell = {(l["document"], l["parameter"]): l for l in lines}
    # the finding that leaves the harvest as a line and not as an absence
    assert cell[("kassel", EM)]["state"] == "unstated"
    assert cell[("kassel", PEAK)]["state"] == "exhausted"
    assert cell[("marburg", PEAK)]["state"] == "never_asked"
    assert cell[("old", E)]["state"] == "not_recorded"
    assert (cell[("kassel", CAP)]["tuples"],
            cell[("kassel", CAP)]["refusals"]) == ("0", "2")
    assert cell[("marburg", PEAK)]["tuples"] == ""
    assert "16 state(s)" in capsys.readouterr().err


def test_export_takes_the_parameters_and_labels_from_the_profile(
        folder, tmp_path, monkeypatch):
    spec_file = tmp_path / "spec.json"
    spec_file.write_text(json.dumps(SPEC), encoding="utf-8")

    class Profile:
        db_path = tmp_path / "none.db"

        @staticmethod
        def component(area, name):
            return spec_file

    monkeypatch.setattr(serve_cli, "resolve_profile", lambda args: Profile)
    write(folder, "bare", [state_line(E, fields.SAID_UNSTATED)])
    out = tmp_path / "s.csv"
    assert serve_cli.export_main([str(folder), "--what", "states",
                                  "--document", "bare",
                                  "--out", str(out)]) == 0
    cell = {l["parameter"]: l for l in read_csv(out)}
    # a parameter of the spec the file has no line for is not unstated
    assert [cell[p]["state"] for p in (E, EM, PEAK, CAP)] == [
        "unstated", "never_asked", "never_asked", "never_asked"]
    assert cell[EM]["label"] == "Emission"


def test_export_writes_the_refusals(folder, tmp_path, no_profile, capsys):
    out = tmp_path / "r.csv"
    assert serve_cli.export_main([str(folder), "--what", "refusals",
                                  "--out", str(out)]) == 0
    lines = read_csv(out)
    assert list(lines[0]) == list(export.REFUSAL_COLUMNS)
    assert len(lines) == 3
    by_reason = {l["reason"]: l for l in lines}
    first = by_reason["quote not found in the source it cites"]
    assert (first["document"], first["parameter"], first["owner_kind"],
            first["owner_id"]) == ("kassel", CAP, "table", "7")
    assert json.loads(first["claim"]) == {"value": 9.0, "quote": "| Gas | 9 |"}
    sentinel = by_reason["claim names no parameter of the spec"]
    assert sentinel["failed"] == "unserved" and sentinel["parameter"] == ""
    assert "3 refusal(s)" in capsys.readouterr().err


def test_export_of_jsonl_carries_what_is_served_whole(folder, no_profile,
                                                      capsys):
    assert serve_cli.export_main([str(folder), "--what", "states",
                                  "--format", "jsonl"]) == 0
    got = [json.loads(l) for l in capsys.readouterr().out.splitlines()]
    # no profile: the store the command opened has no spec either
    assert got == Values.load(folder).states(limit=None)["states"]
    assert len(got) == 16
    assert serve_cli.export_main([str(folder), "--what", "refusals",
                                  "--format", "jsonl",
                                  "--parameter", CAP]) == 0
    refused = [json.loads(l) for l in capsys.readouterr().out.splitlines()]
    assert [r["parameter"] for r in refused] == [CAP, CAP]
    assert refused[0]["source"] == {"owner_kind": "table", "owner_id": 7}


def test_export_takes_no_level_for_what_is_not_a_value(folder):
    for what in ("states", "refusals"):
        with pytest.raises(SystemExit) as caught:
            serve_cli.export_main([str(folder), "--what", what,
                                   "--level", "A"])
        assert caught.value.code == 2
    assert serve_cli.export_main([str(folder), "--what", "values",
                                  "--level", "A", "--format", "jsonl"]) == 0


def test_export_of_what_the_harvest_does_not_have_fails_and_says_so(
        folder, no_profile):
    for what in ("states", "refusals"):
        with pytest.raises(SystemExit) as caught:
            serve_cli.export_main([str(folder), "--what", what,
                                   "--document", "kasel"])
        assert "no document 'kasel'" in str(caught.value)
        with pytest.raises(SystemExit) as caught:
            serve_cli.export_main([str(folder), "--what", what,
                                   "--parameter", "emisson"])
        assert "no parameter 'emisson'" in str(caught.value)


def test_export_says_how_many_lines_it_skipped(folder, tmp_path, no_profile,
                                               capsys):
    with open(folder / "kassel.jsonl", "a", encoding="utf-8") as handle:
        handle.write("{broken\n")
    out = tmp_path / "v.csv"
    assert serve_cli.export_main([str(folder), "--out", str(out)]) == 0
    err = capsys.readouterr().err
    assert "1 unreadable line(s) of the harvest were skipped" in err
    assert "3 value(s)" in err


# ------------------------------------------------------------------- HTTP, MCP

def test_the_api_answers_states_coverage_and_refusals(store):
    status, body = http.answer(store, "/states",
                               "document=kassel&state=exhausted")
    assert status == 200 and body == store.states(
        document="kassel", state="exhausted")
    assert [c["parameter"] for c in body["states"]] == [PEAK]
    status, body = http.answer(store, "/coverage", "limit=2")
    assert status == 200 and body == store.coverage(limit=2)
    assert len(body["documents"]) == 2 and body["total"] == 4
    status, body = http.answer(store, "/refusals", "parameter=" + CAP)
    assert status == 200 and body["total"] == 2
    status, body = http.answer(store, "/")
    assert body["documents"] == 4 and body["unreadable_lines"] == 0


@pytest.mark.parametrize("path, query, status, says", [
    ("/states", "parameter=emisson", 404, "no parameter 'emisson'"),
    ("/states", "document=kasel", 404, "no document 'kasel'"),
    ("/coverage", "document=kasel", 404, "no document"),
    ("/refusals", "parameter=emisson", 404, "no parameter"),
    ("/states", "state=done", 400, "state must be one of"),
    ("/states", "limit=many", 400, "limit must be a whole number"),
    ("/states", "colour=red", 400, "unknown argument(s): colour"),
    ("/coverage", "state=read", 400, "unknown argument(s): state"),
    ("/states", "document=a&document=b", 400, "document is given twice"),
    ("/search", "text=Fernwaerme", 503, NO_DATABASE),
])
def test_what_the_api_cannot_answer_is_a_status_and_a_reason(
        store, path, query, status, says):
    got, body = http.answer(store, path, query)
    assert got == status and says in body["error"]
    assert "states" not in body and "passages" not in body


def test_the_index_page_says_the_search_is_not_available(store):
    _status, body = http.answer(store, "/")
    assert body["endpoints"]["/search"].startswith("NOT AVAILABLE: ")
    assert NO_DATABASE in body["endpoints"]["/search"]
    assert not body["endpoints"]["/states"].startswith("NOT AVAILABLE")


def ask(store, name, arguments=None, request_id=1):
    return mcp.respond(store, {"jsonrpc": "2.0", "id": request_id,
                               "method": "tools/call",
                               "params": {"name": name,
                                          "arguments": arguments or {}}})


def test_the_tools_answer_what_the_store_answers(store):
    got = ask(store, "get_states", {"document": "marburg"})["result"]
    assert got["isError"] is False
    assert got["structuredContent"] == store.states(document="marburg")
    assert json.loads(got["content"][0]["text"]) == got["structuredContent"]
    assert ask(store, "get_coverage")["result"]["structuredContent"] \
        == store.coverage()
    assert ask(store, "find_refusals", {"document": "kassel"})["result"][
        "structuredContent"] == store.refusals(document="kassel")
    unstated = ask(store, "get_states", {"state": "unstated",
                                         "parameter": EM})["result"]
    assert [c["document"] for c in unstated["structuredContent"]["states"]] \
        == ["bare", "kassel", "marburg"]


@pytest.mark.parametrize("name, arguments, says", [
    ("get_states", {"parameter": "emisson"}, "no parameter 'emisson'"),
    ("get_states", {"document": "kasel"}, "no document 'kasel'"),
    ("get_states", {"state": "done"}, "state must be one of"),
    ("get_coverage", {"limit": -1}, "must not be negative"),
    ("find_refusals", {"colour": "red"}, "unknown argument(s): colour"),
    ("find_refusals", {"document": ""}, "document must be a name"),
    ("search", {"text": "x"}, NO_DATABASE),
])
def test_what_a_tool_cannot_answer_is_a_tool_result_with_the_reason(
        store, name, arguments, says):
    got = ask(store, name, arguments)
    assert "error" not in got
    assert got["result"]["isError"] is True
    assert says in got["result"]["content"][0]["text"]
    assert "structuredContent" not in got["result"]


def test_the_list_of_tools_does_not_offer_a_search_that_cannot_work(store):
    listed = mcp.respond(store, {"jsonrpc": "2.0", "id": 1,
                                 "method": "tools/list"})["result"]["tools"]
    by_name = {tool["name"]: tool for tool in listed}
    assert list(by_name) == list(tools.DESCRIPTIONS)
    assert by_name["search"]["description"].startswith("NOT AVAILABLE: ")
    for name in by_name:
        if name != "search":
            assert not by_name[name]["description"].startswith("NOT AVAILABLE")
        assert by_name[name]["inputSchema"]["type"] == "object"


def test_the_instructions_name_tools_that_exist_and_where_the_list_is():
    """A parameter no plan has a value of is in no list_parameters answer:
    the assistant is told where the whole list is."""
    import re
    named = set(re.findall(r"\b(?:list|get|find)_[a-z]+\b|\bsearch\b",
                           mcp.INSTRUCTIONS))
    assert named <= set(tools.DESCRIPTIONS)
    assert {"list_parameters", "get_states", "get_coverage", "search"} <= named


# --------------------------------------------------------------------- passages

SCHEMA = """
CREATE TABLE Documents (id INTEGER PRIMARY KEY, filename TEXT,
                        is_current INTEGER);
CREATE TABLE Sections (id INTEGER PRIMARY KEY, document INTEGER,
                       section_number INTEGER, title TEXT, content TEXT,
                       page_number INTEGER);
CREATE TABLE Tables (id INTEGER PRIMARY KEY, section INTEGER, block_id TEXT,
                     path TEXT, page_number INTEGER, caption TEXT,
                     markdown TEXT);
CREATE TABLE Images (id INTEGER PRIMARY KEY, section INTEGER, block_id TEXT,
                     path TEXT, page_number INTEGER, caption TEXT,
                     description TEXT);
"""


@pytest.fixture
def corpus_db(tmp_path):
    path = tmp_path / "corpus.db"
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.executemany("INSERT INTO Documents VALUES (?, ?, ?)", [
        (1, "kassel.pdf", 1), (2, "marburg.pdf", 1)])
    conn.executemany("INSERT INTO Sections VALUES (?, ?, ?, ?, ?, ?)", [
        (10, 1, 1, "Waermenetze", "Die Stadtwerke Kassel betreiben das "
                                  "Fernwaermenetz.", 4),
        (11, 1, 2, "Bestand", "Der Endenergieverbrauch liegt bei 241 GWh.",
         9),
        (20, 2, 1, "Waermenetze", "Die Stadtwerke Marburg planen ein "
                                  "Waermenetz.", 5)])
    conn.execute("INSERT INTO Tables VALUES (100, 11, 'p9_tbl0', 't.png', 9, "
                 "'Tabelle 3: Endenergie', '| Erdgas | 241 |')")
    conn.commit()
    conn.close()
    return path


@pytest.fixture
def made(corpus_db):
    """Passages on a database that has its word index, closed afterwards."""
    lexical.build(corpus_db)
    opened = []

    def open_it(db=corpus_db):
        found = Passages(db)
        opened.append(found)
        return found

    yield open_it
    for found in opened:
        found.close()


def test_a_search_returns_passages_with_document_section_title_page_and_text(
        made):
    found = made().search("Fernwaermenetz")
    assert found["words"] == ["fernwaermenetz"]
    (hit,) = found["passages"]
    assert hit == {
        "document": "kassel", "kind": "section", "id": 10,
        "title": "Waermenetze", "section_title": "Waermenetze", "page": 4,
        "text": "Die Stadtwerke Kassel betreiben das Fernwaermenetz.",
        "rank": 1}


def test_a_table_is_a_passage_of_the_section_it_stands_in(made):
    (hit,) = made().search("Erdgas")["passages"]
    assert (hit["kind"], hit["id"], hit["document"]) == ("table", 100,
                                                          "kassel")
    assert hit["title"] == "Tabelle 3: Endenergie"
    assert hit["section_title"] == "Bestand"
    assert (hit["page"], hit["text"]) == (9, "| Erdgas | 241 |")


def test_a_search_ranks_the_passage_with_more_of_the_words_first(made):
    found = made().search("Stadtwerke Marburg")["passages"]
    assert [(p["document"], p["rank"]) for p in found][:2] == [
        ("marburg", 1), ("kassel", 2)]
    assert made().search("Geothermie")["passages"] == []


def test_a_search_can_be_limited_to_a_document_and_a_count(made):
    search = made()
    found = search.search("Stadtwerke", document="kassel")["passages"]
    assert [p["document"] for p in found] == ["kassel"]
    assert len(search.search("Stadtwerke Erdgas", limit=1)["passages"]) == 1
    assert search.search("Stadtwerke", limit=0)["passages"] == []
    with pytest.raises(NotFound, match="no document 'koeln'"):
        search.search("Stadtwerke", document="koeln")
    with pytest.raises(ValueError):
        search.search("Stadtwerke", limit=-1)
    with pytest.raises(ValueError, match="no word"):
        search.search("  !? ")


def test_a_search_is_held_to_the_limit(made, monkeypatch):
    monkeypatch.setattr(passages, "MAX_LIMIT", 2)
    found = made().search("Stadtwerke Waermenetze Erdgas Endenergieverbrauch",
                          limit=50)["passages"]
    assert len(found) == 2
    monkeypatch.setattr(passages, "MAX_LIMIT", 1000)
    assert len(made().search("Stadtwerke Waermenetze Erdgas "
                             "Endenergieverbrauch", limit=50)["passages"]) == 4


def test_without_a_database_the_search_says_so(store):
    assert store.passages is None
    with pytest.raises(Unavailable, match="no corpus database"):
        tools.search(store, {"text": "Stadtwerke"})
    nothing = Passages(None)
    assert not nothing.available and nothing.why == NO_DATABASE
    with pytest.raises(Unavailable, match="--db"):
        nothing.search("Stadtwerke")


def test_without_a_word_index_the_search_says_so_and_how_to_build_it(
        corpus_db):
    found = Passages(corpus_db)
    assert not found.available
    assert "is missing" in found.why and "docpipe lexical" in found.why
    with pytest.raises(Unavailable, match="docpipe lexical"):
        found.search("Stadtwerke")


def test_a_server_with_no_search_says_so_before_it_judges_the_question(
        store, corpus_db):
    """A malformed question to a search that cannot work is told that the
    search cannot work: fixing the question would not help."""
    for passages_of in (None, Passages(corpus_db)):
        store.passages = passages_of
        for arguments in ({}, {"text": ""}, {"text": "x", "colour": 1},
                          {"text": "Stadtwerke", "limit": "many"}):
            with pytest.raises(Unavailable):
                tools.search(store, arguments)


def test_a_stale_index_is_not_asked(corpus_db):
    """The index was built, and a passage was rewritten after. An answer
    from it would name words the passage no longer has."""
    lexical.build(corpus_db)
    conn = sqlite3.connect(corpus_db)
    conn.execute("UPDATE Sections SET content = 'Neu geschrieben.' "
                 "WHERE id = 10")
    conn.commit()
    conn.close()
    found = Passages(corpus_db)
    assert not found.available
    assert "another state" in found.why and "docpipe lexical" in found.why
    with pytest.raises(Unavailable):
        found.search("Fernwaermenetz")


def test_an_index_that_names_a_passage_the_database_lost_is_not_an_answer(
        made, monkeypatch):
    search = made()
    monkeypatch.setattr(passages.corpus, "fetch_owner_content",
                        lambda conn, kind, owner: None)
    with pytest.raises(Unavailable, match="no longer has"):
        search.search("Fernwaermenetz")


def test_a_word_index_this_python_cannot_ask_is_said_and_not_hidden(
        made, monkeypatch):
    search = made()

    def broken(*_args, **_kwargs):
        raise sqlite3.OperationalError("no such module: fts5")

    monkeypatch.setattr(passages.lexical, "search", broken)
    with pytest.raises(Unavailable, match="could not be asked"):
        search.search("Stadtwerke")


def test_an_index_this_python_cannot_ask_is_not_listed_as_working(
        corpus_db, store):
    """What an SQLite without FTS5 does to an index built elsewhere: it
    opens, its digest is current, and every query fails. Built here as an
    index whose table cannot be read."""
    lexical.build(corpus_db)
    index = sqlite3.connect(lexical.path_for(corpus_db))
    index.execute('DROP TABLE "passages"')
    index.execute('CREATE VIEW "passages" AS SELECT * FROM "gone"')
    index.commit()
    index.close()
    assert lexical.state(corpus_db) == "current"
    found = Passages(corpus_db)
    assert not found.available and "could not be asked" in found.why
    store.passages = found
    listed = tools.described(store)["search"]["description"]
    assert listed.startswith("NOT AVAILABLE: ") and found.why in listed
    with pytest.raises(Unavailable, match="could not be asked"):
        tools.search(store, {"text": "Fernwaermenetz"})


def test_the_tools_search_when_there_is_something_to_search(store, made):
    store.passages = made()
    got = ask(store, "search", {"text": "Fernwaermenetz"})["result"]
    assert got["isError"] is False
    assert got["structuredContent"]["passages"][0]["document"] == "kassel"
    listed = mcp.respond(store, {"jsonrpc": "2.0", "id": 1,
                                 "method": "tools/list"})["result"]["tools"]
    search = [t for t in listed if t["name"] == "search"][0]
    assert "NOT AVAILABLE" not in search["description"]
    status, body = http.answer(store, "/search",
                               "text=Fernwaermenetz&document=kassel")
    assert status == 200 and body["passages"][0]["page"] == 4
    assert http.answer(store, "/")[1]["endpoints"]["/search"] \
        == tools.DESCRIPTIONS["search"]["description"]
    status, body = http.answer(store, "/search",
                               "text=Stadtwerke&document=koeln")
    assert status == 404 and "no document 'koeln'" in body["error"]
    status, body = http.answer(store, "/search", "limit=3")
    assert status == 400 and body["error"] == "text is missing"
    status, body = http.answer(store, "/search", "text=%3F%21")
    assert status == 400 and "no word" in body["error"]


def test_the_tool_that_is_not_working_is_listed_with_why_when_the_index_is_gone(
        store, corpus_db):
    found = Passages(corpus_db)                # no index was built
    store.passages = found
    listed = tools.described(store)["search"]["description"]
    assert listed.startswith("NOT AVAILABLE: ") and found.why in listed
    status, body = http.answer(store, "/search", "text=Stadtwerke")
    assert status == 503 and body["error"] == found.why


# ---------------------------------------------------------------------- the CLI

def _args(*argv):
    import argparse
    parser = argparse.ArgumentParser()
    serve_cli._common(parser)
    return parser.parse_args(list(argv))


def test_the_server_takes_the_database_as_the_chat_does(
        folder, corpus_db, tmp_path, monkeypatch, no_profile):
    lexical.build(corpus_db)
    other = tmp_path / "other.db"
    other.write_bytes(corpus_db.read_bytes())
    monkeypatch.delenv(serve_cli.DB_ENV, raising=False)

    # no option, no setting, no profile: no database, and the search says it
    nothing = serve_cli.open_store(_args(str(folder)), search=True)
    assert nothing.passages.why == NO_DATABASE

    # the setting
    monkeypatch.setenv(serve_cli.DB_ENV, str(corpus_db))
    by_setting = serve_cli.open_store(_args(str(folder)), search=True)
    try:
        assert by_setting.passages.available
        assert by_setting.passages.db_path == corpus_db
    finally:
        by_setting.passages.close()

    # the option beats the setting (and `other` has no index of its own)
    by_option = serve_cli.open_store(
        _args(str(folder), "--db", str(other)), search=True)
    assert by_option.passages.db_path == other
    assert "is missing" in by_option.passages.why

    # a database that is not there is an error and not a search without one
    monkeypatch.setenv(serve_cli.DB_ENV, str(tmp_path / "gone.db"))
    with pytest.raises(SystemExit, match="gone.db"):
        serve_cli.open_store(_args(str(folder)), search=True)


def test_serve_gives_the_search_the_database_it_was_told(
        folder, corpus_db, monkeypatch, no_profile):
    """`open_store` has the option; the command has to ask for the search,
    or a server started with --db says that it has no database."""
    lexical.build(corpus_db)
    monkeypatch.delenv(serve_cli.DB_ENV, raising=False)
    served = []
    monkeypatch.setattr(mcp, "serve", lambda store: served.append(store) or 0)
    monkeypatch.setattr(http, "serve", lambda store, host, port:
                        served.append(store) or 0)
    try:
        for how in ("--mcp", "--http"):
            assert serve_cli.serve_main(
                [str(folder), how, "--db", str(corpus_db)]) == 0
        assert len(served) == 2
        for store in served:
            assert store.passages.available
            (hit,) = tools.search(store, {"text": "Fernwaermenetz"})[
                "passages"]
            assert hit["document"] == "kassel"
        # no database: the server starts, and says why it has no search
        assert serve_cli.serve_main([str(folder), "--mcp"]) == 0
        assert served[2].passages.why == NO_DATABASE
    finally:
        for store in served:
            store.passages.close()


def test_a_harvest_that_is_not_there_fails_before_the_passages_are_opened(
        tmp_path, corpus_db, monkeypatch, no_profile):
    """Opening them checks the index against the whole database, which is
    not worth doing for a command that is about to fail."""
    opened = []
    monkeypatch.setattr(Passages, "__init__",
                        lambda self, db=None: opened.append(db))
    with pytest.raises(SystemExit, match="not a directory"):
        serve_cli.open_store(_args(str(tmp_path / "nowhere"), "--db",
                                   str(corpus_db)), search=True)
    assert opened == []


def test_an_export_does_not_open_the_passages(folder, corpus_db, monkeypatch,
                                              no_profile):
    """Opening them reads the whole database to check the index."""
    lexical.build(corpus_db)
    monkeypatch.setenv(serve_cli.DB_ENV, str(corpus_db))
    opened = serve_cli.open_store(_args(str(folder)))
    assert opened.passages is None


def test_the_setting_is_one_the_serve_stage_reads():
    from docpipe import settings
    (setting,) = [s for s in settings.SETTINGS
                  if s.env == serve_cli.DB_ENV]
    assert "serve" in setting.stages and "chat" in setting.stages
