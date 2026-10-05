"""What stage 3 and stage 5 hand on is written down as a schema.

The promise, in one sentence: docpipe/schemas holds a JSON Schema for
sections.json and one for visuals.json that accept a file as the writers
write it AND refuse a file that breaks what a reader needs, AND each writer
puts its own version key into its file, AND every reader still reads a file
with the key and a file without it, AND no stage refuses a file because of
the schema.

Each AND has its own tests, and each has a case built to break it: a table
without an id, a QA that says it passed with nothing measured, a version the
input file brought along, a file that violates the schema and is read anyway.
"""
import ast
import copy
import json
import shutil
import types
from pathlib import Path

import pytest

from docpipe import artifacts, estimate, status
from docpipe.artifacts import SCHEMA_DIR, SECTIONS_VERSION, VISUALS_VERSION
from docpipe.chunking import database as DB
from docpipe.chunking import merge as MG
from docpipe.preprocessing import stage3_structure as s3
from docpipe.preprocessing.models import Block, PageData
from docpipe.refinement import refine as R
from docpipe.visuals import config as C
from docpipe.visuals import pipeline as IP

jsonschema = pytest.importorskip("jsonschema")


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

def _schema(name):
    return json.loads((SCHEMA_DIR / f"{name}.schema.json")
                      .read_text(encoding="utf-8"))


def _errors(name, document):
    """The (path, message) of every way *document* does not fit."""
    validator = jsonschema.Draft202012Validator(_schema(name))
    return sorted(("/".join(str(p) for p in e.absolute_path), e.message)
                  for e in validator.iter_errors(document))


def _page(n, blocks):
    page = PageData(page_number=n, width_pt=595.0, height_pt=842.0)
    page.blocks = blocks
    return page


SOURCE = ("Energieträger Anteil Erdgas 45,2 Fernwärme 23,1 Wärmepumpe 12,8 "
          "Solar 5,0 Biomasse 9,1")
OTHER = "Zeile Spalte Alpha 100 Beta 200 Gamma 300 Delta 400"
FULL = ("| Energieträger | Anteil |\n| --- | --- |\n| Erdgas | 45,2 |\n"
        "| Fernwärme | 23,1 |\n| Wärmepumpe | 12,8 |\n| Solar | 5,0 |\n"
        "| Biomasse | 9,1 |")


def _stage3_blocks():
    """Two sections: a heading, prose on two pages, a table with its text
    layer, a figure; then a heading with a table that has no crop."""
    return [
        _page(1, [
            Block(id="p0_title0", type="text", bbox=[0, 0, 100, 20],
                  content="Einleitung", layout_label="paragraph_title"),
            Block(id="p0_t0", type="text", bbox=[0, 30, 100, 50],
                  content="Erster Absatz."),
            Block(id="p0_t1", type="text", bbox=[0, 55, 100, 70],
                  content="Zweiter Absatz."),
            Block(id="p0_tbl0", type="table", bbox=[0, 80, 200, 160],
                  path="images/p0_tbl0.png", caption="Tabelle 1: Anteile",
                  source_text=SOURCE),
        ]),
        _page(2, [
            Block(id="p1_t0", type="text", bbox=[0, 0, 100, 20],
                  content="Fortsetzung."),
            Block(id="p1_img0", type="image", bbox=[0, 30, 200, 120],
                  path="images/p1_img0.png"),
            Block(id="p1_title0", type="text", bbox=[0, 130, 100, 150],
                  content="Ausblick", layout_label="paragraph_title"),
            Block(id="p1_tbl0", type="table", bbox=[0, 160, 200, 240],
                  path="images/p1_tbl0.png", source_text=OTHER),
        ]),
    ]


@pytest.fixture
def document(tmp_path):
    """A document directory as stage 3 writes it: sections.json from the
    real writer, and the crops its paths name."""
    sections = s3.build_sections(_stage3_blocks())
    s3.save_output(sections, tmp_path)
    (tmp_path / "images").mkdir()
    for name in ("p0_tbl0", "p1_img0", "p1_tbl0"):
        (tmp_path / "images" / f"{name}.png").write_bytes(b"x")
    return tmp_path


