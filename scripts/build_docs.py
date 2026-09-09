#!/usr/bin/env python3
"""Generate the documentation pages from the sources they describe.

A hand-written page is a second copy of something, and the copy is the one
that goes stale: it says what a module did when somebody last looked. Every
page under `docs/` except one is therefore rendered from what it documents --
module docstrings, the checked-in extraction schemas, the artifact constants --
and `--check` fails the test suite the moment the checked-in page and a fresh
render disagree.

What that buys, concretely: renaming a package, emptying a docstring, adding a
state to `fields.py` without regenerating a schema, or adding a profile with no
contract page all turn into a red test instead of a paragraph nobody re-reads.

Two rules hold the thing together.

**One door.** `read_source` is the only function that opens a file, and it
refuses anything outside `docpipe/`, `profiles/`, `scripts/` and `docs/`, and
anything under `data/`. The corpus is not in this repository, but the plans it
is built from are not public either, and a generator that can read a path can
publish it. A test parses THIS file and asserts no other read exists.

**Build, then write.** `build()` renders every page into memory and writes
nothing; `write()` is the only writer and refuses a key that escapes its output
directory. So `--check` cannot mutate the tree it is checking, and a source
that has moved fails the whole build instead of leaving half a site.

Usage:
    python scripts/build_docs.py --out docs      # rewrite the pages
    python scripts/build_docs.py --check         # fail on drift
Exit codes:
    0  the checked-in pages are a fresh render
    1  a page has drifted, a page is orphaned, or a source has moved

Author: Felix Vossel
"""
from __future__ import annotations

import argparse
import ast
import difflib
import io
import json
import re
import pathlib
import sys
import tokenize

ROOT = pathlib.Path(__file__).resolve().parent.parent
PAGES_DIR = ROOT / "docs"

# Where a documented source may live. Not a convenience: `data/` holds the
# corpus and its database, and a page that could quote a plan would publish
# one.
ALLOWED_ROOTS = ("docpipe", "profiles", "scripts", "docs")

# The one page nobody generates, because it says what the parts are FOR and no
# source carries that. It is a source here, not an output: checked where it
# lives, linked from the index, and never written.
HANDWRITTEN = ("pipeline.md",)

# Where a page's introduction lives: one Markdown file per generated page,
# under `docs/_intros/<page>`. Prose, in a file, rather than a string in this
# script -- it is edited like prose, it goes through the one door like every
# other source, and `resolve` fails when a page has none. What belongs in it
# is the connective tissue no module docstring can carry: what the stage is
# FOR, what it hands to what, and what breaks if it is skipped.
INTRO_DIR = "docs/_intros"

NEWLINE = chr(10)


class SourceMoved(Exception):
    """A page's source is gone, empty, or no longer carries what it renders."""

    def __init__(self, page: str, rel: str, why: str):
        super().__init__(f"{page}: {rel} — {why}")
        self.page, self.rel, self.why = page, rel, why


# ---------------------------------------------------------------------------
# The one door
# ---------------------------------------------------------------------------
def read_source(rel: str) -> str:
    """The text of one documented file. The only read in this module.

    Returns text and not a path on purpose: a caller holding a path would have
    to open it, and the second door is how the first one stops meaning
    anything.
    """
    if rel.split("/")[0] not in ALLOWED_ROOTS:
        raise SourceMoved(rel, rel, f"outside {', '.join(ALLOWED_ROOTS)}")
    path = (ROOT / rel).resolve()
    if ROOT not in path.parents and path != ROOT:
        raise SourceMoved(rel, rel, "outside the repository")
    if (ROOT / "data") in path.parents:
        raise SourceMoved(rel, rel, "under data/, which holds the corpus")
    if not path.is_file():
        raise SourceMoved(rel, rel, "is not a file")
    return path.read_text(encoding="utf-8")


def _profile_names() -> tuple:
    """The profiles that publish a contract, by directory name.

    Enumerates and does not read: the schema itself goes through the door like
    everything else.
    """
    out = []
    for entry in sorted((ROOT / "profiles").iterdir()):
        if entry.is_dir() and (entry / "extraction_schema.json").is_file():
            out.append(entry.name)
    return tuple(out)


