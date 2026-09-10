## Purpose

`docpipe/artifacts.py`, `docpipe/profile.py`, `docpipe/prompts.py`,
`docpipe/llm_preflight.py` and `docpipe/captions.py` are the five
modules this page documents together (`scripts/build_docs.py:349-351`
groups them under this page). Each is imported by a different subset of
preprocessing, refinement, visuals, chunking, extraction and inference;
only `profile.py` reaches all six (Position in the pipeline, below).
None turns a PDF
into text or a section into a database row; each answers one question a
stage would otherwise answer for itself, risking a different one each
time: where a profile's data is stored and what it
supplies (`profile.py`), which file carries a stage's prompt and
whether a result on disk still matches it (`prompts.py`), what a
file a stage writes is called so the next stage can find it
(`artifacts.py`), whether the model server a stage is about to call can
do what is asked (`llm_preflight.py`), and, once a caption-linking rule
elsewhere attaches the wrong sentence to a table, where the real title
sits (`captions.py`).

The five files share a property none of the numbered stages needs: a
profile never appears inside them by name. `docpipe/profile.py` states
the rule in its own docstring, "The core never imports a profile; it
receives one" (`docpipe/profile.py:6`), and
`test_core_imports_neither_profiles_nor_streamlit`
(`tests/test_architecture.py`) holds it mechanically, parsing the AST of
every file under `docpipe/` for a top-level `import profiles` or `import
streamlit`. Three further checks in the same file hold the reverse:
every prompt id the core loads is something each profile with prompts
on disk supplies
(`test_a_profile_provides_every_prompt_the_core_loads`), every
component or attribute pair the core requires is something each
profile supplies
(`test_a_profile_provides_every_component_the_core_requires`), and no
profile carries a prompt file that neither the core nor the profile's
own code ever requests
(`test_a_profile_carries_no_prompt_nobody_loads`). What a profile itself
contributes is on [profiles](../profiles.md); this chapter documents the
receiving side.

## Position in the pipeline

None of these five modules sits between an upstream and downstream step;
each is imported by whichever stage is running, none writes its own
`results/` file, and none runs from the command line by itself. In
place of an In/Out table, what each module supplies and who reaches for
it is:

| Module | Supplies | Reached from |
|---|---|---|
| `profile.py` | the active `Profile`: paths, prompts directory, `component()`/`require()` | every stage's pipeline or CLI module, plus preprocessing's and refinement's `config.py`; inference only via `wording.py`, no CLI |
| `prompts.py` | a prompt's text and sha256, plus a staleness check against `.prompt_versions.json` | preprocessing, refinement, visuals, extraction, inference load; refinement and visuals record/check |
| `artifacts.py` | the filename of every per-document result file, spelled out once | preprocessing, refinement, visuals, chunking |
| `llm_preflight.py` | a check, before a stage's first document, that its server can do what is asked | refinement, visuals, extraction |
| `captions.py` | the rule for where a table's or figure's real title sits | preprocessing (write time); chunking, inference (read time) |

The closest thing any of the five holds to a resume rule is
`prompts.py`'s staleness check (Method). `profile.py` also memoizes
`profile_value()` in memory for one process, not a resume rule;
`artifacts.py`, `llm_preflight.py` and `captions.py` keep no state of
their own.

## Method

### Loading the environment before anything reads it

`docpipe/__init__.py`'s only statement calls `dotenv.load_dotenv()`
(`docpipe/__init__.py:1-5`), the moment any code imports `docpipe`. It
reads the first readable of `DOCPIPE_ENV_FILE`, `INFERENCE_ENV_FILE`, or
a bare `.env`, filling in only keys not already set
(`docpipe/dotenv.py:24-50`), so an exported value is never replaced by
the file. This precedes prompt binding, or an unset `LLM_API_KEY` is
captured empty.

### Resolving the active profile

