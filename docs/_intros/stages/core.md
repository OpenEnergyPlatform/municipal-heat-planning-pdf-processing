## Purpose

`docpipe/artifacts.py`, `docpipe/profile.py`, `docpipe/prompts.py`,
`docpipe/llm_preflight.py`, `docpipe/reading.py`, `docpipe/captions.py`,
`docpipe/usage.py` and `docpipe/jsonl.py` are the eight modules this page
documents together (the
`SOURCES` manifest of `scripts/build_docs.py` groups them under this page).
Each is imported by a different subset of
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
do what is asked (`llm_preflight.py`), what a model's reply is when it was
asked to be one JSON object and why it is none when it is not (`reading.py`),
once a caption-linking rule
elsewhere attaches the wrong sentence to a table, where the real title
sits (`captions.py`), how many tokens a run spent, summed across
processes that come and go (`usage.py`), and where one line of a JSON
Lines file ends (`jsonl.py`).

The eight files share a property none of the numbered stages needs: a
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

None of these eight modules sits between an upstream and downstream step;
each is imported by whichever stage is running, none writes its own
`results/` file, and none runs from the command line by itself. In
place of an In/Out table, what each module supplies and who reaches for
it is:

| Module | Supplies | Reached from |
|---|---|---|
| `profile.py` | the active `Profile`: paths, prompts directory, `component()`/`require()` | every stage's pipeline or CLI module, plus preprocessing's and refinement's `config.py`; inference only via `wording.py`, no CLI |
| `prompts.py` | a prompt's text and sha256, plus a staleness check against `.prompt_versions.json` | preprocessing, refinement, visuals, extraction, inference load; refinement and visuals record/check |
| `artifacts.py` | the filename of every per-document result file, spelled out once, and the one listing of the document directories that hold them (`document_dirs`) | preprocessing, refinement, visuals, chunking |
| `llm_preflight.py` | a check, before a stage's first document, that its server can do what is asked, reply schemas included; the window the server reported, and the room a cut-off unit is asked once more with | refinement, visuals, page transcription (preprocessing), extraction |
| `reading.py` | the one JSON object a reply was asked to be, or the cause it is not one; the profile's sentences that name the cause (`reading.PHRASES`) | refinement, visuals, page transcription, and the chat (`inference/llm_client.py`) |
| `captions.py` | the rule for where a table's or figure's real title sits, with the patterns that open a caption read from the profile in force | preprocessing (write time); chunking, inference (read time) |
| `usage.py` | token/request counting, on once a process calls `begin(stage)` | refinement, visuals, chunking and extraction call `begin()`; every reply or embedding call in those four books through `add()`/`reply()` |
| `jsonl.py` | the lines of a JSON Lines text or file, split at the line feed and nowhere else | extraction (the harvest reader, the decisions file, review, remap, top-up, recheck, identity) and the cassette of [the provider layer](providers.md) |

The closest thing any of the eight holds to a resume rule is
`prompts.py`'s staleness check (Method). `profile.py` also memoizes
`profile_value()` in memory for one process, not a resume rule;
`artifacts.py`, `llm_preflight.py` and `jsonl.py` keep no state of their own,
and `captions.py` and `reading.py` keep only what they compiled or checked once
per profile (the patterns, the table of sentences);
`usage.py` keeps counts in memory and periodically flushes
them, not a resume rule either since a flush always overwrites the same
row.

## Method

### Loading the environment before anything reads it

`docpipe/__init__.py` calls `dotenv.load_dotenv()` the moment any code
imports `docpipe`. It reads the first readable of `DOCPIPE_ENV_FILE`,
`INFERENCE_ENV_FILE`, or a bare `.env`, filling in only keys not already
set, so an exported value is never replaced by the file. It then applies the
project file, `docpipe.toml`, for the names still unset (`settings.apply()`;
see [the command and its settings](command.md)). Both precede prompt binding,
or an unset `LLM_API_KEY` is captured empty.

### Resolving the active profile

