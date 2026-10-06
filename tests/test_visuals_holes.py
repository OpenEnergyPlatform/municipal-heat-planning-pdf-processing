"""An item the model gave no object for is a hole with its cause.

Promised: a table or figure without a readable reply has no markdown or
description AND says why in `vlm_why` AND is counted by kind and by cause AND is
asked again by the next run, which asks no item that has its content AND the
run's exit code does not move, while the run says what it left without content
in tables, figures and documents AND an item an older run stored as a plain-text
answer is asked again only with --force-stale.

Nothing fills a hole in: no plain-text request, no salvage of a cut reply.
"""
import json
import logging
import sys
import types

import pytest

from docpipe import prompts
from docpipe.reading import Hole
from docpipe.visuals import config as C
from docpipe.visuals import pipeline as IP
from docpipe.visuals import process as P
from docpipe.visuals.models import ProcessingStats

GOOD_TABLE = "| h | h |\n| --- | --- |\n| a | 1 |\n| b | 2 |"
STUTTER = "| --- | --- |\n| a | 1 |\n| a | 1 |\n| a | 1 |\n| a | 1 |"


@pytest.fixture
def images(tmp_path):
    (tmp_path / "images").mkdir()
    for name in ("t.png", "f.png"):
        (tmp_path / "images" / name).write_bytes(b"x")
    return tmp_path


def _table(images, response):
    stats = ProcessingStats()
    result = P.process_table(
        {"id": "t", "path": "images/t.png", "source_text": "x"},
        {"title": "S"}, images, None, stats)
    return result, stats


# ---------------------------------------------------------------------------
# AND 1 + 2 + 3: no content, the cause, the count
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cause", ["cut_off", "no_object", "syntax",
                                   "outside_text", "missing_key", "refused",
                                   "not_served", "error", "empty"])
def test_a_table_that_could_not_be_read_is_a_hole_with_its_cause(
        images, monkeypatch, cause):
    monkeypatch.setattr(P, "call_vision", lambda *a, **k: Hole(cause))
    result, stats = _table(images, None)
    assert "markdown" not in result and "qa" not in result, (
        "not checked is not the same as passed")
    assert result["vlm_why"] == cause
    assert "vlm_status" not in result, "the plain-text status is no longer written"
    assert (stats.failed_tables, stats.failed_figures) == (1, 0)
    assert stats.hole_causes == {cause: 1}
    assert stats.processed_tables == 0


def test_a_figure_that_could_not_be_read_is_a_hole_with_its_cause(
        images, monkeypatch):
    monkeypatch.setattr(P, "call_vision", lambda *a, **k: Hole("cut_off"))
    stats = ProcessingStats()
    result = P.process_figure({"id": "f", "path": "images/f.png"}, {"title": "S"},
                              images, None, stats)
    assert "description" not in result and result["vlm_why"] == "cut_off"
    assert (stats.failed_tables, stats.failed_figures) == (0, 1)
    assert stats.hole_causes == {"cut_off": 1}


def test_no_second_request_fills_the_hole_in(images, make_client, seq_responder):
    """Four unreadable answers: exactly the retries, each with the schema, and
    nothing in the item that came out of the text. The plain-text request is gone."""
    rec: list = []
    client = make_client(seq_responder(["| a | b |\n|---|---|"]), recorder=rec)
    stats = ProcessingStats()
    result = P.process_table({"id": "t", "path": "images/t.png"}, {"title": "S"},
                             images, client, stats)
    assert len(rec) == 4
    assert all(r["response_format"]["json_schema"]["name"] == "table_reply"
               for r in rec)
    assert "markdown" not in result and result["vlm_why"] == "no_object"
    for name in ("_rescue_plain", "_PLAIN_HINT"):
        assert not hasattr(P, name), name


def test_a_qa_retry_that_is_a_hole_keeps_the_first_attempt(images, monkeypatch):
    """The first reply stuttered (it fails the check), the retry is a hole: the
    table keeps what it was read, and is not counted as a hole."""
    answers = iter([{"markdown": STUTTER, "caption": "C"}, Hole("cut_off")])
    monkeypatch.setattr(P, "call_vision", lambda *a, **k: next(answers))
    result, stats = _table(images, None)
    assert result["markdown"].count("| a | 1 |") == 1, "kept, collapsed"
    assert "vlm_why" not in result
    assert (stats.failed_tables, stats.processed_tables) == (0, 1)
    assert stats.hole_causes == {}


def test_the_summary_says_what_has_no_content_and_nothing_was_rescued():
    stats = ProcessingStats(total_tables=5, total_figures=2)
    stats.hole("table", "cut_off")
    stats.hole("table", "cut_off")
    stats.hole("figure", "no_object")
    out = stats.summary()
    assert "Items without content: 2 table(s), 1 figure(s) (cut_off 2, " \
        "no_object 1)" in out
    assert "Rescued" not in out and "plain text" not in out
    assert not hasattr(stats, "rescued_tables")
    assert not hasattr(stats, "rescued_figures")
    assert "Items without content: 0 table(s), 0 figure(s)\n" in \
        ProcessingStats().summary()


