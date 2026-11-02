"""A row of a table is written once with its numbers, a table too long for one
answer is read in halves, a request's time follows its room, and a year is a
number the profile takes for a year."""
import json
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

import pytest

from docpipe.extraction import pipeline, runner

SPEC = runner.load_spec(json.loads(
    (Path(__file__).resolve().parent.parent / "profiles" / "kwp"
     / "extraction_spec.json").read_text(encoding="utf-8")))

TABLE = "\n".join([
    "Tab. 11: Einsparpotenzial",
    "| Gemeinde | privat | gewerbl. |",
    "| --- | --- | --- |",
    "| | Wert | Wert |",
    "| Alt Zachun | -1.155 | -198 |",
    "| Bandenitz | -2.429 | -152 |",
    "| Belsch | -1.812 | -14 |",
    "| Bobzin | -1.292 | -142 |",
])


@dataclass
class Source:
    text: str
    owner_kind: str = "table"
    owner_id: int = 1
    image_path: Optional[str] = "crop.png"


@dataclass
class Item:
    source: Source


@dataclass
class Batch:
    items: list


def reply_with(tuples):
    return runner._parse_reply(runner.json.dumps(
        {"tuples": tuples, "status": "complete"}))["tuples"]


def test_an_entry_with_values_is_one_tuple_per_value():
    got = reply_with([{"source": "Q1", "unit_raw": "MWh/a", "quote": "| a |",
                       "values": [1, 2, 3]}])
    assert [t["value"] for t in got] == [1, 2, 3]
    assert all(t["quote"] == "| a |" and t["unit_raw"] == "MWh/a"
               and "values" not in t for t in got)


def test_an_entry_with_one_value_stays_as_it_was():
    plain = {"source": "Q1", "value": 7, "quote": "| a |"}
    assert reply_with([plain]) == [plain]


def test_values_are_not_shared_through_defaults():
    got = runner._parse_reply(
        '{"tuples": [{"value": 1, "quote": "eine Zeile"}],'
        ' "defaults": {"values": [8, 9]}}')["tuples"]
    assert [t["value"] for t in got] == [1]


def test_a_value_that_is_not_in_the_row_is_a_tuple_of_its_own_to_refuse():
    quote = "| Alt Zachun | -1.155 | -198 |"
    got = reply_with([{"source": "Q1", "quote": quote, "values": [1155, 777]}])
    held = [t["value"] for t in got
            if str(t["value"]) in quote.replace(".", "")]
    assert held == [1155] and len(got) == 2


def test_each_half_of_a_table_keeps_its_headers():
    for half in runner.split_table(Source(TABLE)):
        assert half.text.startswith("\n".join(TABLE.split("\n")[:4]))


def test_a_split_loses_no_row_and_repeats_none():
    first, second = runner.split_table(Source(TABLE))
    rows = TABLE.split("\n")[4:]
    head = 4
    assert first.text.split("\n")[head:] + second.text.split("\n")[head:] \
        == rows


def test_a_half_stays_the_same_passage_without_its_crop():
    for half in runner.split_table(Source(TABLE)):
        assert half.owner_id == 1 and half.image_path is None


@pytest.mark.parametrize("text", [
    "Fließtext ohne Tabelle",
    "| a |\n| --- |\n| 1 |",
    "| a |\n| --- |\n| keine Zahl |",
])
def test_what_has_no_rows_to_divide_is_not_divided(text):
    assert runner.split_table(Source(text)) is None


def test_the_halves_of_one_table_keep_its_label():
    halves = runner._halves(Batch([Item(Source(TABLE))]), 0)
    assert [offset for offset, _ in halves] == [0, 0]


def test_the_halves_of_several_passages_move_their_labels():
    items = [Item(Source("a", "section")), Item(Source("b", "section"))]
    assert [offset for offset, _ in runner._halves(Batch(items), 0)] == [0, 1]


def test_halving_stops_at_its_depth():
    batch = Batch([Item(Source(TABLE))])
    assert runner._halves(batch, runner.SPLIT_DEPTH) is None


def test_a_section_is_not_halved_as_a_table():
    assert runner._halves(Batch([Item(Source(TABLE, "section"))]), 0) is None


def test_time_follows_room_and_a_repeat_keeps_its_limit(monkeypatch):
    monkeypatch.setattr(runner, "LLM_TIMEOUT", 1800)
    assert runner.request_timeout(6144, 6144, False) is None
    assert runner.request_timeout(6144, 6144, True) == runner.RETRY_TIMEOUT
    twice = runner.request_timeout(12288, 6144, True)
    assert twice == runner.LLM_TIMEOUT * 2 and twice > runner.RETRY_TIMEOUT


def test_a_cut_reply_leaves_both_ends_and_another_leaves_none():
    reply = SimpleNamespace(message=SimpleNamespace(content="a" * 400 + "b"))
    ends = runner._cut_ends(reply, "cut_off")
    assert ends["head"] == "a" * 300 and ends["tail"].endswith("b")
    assert runner._cut_ends(reply, "syntax") == {}


class Years:
    def component(self, stage, name):
        return (1900, 2100) if name == "YEAR_RANGE" else None


@pytest.fixture
def years(monkeypatch):
    monkeypatch.setattr(pipeline, "active_profile", lambda: Years())


NUMBER = SimpleNamespace(kind=pipeline.NUMBER)


@pytest.mark.parametrize("given", [2045, 2045.0, "2045", 1900, 2100])
def test_a_year_in_the_range_passes(years, given):
    assert pipeline._wrong_type(NUMBER, given) is None


@pytest.mark.parametrize("given", [169002, 169002.0, "169002", 1899, 2101])
def test_a_number_outside_the_range_is_refused(years, given):
    assert pipeline._wrong_type(NUMBER, given) is not None


