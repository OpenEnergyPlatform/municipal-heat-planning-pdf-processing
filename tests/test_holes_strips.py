"""What does not fit is read in parts, and what could not be read is known
downstream (owner request 2026-11-19, points B1 and B2 of the review of that
day, on the rules of 2026-09-12 and 2026-11-17: a request whose reply does
not fit is split and nothing is cut; and on the states: "not stated" is a
finding about the document, not about the run).

The promises, each with a case that breaks it by construction:

1. A table image is cut at a pixel row without writing, between two rows of
   the table and never through one, AND an image with one row of writing has
   no halves.
2. A table whose reply does not fit is read in strips: the first strip as the
   table was asked, every later one shown the first strip's caption and head,
   AND their rows stand under that one head; a strip cut off again is cut
   again, AND one that cannot be cut leaves the table without content; a hole
   of another cause ends the reading with that cause.
3. The tables and figures without content are known by id, kind, page and
   why (Stage 5's cause, else "not_asked"), AND a table with markdown and a
   figure with a description are none of them; a job counts them.
4. The merge writes them into the document and the database keeps them
   beside it, AND a document merged before they were written keeps its row.
5. A run reads them with the documents: a search that found nothing ends in
   the state of unstated_with_holes in such a document, AND in that of
   unstated_after_combing in a document without; a field likewise.
6. The stamp records them, AND a hole with content since makes the document
   work again, while one whose holes stand is current.
"""
from __future__ import annotations

import io
import json
import sqlite3
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw

from docpipe import rules
from docpipe.chunking import database, merge
from docpipe.extraction import engine, fields, holes as run_holes, runner, trust
from docpipe.reading import Hole
from docpipe.store import schema as store_schema
from docpipe.visuals import holes, process, replies, strips
from docpipe.visuals.models import ProcessingStats

ROWS = ["Liegenschaft  Verbrauch", "Kita Nord  61.400", "Schule Sued  230.000",
        "Rathaus  88.100", "Bad West  410.900", "Hof Ost  12.000"]


def table_png(lines=ROWS, gap=9, rules_x=(2, 150, 297)) -> tuple:
    """(PNG, [(top, bottom)] of each row of writing): a table of *lines*,
    a vertical rule at each of *rules_x*, a rule across under each row."""
    width, step = 300, 11 + gap
    height = gap + len(lines) * step
    image = Image.new("L", (width, height), 255)
    draw = ImageDraw.Draw(image)
    for x in rules_x:
        draw.line([(x, 0), (x, height - 1)], fill=0)
    spans = []
    for at, line in enumerate(lines):
        top = gap + at * step
        box = draw.textbbox((8, top), line)
        draw.text((8, top), line, fill=0)
        spans.append((box[1], box[3]))
        y = box[3] + gap // 2
        if at < len(lines) - 1:
            draw.line([(0, y), (width - 1, y)], fill=0)
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue(), spans


def size(png: bytes) -> tuple:
    with Image.open(io.BytesIO(png)) as image:
        return image.size


# -- 1. where an image is cut ----------------------------------------------------

def test_an_image_is_cut_between_two_rows_and_never_through_one():
    png, spans = table_png()
    top, bottom = strips.halves(png)
    width, height = size(png)
    cut = size(top)[1]
    assert size(top)[0] == size(bottom)[0] == width
    assert cut + size(bottom)[1] == height
    assert not any(first <= cut < last for first, last in spans)
    # near the middle: the run of blank rows nearest it
    assert abs(cut - height / 2) <= 11 + 9


def test_an_image_with_one_row_of_writing_has_no_halves():
    png, _ = table_png(["Kita Nord  61.400"])
    assert strips.halves(png) is None
    # the failure by construction: two rows have a blank run between them
    png, _ = table_png(["Kita Nord  61.400", "Schule Sued  230.000"])
    assert strips.halves(png) is not None


def test_the_blank_run_must_have_writing_above_and_below():
    assert strips.cut_at([0, 0, 0, 9, 9, 9, 0, 0]) is None
    assert strips.cut_at([9, 9, 0, 0, 0, 9, 9]) == 3
    # of two blank runs, the one nearer the middle
    assert strips.cut_at([9, 0, 9, 9, 9, 9, 0, 0, 9, 9, 9, 9]) == 7


# -- 2. reading in strips -----------------------------------------------------

