"""A window the model could not read is a hole with its cause, and the next
plain run asks exactly the windows the report lists.

Promised: a window that ends as a hole keeps its original text in a final
output that is written all the same AND the report names it with the cause AND
the next plain run asks exactly the windows the report lists, and no others
AND the run's exit code does not move, while the run says what it left unread
in the units each number counts AND a section whose cut the model did not place
is named with its cause and is not cut again by a resume.

The real `run_refine` and the real window loop, with only the request stubbed.
"""
import json
import logging

import pytest

from docpipe.reading import Hole
from docpipe.refinement import pipeline as RP
from docpipe.refinement import refine as R
from docpipe.refinement import split

TITLES = ["A", "B", "C"]


@pytest.fixture
def doc(tmp_path, monkeypatch):
    """Three sections of one document, one per window, nothing to split."""
    directory = tmp_path / "plan"
    (directory / "results").mkdir(parents=True)
    _write_input(directory, TITLES)
    monkeypatch.setattr(R, "WINDOW_SIZE", 1)
    monkeypatch.setattr(R, "_make_splitter", lambda client: None)
    monkeypatch.setattr(RP, "DOC_PARALLEL", 1)
    CUTS.clear()
    monkeypatch.setattr(
        R, "split_oversized",
        lambda sections, ask=None, holes=None: CUTS.append(1) or sections)
    return directory


CUTS: list = []


def _write_input(directory, titles):
    (directory / "results" / "sections.json").write_text(json.dumps({
        "sections": [{"title": t, "content": f"text of {t.lower()}",
                      "tables": []} for t in titles]}), encoding="utf-8")


def _final(directory):
    return directory / "results" / "sections_refined.json"


def _partial(directory):
    return directory / "results" / "sections_refined.partial.json"


def _report(directory):
    return json.loads((directory / "results" / "refinement_report.json")
                      .read_text(encoding="utf-8"))


def _contents(directory):
    return [s["content"] for s in json.loads(
        _final(directory).read_text(encoding="utf-8"))["sections"]]


def _model(monkeypatch, holes=None):
    """Stub the request: a window whose first title is in *holes* ({title:
    outcome}) answers with that outcome, any other is refined (upper case).
    Returns the titles asked for, in order."""
    asked: list = []

    def call(window, client=None, prev_ctx=None, again=False):
        asked.append(window[0]["title"])
        outcome = (holes or {}).get(window[0]["title"])
        if outcome is not None:
            return outcome
        return [dict(section, content=section["content"].upper(),
                     _action="keep") for section in window]

    monkeypatch.setattr(R, "_call_llm", call)
    return asked


# ---------------------------------------------------------------------------
# AND 1 + 2: the output is written with the original text, the report names it
# ---------------------------------------------------------------------------

def test_a_hole_is_written_with_its_original_text_and_named_with_its_cause(
        doc, monkeypatch):
    _model(monkeypatch, {"B": Hole("cut_off", "8192 tokens")})
    result = R.run_refine(doc)
    assert result is not None
    assert _contents(doc) == ["TEXT OF A", "text of b", "TEXT OF C"], (
        "the hole keeps the text it had, the others are refined")
    report = _report(doc)
    assert report["total_windows"] == 3
    assert report["failed_windows"] == [
        {"window": 2, "reason": "cut_off", "sections": [1], "titles": ["B"]}]
    assert report["mechanical_cuts"] == []


@pytest.mark.parametrize("cause", ["cut_off", "no_object", "syntax",
                                   "outside_text", "empty", "missing_key",
                                   "refused", "error", "reasoning_only"])
def test_every_cause_a_window_can_end_with_is_in_the_report(doc, monkeypatch,
                                                            cause):
    _model(monkeypatch, {"B": Hole(cause)})
    R.run_refine(doc)
    assert [f["reason"] for f in _report(doc)["failed_windows"]] == [cause]


def test_a_window_whose_request_breaks_in_our_own_code_is_a_hole_named_error(
        doc, monkeypatch, caplog):
    """Not the server's fault and not the model's: the window keeps its text,
    the cause says it was ours, the traceback is in the log, and the other
    windows are refined all the same."""
    def ask(window, client, prev_context):
        if window[0]["title"] == "B":
            raise ValueError("our own bug")
        return [dict(s, content=s["content"].upper(), _action="keep")
                for s in window]

    monkeypatch.setattr(R, "_ask_window", ask)
    with caplog.at_level(logging.ERROR):
        assert R.run_refine(doc) is not None
    assert _contents(doc) == ["TEXT OF A", "text of b", "TEXT OF C"]
    assert _report(doc)["failed_windows"] == [
        {"window": 2, "reason": "error", "sections": [1], "titles": ["B"]}]
    assert "Traceback" in caplog.text and "our own bug" in caplog.text
    kept = json.loads(_partial(doc).read_text(encoding="utf-8"))
    assert sorted(kept["windows"]) == ["0", "2"], "and it is asked again"