A CLI entry point calls `resolve_profile(args)`, which reads `--profile`
or `DOCPIPE_PROFILE`, imports `profiles/<name>/profile.py` through
`load_profile()`, and writes the resolved name back into
`os.environ[DOCPIPE_PROFILE]` (`docpipe/profile.py:178-197`). Code with
no command line calls `active_profile()` instead, reading only the
ambient variable (`docpipe/profile.py:145-149`). A third function,
`profile_value(module, attr)`, resolves through `active_profile()` too,
then caches its result in a module-level dict keyed by profile name,
module and attribute, so a value is looked up once per process and
reused after (`docpipe/profile.py:152,166-169`).
Full mechanics (`component()`/`require()`, a profile's layout, why
`--profile` alone can be too late) are on [profiles](../profiles.md).

### Binding a stage's prompts at import time

A stage's config module calls `prompts.load()` at the moment Python
imports it, not inside a function that runs later: refinement binds
`SYSTEM_PROMPT = _REFINE.text` off `prompts.load("refinement/refine")`
this way (`docpipe/refinement/config.py:77-79`). Because `load()`
resolves through `active_profile()`, `DOCPIPE_PROFILE` must already be
set before that module is first imported, or the wrong prompts, or
none, get bound. The same module reads `_REFINE.meta` for
`LLM_TEMPERATURE` and `LLM_MAX_TOKENS` (`:81-84`; see Data model).

### Checking the server before the first document

`assert_serving()` calls `serving_limits()`, one `GET {base_url}/models`
request, 30 seconds and one retry by default
(`docpipe/llm_preflight.py:37,45`), and compares served model ids and
the smallest `max_model_len` reported against the tokens the stage
needs. It runs once per run, before any document, from four call
sites: refinement's `run()` (`docpipe/refinement/pipeline.py:165`) and
`main()` (`:247`); visuals (`docpipe/visuals/pipeline.py:501`, skipped
under `--dry-run`); and extraction's review pass and harvest
(`docpipe/extraction/runner.py:4012` and `:4081`).

### Rendering a prompt for one request

`Prompt.render(**values)` substitutes each `{{name}}` placeholder in a
prompt's body and raises `KeyError` naming any placeholder left unfilled
or any keyword not asked for (`docpipe/prompts.py:47-58`), so a
placeholder renamed in the Markdown file fails at the call site instead
of shipping a literal `{{foo}}` to the model.

### Recording prompt versions after a stage runs

After refinement or visuals writes its output, `prompts.record()` writes
each prompt's sha256 into `.prompt_versions.json`
(`docpipe/prompts.py:100-106`, called from
`docpipe/refinement/pipeline.py:79` and
`docpipe/visuals/pipeline.py:269`). The next run's `prompts.check()`
compares that file against today's prompts and returns the ids changed
(`docpipe/prompts.py:109-119`, called from
`docpipe/refinement/pipeline.py:66` and
`docpipe/visuals/pipeline.py:122`); a non-empty result decides whether
`--force-stale` is warranted.

### Resolving a caption while Stage 3 assembles a section

As `build_sections` appends a table's or a figure's placeholder to the
section text it is assembling, it calls `resolve_title(ref.caption,
current_section.content, block.id)` before the next block, settling the
caption the moment the section is written
(`docpipe/preprocessing/stage3_structure.py:399-401` for a table,
`:422-424` for a figure).

### Resolving a caption again, from the finished database

The same rule runs again, without a model, over rows already in SQLite:
once as a one-time backfill, `enrich_caption`, for the corpus
built before Stage 3 settled captions at write time
(`docpipe/chunking/database.py:214-243`), and once on every read, so a
document the backfill has not reached still shows a resolved title
(`section_item_captions`, `docpipe/inference/db.py:100-119`;
`fetch_owner_content`, which keeps the original as `caption_stored`,
`:242`). `enrich_caption` records the outcome in a `caption_source`
column, `'stage'` kept, `'section_text'` replaced; the resume logic
reads the same column: without `force=True` a row already marked is
skipped (`docpipe/chunking/database.py:229-232,243,260`).

## Data model

`Prompt` (`docpipe/prompts.py:35-41`) is a frozen dataclass: `id`
(`"<stage>/<name>"`), `text` (the body after any front matter, byte for
byte), `meta` (the parsed front matter, or `{}`; a stage's config reads
`temperature`/`max_tokens` off it, as refinement's does,
`docpipe/refinement/config.py:81-84`), `sha256` (over the whole raw
file) and `path`, which `path_for()` resolves to `<profile's
prompts_dir>/<stage>/<name>.md` (`:61-65`); `placeholders` extracts the
`{{name}}` tokens in `text` by regex (`:43-45`). `.prompt_versions.json`
is a JSON object mapping each prompt id to its current sha256, written
by `record()` next to a stage's output and read back by
`check()`/`stale()`.

