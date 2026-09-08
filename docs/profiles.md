# Profiles

A profile is a directory, `profiles/<name>/`, and nothing else -- there is no
plugin registry, no entry-point declaration, no place a third profile has to
be listed. `docpipe/` finds one by name, either `$DOCPIPE_PROFILE` or
`--profile`, and from there does exactly two things to it: import
`profiles/<name>/profile.py` for its `PROFILE` object, and ask that object for
whatever else a given stage needs. It never imports `profiles.<name>.source`,
`profiles.<name>.kg` or any other of the profile's own modules directly, and
`tests/test_architecture.py` enforces that mechanically: it parses every `.py`
file under `docpipe/` and fails the moment one of them contains a top-level
`import profiles...`. What the two shipped profiles, `kwp` (German municipal
heat plans) and `scenarios` (the literature the IPCC AR6 scenario database
cites), have in common is therefore not a shared base class or a shared
import. It is that both answer the same two lookups, `Profile.component(module,
attr)` and `Profile.require(module, attr)`, the same way: `component` imports
`profiles.<name>.<module>` and returns `getattr(loaded, attr, None)`, treating
a module the profile does not have as an absence and a module that exists but
fails to import as the profile's own bug, raised rather than swallowed.
`require` is the same lookup with a `LookupError` in place of `None`, for the
parts a stage genuinely cannot run without. A third profile has to answer
those same lookups. Nothing else about its internals is checked, or checkable,
from outside `profiles/<name>/` itself.

## The directory

Not every file below is read by the core, and of the ones that are, not every
one is required for every stage. The table gives each one honestly: whether
the pipeline can run at all without it, and which piece of `docpipe/` (or
which script) actually opens it.

| file | required? | read by |
|---|---|---|
| `__init__.py` | yes | makes `profiles.<name>` an ordinary package -- never imported for its own content |
| `profile.py` | yes | `docpipe.profile.load_profile()` imports it and reads its `PROFILE` attribute |
| `source.py` | to run stage 1 | `scripts/fileprocessing/pipeline.py`, via `profile.component("source", "SOURCE")` (and, for `--backfill-meta`, `"backfill_meta"`) |
| `store.py` | no | not read by `docpipe/` at all -- a place for the profile's own SQL, imported by its own `source.py` / `catalog.py` |
| `config.py` | no | not read by `docpipe/` at all -- constants private to the profile, imported by its own modules |
| `preprocessing.py` | to run stages 2-3 | `docpipe.preprocessing`'s `config.py`, `stage1_extract.py`, `stage3_structure.py`, via `profile.require` / `profile_value` |
| `catalog.py` | no | `docpipe.inference.catalog.load_catalog()`, via `profile.component("catalog", "CATALOG")` -- falls back to a generic catalog over `Documents` |
| `inference.py` | to run the answer app | `docpipe.inference.wording`, via `profile.require("inference", attr)` |
| `extraction.py` | to run extraction | `docpipe.extraction.runner`, via `profile.component("extraction", attr)`, several attributes, all optional individually |
| `kg.py` | to run `--serialize` | `docpipe.extraction.runner`, via `profile.component("kg", "make_serializer")` |
| `schema.sql` | no | `docpipe.store.schema.apply()` / `.connect()`, via the `profile.schema_sql` property -- applied after the core schema, same connection |
| `extraction_spec.json` | to run extraction | not read by `docpipe/` directly -- its path is what `extraction.py`'s `SPEC_PATH` names, loaded by `docpipe.extraction.spec.load()` |
| `extraction_schema.json` | no | not read by the running pipeline at all -- a published artifact, checked for freshness by `scripts/preflight_profiles.py` |
| `extraction_anchors.json` | no | not read by `docpipe/` directly -- named by `extraction.py`'s optional `ANCHORS_PATH`, read by `docpipe.extraction.runner.frozen_anchors()` |
| `vocabulary.json` | no | not read by `docpipe/` at all -- read by `scripts/preflight_profiles.py`, which imports `profiles.<name>.vocabulary` directly |
| `vocabulary.py` | no | same as above -- also the script that builds and checks `vocabulary.json` |
| `prompts/<stage>/<name>.md` | one file per id the core loads | `docpipe.prompts.load()` / `.text()` |
| anything else | no | the profile's own business (both shipped profiles carry a few of these -- see below) |

