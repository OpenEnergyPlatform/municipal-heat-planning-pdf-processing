#!/usr/bin/env python3
"""Generate the documentation pages from the sources they describe.

A hand-written page is a second copy of something, and the copy is the one
that goes stale: it says what a module did when somebody last looked. Every
page under `docs/` except one is therefore rendered from what it documents --
module docstrings, the checked-in extraction schemas, the artifact constants,
the signatures and docstrings of every public name for the API reference --
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
import textwrap
import tokenize

ROOT = pathlib.Path(__file__).resolve().parent.parent
PAGES_DIR = ROOT / "docs"

# Where a documented source may live. Not a convenience: `data/` holds the
# corpus and its database, and a page that could quote a plan would publish
# one.
ALLOWED_ROOTS = ("docpipe", "profiles", "scripts", "docs")

# The pages nobody generates, because they say what the parts are FOR, how
# the whole is run, and what the words mean, and no source carries that. They
# are sources here, not outputs: checked where they live, linked from the
# index, and never written.
HANDWRITTEN = ("pipeline.md", "running.md", "glossary.md")
HANDWRITTEN_TITLES = {"pipeline.md": "How the parts fit together",
                      "running.md": "Running the pipeline",
                      "glossary.md": "Glossary"}

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

# The site's table of contents, in groups. Named here because the order is
# the pipeline's and nothing in the tree carries it: the packages are named
# after what they do, not after when they run. An entry ending in "/*" stands
# for the pages a profile contributes, discovered rather than listed.
GROUPS = (
    ("Overview", ("pipeline.md", "running.md")),
    ("The stages", ("stages/fileprocessing.md", "stages/preprocessing.md",
                    "stages/refinement.md", "stages/visuals.md",
                    "stages/chunking.md", "stages/extraction.md",
                    "stages/graph.md", "stages/inference.md",
                    "stages/app.md", "stages/embedding.md",
                    "stages/store.md", "stages/core.md")),
    ("Profiles", ("profiles.md", "profiles/*")),
    ("Contracts", ("contract/states.md", "contract/trust.md",
                   "contract/*")),
    ("Reference", ("artifacts.md", "glossary.md", "api/index.md")),
)
ORDER = tuple(page for _caption, pages in GROUPS for page in pages
              if not page.endswith("/*"))


def toctree_groups(pages) -> list:
    """[(caption, [page, ...])] for the site's contents, wildcards expanded.

    A page that no group names still reaches the contents, in a last group,
    so a new page is a broken build (the Read the Docs build treats a page
    outside every toctree as a warning) rather than an unreachable document.
    """
    have = set(pages) | set(HANDWRITTEN)
    have -= {"README.md", "index.md"}
    # The module pages of the API reference are named by its own index and
    # nowhere else: a hundred of them in the site's contents would bury the
    # twenty pages that say what the parts are for.
    have = {page for page in have if not is_api_module(page)}
    named = {page for _caption, members in GROUPS for page in members}
    out, placed = [], set()
    for caption, members in GROUPS:
        listed = []
        for member in members:
            if member.endswith("/*"):
                prefix = member[:-1]
                listed += sorted(page for page in have
                                 if page.startswith(prefix)
                                 and page not in named)
            elif member in have:
                listed.append(member)
        listed = [page for page in listed if page not in placed]
        if listed:
            out.append((caption, listed))
            placed.update(listed)
    rest = sorted(have - placed)
    if rest:
        out.append(("More", rest))
    return out


def _profile_sources() -> tuple:
    """One page per profile, discovered, not listed: prose plus a table of
    the parameters and axes read from the published contract."""
    return tuple(
        (f"profiles/{name}.md", f"The {name} profile",
         ((_contract_rel(name), "harvest/$defs"),))
        for name in _profile_names())


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
    # Every generated page, the front page included, opens with prose that
    # no source carries: what the thing is for. Without it a page is a table
    # or a list of docstrings, and it is refused rather than published.
    for page in list(out) + ["index.md", API_INDEX]:
        if not (ROOT / INTRO_DIR / page).is_file():
            raise SourceMoved(page, f"{INTRO_DIR}/{page}",
                              "the page has no introduction")
    for page in ORDER:
        if page not in out and page not in HANDWRITTEN and page != API_INDEX:
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
    # A module docstring opens with its file name; the index names the page.
    text = re.sub(r"^[\w./]+\.py\s*[:\u2013\u2014-]+\s*", "", text)
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
    out += ["## Module reference", "",
            "The docstring of each module of this stage, verbatim from the "
            "code and generated by `scripts/build_docs.py`. The chapter "
            "above is the account; this is the reference. Edit the "
            "docstring, not this page.", ""]
    for rel, doc in parts:
        out += _collapsed(f"<code>{rel}</code>", doc)
    out += [f"[Back to the index]({_up(page)}README.md)", ""]
    return NEWLINE.join(out)


def _collapsed(summary: str, body: str) -> list:
    """A `<details>` block whose body is still Markdown: the blank lines
    around it end the HTML block, so what stands between is rendered."""
    return ["<details>", f"<summary>{summary}</summary>", "", body, "",
            "</details>", ""]


def render_profile_page(name: str, harvest: dict, intro: str) -> str:
    """The profile's own page: prose, then the parameters and their axes
    read off the published contract, never off the spec (the spec carries
    real corpus tables as examples)."""
    out = [f"# The {name} profile", ""]
    if intro:
        out += [intro, ""]
    out += ["## The parameters, from the published contract", "",
            "Read from `profiles/%s/extraction_schema.json` by "
            "`scripts/build_docs.py`. Each row is one record kind of the "
            "harvest; an axis is a coordinate of that record, with the "
            "kind of answer it takes. The full contract, every question and "
            "every option, is on [contract/%s.md](../contract/%s.md)." %
            (name, name, name), "",
            "| parameter | value | axes | graph node |", "|---|---|---|---|"]
    for key in sorted(harvest):
        body = harvest[key]
        if not (key.startswith("tuple_") and isinstance(body, dict)):
            continue
        props = body.get("properties") or {}
        value = props.get("value") or {}
        options = value.get("x-options")
        kind = (f"choice of {len(options)}" if isinstance(options, dict)
                and options else str(value.get("type", "")))
        axes = []
        for axis in sorted(props):
            if f"{axis}_state" not in props:
                continue
            prop = props[axis] or {}
            choices = prop.get("x-options")
            kinds = prop.get("type")
            kinds = [kinds] if isinstance(kinds, str) else list(kinds or [])
            kinds = [k for k in kinds if k != "null"]
            if axis == "parameter":
                axes.append("`parameter` (one of the spec's parameters)")
            elif isinstance(choices, dict) and choices:
                axes.append(f"`{axis}` ({len(choices)} options)")
            else:
                axes.append(f"`{axis}` ({kinds[0] if kinds else 'per document'})")
        kg = body.get("x-kg") if isinstance(body.get("x-kg"), dict) else {}
        node = kg.get("node", "")
        out.append(f"| `{key[len('tuple_'):]}` | {kind} | "
                   f"{', '.join(axes) or 'none'} | "
                   f"{'`' + str(node) + '`' if node else ''} |")
    out += ["", "[Back to the index](../README.md)", ""]
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
                         trace=None, intro: str = "") -> str:
    """One section per record kind, straight out of the published schema,
    then the stamp beside the harvest file and the trace beside both."""
    harvest = schema
    out = [f"# The harvest contract: {profile}", "",
           "Generated from `profiles/%s/extraction_schema.json` by "
           "`scripts/build_docs.py`; that file is itself generated from the "
           "profile's `extraction_spec.json` by "
           "`docpipe/extraction/schema.py`. Edit neither: change the spec and "
           "regenerate." % profile, ""]
    if intro:
        out += [intro, ""]
    out += ["One JSON object per line of a harvest file. Every line is one "
            "of the kinds below and nothing else, and each of them is closed "
            "(`additionalProperties: false`). A new record kind costs a "
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
                    "was read or derived; that is what the `allOf` branches "
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


def render_states_page(rows, intro: str = "") -> str:
    out = ["# What a coordinate's state means", "",
           "Generated from `docpipe/extraction/fields.py` and the published "
           "schema by `scripts/build_docs.py`.", ""]
    if intro:
        out += [intro, ""]
    out += [
           "| constant | value | what it says |", "|---|---|---|"]
    for name, value, gloss in rows:
        out.append(f"| `{name}` | `{value}` | {gloss} |")
    out += ["", "[Back to the index](../README.md)", ""]
    return NEWLINE.join(out)


def render_trust_page(levels, reasons, flag_reasons, marks, join,
                      doc: str, intro: str = "") -> str:
    out = ["# How much of a value the run can stand behind", "",
           "Generated from `docpipe/extraction/trust.py` and the published "
           "schema by `scripts/build_docs.py`.", ""]
    if intro:
        out += [intro, ""]
    out += ["## What `docpipe/extraction/trust.py` says", ""]
    out += _collapsed("<code>docpipe/extraction/trust.py</code>", doc)
    out += ["## The levels", "", "| level | what it says |", "|---|---|"]
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


def render_artifacts_page(constants, doc: str, intro: str = "") -> str:
    out = ["# What each stage leaves behind", "",
           "Generated from `docpipe/artifacts.py` by "
           "`scripts/build_docs.py`: the names below and the stage against "
           "each are that module's own constants and its own comments.", ""]
    if intro:
        out += [intro, ""]
    out += ["## What `docpipe/artifacts.py` says", ""]
    out += _collapsed("<code>docpipe/artifacts.py</code>", doc)
    out += ["## Directories", "", "| name | path |", "|---|---|"]
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
    out += ["## What `docpipe/profile.py` says", ""]
    out += _collapsed("<code>docpipe/profile.py</code>", doc)
    out += ["## The profiles in this repository", ""]
    for name in profiles:
        out.append(f"- **{name}**: [the profile](profiles/{name}.md), "
                   f"[its harvest contract](contract/{name}.md)")
    out += ["", "[Back to the index](README.md)", ""]
    return NEWLINE.join(out)


# ---------------------------------------------------------------------------
# The API reference
# ---------------------------------------------------------------------------
# What the reference covers: the packages the chapters describe. One page per
# module under `docs/api/`, named after its dotted path; a package's
# `__init__` is the package's own page. Read with `ast` like everything else
# here, so a signature and a docstring reach the site without the module
# being imported, and therefore without OpenCV, PyMuPDF or torch.
API_ROOTS = ("docpipe", "profiles", "scripts/inference_app",
             "scripts/fileprocessing")
API_DIR = "api"
API_INDEX = f"{API_DIR}/index.md"
API_TITLE = "API reference"
API_LEDE = ("Every public function, class and method of the modules under "
            "`docpipe/`, `profiles/` and the two script packages, with its "
            "signature as written and its docstring.")


def _api_modules() -> tuple:
    """Every module under API_ROOTS, by relative path.

    Enumerates and does not read, like `_profile_names`: the text goes
    through the door.
    """
    out = []
    for root in API_ROOTS:
        for path in sorted((ROOT / root).rglob("*.py")):
            if "__pycache__" not in path.parts:
                out.append(path.relative_to(ROOT).as_posix())
    return tuple(out)


def dotted(rel: str) -> str:
    """`docpipe/extraction/pipeline.py` is `docpipe.extraction.pipeline`,
    and a package's `__init__.py` is the package."""
    parts = rel[:-3].split("/")
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def api_page(rel: str) -> str:
    return f"{API_DIR}/{dotted(rel)}.md"


