"""Every stage lists the documents of a processed root the same way.

Promised: every stage lists the document directories of a processed root
through one helper that finds them at any depth, so a document that
preprocessing wrote below a subfolder is seen by the stages after it; AND for
a flat layout the directories and their order are exactly what the stages
listed before; AND two directories of one name under different subfolders are
refused with both places named, because the stages know a document by that
name.
"""
import ast
import json
import os
import sys
import types
from pathlib import Path

import pytest

from docpipe import artifacts, migrate_artifact_names
from docpipe.artifacts import (DIR_RESULTS, DOCUMENT_JSON, PAGE_TRANSCRIPTION_REPORT_JSON,
                               PAGES_JSON, SECTIONS_JSON, SECTIONS_REFINED_JSON,
                               DuplicateDocumentName, document_dirs)
from docpipe.chunking import database as DB
from docpipe.chunking import merge as M
from docpipe.preprocessing import pipeline as PP
from docpipe.refinement import pipeline as RP
from docpipe.visuals import pipeline as VP

ROOT = Path(__file__).resolve().parent.parent
MARKERS = (PAGES_JSON, SECTIONS_JSON, SECTIONS_REFINED_JSON, DOCUMENT_JSON,
           PAGE_TRANSCRIPTION_REPORT_JSON)


def make(root: Path, relative: str, *artifact_names: str) -> Path:
    """A document directory holding the named artifacts."""
    folder = root / relative
    for name in artifact_names or (SECTIONS_JSON,):
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")
    return folder


def listed_before(root: Path, marker: str) -> list:
    """What every stage wrote out for itself before there was a helper."""
    return sorted(d for d in root.iterdir()
                  if d.is_dir() and (d / marker).exists())


# -- the same list for a flat layout -----------------------------------------

@pytest.fixture
def flat(tmp_path):
    root = tmp_path / "processed"
    for name in ("Zeta", "alpha", "beta_2", "10", "9", "Ärzte", "kreis.plan"):
        make(root, name, *MARKERS)
    make(root, "only_pages", PAGES_JSON)
    make(root, "only_sections", SECTIONS_JSON)
    make(root, "only_refined", SECTIONS_REFINED_JSON)
    (root / "empty_dir").mkdir()
    (root / "results").mkdir()                  # a folder named like an artifact
    (root / "_index.json").write_text("{}", encoding="utf-8")
    (root / "notes.txt").write_text("a file, not a document", encoding="utf-8")
    return root


@pytest.mark.parametrize("marker", MARKERS)
def test_a_flat_layout_lists_what_the_stages_listed_before(flat, marker):
    got = document_dirs(flat, marker)
    assert got == listed_before(flat, marker)
    assert len(got) >= 7, "a comparison of two empty lists proves nothing"


def test_a_flat_layout_is_listed_as_the_visuals_stage_listed_it(flat):
    before = sorted(d for d in flat.iterdir() if d.is_dir()
                    and VP._resolve_input(d) is not None)
    assert document_dirs(flat, *VP.INPUT_JSONS) == before
    assert {d.name for d in before} >= {"only_sections", "only_refined", "alpha"}


def test_the_directories_keep_the_form_of_the_root_they_were_given(
        flat, monkeypatch):
    monkeypatch.chdir(flat.parent)
    relative = Path("processed")
    assert document_dirs(relative, SECTIONS_JSON) == listed_before(
        relative, SECTIONS_JSON)
    assert document_dirs(relative, SECTIONS_JSON)[0].parts[0] == "processed"


# -- any depth ---------------------------------------------------------------

@pytest.fixture
def nested(tmp_path):
    root = tmp_path / "processed"
    make(root, "top")
    make(root, "2023/kreis_a")
    make(root, "2023/north/kreis_b")
    make(root, "2024/deep/er/still/kreis_c")
    return root


def test_a_document_below_subfolders_is_listed_in_path_order(nested):
    got = document_dirs(nested, SECTIONS_JSON)
    assert [d.relative_to(nested).as_posix() for d in got] == [
        "2023/kreis_a", "2023/north/kreis_b", "2024/deep/er/still/kreis_c",
        "top"]
    assert got == sorted(got)