def reply_of(png: bytes, first) -> dict:
    """A model that reads a strip by its height: a strip of more than three
    rows does not fit; a later strip writes the head first, as told."""
    height = size(png)[1]
    if height > 3 * 20 + 9:
        return Hole("cut_off", "8192 tokens")
    rows = [f"| row of {height} px |"]
    if first is None:
        return {"rows": ["| Liegenschaft | Verbrauch |", "| --- | --- |",
                         *rows], "caption": "Tabelle 5"}
    return {"rows": ["| Liegenschaft | Verbrauch |", "| --- | --- |", *rows],
            "continues": True}


def test_a_table_is_read_in_strips_under_one_head():
    png, _ = table_png()
    seen = []

    def ask(strip, first):
        seen.append((size(strip)[1], first))
        return reply_of(strip, first)

    got, asked = strips.read(png, ask, "t1")
    assert not isinstance(got, Hole)
    fitted = [height for height, _first in seen if height <= 3 * 20 + 9]
    assert got["strips"] == len(fitted) >= 2
    assert seen[0][1] is None                      # the first as the table
    assert all(first is not None for _h, first in seen[1:])
    assert all(first["caption"] == "Tabelle 5" for _h, first in seen[1:]
               if first is not None)
    heads = [r for r in got["rows"] if r.startswith("| Liegenschaft")]
    assert len(heads) == 1 and got["rows"][1] == "| --- | --- |"
    assert len(got["rows"]) == 2 + got["strips"]
    assert got["caption"] == "Tabelle 5"
    # every pixel row is in exactly one strip read
    assert sum(int(r.split(" ")[3]) for r in got["rows"][2:]) == size(png)[1]
    assert asked == len(seen)


def test_a_strip_that_cannot_be_cut_leaves_the_table_without_content():
    png, _ = table_png()

    def never_fits(strip, first):
        return Hole("cut_off")

    got, asked = strips.read(png, never_fits, "t1")
    assert isinstance(got, Hole) and got.cause == "cut_off"
    assert asked >= 2


def test_a_hole_of_another_cause_ends_the_reading_with_it():
    png, _ = table_png()
    got, asked = strips.read(png, lambda s, f: Hole("not_served"), "t1")
    assert isinstance(got, Hole) and got.cause == "not_served" and asked == 1


@pytest.fixture
def prompts_stub(monkeypatch):
    texts = {"table_system_prompt": "table system",
             "table_user_prompt": "{section_title}|{page_number}|"
                                  "{existing_caption}|{section_content}|"
                                  "{caption_instruction}",
             "table_continued_prompt": " BEFORE {previous_caption}|"
                                       "{previous_head}|{between}",
             "caption_keep_instruction": "keep",
             "caption_generate_table_instruction": "make table"}
    for name, text in texts.items():
        monkeypatch.setattr(process, name, lambda t=text: t)


def test_process_table_reads_a_table_in_strips_where_it_does_not_fit(
        tmp_path, monkeypatch, prompts_stub):
    png, _ = table_png()
    (tmp_path / "t.png").write_bytes(png)
    calls = []

    def call_vision(client, system, user, path, *, reply, picture=None,
                    **kwargs):
        calls.append({"user": user, "reply": reply[0], "picture": picture})
        return reply_of(png if picture is None else picture,
                        None if " BEFORE " not in user else {"x": 1})

    monkeypatch.setattr(process, "call_vision", call_vision)
    stats = ProcessingStats()
    got = process.process_table({"id": "t1", "path": "t.png"},
                                {"title": "S", "content": "text"}, tmp_path,
                                None, stats)
    assert calls[0]["picture"] is None                # the whole table first
    assert all(c["picture"] for c in calls[1:])
    later = [c for c in calls[1:] if " BEFORE " in c["user"]]
    assert later and all(c["reply"] == replies.TABLE_CONTINUED[0]
                         for c in later)
    assert all("| Liegenschaft | Verbrauch |" in c["user"] for c in later)
    assert got["strips"] >= 2 and stats.strip_tables == 1
    assert got["markdown"].count("Liegenschaft") == 1
    assert "vlm_why" not in got