def test_a_profile_without_a_range_takes_every_whole_number(monkeypatch):
    monkeypatch.setattr(pipeline, "active_profile", lambda: None)
    assert pipeline._wrong_type(NUMBER, 169002) is None


def test_the_frame_refuses_a_zone_number_as_its_year(years):
    source = Source("| 169002 | Toddin | 113 |", "table")
    year = SimpleNamespace(name="year", kind=pipeline.NUMBER, options=())
    rejected = []
    pairs = runner.frame_pairs(
        {"pairs": [{"year": 169002, "year_quote": "| 169002 | Toddin | 113 |",
                    "year_source": "Q1"}]}, [year], [source], rejected)
    assert pairs == [] and len(rejected) == 1


def test_the_frame_takes_a_year_it_can_read(years):
    source = Source("Zieljahr 2045 im Szenario", "section")
    year = SimpleNamespace(name="year", kind=pipeline.NUMBER, options=())
    pairs = runner.frame_pairs(
        {"pairs": [{"year": 2045, "year_quote": "Zieljahr 2045 im Szenario",
                    "year_source": "Q1"}]}, [year], [source], [])
    assert [p["year"] for p in pairs] == [2045]


@pytest.mark.parametrize("ran, kept", [
    ({"ok": True, "stdout": "48\n", "error": None}, "48\n"),
    ({"ok": False, "stdout": "", "error": "code-exec disabled"}, ""),
])
def test_a_sandbox_round_is_on_the_trace_and_on_the_values(monkeypatch, ran,
                                                           kept):
    replies = iter(['{"action": "python", "code": "print(48)"}',
                    '{"tuples": [{"source": "Q1", "value": 48, "computed": true,'
                    ' "quote": "120 GWh, davon 40 Prozent"}], "status": "complete"}'])

    def create(**_):
        return SimpleNamespace(
            usage=None, choices=[SimpleNamespace(
                finish_reason="stop",
                message=SimpleNamespace(content=next(replies)))])

    client = SimpleNamespace(chat=SimpleNamespace(
        completions=SimpleNamespace(create=create)))
    events = []
    monkeypatch.setattr(runner, "_client", lambda *a, **k: client)
    monkeypatch.setattr(runner.trace, "event",
                        lambda kind, doc=None, /, **f: events.append((kind, f)))
    monkeypatch.setattr("docpipe.inference.code_exec.run_code",
                        lambda *a, **k: ran)
    source = pipeline.Source(owner_kind="section", owner_id=1,
                             text="120 GWh, davon 40 Prozent", provenance={})
    batch = pipeline.Batch(1, None, [pipeline.WorkItem(1, None, source)])
    got = runner.make_harvester(spec=SPEC)(batch, [])
    assert [f["ok"] for kind, f in events if kind == "code"] == [ran["ok"]]
    assert got["tuples"][0]["compute"][0]["stdout"] == kept


ROW = "| Wohnen | 120 | 80 |"
NEXT = "| Gewerbe | 40 | 30 |"


def reread_harvest(monkeypatch, *said):
    """A rows request over two table rows, answered by *said* in turn. The
    replies it got, and the conversation of each, for the assertions."""
    told = iter(said)
    asked = []

    def create(**request):
        asked.append(request["messages"])
        return SimpleNamespace(usage=None, choices=[SimpleNamespace(
            finish_reason="stop", message=SimpleNamespace(content=next(told)))])

    client = SimpleNamespace(chat=SimpleNamespace(
        completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(runner, "_client", lambda *a, **k: client)
    monkeypatch.setattr(runner.trace, "event", lambda *a, **k: None)
    source = pipeline.Source(owner_kind="table", owner_id=1, provenance={},
                             text=f"{ROW}\n{NEXT}")
    batch = pipeline.Batch(1, None, [pipeline.WorkItem(1, None, source)])
    return runner.make_harvester(spec=SPEC)(batch, []), asked


def entries(*pairs):
    return json.dumps({"tuples": [
        {"source": "Q1", "values": values, "quote": quote}
        for values, quote in pairs], "status": "complete"})


def numbers_of(got):
    return sorted((t["value"], t["quote"]) for t in got["tuples"])


def test_a_number_under_the_wrong_row_is_asked_again_and_named(monkeypatch):
    got, asked = reread_harvest(
        monkeypatch, entries(([120, 40], ROW)), entries(([40], NEXT)))
    assert numbers_of(got) == [(40, NEXT), (120, ROW)]
    assert len(asked) == 2
    assert "40" in asked[1][-1]["content"]


def test_numbers_their_quote_prints_cost_no_second_request(monkeypatch):
    got, asked = reread_harvest(monkeypatch, entries(([120, 80], ROW)))
    assert numbers_of(got) == [(80, ROW), (120, ROW)]
    assert len(asked) == 1


def test_a_number_not_given_again_stays_to_be_refused(monkeypatch):
    got, _asked = reread_harvest(
        monkeypatch, entries(([120, 999], ROW)), entries())
    assert numbers_of(got) == [(120, ROW), (999, ROW)]


def test_an_unreadable_second_reply_leaves_the_first(monkeypatch):
    got, asked = reread_harvest(
        monkeypatch, entries(([120, 999], ROW)), "no object")
    assert numbers_of(got) == [(120, ROW), (999, ROW)]
    assert len(asked) == 2


def test_a_wrong_second_quote_is_not_asked_a_third_time(monkeypatch):
    got, asked = reread_harvest(
        monkeypatch, entries(([999], ROW)), entries(([999], NEXT)))
    assert numbers_of(got) == [(999, NEXT)]
    assert len(asked) == 2