def test_the_order_is_the_path_order_however_the_file_system_lists(
        nested, monkeypatch):
    real = os.scandir

    class Reversed:
        def __init__(self, folder):
            self._scan = real(folder)

        def __enter__(self):
            return list(reversed(list(self._scan.__enter__())))

        def __exit__(self, *exc):
            return self._scan.__exit__(*exc)

    monkeypatch.setattr(artifacts.os, "scandir", Reversed)
    got = document_dirs(nested, SECTIONS_JSON)
    assert got == sorted(got) and len(got) == 4


def test_a_subfolder_is_not_a_document_and_a_document_is_not_searched(nested):
    # a directory holding no marker is searched, never listed; one that holds
    # a marker is listed, and what lies below it is its own business
    make(nested, "top/inner_doc")
    got = [d.relative_to(nested).as_posix()
           for d in document_dirs(nested, SECTIONS_JSON)]
    assert "2023" not in got and "top/inner_doc" not in got
    assert "top" in got


def test_a_document_the_stage_cannot_read_yet_is_not_listed_but_its_neighbours_are(
        nested):
    make(nested, "2023/not_refined_yet", SECTIONS_JSON)
    make(nested, "2023/refined", SECTIONS_REFINED_JSON, SECTIONS_JSON)
    got = {d.name for d in document_dirs(nested, SECTIONS_REFINED_JSON)}
    assert got == {"refined"}
    assert {d.name for d in document_dirs(nested, SECTIONS_JSON)} >= {
        "not_refined_yet", "refined", "kreis_a"}


def test_a_folder_or_a_document_named_like_an_artifact_is_still_found(tmp_path):
    root = tmp_path / "processed"
    make(root, "results/kreis_a")                # a subfolder named `results`
    make(root, "sub/results")                    # a document named `results`
    make(root, "images/kreis_b", DOCUMENT_JSON)
    assert [d.relative_to(root).as_posix()
            for d in document_dirs(root, SECTIONS_JSON)] == [
        "results/kreis_a", "sub/results"]
    assert [d.relative_to(root).as_posix()
            for d in document_dirs(root, DOCUMENT_JSON)] == ["images/kreis_b"]


def test_a_missing_root_is_an_error_as_it_was(tmp_path):
    with pytest.raises(FileNotFoundError):
        document_dirs(tmp_path / "nowhere", SECTIONS_JSON)
    assert document_dirs(tmp_path, SECTIONS_JSON) == []