def is_api_module(page: str) -> bool:
    """A module's page, as opposed to the reference's own index."""
    return page.startswith(f"{API_DIR}/") and page != API_INDEX


def _package_of(rel: str, name: str) -> str:
    """The package a module's page is listed under; a package under itself."""
    return name if rel.endswith("/__init__.py") else name.rpartition(".")[0]


def _header_end(node, by_line: dict) -> tuple:
    """(row, column) of the colon that closes a `def` or `class` header.

    The first `:` at bracket depth zero from the header's first line on,
    found with the tokenizer: what follows the header is not always the
    first statement, since a comment line is no statement and `ast` does not
    see it, and a colon inside a default (`lambda x: x`) or an annotation
    sits inside brackets.
    """
    depth = 0
    for row in range(node.lineno, (node.end_lineno or node.lineno) + 1):
        for token in by_line.get(row, ()):
            if token.type != tokenize.OP:
                continue
            if token.string in ("(", "[", "{"):
                depth += 1
            elif token.string in (")", "]", "}"):
                depth -= 1
            elif token.string == ":" and depth == 0:
                return token.start
    return node.lineno, 0


def _signature(node, lines: list, by_line: dict) -> str:
    """The `def` or `class` header as written, decorators included, up to
    the colon that opens the body.

    From the source lines and not from `ast.unparse`, which spells a default
    `int=0` on Python 3.9 and `int = 0` on 3.11: a page has to render the
    same on a laptop and in the workflow, or `--check` fails on one of them.
    """
    start = (node.decorator_list[0].lineno if node.decorator_list
             else node.lineno) - 1
    row, column = _header_end(node, by_line)
    head = lines[start:row - 1] + [lines[row - 1][:column]]
    return textwrap.dedent(NEWLINE.join(line.rstrip() for line in head)).strip()


