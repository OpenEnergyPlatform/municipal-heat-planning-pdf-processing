# Profiles

## What a profile is

`docpipe/profile.py` states the idea in its own module docstring: a profile
is everything a project contributes to the generic pipeline, where its
documents come from, what extra tables it needs, which prompts it
overrides, and which filters its app offers (`docpipe/profile.py:2-4`). In
code that is one frozen dataclass, `Profile` (`docpipe/profile.py:32-44`):
`name` (required, and may hold neither `/` nor `\`), `source_language` and
`answer_language` (both default to `"de"`), `column_layout` (one of
`"auto"`, `"single"`, `"double"`, default `"auto"`), `data_root` and `home`
(both optional path overrides), `facets` (a tuple of `Facet(field, label,
widget)` entries the answer app turns into filters), `title`, and
`document_noun`. `__post_init__` checks the name and the column layout
immediately and raises `ValueError` on either (`docpipe/profile.py:46-50`).

A profile is not a subclass to write against. It is a directory,
`profiles/<name>/`, holding exactly one thing the core reads directly: a
`profile.py` exporting a module-level `PROFILE` whose own `name` field
matches the directory it lives in, checked by `load_profile()`
(`docpipe/profile.py:124-142`); a mismatch raises `ValueError` rather than
running a profile under the wrong identity. Everything else the directory
holds, source code, prompts, a spec, an ontology snapshot, is read only by
that profile's own modules or by the specific piece of `docpipe/` that asks
for it by name, described stage by stage below.

Two profiles ship. `kwp` covers German municipal heat plans, a corpus of
801 documents at the point its `column_layout` comment was written
(`profiles/kwp/profile.py:10`), and answers in German; its accepted
values go into MHPKG on the Open Energy Platform. `scenarios` covers the
literature the IIASA AR6 scenario database cites
(`profiles/scenarios/profile.py:1`), a 164-document harvest
(`profiles/scenarios/kg.py:800`), and answers in English; its values go
into OEKG on the same platform. Each has its own
page, [kwp](profiles/kwp.md) and [scenarios](profiles/scenarios.md), for
what its own modules do beyond the interface points here.

Every path a profile's data or files live under is derived from `name`
alone, never typed twice: `package_dir` is `profiles/<name>` unless `home`
overrides it, `prompts_dir` sits under that, `schema_sql` is that
directory's `schema.sql` if the file exists and `None` otherwise, read by
`docpipe/store/schema.py`'s `profile_sql()` and appended to the core
schema inside `apply()`'s one transaction
(`docpipe/store/schema.py:34-37,43`), and
`root`, `pdf_dir`, `processed_dir`, `db_path` and `index_path` all sit
under `data/<name>/` (or `$DOCPIPE_DATA_ROOT/<name>` or `data_root`) if set
(`docpipe/profile.py:85-121`). Two profiles run from the same checkout
therefore never share a file by accident.

## How the core finds and asks a profile

`load_profile(name)` resolves the profile: `name`, or failing that
`$DOCPIPE_PROFILE`, names a directory whose `profiles.<name>.profile`
module it imports; an unknown name raises `LookupError` listing the
profile directories that exist (`docpipe/profile.py:124-135`). Nothing
under `docpipe/` imports a profile itself: its own docstring states the
rule in one line, "the core never imports a profile; it receives one"
(`docpipe/profile.py:6`), and `tests/test_architecture.py` holds it
mechanically. `test_core_imports_neither_profiles_nor_streamlit` walks the
AST of every `.py` file under `docpipe/` (`ast.walk`, so a nested import
counts as well as a module-level one) and fails at the exact line of any
`import profiles...` or `import streamlit...`
(`tests/test_architecture.py:18-25,28-35`).

Five entry points, preprocessing, refinement, visuals, extraction, and
chunking, reach `load_profile` through `resolve_profile(args)` rather than
calling it directly (`docpipe/preprocessing/pipeline.py:501`,
`docpipe/refinement/pipeline.py:233`, `docpipe/visuals/pipeline.py:473`,
`docpipe/extraction/runner.py:3863`, `docpipe/chunking/pipeline.py:346`),
and each adds the `--profile` flag through `add_profile_argument(parser)`
(`docpipe/profile.py:172-176`). `resolve_profile` reads `args.profile` or,
failing that, `$DOCPIPE_PROFILE`, loads the named profile, and writes the
resolved name back into `$DOCPIPE_PROFILE` (`docpipe/profile.py:178-197`).
It refuses one case rather than running it on the wrong prompts: a stage's
config module calls `prompts.load()` the moment Python imports it, before
argparse has read `--profile`, so a profile named only through the flag,
once that module's prompts were already bound under a different or no
profile, is refused with `SystemExit` naming the fix
(`docpipe/profile.py:190-195`). Code with no command line calls
`active_profile()` instead, reading only `$DOCPIPE_PROFILE` and returning
`None` when the variable is unset (`docpipe/profile.py:145-149`).

| Name | Kind | Default | Effect | Where read |
|---|---|---|---|---|
| `--profile` | CLI flag | ambient `$DOCPIPE_PROFILE` or none | names the profile `resolve_profile` loads for this run | `docpipe/profile.py:172-176` |
| `$DOCPIPE_PROFILE` | environment variable | unset | read by `load_profile`, `active_profile`, and `resolve_profile`; the last writes it back once a name is resolved | `docpipe/profile.py:20` |
| `$DOCPIPE_DATA_ROOT` | environment variable | unset, falls back to `<repo>/data` | base directory for every profile's `root` (and therefore `pdf_dir`, `db_path`, `index_path`), unless `Profile.data_root` overrides it | `docpipe/profile.py:101-105` |

Once a `Profile` object exists, the core asks it through exactly two
lookups. `Profile.component(module, attr)` imports
`profiles.<name>.<module>` and returns `getattr(loaded, attr, None)`; a
module the profile lacks is an absence, returning `None`, but one that
exists and fails to import is the profile's own bug and re-raises rather
than being swallowed as absence (`docpipe/profile.py:57-74`).
`Profile.require(module, attr)` is the same lookup with `LookupError` in
place of `None`, for a part the pipeline cannot run without
(`docpipe/profile.py:76-82`); `profile_value(module, attr)` is `require()`
against the ambient profile, cached once per `(profile.name, module,
attr)` for the process's life (`docpipe/profile.py:155-169`).

Which of the two a caller uses is a choice, not a fixed rule.
`docpipe/inference/kg_route.py`'s `hooks()` reads `kg.VALUE_QUERY` through
`component`, not `require`, so a profile with no answerable graph
(`scenarios`) is not forced to provide one; its own comment names why: "a
require with two constant arguments is read by test_architecture as a
demand on EVERY profile" (`docpipe/inference/kg_route.py:98-99, 104`).
`preprocessing.py`'s five constants, by contrast, are all read through
`require` or `profile_value`, so their absence is a hard failure for any
profile the pipeline runs text through.

That comment points at the fourth and last of `tests/test_architecture.py`'s
checks. The other two share the same gate: they run only for a profile
whose `prompts/` directory already holds one `.md` file (`_profile_homes()`,
`tests/test_architecture.py:80-83`). The first finds every prompt id the
core's own source asks for, by walking `docpipe/`'s AST for literal
arguments to `prompts.load()` / `.text()` or a module constant named
`..._PROMPT_ID`, and checks each exists on disk under that profile's
`prompts/`, excusing an id under `extraction/` when `extraction.SPEC_PATH`
is absent and one under `kg/` when `kg.VALUE_QUERY` is absent
(`OPTIONAL_STAGES`, `tests/test_architecture.py:66-77`). The second checks
the reverse: every `.md` file on disk names an id the core actually
requested. The fourth check is what `kg_route.py` is written around: every
`(module, attr)` pair reached through **two literal strings** passed to
`require()` or `profile_value()` anywhere under `docpipe/` must resolve to
something other than `None`, for every profile `_profile_homes()` finds
(`tests/test_architecture.py:111-149`). It is a syntactic scan, and that
literalness is its whole limit: `docpipe/inference/wording.py:39` calls
`profile.require("inference", attr)` with `attr` a variable, so a profile
missing `PHRASES` or `NON_ANCHOR` is invisible to it and surfaces only as a
`LookupError` the first time the answer app is asked a question.

One consequence follows from all three checks sharing `_profile_homes()`: a
profile with only a `profile.py` and no `prompts/` directory is invisible
to all three, not because it passes but because none exercises it.

## The profile interface, stage by stage

The table lists every `(module, attribute)` pair `docpipe/` or its
entry-point scripts asks a profile for, grouped by stage, with what each
shipped profile provides.

| Stage | Module.attribute | Required or optional | `kwp` provides | `scenarios` provides |
|---|---|---|---|---|
| Getting the documents in | `source.SOURCE` | required to run the stage (`component`, `scripts/fileprocessing/pipeline.py:65`) | a class over the KWW Excel sheet | a class over the crawl's `pdf_index.json` |
| Getting the documents in | `source.backfill_meta` | optional, for `--backfill-meta` (`component`, `scripts/fileprocessing/pipeline.py:58`) | provided (`profiles/kwp/source.py:199`) | not provided; the flag ends the run |
| Reading the page | `preprocessing.HYPHEN_EXCEPTIONS` | required (`profile.require`, `docpipe/preprocessing/stage1_extract.py:45`) | German continuation words ("und", "oder", ...) | English ones ("and", "or", ...) |
| Reading the page | `preprocessing.CAPTION_MAX_WORDS` | required (`profile_value`, `docpipe/preprocessing/config.py:176`) | 45 (median caption 8 words, 205 past 40, `profiles/kwp/preprocessing.py:28-32`) | 160 (journal/IPCC captions run 60 to 150 words, `profiles/scenarios/preprocessing.py:31-35`) |
| Reading the page | `preprocessing.TITLE_EXCLUDE_PREFIXES` | required (`profile_value`, `docpipe/preprocessing/config.py:186`) | "abbildung", "tabelle", and their abbreviations | "figure", "table", "box", "plate", and their abbreviations |
| Reading the page | `preprocessing.DIRECTORY_FIGTAB_WORDS` | required (`profile_value`, `docpipe/preprocessing/stage3_structure.py:190`) | German figure/table list openers | English ones |
| Reading the page | `preprocessing.BIBLIOGRAPHY_TITLE_WORDS` | required (`profile_value`, `docpipe/preprocessing/stage3_structure.py:213`) | "literatur", "quellen", ... | "references", "bibliography", ... |
| Repairing the text | `refinement.WINDOW_SIZE` | optional (`component`, `docpipe/refinement/config.py:40`) | not set, falls back to 3 | not set, falls back to 3 |
| The answer app | `catalog.CATALOG` | optional (`component`, `docpipe/inference/catalog.py:140`) | `KwpCatalog`: municipality, Land, year | `Ar6Catalog`: year, venue, AR6 scenario |
| The answer app | `inference.PHRASES`, `NON_ANCHOR`, `READOFF_MARKER`, `READOFF_NOTE` | required at first use (`profile.require`, variable `attr`, `docpipe/inference/wording.py:39`) | German phrasing, 29 keys checked against `wording.REQUIRED` | English phrasing, same 29 keys |
| Reading the values out | `extraction.SPEC_PATH` | required in practice; refused with `SystemExit` otherwise (`component`, `docpipe/extraction/runner.py:3917-3920`) | `extraction_spec.json` | `extraction_spec.json` |
| Reading the values out | `extraction.ANCHORS_PATH` | optional (`component`, `docpipe/extraction/runner.py:1204`) | frozen anchors; measured over 150 documents and 4,785 prose values, 18.0% land in the top 10 sections against 11.0% for anchors the model writes and 7.6% for chance (`docpipe/extraction/runner.py:1196-1198`) | none; every anchor is written by the model |
| Reading the values out | `extraction.SLICE` | optional (`component`, `docpipe/extraction/runner.py:3974`) | `{"quantity": None}`, gates a row on its quantity class alone | not provided; no gate |
| Reading the values out | `extraction.FRAME` | optional (`component`, `docpipe/extraction/runner.py:3994`) | `("scenario", "year")`, found once per document | not provided; nothing repeats that way |
| Reading the values out | `extraction.document_axes` | optional (`component`, `docpipe/extraction/runner.py:3985`) | not provided | this publication's AR6 scenarios and the study regions it names, out of 249 (`profiles/scenarios/regions.json`) |
| Reading the values out | `extraction.document_context` | optional (`component`, `docpipe/extraction/runner.py:3990`) | the plan's own municipality name | not provided |
| The knowledge graph | `kg.make_serializer` | required for `--serialize`; refused with `SystemExit` otherwise (`component`, `docpipe/extraction/runner.py:3896-3899`) | tuples to MHPKG Turtle | tuples to OEKG Turtle |
| The answer app | `kg.VALUE_QUERY` plus six more attributes, and `inference.ROUTE_NOTES` | optional; absent returns `None` (`component`, `docpipe/inference/kg_route.py:104-106`), present but missing any of the other seven raises `LookupError` instead (`111-114`), all eight present builds the route | provided; the app can answer a coordinate question straight from the graph | not provided; the app never queries a graph |

## The two profiles in comparison

| | `kwp` | `scenarios` |
|---|---|---|
| Corpus | German municipal heat plans, 801 documents (`profiles/kwp/profile.py:10`) | the AR6 scenario literature, a 164-document harvest (`profiles/scenarios/kg.py:800`) |
| Target graph | MHPKG, Open Energy Platform | OEKG, Open Energy Platform |
| `source_language` / `answer_language` | de / de | en / en |
| `document_noun` | "Wärmeplan" | "Publikation" |
| `column_layout` | `"auto"`; 184 of 801 documents carry multi-column pages, 44 throughout (`profiles/kwp/profile.py:10-12`) | `"auto"`; journal and agency layouts run two columns more often still |
| Facets in the answer app | `gemeinde`, `bundesland_lang`, `jahr` | `year`, `venue`, `scenario` |
| `catalog.CATALOG` | `KwpCatalog` | `Ar6Catalog` |
| `--backfill-meta` | provided, refreshes `MunicipalityMeta` from a re-read KWW sheet | not provided |
| Frozen extraction anchors | yes, curated from an earlier run's own `anchors.json` | no |
| `SLICE` / `FRAME` | gates on quantity; frames on scenario and year | neither set |
| Per-document choice lists (`document_axes`) | not used | the AR6 scenarios and study regions a publication names, out of 1389 scenarios and 249 regions in `regions.json` (`profiles/scenarios/extraction.py:7-12`) |
| Answer app's graph route (`kg_route`) | wired; a coordinate question can be answered straight from MHPKG | not wired; every answer comes from retrieval |
| `extraction_anchors.json` | present | absent |

## Adding a profile

1. **The smallest profile that loads.** `profiles/<name>/__init__.py`
   (empty) and `profiles/<name>/profile.py` exporting
   `PROFILE = Profile(name="<name>")`. Verify with
   `python -c "from docpipe.profile import load_profile;
   print(load_profile('<name>').display_title)"`. No test in
   `tests/test_architecture.py` notices this profile yet: `_profile_homes()`
   only picks up a profile whose `prompts/` directory holds a `.md` file,
   and this one has none.

2. **Register documents.** Add `source.py` with a `SOURCE` class
   implementing `docpipe.ingest.models.Source`
   (`documents(connection)`, `after_document(connection, doc)`), and, if
   `SourceDoc.meta` carries fields, a `schema.sql` with a `DocumentMeta`
   table plus a `store.py` for the SQL that fills it. Nothing in
   `tests/test_architecture.py` checks this; a missing `SOURCE` surfaces
   only when `scripts/fileprocessing/pipeline.py` runs and
   `profile.component("source", "SOURCE")` comes back `None`.

3. **Teach text extraction the corpus's language, together with the first
   prompt file.** Add `preprocessing.py`'s five constants (the table
   above), and one file under `prompts/`, because
   `test_a_profile_provides_every_component_the_core_requires` only runs
   once `_profile_homes()` sees this profile. From here,
   `pytest tests/test_architecture.py -k <name>` reports every missing
   preprocessing constant and prompt id together.