def test_a_link_back_up_the_tree_is_searched_once(nested):
    try:
        os.symlink(nested, nested / "2023" / "loop", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("this system does not let the test make a link")
    got = [d.relative_to(nested).as_posix()
           for d in document_dirs(nested, SECTIONS_JSON, distinct=False)]
    assert got.count("top") == 1 and "2023/kreis_a" in got


# -- one name, two places ----------------------------------------------------

def test_one_name_in_two_subfolders_is_refused_and_both_places_are_named(
        tmp_path):
    root = tmp_path / "processed"
    make(root, "x/report")
    make(root, "y/z/report")
    make(root, "fine")
    with pytest.raises(DuplicateDocumentName) as refused:
        document_dirs(root, SECTIONS_JSON)
    said = str(refused.value)
    assert "report" in said and "x" in said and "y/z" in said
    assert "fine" not in said
    assert isinstance(refused.value, ValueError)
    # a caller that only reads the directories may take both
    assert len(document_dirs(root, SECTIONS_JSON, distinct=False)) == 3


def test_the_name_is_held_against_the_stage_s_own_documents_only(tmp_path):
    """The twin that this stage cannot read yet is not a document of it."""
    root = tmp_path / "processed"
    make(root, "x/report", SECTIONS_REFINED_JSON)
    make(root, "y/report", SECTIONS_JSON)
    assert len(document_dirs(root, SECTIONS_REFINED_JSON)) == 1
    with pytest.raises(DuplicateDocumentName):
        document_dirs(root, SECTIONS_JSON, SECTIONS_REFINED_JSON)


# -- every stage reaches the nested document ---------------------------------

def test_refinement_visits_a_nested_document(nested, monkeypatch):
    seen = []
    monkeypatch.setattr(RP, "DOC_PARALLEL", 1)
    monkeypatch.setattr(RP, "run_single",
                        lambda d, **kw: seen.append(d) or {"sections": []})
    results = RP.run_batch(nested)
    assert seen == document_dirs(nested, SECTIONS_JSON)
    assert results == {"kreis_a": True, "kreis_b": True, "kreis_c": True,
                       "top": True}


def test_visuals_visits_a_nested_document(nested, monkeypatch):
    seen = []
    monkeypatch.setattr(VP, "DOC_PARALLEL", 1)
    monkeypatch.setattr(VP, "run_single",
                        lambda d, **kw: seen.append(d) or {"sections": []})
    results = VP.run_batch(nested)
    assert seen == document_dirs(nested, SECTIONS_JSON)
    assert sorted(results) == ["kreis_a", "kreis_b", "kreis_c", "top"]


def test_the_merge_merges_and_names_a_nested_document(tmp_path, monkeypatch,
                                                      caplog):
    root = tmp_path / "processed"
    make(root, "2023/refined", SECTIONS_REFINED_JSON)
    make(root, "2024/raw", SECTIONS_JSON)
    merged = []
    monkeypatch.setattr(M, "merge_single",
                        lambda d, force=False: merged.append(d) or {})
    with caplog.at_level("WARNING"):
        assert M.merge_batch(root, force=True) == {"refined": True}
    assert [d.name for d in merged] == ["refined"]
    said = [r.getMessage() for r in caplog.records
            if "no refined output" in r.getMessage()]
    assert len(said) == 1 and said[0].endswith(": raw")


def test_the_database_step_reads_a_nested_document(kwp_db, tmp_path):
    db, con = kwp_db
    con.execute("INSERT INTO Documents (id, filename, num_pages) "
                "VALUES (2, 'kreis_b.pdf', 3)")
    con.commit()
    root = tmp_path / "processed"
    for where, name in (("2023/north", "kreis_b"), ("", "doc")):
        folder = make(root, f"{where}/{name}" if where else name, DOCUMENT_JSON)
        (folder / DOCUMENT_JSON).write_text(json.dumps({"sections": [
            {"title": name, "content": "text", "page_number": 1, "pages": [1],
             "segments": [], "tables": [], "figures": []}]}), encoding="utf-8")

    DB.update_database(db, root)

    got = dict(con.execute(
        "SELECT d.filename, count(s.id) FROM Documents d "
        "LEFT JOIN Sections s ON s.document = d.id GROUP BY d.id"))
    assert got == {"doc.pdf": 1, "kreis_b.pdf": 1}


class _Index:
    ntotal = 0


def test_the_embedding_step_embeds_a_nested_document_under_its_name(
        tmp_path, monkeypatch):
    from docpipe.chunking import pipeline as pl
    root = tmp_path / "processed"
    for relative in ("2023/north/kreis_b", "doc"):
        make(root, relative, DOCUMENT_JSON)
    prepared = []
    monkeypatch.setattr(pl, "build_embedding_inputs",
                        lambda merged, name, d: prepared.append((name, d)) or [])
    monkeypatch.setattr(pl, "document_id", lambda db, name: 1)
    monkeypatch.setattr(pl, "get_existing_embeddings",
                        lambda db, name, doc_id=None: set())
    monkeypatch.setattr(pl, "load_or_create_index", lambda p: (_Index(), 0))
    monkeypatch.setattr(pl, "index_ids", lambda index: set())
    monkeypatch.setattr(pl, "drop_embeddings_missing_from_index",
                        lambda db, held: None)
    monkeypatch.setattr(pl, "next_faiss_id", lambda p: 0)
    monkeypatch.setattr(pl, "load_embedder", lambda name: None)
    monkeypatch.setattr(pl, "note_embedding", lambda db, embedder: None)
    monkeypatch.setattr(pl, "create_embeddings",
                        lambda inputs, index, next_id, db, **kw: next_id)
    monkeypatch.setattr(pl, "save_index", lambda index, path: None)

    pl.run(root, tmp_path / "db.sqlite", tmp_path / "idx", step="embed")

    # by the name of the directory, and read from where the directory is
    assert sorted((name, d.relative_to(root).as_posix())
                  for name, d in prepared) == [
        ("doc", "doc"), ("kreis_b", "2023/north/kreis_b")]


def test_a_forced_run_evicts_the_vectors_of_a_nested_document(tmp_path,
                                                              monkeypatch):
    from docpipe.chunking import pipeline as pl
    root = tmp_path / "processed"
    make(root, "2023/north/kreis_b", DOCUMENT_JSON)
    asked, removed = [], []
    for name in ("merge_batch", "update_database", "enrich_page_source",
                 "enrich_caption", "create_embeddings", "save_index"):
        monkeypatch.setattr(pl, name, lambda *a, **kw: None)
    monkeypatch.setattr(pl, "get_document_faiss_ids",
                        lambda db, name: asked.append(name) or [7])
    monkeypatch.setattr(pl, "clear_embedding_ids", lambda db, name: [])
    monkeypatch.setattr(pl, "remove_ids_from_index",
                        lambda index, ids: removed.append(ids))
    monkeypatch.setattr(pl, "build_embedding_inputs", lambda *a: [])
    monkeypatch.setattr(pl, "document_id", lambda db, name: 1)
    monkeypatch.setattr(pl, "get_existing_embeddings",
                        lambda db, name, doc_id=None: set())
    monkeypatch.setattr(pl, "load_or_create_index", lambda p: (_Index(), 0))
    monkeypatch.setattr(pl, "index_ids", lambda index: set())
    monkeypatch.setattr(pl, "drop_embeddings_missing_from_index",
                        lambda db, held: None)
    monkeypatch.setattr(pl, "next_faiss_id", lambda p: 0)
    monkeypatch.setattr(pl, "load_embedder", lambda name: None)
    monkeypatch.setattr(pl, "note_embedding", lambda db, embedder: None)

    pl.run(root, tmp_path / "db.sqlite", tmp_path / "idx", force=True)

    assert asked == ["kreis_b"] and removed == [[7]]


def test_the_additive_steps_read_a_nested_document(kwp_db, tmp_path):
    db, con = kwp_db
    DB._insert_sections(1, {"sections": [
        {"title": "S", "content": "[p5_tbl0]", "page_number": 5, "pages": [5],
         "segments": [{"page": 5, "kind": "table", "ref": "p5_tbl0"}],
         "tables": [{"id": "p5_tbl0", "path": "t.png", "page_number": 5,
                     "markdown": "| a |"}],
         "figures": []}]}, con)
    con.commit()
    root = tmp_path / "processed"
    folder = make(root, "2023/doc", SECTIONS_JSON,
                  PAGE_TRANSCRIPTION_REPORT_JSON)
    (folder / PAGE_TRANSCRIPTION_REPORT_JSON).write_text(
        json.dumps({"pages_transcribed": 4}), encoding="utf-8")
    (folder / SECTIONS_JSON).write_text(json.dumps({"sections": [
        {"segments": [{"page": 5, "kind": "table", "ref": "p5_tbl0",
                       "bbox": [[5, 6, 7, 8]]}],
         "tables": [{"id": "p5_tbl0", "bbox": [[5, 6, 7, 8]]}],
         "figures": []}]}), encoding="utf-8")

    assert DB.enrich_page_source(db, root) == {
        "documents": 1, "transcribed": 1, "pages": 4}
    assert DB.enrich_bbox(db, root) == {
        "documents": 1, "segments": 1, "tables": 1, "images": 0}


def test_the_stage_3_rebuild_and_the_column_report_see_a_nested_document(
        tmp_path, monkeypatch):
    root = tmp_path / "processed"
    make(root, "2023/doc", PAGES_JSON)
    make(root, "flat", PAGES_JSON)
    monkeypatch.setattr(PP, "_load_pages_cache", lambda d: [object()])
    rebuilt = []
    monkeypatch.setattr(PP, "save_output", lambda sections, d: rebuilt.append(d))
    monkeypatch.setattr(PP, "build_sections", lambda pages, layout: [])
    assert PP.rebuild_stage3_from_cache(root) == 2
    assert sorted(d.name for d in rebuilt) == ["doc", "flat"]

    from docpipe.preprocessing import columns
    monkeypatch.setattr(columns, "count_multi_column_pages",
                        lambda pages: (1, 2))
    assert sorted(PP.report_columns(root)) == ["doc", "flat"]


def _pdfs(root, *names):
    for name in names:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"%PDF-1.4 stand-in\n")