def test_process_table_keeps_a_table_without_content_where_no_strip_fits(
        tmp_path, monkeypatch, prompts_stub):
    png, _ = table_png()
    (tmp_path / "t.png").write_bytes(png)
    monkeypatch.setattr(process, "call_vision",
                        lambda *a, **k: Hole("cut_off"))
    stats = ProcessingStats()
    got = process.process_table({"id": "t1", "path": "t.png"},
                                {"title": "S", "content": "text"}, tmp_path,
                                None, stats)
    assert got["vlm_why"] == "cut_off" and "markdown" not in got
    assert stats.failed_tables == 1 and stats.strip_tables == 0


# -- 3. the holes of a document -----------------------------------------------

SECTIONS = [{"page_number": 4, "tables": [
    {"id": "t1", "page_number": 5}, {"id": "t2", "page_number": 6},
    {"id": "t3"}], "figures": [{"id": "f1", "page_number": 7},
                               {"id": "f2", "page_number": 8}]}]
ENRICHED = {"sections": [{"tables": [
    {"id": "t1", "markdown": "| a |"}, {"id": "t2", "vlm_why": "cut_off"}],
    "figures": [{"id": "f1", "description": "a map"}, {"id": "f2"}]}]}


def test_the_holes_are_known_by_id_kind_page_and_why():
    assert holes.of(SECTIONS, ENRICHED) == [
        {"id": "t2", "kind": "table", "page": 6, "why": "cut_off"},
        {"id": "t3", "kind": "table", "page": 4, "why": "not_asked"},
        {"id": "f2", "kind": "figure", "page": 8, "why": "not_asked"}]
    # the failure by construction: without visuals.json all are holes
    assert len(holes.of(SECTIONS, {})) == 5


def write_document(folder: Path, enriched=ENRICHED) -> Path:
    results = folder / "results"
    results.mkdir(parents=True)
    (results / "sections_refined.json").write_text(
        json.dumps({"sections": SECTIONS}), encoding="utf-8")
    if enriched is not None:
        (results / "visuals.json").write_text(json.dumps(enriched),
                                              encoding="utf-8")
    return results


def test_a_job_counts_the_holes_of_every_document(tmp_path):
    write_document(tmp_path / "a")
    write_document(tmp_path / "b", {"sections": [{"tables": [
        {"id": "t1", "markdown": "x"}, {"id": "t2", "markdown": "y"},
        {"id": "t3", "markdown": "z"}], "figures": [
        {"id": "f1", "description": "d"}, {"id": "f2", "description": "e"}]}]})
    assert holes.count(tmp_path) == (2, 1, 1)
    assert holes.count(tmp_path / "b") == (0, 0, 0)


def test_the_stage_s_command_prints_the_count(tmp_path):
    write_document(tmp_path / "a")
    out = subprocess.run(
        [sys.executable, "-m", "docpipe.visuals", str(tmp_path),
         "--count-holes"], capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip().splitlines()[-1] == "2 1 1"


# -- 4. the merge and the database --------------------------------------------

def test_the_merge_writes_the_holes_into_the_document(tmp_path):
    results = write_document(tmp_path / "plan")
    merged = merge.merge_single(tmp_path / "plan", force=True)
    assert [h["id"] for h in merged["holes"]] == ["t2", "t3", "f2"]
    on_disk = json.loads((results / "document.json").read_text("utf-8"))
    assert on_disk["holes"] == merged["holes"]


def test_the_database_keeps_the_holes_beside_the_document(tmp_path):
    db = tmp_path / "corpus.db"
    with sqlite3.connect(db) as conn:
        store_schema.apply(conn)
        conn.executemany("INSERT INTO Documents (filename) VALUES (?)",
                         [("plan.pdf",), ("older.pdf",)])
    plan = tmp_path / "processed" / "plan" / "results"
    plan.mkdir(parents=True)
    (plan / "document.json").write_text(json.dumps(
        {"sections": [], "holes": [{"id": "t2", "kind": "table", "page": 6,
                                    "why": "cut_off"}]}), encoding="utf-8")
    older = tmp_path / "processed" / "older" / "results"
    older.mkdir(parents=True)
    (older / "document.json").write_text(json.dumps({"sections": []}),
                                         encoding="utf-8")
    got = database.note_holes(db, tmp_path / "processed")
    assert got == {"documents": 1, "with_holes": 1, "items": 1}
    with sqlite3.connect(db) as conn:
        held = dict(conn.execute("SELECT filename, holes FROM Documents"))
    assert json.loads(held["plan.pdf"])[0]["id"] == "t2"
    assert held["older.pdf"] is None        # merged before: left as it was


def test_an_older_database_gains_the_column(tmp_path):
    db = tmp_path / "old.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE Documents (id INTEGER PRIMARY KEY, "
                     "filename TEXT, sha256 TEXT, bytes INTEGER)")
        store_schema.migrate(conn)
        assert "holes" in store_schema.columns(conn, "Documents")


