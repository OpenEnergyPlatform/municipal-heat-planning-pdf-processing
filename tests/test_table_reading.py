"""A table is read as a table: a quote is one row, a number keeps the head of
its column, and the frame of a table that prints none is read once for the
table and not for a number of it. Each promise has a case that breaks it by
construction beside the one that keeps it."""
import json
from pathlib import Path
from types import SimpleNamespace

import jsonschema
import pytest

from docpipe.extraction import fields, pipeline, runner, schema, stats
from docpipe.extraction.pipeline import Row, Source
from docpipe.extraction.spec import load as load_spec
from profiles.kwp import kg

SPEC = load_spec(json.loads(
    (Path(__file__).resolve().parent.parent / "profiles" / "kwp"
     / "extraction_spec.json").read_text(encoding="utf-8")))
PARAMETER = SPEC.by_uri["energy_consumption"]
SLOTS = {slot.name: slot for slot in fields.axis_slots(PARAMETER)}
YEAR, SCENARIO, CARRIER = SLOTS["year"], SLOTS["scenario"], SLOTS["carrier"]
FRAME = [SCENARIO, YEAR]

WOHNEN, GEWERBE = "| Wohnen | 120 | 80 |", "| Gewerbe | 40 | 80 |"
BOTH_ROWS = f"{WOHNEN}\n{GEWERBE}"


# -- a quote is one row ------------------------------------------------------

def test_a_quote_over_rows_is_cut_to_the_row_of_its_number():
    claim = {"value": 120, "quote": BOTH_ROWS}
    assert pipeline.narrow_quote(claim)["quote"] == WOHNEN


def test_a_number_on_several_rows_keeps_its_quote():
    claim = {"value": 80, "quote": BOTH_ROWS}
    assert pipeline.narrow_quote(claim)["quote"] == BOTH_ROWS
    assert pipeline.in_several_rows(claim)


def test_a_number_on_one_row_is_not_asked_again():
    assert not pipeline.in_several_rows({"value": 120, "quote": BOTH_ROWS})


def test_a_number_no_row_prints_keeps_its_quote_for_the_check():
    claim = {"value": 999, "quote": BOTH_ROWS}
    assert pipeline.narrow_quote(claim)["quote"] == BOTH_ROWS
    assert not pipeline.in_several_rows(claim)


def test_a_sentence_is_no_row():
    claim = {"value": 120, "quote": "Der Bedarf liegt bei 120 MWh.\nDer Rest."}
    assert pipeline.narrow_quote(claim) == claim


def test_the_rule_under_a_head_is_no_row():
    assert pipeline.printed_lines("| a | b |\n| --- | --- |\n| 1 | 2 |") == [
        "| a | b |", "| 1 | 2 |"]


def test_every_value_of_an_entry_is_cut_to_its_own_row():
    got = runner._parse_reply(json.dumps({"status": "complete", "tuples": [
        {"source": "Q1", "values": [120, 40], "quote": BOTH_ROWS}]}))["tuples"]
    assert [(t["value"], t["quote"]) for t in got] == [(120, WOHNEN),
                                                       (40, GEWERBE)]


def test_the_cell_of_a_number_is_counted_in_the_row_that_prints_it():
    assert pipeline.cell_index(BOTH_ROWS, 40) == (2, 3)


def test_a_number_on_two_rows_names_no_cell():
    assert pipeline.cell_index(BOTH_ROWS, 80) is None


# -- a number keeps the head of its column -----------------------------------

TABLE = ("| Sektor | Erdgas | Wärmenetze |\n| --- | --- | --- |\n"
         f"{WOHNEN}\n")


def rows_of(text, kind="table", value=80, quote=WOHNEN):
    source = Source(kind, 1, text, {})
    batch = pipeline.Batch(1, None, [pipeline.WorkItem(1, None, source)])
    rows, _orphans = pipeline.rows_from_reply(batch, {"tuples": [
        {"source": "Q1", "value": value, "quote": quote}]})
    return rows


def test_a_row_of_a_table_carries_the_head_of_its_number():
    assert rows_of(TABLE)[0].claim["head"] == "Wärmenetze"


