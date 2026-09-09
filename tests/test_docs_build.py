"""The documentation is generated, and these are what make that mean something.

A generated page is only better than a hand-written one while three things hold:
the manifest still points at files that exist, the checked-in pages are a fresh
render, and the generator cannot read anything it should not publish. Each of
those is a test here, and each fails within seconds of a rename, a stale page or
a second file read.

Offline: no corpus, no network, no model, no database, no GPU. The generator
imports nothing from `docpipe` on purpose -- one of the modules it documents
imports OpenCV, PyMuPDF and torch at module level, so a generator that imported
its subject would need the GPU stack to render a docstring.
"""
import ast
import io
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build_docs                                            # noqa: E402
from build_docs import (SourceMoved, build, check, constants_of,  # noqa: E402
                        docstring_of, json_at, main, read_source,
                        render_artifacts_page, render_contract_page,
                        render_index, render_stage_page, render_states_page,
                        render_toctree, render_trust_page,
                        render_profiles_page, resolve, states_table,
                        trust_table, write)


# ---------------------------------------------------------------------------
# The manifest still points at the tree
# ---------------------------------------------------------------------------
def test_every_source_the_manifest_names_exists_today():
    """`resolve` over the real tree. A renamed package or an emptied docstring
    is a red test here rather than a page that quietly documents nothing."""
    got = resolve(build_docs.SOURCES + build_docs._contract_sources())
    assert got, "the manifest is empty"
    for page, parts in got.items():
        assert parts, page
        for rel, value in parts:
            assert value, f"{page}: {rel} rendered nothing"
    assert json_at("profiles/kwp/extraction_schema.json", "harvest/$defs")


def test_a_moved_source_fails_the_build(tmp_path, monkeypatch):
    """One source gone fails the WHOLE build. Skipped instead, the site is
    half fresh and half from before the rename, and nothing says which half."""
    moved = (("stages/store.md", "The database",
              (("docpipe/does_not_exist.py", None),)),)
    monkeypatch.setattr(build_docs, "SOURCES", moved)
    with pytest.raises(SourceMoved):
        build()
    assert list(tmp_path.iterdir()) == [], "nothing was written"


def test_an_emptied_docstring_fails_the_build():
    """A module that still exists and no longer says anything is the failure a
    file-existence check cannot see."""
    with pytest.raises(SourceMoved):
        docstring_of("docpipe/preprocessing/__init__.py")


def test_the_checked_in_docs_are_the_generated_ones():
    """The whole point. Hand-edit a page, change a docstring without
    regenerating, or leave a page behind after removing its manifest entry,
    and this goes red."""
    assert main(["--check"]) == 0
    assert check() == 0


# ---------------------------------------------------------------------------
# The hand-written page
# ---------------------------------------------------------------------------
def test_the_hand_written_page_is_never_overwritten(tmp_path):
    """It is a source, not an output. Generated, it would say what the parts
    do rather than what they are for, which is the one thing no docstring
    carries."""
    pages = build()
    assert "pipeline.md" not in pages
    seeded = tmp_path / "pipeline.md"
    seeded.write_text("von Hand", encoding="utf-8")
    write(tmp_path, {**pages, "pipeline.md": "generiert"})
    assert seeded.read_text(encoding="utf-8") == "von Hand"


def test_a_missing_hand_written_page_fails_the_build(tmp_path, monkeypatch):
    """The index links it. Missing, the site ships a link to a 404."""
    monkeypatch.setattr(build_docs, "PAGES_DIR", tmp_path)
    with pytest.raises(SourceMoved):
        build()


def test_the_hand_written_page_does_not_restate_the_readme():
    """The README already lists the stages. A second copy of that is the
    uncheckable duplicate this whole package exists to prevent."""
    readme = {line.strip() for line
              in (ROOT / "README.md").read_text(encoding="utf-8").splitlines()
              if len(line.strip()) > 40}
    for name in build_docs.HANDWRITTEN:
        page = [line.strip() for line
                in (ROOT / "docs" / name).read_text(encoding="utf-8")
                .splitlines() if len(line.strip()) > 40]
        assert [line for line in page if line in readme] == [], name


def test_the_index_links_every_page_and_nothing_else():
    """A page nobody links is a page nobody reads, and a link to a page that
    no longer exists is worse than no link. The module pages of the API
    reference are the exception: they are reached through the reference's
    own index, not from the front page."""
    pages = build()
    text = pages["README.md"]
    linked = {part.split(")")[0] for part in text.split("](")[1:]}
    linked = {link for link in linked if link.endswith(".md")}
    # `index.md` is Sphinx's front page and carries the toctree; the README is
    # what a reader of the repository opens. Neither links the other. The
    # module pages of the API reference are reached through its own index.
    modules = {page for page in pages if build_docs.is_api_module(page)}
    assert linked == ((set(pages) - {"README.md", "index.md"} - modules)
                      | set(build_docs.HANDWRITTEN))
    assert render_index({"a.md": "A"}).count("](a.md)") == 1