def _sections_json(directory):
    return json.loads((directory / artifacts.SECTIONS_JSON)
                      .read_text(encoding="utf-8"))


def _client(monkeypatch, reply=None):
    reply = reply or json.dumps({"markdown": FULL, "description": "DESC",
                                 "caption": "CAP"})
    answer = types.SimpleNamespace(choices=[types.SimpleNamespace(
        message=types.SimpleNamespace(content=reply))])
    monkeypatch.setattr(IP, "create_client", lambda base_url=None,
                        timeout=None: types.SimpleNamespace(
        chat=types.SimpleNamespace(completions=types.SimpleNamespace(
            create=lambda **k: answer)),
        models=types.SimpleNamespace(list=lambda: types.SimpleNamespace(
            data=[types.SimpleNamespace(id=C.VLM_MODEL)]))))


@pytest.fixture
def visuals(document, monkeypatch):
    """visuals.json as stage 5 writes it over a stage 3 file of the first
    version (no key), so that whatever version it holds is the stage's own:
    one table that passes its check, one that fails it, a figure."""
    path = document / artifacts.SECTIONS_JSON
    path.write_text(json.dumps(_without(_sections_json(document))),
                    encoding="utf-8")
    _client(monkeypatch)
    IP.run_single(document)
    return json.loads((document / artifacts.VISUALS_JSON)
                      .read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# AND 1: a file as the writers write it fits
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["sections", "visuals"])
def test_a_schema_is_itself_a_valid_schema(name):
    jsonschema.Draft202012Validator.check_schema(_schema(name))


def test_the_file_stage_3_writes_fits(document):
    data = _sections_json(document)
    assert _errors("sections", data) == []
    # not an empty fit: the file holds what the schema is about
    assert [len(s["segments"]) for s in data["sections"]] == [4, 1]
    assert any("bbox" in s for s in data["sections"][0]["segments"])
    assert data["sections"][0]["tables"][0]["source_text"] == SOURCE


def test_the_file_stage_5_writes_fits_and_holds_both_results_of_the_check(
        visuals):
    assert _errors("visuals", visuals) == []
    passed, failed = [t["qa"]["passed"] for s in visuals["sections"]
                      for t in s["tables"]]
    assert (passed, failed) == (True, False)


def test_the_file_stage_5_writes_from_its_cache_fits_too(document, visuals,
                                                         monkeypatch):
    monkeypatch.setattr(IP, "create_client", lambda **k: (_ for _ in ()).throw(
        AssertionError("everything is cached")))
    again = IP.run_single(document)
    assert _errors("visuals", again) == []


def test_a_file_without_the_version_is_the_first_version(document):
    data = _sections_json(document)
    del data["version"]
    assert _errors("sections", data) == []


def test_keys_the_schema_does_not_name_are_carried_not_refused(document):
    data = _sections_json(document)
    data["parser"] = "elsewhere"
    data["sections"][0]["language"] = "de"
    data["sections"][0]["tables"][0]["rows"] = 5
    assert _errors("sections", data) == []


# ---------------------------------------------------------------------------
# AND 2: a file that breaks what a reader needs does not
# ---------------------------------------------------------------------------

def _drop(*path):
    def mutate(doc):
        target = doc
        for step in path[:-1]:
            target = target[step]
        del target[path[-1]]
    return mutate


def _set(*path, value):
    def mutate(doc):
        target = doc
        for step in path[:-1]:
            target = target[step]
        target[path[-1]] = value
    return mutate


