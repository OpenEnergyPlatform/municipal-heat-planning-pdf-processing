"""`docpipe estimate`: what a run will cost, before it runs.

The promise, in one sentence: for each stage named it counts the work the
stage still has by that stage's own rule, AND turns it into requests and
tokens, each from a stated basis (the ledger's mean for this profile and this
model, else a count of the prompt), AND prices them where the project file
prices the model, AND it calls no model and writes nothing, AND a stage it
cannot count requests for ends the command non-zero and says why.

Each AND has its own tests below, and each of those has a case built to break
it: a document the stage would skip that must not be counted, a ledger of
another profile that must not be used, a stamp that is gone.
"""
import ast
import json
import os
import re
import sqlite3
import types
from pathlib import Path

import pytest

from docpipe import estimate, settings, store, usage
from docpipe.extraction import runner
from docpipe.profile import load_profile
from docpipe.refinement import refine as R
from tests.test_cli import _docpipe

MODEL = R.LLM_MODEL


# ---------------------------------------------------------------------------
# Fixtures and builders
# ---------------------------------------------------------------------------

@pytest.fixture
def ledger(tmp_path, monkeypatch):
    """A ledger of this test's own, and a counter that is not running."""
    path = tmp_path / "ledger" / "usage.db"
    monkeypatch.setenv("DOCPIPE_USAGE_DB", str(path))
    monkeypatch.setattr(usage, "_stage", None)
    monkeypatch.setattr(usage, "_counts", {})
    monkeypatch.setattr(usage.atexit, "register", lambda fn: None)
    return path


def _book(monkeypatch, profile, stage, model, **counts):
    """One run of `stage` under `profile` (None: none in effect) that spent
    `counts`, as the ledger keeps it."""
    monkeypatch.setattr(usage, "_stage", None)
    monkeypatch.setattr(usage, "_counts", {})
    if profile is None:
        monkeypatch.delenv("DOCPIPE_PROFILE", raising=False)
    else:
        monkeypatch.setenv("DOCPIPE_PROFILE", profile)
    usage.begin(stage)
    usage.add(model, **counts)
    usage.flush()
    monkeypatch.setattr(usage, "_stage", None)
    monkeypatch.setenv("DOCPIPE_PROFILE", "kwp")


@pytest.fixture
def project(monkeypatch):
    """Apply a project file for the length of a test, and put back what the
    settings module knew before it."""
    before = dict(os.environ)
    state = (settings._file, dict(settings._said), set(settings._set),
             settings._env_file)

    def apply(tmp_path, text):
        file = tmp_path / "docpipe.toml"
        file.write_text(text, encoding="utf-8")
        monkeypatch.setenv("DOCPIPE_CONFIG", str(file))
        settings.apply()

    yield apply
    for name in set(os.environ) - set(before):
        del os.environ[name]
    os.environ.update(before)
    (settings._file, settings._said, settings._set,
     settings._env_file) = state


def _estimate(capsys, *args):
    code = estimate.main([str(a) for a in args])
    seen = capsys.readouterr()
    return code, seen.out, seen.err


def _write(path: Path, data) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else json.dumps(data),
                    encoding="utf-8")
    return path


def _sections(n, words=20, **extra):
    return [{"title": f"S{i}",
             "content": " ".join(f"w{j}" for j in range(words)),
             "tables": [], "figures": [], **extra} for i in range(n)]


def _stage3(root, name, sections):
    return _write(root / name / "results" / "sections.json",
                  {"sections": sections})


def _snapshot(folder: Path) -> dict:
    return {str(p.relative_to(folder)): p.read_bytes()
            for p in sorted(folder.rglob("*")) if p.is_file()}


def _line(out: str, label: str) -> str:
    """The text after a label of the report, its first line."""
    for line in out.splitlines():
        if line.strip().startswith(label):
            return line.strip()[len(label):].strip()
    raise AssertionError(f"no {label!r} line in:\n{out}")


# ------------------------------------------------------------------------------
# the work each stage still has, by the stage's own rule
# ------------------------------------------------------------------------------

def _server(monkeypatch, lose=()):
    """Stage 4 with only the request stubbed, as its own tests do it.
    Returns the titles of the windows asked for."""
    asked: list = []

    def call(window, client=None, prev_ctx=None):
        asked.append(window[0]["title"])
        if window[0]["title"] in lose:      # a list a test may empty again
            return R.NOT_SERVED
        return [dict(s, _action="keep") for s in window]

    monkeypatch.setattr(R, "_call_llm", call)
    monkeypatch.setattr(R, "_make_splitter", lambda client: None)
    monkeypatch.setattr(R, "split_oversized",
                        lambda sections, ask=None: sections)
    return asked