# ---------------------------------------------------------------------------
# Reading the sources
# ---------------------------------------------------------------------------
def docstring_of(rel: str) -> str:
    """One module's docstring, or `SourceMoved` if it has none."""
    text = read_source(rel)
    try:
        doc = ast.get_docstring(ast.parse(text))
    except SyntaxError as exc:
        raise SourceMoved(rel, rel, f"does not parse: {exc}")
    if not (doc or "").strip():
        raise SourceMoved(rel, rel, "has no module docstring to render")
    return doc.strip()


def json_at(rel: str, pointer: str):
    """The value at a `/`-separated pointer, or `SourceMoved`."""
    node = json.loads(read_source(rel))
    for step in [p for p in pointer.split("/") if p]:
        if not isinstance(node, dict) or step not in node:
            raise SourceMoved(rel, rel, f"has no {pointer}")
        node = node[step]
    return node


def constants_of(rel: str) -> tuple:
    """((name, value, trailing comment), ...) for one module's string names.

    Two passes over one string, because neither tool alone can do it: `ast`
    keeps no comments, and `ast.literal_eval` raises on an f-string -- and
    seven of the nine artifact names ARE f-strings built from the two before
    them. The comment is what says which stage writes the file, which is the
    only reason the page is worth generating.
    """
    text = read_source(rel)
    comments = {t.start[0]: t.string.lstrip("# ").strip()
                for t in tokenize.generate_tokens(io.StringIO(text).readline)
                if t.type == tokenize.COMMENT}
    seen, out = {}, []
    for node in ast.parse(text).body:
        if not isinstance(node, ast.Assign):
            continue
        if not isinstance(node.targets[0], ast.Name):
            continue
        value = node.value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            resolved = value.value
        elif isinstance(value, ast.JoinedStr):
            parts = []
            for piece in value.values:
                if isinstance(piece, ast.Constant):
                    parts.append(str(piece.value))
                elif (isinstance(piece, ast.FormattedValue)
                      and isinstance(piece.value, ast.Name)
                      and piece.value.id in seen):
                    parts.append(seen[piece.value.id])
                else:
                    raise SourceMoved(rel, rel,
                                      "constant is no longer a plain f-string")
            resolved = "".join(parts)
        else:
            continue
        seen[node.targets[0].id] = resolved
        note = ""
        # The whole assignment, so a comment on the continuation line of a
        # two-line assignment is still its comment.
        for line in range(node.lineno, (node.end_lineno or node.lineno) + 1):
            note = comments.get(line, note)
        out.append((node.targets[0].id, resolved, note))
    return tuple(out)


def _string_constants(rel: str) -> dict:
    """{value: name} for a module's plain string assignments, first wins."""
    out: dict = {}
    for node in ast.parse(read_source(rel)).body:
        if not isinstance(node, ast.Assign):
            continue
        target = node.targets[0]
        value = node.value
        if (isinstance(target, ast.Name) and isinstance(value, ast.Constant)
                and isinstance(value.value, str)
                and value.value not in out):
            out[value.value] = target.id
    return out


def _literal(rel: str, name: str):
    """One module-level literal by name, or `SourceMoved`.

    A name used as a key or a value inside it is resolved from the module's
    own string constants first: `FLAG_REASONS` is written `{REVIEW_DISAGREE:
    "review:disagree", ...}`, which is a literal to a reader and a `Name` to
    `ast.literal_eval`.
    """
    text = read_source(rel)
    bound = {n.targets[0].id: n.value.value for n in ast.parse(text).body
             if isinstance(n, ast.Assign)
             and isinstance(n.targets[0], ast.Name)
             and isinstance(n.value, ast.Constant)
             and isinstance(n.value.value, str)}

    def _value_of(node):
        if isinstance(node, ast.Name) and node.id in bound:
            return bound[node.id]
        return ast.literal_eval(node)

    for node in ast.parse(text).body:
        if not (isinstance(node, ast.Assign)
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == name):
            continue
        try:
            if isinstance(node.value, ast.Dict):
                return {_value_of(k): _value_of(v)
                        for k, v in zip(node.value.keys, node.value.values)}
            return ast.literal_eval(node.value)
        except ValueError:
            raise SourceMoved(rel, rel, f"{name} is no longer a literal")
    raise SourceMoved(rel, rel, f"no longer defines {name}")