def test_the_index_says_what_each_page_is_about():
    """Each index line carries the first sentence of the page's primary
    source's docstring, so a reader picks a page by what it is about and not
    by its title alone. A page whose primary source is a schema has no
    docstring and gets no lede, rather than a made-up one."""
    from build_docs import _lede
    text = build()["README.md"]
    lines = {line.split("](")[1].split(")")[0]: line
             for line in text.splitlines() if line.startswith("- [")}
    lede = _lede(docstring_of("docpipe/extraction/__init__.py"))
    assert lede.endswith(".") and " " in lede
    assert lines["stages/extraction.md"].endswith(f"): {lede}")
    assert lines["contract/kwp.md"].endswith(")")
    # The lede is one sentence, joined across the docstring's lines.
    assert _lede("The per-document files, in the order\nthey are "
                 "written.\n\nSecond paragraph.") \
        == "The per-document files, in the order they are written."
    assert _lede("Writes results.json to disk. Then more.") \
        == "Writes results.json to disk."
    # The file name a docstring opens with is not the page's subject.
    assert _lede("trust.py: Grades every value. More.") \
        == "Grades every value."
    assert _lede("kg_route.py \u2013 Answers from the graph.\n") \
        == "Answers from the graph."
    assert render_index({"a.md": "A"}, {"a.md": "Erste Zeile."}) \
        .count("](a.md): Erste Zeile.") == 1


def test_the_site_names_every_page_exactly_once_and_in_order():
    """Sphinx builds from one toctree. A page missing from it is built and
    reachable from nothing; a page named twice is a warning, and the Read the
    Docs build treats warnings as errors. The API reference's module pages
    sit in a second layer, the hidden toctrees of `api/index.md`, and are
    checked there."""
    pages = build()
    listed = _toctree_entries(pages["index.md"])
    wanted = ({page[:-3] for page in pages
               if page not in ("README.md", "index.md")
               and not build_docs.is_api_module(page)}
              | {name[:-3] for name in build_docs.HANDWRITTEN})
    assert sorted(listed) == sorted(wanted)
    assert len(listed) == len(set(listed)), "a page is named twice"
    # And the order is the pipeline's, which is in no file: the groups in
    # their order, the discovered profile pages inside their group.
    groups = build_docs.toctree_groups(pages)
    assert [page[:-3] for _c, members in groups for page in members] \
        == listed
    assert [page for _c, members in groups for page in members
            if page in build_docs.ORDER] == list(build_docs.ORDER)
    assert [caption for caption, _m in groups] \
        == [caption for caption, _m in build_docs.GROUPS]
    # A page the manifest does not render still reaches the toctree, so a new
    # page is a broken build rather than an unreachable document.
    assert "neu" in render_toctree({"neu.md": "Neu"})
    assert ("More", ["neu.md"]) in build_docs.toctree_groups({"neu.md": ""})


def _toctree_entries(index: str) -> list:
    """The pages every toctree block of index.md names, in order."""
    out = []
    for block in index.split("```{toctree}")[1:]:
        inside = block.split("```")[0]
        out += [line.strip() for line in inside.splitlines()
                if line.strip() and not line.startswith(":")]
    return out


# ---------------------------------------------------------------------------
# The one door
# ---------------------------------------------------------------------------
def test_a_source_under_data_is_refused():
    """`data/` holds the corpus and the database. A generator that can read a
    plan can publish one, and the plans are not ours to publish."""
    for rel in ("data/KWP.db", "../secrets", "utils/x.py",
                "docpipe/../data/KWP.db"):
        with pytest.raises(SourceMoved):
            read_source(rel)
    assert read_source("docpipe/artifacts.py").startswith('"""')


def test_the_generator_reads_through_one_door():
    """One read, in one function, with one guard in front of it. A second read
    anywhere makes the guard decorative."""
    text = (ROOT / "scripts" / "build_docs.py").read_text(encoding="utf-8")
    tree = ast.parse(text)
    allowed = {"read_source", "_profile_names", "_pages_on_disk",
               "_api_modules", "write"}
    inside = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            for child in ast.walk(node):
                inside[id(child)] = node.name
    readers = {"read_text", "read_bytes", "open", "glob", "rglob",
               "iterdir", "listdir", "load"}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = (func.attr if isinstance(func, ast.Attribute)
                else func.id if isinstance(func, ast.Name) else "")
        if name not in readers and name != "open":
            continue
        where = inside.get(id(node))
        assert where in allowed, f"{name}() in {where}"
    # And the enumerators only enumerate.
    for enumerating in ("_profile_names", "_pages_on_disk",
                        "_api_modules"):
        enumerator = next(n for n in ast.walk(tree)
                          if isinstance(n, ast.FunctionDef)
                          and n.name == enumerating)
        for node in ast.walk(enumerator):
            if isinstance(node, ast.Call):
                func = node.func
                name = (func.attr if isinstance(func, ast.Attribute)
                        else func.id if isinstance(func, ast.Name) else "")
                assert name not in {"read_text", "read_bytes", "open",
                                    "load"}, enumerating
    # And the writer only writes.
    writer = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "write")
    opens = [node for node in ast.walk(writer)
             if isinstance(node, ast.Call)
             and getattr(node.func, "attr", getattr(node.func, "id", ""))
             == "open"]
    assert opens
    for node in opens:
        assert any(isinstance(arg, ast.Constant) and arg.value == "w"
                   for arg in node.args), "write opens for writing only"