# ---------------------------------------------------------------------------
# The stage: the file, the cache, the crash
# ---------------------------------------------------------------------------

def _document(tmp_path, tables=("t0", "t1"), figures=("f0",)):
    (tmp_path / "results").mkdir(parents=True)
    (tmp_path / "images").mkdir()
    sections = [{"title": "S", "page_number": 1,
                 "content": " ".join(f"[{i}]" for i in (*tables, *figures)),
                 "tables": [{"id": i, "path": f"images/{i}.png",
                             "page_number": 1, "source_text": "x"}
                            for i in tables],
                 "figures": [{"id": i, "path": f"images/{i}.png",
                              "page_number": 1} for i in figures]}]
    (tmp_path / "results" / "sections.json").write_text(
        json.dumps({"sections": sections}), encoding="utf-8")
    for name in (*tables, *figures):
        (tmp_path / "images" / f"{name}.png").write_bytes(b"x")
    return tmp_path


def _model(monkeypatch, outcome):
    """The vision model, with only the request stubbed: *outcome(kind, id)* is
    a Hole, or None for an item that is read. Returns the ids asked for."""
    asked: list = []

    def call(client, system, user, image, **kwargs):
        kind = "table" if kwargs["reply"][0] == "table_reply" else "figure"
        item = image.stem
        asked.append(item)
        hole = outcome(kind, item)
        if hole is not None:
            return hole
        return ({"markdown": GOOD_TABLE, "caption": "C"} if kind == "table"
                else {"description": "D", "caption": "C"})

    monkeypatch.setattr(P, "call_vision", call)
    monkeypatch.setattr(IP, "create_client", lambda **k: types.SimpleNamespace(
        models=types.SimpleNamespace(list=lambda: types.SimpleNamespace(
            data=[types.SimpleNamespace(id=C.VLM_MODEL)]))))
    monkeypatch.setattr(IP, "check_model_available", lambda *a, **k: True)
    return asked


def _items(written):
    return {i["id"]: i for s in written["sections"]
            for i in (*s["tables"], *s["figures"])}


def test_a_document_with_holes_is_written_and_the_next_run_asks_only_them(
        tmp_path, monkeypatch):
    doc = _document(tmp_path)
    asked = _model(monkeypatch, lambda kind, item: Hole("cut_off")
                   if item == "t1" else None)
    written = IP.run_single(doc)
    items = _items(written)
    assert "markdown" not in items["t1"] and items["t1"]["vlm_why"] == "cut_off"
    assert items["t0"]["markdown"] and items["f0"]["description"]
    on_disk = json.loads((doc / "results" / "visuals.json").read_text(
        encoding="utf-8"))
    assert _items(on_disk)["t1"]["vlm_why"] == "cut_off"

    again = _model(monkeypatch, lambda kind, item: None)
    written = IP.run_single(doc)
    assert again == ["t1"], "an item that has its content is not asked again"
    items = _items(written)
    assert items["t1"]["markdown"] and "vlm_why" not in items["t1"], (
        "the new answer is the item, with no trace of the hole")
    assert sorted(asked) == ["f0", "t0", "t1"], "the first run asked every item"


def test_a_crash_of_our_own_is_counted_as_a_hole_named_error(tmp_path,
                                                             monkeypatch):
    doc = _document(tmp_path)
    _model(monkeypatch, lambda kind, item: None)
    real = P.process_table

    def boom(table, *args, **kwargs):
        if table["id"] == "t1":
            raise RuntimeError("worker crash")
        return real(table, *args, **kwargs)

    monkeypatch.setattr(IP, "process_table", boom)
    holes: list = []
    written = IP.run_single(doc, holes=holes)
    items = _items(written)
    assert items["t1"]["vlm_why"] == "error" and "markdown" not in items["t1"]
    assert "source_text" not in items["t1"]
    assert (doc / "results" / "visuals.json").exists(), "the file is written"
    assert holes == [{"document": doc.name, "tables": 1, "figures": 0,
                      "causes": {"error": 1}}], "a crash is counted, as it was not"


def test_the_hole_entry_counts_items_by_kind_and_cause(tmp_path, monkeypatch):
    doc = _document(tmp_path)
    _model(monkeypatch, lambda kind, item: {
        "t0": Hole("cut_off"), "f0": Hole("no_object")}.get(item))
    holes: list = []
    IP.run_single(doc, holes=holes)
    assert holes == [{"document": doc.name, "tables": 1, "figures": 1,
                      "causes": {"cut_off": 1, "no_object": 1}}]


def test_a_clean_document_adds_no_entry(tmp_path, monkeypatch):
    doc = _document(tmp_path)
    _model(monkeypatch, lambda kind, item: None)
    holes: list = []
    IP.run_single(doc, holes=holes)
    assert holes == []


# ---------------------------------------------------------------------------
# AND 4: the exit code does not move, the run says what it left
# ---------------------------------------------------------------------------

