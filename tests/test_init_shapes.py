"""A project without shapes of its own can start: `docpipe init --shapes`.

Promised: `docpipe init --shapes [FILE]` writes the DRAFT of an extraction spec
into the new project's profile, from the small metadata shape the package
brings or from the user's FILE, AND the draft is no spec (the project names
none, so `docpipe extract` still stops until a spec exists), AND a file that
cannot be used stops it before anything is written, naming the file.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("rdflib")

from docpipe import cli  # noqa: E402
from docpipe.compile import cli as compiling  # noqa: E402
from docpipe.compile import draft as drafting  # noqa: E402
from docpipe.compile import shapes  # noqa: E402
from tests.test_entry_points import PROBE  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
STRIP = ("DOCPIPE_PROFILE", "DOCPIPE_PROFILE_PATH", "DOCPIPE_CONFIG",
         "DOCPIPE_DATA_ROOT", "DOCPIPE_ENV_FILE")
DRAFT = cli.DRAFT_FILE

OWN_SHAPES = """
@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix ex: <http://example.org/shapes/> .
@prefix v: <http://example.org/vocab/> .

ex:NoteShape a sh:NodeShape ; sh:targetClass v:Note ;
    sh:property [ sh:path v:subject ; sh:datatype xsd:string ;
                  sh:name "subject" ;
                  sh:description "What the note says it is about, in its words." ] .
"""


def _docpipe(*args, cwd):
    child = {k: v for k, v in os.environ.items() if k not in STRIP}
    child.update(PYTHONPATH=str(ROOT),
                 DOCPIPE_USAGE_DB=str(Path(cwd) / "usage.db"))
    return subprocess.run([sys.executable, "-c", PROBE, "docpipe", *args],
                          cwd=str(cwd), env=child, capture_output=True,
                          text=True)


def _spec_path_of(profile: Path):
    """What `SPEC_PATH` is in the profile's extraction module as written."""
    scope = {"__file__": str(profile / "extraction.py")}
    exec(compile((profile / "extraction.py").read_text(encoding="utf-8"),
                 str(profile / "extraction.py"), "exec"), scope)
    return scope["SPEC_PATH"]


@pytest.fixture
def home(tmp_path):
    folder = tmp_path / "home"
    folder.mkdir()
    return folder


# ---- the shape the package brings ----------------------------------------------

def test_the_bundled_shape_says_eight_fields_of_a_document_after_schema_org():
    found, prefixes = shapes.read([shapes.BUNDLED])
    [shape] = found
    assert shape.target_class == "https://schema.org/CreativeWork"
    assert prefixes["schema"] == "https://schema.org/"
    assert sorted(prop.name for prop in shape.properties) == [
        "abstract", "author", "date", "keywords", "language", "publisher",
        "title", "version"]
    assert all(prop.path.startswith("https://schema.org/")
               for prop in shape.properties)


def test_its_draft_lacks_only_what_the_author_alone_can_say():
    raw = compiling.draft_of(shapes.BUNDLED)
    assert len(raw["parameters"]) == 8
    assert all(parameter["value_type"] == "text" and parameter["axes"] == {}
               for parameter in raw["parameters"])
    assert {parameter["kg"]["node"] for parameter in raw["parameters"]} == {
        "metadata"}
    open_points = drafting.todo(raw)
    assert len(open_points) == 1 + 8
    assert open_points[0].startswith("graph.base:")
    assert all(".example: missing" in line for line in open_points[1:])


def test_a_field_of_the_shape_that_says_too_little_would_show_in_the_draft(
        tmp_path):
    """Built to fall: the same shape with one description cut to a word is a
    draft that lacks a description as well."""
    text = shapes.BUNDLED.read_text(encoding="utf-8")
    cut = tmp_path / "metadata.ttl"
    cut.write_text(text.replace(
        '"The title of the document as printed on its cover or its first '
        'page."', '"title"'), encoding="utf-8")
    assert text != cut.read_text(encoding="utf-8")
    open_points = drafting.todo(compiling.draft_of(cut))
    assert len(open_points) == 1 + 8 + 1
    assert any(line.startswith("metadata_title.description:")
               for line in open_points)