def test_the_contract_page_is_built_from_the_schema_not_the_spec():
    """The spec carries a real corpus table as its few-shot example. The
    schema does not: `grep -c '"example"'` is 0 on both checked-in files."""
    for _page, _title, entries in (build_docs.SOURCES
                                   + build_docs._contract_sources()):
        for rel, _pointer in entries:
            assert "extraction_spec.json" not in rel, rel
    # And a contract page really is the schema's own text: its lede is the
    # sentence the generator writes about the published record kinds, and the
    # sections are the schema's own def names.
    page = build()["contract/kwp.md"]
    defs = json_at("profiles/kwp/extraction_schema.json", "harvest/$defs")
    for name in defs:
        if name in ("state", "provenance"):
            continue
        heading = name[len("tuple_"):] if name.startswith("tuple_") else name
        assert f"## `{heading}`" in page, heading
    assert render_contract_page("kwp", {}).startswith("# The harvest contract")


def test_no_generated_page_quotes_a_corpus_passage():
    """The belt to the one door's braces. The examples are the only corpus
    text in this repository, and a page that reproduced one would publish a
    passage of somebody's plan."""
    pages = "".join(build().values())
    for profile in build_docs._profile_names():
        spec = json.loads((ROOT / "profiles" / profile / "extraction_spec.json")
                          .read_text(encoding="utf-8"))
        for parameter in spec["parameters"]:
            source = (parameter.get("example") or {}).get("source") or ""
            for line in source.splitlines():
                if len(line.strip()) > 40:
                    assert line.strip() not in pages, line[:60]


def test_the_build_writes_nothing_outside_the_out_directory(tmp_path):
    """`--check` renders every page. A helper that wrote to `docs/` on the way
    would make the check mutate the tree it is checking."""
    before = {p: p.read_bytes() for p in
              sorted((ROOT / "docs").rglob("*")) if p.is_file()}
    written = write(tmp_path, build())
    assert written
    for path in written:
        assert tmp_path in path.parents
    after = {p: p.read_bytes() for p in
             sorted((ROOT / "docs").rglob("*")) if p.is_file()}
    assert after == before
    for bad in ("../x.md", "/x.md"):
        with pytest.raises(ValueError):
            write(tmp_path, {bad: "x"})


# ---------------------------------------------------------------------------
# What the pages say
# ---------------------------------------------------------------------------
def test_every_state_of_fields_is_documented():
    """Seven states and twelve string constants in the same module. Published
    by "every constant", the page offers `out:unstated`, which is an ANSWER a
    model may give and not a state a coordinate can be in."""
    rows = states_table()
    assert [name for name, _v, _g in rows] == [
        "READ", "DERIVED", "SAID_UNSTATED", "UNANSWERED", "EXHAUSTED",
        "UNBACKED", "OUT_OF_SLICE"]
    pages = build()
    page = pages["contract/states.md"]
    # It is an ANSWER a model may give, so it is all over the prompt wording
    # the contract pages quote. It is not a state, so it is not on this page.
    # In the generated table, that is: the introduction may explain the
    # sentinel in prose, the table may not list it.
    generated = page[page.index("| constant | value |"):]
    assert "out:unstated" not in generated
    for _name, value, gloss in rows:
        assert value in page and gloss in page
    assert render_states_page(rows).count("|---|---|---|") == 1
    # Both profiles publish the same state vocabulary, so which one the page
    # is built from cannot matter.
    first, *rest = build_docs._profile_names()
    for other in rest:
        assert (json_at(f"profiles/{other}/extraction_schema.json",
                        "harvest/$defs/state")
                == json_at(f"profiles/{first}/extraction_schema.json",
                           "harvest/$defs/state"))


def test_every_trust_level_and_reason_family_is_documented():
    """The reason that reaches the harvest is the VALUE of the flag mapping,
    not its key: rendered the other way the page publishes `quote_repaired`,
    which matches no pattern the schema accepts."""
    levels, reasons, flags, marks, join = trust_table()
    assert [level for level, _gloss in levels] == ["A", "B", "C"]
    page = build()["contract/trust.md"]
    for value in flags.values():
        assert value in page
        assert any(value == pattern.strip("^$") for pattern in reasons), value
    for pattern in reasons:
        assert pattern in page
    assert render_trust_page(levels, reasons, flags, marks, join,
                             "x").startswith("# How")