def _note_of(node, comments: dict, lines: list) -> str:
    """The comment that belongs to a class field: at the end of its own
    line, or the block of comment-only lines directly above it. In a
    dataclass that comment is the field's only documentation.

    A line above counts only when it is a comment and nothing else: the
    comment at the end of the previous field's line is that field's. A
    comment inside a field that spans lines is not the field's note either.
    """
    if node.lineno == (node.end_lineno or node.lineno) and node.lineno in comments:
        return comments[node.lineno]
    above, line = [], node.lineno - 1
    while line in comments and lines[line - 1].lstrip().startswith("#"):
        above.insert(0, comments[line])
        line -= 1
    return " ".join(above)


def _function(node, lines: list, by_line: dict) -> dict:
    return {"name": node.name, "signature": _signature(node, lines, by_line),
            "doc": ast.get_docstring(node) or ""}


def _class(node, comments: dict, text: str, lines: list, by_line: dict) -> dict:
    """A class: its fields with their comments, its constructor and its
    public methods, in the order the class states them."""
    fields, methods = [], []
    for item in node.body:
        if (isinstance(item, ast.AnnAssign)
                and isinstance(item.target, ast.Name)
                and not item.target.id.startswith("_")):
            # The statement as written, its comment left to `_note_of`.
            fields.append((ast.get_source_segment(text, item) or "",
                           _note_of(item, comments, lines)))
        elif isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if item.name == "__init__" or not item.name.startswith("_"):
                methods.append(_function(item, lines, by_line))
    return {"name": node.name, "signature": _signature(node, lines, by_line),
            "doc": ast.get_docstring(node) or "", "fields": fields,
            "methods": methods}