def test_a_reply_with_no_section_in_it_is_a_hole_named_wrong_shape(
        doc, monkeypatch):
    """The two prose reasons of the report are gone: an empty list or a list
    of bare strings is a wrong shape, said at the same place, and is not asked
    again within the pass."""
    asked: list = []
    answers = {"A": None, "B": [], "C": ["junk"]}

    def call(window, client=None, prev_ctx=None, again=False):
        title = window[0]["title"]
        asked.append(title)
        return list(window) if answers[title] is None else answers[title]

    monkeypatch.setattr(R, "_call_llm", call)
    R.run_refine(doc)
    assert sorted(asked) == TITLES, "once each"
    assert [(f["window"], f["reason"]) for f in _report(doc)["failed_windows"]
            ] == [(2, "wrong_shape"), (3, "wrong_shape")]
    assert _contents(doc) == ["text of a", "text of b", "text of c"]


# ---------------------------------------------------------------------------
# AND 3: the next plain run asks exactly the windows the report lists
# ---------------------------------------------------------------------------

def test_the_next_plain_run_asks_exactly_the_windows_the_report_lists(
        doc, monkeypatch):
    _model(monkeypatch, {"B": Hole("cut_off")})
    R.run_refine(doc)
    listed = [f["window"] - 1 for f in _report(doc)["failed_windows"]]
    kept = json.loads(_partial(doc).read_text(encoding="utf-8"))
    assert sorted(kept["windows"]) == ["0", "2"], (
        "the replies of the windows that were read are kept")
    assert sorted(set(range(3)) - {int(i) for i in kept["windows"]}) == listed

    again = _model(monkeypatch)
    out = R.run_refine(doc)
    assert again == ["B"], "only the window the report listed, no other"
    assert len(CUTS) == 1, "the sections are not cut again: the replies kept "\
        "belong to the windows of the first cut"
    assert [s["content"] for s in out["sections"]] == [
        "TEXT OF A", "TEXT OF B", "TEXT OF C"]
    assert _contents(doc) == ["TEXT OF A", "TEXT OF B", "TEXT OF C"]
    assert not _partial(doc).exists(), "nothing is left to ask"
    assert _report(doc)["failed_windows"] == []

    third = _model(monkeypatch)
    R.run_refine(doc)
    assert third == [], "and now it is a cache hit"


def _merging_model(monkeypatch, hole_titles=()):
    """A model that merges B (which carries a table) into A, as a window of
    two, and refines the rest; a window whose first title is in *hole_titles*
    is a hole. The replies are what a model sends: no segments, no pages."""
    asked: list = []
    table = {"id": "p1_tbl0", "path": "images/p1_tbl0.png", "page_number": 1}

    def call(window, client=None, prev_ctx=None, again=False):
        titles = tuple(s["title"] for s in window)
        asked.append(titles)
        if titles[0] in hole_titles:
            return Hole("cut_off")
        if titles == ("A", "B"):
            return [{"title": "A", "content": "text of a", "tables": [],
                     "figures": [], "_action": "keep"},
                    {"title": "B", "content": "text of b [p1_tbl0]",
                     "tables": [dict(table)], "figures": [],
                     "_action": "merge_into_previous"}]
        return [{"title": s["title"], "content": s["content"].upper(),
                 "tables": [], "figures": [], "_action": "keep"}
                for s in window]

    monkeypatch.setattr(R, "_call_llm", call)
    return asked


def _write_media_input(directory):
    page = [{"kind": "text", "text": "text of a", "page": 1}]
    sections = [
        {"title": "A", "content": "text of a", "page_number": 1,
         "tables": [], "figures": [], "segments": page},
        {"title": "B", "content": "text of b [p1_tbl0]", "page_number": 1,
         "tables": [{"id": "p1_tbl0", "path": "images/p1_tbl0.png",
                     "page_number": 1}], "figures": [],
         "segments": [{"kind": "text", "text": "text of b", "page": 1},
                      {"kind": "table", "ref": "p1_tbl0", "page": 1}]},
        {"title": "C", "content": "text of c", "page_number": 2,
         "tables": [], "figures": [],
         "segments": [{"kind": "text", "text": "text of c", "page": 2}]},
        {"title": "D", "content": "text of d", "page_number": 2,
         "tables": [], "figures": [],
         "segments": [{"kind": "text", "text": "text of d", "page": 2}]}]
    (directory / "results" / "sections.json").write_text(
        json.dumps({"sections": sections}), encoding="utf-8")