def test_a_number_outside_a_table_has_no_head():
    assert "head" not in rows_of(TABLE, kind="section")[0].claim


def test_a_number_in_two_cells_has_no_head():
    twice = "| Sektor | Erdgas | Netz |\n| --- | --- | --- |\n| Wohnen | 80 | 80 |"
    rows = rows_of(twice, quote="| Wohnen | 80 | 80 |")
    assert "head" not in rows[0].claim


def test_the_harvest_file_may_carry_a_head():
    assert "head" in schema._tuple_schema(SPEC, PARAMETER)["properties"]


# -- a number printed twice takes its column from its place ------------------

YEARS = ("| Energieträger | 2022 | 2030 | 2045 |\n| --- | --- | --- | --- |\n"
         "| Abfall | 27% | 28% | 27% |\n")
ABFALL = "| Abfall | 27% | 28% | 27% |"
EVERY_YEAR = ({"year": 2022}, {"year": 2030}, {"year": 2045})


def listed(values, quote=ABFALL, text=YEARS, pairs=(), frame=None,
           label="Q1"):
    """The rows a reply listing one table row makes, and its orphans."""
    reply = runner._parse_reply(json.dumps({"status": "complete", "tuples": [
        {"source": label, "values": values, "quote": quote}]}))
    batch = pipeline.Batch(1, None, [pipeline.WorkItem(
        1, None, Source("table", 1, text, {}))])
    batch.pairs, batch.frame = tuple(pairs), frame
    return pipeline.rows_from_reply(batch, reply, FRAME, SPEC)


def test_a_number_printed_twice_takes_the_head_of_its_place_in_the_row():
    rows, _orphans = listed([27, 28, 27])
    assert [row.claim.get("head") for row in rows] == ["2022", "2030", "2045"]


def test_a_list_that_is_not_its_row_cell_by_cell_places_no_repeat():
    rows, _orphans = listed([27, 27])
    assert [row.claim.get("head") for row in rows] == [None, None]
    rows, _orphans = listed([28, 27, 27])
    assert [row.claim.get("head") for row in rows] == ["2030", None, None]


def test_the_place_of_a_number_reaches_no_row_no_orphan_and_no_prompt():
    rows, _orphans = listed([27, 28, 27])
    assert not any(pipeline.CELL in row.claim for row in rows)
    _rows, orphans = listed([27, 28, 27], label="Q9",
                            quote="| Gewerbe | 27% | 28% | 27% |")
    assert orphans and not any(pipeline.CELL in o for o in orphans)
    prior = runner._prior_payload([{"value": 27, pipeline.CELL: (2, 4)}])
    assert prior == [{"value": 27}]


def test_a_field_request_shows_a_repeated_number_the_head_of_its_place():
    source = SimpleNamespace(owner_kind="table", owner_id=1, text=YEARS)
    assert runner.cell_facts(27, ABFALL, source, "2045") == {"head": "2045"}
    assert runner.cell_facts(27, ABFALL, source) == {}


# -- a head that prints a year of the plan is the year of its column ---------

def test_a_head_printing_a_year_of_the_pairs_is_the_year_of_its_numbers():
    rows, _orphans = listed([27, 28, 27], pairs=EVERY_YEAR)
    assert [row.claim["year"] for row in rows] == [2022, 2030, 2045]
    claim = rows[1].claim
    assert claim["year_state"] == fields.READ
    assert claim["year_quote"] == "| Energieträger | 2022 | 2030 | 2045 |"
    assert (claim["year_source"], claim["year_window"]) == (["table", 1],
                                                            ["head", 3])
    assert pipeline.open_rows(rows, YEAR) == []


def test_a_year_no_pair_has_or_two_years_in_a_head_are_not_taken():
    rows, _orphans = listed([27, 28, 27], pairs=({"year": 2022},
                                                 {"year": 2045}))
    assert [row.claim.get("year") for row in rows] == [2022, None, 2045]
    two = ("| Sektor | 2022 bis 2030 |\n| --- | --- |\n| Wohnen | 120 |\n")
    rows, _orphans = listed([120], quote="| Wohnen | 120 |", text=two,
                            pairs=EVERY_YEAR)
    assert "year" not in rows[0].claim