def _contract_rel(profile: str) -> str:
    return f"profiles/{profile}/extraction_schema.json"


def states_table() -> tuple:
    """((constant name, value, gloss), ...) in the schema's own enum order.

    The rule is an intersection and it has to be: `fields.py` carries twelve
    module-level strings and only seven of them are states. Published by
    "every string constant" the page would offer `out:unstated`, which is an
    ANSWER a model may give and not a state a coordinate can be in.
    """
    rel = "docpipe/extraction/fields.py"
    by_value = _string_constants(rel)
    state = json_at(_contract_rel(_profile_names()[0]), "harvest/$defs/state")
    rows = []
    for value in state["enum"]:
        if value not in by_value:
            raise SourceMoved("contract/states.md", rel,
                              f"nothing is named {value!r} any more")
        rows.append((by_value[value], value, state["x-doc"][value]))
    return tuple(rows)


def trust_table() -> tuple:
    """((level, gloss), ...), the reason patterns, the flag reasons, the
    marks of a trust line in their order, and the reason separator.

    The levels and the reason vocabulary are read from the published schema
    rather than from `trust.py` alone, because the schema is the copy an
    existing test keeps equal to the code -- so the page inherits that check
    instead of adding a second one.
    """
    rel = _contract_rel(_profile_names()[0])
    levels = json_at(rel, "harvest/$defs/summary/properties/levels/x-doc")
    reasons = json_at(
        rel, "harvest/$defs/summary/properties/reasons/propertyNames")
    flags = _literal("docpipe/extraction/trust.py", "FLAG_REASONS")
    marks = _literal("docpipe/extraction/trust.py", "MARKS")
    join = _literal("docpipe/extraction/trust.py", "REASON_JOIN")
    ordered = tuple((level, levels[level]) for level in sorted(levels))
    return (ordered, tuple(p["pattern"] for p in reasons["anyOf"]), flags,
            tuple(marks), str(join))


# ---------------------------------------------------------------------------
# The manifest
# ---------------------------------------------------------------------------
def _stage(page: str, title: str, *rels) -> tuple:
    return (page, title, tuple((rel, None) for rel in rels))


SOURCES = (
    _stage("stages/fileprocessing.md", "1. Getting the documents in",
           "docpipe/ingest/__init__.py", "docpipe/ingest/pipeline.py",
           "docpipe/ingest/fetch.py", "docpipe/ingest/pdf_quality.py",
           "docpipe/ingest/models.py",
           "scripts/fileprocessing/__init__.py",
           "scripts/fileprocessing/pipeline.py"),
    _stage("stages/preprocessing.md", "2-3. Reading the page",
           "docpipe/preprocessing/pipeline.py",
           "docpipe/preprocessing/stage1_extract.py",
           "docpipe/preprocessing/stage2_layout.py",
           "docpipe/preprocessing/stage3_structure.py",
           "docpipe/preprocessing/page_text_fallback.py",
           "docpipe/preprocessing/columns.py"),
    _stage("stages/refinement.md", "4. Repairing the text",
           "docpipe/refinement/pipeline.py", "docpipe/refinement/refine.py",
           "docpipe/refinement/split.py",
           "docpipe/refinement/corrections.py"),
    _stage("stages/visuals.md", "5. Reading the pictures",
           "docpipe/visuals/__init__.py", "docpipe/visuals/pipeline.py",
           "docpipe/visuals/vision.py", "docpipe/visuals/qa.py",
           "docpipe/visuals/process.py"),
    _stage("stages/chunking.md", "6. Chunking, embedding, indexing",
           "docpipe/chunking/__init__.py", "docpipe/chunking/pipeline.py",
           "docpipe/chunking/merge.py", "docpipe/chunking/database.py",
           "docpipe/chunking/chunking.py", "docpipe/chunking/embedding.py"),
    _stage("stages/extraction.md", "7. Reading the values out",
           "docpipe/extraction/__init__.py", "docpipe/extraction/pipeline.py",
           "docpipe/extraction/runner.py", "docpipe/extraction/spec.py",
           "docpipe/extraction/fields.py", "docpipe/extraction/queries.py",
           "docpipe/extraction/verify.py", "docpipe/extraction/trust.py",
           "docpipe/extraction/schema.py", "docpipe/extraction/trace.py",
           "docpipe/extraction/recheck.py", "docpipe/extraction/remap.py",
           "docpipe/extraction/review.py", "docpipe/extraction/topup.py"),
    _stage("stages/graph.md", "8. The knowledge graph",
           "docpipe/extraction/serialize.py", "docpipe/ontology.py"),
    _stage("stages/embedding.md", "The embedders",
           "docpipe/embedding/__init__.py", "docpipe/embedding/local.py",
           "docpipe/embedding/api.py"),
    _stage("stages/inference.md", "Asking the corpus",
           "docpipe/inference/__init__.py", "docpipe/inference/answer.py",
           "docpipe/inference/catalog.py", "docpipe/inference/faiss_store.py",
           "docpipe/inference/pdf_locate.py",
           "docpipe/inference/code_exec.py",
           "docpipe/inference/kg_route.py"),
    _stage("stages/app.md", "The chat over the corpus",
           "scripts/inference_app/__init__.py", "scripts/inference_app/app.py",
           "scripts/inference_app/config.py",
           "scripts/inference_app/pdf_link.py",
           "scripts/inference_app/sandbox_service.py"),
    _stage("stages/store.md", "The database",
           "docpipe/store/__init__.py", "docpipe/store/schema.py",
           "docpipe/store/documents.py"),
    _stage("stages/core.md", "The parts every stage uses",
           "docpipe/artifacts.py", "docpipe/prompts.py", "docpipe/profile.py",
           "docpipe/llm_preflight.py", "docpipe/captions.py"),
    ("artifacts.md", "What each stage leaves behind",
     (("docpipe/artifacts.py", None),)),
    ("profiles.md", "Profiles", (("docpipe/profile.py", None),)),
    ("contract/states.md", "What a coordinate's state means",
     (("docpipe/extraction/fields.py", None),)),
    ("contract/trust.md", "How much of a value the run can stand behind",
     (("docpipe/extraction/trust.py", None),)),
)

