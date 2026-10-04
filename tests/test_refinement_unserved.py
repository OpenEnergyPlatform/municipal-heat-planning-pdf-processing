"""A window the model server did not serve is not a refined window.

A failed window keeps its original text. That is right for a window the model
could not do anything with, and it was also what happened to a window whose
request never got an answer: the server gone, a timeout, a 429, a 5xx. The
document was written as refined, the next run read the file as done and asked
nothing, and a run in which every single window failed exited 0.

So: the real `run_refine` and the real window loop, with only the request
stubbed.
"""
import json
import types

import pytest

from docpipe.chunking import merge as M
from docpipe.refinement import config as C
from docpipe.refinement import pipeline as RP
from docpipe.refinement import refine as R
from docpipe.refinement import split

TITLES = ["A", "B", "C"]
CUTS: list = []     # one entry per time the sections were cut


class Status(Exception):
    def __init__(self, status):
        super().__init__(f"HTTP {status}")
        self.status_code = status


@pytest.fixture
def doc(tmp_path, monkeypatch):
    """A document of three sections, one per window, nothing to split."""
    directory = tmp_path / "plan"
    (directory / "results").mkdir(parents=True)
    _write_input(directory, TITLES)
    monkeypatch.setattr(R, "WINDOW_SIZE", 1)
    monkeypatch.setattr(R, "_make_splitter", lambda client: None)
    CUTS.clear()
    monkeypatch.setattr(R, "split_oversized",
                        lambda sections, ask=None: CUTS.append(1) or sections)
    return directory


def _sections(titles):
    """As the structure stage writes them: a table carries the text it was
    read from, which the pass strips before anything else."""
    return [{"title": t, "content": f"text of {t.lower()}",
             "tables": [{"id": f"tbl_{t}", "caption": "",
                         "source_text": f"raw {t}"}]} for t in titles]


def _write_input(directory, titles):
    (directory / "results" / "sections.json").write_text(
        json.dumps({"sections": _sections(titles)}), encoding="utf-8")


def _final(directory):
    return directory / "results" / "sections_refined.json"


def _partial(directory):
    return directory / "results" / "sections_refined.partial.json"


def _report_path(directory):
    return directory / "results" / "refinement_report.json"


def _server(monkeypatch, outcome=None):
    """Stub the request. `outcome(title)` is R.NOT_SERVED, None or missing
    (the window is refined). Returns the titles asked for, in order."""
    asked: list = []

    def call(window, client=None, prev_ctx=None):
        title = window[0]["title"]
        asked.append(title)
        result = outcome(title) if outcome else "refine"
        if result is R.NOT_SERVED or result is None:
            return result
        return [dict(section, content=section["content"].upper(),
                     _action="keep") for section in window]

    monkeypatch.setattr(R, "_call_llm", call)
    return asked


def _lose(*titles):
    return lambda title: R.NOT_SERVED if title in titles else "refine"


def _contents(directory):
    return [s["content"] for s in json.loads(
        _final(directory).read_text(encoding="utf-8"))["sections"]]


# ---------------------------------------------------------------------------
# What a window's request ended on
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("failure", [RuntimeError("down"), Status(429),
                                     Status(500), Status(503)])
def test_a_window_nobody_answered_is_not_served(make_client, seq_responder,
                                                failure):
    record: list = []
    client = make_client(seq_responder([failure]), recorder=record)
    assert R._call_llm([{"t": 1}], client) is R.NOT_SERVED
    assert len(record) == R.MAX_RETRIES


def test_the_last_attempt_decides(make_client, seq_responder):
    """A 503 and then replies nobody can read: the server did serve it, and
    the model gave nothing usable. That window keeps its text."""
    client = make_client(seq_responder([Status(503), "garbage"]))
    assert R._call_llm([{"t": 1}], client) is None
    client = make_client(seq_responder(["garbage", Status(503)]))
    assert R._call_llm([{"t": 1}], client) is R.NOT_SERVED


def test_a_reply_that_breaks_on_reading_was_served(make_client):
    """An error raised after the reply arrived is the reply's. Counted as
    the server's, a model that answers with no choice at all would keep its
    document unfinished for ever."""
    client = make_client(
        lambda kwargs: types.SimpleNamespace(choices=[], usage=None))
    assert R._call_llm([{"t": 1}], client) is None


