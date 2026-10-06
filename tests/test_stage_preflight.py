"""The stages that send their reply schema as the grammar put every schema to
the server before the first document.

Promised: refinement and the visuals stage hand the preflight the schemas
their requests send, from the command and from `run` AND a server that refuses
one of them ends the run before the first document, naming the schema AND a
server that takes them all lets the run go on AND a run that asks nothing of the
model (a dry run) asks the server nothing.

The probe itself is held in test_llm_preflight.py. What is held here is that
each stage's command calls it with its own shapes: removing the `shapes`
argument from a stage left every other test green.
"""
import logging
import sys
from types import SimpleNamespace as NS

import pytest

from docpipe import llm_preflight
from docpipe.providers import base
from docpipe.refinement import pipeline as RP
from docpipe.refinement import refine as R
from docpipe.refinement import replies as refinement_replies
from docpipe.visuals import pipeline as IP
from docpipe.visuals import replies as visuals_replies


class _Status(Exception):
    def __init__(self, status_code, message="refused"):
        super().__init__(message)
        self.status_code = status_code


def _server(monkeypatch, refuses=()):
    """A server that serves the model "m" with room for any request, takes every
    request and answers 400 to the schemas named in *refuses*. Returns the names
    of the schemas it was asked, in order."""
    asked: list = []

    def answer(**kwargs):
        shape = (kwargs.get("response_format") or {}).get("json_schema") or {}
        if shape:
            asked.append(shape["name"])
        if shape.get("name") in refuses:
            raise _Status(400, f"cannot compile {shape['name']}")
        return base.reply("ok", "length")

    client = base.facade(
        answer, models=lambda: NS(data=[NS(id="m", max_model_len=10 ** 7)]))
    monkeypatch.setattr(llm_preflight.providers, "client",
                        lambda role, **kw: client)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("VLM_PROVIDER", raising=False)
    return asked


@pytest.fixture
def refinement(tmp_path, monkeypatch):
    """The refinement command over a folder, its documents stubbed out: what is
    recorded is whether a document was started."""
    started: list = []
    monkeypatch.setattr(RP, "LLM_MODEL", "m")
    monkeypatch.setattr(RP, "run_batch",
                        lambda root, **kw: started.append(root) or {})
    monkeypatch.setattr(sys, "argv", ["refinement", str(tmp_path), "--batch"])
    return started


@pytest.fixture
def visuals(tmp_path, monkeypatch):
    started: list = []
    monkeypatch.setattr(IP, "VLM_MODEL", "m")
    monkeypatch.setattr(IP, "run_batch",
                        lambda root, **kw: started.append(root) or {})
    monkeypatch.setattr(sys, "argv", ["visuals", str(tmp_path), "--batch"])
    return started


def _exit(main):
    with pytest.raises(SystemExit) as stopped:
        main()
    return stopped.value.code


# ---------------------------------------------------------------------------
# AND 1: the shapes the stage sends are the shapes it hands over
# ---------------------------------------------------------------------------

def test_the_refinement_command_hands_the_preflight_its_own_shapes(
        refinement, monkeypatch):
    seen: dict = {}
    monkeypatch.setattr(RP, "assert_serving",
                        lambda *a, **k: seen.update(kwargs=k))
    assert _exit(RP.main) == 0
    assert seen["kwargs"]["shapes"] == R.reply_shapes()
    assert set(seen["kwargs"]["shapes"]) == {"refined_sections", "section_cuts"}
    assert seen["kwargs"]["shapes"]["section_cuts"] == refinement_replies.SPLIT


def test_the_refinement_entry_point_hands_it_over_too(tmp_path, monkeypatch):
    seen: dict = {}
    monkeypatch.setattr(RP, "assert_serving",
                        lambda *a, **k: seen.update(kwargs=k))
    monkeypatch.setattr(RP, "run_batch", lambda root, **kw: {})
    RP.run(tmp_path, batch=True)
    assert seen["kwargs"]["shapes"] == R.reply_shapes()


def test_the_visuals_command_hands_the_preflight_its_own_shapes(
        visuals, monkeypatch):
    seen: dict = {}
    monkeypatch.setattr(IP, "assert_serving",
                        lambda *a, **k: seen.update(kwargs=k))
    assert _exit(IP.main) == 0
    assert seen["kwargs"]["shapes"] == {
        "table_reply": visuals_replies.TABLE[1],
        "figure_reply": visuals_replies.FIGURE[1]}
    assert seen["kwargs"]["role"] == "vlm", "the vision server is the one asked"


# ---------------------------------------------------------------------------
# AND 2 + 3: a server that refuses one ends the run, one that takes them all
# does not
# ---------------------------------------------------------------------------

def test_a_server_that_refuses_the_cut_schema_ends_refinement_before_any_document(
        refinement, monkeypatch, caplog):
    """The case built to break it: the window schema is taken, the cut schema
    is not. A command that left the shapes out is never refused."""
    asked = _server(monkeypatch, refuses={"section_cuts"})
    with caplog.at_level(logging.ERROR):
        code = _exit(RP.main)
    assert code == 1
    assert refinement == [], "no document was started"
    assert asked == ["refined_sections", "section_cuts"]
    assert "section_cuts" in caplog.text and "HTTP 400" in caplog.text


def test_a_server_that_refuses_the_figure_schema_ends_the_visuals_stage_before_any_document(
        visuals, monkeypatch, caplog):
    asked = _server(monkeypatch, refuses={"figure_reply"})
    with caplog.at_level(logging.ERROR):
        code = _exit(IP.main)
    assert code == 1
    assert visuals == [], "no document was started"
    assert asked == ["table_reply", "figure_reply"]
    assert "figure_reply" in caplog.text


def test_a_server_that_takes_every_schema_lets_refinement_go_on(
        refinement, monkeypatch):
    asked = _server(monkeypatch)
    assert _exit(RP.main) == 0
    assert asked == ["refined_sections", "section_cuts"]
    assert len(refinement) == 1


def test_a_server_that_takes_every_schema_lets_the_visuals_stage_go_on(
        visuals, monkeypatch):
    asked = _server(monkeypatch)
    assert _exit(IP.main) == 0
    assert asked == ["table_reply", "figure_reply"]
    assert len(visuals) == 1


def test_a_dry_run_asks_the_server_nothing(tmp_path, monkeypatch):
    """It reads files and counts items; a server that is down or refuses a
    schema is no reason for it to end."""
    asked = _server(monkeypatch, refuses={"table_reply", "figure_reply"})
    monkeypatch.setattr(IP, "run_batch", lambda root, **kw: {})
    monkeypatch.setattr(sys, "argv",
                        ["visuals", str(tmp_path), "--batch", "--dry-run"])
    assert _exit(IP.main) == 0
    assert asked == []