def test_the_marks_of_a_trust_line_are_documented_in_their_order():
    """The line above a value node is the profile's words in the core's
    order, and the order is a fact about trust.py that no profile can state.
    Read off trust.py by AST here, independently of the generator's reader."""
    tree = ast.parse((ROOT / "docpipe" / "extraction" / "trust.py")
                     .read_text(encoding="utf-8"))
    literal = {n.targets[0].id: ast.literal_eval(n.value) for n in tree.body
               if isinstance(n, ast.Assign)
               and isinstance(n.targets[0], ast.Name)
               and n.targets[0].id in ("MARKS", "REASON_JOIN")}
    _levels, _reasons, _flags, marks, join = trust_table()
    assert marks == tuple(literal["MARKS"]) and join == literal["REASON_JOIN"]
    page = build()["contract/trust.md"]
    section = page[page.index("\n## The marks of a trust line\n"):]
    listed = [line.split("`")[1] for line in section.splitlines()
              if line[:1].isdigit()]
    assert listed == list(marks)
    assert f"joined with `{join}`" in section


def test_the_contract_page_documents_the_stamp_and_the_trace():
    """Both checked-in schemas carry three top-level branches, and the page
    used to render one. The stamp is what the resume decides on and the
    trace what the cost is read from, so a reader of the contract has to see
    their keys and their record kinds, straight from the JSON."""
    pages = build()
    for name in build_docs._profile_names():
        rel = build_docs._contract_rel(name)
        stamp, trace = json_at(rel, "stamp"), json_at(rel, "trace")
        page = pages[f"contract/{name}.md"]
        # Heading lines, not mentions: an introduction may name the sections.
        assert "\n## The stamp\n" in page and "\n## The trace\n" in page
        stamp_part = page[page.index("\n## The stamp\n"):
                          page.index("\n## The trace\n")]
        for key in stamp["properties"]:
            assert f"| `{key}` |" in stamp_part, key
        for pattern in stamp["patternProperties"]:
            # A pipe inside a code span still splits a table cell.
            cell = pattern.replace("|", "\\|")
            assert f"| `{cell}` |" in stamp_part, pattern
        trace_part = page[page.index("\n## The trace\n"):]
        kinds = [b["properties"]["t"]["const"] for b in trace["oneOf"]]
        assert len(kinds) == 11
        assert f"{len(kinds)} record kinds" in trace_part
        for kind in kinds:
            assert f"- `{kind}`:" in trace_part, kind
    # Rendered without them, the page says nothing about either.
    bare = render_contract_page("x", {"refusal": {"type": "object"}})
    assert "## The stamp" not in bare and "## The trace" not in bare


def test_a_profile_with_a_schema_gets_a_contract_page():
    """Discovered, not listed: a third profile added with a schema and no page
    is exactly the kind of gap a hand-maintained list keeps."""
    have = {p.parent.name for p in (ROOT / "profiles")
            .glob("*/extraction_schema.json")}
    pages = build()
    assert {page.split("/")[1][:-3] for page in pages
            if page.startswith("contract/")
            and page not in ("contract/states.md",
                             "contract/trust.md")} == have
    assert render_profiles_page("x", sorted(have)).startswith("# Profiles")


def test_every_stage_package_of_the_core_has_a_page():
    """Coverage is derived from the manifest's paths and not from the page
    names: the pages are named after the stages, the packages after what they
    do, and those two lists have already drifted apart once."""
    documented = {rel for _p, _t, entries in build_docs.SOURCES
                  for rel, _pointer in entries}
    for pipeline in sorted((ROOT / "docpipe").glob("*/pipeline.py")):
        package = pipeline.parent.name
        assert any(rel.startswith(f"docpipe/{package}/")
                   for rel in documented), package
    assert render_stage_page("stages/store.md", [("a.py", "doc")]).endswith(
        "\n")


def test_the_artifact_constants_carry_the_stage_that_writes_them():
    """Two tools over one string, because neither alone can do it: `ast` keeps
    no comments, and seven of these nine names are f-strings that
    `literal_eval` refuses."""
    rows = constants_of("docpipe/artifacts.py")
    by_name = {name: (value, note) for name, value, note in rows}
    assert len(rows) == 9
    assert by_name["PAGES_JSON"] == ("results/pages.json",
                                     "preprocessing (extract)")
    # The two-line assignment: its comment sits on the continuation line.
    assert by_name["PAGE_TRANSCRIPTION_REPORT_JSON"] == (
        "results/page_transcription_report.json",
        "preprocessing (model-read pages)")
    assert by_name["DIR_RESULTS"] == ("results", "")
    page = render_artifacts_page(rows, "doc")
    assert "results/pages.json" in page


