"""What the image build installs on top of the vLLM base image.

The promise: a requirement the base image already has is skipped and the base
version stays, OpenCV counts as present whichever build of it the base has,
a full OpenCV is installed headless, and everything else is installed as
pinned. A base package the install changed anyway fails the build.
"""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def ir():
    spec = importlib.util.spec_from_file_location(
        "install_requirements", ROOT / "docker" / "install_requirements.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_package_the_base_has_is_skipped_and_keeps_the_base_version(ir):
    keep, skipped = ir.split(["torch==2.10.0", "Transformers==5.3.0",
                              "rdflib==7.6.0"],
                             {"torch": "2.11.0+cu129", "transformers": "5.12.1"})
    assert keep == ["rdflib==7.6.0"]
    assert [(n, v) for n, _, v in skipped] == [("torch", "2.11.0+cu129"),
                                               ("transformers", "5.12.1")]


def test_opencv_in_the_base_under_another_name_counts_as_present(ir):
    keep, skipped = ir.split(["opencv-python==4.13.0.92"],
                             {"opencv-python-headless": "4.11.0.86"})
    assert keep == []
    assert skipped[0][2] == "4.11.0.86"


def test_a_full_opencv_the_base_lacks_is_installed_headless(ir):
    keep, _ = ir.split(["opencv-python==4.13.0.92"], {})
    assert keep == ["opencv-python-headless==4.13.0.92"]


def test_names_are_read_from_urls_ranges_and_comments(ir):
    lines = ["# Tests.", "", "pytest>=8",
             "de_core_news_lg @ https://example.test/de_core_news_lg-3.8.0-py3-none-any.whl#sha256=ab",
             "rapidfuzz", "-r other.txt"]
    keep, skipped = ir.split(lines, {"de-core-news-lg": "3.8.0"})
    assert keep == ["pytest>=8", "rapidfuzz"]
    assert [n for n, _, _ in skipped] == ["de-core-news-lg"]


def test_a_changed_base_package_fails_the_build(ir, monkeypatch, tmp_path):
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("rdflib==7.6.0\n")
    seen = iter([{"torch": "2.11.0+cu129"},
                 {"torch": "2.10.0", "rdflib": "7.6.0"}])
    monkeypatch.setattr(ir, "installed", lambda: next(seen))
    calls = []
    monkeypatch.setattr(ir.subprocess, "run", lambda cmd, check: calls.append(cmd))
    assert ir.main([str(requirements)]) == 1
    assert "-c" in calls[0], "every base package goes in as a constraint"


def test_an_install_that_only_adds_passes(ir, monkeypatch, tmp_path):
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("rdflib==7.6.0\n")
    seen = iter([{"torch": "2.11.0+cu129"},
                 {"torch": "2.11.0+cu129", "rdflib": "7.6.0"}])
    monkeypatch.setattr(ir, "installed", lambda: next(seen))
    monkeypatch.setattr(ir, "unmet", lambda added, present: [])
    monkeypatch.setattr(ir.subprocess, "run", lambda cmd, check: None)
    assert ir.main([str(requirements)]) == 0


def test_the_freeze_is_installed_without_resolving_the_base_again(
        ir, monkeypatch, tmp_path):
    """The base's own pins need not agree with each other, so resolving the
    added packages' dependencies again can find no install at all."""
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("rdflib==7.6.0\n")
    seen = iter([{"torch": "2.13.0+cu130"},
                 {"torch": "2.13.0+cu130", "rdflib": "7.6.0"}])
    monkeypatch.setattr(ir, "installed", lambda: next(seen))
    monkeypatch.setattr(ir, "unmet", lambda added, present: [])
    calls = []
    monkeypatch.setattr(ir.subprocess, "run",
                        lambda cmd, check: calls.append(cmd))
    assert ir.main([str(requirements)]) == 0
    assert "--no-deps" in calls[0]


def _requires(table):
    def requires(name):
        if name not in table:
            raise ir_metadata().PackageNotFoundError(name)
        return table[name]
    return requires


def ir_metadata():
    from importlib import metadata
    return metadata


def test_a_dependency_the_freeze_lacks_fails_the_build(ir, monkeypatch,
                                                       tmp_path):
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("rdflib==7.6.0\n")
    seen = iter([{"torch": "2.13.0+cu130"},
                 {"torch": "2.13.0+cu130", "rdflib": "7.6.0"}])
    monkeypatch.setattr(ir, "installed", lambda: next(seen))
    monkeypatch.setattr(ir.metadata, "requires",
                        _requires({"rdflib": ["pyparsing>=3"]}))
    monkeypatch.setattr(ir.subprocess, "run", lambda cmd, check: None)
    assert ir.main([str(requirements)]) == 1


def test_only_a_dependency_that_applies_counts(ir, monkeypatch):
    monkeypatch.setattr(ir.metadata, "requires", _requires({"rdflib": [
        "pyparsing>=3",
        "html5lib; extra == 'html'",
        "pywin32; sys_platform == 'never'",
        "Isodate>=0.7"]}))
    assert ir.unmet({"rdflib"}, {"rdflib": "7.6.0", "isodate": "0.7.2"}) == [
        "rdflib needs pyparsing"]
    assert ir.unmet({"rdflib"}, {"rdflib": "7.6.0", "isodate": "0.7.2",
                                 "pyparsing": "3.2.0"}) == []


def test_the_headless_opencv_is_the_dependency_on_opencv(ir, monkeypatch):
    monkeypatch.setattr(ir.metadata, "requires", _requires({
        "layoutparser": ["opencv-python"]}))
    assert ir.unmet({"layoutparser"}, {"layoutparser": "0.3.4"}) == [
        "layoutparser needs opencv-python"]
    assert ir.unmet({"layoutparser"}, {"layoutparser": "0.3.4",
                                       "opencv-python-headless": "4.12"}) == []
