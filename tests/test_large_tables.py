"""A row of a table is written once with its numbers, a table too long for one
answer is read in halves, a request's time follows its room, and a year is a
number the profile takes for a year."""
from dataclasses import dataclass, replace
from types import SimpleNamespace
from typing import Optional

import pytest

from docpipe.extraction import pipeline, runner

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