def test_a_resume_writes_what_a_single_pass_writes(doc, monkeypatch):
    """The window that was read is kept as the model sent it. Its merge into
    the section before extended that section's own list of tables, and a
    resume that kept the list as the merge left it would merge the table a
    second time: two copies of it in the section."""
    monkeypatch.setattr(R, "WINDOW_SIZE", 2)
    _write_media_input(doc)
    _merging_model(monkeypatch, hole_titles=("C",))
    R.run_refine(doc)
    assert [(f["window"], f["reason"]) for f in _report(doc)["failed_windows"]
            ] == [(2, "cut_off")]
    kept = json.loads(_partial(doc).read_text(encoding="utf-8"))
    assert sorted(kept["windows"]) == ["0"]
    assert kept["windows"]["0"][0]["tables"] == [], (
        "what was kept is what was read: A's reply carried no table")
    assert "segments" not in kept["windows"]["0"][0]
    again = _merging_model(monkeypatch)
    resumed = R.run_refine(doc)
    assert again == [("C", "D")], "only the window the report lists"

    clean = doc.parent / "clean"
    (clean / "results").mkdir(parents=True)
    _write_media_input(clean)
    _merging_model(monkeypatch)
    single = R.run_refine(clean)
    assert [s["title"] for s in resumed["sections"]] == ["A", "C", "D"]
    assert resumed == single
    merged = resumed["sections"][0]
    assert [t["id"] for t in merged["tables"]] == ["p1_tbl0"], (
        "the table is in the section once")


def test_a_window_that_stays_a_hole_is_asked_again_and_the_others_are_not(
        doc, monkeypatch):
    _model(monkeypatch, {"B": Hole("cut_off")})
    R.run_refine(doc)
    second = _model(monkeypatch, {"B": Hole("syntax")})
    R.run_refine(doc)
    assert second == ["B"]
    assert [(f["window"], f["reason"]) for f in _report(doc)["failed_windows"]
            ] == [(2, "syntax")], "the cause is this pass's"
    assert _partial(doc).exists()
    third = _model(monkeypatch)
    R.run_refine(doc)
    assert third == ["B"]
    assert _contents(doc) == ["TEXT OF A", "TEXT OF B", "TEXT OF C"]


def test_a_window_whose_list_held_no_section_is_asked_again_too(doc,
                                                                monkeypatch):
    """Its reply was a list, but nothing in it is kept: it must not be stored
    among the windows that were read."""
    monkeypatch.setattr(R, "_call_llm", lambda window, client=None,
                        prev_ctx=None, again=False: [] if window[0]["title"] == "B"
                        else list(window))
    R.run_refine(doc)
    kept = json.loads(_partial(doc).read_text(encoding="utf-8"))
    assert sorted(kept["windows"]) == ["0", "2"]
    again = _model(monkeypatch)
    R.run_refine(doc)
    assert again == ["B"]


def test_a_hole_does_not_make_the_next_run_ask_a_window_that_was_read(
        doc, monkeypatch):
    """The case built to break it: a resume that kept nothing would ask all
    three windows, as a forced run does."""
    _model(monkeypatch, {"A": Hole("syntax"), "C": Hole("syntax")})
    R.run_refine(doc)
    again = _model(monkeypatch)
    R.run_refine(doc)
    assert sorted(again) == ["A", "C"] and "B" not in again


def test_a_pass_that_is_not_served_after_a_hole_keeps_the_output_it_had(
        doc, monkeypatch):
    _model(monkeypatch, {"B": Hole("cut_off")})
    R.run_refine(doc)
    before = _final(doc).read_text(encoding="utf-8")
    _model(monkeypatch, {"B": R.NOT_SERVED})
    assert R.run_refine(doc) is None
    assert _final(doc).read_text(encoding="utf-8") == before
    after = _model(monkeypatch)
    assert R.run_refine(doc) is not None
    assert after == ["B"]