def test_a_year_read_off_its_head_fits_the_harvest_file():
    window = schema._tuple_schema(SPEC, PARAMETER)["properties"]["year_window"]
    jsonschema.validate(["head", 3], window)


def test_a_number_of_another_column_keeps_the_pair_of_its_year():
    rows, _orphans = listed([27, 28, 27], pairs=({"year": 2045},
                                                 {"year": 2022}),
                            frame={"year": 2045})
    assert (rows[0].pair, rows[0].pair_index) == ({"year": 2022}, 1)
    assert rows[2].pair is None
    two = ({"year": 2045}, {"year": 2022, "scenario": "status_quo"},
           {"year": 2022, "scenario": "target"})
    rows, _orphans = listed([27, 28, 27], pairs=two, frame={"year": 2045})
    assert rows[0].pair is None and rows[0].claim["year"] == 2022


def graph_row(value, **more):
    return {"quantity": "OEO_00050016", "year": 2045, "value": value,
            "value_target": float(value), "subject": "Wohnen",
            "quote": WOHNEN, "scenario": "target", "tier": "text_located",
            "flags": [], **more}


def settled(*rows):
    iri = kg._value_iri("part", rows[0])
    return kg.settle(iri, list(rows), "part", keep_open=False)


def test_two_numbers_of_one_row_are_two_nodes_by_their_heads():
    kept, lost, _marks = settled(graph_row(120, head="Erdgas"),
                                 graph_row(80, head="Wärmenetze"))
    assert sorted(r["value"] for r in kept.values()) == [80, 120]
    assert not lost["conflict"]


def test_two_numbers_of_one_head_still_disagree():
    kept, lost, _marks = settled(graph_row(120, head="Erdgas"),
                                 graph_row(80, head="Erdgas"))
    assert kept == {}
    assert lost["conflict"] == 2


# -- what prints a frame -----------------------------------------------------

BODY = ("| Sektor | Wärmebedarf |\n| --- | --- |\n| Wohnen | 120 |\n"
        "| Gewerbe | 80 |\n| Industrie | 40 |")
CAPTION = "Tabelle 3: Zielszenario im Jahr 2045"


def table(body=BODY, owner=5, caption=CAPTION):
    return Source("table", owner, f"{caption}\n{body}", {"document_id": 7},
                  body=body)


def test_a_table_printing_neither_prints_no_frame():
    assert pipeline.prints_no_frame(table(), FRAME)


def test_its_title_does_not_count():
    assert "2045" in table().text and pipeline.prints_no_frame(table(), FRAME)


@pytest.mark.parametrize("cell", ["2030", "Zielszenario", "Basisjahr"])
def test_a_year_or_a_spelling_of_the_scenario_prints_the_frame(cell):
    body = f"| Sektor | {cell} |\n| --- | --- |\n| Wohnen | 120 |"
    assert not pipeline.prints_no_frame(table(body), FRAME)


@pytest.mark.parametrize("cell", ["2.030", "2030,5", "9999"])
def test_a_number_is_no_year(cell):
    body = f"| Sektor | Wert |\n| --- | --- |\n| Wohnen | {cell} |"
    assert pipeline.prints_no_frame(table(body), FRAME)


def test_a_table_known_only_by_its_text_is_read_from_it():
    source = Source("table", 5, "Tabelle 2030\n| Wohnen | 120 |", {})
    assert not pipeline.prints_no_frame(source, FRAME)


# -- the frame of a table is read once ---------------------------------------

def plain_rows(*claims):
    claims = claims or ({}, {}, {})
    return [Row(label=f"R{i + 1}", item_index=0,
                claim={"value": 10 * (i + 1), "quote": f"| Zeile | {i} |",
                       **claim})
            for i, claim in enumerate(claims)]


