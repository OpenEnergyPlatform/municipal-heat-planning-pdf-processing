"""Tests for table/figure enrichment workers."""
import json

from docpipe.visuals import config as C
from docpipe.visuals import process as P
from docpipe.visuals.models import ProcessingStats


def _table_reply(markdown, caption="C"):
    return json.dumps({"markdown": markdown, "caption": caption})


_GOOD_TABLE = "| h | h |\n| --- | --- |\n| a | 1 |\n| b | 2 |"
_STUTTER = "| --- | --- |\n| a | 1 |\n| a | 1 |\n| a | 1 |\n| a | 1 |"


def test_truncate():
    assert P._truncate("abc", 10) == "abc"
    assert P._truncate("abcdefghij", 6) == "abc..."


def test_caption_instruction_selection():
    assert P._caption_instruction("has cap", "table") == C.CAPTION_KEEP_INSTRUCTION
    assert P._caption_instruction("", "table") == C.CAPTION_GENERATE_TABLE_INSTRUCTION
    assert P._caption_instruction("", "figure") == C.CAPTION_GENERATE_FIGURE_INSTRUCTION


def test_process_table_missing_image_counts_skip(tmp_path, make_client):
    stats = ProcessingStats()
    client = make_client(lambda kw: None)            # responder never called
    res = P.process_table({"id": "t", "path": "images/missing.png"}, {"title": "S"},
                          tmp_path, client, stats)
    assert "markdown" not in res
    assert stats.skipped_missing == 1


def test_process_table_success(tmp_path, make_client, seq_responder):
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "t.png").write_bytes(b"x")
    stats = ProcessingStats()
    client = make_client(seq_responder(['{"markdown": "MD", "caption": "CAP"}']))
    res = P.process_table({"id": "t", "path": "images/t.png"},
                          {"title": "S", "content": "c"}, tmp_path, client, stats)
    assert res["markdown"] == "MD" and res["caption"] == "CAP"
    assert stats.processed_tables == 1
    assert stats.captions_generated == 1


def test_process_table_qa_retry_recovers(tmp_path, make_client, seq_responder):
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "t.png").write_bytes(b"x")
    stats = ProcessingStats()
    # First reply stutters (high duplication → QA fail); retry is clean.
    client = make_client(seq_responder([_table_reply(_STUTTER), _table_reply(_GOOD_TABLE)]))
    res = P.process_table({"id": "t", "path": "images/t.png"}, {"title": "S"},
                          tmp_path, client, stats)
    assert "| b | 2 |" in res["markdown"]        # took the good retry
    assert "qa_warning" not in res               # passed after retry
    assert stats.processed_tables == 1
    assert stats.qa_failed_tables == 0


def test_process_table_qa_flags_persistent_failure(tmp_path, make_client, seq_responder):
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "t.png").write_bytes(b"x")
    stats = ProcessingStats()
    client = make_client(seq_responder([_table_reply(_STUTTER), _table_reply(_STUTTER)]))
    res = P.process_table({"id": "t", "path": "images/t.png"}, {"title": "S"},
                          tmp_path, client, stats)
    assert res.get("qa_warning") is not None     # both attempts degenerate → flagged
    assert stats.qa_failed_tables == 1
    assert stats.processed_tables == 1
    assert res["markdown"].count("| a | 1 |") == 1   # kept best effort, deduped


def test_process_table_coverage_triggers_retry(tmp_path, make_client, seq_responder):
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "t.png").write_bytes(b"x")
    stats = ProcessingStats()
    src = ("Energieträger Anteil Erdgas 45,2 Fernwärme 23,1 Wärmepumpe 12,8 "
           "Solar 5,0 Biomasse 9,1")
    truncated = "| Energieträger | Anteil |\n| --- | --- |\n| Erdgas | 45,2 |"
    full = (truncated + "\n| Fernwärme | 23,1 |\n| Wärmepumpe | 12,8 |"
            "\n| Solar | 5,0 |\n| Biomasse | 9,1 |")
    client = make_client(seq_responder([_table_reply(truncated), _table_reply(full)]))
    res = P.process_table({"id": "t", "path": "images/t.png"}, {"title": "S"},
                          tmp_path, client, stats, source_text=src)
    assert "12,8" in res["markdown"] and "9,1" in res["markdown"]   # recovered missing rows
    assert stats.qa_failed_tables == 0


def test_process_table_passing_keeps_legit_adjacent_duplicates(tmp_path, make_client, seq_responder):
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "t.png").write_bytes(b"x")
    stats = ProcessingStats()
    # Passes QA (duplication 0.2 ≤ 0.4) but has a legitimate repeated adjacent
    # row — must NOT be deduped (no silent data loss on the success path).
    md = "| h | h |\n| --- | --- |\n| a | 1 |\n| a | 1 |\n| b | 2 |\n| c | 3 |"
    client = make_client(seq_responder([_table_reply(md)]))
    res = P.process_table({"id": "t", "path": "images/t.png"}, {"title": "S"},
                          tmp_path, client, stats)
    assert res["markdown"].count("| a | 1 |") == 2   # preserved
    assert "qa_warning" not in res
    assert stats.qa_failed_tables == 0


def test_process_table_strips_source_text_from_output(tmp_path, make_client, seq_responder):
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "t.png").write_bytes(b"x")
    stats = ProcessingStats()
    client = make_client(seq_responder([_table_reply(_GOOD_TABLE)]))
    res = P.process_table({"id": "t", "path": "images/t.png", "source_text": "x 1 2"},
                          {"title": "S"}, tmp_path, client, stats, source_text="x 1 2")
    assert "source_text" not in res


def test_process_figure_success(tmp_path, make_client, seq_responder):
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "f.png").write_bytes(b"x")
    stats = ProcessingStats()
    client = make_client(seq_responder(['{"description": "DESC"}']))
    res = P.process_figure({"id": "f", "path": "images/f.png"}, {"title": "S"},
                           tmp_path, client, stats)
    assert res["description"] == "DESC"
    assert stats.processed_figures == 1