4. **Add the prompts each stage asks for.** The id set is fixed by the
   core's own code, not invented per profile; copying an existing
   profile's `prompts/` tree gives the identical set, since both shipped
   profiles are asked for the same one (confirmed above,
   `_requested_prompt_ids`). `refinement/` and `visuals/` need no Python
   module beyond their prompts. `preprocessing/page_transcribe.md` is
   exercised only when a PDF carries no text layer, but `preprocessing`
   is not one of `OPTIONAL_STAGES`' two keys, `extraction` and `kg`
   (`tests/test_architecture.py:66-67`), so
   `test_a_profile_provides_every_prompt_the_core_loads` demands it on
   disk for every profile once its `prompts/` directory holds any `.md`
   file, regardless of whether its corpus has a textless PDF.

5. **Wire up the answer app.** Add `inference.py`
   (`PHRASES`, `NON_ANCHOR`, `READOFF_MARKER`, `READOFF_NOTE`) and
   `prompts/inference/*.md`, then `catalog.py` if the generic picker
   (filename, published date, current or superseded) is not enough. A
   missing one of these four `inference.py` attributes is the case named
   above where `test_architecture.py` cannot catch it: it passes `pytest`
   and fails only at the answer app's first real question.

6. **Add extraction, if this corpus should feed a knowledge graph.** Write
   `extraction_spec.json` by hand, add `extraction.py` with `SPEC_PATH` at
   least, `kg.py` with `make_serializer`, and `prompts/extraction/*.md`.
   `python scripts/preflight_profiles.py <name>` exercises, without a GPU,
   a model, or a database: the spec
   (`scripts/preflight_profiles.py:54-55`), any frozen anchors
   (`scripts/preflight_profiles.py:116-127`), each extraction prompt's
   presence and non-empty text, `temperature` and `max_tokens` for
   `extraction/rows` and `extraction/field` specifically
   (`scripts/preflight_profiles.py:161-176`), and `kg.py`'s presence
   (`scripts/preflight_profiles.py:219-220`).