`Profile` (`docpipe/profile.py:32-44`) is a frozen dataclass. A profile
author's own fields are on [profiles](../profiles.md); what belongs
here are the properties a stage reads once resolved:
`package_dir`, `prompts_dir`, `schema_sql`, and, under `root`
(`<repo>/data/<name>` unless overridden), `pdf_dir`, `processed_dir`
(`root/pdf/processed`, refinement's default input,
`docpipe/refinement/pipeline.py:244`), `db_path` (`<name>.db`) and
`index_path` (`faiss_index.bin`) (`docpipe/profile.py:85-121`). `Facet`
(`docpipe/profile.py:25-29`) is `field`, `label`, `widget`.

`artifacts.py` names seven plain string constants for files under a
document's own `results/` (`PAGES_JSON` through `DOCUMENT_JSON`), plus
`DIR_IMAGES` for the sibling `images/` folder
(`docpipe/artifacts.py:12-22`); the full table of who writes and reads
each one is on [artifacts](../artifacts.md).

`resolve_title(caption, content, block_id)` reads three loosely typed
values, not one record: `caption` is whatever Stage 2 already
linked, `content` is the owning section's assembled text, including
bracketed placeholders such as `[p85_tbl0]`, and `block_id` is that
placeholder's id without the brackets. It never raises: `caption`
already looking like one, a missing `content` or `block_id`, a
`block_id` absent from `content`, or no caption-like sentence before the
placeholder, all come back as `caption`, unchanged
(`docpipe/captions.py:61-73`).

## Configuration

| Name | Kind | Default | Effect | Where read |
|---|---|---|---|---|
| `DOCPIPE_PROFILE` | environment variable | unset | names the active profile; `resolve_profile()` writes it back | `docpipe/profile.py:20,124-149,178-197` |
| `--profile` | CLI flag | ambient `DOCPIPE_PROFILE` or none | passed through `resolve_profile()`; refused when named late on a prompt-overriding profile | `docpipe/profile.py:172-197` |
| `DOCPIPE_DATA_ROOT` | environment variable | unset, falls back to `<repo>/data` | base directory for `Profile.root`, unless `Profile.data_root` is set | `docpipe/profile.py:100-105` |
| `DOCPIPE_ENV_FILE` / `INFERENCE_ENV_FILE` | environment variables | unset; falls back to a bare `.env` | names a `.env` file to load before config reads `os.environ`; only the first readable one is loaded | `docpipe/dotenv.py:26-30` |
| `Profile.column_layout` | dataclass field | `"auto"` | must be `auto`, `single` or `double`, or `Profile()` raises | `docpipe/profile.py:37,49-50` |
| `Profile.data_root` / `Profile.home` | dataclass fields | `None` / `None` | override where a profile's data and package files live | `docpipe/profile.py:38-40` |
| `timeout` (`serving_limits`) | function parameter | 30.0 seconds | timeout for the preflight `GET /models` call | `docpipe/llm_preflight.py:37` |
| `max_retries` (OpenAI client) | hardcoded constant | 1 | preflight retried once before a connection failure is reported | `docpipe/llm_preflight.py:45` |
| `what` / `flag` (`assert_serving`) | function parameters | `"this stage"` / `"--max-model-len"` | substituted into the error and success log; each call site names itself | `docpipe/llm_preflight.py:58-59` |
| `_CAPTION_LIMIT` | module constant | 300 characters | caps the length of a title `resolve_title()` returns | `docpipe/captions.py:34` |

## Failure modes

`prompts.py`: `load()` with no profile passed and none ambient raises
`LookupError` naming the prompt id and the variable to set
(`docpipe/prompts.py:73-75`); for a prompt id the profile ships no file
for, `FileNotFoundError` naming the profile, the id and the path
(`:78-80`). `Prompt.render()` raises `KeyError` listing a missing
placeholder, an unexpected keyword, or both (`:52-57`). `check()` finding
`.prompt_versions.json` missing, unreadable or invalid treats the stored
map as absent, so every current prompt id is reported stale (`:113-119`).