# ---- init --shapes ---------------------------------------------------------------

def test_init_shapes_writes_the_draft_into_the_profile(home, capsys):
    assert cli.main(["init", "demo", "--dir", str(home), "--shapes"]) == 0
    said = capsys.readouterr().out
    profile = home / "profiles" / "demo"
    raw = json.loads((profile / DRAFT).read_text(encoding="utf-8"))
    assert raw == json.loads(json.dumps(compiling.draft_of(shapes.BUNDLED)))
    assert f"wrote {profile / DRAFT}" in said
    # what the person meets: a draft, what it lacks, and where a spec goes
    assert "8 parameter(s), 9 point(s) still open" in said
    assert "It is not a spec" in said and "docpipe compile check" in said
    assert "extraction_spec.json" in said
    assert (home / "docpipe.toml").is_file()


def test_the_draft_is_not_a_spec_and_the_project_names_none(home, capsys):
    cli.main(["init", "demo", "--dir", str(home), "--shapes"])
    capsys.readouterr()
    profile = home / "profiles" / "demo"
    assert not (profile / "extraction_spec.json").exists()
    assert _spec_path_of(profile) is None
    draft_file = profile / DRAFT
    assert compiling.main(["check", str(draft_file)]) == 1
    assert "9 point(s) open" in capsys.readouterr().out
    # built to fall: the spec beside the module is what it names, and the
    # draft is not that
    (profile / "extraction_spec.json").write_text("{}", encoding="utf-8")
    assert _spec_path_of(profile) == profile / "extraction_spec.json"


def test_extract_stops_under_such_a_project_until_it_has_a_spec(home):
    assert _docpipe("init", "demo", "--shapes", cwd=home).returncode == 0
    run = _docpipe("--profile", "demo", "extract", "a.db", "a.bin", "out",
                   cwd=home)
    assert run.returncode == 2
    assert "profile 'demo' does not configure the extraction stage" \
        in run.stderr


def test_init_without_shapes_writes_no_draft(home):
    assert cli.main(["init", "demo", "--dir", str(home)]) == 0
    assert sorted(path.name for path in (home / "profiles" / "demo").iterdir()
                  ) == ["__init__.py", "extraction.py", "profile.py"]


def test_init_shapes_takes_a_file_of_the_users_in_place_of_the_bundled_one(
        home, tmp_path):
    own = tmp_path / "notes.shacl.ttl"
    own.write_text(OWN_SHAPES, encoding="utf-8")
    assert cli.main(["init", "demo", "--dir", str(home), "--shapes",
                     str(own)]) == 0
    raw = json.loads((home / "profiles" / "demo" / DRAFT).read_text(
        encoding="utf-8"))
    assert [parameter["uri"] for parameter in raw["parameters"]] == [
        "note_subject"]
    assert "notes.shacl.ttl" in raw["_comment"]
    assert "metadata" not in json.dumps(raw)


# ---- a file that cannot be used ------------------------------------------------

def _garbage(folder):
    path = folder / "garbage.ttl"
    path.write_bytes(b"\x00\x01\xff\xfe not turtle")
    return path


def _not_turtle(folder):
    path = folder / "bad.ttl"
    path.write_text("this is not turtle at all .", encoding="utf-8")
    return path


def _no_shape(folder):
    path = folder / "empty.ttl"
    path.write_text("@prefix v: <http://example.org/> . v:a v:b v:c .\n",
                    encoding="utf-8")
    return path


def _a_folder(folder):
    path = folder / "folder.ttl"
    path.mkdir()
    return path


def _missing(folder):
    return folder / "nowhere.ttl"