# The order the site's table of contents reads in. Named here because it is
# the pipeline's order and nothing in the tree carries it: the packages are
# named after what they do, not after when they run.
ORDER = (
    "pipeline.md",
    "stages/fileprocessing.md", "stages/preprocessing.md",
    "stages/refinement.md", "stages/visuals.md", "stages/chunking.md",
    "stages/extraction.md", "stages/graph.md",
    "stages/inference.md", "stages/app.md",
    "stages/embedding.md", "stages/store.md", "stages/core.md",
    "artifacts.md", "profiles.md",
    "contract/states.md", "contract/trust.md",
)


def _contract_sources() -> tuple:
    """One entry per profile that publishes a schema, discovered, not listed."""
    return tuple(
        (f"contract/{name}.md", f"The harvest contract: {name}",
         ((_contract_rel(name), "harvest/$defs"),
          (_contract_rel(name), "stamp"),
          (_contract_rel(name), "trace")))
        for name in _profile_names())


def resolve(sources) -> dict:
    """{page: [(rel, value)]} — every source of every page, or `SourceMoved`.

    Run over the WHOLE manifest before anything is rendered, so a source that
    has moved fails the build instead of leaving a site whose other half is
    fresh.
    """
    out: dict = {}
    for page, _title, entries in sources:
        got = []
        for rel, pointer in entries:
            try:
                value = (json_at(rel, pointer) if pointer
                         else (docstring_of(rel) if rel.endswith(".py")
                               else read_source(rel)))
            except SourceMoved as exc:
                raise SourceMoved(page, rel, exc.why)
            got.append((rel, value))
        out[page] = got
    for name in HANDWRITTEN:
        if not (PAGES_DIR / name).is_file():
            raise SourceMoved(name, f"docs/{name}",
                              "the hand-written page is missing")
    for page in out:
        if not page.startswith("stages/"):
            continue
        if not (PAGES_DIR / "_intros" / page).is_file():
            raise SourceMoved(page, f"{INTRO_DIR}/{page}",
                              "a stage page has no introduction, so it would "
                              "publish a list of docstrings and no order")
    for page in ORDER:
        if page not in out and page not in HANDWRITTEN:
            raise SourceMoved(page, "scripts/build_docs.py",
                              "is in ORDER and in no manifest entry")
    return out


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
def _lede(doc: str) -> str:
    """The first sentence of a docstring's first paragraph, as one line.

    A sentence and not a line: module docstrings wrap at 79 columns, and the
    first line alone stops mid-thought more often than not.
    """
    lines: list = []
    for line in doc.splitlines():
        if not line.strip():
            if lines:
                break
            continue
        lines.append(line.strip())
    text = " ".join(lines)
    found = re.match(r"(.+?[.!?])(\s|$)", text)
    return (found.group(1) if found else text).strip()