# (what is wrong, the change that makes it so, where the schema says it is)
SECTIONS_BREAKS = [
    ("no sections", _drop("sections"), ""),
    ("a section without its tables", _drop("sections", 0, "tables"),
     "sections/0"),
    ("a section without its segments", _drop("sections", 0, "segments"),
     "sections/0"),
    ("a page below 1", _set("sections", 0, "pages", value=[0, 1]),
     "sections/0/pages/0"),
    ("content that is a list", _set("sections", 0, "content", value=["a"]),
     "sections/0/content"),
    ("a segment of an unknown kind",
     _set("sections", 0, "segments", 0, "kind", value="heading"),
     "sections/0/segments/0/kind"),
    ("a text segment without its text",
     _drop("sections", 0, "segments", 0, "text"), "sections/0/segments/0"),
    ("a table segment without its ref",
     _drop("sections", 0, "segments", 1, "ref"), "sections/0/segments/1"),
    ("a segment without its page", _drop("sections", 0, "segments", 0, "page"),
     "sections/0/segments/0"),
    ("a table without an id", _drop("sections", 0, "tables", 0, "id"),
     "sections/0/tables/0"),
    ("a table without a path", _drop("sections", 0, "tables", 0, "path"),
     "sections/0/tables/0"),
    ("an id the placeholder pattern cannot find",
     _set("sections", 0, "tables", 0, "id", value="P0 Tbl"),
     "sections/0/tables/0/id"),
    ("a bbox that is a bare rect",
     _set("sections", 0, "tables", 0, "bbox", value=[1, 2, 3, 4]),
     "sections/0/tables/0/bbox/0"),
    ("a rect of three numbers",
     _set("sections", 0, "segments", 0, "bbox", value=[[1, 2, 3]]),
     "sections/0/segments/0/bbox/0"),
    ("a version the schema does not describe", _set("version", value=2),
     "version"),
    ("a version that is not a number", _set("version", value="1"), "version"),
]


@pytest.mark.parametrize("what,change,where", SECTIONS_BREAKS,
                         ids=[b[0] for b in SECTIONS_BREAKS])
def test_a_sections_file_that_breaks_what_a_reader_needs_is_not_a_fit(
        document, what, change, where):
    data = _sections_json(document)
    change(data)
    found = _errors("sections", data)
    assert found, f"{what}: the schema accepted it"
    assert any(path.startswith(where) for path, _ in found), (what, found)


VISUALS_BREAKS = [
    ("no sections", _drop("sections"), ""),
    ("a table without an id", _drop("sections", 0, "tables", 0, "id"),
     "sections/0/tables/0"),
    ("a markdown that is not text",
     _set("sections", 0, "tables", 0, "markdown", value=None),
     "sections/0/tables/0/markdown"),
    ("a status nobody writes",
     _set("sections", 0, "tables", 0, "vlm_status", value="ok"),
     "sections/0/tables/0/vlm_status"),
    ("a figure description that is not text",
     _set("sections", 0, "figures", 0, "description", value=7),
     "sections/0/figures/0/description"),
    ("a qa that does not say whether it passed",
     _drop("sections", 0, "tables", 0, "qa", "passed"),
     "sections/0/tables/0/qa"),
    ("a qa that passed as a word",
     _set("sections", 0, "tables", 0, "qa", "passed", value="yes"),
     "sections/0/tables/0/qa/passed"),
    ("a coverage above 1",
     _set("sections", 0, "tables", 0, "qa", "coverage", value=1.5),
     "sections/0/tables/0/qa/coverage"),
    ("a duplication that is missing",
     _drop("sections", 0, "tables", 0, "qa", "duplication"),
     "sections/0/tables/0/qa"),
    ("a measured coverage that is null",
     _set("sections", 0, "tables", 0, "qa", "coverage", value=None),
     "sections/0/tables/0/qa"),
    ("an unmeasured coverage that is a number",
     _set("sections", 0, "tables", 0, "qa", "coverage_assessed", value=False),
     "sections/0/tables/0/qa"),
    ("a version that is not 1", _set("version", value=0), "version"),
]


@pytest.mark.parametrize("what,change,where", VISUALS_BREAKS,
                         ids=[b[0] for b in VISUALS_BREAKS])