def test_a_refused_window_is_the_requests_fault(make_client, seq_responder):
    client = make_client(seq_responder([Status(400)]))
    assert R._call_llm([{"t": 1}], client) is None


@pytest.mark.parametrize("name,value", [("LLM_TEMPERATURE", "0,1"),
                                        ("LLM_MAX_TOKENS", "8k")])
def test_a_setting_nobody_can_read_is_not_an_outage(monkeypatch, make_client,
                                                    name, value):
    """Read inside the request's own try it was retried four times and
    called a server that did not answer, for every window of every
    document."""
    monkeypatch.setenv(name, value)
    record: list = []
    client = make_client(lambda kwargs: pytest.fail("asked"), recorder=record)
    with pytest.raises(ValueError):
        R._call_llm([{"t": 1}], client)
    assert record == []


def test_a_window_is_asked_with_the_refine_prompt_and_its_sampling(
        make_client, seq_responder):
    record: list = []
    client = make_client(seq_responder(['{"sections": []}']), recorder=record)
    R._call_llm([{"t": 1}], client)
    prompt = C.refine_prompt()
    assert prompt.id == C.PROMPT_IDS[0]
    assert record[0]["messages"][0] == {"role": "system",
                                        "content": prompt.text}
    assert record[0]["temperature"] == float(prompt.meta["temperature"])
    assert record[0]["max_tokens"] >= int(prompt.meta["max_tokens"])


@pytest.mark.parametrize("corrections,prompt_id", [
    (False, "refinement/refine"), (True, "refinement/refine_corrections")])
def test_the_mode_decides_which_prompt_refines(monkeypatch, corrections,
                                               prompt_id):
    monkeypatch.setattr(C, "REFINE_RETURN_CORRECTIONS", corrections)
    # Past the per-profile cache: this asks what a fresh process would read.
    assert C.refine_prompt.__wrapped__().id == prompt_id


# ---------------------------------------------------------------------------
# The cut of an oversized section
# ---------------------------------------------------------------------------

def test_a_cut_nobody_answered_is_asked_again_and_then_not_served(
        make_client, seq_responder):
    record: list = []
    ask = R._make_splitter(make_client(seq_responder([Status(503)]),
                                       recorder=record))
    with pytest.raises(split.NotServed):
        ask("system", "user")
    assert len(record) == R.MAX_RETRIES

    ask = R._make_splitter(make_client(seq_responder(
        [RuntimeError("down"), '{"cuts": [2]}'])))
    assert ask("system", "user") == '{"cuts": [2]}'


def test_a_refused_cut_is_not_asked_twice(make_client, seq_responder):
    record: list = []
    ask = R._make_splitter(make_client(seq_responder([Status(400)]),
                                       recorder=record))
    with pytest.raises(Status):
        ask("system", "user")
    assert len(record) == 1


def test_the_cut_is_asked_with_the_split_prompts_sampling(make_client,
                                                          seq_responder):
    record: list = []
    R._make_splitter(make_client(seq_responder(["{}"]), recorder=record))(
        "system", "user")
    prompt = split.split_prompt()
    assert prompt.id == "refinement/split"
    assert record[0]["temperature"] == float(prompt.meta["temperature"])
    assert record[0]["max_tokens"] == int(prompt.meta["max_tokens"])


def test_only_a_cut_the_model_could_not_place_is_made_mechanically():
    section = {"title": "T", "content": "x"}

    def not_served(system, user):
        raise split.NotServed("down")

    def unusable(system, user):
        raise RuntimeError("no JSON")

    with pytest.raises(split.NotServed):
        split._ask_cuts(section, not_served)
    assert split._ask_cuts(section, unusable) is None


def test_a_document_whose_cut_was_not_served_is_not_refined(doc, monkeypatch,
                                                            caplog):
    """Cut mechanically because the server was down and resumed from there,
    it would keep cuts and titles the model never chose."""
    def down(sections, ask=None):
        raise split.NotServed("down")

    monkeypatch.setattr(R, "split_oversized", down)
    asked = _server(monkeypatch)
    with caplog.at_level("ERROR"):
        assert R.run_refine(doc) is None
    assert asked == [] and not _final(doc).exists()
    assert not _partial(doc).exists(), "nothing was asked, nothing to keep"
    assert "the cut of an oversized section" in caplog.text


# ---------------------------------------------------------------------------
# The document
# ---------------------------------------------------------------------------