def test_claude_md_lists_the_same_states_as_the_schema():
    """The German table in CLAUDE.md is the copy a reader of that file acts
    on. A state added to the schema and not to it leaves the instructions
    quietly wrong."""
    text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    enum = set(json_at(f"profiles/{build_docs._profile_names()[0]}"
                       f"/extraction_schema.json", "harvest/$defs/state")
               ["enum"])
    named = {value for value in enum if f"`{value}`" in text}
    assert named == enum, sorted(enum - named)

# ---------------------------------------------------------------------------
# The published site
# ---------------------------------------------------------------------------
def test_the_site_config_and_the_pages_agree():
    """Read the Docs builds `docs/conf.py` with `fail_on_warning: true`, and
    Sphinx is not installed here -- so what can be checked without it is
    checked here: that the config parses, that it excludes exactly the files
    that are sources rather than pages, and that every entry of the toctree
    names a file that exists."""
    import ast as _ast
    config = _ast.parse((ROOT / "docs" / "conf.py").read_text(encoding="utf-8"))
    values = {}
    for node in config.body:
        if (isinstance(node, _ast.Assign)
                and isinstance(node.targets[0], _ast.Name)):
            try:
                values[node.targets[0].id] = _ast.literal_eval(node.value)
            except ValueError:
                pass
    assert values["master_doc"] == "index"
    assert "myst_parser" in values["extensions"]
    # The two that are sources and not pages. Built, each would be a document
    # no toctree names, which is a warning, which is a failed build.
    for excluded in ("_intros", "README.md"):
        assert excluded in values["exclude_patterns"], excluded

    entries = _toctree_entries(build()["index.md"])
    assert entries
    for entry in entries:
        assert (ROOT / "docs" / f"{entry}.md").is_file(), entry


def test_the_docs_build_needs_neither_the_corpus_nor_a_gpu():
    """The site is built from Markdown that is already in the tree, so its
    requirements are three packages and not the project's 213. Pulling in
    torch to render a docstring would turn a one-minute build into an hour and
    tie the documentation to a machine with a GPU."""
    wanted = (ROOT / "docs" / "requirements.txt").read_text(encoding="utf-8")
    named = [line.split("==")[0].strip() for line in wanted.splitlines()
             if line.strip() and not line.startswith("#")]
    assert named == ["sphinx", "myst-parser", "furo"]
    config = (ROOT / "docs" / "conf.py").read_text(encoding="utf-8")
    assert "autodoc" not in config.split('"""')[2], "autodoc imports docpipe"
    rtd = (ROOT / ".readthedocs.yaml").read_text(encoding="utf-8")
    assert "docs/requirements.txt" in rtd
    assert "configuration: docs/conf.py" in rtd
    assert "fail_on_warning: true" in rtd


def test_every_page_says_what_it_is_for(monkeypatch):
    """A page of docstrings or of tables is a list of parts. What no module
    can say is what the thing is for, so every generated page, the front
    page included, opens with prose from `docs/_intros/`, and a page without
    it is refused rather than published half-empty.

    A module page of the API reference is the exception: what it is for is
    its module's own docstring, and the reference's index carries the
    prose."""
    from build_docs import intro_of
    pages = build()
    for page in sorted(pages):
        if page == "README.md" or build_docs.is_api_module(page):
            continue
        intro = intro_of(page)
        assert intro, page
        assert intro in pages[page], page
        assert len(intro) > 200, f"{page}: {len(intro)} characters"
        assert not intro.startswith("#") or intro.startswith("##"), page
    assert intro_of("stages/gibt_es_nicht.md") == ""
    monkeypatch.setattr(build_docs, "INTRO_DIR", "docs/_gibt_es_nicht")
    with pytest.raises(SourceMoved):
        build()


def test_the_module_reference_follows_the_chapter_collapsed():
    """The chapter is the account and the docstrings are the reference: a
    stage page carries every module's docstring after the prose, each in
    its own collapsed block, so the reference is there without being read
    first."""
    pages = build()
    for page, _title, entries in build_docs.SOURCES:
        if not page.startswith("stages/"):
            continue
        text = pages[page]
        assert text.index("## Module reference") > text.index(
            build_docs.intro_of(page)[:80]), page
        reference = text[text.index("## Module reference"):]
        for rel, _pointer in entries:
            assert f"<summary><code>{rel}</code></summary>" in reference, rel
            assert docstring_of(rel) in reference, rel
        assert reference.count("<details>") == len(entries)
        assert reference.count("</details>") == len(entries)


