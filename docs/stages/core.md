# The parts every stage uses

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
supplies (`profile.py`), which file carries a stage's prompt, what text
a prompt written in two halves makes, and whether a result on disk still
matches it (`prompts.py`), what a
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
receives one" (`docpipe/profile.py:6`). Three further checks in the same file hold the reverse:
every prompt id the core loads is something each profile with prompts
on disk supplies, every
component or attribute pair the core requires is something each
profile supplies, and no
profile carries a prompt file that neither the core nor the profile's
own code ever requests. What a profile itself
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
| `prompts.py` | a prompt's text and sha256, composed from the core's template and the profile's parts where a profile's file names a template, plus a staleness check against `.prompt_versions.json` | preprocessing, refinement, visuals, extraction, inference load; refinement and visuals record/check |
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
before the stage is imported (`docpipe/profile.py:421-438`). It reads the
flag with a small argparse parser and `parse_known_args`, as the stage's own
parser does, so an abbreviation of `--profile` that the stage accepts, with a
space or an equals sign before the name, is bound too; the parser raises where argparse would print
a usage and exit (`_Quiet`), and a line it cannot read is left to
the stage's own parser (the `except ValueError` in `bind_command_line`). The CLI entry
point then calls `resolve_profile(args)`, which reads `--profile` or
`DOCPIPE_PROFILE`, imports `profiles/<name>/profile.py` through
`load_profile()`, and writes the resolved name back into
`os.environ[DOCPIPE_PROFILE]` (`docpipe/profile.py:452-475`);
`require_profile(args)` is the same call for a stage that has nothing to
run without a profile, and refuses in one line naming the available
profiles when none is given (`docpipe/profile.py:478-485`); the chat does not go
through it, its answer loop falls back to the built-in profile
(`docpipe/inference/wording.py`, `chat_profile`). Code with
no command line calls `active_profile()` instead, reading only the
ambient variable (`docpipe/profile.py:382-386`). A third function,
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
profile (`docpipe/prompts.py:208-225`), so a stage can be imported, and
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

### Composing a prompt from a template and a profile's parts

`load()` finds the file the profile has for the prompt, its own or that of the
nearest profile it extends (`_find`, `docpipe/prompts.py:157-167`), and splits
the front matter off. A file without a `template` key is returned as it is
written: its text is the body and its sha256 is that of the file. A file with
the key is a parts file, which `load()` hands to `_composed`
(`docpipe/prompts.py:202-203`, `685-792`). That asks the module of the stage
for its templates (`TEMPLATE_MODULES`, `docpipe/prompts.py:85`; only the
extraction stage has them, in `docpipe/extraction/contract.py`, see [the
extraction stage](extraction.md)), takes the language from the profile that
holds the file, reads the template (`read_template`,
`docpipe/prompts.py:345-482`) and the file's sections (`read_parts`,
`docpipe/prompts.py:486-509`), and puts the two together (`_compose`,
`docpipe/prompts.py:571-668`).

The marks of a template are listed in the module docstring
(`docpipe/prompts.py:15-51`): `{{name}}` where a part or a fact goes,
`<!-- block: name -->` and `<!-- /block -->` around a stretch of contract text
that a profile may word itself or leave out, `<!-- rule: name -->` for a numbered
rule and `{{rule:name}}` for a reference to it. A parts file is a front matter
and sections that start with a line `<!-- part: name -->`. Composition puts
each part in the slot of its name. A part with the name of a block replaces the
block, and keeps the whitespace the block ended with. A block named under
`without` in the front matter is dropped, and is refused if the template does
not list it as omittable. The rules that are left are numbered from 1 without a
gap, and the references follow the numbers. The facts are filled in last. A
block mark or a slot that stands alone on its line takes the line with it, so
an absent optional part or a dropped block leaves no blank line, and a part is
trimmed of the blank lines around it and nothing else.