def _up(page: str) -> str:
    return "../" * page.count("/")


def intro_of(page: str) -> str:
    """The page's own introduction, or "" when it has none."""
    try:
        return read_source(f"{INTRO_DIR}/{page}").strip()
    except SourceMoved:
        return ""


def render_stage_page(page: str, parts: list) -> str:
    """The page's introduction, then one section per module.

    The introduction is prose somebody wrote; everything under it is the
    module's own docstring, verbatim. Two layers rather than one, because they
    go stale differently: a docstring is wrong the moment its module changes
    and is checked by being generated, while "this runs before that" is not in
    any module and cannot be.
    """
    title = next(t for p, t, _ in SOURCES if p == page)
    out = [f"# {title}", ""]
    intro = intro_of(page)
    if intro:
        out += [intro, ""]
    out += ["## The modules", "",
            "Verbatim from the module docstrings, generated by "
            "`scripts/build_docs.py`. Edit the docstring, not this page.", ""]
    for rel, doc in parts:
        out += [f"### `{rel}`", "", doc, ""]
    out += [f"[Back to the index]({_up(page)}README.md)", ""]
    return NEWLINE.join(out)


def _option_lines(options: dict) -> list:
    out = []
    for label in sorted(options):
        entry = options[label] or {}
        line = f"- **{label}** → `{entry.get('uri', '')}`"
        meaning = entry.get("meaning")
        if meaning:
            line += f" — {meaning}"
        out.append(line)
        spellings = [s for s in (entry.get("spellings") or []) if s]
        if spellings:
            out.append(f"  - also written: {', '.join(spellings)}")
    return out


def _kg_lines(kg: dict) -> list:
    out = []
    for key in sorted(kg):
        value = kg[key]
        if key == "note":
            continue
        out.append(f"- `{key}`: `{value}`")
    note = kg.get("note")
    if note:
        out += ["", "<details><summary>Why</summary>", "", str(note), "",
                "</details>"]
    return out


def render_contract_page(profile: str, schema: dict, stamp=None,
                         trace=None) -> str:
    """One section per record kind, straight out of the published schema,
    then the stamp beside the harvest file and the trace beside both."""
    harvest = schema
    out = [f"# The harvest contract: {profile}", "",
           "Generated from `profiles/%s/extraction_schema.json` by "
           "`scripts/build_docs.py`, which is itself generated from the "
           "profile's `extraction_spec.json` by "
           "`docpipe/extraction/schema.py`. Edit neither: change the spec and "
           "regenerate." % profile,
           "",
           "One JSON object per line of a harvest file. Every line is one of "
           "the kinds below and nothing else, and each of them is closed "
           "(`additionalProperties: false`) — a new record kind costs a "
           "branch in `docpipe/extraction/schema.py`, a regeneration of both "
           "checked-in schemas, and a branch in `read_harvest` in "
           "`scripts/harvest_compare.py`.", ""]
    for name in sorted(harvest):
        if name in ("state", "provenance"):
            continue
        body = harvest[name]
        if not isinstance(body, dict):
            continue
        heading = name[len("tuple_"):] if name.startswith("tuple_") else name
        out += [f"## `{heading}`", ""]
        if body.get("description"):
            out += [str(body["description"]), ""]
        kg = body.get("x-kg")
        if isinstance(kg, dict):
            out += ["How the row becomes a node:", ""] + _kg_lines(kg) + [""]
        for key in sorted(body.get("properties") or {}):
            prop = body["properties"][key] or {}
            out += [f"### `{key}`", ""]
            if prop.get("description"):
                out += [str(prop["description"]), ""]
            question = prop.get("x-question")
            if question:
                # The prompt's own wording, in the language the model was
                # asked in. Not translated: a translated question documents a
                # request nobody made.
                out += ["The prompt's own wording:", "",
                        f"> {question}", ""]
            options = prop.get("x-options")
            if isinstance(options, dict) and options:
                out += ["<details><summary>What it may answer "
                        f"({len(options)})</summary>", ""]
                out += _option_lines(options) + ["", "</details>", ""]
            prop_kg = prop.get("x-kg")
            if isinstance(prop_kg, dict):
                out += _kg_lines(prop_kg) + [""]
        if body.get("allOf"):
            out += ["A coordinate is `null` unless its `<axis>_state` says it "
                    "was read or derived — that is what the `allOf` branches "
                    "encode, one per coordinate.", ""]
    out += _stamp_lines(stamp or {}) + _trace_lines(trace or {})
    out += ["[Back to the index](../README.md)", ""]
    return NEWLINE.join(out)