def test_an_outage_writes_nothing_as_refined(doc, monkeypatch, caplog):
    _server(monkeypatch, lambda title: R.NOT_SERVED)
    with caplog.at_level("ERROR"):
        assert R.run_refine(doc) is None
    assert not _final(doc).exists(), (
        "three windows nobody answered, written down as a refined document")
    assert not _report_path(doc).exists(), (
        "the report describes a refined output, and there is none")
    kept = json.loads(_partial(doc).read_text(encoding="utf-8"))
    assert kept["total_windows"] == 3
    assert kept["unserved_windows"] == [1, 2, 3] and kept["windows"] == {}
    assert "did not serve 3 of 3" in caplog.text


def test_the_next_run_asks_only_for_what_was_not_served(doc, monkeypatch):
    first = _server(monkeypatch, _lose("B"))
    assert R.run_refine(doc) is None
    assert sorted(first) == TITLES
    assert not _final(doc).exists()
    kept = json.loads(_partial(doc).read_text(encoding="utf-8"))
    assert kept["unserved_windows"] == [2] and sorted(kept["windows"]) == [
        "0", "2"]

    second = _server(monkeypatch)
    out = R.run_refine(doc)
    assert second == ["B"], "the windows it already has are not asked again"
    assert len(CUTS) == 1, (
        "the model places the cuts, so a second cut is another set of "
        "windows and the replies kept would belong to none of them")
    assert [s["content"] for s in out["sections"]] == [
        "TEXT OF A", "TEXT OF B", "TEXT OF C"]
    assert _contents(doc) == ["TEXT OF A", "TEXT OF B", "TEXT OF C"]
    assert not _partial(doc).exists(), "finished, so nothing is left to resume"
    assert json.loads(_report_path(doc).read_text(encoding="utf-8")) == {
        "total_windows": 3, "failed_windows": []}

    third = _server(monkeypatch)
    assert R.run_refine(doc)["sections"] == out["sections"]
    assert third == [], "and now it is a cache hit"


def test_what_an_earlier_pass_kept_survives_a_second_outage(doc, monkeypatch):
    _server(monkeypatch, _lose("B", "C"))
    assert R.run_refine(doc) is None
    second = _server(monkeypatch, _lose("C"))
    assert R.run_refine(doc) is None
    assert sorted(second) == ["B", "C"]
    third = _server(monkeypatch)
    R.run_refine(doc)
    assert third == ["C"]
    assert _contents(doc) == ["TEXT OF A", "TEXT OF B", "TEXT OF C"]


def test_a_resumed_document_is_the_one_a_single_pass_writes(doc, monkeypatch,
                                                            tmp_path):
    whole = tmp_path / "whole"
    (whole / "results").mkdir(parents=True)
    _write_input(whole, TITLES)
    _server(monkeypatch)
    R.run_refine(whole)

    _server(monkeypatch, _lose("A", "C"))
    assert R.run_refine(doc) is None
    _server(monkeypatch)
    R.run_refine(doc)
    assert _final(doc).read_text(encoding="utf-8") == _final(whole).read_text(
        encoding="utf-8")


def test_the_windows_of_a_resume_are_cut_from_the_sections_as_split(
        doc, monkeypatch):
    """The cut makes two sections of B. What is kept belongs to the windows
    of THAT list: resumed over the three sections of the input, the reply
    kept for the second half of B would be laid over C."""
    def cut(sections, ask=None):
        CUTS.append(1)
        out = []
        for section in sections:
            if section["title"] == "B":
                out += [dict(section, title="B1", content="text of b1"),
                        dict(section, title="B2", content="text of b2")]
            else:
                out.append(section)
        return out

    monkeypatch.setattr(R, "split_oversized", cut)
    _server(monkeypatch, _lose("B2"))
    assert R.run_refine(doc) is None
    second = _server(monkeypatch)
    out = R.run_refine(doc)
    assert second == ["B2"] and len(CUTS) == 1
    assert [(s["title"], s["content"]) for s in out["sections"]] == [
        ("A", "TEXT OF A"), ("B1", "TEXT OF B1"), ("B2", "TEXT OF B2"),
        ("C", "TEXT OF C")]


def test_sections_handed_in_again_are_resumed_too(doc, monkeypatch):
    """The pass strips fields from the sections it is given. A caller that
    retries with the same object must not be told it is another input."""
    data = {"sections": _sections(TITLES)}
    _server(monkeypatch, _lose("B"))
    assert R.run_refine(doc, data=data) is None
    second = _server(monkeypatch)
    assert R.run_refine(doc, data=data) is not None
    assert second == ["B"]