def test_a_window_asked_in_halves_lists_only_the_part_that_is_a_hole(
        doc, monkeypatch):
    """Three sections in one window; the second and the third are cut off, the
    third even with more room. The first two are refined, the third is listed
    with the index it has in the document."""
    monkeypatch.setattr(R, "WINDOW_SIZE", 3)
    asked: list = []

    def call(window, client=None, prev_ctx=None, again=False):
        titles = tuple(s["title"] for s in window)
        asked.append(titles)
        if titles in (("A", "B", "C"), ("B", "C"), ("C",)):
            return Hole("cut_off")
        return [dict(s, content=s["content"].upper(), _action="keep")
                for s in window]

    monkeypatch.setattr(R, "_call_llm", call)
    R.run_refine(doc)
    assert asked == [("A", "B", "C"), ("A",), ("B", "C"), ("B",), ("C",),
                     ("C",)]
    assert _contents(doc) == ["TEXT OF A", "TEXT OF B", "text of c"]
    assert _report(doc)["failed_windows"] == [
        {"window": 1, "reason": "cut_off", "sections": [2], "titles": ["C"]}]
    # the window is asked again as a whole: it is the window the report lists
    kept = json.loads(_partial(doc).read_text(encoding="utf-8"))
    assert kept["windows"] == {}


# ---------------------------------------------------------------------------
# AND 4: the exit code does not move, the run says what it left unread
# ---------------------------------------------------------------------------

def _batch(root, monkeypatch, caplog, argv_extra=()):
    import sys
    monkeypatch.setattr(sys, "argv", ["refinement", str(root), "--batch",
                                      *argv_extra])
    monkeypatch.setattr(RP, "assert_serving", lambda *a, **k: None)
    with caplog.at_level(logging.WARNING):
        with pytest.raises(SystemExit) as stopped:
            RP.main()
    return stopped.value.code


def test_a_run_with_a_hole_exits_as_it_did_and_says_what_it_left_unread(
        doc, monkeypatch, caplog):
    clean = doc.parent / "clean"
    (clean / "results").mkdir(parents=True)
    _write_input(clean, ["X", "Y"])
    _model(monkeypatch, {"B": Hole("cut_off"), "C": Hole("syntax")})
    code = _batch(doc.parent, monkeypatch, caplog)
    assert code == 0, "a hole is a result with a cause, not a failed command"
    said = [r.getMessage() for r in caplog.records
            if "kept their original text" in r.getMessage()
            and r.getMessage().startswith("Stage 4: 2 window(s) (2 section(s)) "
                                          "in 1 document(s)")]
    assert len(said) == 1, [r.getMessage() for r in caplog.records]
    assert "cut_off 1, syntax 1" in said[0]


def test_a_run_without_holes_says_nothing_of_them(doc, monkeypatch, caplog):
    _model(monkeypatch)
    assert _batch(doc.parent, monkeypatch, caplog) == 0
    assert not [r for r in caplog.records
                if "kept their original text" in r.getMessage()]


def test_a_request_the_server_did_not_serve_still_ends_the_run_non_zero(
        doc, monkeypatch, caplog):
    _model(monkeypatch, {"B": R.NOT_SERVED})
    assert _batch(doc.parent, monkeypatch, caplog) == 1


def test_the_summary_counts_windows_sections_and_documents():
    entries = [{"document": "a", "windows": 2, "sections": 3,
                "holes": {"cut_off": 2, "syntax": 1}, "mechanical": {}},
               {"document": "b", "windows": 1, "sections": 1,
                "holes": {"cut_off": 1}, "mechanical": {"refused": 2}},
               {"document": "c", "windows": 0, "sections": 0, "holes": {},
                "mechanical": {"syntax": 1}}]
    assert RP.summarise(entries) == (
        "Stage 4: 3 window(s) (4 section(s)) in 2 document(s) kept their "
        "original text; hole(s) by cause: cut_off 3, syntax 1; "
        "3 section(s) in 2 document(s) were cut mechanically, the model's "
        "cuts being unusable; section(s) by cause: refused 2, syntax 1")


# ---------------------------------------------------------------------------
# AND 5: a cut the model did not place
# ---------------------------------------------------------------------------

def _mechanical_cut(sections, ask=None, holes=None):
    CUTS.append(1)
    holes.append({"title": "B", "why": "syntax"})
    return sections


def test_a_cut_the_model_did_not_place_is_named_and_not_made_again(
        doc, monkeypatch):
    monkeypatch.setattr(R, "split_oversized", _mechanical_cut)
    _model(monkeypatch, {"C": Hole("cut_off")})
    R.run_refine(doc)
    assert _report(doc)["mechanical_cuts"] == [{"title": "B", "why": "syntax"}]
    kept = json.loads(_partial(doc).read_text(encoding="utf-8"))
    assert kept["mechanical_cuts"] == [{"title": "B", "why": "syntax"}]

    _model(monkeypatch)
    R.run_refine(doc)
    assert len(CUTS) == 1, "the resume does not cut again"
    assert _report(doc)["mechanical_cuts"] == [
        {"title": "B", "why": "syntax"}], (
        "and the document still says which cut was not the model's")