def _layout_model(monkeypatch, load_model):
    """Stage 2 as a module that only knows how to load its model: the real
    one needs torch, and what is tested here happens before it is asked."""
    stage2 = types.ModuleType("docpipe.preprocessing.stage2_layout")
    stage2.load_model = load_model
    monkeypatch.setitem(sys.modules, "docpipe.preprocessing.stage2_layout",
                        stage2)


def test_stage_2_refuses_two_documents_of_one_name_before_the_layout_model(
        tmp_path, monkeypatch):
    """The stages after it refuse such a pair, so the one that costs the GPU
    must not be the one that runs first and finds out afterwards."""
    def model_loaded():
        raise AssertionError("the layout model was loaded for a refused pair")

    _layout_model(monkeypatch, model_loaded)
    ran = []
    monkeypatch.setattr(PP, "run_single", lambda **kw: ran.append(kw) or {})
    source = tmp_path / "pdf"
    _pdfs(source, "2023/north/report.pdf", "2024/report.pdf", "fine.pdf")

    with pytest.raises(DuplicateDocumentName) as refused:
        PP.run_folder(source, tmp_path / "out", glob="**/*.pdf")

    said = str(refused.value)
    assert "report" in said and "2023/north" in said and "2024" in said
    assert "fine" not in said
    assert ran == [] and not (tmp_path / "out" / "_index.json").exists()