def test_a_window_the_model_could_not_do_is_asked_again_on_a_resume(
        doc, monkeypatch):
    """It has no reply to keep, and the run is asking anyway."""
    _server(monkeypatch, lambda title: {"A": None, "B": R.NOT_SERVED}.get(
        title, "refine"))
    assert R.run_refine(doc) is None
    second = _server(monkeypatch, lambda title: None if title == "A"
                     else "refine")
    R.run_refine(doc)
    assert sorted(second) == ["A", "B"]
    assert _contents(doc) == ["text of a", "TEXT OF B", "TEXT OF C"]
    report = json.loads(_report_path(doc).read_text(encoding="utf-8"))
    assert [f["window"] for f in report["failed_windows"]] == [1], (
        "a window the model could not do keeps its text, as it always did")


def test_a_forced_pass_that_is_not_served_keeps_the_old_output(doc,
                                                               monkeypatch):
    _final(doc).write_text(json.dumps(
        {"sections": [{"title": "old", "content": "old"}]}), encoding="utf-8")
    earlier = json.dumps({"total_windows": 1, "failed_windows": []})
    _report_path(doc).write_text(earlier, encoding="utf-8")
    _server(monkeypatch, _lose("C"))
    assert R.run_refine(doc, force=True) is None
    assert _contents(doc) == ["old"]
    assert _report_path(doc).read_text(encoding="utf-8") == earlier, (
        "the report still describes the output that is still there")

    # Not forced: there is an unfinished pass, and it is finished first.
    second = _server(monkeypatch)
    R.run_refine(doc)
    assert second == ["C"]
    assert _contents(doc) == ["TEXT OF A", "TEXT OF B", "TEXT OF C"]


def test_an_unfinished_pass_over_another_input_is_not_resumed(doc,
                                                              monkeypatch):
    _server(monkeypatch, _lose("B"))
    assert R.run_refine(doc) is None
    _write_input(doc, ["A", "B", "D"])

    second = _server(monkeypatch)
    R.run_refine(doc)
    assert sorted(second) == ["A", "B", "D"], "everything is asked again"
    assert _contents(doc) == ["TEXT OF A", "TEXT OF B", "TEXT OF D"]
    assert not _partial(doc).exists()


def test_an_unfinished_pass_asked_with_another_prompt_is_not_resumed(
        doc, monkeypatch):
    """Half a document refined under one prompt and half under another is
    what the prompt hashes beside the output exist to rule out."""
    monkeypatch.setattr(R.prompts, "versions", lambda ids: {"p": "v1"})
    _server(monkeypatch, _lose("B"))
    assert R.run_refine(doc) is None
    monkeypatch.setattr(R.prompts, "versions", lambda ids: {"p": "v2"})
    second = _server(monkeypatch)
    R.run_refine(doc)
    assert sorted(second) == TITLES


def test_an_unfinished_pass_asked_of_another_model_is_not_resumed(
        doc, monkeypatch):
    _server(monkeypatch, _lose("B"))
    assert R.run_refine(doc) is None
    monkeypatch.setattr(R, "LLM_MODEL", "another/model")
    second = _server(monkeypatch)
    R.run_refine(doc)
    assert sorted(second) == TITLES


def test_an_unfinished_pass_with_another_window_size_is_not_resumed(
        doc, monkeypatch):
    _server(monkeypatch, _lose("B"))
    assert R.run_refine(doc) is None
    monkeypatch.setattr(R, "WINDOW_SIZE", 3)
    second = _server(monkeypatch)
    R.run_refine(doc)
    assert second == ["A"], "one window of three, asked whole"


def test_a_stale_unfinished_pass_does_not_undo_a_cache_hit(doc, monkeypatch):
    _server(monkeypatch, lambda title: R.NOT_SERVED)
    assert R.run_refine(doc) is None
    _final(doc).write_text(json.dumps(
        {"sections": [{"title": "old", "content": "old"}]}), encoding="utf-8")
    _write_input(doc, ["X"])
    asked = _server(monkeypatch)
    assert R.run_refine(doc)["sections"][0]["content"] == "old"
    assert asked == [] and not _partial(doc).exists()


@pytest.mark.parametrize("garbage", [
    "{ not json", "[1, 2]", '{"sections": []}', '{"windows": {}}'])