def test_a_profile_with_a_schema_gets_a_profile_page():
    """Discovered like the contract pages: prose from `docs/_intros/`, then
    the parameters and their axes read off the published contract, never
    off the spec."""
    have = {p.parent.name for p in (ROOT / "profiles")
            .glob("*/extraction_schema.json")}
    pages = build()
    assert {page.split("/")[1][:-3] for page in pages
            if page.startswith("profiles/")} == have
    for name in sorted(have):
        page = pages[f"profiles/{name}.md"]
        harvest = json_at(build_docs._contract_rel(name), "harvest/$defs")
        parameters = sorted(key[len("tuple_"):] for key in harvest
                            if key.startswith("tuple_"))
        assert parameters
        for parameter in parameters:
            assert f"| `{parameter}` |" in page, (name, parameter)
        assert f"(../contract/{name}.md)" in page
    from build_docs import render_profile_page
    bare = render_profile_page("x", {"tuple_a": {
        "properties": {"value": {"type": "number"},
                       "year": {"type": "integer"}, "year_state": {},
                       "carrier": {"x-options": {"a": {}, "b": {}}},
                       "carrier_state": {}},
        "x-kg": {"node": "value"}}}, "## Intro")
    assert "| `a` | number | `carrier` (2 options), `year` (integer) | " \
           "`value` |" in bare

def test_the_profiles_page_says_what_a_profile_is_for():
    """The one page besides the stages that carries an introduction: what a
    profile is FOR is prose no module can state, so it lives in a file of
    its own and the page must carry it whole."""
    from build_docs import intro_of
    intro = intro_of("profiles.md")
    assert len(intro) > 200, len(intro)
    assert intro in build()["profiles.md"]
    # The renderer takes it as an argument and adds none of its own.
    assert intro not in render_profiles_page("x", ["kwp"])
    assert intro in render_profiles_page("x", ["kwp"], intro)


def test_every_command_the_hand_written_pages_print_can_be_run():
    """The hand-written pages are the ones nobody regenerates, so a flag
    renamed in a parser leaves them wrong with nothing to notice. Every
    module they tell a reader to run, and every flag they name, is checked
    against the parsers themselves."""
    import re
    flags = set()
    for path in sorted(ROOT.glob("docpipe/**/*.py")) + sorted(
            ROOT.glob("scripts/**/*.py")):
        flags |= set(re.findall(r'add_argument\(\s*"(--[\w-]+)"',
                                path.read_text(encoding="utf-8")))
    named_anywhere = set()
    for name in build_docs.HANDWRITTEN:
        page = (ROOT / "docs" / name).read_text(encoding="utf-8")
        for module in sorted(set(re.findall(r"python -m ([\w.]+)", page))):
            parts = module.split(".")
            path = ROOT.joinpath(*parts)
            assert (path / "__main__.py").is_file() or path.with_suffix(
                ".py").is_file(), (name, module)
        named = set(re.findall(r"`(--[\w-]+)", page))
        assert named <= flags, (name, sorted(named - flags))
        named_anywhere |= named
    assert named_anywhere, "no hand-written page names a flag at all"


def _prose_of(page: str) -> str:
    """A page without its fenced code, its block quotes (the prompts' own
    wording, in the model's language) and its collapsed blocks (docstrings
    and the spec's own notes, checked at their source)."""
    out, fenced, collapsed = [], False, False
    for line in page.splitlines():
        if line.startswith("```"):
            fenced = not fenced
            continue
        if line.startswith("<details>"):
            collapsed = True
        if not fenced and not collapsed and not line.startswith(">"):
            out.append(line)
        if line.startswith("</details>"):
            collapsed = False
    return "\n".join(out)


def _dashes(text: str) -> list:
    return [line for line in text.splitlines()
            if "\u2014" in line or "\u2013" in line or " -- " in line]


def test_no_page_uses_a_dash_as_punctuation():
    """The register of the site is settled: no em dash, no en dash and no
    double hyphen standing in for one, in the prose of any page, in any
    introduction, in any hand-written page and in any module docstring the
    site renders. Fenced code, quoted prompts and the collapsed blocks are
    left out here; the docstrings are checked at their source instead.

    The module pages of the API reference are left out: they carry the
    code's docstrings verbatim, and the register rule reaches a docstring
    only where it is applied at the source, which is the module docstrings
    the chapters render."""
    for page, text in sorted(build().items()):
        if build_docs.is_api_module(page):
            continue
        assert _dashes(_prose_of(text)) == [], page
    for path in sorted((ROOT / "docs" / "_intros").rglob("*.md")):
        assert _dashes(_prose_of(path.read_text(encoding="utf-8"))) == [], \
            path.name
    for name in build_docs.HANDWRITTEN:
        text = (ROOT / "docs" / name).read_text(encoding="utf-8")
        assert _dashes(_prose_of(text)) == [], name
    rels = {rel for _p, _t, entries in build_docs.SOURCES
            for rel, _pointer in entries}
    for rel in sorted(rels):
        assert _dashes(docstring_of(rel)) == [], rel