As a tree, `kwp` (the fuller of the two shipped profiles):

```
profiles/kwp/
├── __init__.py
├── profile.py                  # PROFILE = Profile(name="kwp", ...)
├── source.py                   # SOURCE, backfill_meta
├── store.py                    # this profile's own SQL, private
├── config.py                   # PDF_OVERRIDES, SHARED_FILE_OWNERS, ...
├── preprocessing.py            # HYPHEN_EXCEPTIONS, CAPTION_MAX_WORDS, ...
├── catalog.py                  # CATALOG
├── inference.py                # PHRASES, NON_ANCHOR, READOFF_MARKER, READOFF_NOTE
├── extraction.py               # SPEC_PATH, ANCHORS_PATH, SLICE, FRAME, ...
├── kg.py                       # make_serializer(db_path)
├── schema.sql                  # OrganisationUnits, Municipalities, DocumentMeta, MunicipalityMeta
├── extraction_spec.json        # hand-written
├── extraction_schema.json      # generated
├── extraction_anchors.json     # hand-picked from an earlier run
├── vocabulary.json             # generated
├── vocabulary.py               # the builder/checker
├── migrate_convoy_group_keys.py    # one-off, this profile's own
├── migrate_profile_split.py        # one-off, this profile's own
└── prompts/
    ├── preprocessing/page_transcribe.md
    ├── refinement/...
    ├── visuals/...
    ├── extraction/...
    └── inference/...
```

`scenarios` carries the same files with two exceptions: it has no
`extraction_anchors.json` and no `migrate_*.py` scripts, and it adds one file
of its own, `regions.json` (the 249 study regions `extraction.py` narrows per
document). Both of those differences are the point of the "not read by the
core" rows above -- a profile may add whatever private files its own modules
need, and the pipeline will never notice either way.

## What each Python module is asked for

**`profile.py`** exports one name, `PROFILE`, a `Profile` instance. Its `name`
must equal the directory name, or `load_profile()` raises `ValueError`
(`"profile 'x' calls itself 'y'"`) rather than run a profile under the wrong
identity. Everything else on it -- `source_language`, `answer_language`,
`column_layout`, `facets`, `title`, `document_noun` -- is a plain dataclass
field read directly, never through `component`/`require`. `column_layout` is
checked once in `__post_init__` against `("auto", "single", "double")`. `kwp`
sets it from a measurement stated right in the comment: 184 of its documents
have multi-column pages, 44 of them throughout, and pages like that read as
interleaved nonsense without a column-aware layout.