def test_a_visuals_file_that_breaks_what_a_reader_needs_is_not_a_fit(
        visuals, what, change, where):
    data = copy.deepcopy(visuals)
    change(data)
    found = _errors("visuals", data)
    assert found, f"{what}: the schema accepted it"
    assert any(path.startswith(where) for path, _ in found), (what, found)


def test_a_qa_that_measured_nothing_is_a_fit_when_it_says_so(visuals):
    """Coverage null is unknown, not 1: the one way a table with no text layer
    can be written."""
    data = copy.deepcopy(visuals)
    data["sections"][0]["tables"][0]["qa"].update(
        coverage=None, coverage_assessed=False)
    assert _errors("visuals", data) == []


def test_the_file_stage_5_writes_for_frames_without_text_fits(document,
                                                              monkeypatch):
    """Not a hand-edited dict: the stage itself, over a stage 3 file whose
    tables carry no text of the PDF, writes an unknown coverage."""
    data = _sections_json(document)
    for section in data["sections"]:
        for table in section["tables"]:
            del table["source_text"]
    _put(document, artifacts.SECTIONS_JSON, data)
    _client(monkeypatch)
    written = IP.run_single(document)
    checks = [t["qa"] for s in written["sections"] for t in s["tables"]]
    assert len(checks) == 2
    assert all(c["coverage"] is None and c["coverage_assessed"] is False
               for c in checks)
    assert _errors("visuals", written) == []


def test_the_file_stage_5_writes_for_tables_rescued_as_plain_text_fits(
        document, monkeypatch):
    """A table the model never answered in JSON has no check at all, and the
    file still fits: the schema does not ask for what was not measured."""
    from docpipe.visuals import process as P
    _client(monkeypatch)
    monkeypatch.setattr(P, "call_vision", lambda *a, **k: None)
    monkeypatch.setattr(P, "call_vision_plain", lambda *a, **k: FULL)
    written = IP.run_single(document)
    tables = [t for s in written["sections"] for t in s["tables"]]
    assert len(tables) == 2
    assert all(t["vlm_status"] == "plain_text" and "qa" not in t
               for t in tables)
    assert _errors("visuals", written) == []


def test_a_table_with_an_empty_path_is_left_without_a_markdown_as_said(
        document, monkeypatch):
    """What the schema says of an empty `path`: the table is not transcribed
    (and the stage goes on with the others)."""
    data = _sections_json(document)
    data["sections"][0]["tables"][0]["path"] = ""
    assert _errors("sections", data) == []
    _put(document, artifacts.SECTIONS_JSON, data)
    _client(monkeypatch)
    written = IP.run_single(document)
    assert "markdown" not in written["sections"][0]["tables"][0]
    assert written["sections"][1]["tables"][0]["markdown"] == FULL


# ---------------------------------------------------------------------------
# AND 3: each writer puts its own version into its file
# ---------------------------------------------------------------------------

def test_stage_3_writes_its_version_first(document):
    data = _sections_json(document)
    assert data["version"] == SECTIONS_VERSION
    assert list(data)[0] == "version"


def test_stage_5_writes_its_version_first(visuals):
    assert visuals["version"] == VISUALS_VERSION
    assert list(visuals)[0] == "version"


def test_stage_5_does_not_take_the_version_its_input_brought(
        document, monkeypatch):
    """The output is a copy of its input. An input that says 7 must not make
    the output say 7: the two files are counted apart."""
    path = document / artifacts.SECTIONS_JSON
    data = _sections_json(document)
    data["version"] = 7
    path.write_text(json.dumps(data), encoding="utf-8")
    _client(monkeypatch)
    written = IP.run_single(document)
    assert written["version"] == VISUALS_VERSION
    on_disk = json.loads((document / artifacts.VISUALS_JSON)
                         .read_text(encoding="utf-8"))
    assert on_disk["version"] == VISUALS_VERSION == 1