Throughout, `pytest tests/test_architecture.py -k <name>` is the one
command that reports what is missing by name rather than by where it
crashes later. Running the suite in full, at the end, is still necessary:
neither it nor `preflight_profiles.py` replaces the profile's own tests,
and `docpipe.extraction.schema`'s generator and `docpipe.extraction`'s
`--serialize` path each read a profile's checked-in files directly.

## Verification

A misconfigured profile fails more than one way. `Profile.__post_init__`
raises `ValueError` on an unusable `name` or unknown `column_layout`
(`docpipe/profile.py:46-50`), pinned by `tests/test_profile.py`'s
`test_rejects_unusable_names` and `test_rejects_unknown_column_layout`.
`load_profile` raises `LookupError` for a name given nowhere
(`docpipe/profile.py:127-129`) or unknown on disk
(`docpipe/profile.py:135`), pinned by
`test_no_profile_is_an_explicit_error` and
`test_unknown_profile_lists_the_available_ones`; it also raises
`ValueError`, unpinned by any test, when `PROFILE.name` does not match its
directory (`docpipe/profile.py:141`). `Profile.require` and
`profile_value` raise `LookupError` for a missing attribute or an unset
`$DOCPIPE_PROFILE` (`docpipe/profile.py:76-81,165`), the case
`kg_route.hooks()` turns into its own `LookupError` for a partial
`kg.VALUE_QUERY` route (above). `resolve_profile` raises `SystemExit` for a
late `--profile` naming a profile whose prompts are already bound
(`docpipe/profile.py:190-195`), pinned by
`test_late_profile_is_refused_when_it_overrides_prompts`. Two entry points
add their own `SystemExit`, via `parser.error()` for extraction:
`scripts/fileprocessing/pipeline.py:60,67,70` for a missing `SOURCE` or
`backfill_meta`, and
`docpipe/extraction/runner.py:3896-3899,3917-3920` for a missing
`SPEC_PATH` or `make_serializer`.

## What `docpipe/profile.py` says

<details>
<summary><code>docpipe/profile.py</code></summary>

profile.py: A profile is everything a project contributes to the generic
pipeline: where its documents come from, what extra tables it needs, which
prompts it overrides and which filters its app offers.

The core never imports a profile; it receives one.

Author: Felix Vossel

</details>

## The profiles in this repository

- **kwp**: [the profile](profiles/kwp.md), [its harvest contract](contract/kwp.md)
- **scenarios**: [the profile](profiles/scenarios.md), [its harvest contract](contract/scenarios.md)

[Back to the index](README.md)