def test_a_pass_the_server_did_not_finish_keeps_the_cut_it_made_without_the_model(
        doc, monkeypatch):
    """The sections are cut once, by the first pass; a resume does not cut
    again and so cannot find out which cut was not the model's. A pass that
    stopped on an unserved window carries the record in the file it leaves,
    and the pass that finishes the document writes it into the report."""
    monkeypatch.setattr(R, "split_oversized", _mechanical_cut)
    _model(monkeypatch, {"C": R.NOT_SERVED})
    assert R.run_refine(doc) is None
    kept = json.loads(_partial(doc).read_text(encoding="utf-8"))
    assert kept["mechanical_cuts"] == [{"title": "B", "why": "syntax"}]
    assert not _final(doc).exists(), "nothing is written as refined"

    _model(monkeypatch)
    assert R.run_refine(doc) is not None
    assert len(CUTS) == 1, "the resume does not cut again"
    assert _report(doc)["mechanical_cuts"] == [{"title": "B", "why": "syntax"}]


def _write_oversized_input(directory):
    """One section far over the word limit, with the segments it was built
    from, and a short one after it."""
    segments = [{"page": 1, "kind": "text",
                 "text": " ".join(f"w{n}" for n in range(400))}
                for _ in range(4)]
    long = {"title": "Lang", "page_number": 1, "pages": [1], "tables": [],
            "figures": [], "segments": segments,
            "content": split.content_from_segments(segments)}
    (directory / "results" / "sections.json").write_text(json.dumps({
        "sections": [long, {"title": "B", "content": "text of b",
                            "tables": []}]}), encoding="utf-8")


def test_a_cut_the_model_did_not_place_reaches_the_report_through_the_real_cut(
        doc, monkeypatch):
    """The chain as it runs, with only the request stubbed: the window loop
    hands the report's list to `split_oversized`, which hands it to
    `split_section`. Each link is held alone by a test that stubs the next one;
    a link that dropped the list left all of them green and the report empty."""
    _write_oversized_input(doc)
    monkeypatch.setattr(R, "split_oversized", split.split_oversized)
    monkeypatch.setattr(R, "_make_splitter", lambda client: (
        lambda system, user, again=False: Hole("syntax")))
    _model(monkeypatch)
    holes: list = []
    R.run_refine(doc, holes=holes)
    assert _report(doc)["mechanical_cuts"] == [{"title": "Lang",
                                                "why": "syntax"}]
    assert holes == [{"document": "plan", "windows": 0, "sections": 0,
                      "holes": {}, "mechanical": {"syntax": 1}}]
    assert len(_contents(doc)) > 2, "the section was cut all the same"


def test_a_cut_the_model_placed_is_no_hole_through_the_real_cut(doc,
                                                                monkeypatch):
    """The case that makes the one above able to fail: an answer that was read
    is not named, whatever it says."""
    _write_oversized_input(doc)
    monkeypatch.setattr(R, "split_oversized", split.split_oversized)
    monkeypatch.setattr(R, "_make_splitter", lambda client: (
        lambda system, user, again=False: {"first_title": "Anfang", "cuts": [
            {"at": 2, "title": "Mitte"}]}))
    _model(monkeypatch)
    holes: list = []
    R.run_refine(doc, holes=holes)
    assert _report(doc)["mechanical_cuts"] == []
    assert holes == []


def test_a_partial_file_from_before_the_cuts_were_recorded_is_still_read(
        doc, monkeypatch):
    """A key an older file does not carry says: none recorded. It does not
    make the file stale or unreadable."""
    _model(monkeypatch, {"B": Hole("cut_off")})
    R.run_refine(doc)
    kept = json.loads(_partial(doc).read_text(encoding="utf-8"))
    del kept["mechanical_cuts"]
    _partial(doc).write_text(json.dumps(kept), encoding="utf-8")
    again = _model(monkeypatch)
    assert R.run_refine(doc) is not None
    assert again == ["B"]
    assert _report(doc)["mechanical_cuts"] == []


def test_the_summary_line_of_a_run_names_a_cut_made_without_the_model(
        doc, monkeypatch, caplog):
    monkeypatch.setattr(R, "split_oversized", _mechanical_cut)
    _model(monkeypatch)
    assert _batch(doc.parent, monkeypatch, caplog) == 0
    assert any("1 section(s) in 1 document(s) were cut mechanically"
               in r.getMessage() for r in caplog.records)