def test_refine_counts_the_windows_the_stage_asks(tmp_path, monkeypatch,
                                                  capsys, ledger):
    monkeypatch.setattr(R, "WINDOW_SIZE", 3)
    asked = _server(monkeypatch)
    root = tmp_path / "processed"
    _stage3(root, "fresh", _sections(7))
    _stage3(root, "finished", _sections(5))
    _write(root / "finished" / "results" / "sections_refined.json",
           {"sections": []})
    (root / "no_stage3" / "results").mkdir(parents=True)
    code, out, _ = _estimate(capsys, "refine", "--processed", root)
    assert code == 0
    # 7 sections in windows of 3; the finished document and the one without
    # a stage-3 result are not work
    assert _line(out, "work") == "1 documents, 7 sections"
    assert _line(out, "requests").startswith("about 3 requests")
    # and that is what the stage asks of it
    R.run_refine(root / "fresh")
    R.run_refine(root / "finished")
    assert len(asked) == 3


def test_refine_counts_only_the_windows_an_unfinished_pass_still_lacks(
        tmp_path, monkeypatch, capsys, ledger):
    """The pass the server half served is resumed by the stage, which asks
    only for the windows that are missing; a count of the whole document
    would be three times the bill."""
    monkeypatch.setattr(R, "WINDOW_SIZE", 1)
    lost = ["S1"]
    asked = _server(monkeypatch, lose=lost)
    root = tmp_path / "processed"
    _stage3(root, "plan", _sections(3))
    assert R.run_refine(root / "plan") is None      # S1 was not served
    assert sorted(asked) == ["S0", "S1", "S2"]
    code, out, _ = _estimate(capsys, "refine", "--processed", root)
    assert _line(out, "work") == "1 documents, 3 sections"
    assert _line(out, "requests").startswith("about 1 requests")
    assert "resume an unfinished pass" in out
    # the server serves again: the next run asks exactly that window
    lost.clear()
    asked.clear()
    assert R.run_refine(root / "plan") is not None
    assert asked == ["S1"]


def test_an_unfinished_pass_of_another_input_next_to_a_refined_one_is_no_work(
        tmp_path, monkeypatch, capsys, ledger):
    """The stage returns the refined result it finds and asks nothing."""
    monkeypatch.setattr(R, "WINDOW_SIZE", 1)
    asked = _server(monkeypatch)
    root = tmp_path / "processed"
    _stage3(root, "plan", _sections(3))
    R.run_refine(root / "plan")
    asked.clear()
    _write(root / "plan" / "results" / "sections_refined.partial.json",
           {"key": "not this input", "sections": [], "windows": {}})
    code, out, _ = _estimate(capsys, "refine", "--processed", root)
    assert _line(out, "requests") == "no requests"
    R.run_refine(root / "plan")
    assert asked == []


def test_an_oversized_section_costs_a_request_to_cut(tmp_path, monkeypatch,
                                                     capsys, ledger):
    monkeypatch.setattr(R, "WINDOW_SIZE", 3)
    root = tmp_path / "processed"
    _stage3(root, "plan", _sections(3, words=10)
            + _sections(1, words=1500))
    code, out, _ = _estimate(capsys, "refine", "--processed", root)
    # 4 sections: two windows, and one cut of the long one
    assert _line(out, "requests").startswith("about 3 requests")
    assert "1 cuts of an oversized section" in out


def _visual_doc(root, name="plan"):
    """A document of one section: tables t0 (described), t1, t2 (no image)
    and figures f0 (described), f1, f2. The images that exist are files."""
    doc = root / name
    items = lambda key, ids: [{"id": i, "path": f"images/{i}.png",
                               "caption": ""} for i in ids]
    section = {"title": "T", "content": "x " * 50,
               "tables": items("tables", ["t0", "t1", "t2"]),
               "figures": items("figures", ["f0", "f1", "f2"])}
    _write(doc / "results" / "sections.json", {"sections": [section]})
    for image in ("t0", "t1", "f0", "f1", "f2"):
        _write(doc / "images" / f"{image}.png", "png")
    described = {"sections": [{"tables": [dict(section["tables"][0],
                                               markdown="| a |")],
                               "figures": [dict(section["figures"][0],
                                                description="a chart"),
                                           section["figures"][1]]}]}
    _write(doc / "results" / "visuals.json", described)
    return doc


def test_visuals_counts_what_the_stage_s_own_dry_run_counts(
        tmp_path, capsys, caplog, ledger):
    from docpipe.visuals import pipeline

    root = tmp_path / "processed"
    doc = _visual_doc(root)
    code, out, _ = _estimate(capsys, "visuals", "--processed", root)
    assert code == 0
    # t1 is still to do; t2 has no image to send; f1 and f2 are still to do
    assert _line(out, "work") == "1 documents, 1 tables, 2 figures"
    assert _line(out, "requests").startswith("about 3 requests")
    assert "1 tables and figures have no image file" in out
    # the stage's dry run reads the same of the document: it counts t2 among
    # the pending ones, as it only finds out about the image when it asks
    with caplog.at_level("INFO"):
        pipeline.run_single(doc, dry_run=True)
    found = re.search(r"Found: (\d+) tables \((\d+) cached, (\d+) pending\), "
                      r"(\d+) figures \((\d+) cached, (\d+) pending\)",
                      caplog.text)
    assert [int(n) for n in found.groups()] == [3, 1, 2, 3, 1, 2]


