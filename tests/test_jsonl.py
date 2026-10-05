"""One record is one line, and a line ends at a line feed and nowhere else.

A quote copied from a PDF can carry U+2028, U+2029 or U+0085. The writers
leave them as they are (`ensure_ascii=False`), and `str.splitlines()` breaks
a line at each of them. What is promised for every reader of a JSON Lines
file:

  * a record whose text carries one of the three is read as one record;
  * a reader that writes the file back writes that record back whole;
  * no reader in the package splits a file's text with `splitlines()`.
"""
import json
import re
import sqlite3
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from docpipe import jsonl
from docpipe.extraction import gold, identity, serialize
from docpipe.providers import cassette
from docpipe.store import schema

ROOT = Path(__file__).resolve().parent.parent
BREAKS = [" ", " ", "\u0085"]


def test_a_line_ends_at_a_line_feed_and_nowhere_else():
    text = 'a b\n\nc\u0085d e\n'
    assert jsonl.lines(text) == ["a b", "", "c\u0085d e"]
    assert jsonl.lines("") == []
    assert jsonl.lines("a") == ["a"]            # no feed after the last line
    # what the readers did before, and why it broke
    assert len(text.splitlines()) == 6


def test_reading_a_file_folds_the_carriage_return(tmp_path):
    path = tmp_path / "a.jsonl"
    path.write_bytes(b'{"a": 1}\r\n{"b": 2}\r\n')
    assert jsonl.read(path) == ['{"a": 1}', '{"b": 2}']


def _tuple(quote, owner=7):
    return {"kind": "tuple", "parameter": "energy", "value": 120.0,
            "value_raw": "120", "quote": quote,
            "provenance": {"document_id": 1, "owner_kind": "section",
                           "owner_id": owner}}


def _write(path, rows):
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n"
                            for row in rows), encoding="utf-8")


@pytest.mark.parametrize("mark", BREAKS)
def test_the_harvest_reader_keeps_a_row_whose_quote_carries_one(tmp_path,
                                                               mark):
    quote = f"Der Bedarf{mark}liegt bei 120 GWh"
    _write(tmp_path / "a.jsonl", [_tuple(quote), _tuple("120 GWh"),
                                  {"kind": "summary", "tuples": 2}])
    rows = serialize.collect(tmp_path)["a"]
    assert [row["quote"] for row in rows] == [quote, "120 GWh"]


@pytest.mark.parametrize("mark", BREAKS)
def test_a_decision_with_one_in_its_note_is_read(tmp_path, mark):
    path = tmp_path / "gold.jsonl"
    row = _tuple("120 GWh")
    gold.decide(path, "a", row, "value", gold.CORRECT, note=f"a{mark}b",
                by="r")
    gold.mark_checked(path, "a")
    found = gold.read(path)
    assert [record["kind"] for record in found] == ["verdict", "checked"]
    assert found[0]["note"] == f"a{mark}b"


@pytest.mark.parametrize("mark", BREAKS)
def test_a_recorded_answer_with_one_is_replayed(tmp_path, mark, monkeypatch):
    tape = tmp_path / "tape.jsonl"
    asked = {"model": "m", "messages": [
        {"role": "user", "content": f"Zeile eins{mark}Zeile zwei"}]}
    record = {"kind": "chat", "key": cassette.chat_key(asked),
              "content": f"Antwort{mark}Ende", "finish_reason": "stop"}
    tape.write_text(json.dumps({"kind": "header"}) + "\n"
                    + json.dumps(record, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    player = cassette.Player(tape)              # raised on the broken line
    reply = player.chat.completions.create(**asked)
    assert reply.choices[0].message.content == f"Antwort{mark}Ende"
    assert player.missed == 0


@pytest.mark.parametrize("mark", BREAKS)
def test_a_file_written_back_keeps_such_a_row_whole(tmp_path, mark):
    """The re-anchor pass rewrites the file when one row moved. The row
    beside it, with the character in its quote, comes back as it was."""
    sections = {41: "Vorwort", 42: "x Der Bedarf liegt bei 120 GWh y",
                7: f"Die Leistung{mark}betraegt 5 MW"}
    database = tmp_path / "db"
    with sqlite3.connect(database) as conn:
        schema.apply(conn)
        conn.execute("INSERT INTO Documents (id, filename) "
                     "VALUES (1, 'a.pdf')")
        for number, (owner, text) in enumerate(sections.items()):
            conn.execute(
                "INSERT INTO Sections (id, document, section_number, content)"
                " VALUES (?, 1, ?, ?)", (owner, number, text))

    def owner_sources(owners):
        return {(kind, owner): NS(text=sections[owner])
                for kind, owner in owners
                if kind == "section" and owner in sections}

    harvest = tmp_path / "a.jsonl"
    stays = _tuple(f"Die Leistung{mark}betraegt 5 MW", owner=7)
    moved = _tuple("Der Bedarf liegt bei 120 GWh", owner=9)
    _write(harvest, [stays, moved, {"kind": "summary", "tuples": 2}])
    with sqlite3.connect(database) as conn:
        stats = identity.reanchor_file(
            harvest, conn, owner_sources, lambda text, quote: quote in text)
    assert stats["rows"] == 2
    assert stats["rows given their passage's new address"] == 1
    after = [json.loads(line) for line in jsonl.read(harvest)]
    assert len(after) == 3                      # and every line still parses
    assert after[0] == stays
    assert after[1]["provenance"]["owner_id"] == 42


FILE_SPLIT = re.compile(r"read_text\([^)]*\)\s*\.splitlines\(\)")


def test_no_reader_splits_a_files_text_at_more_than_the_line_feed():
    """Every reader of a harvest, a gold file or a recording goes through
    `jsonl`. The pattern is the one all of them had."""
    assert FILE_SPLIT.search('x = p.read_text(encoding="utf-8").splitlines()')
    readers = [path for folder in ("extraction", "providers", "serve",
                                   "inference", "app")
               for path in sorted((ROOT / "docpipe" / folder).rglob("*.py"))]
    readers += [ROOT / "scripts" / name for name in (
        "curation_list.py", "harvest_lists.py", "harvest_compare.py",
        "harvest_report.py", "trace_report.py")]
    found = [path.relative_to(ROOT).as_posix() for path in readers
             if FILE_SPLIT.search(path.read_text(encoding="utf-8"))]
    assert found == []