def test_the_docs_workflow_regenerates_on_develop_and_checks_everywhere_else():
    """On a push to develop the workflow renders the pages from the code and
    commits them back, so a docstring edit is never followed by a stale page.
    On a pull request and on a tag the checked-in pages have to be the fresh
    render, checked BEFORE anything is rendered or the check is vacuous.
    Sphinx runs either way with warnings as errors, and nothing is published
    from here: hosting and versions are Read the Docs'."""
    text = (ROOT / ".github" / "workflows" / "docs.yml").read_text(encoding="utf-8")
    assert "branches: [develop]" in text and 'tags: ["v*"]' in text
    assert "python scripts/build_docs.py --check" in text
    assert "python scripts/build_docs.py --out docs" in text
    assert text.index("build_docs.py --check") < text.index("build_docs.py --out docs")
    assert "python -m sphinx -W" in text
    assert "contents: write" in text
    # The check is for every ref but develop; the commit is for develop only,
    # to develop only, and never on a pull request.
    assert "if: github.ref != 'refs/heads/develop'" in text
    assert ("if: github.ref == 'refs/heads/develop' "
            "&& github.event_name != 'pull_request'") in text
    assert "git push origin HEAD:develop" in text
    assert text.count("git push") == 1
    assert "concurrency:" in text and "cancel-in-progress: false" in text
    for forbidden in ("gh-pages", "pages-deploy", "--versions"):
        assert forbidden not in text, forbidden


def test_the_site_turns_every_readme_link_into_an_index_link():
    """The repository index and the site's toctree page are two files, and
    the pages link the first. Without the rewrite the site build reports one
    missing cross-reference per page, and warnings are errors there."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("docs_conf", ROOT / "docs" / "conf.py")
    conf = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(conf)
    source = ["[Back to the index](README.md) and [up](../README.md#pages) "
              "and [kept](../README.md.bak) and [other](README.txt)"]
    conf._site_links(None, "stages/app", source)
    assert source[0] == ("[Back to the index](index.md) and [up](../index.md#pages) "
                         "and [kept](../README.md.bak) and [other](README.txt)")
    # Every generated page carries the link the rewrite is for.
    for rel, text in build().items():
        if rel not in ("README.md", "index.md"):
            assert "](README.md)" in text or "](../README.md)" in text, rel
    # And Sphinx is told to run it on every source it reads.
    connected = []

    class App:
        def connect(self, event, handler):
            connected.append((event, handler))

    conf.setup(App())
    assert connected == [("source-read", conf._site_links)]


# ---------------------------------------------------------------------------
# The API reference
# ---------------------------------------------------------------------------
_DEMO = '''"""demo.py: Reads rows.