`profile.py`: `Profile(name=...)` with an empty name, a slash, or an
unrecognised `column_layout` raises `ValueError`
(`docpipe/profile.py:46-50`). `load_profile()` with no name resolvable
raises `LookupError`, listing available profiles when the name given is
unknown (`:126-135`); a module exporting no proper `PROFILE`, or one
whose name disagrees with its own directory, raises `TypeError` or
`ValueError` (`:137-141`). `component()` re-raises `ModuleNotFoundError`
for an existing profile module that fails to import, not absence
(`:65-73`); `require()` raises `LookupError` for genuine absence
(`:76-82`). `resolve_profile()` raises
`SystemExit` when a profile named only on the command line, later than
process start, ships prompt overrides bound to whatever was ambient at
import time (`:186-197`). `profile_value()` raises the same
`LookupError` when no profile is ambient, naming the module, the
attribute and the environment variable to set (`:163-165`).

`llm_preflight.py`: a missing `openai` package raises `ImportError` with
an install hint (`docpipe/llm_preflight.py:39-42`). An unreachable
server, or one erroring on `GET /models`, raises `PreflightError`
wrapping the exception (`:48-50`); one serving zero models likewise
(`:52`). A requested model absent from what the server serves raises
`PreflightError` listing what it serves (`:65-70`). When no served
model card reports a usable `max_model_len`, the check warns and
returns without comparing, not fatally (`:72-75`); when the reported
limit is smaller than required, `assert_serving()` names both numbers
and the flag to raise (`:77-84`).

`captions.py`: `resolve_title()` never raises; Data model, above, lists
what leaves `caption` unchanged.

## Measured behaviour

Over one plan (Kassel), Stage 2's nearest-block caption linking attached
a rounding-note footnote to 15 of 89 tables in place of the sentence
naming the table (`docpipe/captions.py:8,45-47`; pinned by
`tests/test_table_title.py`). Because the caption is the only line of a
table a model can quote for its own year, that mislinking propagated to
240 of 379 tuples read off the twelve titled target tables' captions,
and to 88 of Kassel's 100 contested value identities
(`docpipe/captions.py:51-53`).

Over three of the corpus's eleven textless plans
`tests/test_table_title.py` measures by name (documents 795 Leipzig,
1082 Grevesmuehlen, 210 VG Maikammer), Stage 2's linking matched none of
169 tables, while 23 had a numbered sentence in the model-transcribed
text that `resolve_title()` could resolve; one carried 60 characters of
the following paragraph before the trim rule was added
(`docpipe/captions.py:76-83`). The figure covers only these three
plans, not all eleven.

A `--max-model-len` set too small for a stage's worst-case request was
not reported as one error at the start: truncated replies accumulated
across windows (42 of them, keeping their raw text, in the run
measured) before the preflight check existed
(`docpipe/llm_preflight.py:6-9`; the same figure opens
`tests/test_context_budget.py`).

Re-preprocessing the corpus's 1,082 documents so Stage 3 could settle
every caption at write time is stated as costing GPU days, so
`enrich_caption` runs instead as a one-time, additive backfill over the
finished database (`docpipe/chunking/database.py:225`).

## Verification

The boundary holds both directions: `test_core_imports_neither_profiles_nor_streamlit`,
`test_a_profile_provides_every_prompt_the_core_loads`,
`test_a_profile_carries_no_prompt_nobody_loads`,
`test_a_profile_provides_every_component_the_core_requires`
(`tests/test_architecture.py`).

A profile resolves to the right paths and identity, and a malformed one
raises a named exception: `test_kwp_profile_loads_and_names_itself`,
`test_paths_are_profile_scoped`, `test_data_root_default_follows_env`,
`test_unknown_profile_lists_the_available_ones`,
`test_no_profile_is_an_explicit_error`,
`test_ambient_profile_comes_from_the_environment`,
`test_rejects_unusable_names`, `test_rejects_unknown_column_layout`,
`test_facet_defaults_to_multiselect`, `test_components_are_optional`,
`test_a_broken_component_is_an_error_not_an_absence`,
`test_late_profile_is_refused_when_it_overrides_prompts`,
`test_late_profile_is_fine_without_prompts` (`tests/test_profile.py`).