def test_stage_2_still_takes_nested_documents_of_different_names(tmp_path,
                                                                 monkeypatch):
    _layout_model(monkeypatch, lambda: None)
    ran = []
    monkeypatch.setattr(PP, "run_single",
                        lambda **kw: ran.append(kw["output_dir"]) or {})
    source, out = tmp_path / "pdf", tmp_path / "out"
    _pdfs(source, "2023/north/report.pdf", "2024/other.pdf", "fine.pdf")

    results = PP.run_folder(source, out, glob="**/*.pdf")

    assert sorted(results) == [str(Path("2023/north/report.pdf")),
                               str(Path("2024/other.pdf")), "fine.pdf"]
    assert sorted(d.relative_to(out).as_posix() for d in ran) == [
        "2023/north/report", "2024/other", "fine"]


def test_the_rename_of_old_artifact_names_reaches_a_nested_document(tmp_path):
    root = tmp_path / "old"
    for where in ("flat", "2023/nested"):
        results = root / where / DIR_RESULTS
        results.mkdir(parents=True)
        (results / "structured_output.json").write_text("{}", encoding="utf-8")
    # two documents of one name: a rename does not care what they are called
    (root / "2024/nested" / DIR_RESULTS).mkdir(parents=True)
    (root / "2024/nested" / DIR_RESULTS / "output.json").write_text(
        "{}", encoding="utf-8")
    todo = migrate_artifact_names.pending(root)
    assert sorted(old.parent.parent.relative_to(root).as_posix()
                  for old, _ in todo) == ["2023/nested", "2024/nested", "flat"]


# -- no stage lists a processed root on its own ------------------------------

STAGE_FILES = ("docpipe/refinement/pipeline.py", "docpipe/visuals/pipeline.py",
               "docpipe/preprocessing/pipeline.py",
               "docpipe/chunking/pipeline.py", "docpipe/chunking/database.py",
               "docpipe/chunking/merge.py",
               "docpipe/migrate_artifact_names.py")


@pytest.mark.parametrize("path", STAGE_FILES)
def test_no_stage_lists_its_documents_by_itself(path):
    """A stage that iterates its root and keeps the directories that hold an
    artifact lists the first level only, which is what lost the nested
    documents. The input folder of preprocessing is a glob of PDFs, and not
    a listing of documents."""
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    own = [node.lineno for node in ast.walk(tree)
           if isinstance(node, ast.Attribute) and node.attr in ("iterdir", "listdir")]
    assert own == [], f"{path}:{own} lists a directory itself"


def test_the_helper_is_what_the_stages_import():
    for path in STAGE_FILES:
        text = (ROOT / path).read_text(encoding="utf-8")
        assert "document_dirs" in text, path
    assert artifacts.document_dirs is document_dirs