def _main(root, monkeypatch, caplog):
    monkeypatch.setattr(sys, "argv", ["visuals", str(root), "--batch"])
    monkeypatch.setattr(IP, "assert_serving", lambda *a, **k: None)
    monkeypatch.setattr(IP, "DOC_PARALLEL", 1)
    with caplog.at_level(logging.WARNING):
        with pytest.raises(SystemExit) as stopped:
            IP.main()
    return stopped.value.code


def test_a_run_with_holes_exits_as_it_did_and_says_what_it_left(
        tmp_path, monkeypatch, caplog):
    _document(tmp_path / "plan")
    _model(monkeypatch, lambda kind, item: {
        "t0": Hole("cut_off"), "f0": Hole("cut_off")}.get(item))
    assert _main(tmp_path, monkeypatch, caplog) == 0
    said = [r.getMessage() for r in caplog.records
            if r.getMessage().startswith("Stage 5:")]
    assert said == ["Stage 5: 1 table(s) and 1 figure(s) in 1 document(s) have "
                    "no content; item(s) by cause: cut_off 2; the next run "
                    "asks only for those"]


def test_a_clean_run_says_nothing_of_holes(tmp_path, monkeypatch, caplog):
    _document(tmp_path / "plan")
    _model(monkeypatch, lambda kind, item: None)
    assert _main(tmp_path, monkeypatch, caplog) == 0
    assert not [r for r in caplog.records
                if r.getMessage().startswith("Stage 5:")]


def test_the_summary_adds_up_documents_tables_and_figures():
    entries = [{"document": "a", "tables": 2, "figures": 0,
                "causes": {"cut_off": 1, "syntax": 1}},
               {"document": "b", "tables": 1, "figures": 3,
                "causes": {"cut_off": 4}}]
    assert IP.summarise(entries) == (
        "Stage 5: 3 table(s) and 3 figure(s) in 2 document(s) have no "
        "content; item(s) by cause: cut_off 5, syntax 1; the next run asks "
        "only for those")


# ---------------------------------------------------------------------------
# AND 5: stored items, and what the cache keeps
# ---------------------------------------------------------------------------

def _stored(doc, **by_id):
    """A visuals.json an earlier run left: {id: the item's keys}."""
    sections = json.loads((doc / "results" / "sections.json").read_text(
        encoding="utf-8"))["sections"]
    for section in sections:
        for kind in ("tables", "figures"):
            section[kind] = [{**item, **by_id.get(item["id"], {})}
                             for item in section[kind]]
    (doc / "results" / "visuals.json").write_text(
        json.dumps({"sections": sections}), encoding="utf-8")
    # written under the prompts of today, as the run that wrote it records
    prompts.record(doc, C.PROMPT_IDS)


def test_an_item_with_content_is_cached_and_one_with_a_cause_is_asked_again(
        tmp_path, monkeypatch):
    doc = _document(tmp_path)
    _stored(doc, t0={"markdown": "| old |"}, t1={"vlm_why": "cut_off"},
            f0={"description": "old"})
    asked = _model(monkeypatch, lambda kind, item: None)
    written = IP.run_single(doc)
    assert asked == ["t1"]
    assert _items(written)["t0"]["markdown"] == "| old |"


def test_an_item_an_older_run_stored_as_plain_text_is_said_and_asked_again_only_with_force_stale(
        tmp_path, monkeypatch, caplog):
    """The case built to break it: a salvaged half table, stored for good by the
    run that wrote it. A plain run keeps it and says how many there are; only
    --force-stale asks them again."""
    doc = _document(tmp_path)
    _stored(doc, t0={"markdown": "| first half", "vlm_status": "plain_text"},
            t1={"markdown": "| whole |"},
            f0={"description": "text", "vlm_status": "plain_text"})
    asked = _model(monkeypatch, lambda kind, item: None)
    with caplog.at_level(logging.WARNING):
        IP.run_single(doc)
    assert asked == [], "nothing is asked again on a plain run"
    said = [r.getMessage() for r in caplog.records
            if "stored as a plain-text answer" in r.getMessage()]
    assert len(said) == 1 and said[0].startswith("2 cached item(s)")
    assert "--force-stale" in said[0]

    asked = _model(monkeypatch, lambda kind, item: None)
    written = IP.run_single(doc, force_stale=True)
    assert sorted(asked) == ["f0", "t0"], "exactly the items that were plain text"
    items = _items(written)
    assert items["t0"]["markdown"] == GOOD_TABLE and "vlm_status" not in items["t0"]
    assert items["t1"]["markdown"] == "| whole |"


def test_stored_items_without_the_status_key_are_nothing_special(
        tmp_path, monkeypatch, caplog):
    """A key an older file does not carry says: read as before. None of the
    items of a file from before the status existed is asked again."""
    doc = _document(tmp_path)
    _stored(doc, t0={"markdown": "| a |"}, t1={"markdown": "| b |"},
            f0={"description": "d"})
    asked = _model(monkeypatch, lambda kind, item: None)
    with caplog.at_level(logging.WARNING):
        IP.run_single(doc, force_stale=True)
    assert asked == []
    assert not [r for r in caplog.records
                if "plain-text" in r.getMessage()]