def test_a_file_that_is_no_unfinished_pass_is_not_resumed(doc, monkeypatch,
                                                          garbage):
    _partial(doc).write_text(garbage, encoding="utf-8")
    asked = _server(monkeypatch)
    assert R.run_refine(doc) is not None
    assert sorted(asked) == TITLES
    assert _contents(doc) == ["TEXT OF A", "TEXT OF B", "TEXT OF C"]


def test_what_was_kept_is_not_thrown_away_over_an_output_that_was_not_written(
        doc, monkeypatch):
    """The writer used to swallow its own failure. The pass then called the
    output written, deleted what it had kept and reported a success with no
    file behind it."""
    _server(monkeypatch, _lose("B"))
    assert R.run_refine(doc) is None
    _server(monkeypatch)
    real = C.os.replace

    def full_disk(source, target):
        if str(target).endswith("sections_refined.json"):
            raise OSError("no space left on device")
        return real(source, target)

    monkeypatch.setattr(C.os, "replace", full_disk)
    with pytest.raises(OSError):
        R.run_refine(doc)
    assert _partial(doc).exists() and not _final(doc).exists()
    assert not list((doc / "results").glob("*.tmp")), "and no half file"


def test_the_real_window_loop_resumes_through_the_real_request(
        doc, monkeypatch, make_client, seq_responder):
    """Nothing stubbed but the client: the request, its classification, the
    loop, the file and the resume."""
    import openai
    reply = json.dumps({"sections": [
        {"title": "T", "content": "refined", "_action": "keep"}]})
    record: list = []
    monkeypatch.setattr(openai, "OpenAI", lambda **kw: make_client(
        seq_responder([Status(503)]), recorder=record), raising=False)
    monkeypatch.setattr(R, "LLM_NUM_PARALLEL", 1)
    assert R.run_refine(doc) is None
    assert len(record) == 3 * R.MAX_RETRIES and not _final(doc).exists()

    record.clear()
    monkeypatch.setattr(openai, "OpenAI", lambda **kw: make_client(
        seq_responder([reply]), recorder=record), raising=False)
    assert R.run_refine(doc) is not None
    assert len(record) == 3 and _contents(doc) == ["refined"] * 3


# ---------------------------------------------------------------------------
# The run, and the stage after it
# ---------------------------------------------------------------------------

def test_a_batch_counts_an_unserved_document_as_failed(doc, monkeypatch):
    monkeypatch.setattr(RP, "DOC_PARALLEL", 1)
    _server(monkeypatch, lambda title: R.NOT_SERVED)
    assert RP.run_batch(doc.parent) == {"plan": False}
    assert not (doc / "results" / ".prompt_versions.json").exists(), (
        "nothing was refined, so no prompt is recorded as having refined it")

    _server(monkeypatch)
    assert RP.run_batch(doc.parent) == {"plan": True}


def test_the_merge_names_the_documents_it_leaves_out(doc, caplog):
    """An unfinished refinement leaves a document with a structure and no
    refined output, and the merge only ever looked at the ones that have
    one. It was left out of the database without a word."""
    refined = doc.parent / "refined"
    (refined / "results").mkdir(parents=True)
    _write_input(refined, ["A"])
    _final(refined).write_text(json.dumps({"sections": []}), encoding="utf-8")
    (doc.parent / "no_document").mkdir()

    with caplog.at_level("WARNING"):
        assert list(M.merge_batch(doc.parent)) == ["refined"]
    said = [r.getMessage() for r in caplog.records
            if "no refined output" in r.getMessage()]
    assert len(said) == 1 and "1 document(s)" in said[0]
    assert said[0].endswith(": plan"), said[0]


def test_a_setting_nobody_can_read_ends_the_run_before_the_first_document(
        doc, monkeypatch):
    """The prompts and what travels with them are read on first use. Left at
    that, a temperature written with a comma would surface inside the first
    request of every document instead of at the start."""
    import sys
    monkeypatch.setenv("LLM_TEMPERATURE", "0,1")
    monkeypatch.setattr(sys, "argv", ["refinement", str(doc)])
    monkeypatch.setattr(RP, "assert_serving",
                        lambda *a, **k: pytest.fail("the run went on"))
    monkeypatch.setattr(RP, "run_single",
                        lambda *a, **k: pytest.fail("a document was started"))
    with pytest.raises(ValueError):
        RP.main()