One line of <name>.jsonl per row; ``<b>`` stays, `<c>` stays, a lone ` then <d>.

Usage:

    demo.read(path) < 2
"""
from dataclasses import dataclass

__all__ = ["Row"]
__all__ += ["read"]


@dataclass
class Row:
    """One row."""
    label: str
    # The cell the value sits in.
    cell: tuple = ()
    span: dict = {
        "k": 1,  # not the note
    }

    def __init__(self, label: str):  # a note on the header
        # not the signature
        self.label = label

    def quote(self, text: str,
              limit: int = 0) -> str:
        """The row's own quote."""
        return text

    def _hidden(self):
        return None


def read(path, *, limit: int = 0) -> list:
    """Every row of the file.

    # not a heading
    """
    return []


def _private():
    return 1


def unlisted():
    return 2
'''


def test_a_module_page_names_every_public_name_and_nothing_private():
    """The reference is the code's public surface: every public function,
    class and method with its signature as written, no private name, a
    dataclass field with the comment above it, and a docstring rendered as
    the Markdown it is written in, with `<name>` kept as text rather than
    swallowed as a tag and a `#` kept as a character rather than a heading."""
    from build_docs import (api_page, dotted, markdown_safe, parse_api,
                            render_api_page)
    assert dotted("docpipe/extraction/pipeline.py") == "docpipe.extraction.pipeline"
    assert dotted("docpipe/extraction/__init__.py") == "docpipe.extraction"
    # Outside code, a tag-like `<` and a leading `#` are escaped; inside a
    # code span or an indented code block they are left as written.
    assert markdown_safe("<name>.jsonl and `<b>`") == "\\<name>.jsonl and `<b>`"
    assert markdown_safe("Usage:\n\n    x = a < b\n    # kept") \
        == "Usage:\n\n    x = a < b\n    # kept"
    module = parse_api(_DEMO, "docpipe/demo.py")
    page = render_api_page(module, {"docpipe.demo"})
    assert page.startswith("# docpipe.demo")
    for heading in ("### Row", "#### Row.\\_\\_init\\_\\_", "#### Row.quote",
                    "### read"):
        assert heading in page, heading
    assert "_hidden" not in page and "_private" not in page
    assert "unlisted" not in page, "__all__ decides what is public"
    assert "def read(path, *, limit: int = 0) -> list" in page
    assert "@dataclass\nclass Row" in page
    # The header ends at its colon: a comment on the header line, and a
    # comment line between the header and the body, are not the signature.
    assert "def __init__(self, label: str)\n```" in page
    assert "not the signature" not in page and "a note on the header" not in page
    assert "def quote(self, text: str,\n          limit: int = 0) -> str" in page
    assert "- `cell: tuple = ()`: The cell the value sits in." in page
    assert ": not the note" not in page
    assert ("One line of \\<name>.jsonl per row; ``<b>`` stays, `<c>` stays, "
            "a lone ` then \\<d>.") in page
    assert "    demo.read(path) < 2" in page, "indented code is left alone"
    assert "\\# not a heading" in page
    assert "](../README.md)" in page
    # A package's `__all__` decides what it exports, and the page says where
    # each exported name is defined.
    package = parse_api('"""pkg."""\nfrom .rows import read\n'
                        '__all__ = ["read"]\n', "docpipe/pkg/__init__.py")
    assert package["name"] == "docpipe.pkg"
    assert package["exports"] == [("read", "docpipe.pkg.rows")]
    assert ("- `read` from [docpipe.pkg.rows](docpipe.pkg.rows.md)"
            in render_api_page(package, {"docpipe.pkg.rows"}))
    # A plain module's relative import is relative to ITS package.
    plain = parse_api('"""m."""\nfrom .other import thing\n'
                      '__all__ = ("thing",)\n', "docpipe/pkg/mod.py")
    assert plain["exports"] == [("thing", "docpipe.pkg.other")]
    # Inside a list item, four spaces continue the item and are prose.
    assert markdown_safe("- item\n\n    more <name> text") \
        == "- item\n\n    more \\<name> text"
    # Over the real tree: a module with anything to publish has a page, an
    # empty `__init__.py` has none.
    pages = build()
    for rel in build_docs._api_modules():
        module = build_docs.module_api(rel)
        assert (api_page(rel) in pages) == build_docs._publishes(module), rel


def test_the_reference_index_names_every_module_page_once():
    """The module pages are not on the front page, which would be a list of
    a hundred lines; they are reached through the reference's own index,
    which names each of them once in its lists and once in its toctrees, and
    the front page names that index."""
    from build_docs import is_api_module, render_api_index
    pages = build()
    modules = sorted(page[len("api/"):-3] for page in pages
                     if is_api_module(page))
    # The index is the intro, then one list and one hidden toctree per
    # package, the package's own page first.
    demo = {"docpipe/demo/__init__.py": {"rel": "docpipe/demo/__init__.py",
                                         "name": "docpipe.demo", "doc": "Demo.",
                                         "functions": [], "classes": [],
                                         "exports": []},
            "docpipe/demo/rows.py": {"rel": "docpipe/demo/rows.py",
                                     "name": "docpipe.demo.rows",
                                     "doc": "rows.py: Reads rows. More.",
                                     "functions": [{"name": "read"}],
                                     "classes": [], "exports": []}}
    index = render_api_index(demo, "What the reference is for.")
    assert "What the reference is for." in index
    assert "- [docpipe.demo.rows](docpipe.demo.rows.md): Reads rows. (1 function)" in index
    assert _toctree_entries(index) == ["docpipe.demo", "docpipe.demo.rows"]
    assert ":hidden:" in index
    assert len(modules) > 100, "the reference is nearly empty"
    listed = _toctree_entries(pages[build_docs.API_INDEX])
    assert sorted(listed) == modules
    assert len(listed) == len(set(listed)), "a module is named twice"
    linked = [part.split(")")[0] for part
              in pages[build_docs.API_INDEX].split("](")[1:]]
    assert sorted(link[:-3] for link in linked
                  if link.endswith(".md") and "/" not in link) == modules
    assert "api/index" in _toctree_entries(pages["index.md"])
    assert "](api/index.md)" in pages["README.md"]
    for page in modules:
        assert f"api/{page}" not in _toctree_entries(pages["index.md"])


def test_a_removed_module_leaves_no_page_behind(tmp_path):
    """A module that is renamed or deleted has no page in a fresh render,
    and the page the last render wrote would stay on disk: Sphinx builds it
    outside every toctree, which is a warning, which is a failed site."""
    pages = build()
    write(tmp_path, pages)
    stale = tmp_path / "api" / "docpipe.gone.md"
    stale.write_text("# docpipe.gone\n", encoding="utf-8")
    write(tmp_path, pages)
    assert not stale.exists()
    assert (tmp_path / "api" / "index.md").is_file()
    assert (tmp_path / "api" / "docpipe.artifacts.md").is_file()