def _stamp_lines(stamp: dict) -> list:
    """The resume stamp: one `<name>.stamp.json` beside each harvest file."""
    if not stamp:
        return []
    out = ["## The stamp", "",
           "One `<document>.stamp.json` beside each harvest file, closed like "
           "the records (`additionalProperties: false`).", ""]
    if stamp.get("description"):
        out += [str(stamp["description"]), ""]
    out += ["| key | what it records |", "|---|---|"]
    # A pipe splits a table cell even inside a code span.
    cell = lambda text: str(text).replace("|", chr(92) + "|")
    for key in sorted(stamp.get("properties") or {}):
        gloss = (stamp["properties"][key] or {}).get("description", "")
        out.append(f"| `{cell(key)}` | {cell(gloss)} |")
    for pattern in sorted(stamp.get("patternProperties") or {}):
        gloss = (stamp["patternProperties"][pattern] or {}).get(
            "description", "")
        out.append(f"| `{cell(pattern)}` | {cell(gloss)} |")
    return out + [""]


def _trace_lines(trace: dict) -> list:
    """The trace: one event per line, one record kind per `oneOf` branch."""
    kinds = [branch for branch in (trace.get("oneOf") or [])
             if isinstance(branch, dict)]
    if not kinds:
        return []
    out = ["## The trace", ""]
    if trace.get("description"):
        out += [str(trace["description"]), ""]
    out += [f"{len(kinds)} record kinds, told apart by `t`:", ""]
    for branch in kinds:
        props = branch.get("properties") or {}
        name = (props.get("t") or {}).get("const", "?")
        fields = ", ".join(f"`{k}`" for k in sorted(props) if k != "t")
        out.append(f"- `{name}`: {fields}")
    return out + [""]


def render_states_page(rows) -> str:
    out = ["# What a coordinate's state means", "",
           "Generated from `docpipe/extraction/fields.py` and the published "
           "schema by `scripts/build_docs.py`.", "",
           "Every coordinate of every accepted value carries one of these, "
           "always. The distinction they exist for is the one between a "
           "finding about the document and a finding about the run: \"the "
           "plan does not say it\" and \"we stopped looking\" are not the "
           "same fact, and an empty cell says neither.", "",
           "| constant | value | what it says |", "|---|---|---|"]
    for name, value, gloss in rows:
        out.append(f"| `{name}` | `{value}` | {gloss} |")
    out += ["", "[Back to the index](../README.md)", ""]
    return NEWLINE.join(out)


def render_trust_page(levels, reasons, flag_reasons, marks, join,
                      doc: str) -> str:
    out = ["# How much of a value the run can stand behind", "",
           "Generated from `docpipe/extraction/trust.py` and the published "
           "schema by `scripts/build_docs.py`.", "", doc, "",
           "## The levels", "", "| level | what it says |", "|---|---|"]
    for level, gloss in levels:
        out.append(f"| `{level}` | {gloss} |")
    out += ["", "## The reasons", "",
            "A closed list, because a reason nobody can enumerate is a reason "
            "nobody can count. The published schema accepts exactly these "
            "shapes:", ""]
    out += [f"- `{pattern}`" for pattern in reasons]
    out += ["", "## Reasons that come off a flag", "",
            "| flag on the row | reason it becomes |", "|---|---|"]
    for flag in sorted(flag_reasons):
        out.append(f"| `{flag}` | `{flag_reasons[flag]}` |")
    out += ["", "## The marks of a trust line", "",
            "The line the serializer writes above a value node is made of "
            "these marks, in this order, each worded by the profile in its "
            "own language (`TRUST_PROSE`) and only where it applies:", ""]
    out += [f"{n}. `{mark}`" for n, mark in enumerate(marks, 1)]
    out += ["", f"Inside the `reasons` mark the reasons are joined with "
            f"`{join}`; the reason tokens themselves are never translated.",
            "", "[Back to the index](../README.md)", ""]
    return NEWLINE.join(out)