A prompt loads, hashes and renders correctly, and a missing or stale one
is caught: `test_a_profile_ships_the_prompts_its_stages_load`,
`test_front_matter_becomes_meta_and_leaves_the_body_alone`,
`test_body_is_passed_through_byte_for_byte`,
`test_a_prompt_the_profile_does_not_have_is_an_error`,
`test_without_a_profile_there_is_no_prompt`,
`test_render_substitutes_and_catches_typos`,
`test_hash_changes_with_the_file`,
`test_stale_reports_changed_and_unversioned_results`,
`test_record_then_check_is_clean`, `test_check_flags_a_changed_prompt`,
`test_check_flags_results_without_a_version_file`,
`test_unusable_prompt_id` (`tests/test_prompts.py`).

The preflight stops a run before the first document, not after a
mid-run rejection: `test_preflight_rejects_a_server_with_too_little_context`,
`test_preflight_rejects_a_server_serving_another_model`,
`test_preflight_passes_when_the_context_fits`,
`test_preflight_reports_an_unreachable_server_as_such`
(`tests/test_context_budget.py`).

A title resolves to the sentence that names it, not a linked footnote, a
neighbour's caption, or past its own end:
`test_each_table_of_a_run_gets_its_own_caption`,
`test_three_appendix_tables_of_one_quantity_keep_their_years_apart`,
`test_a_caption_stage_two_did_link_is_never_replaced`,
`test_a_table_with_no_caption_of_its_own_does_not_borrow_the_last_one`,
`test_the_caption_taken_is_the_one_nearest_the_placeholder`,
`test_a_note_is_not_a_caption_and_a_numbered_phrase_is`,
`test_nothing_to_resolve_leaves_the_caption_alone`,
`test_the_table_a_run_reads_carries_the_resolved_title`,
`test_a_transcribed_page_still_yields_the_documents_own_caption`,
`test_a_caption_followed_by_prose_ends_where_the_caption_ends`
(`tests/test_table_title.py`).

The `.env` load precedes everything else, and an explicit environment
variable is never overwritten by the file: `test_it_reads_key_value_lines`,
`test_an_explicit_environment_variable_wins`,
`test_comments_blanks_and_quotes`, `test_a_missing_file_is_not_an_error`,
`test_the_value_reaches_the_config_that_reads_it`
(`tests/test_dotenv.py`).

## Modules

`artifacts.py` names the per-document result files under `<doc>/results/`
as string constants and performs no I/O, so a filename spelled out once
cannot drift between the module that writes it and the one that reads
it. Re-exported by four stages' `config.py` modules and by the
standalone `migrate_artifact_names.py`, which renames old filenames.

`profile.py` defines `Profile` and `Facet`, resolves the active profile,
and provides the `component()`/`require()`/`profile_value()` lookup the
core uses to pull the Python objects a profile contributes. Imported
throughout, including `prompts.py`, `refinement/config.py`,
`preprocessing/stage3_structure.py` and `extraction/runner.py`
(Position in the pipeline, above, names the rest).

`prompts.py` loads a profile's Markdown prompt files, splits optional
YAML front matter from the body, hashes the raw file, substitutes
`{{placeholder}}` values and writes or reads `.prompt_versions.json`.
Called at import time by every config module binding a system prompt,
and at request time by `preprocessing/page_text_fallback.py`,
`extraction/runner.py` and `inference/kg_route.py`;
`record()`/`check()` run from the refinement and visuals pipelines.

`llm_preflight.py` asks an OpenAI-compatible server which models it
serves and how large its context window is, raising `PreflightError`
before the first document if the model or the window is unsuitable.
Called once per run from refinement, extraction (review and harvest)
and visuals (skipped under `--dry-run`).

`captions.py` decides whether a stored caption already looks like one
(`looks_like_a_caption`) and, if not, resolves the real title from the
sentence before its placeholder (`resolve_title`). Called from the write
side while Stage 3 assembles a section, and from the read side both as
`chunking/database.py`'s one-time backfill and on every read by
`inference/db.py`.