def test_a_table_without_an_image_is_no_request_for_the_stage_either(tmp_path):
    from docpipe.visuals import process

    doc = _visual_doc(tmp_path)
    table = {"id": "t2", "path": "images/t2.png", "caption": ""}
    called = types.SimpleNamespace()        # any use of it is an AttributeError
    stats = process.ProcessingStats()
    result = process.process_table(table, {"title": "T"}, doc, called, stats)
    assert "markdown" not in result and stats.skipped_missing == 1


def test_preprocess_counts_the_documents_without_a_stage_3_result(
        tmp_path, capsys, ledger):
    pdfs, processed = tmp_path / "pdf", tmp_path / "pdf" / "processed"
    for name in ("a", "b", "c", "d"):
        _write(pdfs / f"{name}.pdf", "%PDF")
    _stage3(processed, "c", _sections(2))                    # done
    _write(processed / "d" / "results" / "pages.json", [])   # stage 3 is not
    db = tmp_path / "corpus.db"
    with sqlite3.connect(str(db)) as conn:
        store.apply(conn)
        conn.execute("INSERT INTO Documents (filename, num_pages) "
                     "VALUES ('a.pdf', 10), ('d.pdf', 4)")
    conn.close()
    code, out, _ = _estimate(capsys, "preprocess", "--pdf-dir", pdfs,
                             "--processed", processed, "--db", db)
    assert code == 0
    # a, b and d; b is not in the database, so its pages are not known
    assert _line(out, "work") == "3 documents, 14 pages"
    assert _line(out, "requests") == "no requests"
    assert "1 of those documents are not in the database" in out
    assert "--transcribe-missing-text" in out


def test_preprocess_calls_a_document_pending_when_its_stage_misses_the_cache(
        tmp_path, capsys, caplog, ledger):
    from docpipe.preprocessing import pipeline

    pdfs, processed = tmp_path / "pdf", tmp_path / "pdf" / "processed"
    for name in ("done", "todo"):
        _write(pdfs / f"{name}.pdf", "%PDF")
        _write(processed / name / "results" / "pages.json", [])  # stages 1-2
    _stage3(processed, "done", _sections(1))
    code, out, _ = _estimate(capsys, "preprocess", "--pdf-dir", pdfs,
                             "--processed", processed)
    assert _line(out, "work").startswith("1 documents")
    # the stage's own run of each: the cache of stage 3 hits for one of them
    hits = {}
    for name in ("done", "todo"):
        caplog.clear()
        with caplog.at_level("INFO"):
            pipeline.run_single(pdfs / f"{name}.pdf", processed / name)
        hits[name] = "Stage 3: cache hit" in caplog.text
    assert hits == {"done": True, "todo": False}


def test_a_directory_that_is_not_there_is_an_error_and_not_zero_work(
        tmp_path, capsys, ledger):
    code, out, err = _estimate(capsys, "refine", "visuals", "chunk",
                               "preprocess", "--processed",
                               tmp_path / "nowhere", "--pdf-dir",
                               tmp_path / "no_pdfs")
    assert code == 1
    assert out.count("not estimated: no processed directory at") == 3
    assert "not estimated: no PDF directory at" in out
    assert "4 of 4 stage(s) could not be estimated" in err
    assert "0 documents" not in out


def test_ingest_asks_no_model_and_says_what_it_cannot_count(capsys, ledger,
                                                           tmp_path):
    code, out, _ = _estimate(capsys, "ingest")
    assert code == 0 and _line(out, "requests") == "no requests"
    assert "only `docpipe ingest` reads" in out


def _corpus_db(path: Path, documents, current=True) -> Path:
    """Documents as (id, filename, sections, tables, figures)."""
    with sqlite3.connect(str(path)) as conn:
        store.apply(conn)
        for number, name, sections, tables, figures in documents:
            conn.execute("INSERT INTO Documents (id, filename, num_pages, "
                         "is_current) VALUES (?, ?, 5, ?)",
                         (number, name, 1 if current else 0))
            for index in range(sections):
                conn.execute("INSERT INTO Sections (document, section_number, "
                             "title, content) VALUES (?, ?, 't', 'c')",
                             (number, index))
            first = conn.execute("SELECT MIN(id) FROM Sections WHERE "
                                 "document = ?", (number,)).fetchone()[0]
            for _ in range(tables):
                conn.execute("INSERT INTO Tables (section, path) "
                             "VALUES (?, 'p.png')", (first,))
            for _ in range(figures):
                conn.execute("INSERT INTO Images (section, path) "
                             "VALUES (?, 'p.png')", (first,))
    conn.close()
    return path


def _merged(doc: Path, titles):
    (doc / "results").mkdir(parents=True, exist_ok=True)
    _write(doc / "results" / "document.json", {"sections": [
        {"title": t, "content": f"text of {t}", "tables": [], "figures": []}
        for t in titles]})


