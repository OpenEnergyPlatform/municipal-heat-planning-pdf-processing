"""Renaming a processed tree onto the docpipe.artifacts names."""
import pytest

from docpipe import migrate_artifact_names as m


def _doc(root, name, files):
    results = root / name / "results"
    results.mkdir(parents=True)
    for f in files:
        (results / f).write_text("{}", encoding="utf-8")
    return results


def test_a_full_document_is_renamed_end_to_end(tmp_path):
    results = _doc(tmp_path, "doc_a", m.RENAMES)

    assert m.migrate(tmp_path, apply=True) == 5

    assert sorted(p.name for p in results.iterdir()) == [
        "document.json", "pages.json", "sections.json",
        "sections_refined.json", "visuals.json"]


def test_a_dry_run_touches_nothing(tmp_path):
    results = _doc(tmp_path, "doc_a", ["output.json"])

    assert m.migrate(tmp_path) == 1

    assert (results / "output.json").exists()
    assert not (results / "document.json").exists()


def test_a_half_processed_document_keeps_both_names(tmp_path, caplog):
    """Old and new side by side means someone ran this twice; the new name
    is the real output, so neither file may be clobbered."""
    results = _doc(tmp_path, "doc_a", ["output.json", "document.json"])
    (results / "document.json").write_text('{"real": 1}', encoding="utf-8")

    with caplog.at_level("WARNING"):
        assert m.migrate(tmp_path, apply=True) == 0

    assert (results / "output.json").exists()
    assert (results / "document.json").read_text(encoding="utf-8") == '{"real": 1}'
    assert "exists already" in caplog.text


def test_a_partly_processed_document_renames_what_it_has(tmp_path):
    """Stage 4 never ran: only the first two artefacts are there."""
    results = _doc(tmp_path, "doc_a", ["pages_extracted.json", "structured_output.json"])

    assert m.migrate(tmp_path, apply=True) == 2

    assert sorted(p.name for p in results.iterdir()) == ["pages.json", "sections.json"]


def test_an_already_migrated_tree_is_a_no_op(tmp_path):
    _doc(tmp_path, "doc_a", ["pages.json", "sections.json", "document.json"])

    assert m.migrate(tmp_path, apply=True) == 0


def test_files_outside_results_are_left_alone(tmp_path):
    """images/ and the odd stray file are none of this migration's business."""
    doc = tmp_path / "doc_a"
    (doc / "images").mkdir(parents=True)
    (doc / "images" / "output.json").write_text("{}", encoding="utf-8")
    _doc(tmp_path, "doc_b", ["output.json"])

    assert m.migrate(tmp_path, apply=True) == 1

    assert (doc / "images" / "output.json").exists()