A stage's `__main__` first calls `bind_command_line()`, which copies a
`--profile` given on the command line into `os.environ[DOCPIPE_PROFILE]`
before the stage is imported (`docpipe/profile.py:415-432`). It reads the
flag with a small argparse parser and `parse_known_args`, as the stage's own
parser does, so an abbreviation of `--profile` that the stage accepts, with a
space or an equals sign before the name, is bound too; the parser raises where argparse would print
a usage and exit (`_Quiet`), and a line it cannot read is left to
the stage's own parser (the `except ValueError` in `bind_command_line`). The CLI entry
point then calls `resolve_profile(args)`, which reads `--profile` or
`DOCPIPE_PROFILE`, imports `profiles/<name>/profile.py` through
`load_profile()`, and writes the resolved name back into
`os.environ[DOCPIPE_PROFILE]` (`docpipe/profile.py:446-469`);
`require_profile(args)` is the same call for a stage that has nothing to
run without a profile, and refuses in one line naming the available
profiles when none is given (`docpipe/profile.py:472-479`); the chat does not go
through it, its answer loop falls back to the built-in profile
(`docpipe/inference/wording.py`, `chat_profile`). Code with
no command line calls `active_profile()` instead, reading only the
ambient variable (`docpipe/profile.py:376-380`). A third function,
`profile_value(module, attr)`, resolves through `active_profile()` too,
then caches its result in a module-level dict keyed by profile name,
module and attribute, so a value is looked up once per process and
reused after (`_values`, kept by `profile_value`).
Full mechanics (`component()`/`require()`, a profile's layout, why
`--profile` alone is enough) are on [profiles](../profiles.md).

### Reading a stage's prompts on first use

A stage's config module does not call `prompts.load()` when Python
imports it. It wraps the read in a function decorated with
`prompts.per_profile`, which runs it on first use and once per ambient
profile (`docpipe/prompts.py:100-117`), so a stage can be imported, and
print its usage, before anybody has named a profile. Refinement reads
`refine_prompt()` this way (`docpipe/refinement/config.py:77-83`), and
`system_prompt()`, `llm_temperature()` and `llm_max_tokens()` take the
text and the front matter off it (`:86-98`; see Data model);
`refinement/split.py` and `visuals/config.py` do the same. What a config
module binds on import is the refinement `WINDOW_SIZE`
(`docpipe/refinement/config.py:39-41`), which reads `active_profile()`
when the module loads, so `DOCPIPE_PROFILE` must be set before that
module is first imported; `bind_command_line()` sets it for a
`python -m` run.

### Checking the server before the first document

`assert_serving()` (`docpipe/llm_preflight.py:304`) calls `serving_limits()`, one `GET {base_url}/models`
request, 30 seconds and one retry by default
(`docpipe/llm_preflight.py:136,141`), and compares served model ids and
the smallest `max_model_len` reported against the tokens the stage
needs. It runs once per run, before any document, from these call sites:
refinement's `run()` (`docpipe/refinement/pipeline.py:200`) and
`main()` (`:290`); visuals (`docpipe/visuals/pipeline.py:590`, skipped
under `--dry-run`); page transcription (`docpipe/preprocessing/pipeline.py:478`),
asked before the first page that lacks its text and not before the first
document; and extraction's review pass and harvest
(`docpipe/extraction/runner.py:5426` and `:5512`). A hosted API is asked the
same through `_hosted_serving`, and besides whether the model answers inside
a reply schema; a replay of a recorded run has no server to ask and takes the
window the recording was planned for. A server that reports no
`max_model_len` is not let off: the window comparison is skipped with a
warning, and the one-token request that probes the request fields is sent all
the same, because a gateway or a local runner is the likeliest to refuse them.
A window one token short of the budget is refused before any request is sent,
and one exactly as large is enough.

A stage that sends its reply schema as the grammar of every request (refinement,
the visuals stage, page transcription) passes `shapes` too, `{name: schema}`:
refinement `refined_sections` and `section_cuts`, the visuals stage `table_reply`
and `figure_reply`, page transcription `page_reply`. After the window and the
request fields, `assert_reply_schemas` puts each schema to the server once, as
the stage will send it: one request of 32 tokens per schema, with the
reasoning settings every request carries; that the capped reply is cut short is
no matter, it is not read. These stages ask for JSON in no other way, so a
server that refuses one schema refuses every request of the run. Only a 4xx other than 429 is a
refusal, and it raises `PreflightError` naming the schema, the model and the
status. A server that is busy or down (a 429, a 5xx, no answer) gives no verdict:
it is logged, `assert_reply_schemas` returns a sentence, and the run asks anyway.
Extraction and the chat pass no shapes.