def test_chunk_counts_the_inputs_that_have_no_vector_yet(tmp_path, capsys,
                                                         ledger):
    root = tmp_path / "processed"
    _merged(root / "plan", ["A", "B"])
    db = tmp_path / "corpus.db"
    _corpus_db(db, [(1, "plan.pdf", 1, 0, 0)])
    with sqlite3.connect(str(db)) as conn:
        conn.executemany(
            "INSERT INTO Embeddings (faiss_id, embedding_type, owner_kind, "
            "owner_id) VALUES (?, ?, 'section', 1)",
            [(1, "section_text"), (2, "section_title")])
    conn.close()
    code, out, _ = _estimate(capsys, "chunk", "--processed", root, "--db", db)
    assert code == 0
    # four inputs (text and title of two sections), two of them embedded
    assert _line(out, "work") == "1 documents, 2 inputs to embed"
    assert _line(out, "requests").startswith("about 2 requests")
    # and a document the database does not know has all of its inputs to do
    _merged(root / "newcomer", ["A", "B"])
    _, out, _ = _estimate(capsys, "chunk", "--processed", root, "--db", db)
    assert _line(out, "work") == "2 documents, 6 inputs to embed"


def test_what_chunk_calls_embedded_is_what_the_stage_reads_from_the_database(
        tmp_path):
    from docpipe.chunking import database

    db = tmp_path / "corpus.db"
    _corpus_db(db, [(1, "plan.pdf", 2, 1, 1)])
    with sqlite3.connect(str(db)) as conn:
        conn.executemany(
            "INSERT INTO Embeddings (faiss_id, embedding_type, owner_kind, "
            "owner_id) VALUES (?, ?, ?, ?)",
            [(1, "section_text", "section", 1), (2, "table_text", "table", 1),
             (3, "figure_text", "figure", 1), (4, "section_title", "section",
                                                 2)])
    conn.close()
    with estimate._readonly(db) as conn:
        mine = estimate._embedded(conn, "plan")
    assert mine == database.get_existing_embeddings(db, "plan")
    assert len(mine) == 4                       # not an empty set on both sides


def test_a_document_with_nothing_merged_yet_is_said_not_counted(
        tmp_path, capsys, ledger):
    root = tmp_path / "processed"
    _stage3(root, "plan", _sections(2))           # stage 3 only: no merge
    _, out, _ = _estimate(capsys, "chunk", "--processed", root, "--db",
                          tmp_path / "none.db")
    assert _line(out, "work") == "0 documents, 0 inputs to embed"
    assert "1 documents have no results/document.json yet" in out
    assert "no database yet" in out


# ---------------------------------------------------------------------------
# Extract: the stage's own rule is its stamps
# ---------------------------------------------------------------------------

@pytest.fixture
def harvest(tmp_path):
    """A corpus and a harvest directory in the states a resume meets.

    a  harvested, stamped, current: done, and the document the trace is of
    b  a file and no stamp: the stamps were deleted, so it is NOT done
    c  nothing harvested
    d  harvested under an older ontology key: done unless --force-stale
    old  a version no longer current: not offered at all
    """
    profile = load_profile("kwp")
    spec_path = Path(profile.component("extraction", "SPEC_PATH"))
    spec = runner.load_spec(spec_path)
    import hashlib
    sha = hashlib.sha256(spec_path.read_bytes()).hexdigest()
    current = runner._stamp_current(sha, runner.anchors_key(), spec)
    db = _corpus_db(tmp_path / "corpus.db", [
        (1, "a.pdf", 10, 0, 0), (2, "b.pdf", 20, 2, 1),
        (3, "c.pdf", 10, 1, 0), (4, "d.pdf", 10, 0, 0)])
    with sqlite3.connect(str(db)) as conn:
        conn.execute("INSERT INTO Documents (id, filename, num_pages, "
                     "is_current) VALUES (5, 'old.pdf', 5, 0)")
        for index in range(99):
            conn.execute("INSERT INTO Sections (document, section_number) "
                         "VALUES (5, ?)", (index,))
    conn.close()
    out = tmp_path / "out"
    for name in ("a", "b", "d", "old"):
        _write(out / f"{name}.jsonl", '{"kind": "summary"}\n')
    _write(out / "a.stamp.json", current)
    _write(out / "old.stamp.json", current)
    key = next(k for k in current if k.startswith("parameter/"))
    _write(out / "d.stamp.json", {**current, key: "an older question"})
    return types.SimpleNamespace(db=db, out=out, trace=out / "trace")


def _events(*events) -> str:
    return "\n".join(e if isinstance(e, str) else json.dumps(e)
                     for e in events) + "\n"


def _trace_of_a(harvest):
    """Ten sections, 4 rows, 6 field and one frame request that were answered."""
    rows = [{"t": "rows", "doc": 1, "prompt_tokens": 1000,
             "completion_tokens": 100}] * 4
    field = [{"t": "field", "doc": 1, "prompt_tokens": 500,
              "completion_tokens": 50}] * 6
    _write(harvest.trace / "a.trace.jsonl", _events(
        *rows, *field,
        {"t": "frame", "doc": 1, "prompt_tokens": 2000,
         "completion_tokens": 200},
        {"t": "frame", "doc": 1, "prompt_tokens": None},    # the summary
        {"t": "error", "doc": 1, "prompt_tokens": 777},     # no request
        {"t": "plan", "doc": 1, "prompt_tokens": 777},
        '{"t": "rows", "doc": 1, "prompt_'))                # a killed run