def test_stage_5_writes_its_version_on_the_cached_run_too(document, visuals,
                                                          monkeypatch):
    """An old file has no key; rewriting it from the cache must add it."""
    old = copy.deepcopy(visuals)
    del old["version"]
    path = document / artifacts.VISUALS_JSON
    path.write_text(json.dumps(old), encoding="utf-8")
    monkeypatch.setattr(IP, "create_client", lambda **k: (_ for _ in ()).throw(
        AssertionError("everything is cached")))
    IP.run_single(document)
    assert json.loads(path.read_text(encoding="utf-8"))["version"] \
        == VISUALS_VERSION


# ---------------------------------------------------------------------------
# AND 4: every reader reads the file with the key and without it
# ---------------------------------------------------------------------------

def _without(data):
    data = copy.deepcopy(data)
    data.pop("version", None)
    return data


def _put(directory, name, data):
    path = directory / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_the_readers_of_sections_json_read_it_with_and_without_the_key(
        document, tmp_path_factory):
    with_key = _sections_json(document)
    assert "version" in with_key
    old = _without(with_key)

    def read_all(data):
        directory = tmp_path_factory.mktemp("doc")
        _put(directory, artifacts.SECTIONS_JSON, data)
        (directory / "images").mkdir()
        for name in ("p0_tbl0", "p1_img0", "p1_tbl0"):
            (directory / "images" / f"{name}.png").write_bytes(b"x")
        cached: dict = {}
        IP.collect_cached(data, cached)
        return {
            "source_texts": IP._load_source_texts(directory),
            "dry_run": IP.run_single(directory, dry_run=True),
            "bbox": DB._bbox_lookups_from_stage3(data),
            "cached": cached,
        }

    new_read, old_read = read_all(with_key), read_all(old)
    assert new_read["source_texts"] == old_read["source_texts"] \
        == {"p0_tbl0": SOURCE, "p1_tbl0": OTHER}
    assert new_read["bbox"] == old_read["bbox"]
    assert new_read["bbox"][0], "the lookup found no geometry at all"
    assert new_read["dry_run"]["sections"] == old_read["dry_run"]["sections"]


def test_stage_4_reads_sections_json_with_the_key_and_writes_no_key(tmp_path):
    """Stage 4 takes the sections and nothing else of the file, so the key
    neither disturbs it nor travels on into sections_refined.json."""
    _put(tmp_path, artifacts.SECTIONS_JSON, {"version": 1, "sections": []})
    refined = R.run_refine(tmp_path)
    assert refined == {"sections": []}
    on_disk = json.loads((tmp_path / artifacts.SECTIONS_REFINED_JSON)
                         .read_text(encoding="utf-8"))
    assert on_disk == {"sections": []}


def test_the_resume_key_of_stage_4_does_not_move_with_the_version(document):
    """A partial pass is resumed only for the same sections. The version is
    not part of what it hashes, so adding it makes no unfinished pass stale."""
    with_key = _sections_json(document)["sections"]
    assert R._partial_key(with_key) == R._partial_key(
        copy.deepcopy(_without(_sections_json(document))["sections"]))


def test_the_estimate_counts_the_same_with_and_without_the_key(
        tmp_path, capsys):
    def counted(data, name):
        root = tmp_path / name
        _put(root / "plan", artifacts.SECTIONS_JSON, data)
        (root / "plan" / "images").mkdir()
        for crop in ("p0_tbl0", "p1_img0", "p1_tbl0"):
            (root / "plan" / "images" / f"{crop}.png").write_bytes(b"x")
        out = []
        for stage in ("refine", "visuals"):
            estimate.main([stage, "--processed", str(root)])
            out.append(capsys.readouterr().out)
        return out

    sections = s3.build_sections(_stage3_blocks())
    with_key = s3.sections_to_dict(sections)
    assert "version" in with_key
    assert counted(with_key, "a") == counted(_without(with_key), "b")


