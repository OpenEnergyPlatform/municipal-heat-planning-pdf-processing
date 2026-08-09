"""The plain-text rescue after the JSON path has given up.

Of 112 parse failures in the August 2026 run, 111 read "No JSON object found in
response" on a 200 OK — the model answered within the same second. Whatever it
wrote, throwing it away leaves the item with nothing at all.
"""
import pytest

from docpipe.visuals import process as P
from docpipe.visuals import vision as V
from docpipe.visuals.models import ProcessingStats


@pytest.fixture
def png(tmp_path):
    p = tmp_path / "t.png"
    p.write_bytes(b"\x89PNG\r\n")
    return p


# ---------------------------------------------------------------------------
# call_vision_plain
# ---------------------------------------------------------------------------

def test_it_returns_the_text_without_the_json_envelope(make_client, seq_responder, png):
    rec = []
    client = make_client(seq_responder(["| a | b |\n|---|---|"]), recorder=rec)

    assert V.call_vision_plain(client, "sys", "user", png) == "| a | b |\n|---|---|"
    assert "response_format" not in rec[0], "the envelope is the thing we dropped"


def test_it_strips_think_blocks_and_fences(make_client, seq_responder, png):
    client = make_client(seq_responder(
        ["<think>hmm</think>```markdown\n| a |\n```"]))

    assert V.call_vision_plain(client, "sys", "user", png) == "| a |"


def test_an_empty_answer_is_not_a_rescue(make_client, seq_responder, png):
    client = make_client(seq_responder(["<think>only reasoning</think>   "]))

    assert V.call_vision_plain(client, "sys", "user", png) is None


def test_a_failing_call_returns_none_rather_than_raising(make_client, seq_responder, png):
    """The rescue runs after everything else already failed — it must not be
    the thing that finally raises."""
    client = make_client(seq_responder([RuntimeError("boom")]))

    assert V.call_vision_plain(client, "sys", "user", png) is None


# ---------------------------------------------------------------------------
# process_table / process_figure take the same route
# ---------------------------------------------------------------------------

def _table(tmp_path):
    (tmp_path / "images").mkdir(exist_ok=True)
    (tmp_path / "images" / "t.png").write_bytes(b"\x89PNG\r\n")
    return {"id": "p1_tbl0", "path": "images/t.png", "page_number": 1}


def _figure(tmp_path):
    (tmp_path / "images").mkdir(exist_ok=True)
    (tmp_path / "images" / "f.png").write_bytes(b"\x89PNG\r\n")
    return {"id": "p1_img0", "path": "images/f.png", "page_number": 1}


def test_a_table_the_json_path_lost_comes_back_as_plain_text(monkeypatch, tmp_path):
    monkeypatch.setattr(P, "call_vision", lambda *a, **k: None)
    monkeypatch.setattr(P, "call_vision_plain", lambda *a, **k: "| Jahr | MWh |")
    stats = ProcessingStats()

    out = P.process_table(_table(tmp_path), {"title": "S", "content": ""},
                          tmp_path, None, stats)

    assert out["markdown"] == "| Jahr | MWh |"
    assert out["vlm_status"] == "plain_text"
    assert (stats.rescued_tables, stats.failed_tables) == (1, 0)


def test_a_figure_the_json_path_lost_comes_back_as_plain_text(monkeypatch, tmp_path):
    monkeypatch.setattr(P, "call_vision", lambda *a, **k: None)
    monkeypatch.setattr(P, "call_vision_plain", lambda *a, **k: "Ein Balkendiagramm.")
    stats = ProcessingStats()

    out = P.process_figure(_figure(tmp_path), {"title": "S", "content": ""},
                           tmp_path, None, stats)

    assert out["description"] == "Ein Balkendiagramm."
    assert out["vlm_status"] == "plain_text"
    assert (stats.rescued_figures, stats.failed_figures) == (1, 0)


def test_only_when_the_rescue_also_comes_back_empty_is_it_a_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(P, "call_vision", lambda *a, **k: None)
    monkeypatch.setattr(P, "call_vision_plain", lambda *a, **k: None)
    stats = ProcessingStats()

    out = P.process_table(_table(tmp_path), {"title": "S", "content": ""},
                          tmp_path, None, stats)

    assert "markdown" not in out, "an empty key would read as a cached success"
    assert (stats.rescued_tables, stats.failed_tables) == (0, 1)


def test_the_rescue_is_not_attempted_when_the_json_path_worked(monkeypatch, tmp_path):
    called = []
    monkeypatch.setattr(P, "call_vision",
                        lambda *a, **k: {"markdown": "| a |", "caption": "C"})
    monkeypatch.setattr(P, "call_vision_plain",
                        lambda *a, **k: called.append(1) or "should not happen")

    out = P.process_table(_table(tmp_path), {"title": "S", "content": ""},
                          tmp_path, None, ProcessingStats())

    assert not called
    assert "vlm_status" not in out


# ---------------------------------------------------------------------------
# Asked for plain text, the model often answers in JSON anyway
# ---------------------------------------------------------------------------

def test_a_json_answer_to_the_plain_request_is_unwrapped(make_client, seq_responder, png):
    """7 of the 12 items rescued in the August 2026 run stored the envelope
    itself as their markdown — `{"markdown": "| a |"}` went into the index."""
    client = make_client(seq_responder(['{"markdown": "| a | b |", "caption": "C"}']))

    assert V.call_vision_plain(client, "sys", "user", png) == "| a | b |"


def test_a_figure_unwraps_its_own_field(make_client, seq_responder, png):
    client = make_client(seq_responder(['{"description": "Ein Diagramm.", "caption": "C"}']))

    assert V.call_vision_plain(client, "sys", "user", png,
                               key="description") == "Ein Diagramm."