def test_extract_counts_the_documents_the_stage_would_harvest(
        harvest, capsys, ledger):
    code, out, _ = _estimate(capsys, "extract", "--db", harvest.db, "--out",
                             harvest.out)
    # b lost its stamp and c was never read: both are work. a is current,
    # d is stale and left to --force-stale, old is not current
    assert _line(out, "work") == ("2 documents, 10 pages, 30 sections, "
                                  "3 tables, 1 figures")
    assert "1 documents were harvested under an older spec" in out
    assert "--force-stale" in out


def test_without_a_harvest_directory_every_current_document_is_work(
        harvest, capsys, ledger):
    _, out, _ = _estimate(capsys, "extract", "--db", harvest.db)
    assert _line(out, "work").startswith("4 documents, 20 pages, 50 sections")
    assert "no --out" in out


def test_extract_takes_its_requests_from_the_trace_of_a_harvested_document(
        harvest, capsys, ledger):
    _trace_of_a(harvest)
    # a document that is not stamped has a trace too, and an unfinished one:
    # it must not be counted
    _write(harvest.trace / "b.trace.jsonl", _events(
        *[{"t": "rows", "doc": 2, "prompt_tokens": 9999,
           "completion_tokens": 9999}] * 500))
    code, out, _ = _estimate(capsys, "extract", "--db", harvest.db, "--out",
                             harvest.out)
    assert code == 0
    # 10 sections traced and 30 still to harvest: three times each kind
    assert _line(out, "requests").startswith("about 33 requests")
    assert "3 frame requests, 12 rows requests, 18 field requests" in out
    assert _line(out, "tokens") == ("about 27,000 tokens in, 2,700 tokens out")
    basis = _line(out, "basis")
    assert basis.startswith("measured: the trace of 1 harvested documents")
    assert "1 frame requests, 4 rows requests, 6 field requests" in basis
    # what the trace has no tokens for is not left out without saying so
    assert "search sentences" in out and "are not counted" in out


def test_extract_without_a_trace_says_so_and_ends_non_zero(
        harvest, capsys, ledger):
    for args in ([], ["--out", harvest.out]):
        code, out, err = _estimate(capsys, "extract", "--db", harvest.db,
                                   *args)
        assert code == 1
        assert "not estimated" in _line(out, "requests")
        assert "harvest a few documents" in out
        assert "extract" in err and "could not be estimated" in err
        assert "about" not in _line(out, "requests")      # no invented number


def test_nothing_to_harvest_is_no_requests_and_not_a_failure(
        harvest, capsys, ledger):
    for name in ("b", "c"):
        _write(harvest.out / f"{name}.jsonl", '{"kind": "summary"}\n')
    # b and c get a current stamp: copy a's
    for name in ("b", "c"):
        (harvest.out / f"{name}.stamp.json").write_text(
            (harvest.out / "a.stamp.json").read_text(encoding="utf-8"),
            encoding="utf-8")
    code, out, _ = _estimate(capsys, "extract", "--db", harvest.db, "--out",
                             harvest.out)
    assert code == 0 and _line(out, "requests") == "no requests"


def test_what_the_trace_module_writes_is_what_the_estimate_reads(
        tmp_path, monkeypatch):
    """The file name, the folder and the shape of an event, from the module
    that writes them to the function that counts them."""
    from docpipe.extraction import trace

    monkeypatch.setattr(trace, "ENABLED", True)
    monkeypatch.setattr(trace, "_root", None)
    monkeypatch.setattr(trace, "_files", {})
    trace.open_trace(tmp_path / estimate.TRACE_DIR, {1: "a"}.get)
    try:
        trace.event("rows", 1, prompt_tokens=100, completion_tokens=10)
        trace.event("field", 1, prompt_tokens=50, completion_tokens=5)
        trace.event("plan", 1, prompt_tokens=999)         # no request
    finally:
        trace.close()
    documents, sections, counted = estimate._trace_of(
        tmp_path, [("a", 1)], {1: 4})
    assert (documents, sections) == (1, 4)
    assert counted == {"rows": [1, 100, 10], "field": [1, 50, 5],
                       "frame": [0, 0, 0]}
    # a document with no trace file is not one the estimate learns from
    assert estimate._trace_of(tmp_path, [("b", 2)], {2: 9}) == (
        0, 0, {kind: [0, 0, 0] for kind in estimate.TRACED})


def test_the_folder_and_the_stamp_the_estimate_looks_for_are_the_runner_s():
    source = Path(runner.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    folders = {node.args[0].right.value for node in ast.walk(tree)
               if isinstance(node, ast.Call)
               and isinstance(node.func, ast.Attribute)
               and node.func.attr == "open_trace" and node.args
               and isinstance(node.args[0], ast.BinOp)
               and isinstance(node.args[0].right, ast.Constant)}
    assert estimate.TRACE_DIR in folders
    assert 'f"{name}.stamp.json"' in source


def test_the_trace_events_the_estimate_reads_are_the_ones_the_harvest_writes():
    """The literals of one end and the other: if the harvest renames an event
    or stops putting its tokens on it, the estimate counts nothing."""
    tree = ast.parse(Path(runner.__file__).read_text(encoding="utf-8"))
    carrying = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "event"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "trace"
                and node.args and isinstance(node.args[0], ast.Constant)
                and any(k.arg == "prompt_tokens" for k in node.keywords)):
            carrying.add(node.args[0].value)
    assert set(estimate.TRACED) <= carrying
    assert "error" not in estimate.TRACED and "plan" not in estimate.TRACED