def _exports(tree, name: str, package: bool) -> tuple:
    """(whether `__all__` is stated, [(name, origin)]).

    The origin is the module a name is imported from when that is one of the
    package's own: relative to the package for an `__init__`, relative to
    the module's own package otherwise. `__all__` counts when it is assigned
    as a list or tuple, annotated or not, and `+=` extends it.
    """
    base = name.split(".") if package else name.split(".")[:-1]
    names, origin, stated = [], {}, False
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.level:
            parts = base[:len(base) - (node.level - 1)]
            for alias in node.names:
                target = parts + ([node.module] if node.module
                                  else [alias.name])
                origin[alias.asname or alias.name] = ".".join(target)
            continue
        target, value = None, None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            target, value = node.target, node.value
        if not (isinstance(target, ast.Name) and target.id == "__all__"):
            continue
        try:
            literal = ast.literal_eval(value) if value is not None else None
        except ValueError:
            continue
        if not isinstance(literal, (list, tuple)):
            continue
        stated = True
        found = [n for n in literal if isinstance(n, str)]
        names = names + found if isinstance(node, ast.AugAssign) else found
    return stated, [(n, origin.get(n, "")) for n in names]


def parse_api(text: str, rel: str) -> dict:
    """What one module publishes, from its text.

    Its docstring, every public function and class with their docstrings,
    and what its `__all__` exports. Public is what `__all__` names when
    there is one, and otherwise every name without a leading underscore.
    """
    # One line ending, whatever the caller read the text with: `ast` counts
    # a bare carriage return as a line and `split` below does not.
    text = text.replace(chr(13) + NEWLINE, NEWLINE).replace(chr(13), NEWLINE)
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        raise SourceMoved(api_page(rel), rel, f"does not parse: {exc}")
    by_line: dict = {}
    for token in tokenize.generate_tokens(io.StringIO(text).readline):
        by_line.setdefault(token.start[0], []).append(token)
    comments = {token.start[0]: token.string.lstrip("#").lstrip(":").strip()
                for tokens in by_line.values() for token in tokens
                if token.type == tokenize.COMMENT}
    name = dotted(rel)
    stated, exports = _exports(tree, name, rel.endswith("/__init__.py"))
    listed = {n for n, _origin in exports} if stated else None

    def public(identifier: str) -> bool:
        return (identifier in listed if listed is not None
                else not identifier.startswith("_"))

    # Split on the newline and nothing else: `str.splitlines` also breaks a
    # line at a form feed, which `ast` and the tokenizer do not, and every
    # line number after it would point one line off.
    lines = text.split(NEWLINE)
    functions = [_function(node, lines, by_line) for node in tree.body
                 if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and public(node.name)]
    classes = [_class(node, comments, text, lines, by_line)
               for node in tree.body
               if isinstance(node, ast.ClassDef) and public(node.name)]
    defined = {f["name"] for f in functions} | {c["name"] for c in classes}
    return {"rel": rel, "name": name, "doc": ast.get_docstring(tree) or "",
            "functions": functions, "classes": classes,
            "exports": [(n, o) for n, o in exports if n not in defined]}


