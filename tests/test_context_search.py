"""A field question and its search carry the row's context; the vectors for
the search come in shared batches; documents start while the server has room;
nothing a run replaces is lost; and every run counts where it was hard.

Each promise has a case that breaks it by construction beside the one that
keeps it."""
import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from docpipe.extraction import archive, fields, runner, stats
from docpipe.extraction.pipeline import Row, Source, merge_field
from docpipe.extraction.remap import enter_producer
from docpipe.extraction.spec import load as load_spec

SPEC = load_spec(json.loads(
    (Path(__file__).resolve().parent.parent / "profiles" / "kwp"
     / "extraction_spec.json").read_text(encoding="utf-8")))
PARAMETER = SPEC.by_uri["energy_consumption"]
SLOTS = {slot.name: slot for slot in fields.axis_slots(PARAMETER)}
CARRIER = SLOTS["carrier"]

TABLE = Source("table", 1, "| Gebäudetyp | Endenergiebedarf [MWh/a] |\n"
                           "| Mehrfamilienhaus | 55.933.927 |",
               {"document_id": 7, "title": "Endenergiebedarf nach Gebäudetyp"})


def row(label="R1", **claim):
    return Row(label=label, item_index=0,
               claim={"value": 55933927, "quote": "| Mehrfamilienhaus | 55.933.927 |",
                      **claim})


READ_ROW = dict(quantity_state=fields.READ, quantity_raw="Endenergiebedarf",
                sector_state=fields.READ, sector_raw="Mehrfamilienhaus",
                unit_state=fields.READ, unit_raw="MWh/a",
                parameter_state=fields.DERIVED, parameter_raw="MWh/a",
                year_state=fields.EXHAUSTED, carrier_state=fields.EXHAUSTED)


# -- the question: what the row already is -----------------------------------

def test_the_row_context_is_the_wording_of_what_it_has_read():
    assert runner.row_context(row(**READ_ROW).claim, {"carrier"}) == {
        "quantity": "Endenergiebedarf", "sector": "Mehrfamilienhaus"}


def test_open_derived_unit_and_asked_coordinates_are_no_context():
    claim = dict(READ_ROW, sector_state=fields.EXHAUSTED)
    assert runner.row_context(row(**claim).claim, {"quantity"}) == {}


def test_every_row_of_a_field_request_carries_its_context_and_title():
    rows = [row(**READ_ROW), row("R2")]
    body = runner._field_payload([TABLE], rows, CARRIER,
                                 owner_of={"R1": TABLE, "R2": TABLE})
    first, second = body["rows"]
    assert first["known"] == {"quantity": "Endenergiebedarf",
                              "sector": "Mehrfamilienhaus"}
    assert first["title"] == second["title"] == "Endenergiebedarf nach Gebäudetyp"
    assert "known" not in second


# -- the search: one sentence per table of the open rows ------------------------

def test_the_search_asks_once_per_own_passage_with_its_context():
    other = Source("table", 2, "x", {"title": "Wärmebedarf 2045"})
    rows = [row("R1", **READ_ROW),
            row("R2", **dict(READ_ROW, sector_raw="Einfamilienhaus")),
            row("R3", **dict(READ_ROW, quantity_raw="Wärmebedarf",
                             sector_state=fields.EXHAUSTED))]
    probes = runner.context_probes(rows, {"carrier"},
                                   {"R1": TABLE, "R2": TABLE, "R3": other},
                                   "Welcher Energieträger?")
    assert probes == [
        "Endenergiebedarf nach Gebäudetyp Endenergiebedarf Mehrfamilienhaus "
        "Einfamilienhaus Welcher Energieträger?",
        "Wärmebedarf 2045 Wärmebedarf Welcher Energieträger?"]


def test_rows_without_any_context_leave_the_search_to_the_anchors():
    assert runner.context_probes([row()], {"carrier"}, {}, "Welcher?") == []


def test_the_head_of_a_question_is_its_first_sentence():
    head = runner.question_head(CARRIER.question)
    assert CARRIER.question.startswith(head) and head.endswith("?")
    assert len(head) < len(CARRIER.question)
    assert runner.question_head("Kein Fragezeichen. Rest") == "Kein Fragezeichen"


# -- not split by the axis: a total, backed like any other answer --------------

def test_a_number_not_split_by_carrier_reads_as_total_from_its_header():
    got = [row()]
    merge_field(got, [TABLE], CARRIER, {"answers": {"R1": {
        "value": "Summe", "value_raw": "Gebäudetyp",
        "quote": "| Gebäudetyp | Endenergiebedarf [MWh/a] |"}}})
    assert got[0].claim["carrier_state"] == fields.READ
    chosen = {o.label: o.uri for o in CARRIER.options}[got[0].claim["carrier"]]
    assert chosen == "out:total"


@pytest.mark.parametrize("answer", [
    # a header no shown passage prints
    {"value": "Summe", "value_raw": "Gebäudetyp",
     "quote": "| Gebäudetyp | Wärmebedarf nach Energieträger |"},
    # a wording its quote does not hold
    {"value": "Summe", "value_raw": "Energieträger",
     "quote": "| Gebäudetyp | Endenergiebedarf [MWh/a] |"},
])
def test_a_total_whose_quote_does_not_carry_it_is_never_read(answer):
    got = [row()]
    merge_field(got, [TABLE], CARRIER, {"answers": {"R1": answer}})
    assert got[0].claim["carrier_state"] == fields.UNBACKED
    assert "carrier" not in got[0].claim


# -- the vectors: many callers, few calls --------------------------------------