def test_the_readers_of_visuals_json_read_it_with_and_without_the_key(
        document, visuals, tmp_path_factory):
    old = _without(visuals)
    assert "version" in visuals

    def read_all(data):
        directory = tmp_path_factory.mktemp("doc")
        shutil.copytree(document, directory, dirs_exist_ok=True)
        _put(directory, artifacts.VISUALS_JSON, data)
        cached: dict = {}
        IP.collect_cached(data, cached)
        _put(directory, artifacts.SECTIONS_REFINED_JSON,
             _sections_json(document))
        merged = MG.merge_single(directory, force=True)
        return {"cached": cached, "lookup": MG._build_enriched_lookup(data),
                "there": status._visuals_there(directory, IP),
                "merged": merged}

    new_read, old_read = read_all(visuals), read_all(old)
    assert new_read == old_read
    assert new_read["there"] is True
    assert set(new_read["cached"]) == {"p0_tbl0", "p1_img0", "p1_tbl0"}
    assert new_read["merged"]["sections"][0]["tables"][0]["markdown"] == FULL


# ---------------------------------------------------------------------------
# AND 5: no stage refuses a file because of the schema
# ---------------------------------------------------------------------------

def test_a_stage_reads_and_enriches_a_file_that_does_not_fit(document,
                                                             monkeypatch):
    """The file lacks what the schema requires of a section (pages, segments)
    and the stage still reads it, asks the model and writes its result."""
    data = _sections_json(document)
    for section in data["sections"]:
        del section["pages"]
        del section["segments"]
    assert _errors("sections", data)
    _put(document, artifacts.SECTIONS_JSON, data)
    _client(monkeypatch)
    written = IP.run_single(document)
    assert written is not None
    assert written["sections"][0]["tables"][0]["markdown"] == FULL
    assert (document / artifacts.VISUALS_JSON).exists()


def test_a_stage_reads_a_file_whose_version_it_has_never_heard_of(
        document, monkeypatch):
    data = _sections_json(document)
    data["version"] = 99
    assert _errors("sections", data)
    _put(document, artifacts.SECTIONS_JSON, data)
    _client(monkeypatch)
    assert IP.run_single(document) is not None


def _names_a_schema(path: Path) -> bool:
    """Does the code of this module (not its comments or docstrings) name the
    schema directory or one of the schema files?"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = {id(node.body[0].value) for node in ast.walk(tree)
                  if isinstance(node, (ast.Module, ast.FunctionDef,
                                       ast.AsyncFunctionDef, ast.ClassDef))
                  and node.body and isinstance(node.body[0], ast.Expr)
                  and isinstance(node.body[0].value, ast.Constant)}
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == "SCHEMA_DIR":
            return True
        if isinstance(node, ast.Attribute) and node.attr == "SCHEMA_DIR":
            return True
        if isinstance(node, ast.alias) and node.name == "SCHEMA_DIR":
            return True
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and id(node) not in docstrings
                and ("sections.schema" in node.value
                     or "visuals.schema" in node.value)):
            return True
    return False


def test_no_module_of_the_package_opens_the_schemas_but_the_one_that_names_them():
    """The schemas are documentation and tests. A stage that read one to
    refuse a file would be a new way for a run to stop."""
    core = Path(artifacts.__file__).resolve().parent
    users = sorted(str(p.relative_to(core)) for p in core.rglob("*.py")
                   if _names_a_schema(p))
    assert users == ["artifacts.py"]


def test_that_check_can_fail(tmp_path):
    """A stage that did open the schema is found by it."""
    stage = tmp_path / "stage.py"
    stage.write_text("from docpipe.artifacts import SCHEMA_DIR" + chr(10),
                     encoding="utf-8")
    assert _names_a_schema(stage)
    other = tmp_path / "other.py"
    other.write_text("name = 'sections.schema.json'" + chr(10),
                     encoding="utf-8")
    assert _names_a_schema(other)
    talk = tmp_path / "talk.py"
    talk.write_text('"""See sections.schema.json."""' + chr(10)
                    + "# SCHEMA_DIR" + chr(10), encoding="utf-8")
    assert not _names_a_schema(talk)