The window the server reports at the preflight is kept for the run, by role
(`served_window(role)`; none for a server or a hosted API that reports none, and
for a caller that ran no preflight). The refinement, visuals and
page-transcription stages use it for one thing: the room of the one further
attempt at a unit whose reply was cut off and that cannot be split (a lone
section, an outline of one segment, an image, a page). `further_room(asked,
reply=, budget=, role=)` gives it in tokens as `min(2 x asked, reply + window -
budget)`. *budget* is the stage's largest request, the prompt, the largest input
and one largest reply of *reply* tokens, which the preflight checked the window
against, so what the window holds beyond it is free for every request of the run.
The result is None where it is no more than *asked*: the unit is a hole `cut_off`
then and nothing is sent. Where the window is not known, or the caller states no
budget, the room is twice *asked*. Each stage's budget is one largest reply
(`refinement.config.max_request_tokens`, `visuals.config.max_request_tokens`,
`page_text_fallback.page_request_tokens`).

### Reading a model's reply as one JSON object

Refinement, the visuals stage, page transcription and the chat ask a model for
one JSON object, inside a reply schema, and read what comes back through
`docpipe/reading.py` and nowhere else. `reading.read(choice, key, of)` takes the
first choice of a response (`first`; a response without one is an empty reply)
and returns `(object, "", "")` for a reply that is exactly one JSON object with
`key` in it as an instance of `of` (a list for a window's sections, text for a
table's markdown, `object` for a key of any kind, which still has to be there).
Otherwise it returns `(None, cause, sentence)`. Whitespace around the object is
no text; anything else around it is. Nothing is stripped (a code fence, a
`<think>` block), nothing is cut out of surrounding text, no bracket is closed,
and nothing is salvaged from a reply that was cut off: each of those turned a
defective answer into content that then stood in a file as if it had been read.

The cause says why the reply is not the object. In the order the checks run:
`missing_key` (an object, but the key is absent or of another type),
`reasoning_only` (no text, the answer went into the reasoning), `cut_off` (no
readable object, and the reply ended at its token limit; an empty reply with no
reasoning that did is a cut-off too), `empty`, `no_object` (text with no `{`), `syntax` (a `{` from
which no complete object can be read, with the position of the break),
`outside_text` (one complete object with text beside it) and `not_an_object`
(well-formed JSON that is a list, a string or a number). `wrong_shape` is the
label a stage gives an object that was read well and is no use to it (a window
whose list holds no section); `read` never gives it. The names and their order
are the harvest's (`extraction.runner._reply_fault`), which keeps its own reader
and its own sentences; a test holds the two against each other. The sentence
is empty for `cut_off`: that reply is never asked again as it stands, the stage
splits the request or gives the unit more room.

A `Hole(cause, detail)` is a unit (a window, a cut request, an item, a page) that ended without a result and the reason it has none. The
causes are those above plus `refused` (the server rejected the request itself,
a 4xx other than 429), `not_served` (the server did not answer) and `error` (a
failure of the stage's own after the reply arrived); they are
`reading.HOLE_CAUSES`, and a hole with another cause raises `ValueError`.
`detail` is for the log and decides nothing.

The sentences the model hears are the profile's. `profiles/<name>/reading.py`
carries a table `PHRASES`, in the language of the profile's prompts for these
stages; `reading.phrases()` lays it over the tables of the profiles it extends,
entry by entry (`profile.layers`), and checks the result against
`reading.REQUIRED`, ten names: `shape_rule` (what is said back whatever went
wrong: the shape that was asked for, appended to every cause), `reasoning_only`,
`empty`, `no_object`, `syntax`, `outside_text`, `not_an_object`, and
`key_missing`, `key_not_a_list`, `key_not_text`, the three the key check says.
A profile that lacks one raises `LookupError` naming it, and the three stages
call `reading.phrases()` in their `main` before the first request, so the gap is
found there and not in the middle of the first document. The built-in
`default`, `kwp` and `scenarios` profiles each provide all ten, in English,
because the prompts of these stages are English in all three (the scenarios
profile's extraction prompts are German, and `extraction.PHRASES` is a
different table: the harvest's own). `reading.say(name, **values)` fills in a
sentence of the profile in force, and `reading.speaking(profile)` makes the
sentences a given profile's inside a block, which the chat uses when it answers
on the built-in profile because none is in force.

### Rendering a prompt for one request

`Prompt.render(**values)` substitutes each `{{name}}` placeholder in a
prompt's body and raises `KeyError` naming any placeholder left unfilled
or any keyword not asked for (`docpipe/prompts.py:50-61`), so a
placeholder renamed in the Markdown file fails at the call site instead
of shipping a literal `{{foo}}` to the model.

### Recording prompt versions after a stage runs

After refinement or visuals writes its output, `prompts.record()` writes
each prompt's sha256 into `.prompt_versions.json`
(`docpipe/prompts.py:132-138`, called from
`docpipe/refinement/pipeline.py:78` and
`docpipe/visuals/pipeline.py:317`). The next run's `prompts.check()`
compares that file against today's prompts and returns the ids changed
(`docpipe/prompts.py:141-151`, called from
`docpipe/refinement/pipeline.py:65` and
`docpipe/visuals/pipeline.py:156`); a non-empty result decides whether
`--force-stale` is warranted.

### Counting tokens across a run

`usage.begin(stage)` (`docpipe/usage.py:110`) turns counting on for the
calling process, once; each of the four batch entry points calls it at
start, and it reads the profile in effect then. From then on,
`usage.reply(response, model)` books a chat
completion's `prompt_tokens`/`completion_tokens` straight off the
server's own usage block (nothing if the reply carries none), together with
the input tokens the provider served from its cache (`cached_of`: the
`cached_tokens` the hosted adapters put on the usage block, or the
`prompt_tokens_details` of a server of one's own, 0 where the reply says
nothing), and
`usage.add(model, ...)` books an embedder's real token count, padding
excluded. Counts accumulate in memory per model and are written into
`DOCPIPE_USAGE_DB` (default `data/usage.db`, table `token_usage`, one
row per `run`/`stage`/`model`, with the `profile` of the run and its
`cached_tokens`, which are part of `input_tokens`) every `FLUSH_SECONDS` (60) while requests
keep coming back, and once more at exit (`atexit`); a flush always
writes the same absolute counts, so writing twice never double-counts. A
ledger written before the two columns existed gets them on the next write,
and the view is rebuilt; a read never writes, so an older ledger is read as
it is, its rows no profile's (`usage.unattributed` counts them).
`python -m docpipe.usage [path] [--profile P]` or `sqlite3 ... "SELECT * FROM
token_totals"` sums every row by stage and model (the view gains a
`cached_tokens` column); `--profile` limits the report to the runs of one
profile, named as the stages name it, and with a `[prices]` table in the
project file the report ends with a cost, where `cost(row, prices, cached)`
prices a cached input token at the model's `cached` price and, without one,
at its `input` price. A process that never
calls `begin()` counts nothing: the inference app, the tests, and
library use are silent by design, as is the 1-token preflight probe in
`llm_preflight.py`. A database that cannot be written is logged once and
never stops the run. A ledger already upgraded to the new columns cannot be
written by an older revision of the package, whose insert fails once and loses
its counts, so jobs that share a ledger need one revision.

### Resolving a caption while Stage 3 assembles a section

As `build_sections` appends a table's or a figure's placeholder to the
section text it is assembling, it calls `resolve_title(ref.caption,
current_section.content, block.id)` before the next block, settling the
caption the moment the section is written
(`docpipe/preprocessing/stage3_structure.py:418-420` for a table,
`:441-443` for a figure). What opens a caption is the profile's:
`captions.py` holds no pattern and reads the list `preprocessing.CAPTION_START`
of the profile in force (the built-in `default` profile where none is named),
joins it into one pattern and compiles it once per profile
(`docpipe/captions.py:40-71`).

### Resolving a caption again, from the finished database

The same rule runs again, without a model, over rows already in SQLite:
once as a one-time backfill, `enrich_caption`, for the corpus
built before Stage 3 settled captions at write time
(`docpipe/chunking/database.py:222-251`), and once on every read, so a
document the backfill has not reached still shows a resolved title
(`section_item_captions`, `docpipe/inference/db.py:131-153`;
`fetch_owner_content`, which keeps the original as `caption_stored`,
`:273`). `enrich_caption` records the outcome in a `caption_source`
column, `'stage'` kept, `'section_text'` replaced; the resume logic
reads the same column: without `force=True` a row already marked is
skipped (`docpipe/chunking/database.py:237-240,251,268`).

## Data model

`Prompt` (`docpipe/prompts.py:38-44`) is a frozen dataclass: `id`
(`"<stage>/<name>"`), `text` (the body after any front matter, byte for
byte), `meta` (the parsed front matter, or `{}`; a stage's config reads
`temperature`/`max_tokens` off it, as refinement's does,
`docpipe/refinement/config.py:90-98`), `sha256` (over the whole raw
file) and `path`, which `path_for()` resolves to `<prompts_dir>/<stage>/<name>.md`
of the profile, else of the nearest profile it extends (`:64-75`). That is
how a profile that extends the built-in one writes every prompt itself except
those that are the built-in file byte for byte: `kwp` inherits one
(`visuals/caption_keep`) and `scenarios` two (that one and the chat's
`inference/json_format`),
so the text read and its sha256 are the ones its own copy had, and
`tests/test_default_profile.py` holds the list (see [profiles](../profiles.md));
`placeholders` extracts the
`{{name}}` tokens in `text` by regex (`:46-48`). `.prompt_versions.json`
is a JSON object mapping each prompt id to its current sha256, written
by `record()` next to a stage's output and read back by
`check()`/`stale()`.

`Profile` (`docpipe/profile.py:169-186`) is a frozen dataclass. A profile
author's own fields are on [profiles](../profiles.md); what belongs
here are the properties a stage reads once resolved:
`package_dir`, `prompts_dir`, `schema_sql`, and, under `root`
(`<repo>/data/<name>` unless overridden), `pdf_dir`, `processed_dir`
(`root/pdf/processed`, refinement's default input,
`docpipe/refinement/pipeline.py:286`), `db_path` (`<name>.db`) and
`index_path` (`faiss_index.bin`) (`docpipe/profile.py:267-318`). `Facet`
(`docpipe/profile.py:161-166`) is `field`, `label`, `widget`.

`artifacts.py` names eight plain string constants for files under a
document's own `results/` (`PAGES_JSON` through `DOCUMENT_JSON`), plus
`DIR_IMAGES` for the sibling `images/` folder
(`docpipe/artifacts.py:21-33`); the full table of who writes and reads
each one is on [artifacts](../artifacts.md). `document_dirs(root, *markers)`
(`docpipe/artifacts.py:49`) lists the document directories under a root at any
depth, in path order: a directory that holds any of the marker files is a
document and is not searched further, any other is searched (with a guard
against links that loop), and with every document directly under the root it
gives what iterating the root gave, in the same order. Two directories of one
name under different subfolders raise `DuplicateDocumentName`, a `ValueError`
naming both places, unless `distinct=False`; `refuse_same_names` is the
check on its own.

`resolve_title(caption, content, block_id)` reads three loosely typed
values, not one record: `caption` is whatever Stage 2 already
linked, `content` is the owning section's assembled text, including
bracketed placeholders such as `[p85_tbl0]`, and `block_id` is that
placeholder's id without the brackets. It never raises: `caption`
already looking like one, a missing `content` or `block_id`, a
`block_id` absent from `content`, or no caption-like sentence before the
placeholder, all come back as `caption`, unchanged
(`docpipe/captions.py:99-111`). The list of patterns it reads is checked on
first use: a list that is empty, a bare string, a pattern that does not
compile or one that matches the empty text (which would make every text a
caption) is a `ValueError` naming the profile, and a standalone profile with
no `CAPTION_START` at all is a `LookupError`.

## Configuration

| Name | Kind | Default | Effect | Where read |
|---|---|---|---|---|
| `DOCPIPE_PROFILE` | environment variable | unset | names the active profile; `resolve_profile()` writes it back | `docpipe/profile.py:45,350-373,446-469` |
| `--profile` | CLI flag | ambient `DOCPIPE_PROFILE` or none | copied into `DOCPIPE_PROFILE` by `bind_command_line()` before a stage is imported; passed through `resolve_profile()`, or `require_profile()` where a profile is needed; refused when named after a stage was imported under another profile and the named one ships prompts | `docpipe/profile.py:409-479` |
| `DOCPIPE_DATA_ROOT` | environment variable | unset, falls back to `data/` beside the project file, else `<repo>/data` | base directory for `Profile.root`, unless `Profile.data_root` is set | `docpipe/profile.py:298-302`, `323-337` |
| `DOCPIPE_ENV_FILE` / `INFERENCE_ENV_FILE` | environment variables | unset; falls back to a bare `.env` | names a `.env` file to load before config reads `os.environ`; only the first readable one is loaded | `docpipe/dotenv.py:76-80` |
| `Profile.column_layout` | dataclass field | `"auto"` | must be `auto`, `single` or `double`, or `Profile()` raises | `docpipe/profile.py:172,191-192` |
| `Profile.data_root` / `Profile.home` | dataclass fields | `None` / `None` | override where a profile's data and package files live | `docpipe/profile.py:173-175` |
| `timeout` (`serving_limits`) | function parameter | 30.0 seconds | timeout for the preflight `GET /models` call | `docpipe/llm_preflight.py:136-137` |
| `max_retries` (OpenAI client) | hardcoded constant | 1 | preflight retried once before a connection failure is reported | `docpipe/llm_preflight.py:141` |
| `what` / `flag` (`assert_serving`) | function parameters | `"this stage"` / `CONTEXT_FLAG` (`"--max-model-len"`) | substituted into the error and success log; each call site names itself | `docpipe/llm_preflight.py:305-306`, `:47-48` |
| `shapes` (`assert_serving`) | function parameter | none | `{name: schema}`, the reply schemas a stage sends as the grammar of every request; each is put to the server once before the first document | `docpipe/llm_preflight.py:308` |
| `reading.PHRASES` | profile component (`reading.py`) | none; required, ten names (`reading.REQUIRED`) | the sentences a stage says to the model when its reply was not the one JSON object; checked before the first request | `docpipe/reading.py:60-64`, `:87-105` |
| `preprocessing.CAPTION_START` | profile component | none; each profile lists its own | the non-empty list of regular expressions, each carrying its own anchor, that open a caption | `docpipe/captions.py:40-71` |
| `_CAPTION_LIMIT` | module constant | 300 characters | caps the length of a title `resolve_title()` returns | `docpipe/captions.py:31` |
| `DOCPIPE_USAGE_DB` | environment variable | `data/usage.db` | SQLite file the token counts are written to | `docpipe/usage.py:91-92` |
| `cached` price | key of a `[prices]` entry in the project file | the model's `input` price | per million tokens, what an input token costs that the provider served from its cache | `docpipe/settings.py` (`PRICED`), `docpipe/usage.py` (`cost`) |

## Failure modes

`prompts.py`: `load()` with no profile passed and none ambient raises
`LookupError` naming the prompt id and the variable to set
(`docpipe/prompts.py:83-85`); for a prompt id that neither the profile nor
a profile it extends ships a file for, `FileNotFoundError` naming the
profile, the id and the path (`:88-92`). `Prompt.render()` raises `KeyError`
listing a missing placeholder, an unexpected keyword, or both (`:54-60`).
`check()` finding `.prompt_versions.json` missing, unreadable or invalid
treats the stored map as absent, so every current prompt id is reported
stale (`:144-151` and `stale()`, `:160-161`).

`profile.py`: `Profile(name=...)` with an empty name, a slash, an
unrecognised `column_layout` or an `extends` that names the profile itself
raises `ValueError` (`docpipe/profile.py:188-194`). `load_profile()` with no
name resolvable raises `LookupError` (`:352-355`), listing available profiles
when the name given is unknown (`:364-366`); a module exporting no proper
`PROFILE`, or one whose name disagrees with its own directory, raises
`TypeError` or `ValueError` (`:368-372`). `component()` re-raises
`ModuleNotFoundError` for an existing profile module that fails to import, not
absence (`_own`, `:246-252`); `require()` raises `LookupError` for genuine
absence (`:255-264`). `resolve_profile()` raises
`SystemExit` when it is given a profile other than the one a stage was
imported under and that profile ships prompts (`:460-467`);
`require_profile()` raises it, naming the available profiles, when no
profile is given (`:475-478`). `profile_value()` raises the same
`LookupError` when no profile is ambient, naming the module, the
attribute and the environment variable to set (`:395-396`).

`llm_preflight.py`: a missing `openai` package raises `ImportError` with
an install hint (`docpipe/llm_preflight.py:139-146`). An unreachable
server, or one erroring on `GET /models`, raises `PreflightError`
wrapping the exception (`:147-151`); one serving zero models likewise
(`:152-153`). A requested model absent from what the server serves raises
`PreflightError` listing what it serves (`:333-338`). When no served
model card reports a usable `max_model_len`, the check warns and does not
compare, not fatally, and still asks the request fields (`:340-342`, `:357`);
when the reported limit is smaller than required, `assert_serving()` names
both numbers and the flag to raise (`:343-350`). The two probes of the request
fields, `assert_request_extras` and `assert_reply_schema`, return `None` when
the server accepted them and a sentence when it could not be asked (down,
busy, a 5xx); that is no verdict and the settings go out anyway. A 429 counts
as no verdict as well and not as a refusal, for every caller of
`assert_serving`. `assert_request_accepted` picks the probe by role, the
reply schema for a hosted API and the reasoning settings otherwise; the
doctor uses it. `assert_reply_schemas`, the probe of a stage's own schemas,
raises `PreflightError` only for a 4xx other than 429 on one of them, and
otherwise returns `None` or a sentence naming the schemas it could not ask.

`reading.py`: `phrases()` with no profile passed and none in force raises
`LookupError` naming the variable to set; a profile that provides no
`reading.PHRASES` raises it through `profile.require`, and one whose table
lacks a name of `REQUIRED` raises `LookupError` listing the names missing
(`docpipe/reading.py:87-105`). A `Hole` with a cause outside `HOLE_CAUSES`
raises `ValueError` (`:52-55`). `read()` raises nothing for a reply it cannot
read: it returns the cause. Every sentence is checked when `phrases()` is first
called for a profile, which the three stages do at the start of the run, so a
missing one is found there and not when `read()` first needs it.

`captions.py`: `resolve_title()` never raises; Data model, above, lists
what leaves `caption` unchanged.

## Measured behaviour

Over one plan (Kassel), Stage 2's nearest-block caption linking attached
a rounding-note footnote to 15 of 89 tables in place of the sentence
naming the table (`docpipe/captions.py:8,83-85`; pinned by
`tests/test_table_title.py`). Because the caption is the only line of a
table a model can quote for its own year, that mislinking propagated to
240 of 379 tuples read off the twelve titled target tables' captions,
and to 88 of Kassel's 100 contested value identities
(`docpipe/captions.py:89-91`).

Over three of the corpus's eleven textless plans
`tests/test_table_title.py` measures by name (documents 795 Leipzig,
1082 Grevesmuehlen, 210 VG Maikammer), Stage 2's linking matched none of
169 tables, while 23 had a numbered sentence in the model-transcribed
text that `resolve_title()` could resolve; one carried 60 characters of
the following paragraph before the trim rule was added
(`docpipe/captions.py:114-121`). The figure covers only these three
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
finished database (`docpipe/chunking/database.py:222`).

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

The reader takes exactly one object and nothing else, names the cause the way
the harvest does, and has no sentence for a cut-off reply:
`test_only_the_one_object_is_read`, `test_it_reads_what_the_harvest_reads`,
`test_a_reply_is_not_made_right_by_what_surrounds_it`,
`test_a_reply_is_classified_like_the_harvests`,
`test_the_guard_against_drift_sees_a_cause_that_changed`,
`test_a_response_without_a_choice_is_an_empty_reply`,
`test_the_key_has_to_be_of_the_type_asked_for`,
`test_a_key_of_any_kind_still_has_to_be_there`,
`test_a_cut_reply_has_no_sentence_for_the_retry`,
`test_the_retry_names_the_cause`, `test_a_hole_names_only_known_causes`,
`test_a_hole_is_a_value_that_cannot_be_changed`,
`test_a_caller_with_a_profile_of_its_own_speaks_through_it`,
`test_a_profile_in_force_speaks_unless_a_block_names_another`
(`tests/test_reading.py`). Every profile carries every sentence, and none of the
stages that read a reply softens one: `test_no_stage_repairs_a_reply`
(`tests/test_architecture.py`, one case per module of refinement, the visuals
stage and page transcription, with
`test_the_stages_scanned_are_the_ones_that_read_a_reply` holding the list). The
preflight puts each reply schema to the server, and only a 4xx other than 429
refuses one: `test_a_server_that_refuses_the_cut_schema_ends_refinement_before_any_document`,
`test_a_server_that_takes_every_schema_lets_refinement_go_on`
(`tests/test_stage_preflight.py`) and the cases of `tests/test_llm_preflight.py`. The window the preflight
found is kept for the role that asked, a later preflight that finds none replaces
it, a replay keeps the window of the recorded run, and the room of a cut-off
unit follows from it: `test_the_window_a_server_reports_is_kept_for_the_role_that_asked`,
`test_each_role_keeps_the_window_of_its_own_server`,
`test_a_later_preflight_that_finds_no_window_replaces_the_one_found_before`,
`test_a_server_that_was_refused_leaves_no_window`,
`test_a_hosted_api_that_reports_a_window_has_it_kept`,
`test_a_replay_keeps_the_window_of_the_recorded_run`,
`test_the_room_is_the_smaller_of_twice_and_the_reply_plus_what_is_left`,
`test_a_hosted_model_that_reports_its_window_is_held_to_it`
(`tests/test_room.py`).

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

A record whose quote carries U+2028, U+2029 or U+0085 stays one record, read
and written back: `test_a_line_ends_at_a_line_feed_and_nowhere_else`,
`test_reading_a_file_folds_the_carriage_return`,
`test_the_harvest_reader_keeps_a_row_whose_quote_carries_one`,
`test_a_decision_with_one_in_its_note_is_read`,
`test_a_recorded_answer_with_one_is_replayed`,
`test_a_file_written_back_keeps_such_a_row_whole`,
`test_no_reader_splits_a_files_text_at_more_than_the_line_feed`
(`tests/test_jsonl.py`).

## Modules

`artifacts.py` names the per-document result files under `<doc>/results/`
as string constants, so a filename spelled out once cannot drift between the
module that writes it and the one that reads it, and lists the document
directories that hold them (`document_dirs`), the one listing every stage and
the migration use. Re-exported by four stages' `config.py` modules and used by
the standalone `migrate_artifact_names.py`, which renames old filenames.

`profile.py` defines `Profile` and `Facet`, resolves the active profile,
and provides the `component()`/`require()`/`profile_value()` lookup the
core uses to pull the Python objects a profile contributes. Imported
throughout, including `prompts.py`, `refinement/config.py`,
`preprocessing/stage3_structure.py` and `extraction/runner.py`
(Position in the pipeline, above, names the rest).

`prompts.py` loads a profile's Markdown prompt files, splits optional
YAML front matter from the body, hashes the raw file, substitutes
`{{placeholder}}` values and writes or reads `.prompt_versions.json`;
`per_profile` defers a stage's read of its prompts to first use. Called on
first use by the refinement (`config.py`, `split.py`) and visuals
(`config.py`) modules, at import time by `inference/llm_client.py`, and at
request time by `preprocessing/page_text_fallback.py`,
`extraction/runner.py` and `inference/kg_route.py`;
`record()`/`check()` run from the refinement and visuals pipelines.

`llm_preflight.py` asks the provider's list of models which models it
serves and how large its context window is, raising `PreflightError`
before the first document if the model or the window is unsuitable. A hosted
model that cannot answer inside a reply schema is refused there too (see
[the provider layer](providers.md)), and a server that refuses a reply schema a
stage sends as its grammar is refused there too (`assert_reply_schemas`). It keeps
the window the server reported (`served_window`) and gives the room of the one
further attempt at a unit whose reply was cut off and that cannot be split
(`further_room`). Called once per run from refinement, extraction (review and harvest),
visuals (skipped under `--dry-run`) and page transcription, which asks before
the first page that lacks its text; the doctor sends its request-field
probe on its own.

`reading.py` reads a model's reply as exactly one JSON object or says why it is
none (`read`, `loads_object`, `first`), names the causes (`CAUSES`,
`HOLE_CAUSES`, `Hole`), and holds the profile's sentences that say the cause back
to the model (`phrases`, `say`, `speaking`, `REQUIRED`). Called by the
refinement, visuals and page-transcription stages and by the chat's reader
(`inference/llm_client.py`); the harvest does not call it. Each profile's table
is its own `reading.py`.

`captions.py` decides whether a stored caption already looks like one
(`looks_like_a_caption`) and, if not, resolves the real title from the
sentence before its placeholder (`resolve_title`), by the patterns of the
profile in force (`preprocessing.CAPTION_START`) and none of its own. Called from the write
side while Stage 3 assembles a section, and from the read side both as
`chunking/database.py`'s one-time backfill and on every read by
`inference/db.py`.

`usage.py` counts each stage's chat and embedding requests in memory and
writes them, one row per run/stage/model, with the run's profile and the
cached input tokens, into a SQLite file
(`DOCPIPE_USAGE_DB`, default `data/usage.db`), flushed periodically and
at exit. Turned on by `begin()` at each of the four call sites in
Position in the pipeline, above, and booked from every reply and
embedding call site those four stages make.

`jsonl.py` splits the text of a JSON Lines file into its lines at the line
feed and nowhere else (`lines`), and reads a file that way (`read`, which
folds a carriage return before the line feed into the line feed).
`str.splitlines()` also breaks at U+2028, U+2029 and U+0085, and a quote copied
from a PDF can carry one of them, which `json.dumps(ensure_ascii=False)` writes
as it is: read with `splitlines()`, that record would become two broken ones.
Every reader of a harvest, of the decisions file and of a cassette goes through
it, and a test holds that no reader in the package splits a file's text with
`splitlines()`.