What does not fit fails at load with `PromptPartsError`
(`docpipe/prompts.py:103-123`), which names the prompt, the part or block, the
profile and the parts file and template file. The causes are a part that is
missing, empty, repeated or not known to the template (with the nearest name
offered), text before the first part, a part whose place is gone, a `without`
entry that is no block, not an omittable one, or also worded by a part, a
reference to a rule that is not in the prompt, a `{{` or `<!--` left in a part
or in the text, a profile that declares no `CONTRACT_LANGUAGE` or one the core
has no templates for, a template the core lacks in that language, and a
`template` key on a stage that has no templates. Nothing is filled in for what
is missing.

The sha256 of a composed prompt is that of the file a person would have written
by hand: the front matter without the two loader keys (`LOADER_KEYS`,
`docpipe/prompts.py:83`), then the composed text. `Prompt.meta` leaves the two
keys out as well, so what a stage reads from it, `temperature` and
`max_tokens`, is what it read from a plain file; the loader refuses a front
matter that cannot be written without them line by line, since the sha256
would not be a hand-written file's. `Prompt.composition` says how a text was
made (see Data model).

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
(`docpipe/extraction/runner.py:5450` and `:5538`). A hosted API is asked the
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
and its own sentences. The sentence
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
or any keyword not asked for (`docpipe/prompts.py:143-154`), so a
placeholder renamed in the Markdown file fails at the call site instead
of shipping a literal `{{foo}}` to the model.

### Recording prompt versions after a stage runs