def module_api(rel: str) -> dict:
    return parse_api(read_source(rel), rel)


def _publishes(module: dict) -> bool:
    """An empty `__init__.py` has no docstring and no name, and no page."""
    return bool(module["doc"] or module["functions"] or module["classes"]
                or module["exports"])


# A `<` that opens what Markdown takes for an HTML tag, and the underscores
# at the edge of a word, which Markdown takes for emphasis: `__init__` is
# "init" in bold with the underscores gone. An underscore inside a word,
# `plan_document`, is none of Markdown's business and is left alone.
_TAG = re.compile(r"<(?=[A-Za-z/!?])")
_EDGE = re.compile(r"(?<![\w\\])_+(?=\w)|(?<=\w)_+(?!\w)")
_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")


def _spans(line: str) -> list:
    """[(piece, is_code)]: a line cut at its code spans.

    A code span opens with a run of backticks and closes with a run of the
    SAME length, so ``<x>`` is one span and `a``b` is not two. A run that
    nothing closes is literal text.
    """
    out, i, n = [], 0, len(line)
    while i < n:
        if line[i] != "`":
            j = line.find("`", i)
            j = n if j < 0 else j
            out.append((line[i:j], False))
            i = j
            continue
        j = i
        while j < n and line[j] == "`":
            j += 1
        run, k = j - i, j
        while True:
            k = line.find("`" * run, k)
            if k < 0:
                break
            end = k + run
            if end < n and line[end] == "`":
                while end < n and line[end] == "`":
                    end += 1
                k = end
                continue
            break
        if k < 0:
            out.append((line[i:j], False))
            i = j
        else:
            out.append((line[i:k + run], True))
            i = k + run
    return out


def _escape(text: str) -> str:
    """One line of prose with its tags and edge underscores escaped, its
    code spans untouched."""
    out = []
    for piece, code in _spans(text):
        if not code:
            piece = _TAG.sub(chr(92) + "<", piece)
            piece = _EDGE.sub(lambda m: "".join(chr(92) + c
                                                 for c in m.group(0)), piece)
        out.append(piece)
    return "".join(out)


def markdown_safe(doc: str) -> str:
    """A docstring as the Markdown it is written in.

    Escaped, and only outside code spans, fenced blocks and indented code:
    a `<` that opens what Markdown takes for a tag, so `<name>.jsonl` reads
    as written instead of as ".jsonl" with the tag swallowed; the underscores
    at a word's edge, so `__init__` does not come out as "init" in bold; and
    a `#` opening a line, which would be a heading of the page rather than a
    line of the docstring. Inside a list item, four spaces are the item's
    continuation and not code, so there the code rule needs four more.
    """
    out, fenced, block, previous_blank = [], False, 0, True
    item_indent = None
    # Split on the newline only: `splitlines` would also break the line at a
    # form feed, which the docstring does not.
    for line in doc.split(NEWLINE):
        stripped = line.strip()
        blank, indent = not stripped, len(line) - len(line.lstrip(" "))
        if line.startswith("```"):
            fenced = not fenced
            out.append(line)
            previous_blank = False
            continue
        if fenced:
            out.append(line)
            continue
        if block and not blank and indent < block:
            block = 0
        needed = 4 if item_indent is None else item_indent + 4
        if (not block and not blank and previous_blank and indent >= needed
                and not _ITEM.match(line)):
            block = needed
        if block:
            out.append(line)
        else:
            text = _escape(line)
            if text.lstrip().startswith("#"):
                text = text.replace("#", chr(92) + "#", 1)
            out.append(text)
            if not blank:
                item = _ITEM.match(line)
                if item:
                    item_indent = len(item.group(0))
                elif indent == 0:
                    item_indent = None
        previous_blank = blank
    return NEWLINE.join(out)