def test_a_profile_without_an_extraction_spec_cannot_be_estimated(
        tmp_path, monkeypatch, capsys, ledger):
    monkeypatch.setenv("DOCPIPE_PROFILE", "default")
    code, out, err = _estimate(capsys, "extract", "--db", tmp_path / "x.db")
    assert code == 1
    assert "does not configure the extraction stage" in out
    assert "extract" in err


# ------------------------------------------------------------------------------
# the basis of the tokens
# ------------------------------------------------------------------------------

def _refine_corpus(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "WINDOW_SIZE", 3)
    root = tmp_path / "processed"
    _stage3(root, "plan", _sections(30))        # ten windows
    return root


def test_a_ledger_of_this_stage_profile_and_model_is_the_basis(
        tmp_path, monkeypatch, capsys, ledger):
    root = _refine_corpus(tmp_path, monkeypatch)
    _book(monkeypatch, "kwp", "refinement", MODEL, requests=4,
          input_tokens=4_000, output_tokens=2_000)
    code, out, _ = _estimate(capsys, "refine", "--processed", root)
    # ten windows at a thousand tokens in and five hundred out
    assert _line(out, "tokens") == "about 10,000 tokens in, 5,000 tokens out"
    basis = _line(out, "basis")
    assert basis.startswith("measured: a mean of 1,000 tokens in and 500 out")
    assert "4 requests" in basis and "profile kwp" in basis


@pytest.mark.parametrize("booked", [
    dict(profile="scenarios", model=MODEL),      # another profile's runs
    dict(profile=None, model=MODEL),             # before profiles were kept
    dict(profile="kwp", model="another-model"),  # another model's runs
], ids=["another profile", "no profile", "another model"])
def test_a_ledger_that_is_not_this_one_s_is_not_the_basis(
        tmp_path, monkeypatch, capsys, ledger, booked):
    root = _refine_corpus(tmp_path, monkeypatch)
    _book(monkeypatch, booked["profile"], "refinement", booked["model"],
          requests=4, input_tokens=4_000, output_tokens=2_000)
    _, out, _ = _estimate(capsys, "refine", "--processed", root)
    basis = _line(out, "basis")
    assert basis.startswith("counted from prompt sizes: the ledger holds no "
                            "requests of stage refinement under profile kwp")
    assert "measured:" not in out
    assert "10,000 tokens in" not in out


def test_without_a_ledger_the_prompt_is_counted_and_more_text_is_more_tokens(
        tmp_path, monkeypatch, capsys, ledger):
    monkeypatch.setattr(R, "WINDOW_SIZE", 3)
    small, big = tmp_path / "small", tmp_path / "big"
    _stage3(small, "plan", _sections(3, words=10))
    _stage3(big, "plan", _sections(3, words=100))
    figures = []
    for root in (small, big):
        _, out, _ = _estimate(capsys, "refine", "--processed", root)
        assert _line(out, "basis").startswith("counted from prompt sizes")
        tokens = _line(out, "tokens")
        figures.append([int(n.replace(",", ""))
                        for n in re.findall(r"([\d,]+) tokens (?:in|out)",
                                            tokens)])
    assert len(figures[0]) == 2                         # both counted here
    assert figures[1][0] > figures[0][0] and figures[1][1] > figures[0][1]


def test_what_a_reply_will_say_is_not_guessed_for_the_tables_and_figures(
        tmp_path, capsys, ledger):
    root = tmp_path / "processed"
    _visual_doc(root)
    _, out, _ = _estimate(capsys, "visuals", "--processed", root)
    tokens = _line(out, "tokens")
    assert "tokens in" in tokens and "tokens out" not in tokens
    assert "output tokens are not counted" in out


def test_chunk_takes_the_embedding_tokens_per_input_from_the_ledger(
        tmp_path, monkeypatch, capsys, ledger):
    from docpipe.chunking import config

    root = tmp_path / "processed"
    _merged(root / "plan", ["A", "B"])
    _book(monkeypatch, "kwp", "chunking", config.EMBEDDING_MODEL, requests=10,
          embedding_tokens=1_000)
    _, out, _ = _estimate(capsys, "chunk", "--processed", root, "--db",
                          tmp_path / "none.db")
    # four inputs at a hundred tokens
    assert _line(out, "tokens") == "about 400 tokens embedded"
    assert _line(out, "basis").startswith("measured")


# ------------------------------------------------------------------------------
# the price
# ------------------------------------------------------------------------------