After refinement or visuals writes its output, `prompts.record()` writes
each prompt's sha256 into `.prompt_versions.json`
(`docpipe/prompts.py:240-246`, called from
`docpipe/refinement/pipeline.py:78` and
`docpipe/visuals/pipeline.py:317`). The next run's `prompts.check()`
compares that file against today's prompts and returns the ids changed
(`docpipe/prompts.py:249-259`, called from
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
calls `begin()` counts nothing: the inference app and
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

`Prompt` (`docpipe/prompts.py:126-137`) is a frozen dataclass: `id`
(`"<stage>/<name>"`), `text` (the body after any front matter, byte for
byte; for a parts file the text composed from the template and the parts),
`meta` (the parsed front matter, or `{}`; a stage's config reads
`temperature`/`max_tokens` off it, as refinement's does,
`docpipe/refinement/config.py:90-98`), `sha256` (over the whole raw
file; for a parts file over the file a person would have written by hand, see
Composing a prompt), `path`, which `path_for()` resolves to `<prompts_dir>/<stage>/<name>.md`
of the profile, else of the nearest profile it extends (`:157-174`), and
`composition`, `None` for a plain file and for a parts file a mapping with the
`template` (its name), the `language`, the `overrides` (the blocks the profile
words itself), the `omitted` blocks and `what_if`, the text with one omitted
block put back for each of them, made the first time it is read
(`:795-814`). `owner_of()` gives the profile whose file the prompt is
(`:177-180`).  `.prompt_versions.json`
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
`index_path` (`faiss_index.bin`) (`docpipe/profile.py:273-324`). `Facet`
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
| `DOCPIPE_PROFILE` | environment variable | unset | names the active profile; `resolve_profile()` writes it back | `docpipe/profile.py:45,356-379,452-475` |
| `--profile` | CLI flag | ambient `DOCPIPE_PROFILE` or none | copied into `DOCPIPE_PROFILE` by `bind_command_line()` before a stage is imported; passed through `resolve_profile()`, or `require_profile()` where a profile is needed; refused when named after a stage was imported under another profile and the named one ships prompts | `docpipe/profile.py:415-485` |
| `DOCPIPE_DATA_ROOT` | environment variable | unset, falls back to `data/` beside the project file, else `<repo>/data` | base directory for `Profile.root`, unless `Profile.data_root` is set | `docpipe/profile.py:304-308`, `327-341` |
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
(`docpipe/prompts.py:189-191`); for a prompt id that neither the profile nor
a profile it extends ships a file for, `FileNotFoundError` naming the
profile, the id and the path (`:194-198`). `Prompt.render()` raises `KeyError`
listing a missing placeholder, an unexpected keyword, or both (`:147-153`).
`check()` finding `.prompt_versions.json` missing, unreadable or invalid
treats the stored map as absent, so every current prompt id is reported
stale (`:252-259` and `stale()`, `:268-269`). A parts file that cannot be
composed raises `PromptPartsError` (`:103-123`), a `ValueError` that names the
prompt, the part or the block, the profile and both files (see Composing a
prompt, above).

`profile.py`: `Profile(name=...)` with an empty name, a slash, an
unrecognised `column_layout` or an `extends` that names the profile itself
raises `ValueError` (`docpipe/profile.py:188-194`). `load_profile()` with no
name resolvable raises `LookupError` (`:358-361`), listing available profiles
when the name given is unknown (`:370-372`); a module exporting no proper
`PROFILE`, or one whose name disagrees with its own directory, raises
`TypeError` or `ValueError` (`:374-378`). `component()` re-raises
`ModuleNotFoundError` for an existing profile module that fails to import, not
absence (`_own`, `:252-258`); `require()` raises `LookupError` for genuine
absence (`:261-270`). `resolve_profile()` raises
`SystemExit` when it is given a profile other than the one a stage was
imported under and that profile ships prompts (`:466-473`);
`require_profile()` raises it, naming the available profiles, when no
profile is given (`:481-484`). `profile_value()` raises the same
`LookupError` when no profile is ambient, naming the module, the
attribute and the environment variable to set (`:401-402`).

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
naming the table (`docpipe/captions.py:8,83-85`; pinned by). Because the caption is the only line of a
table a model can quote for its own year, that mislinking propagated to
240 of 379 tuples read off the twelve titled target tables' captions,
and to 88 of Kassel's 100 contested value identities
(`docpipe/captions.py:89-91`).
 The figure covers only these three
plans, not all eleven.

A `--max-model-len` set too small for a stage's worst-case request was
not reported as one error at the start: truncated replies accumulated
across windows (42 of them, keeping their raw text, in the run
measured) before the preflight check existed
(`docpipe/llm_preflight.py:6-9`; the same figure opens).

Re-preprocessing the corpus's 1,082 documents so Stage 3 could settle
every caption at write time is stated as costing GPU days, so
`enrich_caption` runs instead as a one-time, additive backfill over the
finished database (`docpipe/chunking/database.py:222`).

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
it.

## Module reference

The docstring of each module of this stage, verbatim from the code and generated by `scripts/build_docs.py`. The chapter above is the account; this is the reference. Edit the docstring, not this page.

<details>
<summary><code>docpipe/artifacts.py</code></summary>

artifacts.py: Names the per-document result files under `<doc>/results/`,
in the order the pipeline writes them, and finds the document directories
that hold them.

One definition serves all five pipeline modules: a filename spelled out in
four separate config.py files drifts, and the module that reads a file is
rarely the one that wrote it. The same goes for the listing: preprocessing
writes a nested folder of PDFs to a nested folder of document directories,
and a stage that lists only the first level loses every document below it,
so every stage lists through `document_dirs`.

Author: Felix Vossel

</details>

<details>
<summary><code>docpipe/prompts.py</code></summary>

prompts.py: Loads a profile's prompts, one Markdown file per stage, from
`profiles/<profile>/prompts/<stage>/<name>.md`.

There is no core default for what a prompt says about a corpus. A prompt names
the corpus it is written for and the language it answers in, and the core
knows neither: a fallback here could only be some other project's prompt,
which is worse than a missing file. A profile that extends another one has
asked for that profile's prompts where it wrote none itself, and gets exactly
those.

Optional YAML front matter carries the model parameters that belong to the
prompt (temperature, max_tokens), so the two never drift apart.

One kind of prompt is written in two halves. A prompt of the extraction stage
that names a template in its front matter (`template: rows`) is a parts file:
the profile writes what is about its corpus (the role, the examples, the
sentences about its own tables), and the core's contract text of the profile's
language (docpipe/extraction/contract.py) says the rest, once. `load` puts the
two together, so a request, a stamp and the render tool see one prompt. A file
without a `template` key is read as it always was.

A parts file is a front matter and sections that each start with a line
`<!-- part: name -->`. A template is a text with these marks:

    {{name}}                 where a part goes, or a fact the code fills in
    <!-- block: name -->     a stretch of contract text a profile may word
    <!-- /block -->          itself (a part of the same name replaces it) or,
                             where the template allows it, leave out
                             (`without: [name]`)
    <!-- rule: name -->      a numbered rule; the number is written at load,
    {{rule:name}}            counted over the rules that are left, and a
                             reference gives it, so omitting a rule moves the
                             numbers and what points at them

The mark of a block and the slot of a part take their line with them when they
stand alone on it: an absent optional part and an omitted block leave no blank
line behind. A part put in a block's place keeps the whitespace the block ended
with, so the lines around it stay. A block may stand more than once, and then
it can be left out but not worded, since one part cannot say two places. A part
keeps its own lines as written, apart from the blank lines around it; it may
use a fact and a reference to a rule, and nothing else with double braces. The
template's front matter says what it has: `required` and `optional` parts,
`blocks`, and the `omittable` ones among them.

Whatever does not fit fails at load with `PromptPartsError`, which names the
prompt, the part or block, the profile and the two files: a part that is
missing, a part the template does not know, a part whose place is gone, a block
that cannot be left out, a reference to a rule that is not there, a mark or a
double brace that is left in the text. Nothing is filled in for a part that is
missing.

Every prompt has a sha256 over its file. Stages record those hashes with
their output; when a hash no longer matches, the result was produced by a
different prompt and is stale (see `stale()`). A composed prompt has the
sha256 of the file a person would have written by hand: its front matter
without the two keys of the loader, and the text that is sent.

Author: Felix Vossel

</details>

<details>
<summary><code>docpipe/profile.py</code></summary>

profile.py: A profile is everything a project contributes to the generic
pipeline: where its documents come from, what extra tables it needs, which
prompts it overrides and which filters its app offers.

The core never imports a profile; it receives one.

A profile is a directory. It is found by its name on a search path, first
match first: the directories $DOCPIPE_PROFILE_PATH names, `profiles/` of the
project, what installed packages register under the entry-point group
`docpipe.profiles`, `profiles/` beside this package, and last the profile
this package brings itself (`builtin/default`). So a project keeps its
profile in its own repository, and `--profile` also takes the directory
itself.

A profile may extend another one (`extends="default"`). What it does not
provide itself, a module's attribute, a prompt, the schema of its tables,
is then taken from the profile it extends. Nothing is taken from a profile
that was not named: a profile without `extends` stands alone, and a part it
lacks is an absence, as before.

Author: Felix Vossel

</details>

<details>
<summary><code>docpipe/llm_preflight.py</code></summary>

llm_preflight.py: Asks the server what it can do, before the first
document.

A stage knows what one request costs it (`config.max_request_tokens()`);
the server knows how much context it was started with. Nothing compared
the two, so a `--max-model-len` set too small surfaced as a slow trickle
of truncated replies hours into a run, with 42 windows silently keeping
their raw text, instead of as a single error within the first second.

Two questions, both answered by the provider's list of models:
  * does it serve the model the stage is about to request?
  * is its context at least as large as the worst-case request?

A hosted API is asked a third: does the model answer inside a reply schema?
That is the only way a hosted model is asked for JSON (see `providers`), so
a model that cannot is refused here and not after the first document.

A stage that sends its reply schema as the grammar of every request
(refinement, the visuals stage, page transcription) has each of its schemas
put to the server once, as that stage will send it (`assert_reply_schemas`): a
server that refuses one refuses every request of the run.

What the preflight learns about the window stays with the run: a unit whose
reply was cut off and that cannot be split is asked once more with as much
room as the window leaves (`further_room`), and the stage that asks has the
number from here and not from a second request to the server.

And one thing every stage agrees with the server about before it asks
anything: `request_extras`, the reasoning settings. They live here because
they are the same for every stage and because getting them wrong fails the
same way a window set too small does: hours in, as replies whose JSON was
truncated by the think block in front of it.

</details>

<details>
<summary><code>docpipe/reading.py</code></summary>

reading.py: The one JSON object a stage asked a model for, or why there is none.

Refinement, the visuals stage and page transcription ask for a JSON object
inside a reply schema. What comes back is read here, and read strictly: the
reply is that object and nothing else. Nothing is stripped (code fences, think
blocks), nothing is cut out of surrounding text, no bracket is closed, and
nothing is salvaged from a reply that was cut off. Every softener of that kind
turned a defective answer into content that then stood in a file as if it had
been read. A reply that is not exactly the object is classified instead, and
the stage asks again with the cause named (`say`), splits the request when the
reply was cut off, or ends the unit as a `Hole` that carries the cause.

The causes are the harvest's (`extraction.runner._reply_fault`), in its order;
a test holds the two against each other, so neither can drift. The harvest does
not call this module: it keeps its own reader and its own sentences.

The sentences the model hears are the profile's, in the language of that
profile's prompts for these stages (`profiles/<name>/reading.py: PHRASES`).

Author: Felix Vossel

</details>

<details>
<summary><code>docpipe/captions.py</code></summary>

captions.py: Defines what a caption looks like, and finds where a table's
title really sits.

Stage 2 links a caption block to a table by distance, and in a plan whose
tables carry a rounding footnote it links the footnote instead. The
sentence that names the table then stands unlinked in the section text, a
few words before the table's own placeholder. Measured over Kassel, 15 of
89 tables were captioned with the rounding footnote's own sentence rather
than their real title.

Both ends of the pipeline need the same rule about that: Stage 3, which
assembles the section text when the placeholder is written, and the read
side, which has only the finished database. A second copy of the rule is
how the section text and the stored title start disagreeing, the defect
this module exists to fix. So the rule lives above both.

Author: Felix Vossel

</details>

<details>
<summary><code>docpipe/usage.py</code></summary>

usage.py: Counts the tokens every run spends, into one SQLite file that
outlives the runs.

The model server reports what each request really cost: input and output
tokens on a chat reply, input tokens on an embedding. Until now those numbers
reached a log line at best and were gone with the job. Here they are summed per
stage and model and written as one row per run, so the total over every run is
a query:

    sqlite3 data/usage.db "SELECT * FROM token_totals"
    python -m docpipe.usage [--profile P]

One row per run instead of one counter that grows: a flush repeats the same
absolute numbers, so writing twice never counts twice, and a total can still be
split by stage, model or job afterwards.

Each row also says which profile the run was under and, where the provider
reports it, how many of the input tokens it served from its cache. A ledger
written before that has neither column: the first write adds them, and a read
never writes, so an older file stays readable as it is.

A process counts only after `begin(stage)`, which each stage's entry point
calls. The inference app, the tests and any library use record nothing. The
row is rewritten every FLUSH_SECONDS while requests come back and once more at
exit, so a job the scheduler kills loses at most that window. Counting must
never take a run down: a database that cannot be written is logged once and
the run goes on.

Author: Felix Vossel

</details>

<details>
<summary><code>docpipe/jsonl.py</code></summary>

jsonl.py: The lines of a JSON Lines file.

One record is one line, and a line ends at a line feed and nowhere else.
`str.splitlines()` also breaks at U+2028, U+2029 and U+0085, and
`json.dumps(ensure_ascii=False)` writes those three as they are. A quote
that carries one would be read as two broken records, and a file that is
read that way and written back would keep them broken.

Author: Felix Vossel

</details>

[Back to the index](../README.md)