def _code(text: str) -> list:
    return ["```python", text, "```", ""]


def render_api_page(module: dict, known=None) -> str:
    """One module: its docstring, then every public class and function with
    its signature as written and its docstring, verbatim."""
    known = set(known or ())
    out = [f"# {_escape(module['name'])}", "",
           f"`{module['rel']}`, read with `ast` by `scripts/build_docs.py`. "
           "The docstrings are the code's own: edit them there, not here.",
           ""]
    out += [markdown_safe(module["doc"]) if module["doc"]
            else "The module has no docstring.", ""]
    if module["exports"]:
        out += ["## Exports", "", "What `__all__` names, and where each "
                "name is defined:", ""]
        for name, origin in module["exports"]:
            where = (f" from [{_escape(origin)}]({origin}.md)"
                     if origin in known
                     else f" from `{origin}`" if origin else "")
            out.append(f"- `{name}`{where}")
        out.append("")
    if module["classes"]:
        out += ["## Classes", ""]
        for cls in module["classes"]:
            out += [f"### {_escape(cls['name'])}", ""] + _code(cls["signature"])
            if cls["doc"]:
                out += [markdown_safe(cls["doc"]), ""]
            if cls["fields"]:
                out += ["Fields:", ""]
                for text, note in cls["fields"]:
                    out.append(f"- `{text}`"
                               + (f": {_escape(note)}" if note else ""))
                out.append("")
            for method in cls["methods"]:
                out += [f"#### {_escape(cls['name'] + '.' + method['name'])}",
                        ""]
                out += _code(method["signature"])
                if method["doc"]:
                    out += [markdown_safe(method["doc"]), ""]
    if module["functions"]:
        out += ["## Functions", ""]
        for function in module["functions"]:
            out += [f"### {_escape(function['name'])}", ""]
            out += _code(function["signature"])
            if function["doc"]:
                out += [markdown_safe(function["doc"]), ""]
    out += [f"[Back to the index]({_up(api_page(module['rel']))}README.md)",
            ""]
    return NEWLINE.join(out)


def _counted(module: dict) -> str:
    parts = []
    for count, word in ((len(module["classes"]), "class"),
                        (len(module["functions"]), "function")):
        if count:
            parts.append(f"{count} {word}"
                         + ("" if count == 1 else "es" if word == "class"
                            else "s"))
    return ", ".join(parts)


def render_api_index(modules: dict, intro: str = "") -> str:
    """The reference's own index: one list per package with each module's
    first sentence, then the toctrees that put the pages in the sidebar.

    The toctrees are hidden because the lists above them already name every
    page, with a sentence each, and Sphinx would otherwise print the same
    names a second time without one.
    """
    out = [f"# {API_TITLE}", ""]
    if intro:
        out += [intro, ""]
    roots = ", ".join(f"`{root}/`" for root in API_ROOTS)
    out += [f"{len(modules)} modules under {roots}, one page each, "
            "generated by `scripts/build_docs.py`.", ""]
    groups: dict = {}
    for rel, module in modules.items():
        groups.setdefault(_package_of(rel, module["name"]), []).append(module)
    ordered = {package: sorted(groups[package],
                               key=lambda m: (m["name"] != package, m["name"]))
               for package in sorted(groups)}
    for package, members in ordered.items():
        out += [f"## {_escape(package)}", ""]
        for module in members:
            lede = _escape(_lede(module["doc"])) if module["doc"] else ""
            counted = _counted(module)
            line = f"- [{_escape(module['name'])}]({module['name']}.md)"
            if lede:
                line += f": {lede}"
            if counted:
                line += f" ({counted})"
            out.append(line)
        out.append("")
    for package, members in ordered.items():
        out += ["```{toctree}", ":maxdepth: 1", ":hidden:", ""]
        out += [module["name"] for module in members]
        out += ["```", ""]
    out += ["[Back to the index](../README.md)", ""]
    return NEWLINE.join(out)