class SlowModel:
    def __init__(self):
        self.calls = []
        self.gate = threading.Event()

    def embed(self, items):
        self.calls.append(len(items))
        self.gate.wait(2)
        return [[float(len(item["text"]))] for item in items]


def test_concurrent_embeds_share_calls_and_each_gets_its_own_vectors():
    model = SlowModel()
    coalescer = runner.Coalescer(lambda: model)
    got = {}

    def ask(text):
        got[text] = coalescer.embed([{"text": text}, {"text": text * 2}])

    threads = [threading.Thread(target=ask, args=("x" * n,))
               for n in range(1, 13)]
    for t in threads:
        t.start()
    time.sleep(0.2)
    model.gate.set()
    for t in threads:
        t.join(5)
    assert len(got) == 12
    assert all(got[text] == [[len(text)], [2 * len(text)]] for text in got)
    assert len(model.calls) < 12
    assert sum(model.calls) == 24


def test_a_failing_model_fails_every_caller_of_its_batch():
    class Broken:
        def embed(self, items):
            raise RuntimeError("card gone")

    with pytest.raises(RuntimeError):
        runner.Coalescer(lambda: Broken()).embed([{"text": "a"}])


# -- documents: as many as the server has room for ---------------------------

def test_a_document_starts_only_while_requests_are_below_the_limit():
    limit = SimpleNamespace(in_flight=10, limit=12)
    room = runner.document_room(limit)
    assert room(5) == 1
    limit.in_flight = 12
    assert room(5) == 0
    assert runner.document_room(None) is None


def test_no_room_holds_documents_back_and_room_lets_them_in():
    limit = SimpleNamespace(in_flight=0, limit=1)
    started = []

    def harvest(document_id, filename):
        started.append(document_id)
        limit.in_flight = 1          # the document now holds the limit
        time.sleep(0.05)
        limit.in_flight = 0
        return True, 0

    done, written, failures = runner.harvest_documents(
        [(i, f"d{i}.pdf") for i in range(3)], harvest, in_flight=8,
        room=runner.document_room(limit))
    assert (done, written, failures) == (3, 3, 0)
    assert started == [0, 1, 2]


# -- nothing replaced is lost -----------------------------------------------------

def test_a_replaced_file_is_kept_as_it_was_before_the_run(tmp_path):
    archive.begin("test-pass")
    stamp = tmp_path / "plan.stamp.json"
    stamp.write_text(json.dumps({"producers": []}), encoding="utf-8")
    enter_producer(stamp, {"pass": "a"})
    enter_producer(stamp, {"pass": "b"})
    kept = archive.folder(tmp_path) / "plan.stamp.json"
    assert json.loads(kept.read_text(encoding="utf-8")) == {"producers": []}
    assert len(json.loads(stamp.read_text(encoding="utf-8"))["producers"]) == 2
    assert archive.keep(tmp_path / "missing.jsonl") is None


def test_the_archive_is_not_read_as_part_of_the_harvest(tmp_path):
    archive.begin("test-pass")
    (tmp_path / "a.jsonl").write_text('{"kind": "tuple"}\n', encoding="utf-8")
    archive.keep(tmp_path / "a.jsonl")
    assert stats.from_harvest(tmp_path)["documents"] == 1


# -- where it was hard ----------------------------------------------------------

def test_the_counts_say_what_is_open_off_the_list_and_outside_it(tmp_path):
    lines = [
        {"kind": "tuple", "parameter": "energy_consumption",
         "carrier_state": "read", "carrier": "OEO_00000292",
         "carrier_raw": "Gas H", "carrier_raw_foreign": True,
         "sector_state": "exhausted"},
        {"kind": "tuple", "parameter": "energy_consumption",
         "carrier_state": "read", "carrier": "out:total",
         "carrier_raw": "Gebäudetyp", "sector_state": "read",
         "unit_state": "derived"},
        {"kind": "summary"},
    ]
    (tmp_path / "hard.jsonl").write_text(
        "\n".join(json.dumps(x) for x in lines), encoding="utf-8")
    (tmp_path / "easy.jsonl").write_text(json.dumps(lines[1]),
                                         encoding="utf-8")
    trace = tmp_path / "trace"
    trace.mkdir()
    (trace / "hard.trace.jsonl").write_text("\n".join(json.dumps(x) for x in [
        {"t": "field", "slot": "carrier", "stage": "rest", "filled": 0},
        {"t": "field", "slot": "carrier", "stage": "own", "filled": 2},
        {"t": "drop", "field": "carrier", "why": "not_an_option",
         "given": "Abwärme Rechenzentrum", "raw": "RZ-Abwärme"},
    ]), encoding="utf-8")
    got = stats.collect(tmp_path, [trace])
    axes = got["coordinates_by_parameter_axis_state"]["energy_consumption"]
    assert axes["sector"] == {"exhausted": 1, "read": 1, "derived": 0} \
        or axes["sector"] == {"exhausted": 1, "read": 2}
    assert got["documents_by_open_share"][0]["document"] == "hard"
    assert got["read_with_wording_off_the_list"]["carrier"] == [
        {"value": "OEO_00000292", "wording": "Gas H", "coordinates": 1}]
    assert got["read_as_total"]["carrier"] == [
        {"wording": "Gebäudetyp", "coordinates": 2}]
    assert got["requests_and_fills_by_axis_stage"]["carrier"]["rest"] == {
        "requests": 1, "coordinates_filled": 0}
    assert got["answers_outside_the_list"]["carrier"][0]["given"] == \
        "Abwärme Rechenzentrum"


def test_an_empty_harvest_counts_nothing(tmp_path):
    got = stats.collect(tmp_path, [tmp_path / "none"])
    assert got["documents"] == 0 and got["documents_by_open_share"] == []