def _cut_off_n3(folder):
    """The N3 parser of rdflib ends on an IndexError here, not on one of its
    own errors."""
    path = folder / "cut.n3"
    path.write_text("@prefix : <http://example.org/> . :a :b", encoding="utf-8")
    return path


@pytest.mark.parametrize("make, why", [
    (_missing, "is not a file"),
    (_a_folder, "is not a file"),
    (_garbage, "cannot be read as SHACL shapes"),
    (_not_turtle, "cannot be read as SHACL shapes"),
    (_cut_off_n3, "cannot be read as SHACL shapes"),
    (_no_shape, "holds no shape with a target class and a property"),
])
def test_a_file_that_cannot_be_used_stops_init_before_anything_is_written(
        home, tmp_path, make, why):
    bad = make(tmp_path)
    with pytest.raises(SystemExit) as stopped:
        cli.main(["init", "demo", "--dir", str(home), "--shapes", str(bad)])
    message = str(stopped.value.code)
    assert str(bad) in message and why in message
    assert message.endswith("; nothing was written")
    assert list(home.iterdir()) == []


def test_whatever_the_reader_fails_with_is_the_files_and_is_named(
        home, tmp_path, monkeypatch):
    """Built to fall: an error of a kind nobody listed is a traceback and no
    message that names the file."""
    own = tmp_path / "notes.shacl.ttl"
    own.write_text(OWN_SHAPES, encoding="utf-8")

    def broken(paths):
        raise RuntimeError("the parser broke")
    monkeypatch.setattr(shapes, "read", broken)
    with pytest.raises(SystemExit) as stopped:
        cli.main(["init", "demo", "--dir", str(home), "--shapes", str(own)])
    message = str(stopped.value.code)
    assert str(own) in message and "RuntimeError: the parser broke" in message
    assert message.endswith("; nothing was written")
    assert list(home.iterdir()) == []


def test_an_empty_file_name_is_no_request_for_the_bundled_shape(home):
    """Built to fall: `--shapes "$UNSET"` is an empty name, and it must not
    write the draft of the shape the package brings in its place."""
    with pytest.raises(SystemExit) as stopped:
        cli.main(["init", "demo", "--dir", str(home), "--shapes", ""])
    assert "empty file name" in str(stopped.value.code)
    assert str(stopped.value.code).endswith("nothing was written")
    assert list(home.iterdir()) == []
    # the option without a name is the bundled shape
    assert cli.main(["init", "demo", "--dir", str(home), "--shapes"]) == 0
    assert (home / "profiles" / "demo" / DRAFT).is_file()


def test_the_same_through_the_command(home, tmp_path):
    run = _docpipe("init", "demo", "--shapes", str(_garbage(tmp_path)),
                   cwd=home)
    assert run.returncode == 1
    assert "garbage.ttl cannot be read as SHACL shapes" in run.stderr
    assert not (home / "docpipe.toml").exists()
    assert not (home / "profiles").exists() and not (home / "data").exists()


def test_without_rdflib_init_shapes_names_the_extra_and_writes_nothing(
        home, monkeypatch):
    monkeypatch.setitem(sys.modules, "rdflib", None)    # as if not installed
    monkeypatch.setitem(sys.modules, "rdflib.exceptions", None)
    with pytest.raises(SystemExit) as stopped:
        cli.main(["init", "demo", "--dir", str(home), "--shapes"])
    assert "docpipe[kg]" in str(stopped.value.code)
    assert str(stopped.value.code).endswith("nothing was written")
    assert list(home.iterdir()) == []
    # and the project without shapes needs no rdflib at all
    assert cli.main(["init", "demo", "--dir", str(home)]) == 0


def test_a_name_that_exists_already_is_refused_before_the_shapes_are_read(
        home, tmp_path):
    (home / "docpipe.toml").write_text("", encoding="utf-8")
    with pytest.raises(SystemExit) as stopped:
        cli.main(["init", "demo", "--dir", str(home), "--shapes",
                  str(_garbage(tmp_path))])
    assert "exists already" in str(stopped.value.code)