def render_artifacts_page(constants, doc: str) -> str:
    out = ["# What each stage leaves behind", "",
           "Generated from `docpipe/artifacts.py` by "
           "`scripts/build_docs.py`: the names below and the stage against "
           "each are that module's own constants and its own comments.", "",
           doc, "", "## Directories", "", "| name | path |", "|---|---|"]
    files = []
    for name, value, note in constants:
        if name.startswith("DIR_"):
            out.append(f"| `{name}` | `{value}` |")
        else:
            files.append((name, value, note))
    out += ["", "## Files", "", "| name | path | written by |", "|---|---|---|"]
    for name, value, note in files:
        out.append(f"| `{name}` | `{value}` | {note or '—'} |")
    out += ["", "[Back to the index](README.md)", ""]
    return NEWLINE.join(out)


def render_profiles_page(doc: str, profiles, intro: str = "") -> str:
    """How to write a profile, then what `profile.py` itself says.

    The introduction is the part that matters to somebody adding a third
    profile, and it is prose in `docs/_intros/profiles.md` rather than a
    docstring: the contract is spread over `profile.py`, the two existing
    profiles and the architecture tests, and no single module can state it.
    """
    out = ["# Profiles", ""]
    if intro:
        out += [intro, ""]
    out += ["## What `docpipe/profile.py` says", "",
            "Verbatim from the module docstring, generated by "
            "`scripts/build_docs.py`.", "", doc, "",
            "## The profiles in this repository", ""]
    for name in profiles:
        out.append(f"- **{name}** — [the harvest contract]"
                   f"(contract/{name}.md)")
    out += ["", "[Back to the index](README.md)", ""]
    return NEWLINE.join(out)


def render_toctree(pages) -> str:
    """`index.md` — the site's own front page, and the only toctree.

    Sphinx needs one document that names every other, in the order a reader
    should meet them. That order is the pipeline's, which is in no file: the
    packages are named after what they do, not after when they run.
    """
    out = ["# The pipeline, end to end", "",
           "This is generated documentation. Every page but "
           "`pipeline.md` is rendered from the code it describes by "
           "`scripts/build_docs.py`, and the test suite fails when a page and "
           "its source disagree.", "",
           "```{toctree}", ":maxdepth: 2", ":caption: Contents", ""]
    listed = [page for page in ORDER
              if page in pages or page in HANDWRITTEN]
    out += [page[:-3] for page in listed]
    rest = sorted(set(pages) - set(listed) - {"README.md", "index.md"})
    out += [page[:-3] for page in rest]
    out += ["```", ""]
    return NEWLINE.join(out)


def render_index(pages, ledes=None) -> str:
    out = ["# Documentation", "",
           "Every page here except `pipeline.md` is generated from the code "
           "it describes by `scripts/build_docs.py`, and "
           "`tests/test_docs_build.py` fails when a checked-in page and a "
           "fresh render disagree. Edit the source, then run:", "",
           "```", "python scripts/build_docs.py --out docs", "```", "",
           "## Pages", "",
           f"- [How the parts fit together](pipeline.md) — hand-written"]
    for page in sorted(pages):
        if page == "README.md":
            continue
        lede = (ledes or {}).get(page) or ""
        out.append(f"- [{pages[page]}]({page})"
                   + (f": {lede}" if lede else ""))
    out.append("")
    return NEWLINE.join(out)