def sweeping_of(answer, rows, source=None, slot=YEAR, sweeper=None):
    """A sweep of *slot* over the rows of one passage, and the requests it
    sent. *answer* is what the model says, given the rows it was asked."""
    asked = []
    source = source or table()

    def ask(shown, todo, slots, corrections, document_id, usage, owner_of,
            bases=None):
        asked.append(list(todo))
        return answer(todo)

    if sweeper is None:
        sweeper = runner.make_sweeper(ask, frame_axes=FRAME)
    else:
        sweeper.ask = ask
    batch = SimpleNamespace(document_id=7, bases=(), parameter=None,
                            items=[SimpleNamespace(source=source)],
                            sources=[source])
    sweeping = runner.Sweeping(sweeper, runner.Scope([(batch, rows)]), [slot],
                               "", seen=set(), held={}, kind="document")
    sweeping.state["stage"] = "own"
    return sweeping, asked, source


def says(slot=YEAR, value=2045, quote=CAPTION):
    """The model reads *value* for the first row it was asked."""
    return lambda todo: {"fields": {slot.name: {"answers": {
        todo[0].label: {"value": value, "quote": quote}}}}}


def test_a_table_with_one_frame_is_asked_once_and_without_a_number():
    sweeping, asked, source = sweeping_of(says(), plain_rows())
    sweeping.run([[source]])
    assert [len(todo) for todo in asked] == [1]
    entry = runner._field_payload([source], asked[0], [YEAR],
                                  owner_of=sweeping.owner_of)["rows"][0]
    assert entry["table"] is True
    assert entry["head"] == "| Sektor | Wärmebedarf |"
    assert not {"value", "quote", "unit", "column"} & set(entry)


def test_a_table_request_knows_only_the_frame_read_so_far():
    claim = {"year": 2045, "year_state": fields.READ,
             "carrier": "Erdgas", "carrier_state": fields.READ,
             "carrier_raw": "Erdgas"}
    rows = [Row(label="R1", item_index=0, claim={"value": 10, **claim},
                table=("scenario", "year"))]
    entry = runner._field_payload([table()], rows, [SCENARIO],
                                  owner_of={"R1": table()})["rows"][0]
    assert entry["known"] == {"year": "2045"}


def test_every_row_takes_the_answer_with_its_evidence():
    rows = plain_rows()
    sweeping, _asked, source = sweeping_of(says(), rows)
    sweeping.run([[source]])
    for row in rows:
        assert row.claim["year"] == 2045
        assert row.claim["year_state"] == fields.READ
        assert row.claim["year_quote"] == CAPTION
        assert row.claim["year_source"] == ["table", 5]
    assert [r.claim["year_window"][0] for r in rows] == ["own", "table",
                                                         "table"]
    assert sweeping.totals["via_table"] == 2


def test_the_scenario_is_read_the_same_way():
    rows = plain_rows()
    sweeping, asked, source = sweeping_of(
        says(SCENARIO, "Zielszenario"), rows, slot=SCENARIO)
    sweeping.run([[source]])
    assert [len(todo) for todo in asked] == [1]
    assert {r.claim["scenario"] for r in rows} == {"Zielszenario"}


def test_a_table_printing_its_frame_is_asked_number_by_number():
    body = "| Sektor | 2030 | 2045 |\n| --- | --- | --- |\n| Wohnen | 120 | 80 |"
    rows = plain_rows()
    sweeping, asked, source = sweeping_of(says(), rows, table(body))
    sweeping.run([[source]])
    assert [row.table for row in asked[0]] == [(), (), ()]
    assert "year_state" not in rows[1].claim
    assert sweeping.totals["via_table"] == 0


def test_an_axis_outside_the_frame_is_asked_number_by_number():
    sweeping, asked, source = sweeping_of(
        lambda todo: None, plain_rows(), slot=CARRIER)
    sweeping.run([[source]])
    assert len(asked[0]) == 3


def test_a_passage_that_is_no_table_is_asked_number_by_number():
    section = Source("section", 5, BODY, {"document_id": 7}, body=BODY)
    sweeping, asked, _source = sweeping_of(says(), plain_rows(), section)
    sweeping.run([[section]])
    assert len(asked[0]) == 3