def test_json_without_the_expected_field_is_not_stored_raw(make_client, seq_responder, png):
    client = make_client(seq_responder(['{"caption": "only a caption"}']))

    assert V.call_vision_plain(client, "sys", "user", png) is None


def test_genuine_plain_text_still_comes_through(make_client, seq_responder, png):
    client = make_client(seq_responder(["| Jahr | MWh |\n|---|---|\n| 2024 | 12 |"]))

    assert V.call_vision_plain(client, "sys", "user", png).startswith("| Jahr")


# ---------------------------------------------------------------------------
# Runaway detection: sparse Gantt grids make the model lose count
# ---------------------------------------------------------------------------

def test_a_real_table_with_a_few_empty_cells_is_not_a_runaway():
    assert not V.looks_runaway("| Jahr | MWh | | |\n|---|---|---|---|\n| 2024 | 12 | | |")


def test_a_long_run_of_empty_cells_is_a_runaway():
    assert V.looks_runaway("| Zeitlicher Rahmen " + "| " * 40)


def test_both_spacings_are_caught():
    assert V.looks_runaway("|" + " |" * 30)
    assert V.looks_runaway("|" + "  |" * 30)


def test_no_stop_sequence_is_sent(make_client, seq_responder, png):
    """A stop on the empty-cell run cut the answer mid-JSON and cost more in
    repair than it saved in tokens; the detector handles the retry instead."""
    rec = []
    client = make_client(seq_responder(['{"markdown": "| a |"}']), recorder=rec)

    V.call_vision(client, "sys", "user", png)

    assert not rec[0].get("stop")


def test_a_runaway_retries_with_a_penalty_rather_than_asking_for_valid_json(
        make_client, seq_responder, png):
    """Feeding a runaway back as 'fix your JSON' just re-runs the same loop."""
    rec = []
    runaway = '{"markdown": "| Rahmen ' + "| " * 40
    client = make_client(seq_responder([runaway, '{"markdown": "| a |"}']), recorder=rec)

    assert V.call_vision(client, "sys", "user", png) == {"markdown": "| a |"}

    assert rec[1]["extra_body"]["repetition_penalty"] == 1.1
    assert len(rec[1]["messages"]) == 2, "the failed answer must not be echoed back"


def test_a_plain_formatting_slip_still_gets_the_correction_turn(
        make_client, seq_responder, png):
    rec = []
    client = make_client(seq_responder(["not json at all", '{"markdown": "| a |"}']),
                         recorder=rec)

    V.call_vision(client, "sys", "user", png)

    assert len(rec[1]["messages"]) == 4, "the model should see its own answer"
    assert "repetition_penalty" not in rec[1].get("extra_body", {})


# ---------------------------------------------------------------------------
# A stop sequence cuts the envelope open mid-string
# ---------------------------------------------------------------------------

def test_a_truncated_envelope_yields_its_content_not_itself(make_client, seq_responder, png):
    """The stop sequence fires inside a sparse Gantt row, so the JSON never
    closes. Storing the envelope raw is what poisoned 13 items in the August
    2026 redo run."""
    cut = '{\n  "markdown": "| Jahr | MWh |\n| --- | --- |\n| 2024 | 12 | | | | |'
    client = make_client(seq_responder([cut]))

    out = V.call_vision_plain(client, "sys", "user", png)

    assert not out.startswith("{"), "the envelope must never reach the index"
    assert out.startswith("| Jahr | MWh |")
    assert "\n| --- | --- |" in out, "escaped newlines must come back as newlines"


def test_a_truncated_envelope_without_the_key_is_no_content():
    assert V._salvage_truncated('{\n  "caption": "nur eine Bildunterschrift', "markdown") is None


def test_salvage_stops_at_the_closing_quote():
    assert V._salvage_truncated('{"markdown": "| a |", "caption": "C"}', "markdown") == "| a |"


def test_a_figure_envelope_is_salvaged_on_its_own_key(make_client, seq_responder, png):
    client = make_client(seq_responder(['{\n  "description": "Ein Balkendiagramm zeigt']))

    out = V.call_vision_plain(client, "sys", "user", png, key="description")

    assert out == "Ein Balkendiagramm zeigt"


def test_an_unopenable_envelope_is_dropped_rather_than_stored(make_client, seq_responder, png):
    """Better no content than the envelope: an empty markdown keeps the item
    pending, so the next run retries it."""
    client = make_client(seq_responder(['{\n  "irgendwas": "x']))

    assert V.call_vision_plain(client, "sys", "user", png) is None


# ---------------------------------------------------------------------------
# The penalty ladder: gentle first, hard once the loop has proven stubborn
# ---------------------------------------------------------------------------

def test_the_penalty_escalates_across_the_four_attempts(make_client, seq_responder, png):
    """Gentle, and it stays gentle: a harder ladder was tried and broke the
    tables it was meant to save."""
    rec = []
    runaway = '{"markdown": "| Rahmen ' + "| " * 40
    client = make_client(seq_responder([runaway, runaway, runaway, '{"markdown": "| a |"}']),
                         recorder=rec)

    assert V.call_vision(client, "sys", "user", png) == {"markdown": "| a |"}

    got = [r.get("extra_body", {}).get("repetition_penalty") for r in rec]
    assert got == [None, 1.1, 1.3, 1.3], got


def test_the_first_attempt_carries_no_penalty(make_client, seq_responder, png):
    """A table legitimately repeats pipes, dashes and units."""
    rec = []
    client = make_client(seq_responder(['{"markdown": "| a |"}']), recorder=rec)

    V.call_vision(client, "sys", "user", png)

    assert "repetition_penalty" not in rec[0].get("extra_body", {})