# -- 5. the states of a run ---------------------------------------------------

def database_with(tmp_path, found) -> Path:
    db = tmp_path / "corpus.db"
    with sqlite3.connect(db) as conn:
        store_schema.apply(conn)
        conn.execute("INSERT INTO Documents (id, filename, sha256, bytes, "
                     "holes) VALUES (7, 'plan.pdf', 'ab', 3, ?)",
                     (json.dumps(found),))
    return db


HOLE = [{"id": "t2", "kind": "table", "page": 6, "why": "cut_off"}]


def test_a_search_without_a_find_is_no_finding_about_a_document_with_holes(
        tmp_path):
    runner.note_documents(database_with(tmp_path, HOLE))
    try:
        plan = SimpleNamespace(document_id=7)
        assert engine.combed(plan) == "unstated_with_holes"
        assert fields.state_for(engine.combed(plan)) == fields.EXHAUSTED
        # the failure by construction: a document without holes
        assert engine.combed(SimpleNamespace(document_id=8)) \
            == "unstated_after_combing"
        assert fields.state_for("unstated_after_combing") \
            == fields.SAID_UNSTATED
    finally:
        run_holes.clear()


def test_a_field_without_a_value_in_a_document_with_holes_is_open():
    spec = SimpleNamespace(parameters=[SimpleNamespace(uri="p")])
    with_holes = trust.parameter_states(spec, [], [], holes=True)
    without = trust.parameter_states(spec, [], [])
    assert with_holes[0]["state"] == fields.EXHAUSTED
    assert without[0]["state"] == fields.SAID_UNSTATED


def test_the_cases_are_rules_the_owner_can_set():
    table = rules.default()["state_rules"]
    assert table["unstated_with_holes"] == "exhausted"
    assert table["parameter_with_holes"] == "exhausted"
    with rules.overlaid(state_rules={**table,
                                     "unstated_with_holes": "unstated"}):
        assert fields.state_for("unstated_with_holes") == "unstated"


# -- 6. the stamp ----------------------------------------------------------------

def test_the_stamp_records_the_holes_and_a_filled_one_makes_work(tmp_path):
    runner.note_documents(database_with(tmp_path, HOLE))
    try:
        record = runner.stamp_record("plan")
        assert record[runner.DOCUMENT_KEY]["holes"] == HOLE
        stamp = tmp_path / "plan.stamp.json"
        stamp.write_text(json.dumps(record), encoding="utf-8")
        # the holes stand: nothing filled
        assert runner.holes_filled(stamp, runner.document_current("plan")) \
            == set()
        # filled since: the database holds none now
        (tmp_path / "later").mkdir()
        runner.note_documents(database_with(tmp_path / "later", []))
        assert runner.holes_filled(stamp, runner.document_current("plan")) \
            == {"t2"}
    finally:
        run_holes.clear()


def test_a_document_whose_hole_was_filled_is_harvested_again(
        tmp_path, monkeypatch):
    out = tmp_path / "out"
    out.mkdir()
    (out / "plan.jsonl").write_text("", encoding="utf-8")
    stamp = out / "plan.stamp.json"
    stamp.write_text(json.dumps(
        {runner.DOCUMENT_KEY: {"sha256": "ab", "bytes": 3, "holes": HOLE}}),
        encoding="utf-8")
    monkeypatch.setattr(runner, "read_in_part", lambda path: False)
    monkeypatch.setattr(runner, "stale", lambda path, current: [])
    monkeypatch.setattr(runner, "_stamp_current", lambda *a, **k: {})
    (tmp_path / "now").mkdir()
    runner.note_documents(database_with(tmp_path / "now", []))
    try:
        assert runner.already_done("plan", out, "sha") is False
        runner.note_documents(database_with(tmp_path, HOLE))
        assert runner.already_done("plan", out, "sha") is True
    finally:
        run_holes.clear()