def test_a_table_with_a_reading_asks_nothing_in_the_next_batch():
    first, asked, source = sweeping_of(says(), plain_rows())
    first.run([[source]])
    rows = plain_rows()
    second, again, _ = sweeping_of(says(), rows, sweeper=first.sweeper)
    second.run([[source]])
    assert again == []
    assert {r.claim["year"] for r in rows} == {2045}
    assert {r.claim["year_window"][0] for r in rows} == {"table"}


def test_a_table_that_does_not_say_says_so_for_every_row():
    rows = plain_rows()
    nothing = says(value=fields.UNSTATED, quote=None)
    sweeping, _asked, source = sweeping_of(nothing, rows)
    sweeping.run([[source]])
    assert [r.claim.get("year_state") for r in rows] == [
        fields.SAID_UNSTATED] * 3


def test_a_row_outside_a_table_asked_for_stays_unanswered():
    body = "| Sektor | 2030 |\n| --- | --- |\n| Wohnen | 120 |"
    rows = plain_rows()
    nothing = says(value=fields.UNSTATED, quote=None)
    sweeping, _asked, source = sweeping_of(nothing, rows, table(body))
    sweeping.run([[source]])
    assert [r.claim.get("year_state") for r in rows] == [
        fields.SAID_UNSTATED, None, None]


def test_a_refused_answer_is_asked_again_for_the_table():
    replies = iter([says(quote="eine Passage die nirgends steht"), says()])
    rows = plain_rows()
    sweeping, asked, source = sweeping_of(lambda t: next(replies)(t), rows)
    sweeping.run([[source]])
    assert [len(todo) for todo in asked] == [1, 1]
    assert asked[1][0].table
    assert {r.claim["year"] for r in rows} == {2045}


def test_a_row_under_a_frame_pair_keeps_its_pair():
    framed = {"year": 2030, "year_state": fields.READ,
              "year_quote": "Stand 2030", "year_window": ["frame", 1]}
    other = {**framed, "year": 2045, "year_window": ["frame", 2]}
    rows = plain_rows(framed, other, {})
    sweeping, asked, source = sweeping_of(says(), rows)
    sweeping.run([[source]])
    assert asked == []
    assert [r.claim["year"] for r in rows] == [2030, 2045, 2030]
    assert rows[2].claim["year_window"] == ["table", 1]


def test_the_first_reading_of_a_table_stands_and_takes_its_evidence_along():
    first = {"year": 2022, "year_state": fields.READ, "year_quote": "Stand 2022",
             "year_source": ["section", 1], "year_window": ["own", 1]}
    second = {"year": 2030, "year_state": fields.READ,
              "year_quote": "Stand 2030", "year_source": ["section", 2],
              "year_window": ["retrieval", 3], "year_link_quote": "Basisjahr",
              "year_link_source": ["table", 5]}
    rows = plain_rows(first, second)
    sweeping, _asked, _source = sweeping_of(says(), rows)
    sweeping.share_tables()
    assert rows[1].claim["year"] == 2022
    assert rows[1].claim["year_quote"] == "Stand 2022"
    assert rows[1].claim["year_window"] == ["table", 1]
    assert "year_link_quote" not in rows[1].claim


def test_the_trace_of_a_sweep_fits_its_schema(monkeypatch):
    events = []
    monkeypatch.setattr(runner.trace, "event", lambda kind, doc=None, /, **f:
                        events.append({"t": kind, "doc": doc, **f}))
    sweeping, _asked, source = sweeping_of(says(), plain_rows())
    sweeping.run([[source]])
    sweeping.close()
    assert [e["t"] for e in events] == ["field", "sweep"]
    assert events[-1]["via_table"] == 2
    for event in events:
        jsonschema.validate(event, schema.trace_schema())


def test_the_statistics_count_the_rows_that_took_their_table(tmp_path):
    trace = tmp_path / "plan.trace.jsonl"
    trace.write_text(json.dumps({"t": "sweep", "via_table": 2}) + "\n",
                     encoding="utf-8")
    assert stats.from_traces([tmp_path])[
        "coordinates_taken_from_their_table"] == 2