def render_toctree(pages, intro: str = "") -> str:
    """`index.md`: the site's front page, its introduction and its contents.

    Sphinx needs one document that names every other, in the order a reader
    should meet them. That order is the pipeline's, which is in no file: the
    packages are named after what they do, not after when they run. One
    toctree per group of GROUPS, so the sidebar carries the group names.
    """
    out = ["# Municipal heat planning PDF processing", ""]
    if intro:
        out += [intro, ""]
    for caption, members in toctree_groups(pages):
        out += ["```{toctree}", ":maxdepth: 1", f":caption: {caption}", ""]
        out += [page[:-3] for page in members]
        out += ["```", ""]
    return NEWLINE.join(out)


def render_index(pages, ledes=None) -> str:
    out = ["# Documentation", "",
           "Every page here except the hand-written ones is generated from "
           "the code it describes by `scripts/build_docs.py`, and "
           "`tests/test_docs_build.py` fails when a checked-in page and a "
           "fresh render disagree. Edit the source, then run:", "",
           "```", "python scripts/build_docs.py --out docs", "```", "",
           "## Pages", ""]
    for name in HANDWRITTEN:
        out.append(f"- [{HANDWRITTEN_TITLES[name]}]({name}): hand-written")
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
    manifest = SOURCES + _profile_sources() + _contract_sources()
    resolved = resolve(manifest)
    titles = {page: title for page, title, _ in manifest}
    pages: dict = {}
    for page, _title, _entries in manifest:
        parts = resolved[page]
        if page.startswith("stages/"):
            pages[page] = render_stage_page(page, parts)
        elif page == "artifacts.md":
            pages[page] = render_artifacts_page(
                constants_of("docpipe/artifacts.py"), parts[0][1],
                intro_of(page))
        elif page == "profiles.md":
            pages[page] = render_profiles_page(parts[0][1], profiles,
                                               intro_of(page))
        elif page.startswith("profiles/"):
            pages[page] = render_profile_page(page.split("/")[-1][:-3],
                                              parts[0][1], intro_of(page))
        elif page == "contract/states.md":
            pages[page] = render_states_page(states_table(), intro_of(page))
        elif page == "contract/trust.md":
            levels, reasons, flags, marks, join = trust_table()
            pages[page] = render_trust_page(levels, reasons, flags, marks,
                                            join, parts[0][1], intro_of(page))
        else:
            pages[page] = render_contract_page(page.split("/")[-1][:-3],
                                               parts[0][1],
                                               stamp=parts[1][1],
                                               trace=parts[2][1],
                                               intro=intro_of(page))
    # The index line of a page is its title and the first line of its
    # primary source's docstring, where that source is a module.
    ledes = {page: (_lede(resolved[page][0][1])
                    if isinstance(resolved[page][0][1], str) else "")
             for page in pages}
    # The reference: one page per module that has anything to publish, and
    # an index of its own. The module pages are listed there and nowhere
    # else; the front pages name the index.
    modules = {}
    for rel in _api_modules():
        module = module_api(rel)
        if _publishes(module):
            modules[rel] = module
    known = {module["name"] for module in modules.values()}
    for rel, module in modules.items():
        pages[api_page(rel)] = render_api_page(module, known)
        titles[api_page(rel)] = module["name"]
    pages[API_INDEX] = render_api_index(modules, intro_of(API_INDEX))
    titles[API_INDEX] = API_TITLE
    ledes[API_INDEX] = API_LEDE
    listed = {page: titles[page] for page in pages if not is_api_module(page)}
    pages["README.md"] = render_index(listed, ledes)
    # Two front pages on purpose: `README.md` is what a reader of the
    # repository opens, `index.md` is what Sphinx builds the site from, and
    # only the second may carry a toctree.
    pages["index.md"] = render_toctree(
        {page: title for page, title in listed.items()
         if page != "README.md"},
        intro_of("index.md"))
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
    # A module that was renamed or removed has no page in this render, and
    # the page the last render wrote would stay: Sphinx builds it outside
    # every toctree, which is a warning, which is a failed site. The
    # reference is the one part of the site whose pages come and go with the
    # tree, so only its directory is swept.
    api_dir = out_dir / API_DIR
    if API_INDEX in pages and api_dir.is_dir():
        for path in sorted(api_dir.glob("*.md")):
            if path.relative_to(out_dir).as_posix() not in pages:
                path.unlink()
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
            print(f"{rel}: " + ("its module is gone" if is_api_module(rel)
                                else "no manifest entry renders this page "
                                     "any more"))
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