**`source.py`** is read by `scripts/fileprocessing/pipeline.py`, which does
`source_class = profile.component("source", "SOURCE")` and then
`source_class(Path(args.source))`. `SOURCE` has to be a class implementing
`docpipe.ingest.models.Source`: `documents(connection)` yields `SourceDoc`
rows (`external_id`, `filename`, `url` -- `None` means the file must already
sit in the data directory -- `group_key`, `published`, `meta` for the
profile's `DocumentMeta` columns, `payload` opaque to the core),
`after_document(connection, doc)` is called once per accepted document for
writing the profile's own rows, and `__len__()` is optional, for the progress
bar. `--backfill-meta` reads a second, independent optional attribute,
`backfill_meta`, a callable `(source_path, db_path) -> int` that only touches
metadata for documents already registered.

**`store.py`** is not looked up by `docpipe/` at all -- there is no
`profile.component("store", ...)` call anywhere in the core. Both shipped
profiles use it the same way regardless: a handful of `INSERT ... ON
CONFLICT` helpers for the tables their own `schema.sql` adds, imported
directly (`from . import store`) by that profile's own `source.py` and, in
`scenarios`, `catalog.py` too. A profile is free to shape it however its own
tables need, or skip it and put the same SQL straight in `source.py`.

**`preprocessing.py`** is the one module every profile with any text at all
needs, and it is enforced: five constants, all read through `profile.require`
or `profile_value` (which is `require`, cached), so all five are picked up by
the automatic component check described below. `HYPHEN_EXCEPTIONS` is a tuple
of words that must not be glued to the word before a line-ending hyphen --
`kwp` lists German continuation words ("und", "oder", "bzw", ...), `scenarios`
lists English ones ("and", "or", "nor", ...), because a German compound breaks
across a hyphen far more often than English does, which instead leans on
suspended hyphenation ("short- and long-term"). `CAPTION_MAX_WORDS` is an
`int`: past it, the nearest-text-block fallback that promotes a stray
paragraph to a caption is refused. `kwp` sets `45` (median caption 8 words,
99th percentile 24, 205 captions past 40 words on its corpus). `scenarios`
sets `160`, because journal and IPCC captions routinely run 60-150 words
where a municipal heat plan's sit at 8 -- same constant, same core code, two
numbers, because the two corpora are typeset differently. `TITLE_EXCLUDE_PREFIXES`
is the lower-cased line openers ("abbildung", "tabelle" / "figure", "table",
...) that must never be promoted to a section title. `DIRECTORY_FIGTAB_WORDS`
and `BIBLIOGRAPHY_TITLE_WORDS` are, respectively, how a figure/table
list entry opens (for stripping directory pages) and which section-title
words route a section to the BibTeX path in stage 4.

**`catalog.py`** is read once, by `docpipe.inference.catalog.load_catalog()`,
through `profile.component("catalog", "CATALOG")`. `CATALOG` must be a
subclass or instance of `docpipe.inference.catalog.Catalog`, overriding
whichever of four methods the generic behaviour is not enough for:
`rows(conn, include_superseded=False)` returns one row per document,
`facet_values(conn, rows)` returns `{document id: {facet field: [values]}}`,
`label(row, facets=None)` returns the picker's display string, and
`detail(row, facets=None)` returns a sequence of `(heading, lines)` blocks
shown for the selected document. Left unset, `Catalog` runs a plain `SELECT
... FROM Documents` and labels each row by its filename, with no facets at
all -- `Catalog.facets` just reads `profile.facets`, which is also empty
unless `PROFILE` declares some.

**`inference.py`** is required the first time the answer app actually answers
a question: `docpipe.inference.wording` reads `PHRASES`, `NON_ANCHOR`,
`READOFF_MARKER` and `READOFF_NOTE`, all through `profile.require("inference",
attr)`. `PHRASES` is checked against `wording.REQUIRED`, a 29-key frozenset --
every heading and guide sentence the answer loop wraps around a profile's own
prompts, in that profile's own language -- and `wording.phrases()` raises
`LookupError` naming exactly the keys still missing, the first time it runs
for that profile, cached after that. `NON_ANCHOR` is a compiled regex
matching the ways a model, asked for a search anchor, answers with a refusal
instead ("not stated", "cannot be determined", and so on, in whichever
language the corpus answers in) -- written wrong or left as some other
profile's pattern, every refusal is silently used as a retrieval probe rather
than caught. `READOFF_MARKER` / `READOFF_NOTE` mark and annotate a value the
model read off a figure rather than off text.

**`extraction.py`** is the one module nothing requires just to run stages 1
through 6 -- every attribute on it is reached through `profile.component`,
never `require`, and it is read only when the extraction (OBIE) stage itself
runs. `SPEC_PATH` is the one attribute close to mandatory in practice: without
it, `python -m docpipe.extraction` refuses immediately with "profile ... does
not configure the extraction stage". The rest are genuinely optional.
`ANCHORS_PATH` names a file of anchors frozen from an earlier real run rather
than written fresh by the model each time. `kwp` measured what that buys, over
150 documents and 4,785 prose values: 18.0% of them land in the top 10
retrieved sections against 11.0% for anchors the model writes itself, and 7.6%
for chance. `SLICE` is `{axis name: allowed answer, or None for "any class the
graph takes"}` -- the coordinates checked first and alone, deciding whether a
row belongs in the graph at all before the other seven are asked at all.
`FRAME` is a tuple of axis names that belong to the *document* rather than the
row -- `kwp` sets `("scenario", "year")`, because a plan's scenario containers
and reference years stand in headings and column headers and can be found
once per document, while `scenarios` sets none, because nothing in that
corpus repeats that way. Two callables close the module out:
`document_axes(conn, document_id)` returns `{axis name: {uri: [labels]}}`
for a per-document dynamic choice list (`scenarios` uses this for the AR6
scenarios and study regions one particular publication actually names), and
`document_context(conn, document_id)` returns `{"name": ...}`, whatever the
document contributes to its own search anchor.

**`kg.py`** is read only for `--serialize`, through
`profile.component("kg", "make_serializer")`. `make_serializer(db_path)`
returns a `serializer(name, rows)` callable -- `name` is one document's stem
in the harvest, `rows` its accepted tuples -- which returns that document's
rendered graph text (Turtle, in both shipped profiles) or `None` to skip a
document with nothing to say. `docpipe.extraction.serialize.run()` calls it
once per document in the harvest and refuses to write the output file at all
if every call came back `None`, so a broken or empty harvest cannot truncate
a good graph already on disk.

## The data files

Two of the JSON files are generated, and the command that generates each is
worth writing down exactly, because getting the file out of date is a test
failure and not a runtime one:

```
python -m docpipe.extraction.schema <name> --write     # extraction_schema.json, from extraction_spec.json
python -m profiles.<name>.vocabulary --closure <closure.owl> [--mhpo <edit.owl>] --write   # vocabulary.json
python -m profiles.<name>.vocabulary --check                                               # spec vs. the pinned snapshot
```

`extraction_schema.json` exists because the alternative was a docstring: what
a harvested key means, which OEO predicate an axis becomes, which closed list
backs it, used to be answered by reading `runner.py`, which nobody outside
this repository can do. It is built from `extraction_spec.json` alone, never
from a real corpus passage (`docpipe/extraction/schema.py` says so in its own
comment, and `tests/test_docs_build.py` checks that no generated page ever
quotes one), and `scripts/preflight_profiles.py` fails when the checked-in
file no longer matches a fresh render of the spec. `extraction_spec.json`
itself is hand-written, and stays that way -- it is where a profile's
parameters, axes, questions and closed answer lists actually live, and
nothing in this repository generates it.

`vocabulary.json` exists because a spec that hand-types an ontology IRI next
to a hand-typed label has nobody checking the two agree, and the ontology
moves. `--check` reads the checked-in snapshot only, never the closure file
and never `rdflib`, so it runs on a machine -- the cluster, say -- that has
neither installed. A profile whose spec names no ontology identifiers at all
needs neither `vocabulary.json` nor `vocabulary.py`. `extraction_anchors.json`
is the one file here that is neither hand-written from scratch nor generated
by a command: it is curated by hand from a *previous run's own* `anchors.json`
(written next to that run's harvest), copying in the sections that really
produced a value for a given question. `kwp` is the only profile that has
one. `scenarios` leaves every anchor to the model.

One convention is worth naming even though it lives entirely inside
`schema.sql`: `docpipe/store/documents.py`'s `add_document()` writes a
`SourceDoc`'s `meta` dict straight into a table named, literally,
`DocumentMeta` -- `document INTEGER PRIMARY KEY REFERENCES Documents(id)`,
plus whichever columns the profile wants -- whenever `meta` is non-empty.
`DocumentMeta` is therefore the one profile table name the core actually
knows, not through `component` or `require` but because it is spelled into an
`INSERT` statement. A profile whose `SourceDoc.meta` carries keys and whose
`schema.sql` does not define exactly that table fails on the very first
document it tries to register.

## Why `DOCPIPE_PROFILE` has to be set in the environment

`docpipe/prompts.py` has no fallback of its own. A prompt id is `<stage>/<name>`
and resolves to exactly one path, `profile.prompts_dir / stage /
f"{name}.md"` -- nothing else is ever tried, and a stage whose profile has no
file there fails with `FileNotFoundError` naming that exact path, never with
some other project's prompt run against the wrong language.

The reason `--profile <name>` on its own is not enough, and `$DOCPIPE_PROFILE`
has to be set before the process even starts: a prompt is not always loaded
inside a function that runs after `argparse` has parsed the command line.
`docpipe/inference/llm_client.py`, `docpipe/visuals/config.py` and
`docpipe/refinement/split.py` all bind several prompts as plain module-level
constants -- `PHRASE_SYSTEM_PROMPT = prompts.text("inference/phrase")`, and
close to twenty more like it across the three files -- text that is read the
moment Python imports the module, which for any of these stages happens
before a single command-line flag has been looked at. `docpipe.profile.
resolve_profile()` is built around exactly that timing: if the profile named
only by `--profile` carries any prompt at all (its `prompts/` directory
exists and holds at least one `.md` file) and `$DOCPIPE_PROFILE` was not
already set to that same name, it raises `SystemExit` rather than run the
stage silently against whichever profile, if any, was ambient when the module
first loaded. Run a stage as

```
DOCPIPE_PROFILE=<name> python -m <stage> ...
```

not as `python -m <stage> --profile <name>`.

## Adding a profile, one piece at a time

**1. The smallest profile that loads.** Just a package and a `Profile`:

```
profiles/<name>/__init__.py     # empty
profiles/<name>/profile.py
```
```python
from docpipe.profile import Profile

PROFILE = Profile(name="<name>")
```
Verify with nothing more than an import:
```
python -c "from docpipe.profile import load_profile; print(load_profile('<name>').display_title)"
```
At this point `tests/test_architecture.py` checks nothing about this profile
at all -- its prompt and component tests only run for a profile whose
`prompts/` directory already holds a `.md` file, and this one has no
`prompts/` directory yet.

**2. Register documents (stage 1).** Add `source.py` (`SOURCE`), and, if
`SourceDoc.meta` will carry anything, `schema.sql` with a `DocumentMeta` table
plus `store.py` for the SQL that fills it and whatever other tables the
profile needs.
```
python -m scripts.fileprocessing --profile <name> --source <list> \
    --db data/<name>/<name>.db --data-dir data/<name>/pdf
```

**3. Teach text extraction the corpus's language (stages 2-3).** Add
`preprocessing.py`'s five constants (above).
```
python -c "from docpipe.profile import load_profile; load_profile('<name>').require('preprocessing', 'HYPHEN_EXCEPTIONS')"
```
then run stage 2/3 over one PDF with `DOCPIPE_PROFILE=<name>` set. Stages 4
(refinement), 5 (visuals) and 6 (chunking) need nothing further from
`profiles/<name>/` in Python -- only their own prompts, next.

**4. Add the prompts each stage you want to run actually asks for.** The set
of ids is fixed by the core's own code, not invented per profile -- copying
the `prompts/` tree of an existing profile is a safe starting list, since both
shipped profiles are asked for the identical set. `refinement/` and
`visuals/` need no Python module at all beyond their prompts.
`preprocessing/page_transcribe.md` is only needed if some of the corpus's
PDFs carry no text layer (`kwp` has eleven such plans).
```
pytest tests/test_architecture.py -k <name>
```
reports every missing prompt id by name, once `prompts/` holds at least one
file (step 1's profile is invisible to this test, this step's is not).

**5. Wire up the answer app.** Add `inference.py` (`PHRASES`, `NON_ANCHOR`,
`READOFF_MARKER`, `READOFF_NOTE`) and `prompts/inference/*.md`, then
`catalog.py` if the generic picker (filename, published date, current/old) is
not enough.
```
pytest tests/test_architecture.py -k <name>
```
again -- this is also where a missing `preprocessing.py` constant would show
up, since that check runs on the same pass.

**6. Add extraction, if this corpus wants a knowledge graph.** Write
`extraction_spec.json` by hand, add `extraction.py` (`SPEC_PATH` at least) and
`kg.py` (`make_serializer`), and `prompts/extraction/*.md`.
```
python scripts/preflight_profiles.py <name>
```
is the one command built for exactly this: it exercises the spec, the frozen
anchors if any, every extraction prompt's placeholders and its
`temperature`/`max_tokens`, `kg.py`'s presence, and, if used, the vocabulary
snapshot -- all without a GPU, a model, or a database. Then publish what it
checked:
```
python -m docpipe.extraction.schema <name> --write
python -m profiles.<name>.vocabulary --closure <closure.owl> --write   # only if the spec names ontology terms
```

**Always, last:** `pytest`. Nothing above runs the whole suite, and
`docpipe.extraction.schema` and `docpipe.extraction`'s `--serialize` path
each have their own tests that read a profile's checked-in files directly.

## What the test suite catches, and what it does not

`tests/test_architecture.py` is four checks built from parsing `docpipe/`'s
own source, not from running it, and each has a blind spot worth knowing
before it looks like a passing check that should have failed.

The first, that the core imports nothing under `profiles/`, has none -- it
walks every `.py` file's AST and fails at the exact line of a top-level
`import profiles...` or `import streamlit...`.

The second and third concern prompts, and both apply only to a profile whose
`prompts/` directory holds at least one `.md` file at all (a profile with none
is invisible to both, which is exactly the state of the profile from step 1
above). One checks that every prompt id the core's own source asks for --
found by walking `docpipe/`'s AST for literal string arguments to
`prompts.load(...)` / `prompts.text(...)`, or for a module constant named
`..._PROMPT_ID` -- exists on disk under that profile's `prompts/`, with one
named carve-out: an id under `extraction/` is not required when
`profile.component("extraction", "SPEC_PATH")` is `None`, so a profile
skipping OBIE is not forced to write prompts nothing will ever load. The
other checks the reverse: every `.md` file actually present corresponds to an
id requested somewhere, so a misspelt filename cannot sit there looking like
coverage while the id the code actually asks for stays missing.

The fourth is where `preprocessing.py`'s five constants are genuinely
enforced: every `(module, attr)` pair the core passes as **two literal
strings** to `profile.require(...)` or `profile_value(...)` must resolve to
something other than `None`. It is a syntactic scan, and that literalness is
its whole limit: `docpipe/inference/wording.py` calls `profile.require
("inference", attr)` with `attr` as a variable, not a literal, so `inference.py`'s
four attributes are invisible to this test even though they are just as real
a requirement -- they surface instead as a `LookupError` from
`wording.phrases()` the first time the app actually answers a question, not
from pytest. The same is true, more broadly, of everything reached only
through `component` and never through `require` / `profile_value`:
`extraction.py`'s and `kg.py`'s attributes, `catalog.py`'s `CATALOG`, and
`refinement.py`'s optional `WINDOW_SIZE` (neither shipped profile defines
one, it defaults to `3`) all fail loudly, but only when the stage that needs
them actually runs, never earlier. `scripts/preflight_profiles.py` is what
closes that gap for extraction specifically -- it is not a pytest test, it
reads a profile's `extraction.py` and `kg.py` directly, and it is the only
check in this repository that does.

## What `docpipe/profile.py` says

Verbatim from the module docstring, generated by `scripts/build_docs.py`.

profile.py – A profile is everything a project contributes to the generic
pipeline: where its documents come from, what extra tables it needs, which
prompts it overrides and which filters its app offers.

The core never imports a profile; it receives one.

Author: Felix Vossel

## The profiles in this repository

- **kwp** — [the harvest contract](contract/kwp.md)
- **scenarios** — [the harvest contract](contract/scenarios.md)

[Back to the index](README.md)