# ---------------------------------------------------------------------------
# Build and write
# ---------------------------------------------------------------------------
def build() -> dict:
    """{page relpath: text}. Renders everything, writes nothing."""
    profiles = _profile_names()
    manifest = SOURCES + _contract_sources()
    resolved = resolve(manifest)
    titles = {page: title for page, title, _ in manifest}
    pages: dict = {}
    for page, _title, _entries in manifest:
        parts = resolved[page]
        if page.startswith("stages/"):
            pages[page] = render_stage_page(page, parts)
        elif page == "artifacts.md":
            pages[page] = render_artifacts_page(
                constants_of("docpipe/artifacts.py"), parts[0][1])
        elif page == "profiles.md":
            pages[page] = render_profiles_page(parts[0][1], profiles,
                                               intro_of(page))
        elif page == "contract/states.md":
            pages[page] = render_states_page(states_table())
        elif page == "contract/trust.md":
            levels, reasons, flags, marks, join = trust_table()
            pages[page] = render_trust_page(levels, reasons, flags, marks,
                                            join, parts[0][1])
        else:
            pages[page] = render_contract_page(page.split("/")[-1][:-3],
                                               parts[0][1],
                                               stamp=parts[1][1],
                                               trace=parts[2][1])
    # The index line of a page is its title and the first line of its
    # primary source's docstring, where that source is a module.
    ledes = {page: (_lede(resolved[page][0][1])
                    if isinstance(resolved[page][0][1], str) else "")
             for page in pages}
    pages["README.md"] = render_index(
        {page: titles[page] for page in pages}, ledes)
    # Two front pages on purpose: `README.md` is what a reader of the
    # repository opens, `index.md` is what Sphinx builds the site from, and
    # only the second may carry a toctree.
    pages["index.md"] = render_toctree(
        {page: titles[page] for page in pages if page != "README.md"})
    return pages


def write(out_dir, pages: dict) -> list:
    """Write the rendered pages. The only writer in this module."""
    out_dir = pathlib.Path(out_dir).resolve()
    written = []
    for rel in sorted(pages):
        if rel in HANDWRITTEN:
            continue
        if pathlib.PurePosixPath(rel).is_absolute() or ".." in rel.split("/"):
            raise ValueError(f"{rel} escapes the output directory")
        path = out_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        # newline=chr(10) and not the platform default: `.gitattributes` says
        # `* text=auto`, so without it --check passes on the compute node and
        # fails on a Windows working copy.
        with io.open(path, "w", encoding="utf-8", newline=NEWLINE) as handle:
            handle.write(pages[rel])
        written.append(path)
    return written


def _pages_on_disk() -> tuple:
    """The markdown files under docs/, by relative path.

    Enumerates and does not read, like `_profile_names`: a stored page is
    read through the door, so `check` holds no second one.
    """
    return tuple(sorted(path.relative_to(PAGES_DIR).as_posix()
                        for path in PAGES_DIR.rglob("*.md")))


def check() -> int:
    """Compare the checked-in pages with a fresh render. 0 when they agree."""
    pages = build()
    on_disk = _pages_on_disk()
    bad = 0
    for rel in sorted(pages):
        if rel in HANDWRITTEN:
            continue
        stored = read_source(f"docs/{rel}") if rel in on_disk else ""
        if stored == pages[rel]:
            continue
        bad += 1
        sys.stdout.writelines(difflib.unified_diff(
            stored.splitlines(True), pages[rel].splitlines(True),
            fromfile=f"docs/{rel}", tofile=f"{rel} (fresh)"))
    for rel in on_disk:
        if rel.startswith("_intros/"):
            continue                      # a source, not a page
        if rel not in pages and rel not in HANDWRITTEN:
            print(f"{rel}: no manifest entry renders this page any more")
            bad += 1
    if bad:
        print(f"{bad} page(s) differ. Re-run "
              f"`python scripts/build_docs.py --out docs` and commit.",
              file=sys.stderr)
        return 1
    print(f"docs: {len(pages)} page(s) match their sources")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", metavar="DIR",
                        help="write the pages into DIR")
    parser.add_argument("--check", action="store_true",
                        help="fail when a checked-in page has drifted")
    args = parser.parse_args(argv)
    try:
        if args.check:
            return check()
        pages = build()
    except SourceMoved as exc:
        print(str(exc), file=sys.stderr)
        return 1
    out_dir = pathlib.Path(args.out) if args.out else PAGES_DIR
    written = write(out_dir, pages)
    print(f"docs: {len(written)} page(s) -> {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
