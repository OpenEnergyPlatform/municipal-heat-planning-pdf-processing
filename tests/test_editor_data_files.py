"""The data files of a profile that no other tab edits have a place in the
page (owner request 2026-11-19, point A2 of the review of that day: "Daten
eines Profils ohne Platz in der Seite": the regions of the scenario profile
with their spellings and groups, the exceptions of the KWP register).

Each promise is held against a case that breaks it by construction:

1. A profile names its data files, each one there; the exceptions of the KWP
   register are read from them as they stood in its code, AND every entry of
   a kept file passes the file's own pattern and schema.
2. The Sources tab lists them and shows one with its entries in the order of
   the file, AND a file it does not name is no data file.
3. An unchanged file is written back byte for byte; a change, an added and a
   removed entry are said and written in the file's form, AND a key against
   the pattern or an entry against the schema is refused, AND a file a fetch
   writes is never written, AND one that changed on disk since the page read
   it is not overwritten.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from docpipe.editor import datafiles, server
from docpipe.profile import load_profile

REPO = Path(__file__).resolve().parents[1]
KWP = load_profile("kwp")
SCENARIOS = load_profile("scenarios")


def read(path) -> bytes:
    return Path(path).read_bytes()


# -- 1. what a profile names ------------------------------------------------------------

def test_each_profile_names_its_data_files_and_each_is_there():
    for profile in (KWP, SCENARIOS):
        named = datafiles.declared(profile)
        assert named, profile.name
        for one in named:
            assert one["path"].is_file(), one["name"]
            assert one["about"]
            if one["kept"]:
                assert one["key"] and one["value"], one["name"]
    assert {one["name"] for one in datafiles.declared(SCENARIOS)} == {
        "region_aliases.json", "regions.json", "region_names.json",
        "region_aggregates.json"}


def test_the_kwp_register_exceptions_are_read_from_their_files():
    from profiles.kwp import config
    named = {one["name"]: one["path"] for one in datafiles.declared(KWP)}
    assert config.PDF_OVERRIDES_PATH == named["pdf_overrides.json"]
    assert config.SHARED_FILE_OWNERS_PATH == named["shared_file_owners.json"]
    overrides = json.loads(read(named["pdf_overrides.json"]))
    assert config.PDF_OVERRIDES == {int(key): entry["file"]
                                    for key, entry in overrides.items()}
    # a convoy's exception keeps its municipality and why it is there
    assert overrides["1059012"]["place"] == "Borgwedel"
    assert "Haddeby" in overrides["1059012"]["why"]
    assert config.SHARED_FILE_OWNERS["waermeplan_greding_20251016.pdf"] \
        == 9576122


def test_every_entry_of_a_kept_file_passes_its_own_pattern_and_schema():
    for profile in (KWP, SCENARIOS):
        for one in datafiles.declared(profile):
            if one["kept"]:
                entries = json.loads(read(one["path"]))
                assert datafiles.problems(one, entries) == [], one["name"]


# -- 2. what the page shows -----------------------------------------------------------------

def app(profile) -> server.App:
    return server.App(profile, None, REPO)


def test_the_sources_tab_lists_and_shows_them():
    status, listed = app(KWP).call("GET", "/api/data", {}, None)
    assert status == 200
    rows = {row["name"]: row for row in listed["files"]}
    assert rows["pdf_overrides.json"]["kept"] is True
    assert rows["pdf_overrides.json"]["entries"] == len(json.loads(read(
        KWP.package_dir / "pdf_overrides.json")))
    status, shown = app(SCENARIOS).call(
        "GET", "/api/data/file", {"name": "regions.json"}, None)
    assert status == 200 and shown["kept"] is False
    assert list(shown["entries"]) == list(json.loads(read(
        SCENARIOS.package_dir / "regions.json")))
    assert shown["sha256"] == hashlib.sha256(read(
        SCENARIOS.package_dir / "regions.json")).hexdigest()
    # a file the profile does not name, its spec among them
    for name in ("extraction_spec.json", "../kwp/pdf_overrides.json"):
        status, _ = app(SCENARIOS).call("GET", "/api/data/file",
                                        {"name": name}, None)
        assert status == 404, name


# -- 3. a save ---------------------------------------------------------------------------------

DECLARED = (
    {"file": "kept.json", "kept": True, "about": "kept", "key": r"^\d{7,8}$",
     "value": {"type": "object", "required": ["file"],
               "properties": {"file": {"type": "string", "minLength": 1},
                              "place": {"type": "string"}},
               "additionalProperties": False}},
    {"file": "fetched.json", "kept": False, "about": "fetched"},
)


@pytest.fixture
def folder(tmp_path):
    # written on Windows: every line ends in CR LF
    (tmp_path / "kept.json").write_bytes((json.dumps(
        {"1051011": {"file": "b.pdf", "place": "B"},
         "1001000": {"file": "a.pdf"}}, indent=1) + "\n").replace(
             "\n", "\r\n").encode())
    (tmp_path / "fetched.json").write_text('{\n "x": 1\n}\n')
    return SimpleNamespace(package_dir=tmp_path,
                           own=lambda module, attr: DECLARED
                           if (module, attr) == ("profile", "DATA_FILES")
                           else None)


def test_an_unchanged_file_is_written_back_byte_for_byte(folder):
    shown = datafiles.detail(folder, "kept.json", read)
    report = datafiles.judge(folder, "kept.json", shown["entries"], read)
    assert report["ok"] and report["changed"] is False
    assert report["text"].encode() == read(folder.package_dir / "kept.json")


def test_a_change_is_said_and_written_in_the_files_form(folder):
    entries = datafiles.detail(folder, "kept.json", read)["entries"]
    entries["1051011"] = {"file": "c.pdf", "place": "C"}
    del entries["1001000"]
    entries["2002000"] = {"file": "d.pdf"}
    report, data, path = datafiles.save(folder, "kept.json", entries, read)
    assert (report["edited"], report["removed"], report["added"]) == (
        ["1051011"], ["1001000"], ["2002000"])
    text = data.decode()
    # the file's indent, its order (unsorted on disk), its line ends
    assert text.startswith('{\r\n "1051011"') and text.endswith("}\r\n")
    assert list(json.loads(text)) == ["1051011", "2002000"]
    assert path == folder.package_dir / "kept.json"


def test_a_key_or_an_entry_against_the_file_is_refused(folder):
    entries = datafiles.detail(folder, "kept.json", read)["entries"]
    for broken, said in (({**entries, "12x": {"file": "x.pdf"}}, "12x"),
                         ({**entries, "3003000": {"place": "no file"}},
                          "file"),
                         ({**entries, "3003000": {"file": "x", "more": 1}},
                          "more"),
                         ([], "one object")):
        report = datafiles.judge(folder, "kept.json", broken, read)
        assert not report["ok"] and said in " ".join(report["problems"])
        with pytest.raises(datafiles.Refused):
            datafiles.save(folder, "kept.json", broken, read)


def test_a_file_a_fetch_writes_is_never_written(folder):
    with pytest.raises(datafiles.Refused, match="fetch"):
        datafiles.save(folder, "fetched.json", {"x": 2}, read)
    status, said = app(SCENARIOS).call(
        "POST", "/api/data/save", {},
        {"name": "regions.json", "entries": {}, "base": None})
    assert status == 400 and "fetch" in said["error"]


def test_a_file_changed_on_disk_since_the_page_read_it_is_kept(folder):
    before = read(SCENARIOS.package_dir / "region_aliases.json")
    status, said = app(SCENARIOS).call(
        "POST", "/api/data/save", {},
        {"name": "region_aliases.json", "entries": {}, "base": "0" * 64})
    assert status == 409 and said["reason"] == "moved"
    assert read(SCENARIOS.package_dir / "region_aliases.json") == before
    # the base the page read is the file's sha256
    assert datafiles.current(folder, "kept.json", read) == hashlib.sha256(
        read(folder.package_dir / "kept.json")).hexdigest()