def test_the_price_is_the_tokens_at_the_price_of_the_models_table(
        tmp_path, monkeypatch, capsys, ledger, project):
    root = _refine_corpus(tmp_path, monkeypatch)
    _book(monkeypatch, "kwp", "refinement", MODEL, requests=4,
          input_tokens=4_000_000, output_tokens=2_000_000,
          cached_tokens=3_000_000)
    project(tmp_path, f'[prices]\n"{MODEL}" = {{ input = 4.0, output = 20.0 }}')
    _, out, _ = _estimate(capsys, "refine", "--processed", root)
    # ten windows: 10 M in at 4.0 and 5 M out at 20.0, cached as any input
    assert _line(out, "price") == ("about 140.00 in the currency of "
                                   "[prices]")
    assert "7,500,000 of them cached" in _line(out, "tokens")
    project(tmp_path, f'[prices]\n"{MODEL}" = {{ input = 4.0, cached = 0.4, '
                      f'output = 20.0 }}')
    _, out, _ = _estimate(capsys, "refine", "--processed", root)
    # three quarters of the input is cached, at a tenth of the price: 2.5 M
    # at 4.0, 7.5 M at 0.4 and 5 M out at 20.0
    assert _line(out, "price") == ("about 113.00 in the currency of "
                                   "[prices]")


def test_a_model_the_table_does_not_price_is_said_and_not_priced(
        tmp_path, monkeypatch, capsys, ledger, project):
    root = _refine_corpus(tmp_path, monkeypatch)
    project(tmp_path, '[prices]\n"some-other-model" = { input = 4.0 }')
    _, out, _ = _estimate(capsys, "refine", "--processed", root)
    assert f"not counted: [prices] has none for {MODEL}" in _line(out, "price")


def test_without_prices_there_is_no_price_and_the_hint_says_how(
        tmp_path, monkeypatch, capsys, ledger):
    root = _refine_corpus(tmp_path, monkeypatch)
    _, out, _ = _estimate(capsys, "refine", "--processed", root)
    assert not [line for line in out.splitlines()
                if line.strip().startswith("price")]
    assert "no [prices] table in the project file" in out


def test_a_price_that_leaves_out_what_could_not_be_counted_says_so(
        tmp_path, capsys, ledger, project):
    root = tmp_path / "processed"
    _visual_doc(root)
    from docpipe.visuals import config
    project(tmp_path, f'[prices]\n"{config.VLM_MODEL}" = '
                      f'{{ input = 4.0, output = 20.0 }}')
    _, out, _ = _estimate(capsys, "visuals", "--processed", root)
    assert _line(out, "price").startswith("at least ")
    assert "left out" in _line(out, "price")


# ------------------------------------------------------------------------------
# no model, nothing written, and the command line
# ------------------------------------------------------------------------------

def test_the_estimate_calls_no_model_and_writes_nothing(
        tmp_path, monkeypatch, capsys, ledger):
    import openai

    from docpipe import providers

    def refuse(*args, **kwargs):
        raise AssertionError("the estimate asked for a model")

    monkeypatch.setattr(providers, "client", refuse)
    monkeypatch.setattr(openai, "OpenAI", refuse)
    monkeypatch.setattr(R, "WINDOW_SIZE", 3)
    root = tmp_path / "processed"
    _stage3(root, "plan", _sections(7))
    _visual_doc(root, "plan2")
    _merged(root / "plan3", ["A"])
    _book(monkeypatch, "kwp", "refinement", MODEL, requests=2,
          input_tokens=10, output_tokens=10)
    (tmp_path / "pdf").mkdir()
    before = _snapshot(tmp_path)
    code, out, _ = _estimate(capsys, "ingest", "preprocess", "refine",
                             "visuals", "chunk", "--processed", root,
                             "--pdf-dir", tmp_path / "pdf", "--db",
                             tmp_path / "none.db")
    assert code == 0 and out.count("about") >= 2
    # no stage was begun, so the ledger has not moved, and no file is new
    assert _snapshot(tmp_path) == before
    assert usage._stage is None


def test_a_stage_that_is_not_one_is_refused(capsys, ledger):
    with pytest.raises(SystemExit) as refused:
        estimate.main(["harvest"])
    assert refused.value.code == 2
    assert "unknown stage harvest" in capsys.readouterr().err


def test_the_command_runs_the_estimate_and_ends_with_its_code(tmp_path):
    (tmp_path / "pdf").mkdir()
    run = _docpipe("estimate", "ingest", "preprocess", "--profile", "kwp",
                   "--pdf-dir", str(tmp_path / "pdf"), "--processed",
                   str(tmp_path / "processed"), "--db",
                   str(tmp_path / "x.db"), cwd=tmp_path)
    assert run.returncode == 0, run.stderr
    assert "estimate for profile kwp" in run.stdout
    assert "no model was called" in run.stdout
    failed = _docpipe("estimate", "extract", "--profile", "kwp", "--db",
                      str(tmp_path / "missing.db"), cwd=tmp_path)
    assert failed.returncode == 1
    assert "no corpus database" in failed.stdout
    assert "extract" in failed.stderr and "Traceback" not in failed.stderr
    listed = _docpipe("--help", cwd=tmp_path)
    assert "  estimate " in listed.stdout
    own = _docpipe("estimate", "--help", cwd=tmp_path)
    assert own.returncode == 0 and "usage: docpipe estimate" in own.stdout
    assert "--out" in own.stdout and "[STAGE ...]" in own.stdout


# ------------------------------------------------------------------------------
# what a review found: the module's own entry point, a stage that cannot be
# imported, a ledger from before the profile, a trace with nothing in it
# ------------------------------------------------------------------------------

@pytest.mark.parametrize("flag", [["--profile", "kwp"], ["--profile=kwp"]])
def test_the_module_run_by_name_takes_the_profile_from_its_own_line(tmp_path,
                                                                    flag):
    """Without a profile in the environment, `python -m docpipe.estimate
    --profile kwp` was refused as a profile named after the stage was
    imported: the stages are imported after it, and nothing had bound it."""
    from tests.test_cli import _module

    run = _module("docpipe.estimate", *flag, "ingest", cwd=tmp_path)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "estimate for profile kwp" in run.stdout
    assert "named after the stage was imported" not in run.stderr
    # a profile that is nowhere on the line is still said in one line
    bare = _module("docpipe.estimate", "ingest", cwd=tmp_path)
    assert bare.returncode != 0
    assert "no profile" in bare.stderr and "Traceback" not in bare.stderr


def test_a_stage_this_installation_cannot_import_is_said_and_the_rest_counted(
        tmp_path, monkeypatch, capsys, ledger):
    monkeypatch.setattr(R, "WINDOW_SIZE", 3)
    root = tmp_path / "processed"
    _stage3(root, "plan", _sections(7))

    def missing_library(where):
        raise ModuleNotFoundError("No module named 'faiss'", name="faiss")

    monkeypatch.setitem(estimate.STAGE_FUNCTIONS, "chunk", missing_library)
    code, out, err = _estimate(capsys, "refine", "chunk", "--processed", root)
    assert code == 1
    assert "chunk  not estimated: this installation cannot import" in out
    assert "No module named 'faiss'" in out
    assert "1 of 2 stage(s) could not be estimated (chunk)" in err
    # the stage before it was still counted, and no traceback ends the run
    assert _line(out, "requests").startswith("about 3 requests")
    assert "Traceback" not in err


def test_a_ledger_from_before_the_profile_is_said_to_be_left_out(
        tmp_path, monkeypatch, capsys, ledger):
    root = _refine_corpus(tmp_path, monkeypatch)
    _book(monkeypatch, None, "refinement", MODEL, requests=4,
          input_tokens=4_000, output_tokens=2_000)
    _book(monkeypatch, None, "visuals", "vlm", requests=2, input_tokens=10)
    _, out, _ = _estimate(capsys, "refine", "--processed", root)
    basis = _line(out, "basis")
    assert basis.startswith("counted from prompt sizes")
    assert ("2 ledger row(s) of runs from before the profile was kept belong "
            "to no profile and are not used") in basis


def test_another_profile_s_ledger_is_not_said_to_be_from_before_profiles(
        tmp_path, monkeypatch, capsys, ledger):
    root = _refine_corpus(tmp_path, monkeypatch)
    _book(monkeypatch, "scenarios", "refinement", MODEL, requests=4,
          input_tokens=4_000, output_tokens=2_000)
    _, out, _ = _estimate(capsys, "refine", "--processed", root)
    basis = _line(out, "basis")
    assert basis.startswith("counted from prompt sizes")
    assert "belong to no profile" not in basis


def test_a_trace_with_no_answered_request_is_no_basis_for_the_harvest(
        harvest, capsys, ledger):
    """A document is stamped and its trace is there, but nothing in it is a
    request that was answered: scaled to the corpus that is zero requests
    for thirty sections still to read, and the command must not say so."""
    _write(harvest.trace / "a.trace.jsonl", _events(
        {"t": "plan", "doc": 1, "prompt_tokens": 777},
        {"t": "error", "doc": 1, "prompt_tokens": 777},
        {"t": "frame", "doc": 1, "prompt_tokens": None}))
    code, out, err = _estimate(capsys, "extract", "--db", harvest.db, "--out",
                               harvest.out)
    assert code == 1
    requests = _line(out, "requests")
    assert "not estimated" in requests and "no answered request" in requests
    assert "no requests" not in requests and "about" not in requests
    assert "extract" in err and "could not be estimated" in err


def test_the_harvest_estimate_calls_no_model_and_writes_nothing(
        harvest, monkeypatch, capsys, ledger):
    """The test of the other stages' promise did not reach the one stage that
    reads the stamps, the spec and the prompts."""
    import openai

    from docpipe import providers

    def refuse(*args, **kwargs):
        raise AssertionError("the estimate asked for a model")

    monkeypatch.setattr(providers, "client", refuse)
    monkeypatch.setattr(openai, "OpenAI", refuse)
    _trace_of_a(harvest)
    before = _snapshot(harvest.out.parent)
    code, out, _ = _estimate(capsys, "extract", "--db", harvest.db, "--out",
                             harvest.out)
    assert code == 0 and "about" in _line(out, "requests")
    assert _snapshot(harvest.out.parent) == before
    assert usage._stage is None
