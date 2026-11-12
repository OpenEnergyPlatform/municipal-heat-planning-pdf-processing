## What a profile is

`docpipe/profile.py` states the idea in its own module docstring: a profile
is everything a project contributes to the generic pipeline, where its
documents come from, what extra tables it needs, which prompts it
overrides, and which filters its app offers (`docpipe/profile.py:2-4`). In
code that is one frozen dataclass, `Profile` (`docpipe/profile.py:169-186`):
`name` (required, and may hold neither `/` nor `\`), `column_layout` (one of
`"auto"`, `"single"`, `"double"`, default `"auto"`), `data_root` and `home`
(both optional path overrides), `facets` (a tuple of `Facet(field, label,
widget)` entries the answer app turns into filters), `title`,
`document_noun` (default `"document"`; a profile words it in its own language),
`extends` (the profile whose parts stand in for the ones this
one does not provide, see Extending a profile) and `documents_shareable`
(whether the text of the documents may be passed on; a recorded run is refused
without it, see [the provider layer](stages/providers.md)). `__post_init__`
checks the name, the column layout and that a profile does not extend itself,
and raises `ValueError` on any of them. A profile has no field for a language:
the language of a request and of an answer is the language of the profile's
prompts and sentence files.

A profile is not a subclass to write against. It is a directory,
`profiles/<name>/`, holding exactly one thing the core reads directly: a
`profile.py` exporting a module-level `PROFILE` whose own `name` field
matches the directory it lives in, checked by `load_profile()`
(`docpipe/profile.py:356-379`); a mismatch raises `ValueError` rather than
running a profile under the wrong identity. Everything else the directory
holds, source code, prompts, a spec, an ontology snapshot, is read only by
that profile's own modules or by the specific piece of `docpipe/` that asks
for it by name, described stage by stage below.

Three profiles ship. The built-in `default` profile
(`docpipe/builtin/default/`) is the one the package brings itself: any folder
of English documents, with no subject. It reads a folder of PDFs
(`docpipe ingest`), carries English prompts for every stage, the English
wording (the chat's labels in `inference.py`, the sentences each stage says to
the model outside its prompts in `prompts/<module>/phrases.json`, among them the
ones a model hears when its reply was not the one JSON object) and a catalog that
filters by subfolder, and has no extraction spec. `kwp` and `scenarios` both
extend it and write every part of their prompts themselves.

`kwp` covers German municipal heat plans, a corpus of
801 documents at the point its `column_layout` comment was written
(`profiles/kwp/profile.py:15`), and answers in German; its accepted
values go into MHPKG on the Open Energy Platform. `scenarios` covers
publications on climate and energy scenarios
(`profiles/scenarios/profile.py`), a 164-document harvest,
and answers in English; its values go
into OEKG on the same platform. Each has its own
page, [kwp](profiles/kwp.md) and [scenarios](profiles/scenarios.md), for
what its own modules do beyond the interface points here.

Every path a profile's data or files live under is derived from `name`
alone, never typed twice: `package_dir` is `profiles/<name>` unless `home`
overrides it, `prompts_dir` sits under that, `schema_sql` is that
directory's `schema.sql` if the file exists and `None` otherwise, read by
`docpipe/store/schema.py`'s `profile_sql()` and appended to the core
schema inside `apply()`'s one transaction
(`docpipe/store/schema.py:45-48,43`), and
`root`, `pdf_dir`, `processed_dir`, `db_path` and `index_path` all sit
under `data/<name>/` (or `$DOCPIPE_DATA_ROOT/<name>` or `data_root`) if set
(`docpipe/profile.py:273-324`). Two profiles run from the same checkout
therefore never share a file by accident.

## How the core finds and asks a profile

A profile is found by its name on a search path, first match first: the
directories `DOCPIPE_PROFILE_PATH` names, `profiles/` of the project, what
installed packages register under the entry-point group `docpipe.profiles`,
`profiles/` beside the package, and last the built-in `default`. So a project
keeps its profile in its own repository, and `--profile` also takes the
directory itself. `docpipe profiles` lists what is found and where.

`load_profile(name)` resolves the profile: `name`, or failing that
`$DOCPIPE_PROFILE`, names a directory whose `profiles.<name>.profile`
module it imports; an unknown name raises `LookupError` listing the
profile directories that exist (`docpipe/profile.py:356-372`). Nothing
under `docpipe/` imports a profile itself: its own docstring states the
rule in one line, "the core never imports a profile; it receives one"
(`docpipe/profile.py:6`).

Five entry points, preprocessing, refinement, visuals, extraction, and
chunking, reach `load_profile` through `resolve_profile(args)` rather than
calling it directly (`docpipe/preprocessing/pipeline.py:599`,
`docpipe/chunking/pipeline.py:418`), except that refinement, visuals and
extraction have nothing to run without a profile and go through
`require_profile(args)`, which refuses in one line naming the available
profiles when none is given (the chat is the one entry point that does not stop:
`wording.chat_profile` gives it the built-in `default` profile, see [the
chat](stages/app.md)) (`docpipe/refinement/pipeline.py:268`,
`docpipe/visuals/pipeline.py:555`, `docpipe/extraction/runner.py:5322`,
`docpipe/profile.py:478-485`). Each adds the `--profile` flag through
`add_profile_argument(parser)` (`docpipe/profile.py:415-418`).
`resolve_profile` reads `args.profile` or, failing that, `$DOCPIPE_PROFILE`,
loads the named profile, and writes the resolved name back into
`$DOCPIPE_PROFILE` (`docpipe/profile.py:452-475`).

The flag reaches the environment before the stage is imported. Each of the
five `docpipe/*/__main__.py` calls `bind_command_line()` first, which reads
the flag off `sys.argv` with a small argparse parser (`parse_known_args`), the way
the stage's own parser reads it, so an abbreviation of `--profile` that the stage
accepts, with a space or an equals sign before the name, is bound too, and sets `$DOCPIPE_PROFILE`
(`docpipe/profile.py:421-438`). A line it cannot read is left to the stage's own
parser to report (`:435-436`). So `--profile` alone
is enough, and a stage's usage text needs no profile: refinement and visuals
read their prompts on first use, once per ambient profile
(`prompts.per_profile`, `docpipe/prompts.py:208-225`), not when the module is
imported. What a stage binds on import is the refinement
`WINDOW_SIZE` (`docpipe/refinement/config.py:39-41`); the answer chat's
prompts are read on first use too, once per profile
(`docpipe/inference/llm_client.py:82` to `94`). `resolve_profile`
refuses one case rather than running it on a mix of two profiles: a caller
that imported a stage under one profile, or none, and then names another
that ships prompts is refused with `SystemExit` naming the fix
(`docpipe/profile.py:466-473`). Code with no command line calls
`active_profile()` instead, reading only `$DOCPIPE_PROFILE` and returning
`None` when the variable is unset (`docpipe/profile.py:382-386`).

| Name | Kind | Default | Effect | Where read |
|---|---|---|---|---|
| `--profile` | CLI flag | ambient `$DOCPIPE_PROFILE` or none | names the profile `resolve_profile` loads for this run; `bind_command_line()` copies it into `$DOCPIPE_PROFILE` before a stage is imported | `docpipe/profile.py:415-418`, `421-438` |
| `$DOCPIPE_PROFILE` | environment variable | unset | read by `load_profile`, `active_profile`, and `resolve_profile`; the last writes it back once a name is resolved | `docpipe/profile.py:45` |
| `$DOCPIPE_DATA_ROOT` | environment variable | unset, falls back to `data/` beside the project file, else `<repo>/data` | base directory for every profile's `root` (and therefore `pdf_dir`, `db_path`, `index_path`), unless `Profile.data_root` overrides it | `docpipe/profile.py:304-308`, `327-341` |

Once a `Profile` object exists, the core asks it through two lookups, and
through a third, narrower one for a single fact. `Profile.component(module,
attr)` imports
`profiles.<name>.<module>` and returns `getattr(loaded, attr, None)`; a
module the profile lacks is an absence, returning `None`, but one that
exists and fails to import is the profile's own bug and re-raises rather
than being swallowed as absence (`docpipe/profile.py:218-259`).
`Profile.require(module, attr)` is the same lookup with `LookupError` in
place of `None`, for a part the pipeline cannot run without
(`docpipe/profile.py:261-271`); `profile_value(module, attr)` is `require()`
against the ambient profile, cached once per `(profile.name, module,
attr)` for the process's life (`docpipe/profile.py:392-406`).

The third lookup is `Profile.own(module, attr)`: what the profile itself
declares in `profiles/<name>/<module>.py`, and nothing from the profiles it
extends (`docpipe/profile.py:229-233`). It is for a fact about the files a
profile owns and not about what it contributes: the language its extraction
prompts are written in, `extraction.CONTRACT_LANGUAGE` (see The extraction
prompts, below).

Which of the two a caller uses is a choice, not a fixed rule.
`docpipe/inference/kg_route.py`'s `hooks()` reads `kg.VALUE_QUERY` through
`component`, not `require`, so a profile with no answerable graph
(`scenarios`) is not forced to provide one; an absent one is no failure there.
`preprocessing.py`'s constants, by contrast, are all read through
`require` or `profile_value`, so their absence is a hard failure for any
profile the pipeline runs text through.

No test walks the profiles for these lookups. What holds a profile to what a
stage asks of it is the stage's own check, made when the stage first reads it:
`require()` raises a `LookupError` that names the attribute, and the three
modules that read sentences (`docpipe/extraction/wording.py`,
`docpipe/inference/wording.py`, `docpipe/reading.py`) check the sentences they
got against their `REQUIRED` names and name what is missing and the file that
should hold it. `docpipe doctor` runs the same checks for the profile in effect
without a model: the prompts each stage loads, and the wording lines
`prompts/extraction/phrases.json`, `prompts/inference/phrases.json` and
`inference.UI`. A profile that is never run and never checked is not looked at
by anything.

## Extending a profile

A profile that sets `extends="default"`, or the name of another profile, gets
what it does not provide from that profile. `Profile.component` walks the line
of profiles nearest first and returns the first attribute it finds;
`Profile.layers` returns the value of every profile along the line, for a
table a profile lays over the one it extends entry by entry. The wording
table `inference.UI` works that way: a profile writes only the labels it words
differently. So do the sentences a stage says outside its prompts, which are
files and not tables: `prompts/extraction/phrases.json`,
`prompts/inference/phrases.json` and `prompts/reading/phrases.json`, one JSON
object each, a sentence's name to its words. `docpipe/phrases.py` reads them
strictly and lays a profile's file over those of the profiles it extends,
entry by entry, the farthest first (`phrases.table`); a profile writes only
the sentences it words differently. The words of the picker are in `inference.UI` too (`version_current`, `version_old` and
`document_noun_fallback`): `kwp` says `(aktuell)`, `(alt)` and `Dokument`, the
built-in profile and `scenarios` `(current)`, `(old)` and `document`. A profile
that stands alone has to word all of `wording.UI_REQUIRED`, those three
included, or the app and the picker raise a `LookupError` naming what is
missing. A prompt it does
not have is the extended profile's, and so is `schema.sql`; a profile that adds
a column to `DocumentMeta` writes the whole file. `kwp` and `scenarios` write
every prompt themselves except those that are the built-in profile's byte for
byte, which they inherit: `visuals/caption_keep` for kwp, and for scenarios that
one and `inference/json_format`. Inherited means the built-in
file, so the text read, its hash and the stamp are what the copies had, and
`docpipe doctor` says `31 prompt file(s), 30 of its own` for kwp and `31 prompt
file(s), 29 of its own` for scenarios.  A later change to one of the two built-in prompts on the
list therefore reaches the profiles that inherit it, and its sha256 is entered
in `BEFORE` there; for `visuals/caption_keep` a changed hash also makes stage 3
say "described with older prompts" for stored documents. A prompt of the
extraction stage that is a parts file is inherited with its parts, and is read
in the language of the profile that holds the file (see The extraction prompts,
below).
`extraction.PROMPT_CHECKS` (the rule `prompt_checks`, like `CONTRACT_LANGUAGE`, `ALT_LABEL_LANGUAGE` and `FRAME`, which a profile's `extraction.py` hands out from its rules) is not laid over entry by entry: a profile that declares it holds the whole
list, and one that declares none keeps the list of the profile it extends.
Nothing is taken from a
profile that was not named. A profile without `extends` stands alone, and a
part it lacks is an absence, as before. A line of profiles that leads back to
itself is refused.

## The files a profile holds beside its code

Each profile folder holds files that say what its code would otherwise hold as
constants. `docpipe edit` shows and sets each of them.

| File | What it holds | Laid over the default's |
|---|---|---|
| `rules.json` | every value a run follows (`docpipe/rules.py`): quote minimum length, decimal mark, year range, span words, request letters, retry waits, image size, country groups, `not_extracted`, compute parts); a setting from the environment or the project file is laid over it, and a step of the flow may set its own value for a rule it reads (the rule's `steps`). Values of the machine (a model's address, slots per model, connections) are not set here but in the project file `docpipe.toml` | rule by rule |
| `sources.json` | the ontology, shapes and graph queries the profile is written against, the lists drawn from them and which coordinate answers from which list (`docpipe/sources.py`); read by the profile's `vocabulary.py` through `sources()`, `sets()` and `axis_sets()` | not inherited |
| `graph.json` | the drawing of the graph (`map`: boxes, arrows and bricks), the classes not written, address rules, the effect of each constraint and the rules the one writer, `docpipe/extraction/graph.py`, follows: which reading wins, how front pages are found, how different numbers on one place are settled, whether a value two passages print is marked as confirmed, the base IRI (`docpipe/graphfile.py`, applied by `serialize.apply_graph_file`) | not inherited |
| `flow.json` | the drawing of the reading (boxes and frames), the numbers that bound it and the values a step or frame sets for the rules it reads | number by number; a drawing of its own is the whole drawing |
| `flows/<name>.json` | a follow-up pass as a flow of its own (`top_up`, `top_up_open`, `top_up_parameters`, `remap`, `recheck`, `review`, `start_at`, `example`); the default profile ships all of them, and a profile may write a file of the same name | the nearest file of the profile's line is the flow |
| `rules.py` | `RULES`, the rules the profile's own code follows, and `GRAPH`, the rules of its graph writer; the code knows name, kind, bounds and help, never the value | not inherited |

## The profile interface, stage by stage

The table lists every `(module, attribute)` pair `docpipe/` or its
entry-point scripts asks a profile for, grouped by stage, with what each
shipped profile provides.

| Stage | Module.attribute | Required or optional | `kwp` provides | `scenarios` provides |
|---|---|---|---|---|
| Getting the documents in | `source.SOURCE` | required to run the stage (`component`, `docpipe/ingest/cli.py:76`) | a class over the KWW Excel sheet | a class over the crawl's `pdf_index.json` |
| Getting the documents in | `source.backfill_meta` | optional, for `--backfill-meta` (`component`, `docpipe/ingest/cli.py:67`) | provided (`profiles/kwp/source.py:199`) | not provided; the flag ends the run |
| Reading the page | `preprocessing.HYPHEN_EXCEPTIONS` | required (`profile.require`, `docpipe/preprocessing/page_text.py:45`) | German continuation words ("und", "oder", ...) | English ones ("and", "or", ...) |
| Reading the page | `preprocessing.CAPTION_MAX_WORDS` | required (`profile_value`, `docpipe/preprocessing/config.py:182`) | 45 (median caption 8 words, 205 past 40, `profiles/kwp/preprocessing.py:35-39`) | 160 (journal/IPCC captions run 60 to 150 words, `profiles/scenarios/preprocessing.py:39-43`) |
| Reading the page | `preprocessing.CAPTION_START` | required, a non-empty list of regular expressions each carrying its own anchor (`profile.require`, `docpipe/captions.py:64-71`); an empty list, a bare string or a pattern that does not compile or matches the empty text is a `ValueError` naming the profile, a missing list a `LookupError` | one German-shaped pattern: a word, a number, a colon ("Tabelle 17:") | the same pattern; the built-in profile adds letter-numbered forms ("Table A.1:") and the colon-less forms ("Figure 3.", "Fig. 2", "Table 1 Annual totals") only where a text, a line or a sentence begins |
| Reading the page | `preprocessing.TITLE_EXCLUDE_PREFIXES` | required (`profile_value`, `docpipe/preprocessing/config.py:192`) | "abbildung", "tabelle", and their abbreviations | "figure", "table", "box", "plate", and their abbreviations |
| Reading the page | `preprocessing.DIRECTORY_FIGTAB_WORDS` | required (`profile_value`, `docpipe/preprocessing/sections.py:211`) | German figure/table list openers | English ones |
| Reading the page | `preprocessing.DIRECTORY_TITLE_WORDS` | required (`profile_value`, `docpipe/preprocessing/sections.py:250`); fragments of a pattern joined with `\|`, matched case-insensitively anywhere in a section title; an empty list never matches | "inhalt", "verzeichnis", "contents", "directory" | the same four, which keeps every verdict where they were |
| Reading the page | `preprocessing.BIBLIOGRAPHY_TITLE_WORDS` | required (`profile_value`, `docpipe/preprocessing/sections.py:234`) | "literatur", "quellen", ... | "references", "bibliography", ... |
| Repairing the text | `refinement.WINDOW_SIZE` | optional (`component`, `docpipe/refinement/config.py:41`) | not set, falls back to 3 | not set, falls back to 3 |
| Repairing the text, the visuals, page transcription, the answer app | the file `prompts/reading/phrases.json` | required, laid over the extended profile's file entry by entry (`phrases.table`, `docpipe/phrases.py`); checked as a set against `reading.REQUIRED`, ten names, by `reading.phrases()` before the first request of refinement, of the visuals stage and of page transcription, and in the chat when a reply was not the one object asked for | the ten sentences said to a model whose reply was not the one JSON object, in English, the language of the profile's prompts for these stages | the same ten, in English; its extraction prompts are German and `prompts/extraction/phrases.json` is another file |
| The answer app | `catalog.CATALOG` | optional (`component`, `docpipe/inference/catalog.py:158`) | `KwpCatalog`: municipality, Land, year | `ScenarioCatalog`: year, venue |
| The answer app | the file `prompts/inference/phrases.json` | required, laid over the extended profile's file (`phrases.table`); checked at first use against `wording.REQUIRED` (`wording.phrases`) | German phrasing, 32 keys | English phrasing, same 32 keys |
| The answer app | `inference.READOFF_MARKER`, `READOFF_NOTE` | required at first use (`profile.require`, variable `attr`, `docpipe/inference/wording.py`) | German | English |
| Reading the values out | the file `prompts/extraction/phrases.json` | required, laid over the extended profile's file (`phrases.table`), checked against `wording.REQUIRED` (`docpipe/extraction/wording.py`) | German sentences the stage writes to the model | German sentences, the language of its extraction prompts |
| Reading the values out | `extraction.PROMPT_CHECKS` | optional, read by `docpipe preflight` (`component`); a profile that declares none has the extended profile's | none: an empty tuple since 2026-11-08, when the field and rows prompts it checked went | none |
| Reading the values out | `extraction.CONTRACT_LANGUAGE` | required of a profile that holds a parts file: the language of the core's template the file is put together with, read from the profile that owns the file (`Profile.own`, `docpipe/extraction/contract.py:85-88`) and not inherited | `"de"` | `"en"` for scenarios and the built-in profile |
| Reading the values out | `extraction.ALT_LABEL_LANGUAGE` | required by the profile's own `vocabulary` module (`profile.require`), not by the core: the language tag of the alternative labels a vocabulary snapshot keeps (`ontology.index` and `ontology.build` take it as `language`, with no default) | `"de"` | `"en"` for scenarios and the built-in profile |
| Reading the values out | rule `not_extracted` | optional, in the profile's `rules.json` (declared by its `rules.py`), read by `docpipe preflight`: a table `(shape, property)` to one sentence, the properties of the profile's shapes it leaves out on purpose | not set | 21 entries, each with its reason |
| Reading the values out | `extraction.shapes_files` | optional (`component`), read by `docpipe preflight`: a callable returning the SHACL files the graph is held against; the shapes line says "skipped" for a profile without it or without a refresh | the MHPKG shapes of the last refresh | the shapes file of the last refresh of the OEKG sources |
| Reading the values out | `extraction.SPEC_PATH` | required in practice; refused with `SystemExit` otherwise (`component`, `docpipe/extraction/runner.py:5433-5436`) | `extraction_spec.json` | `extraction_spec.json` |
| Reading the values out | `extraction.FRAME` | optional (`component`, `runner.main`): the frame coordinates, the ones the plan's base and target years date a value by | `("scenario", "year")`; each value is asked them for itself | not provided |
| Reading the values out | the key `of` of the spec's plan fields `base_year` and `target_year` (the profile hooks `BASE_YEAR` and `TARGET_YEAR` were deleted on 2026-11-10) | optional, checked by `spec.load` (`spec._validate_of`): which frame pairs are the plan's own state and its target; only the passes over a stored harvest (`--top-up`, `--top-up-open`) read it, to say where the plan's own years are looked for. A year answer naming only the plan's word for one of them ("Basisjahr", "Zieljahr") is read when its number is one of the plan's years | `{"scenario": "status_quo"}` and `{"scenario": "target"}` | not provided; no state has years |
| Reading the values out | the file `flow.json` of the profile's folder | optional for a profile that extends another: the `numbers` it sets differently, laid over the inherited file number by number, and the `flow` (the drawing) where it draws otherwise; the default profile's file is the whole flow, `numbers` and `flow` (`extraction.flow`) | not provided; the default's numbers are read | not provided; the default's numbers are read |
| Reading the values out | `extraction.document_axes` | optional (`component`, `docpipe/extraction/runner.py:5505`) | not provided | the study regions this publication names, out of 249 (`profiles/scenarios/regions.json`) |
| Reading the values out | `extraction.document_context` | optional (`component`, `docpipe/extraction/runner.py:5510`) | the plan's own municipality name | not provided |
| The knowledge graph | the `map` (drawing) of the profile's `graph.json`; `kg.BRICKS` for the bricks only the profile needs | required for `--serialize`: every profile's graph is written by the core's program from its drawing (`docpipe/extraction/graph.py`), and a graph file without a drawing is refused with the reason (`parser.error`) | the drawing of tuples to MHPKG Turtle | the drawing of tuples to OEKG Turtle |
| The answer app | `kg.VALUE_QUERY` plus six more attributes, and `inference.ROUTE_NOTES` | optional; absent returns `None` (`component`, `docpipe/inference/kg_route.py:104-106`), present but missing any of the other seven raises `LookupError` instead (`111-114`), all eight present builds the route | provided; the app can answer a coordinate question straight from the graph | not provided; the app never queries a graph |

Two entries say more than the table. `prompts/extraction/phrases.json` names
the key of a list as well as its sentences. A request names the list of a
closed coordinate through `say("frame_options", slot=<coordinate name>)`, and
`frame_options` is one of the phrases a profile has to have. `kwp` and `scenarios` say `"scenarios"`, one list
for every closed coordinate, and the built-in profile says `"{slot}_options"`,
one list per coordinate.

`extraction.PROMPT_CHECKS` is a tuple of entries `(what is checked, prompt id,
passage, has to be there)`: a passage the profile's prompts have to hold
(`True`) or must not hold (`False`), in the language of those prompts and in the
text a request sends, which for a parts file is the composed one. None of the
shipped profiles declares one since 2026-11-08.
The shapes of a profile's graph are its own as well: `extraction.shapes_files`
says where they are and the rule `not_extracted` which of their properties it
leaves out on purpose, and `docpipe preflight` warns about the rest (see [the
extraction stage](stages/extraction.md)).

Two more phrases of `prompts/extraction/phrases.json` are keys and not sentences:
`option_means` and `option_spellings`, the keys an entry of a closed list goes
to the model under. They are `means` and `spellings` in the built-in profile,
`kwp` and `scenarios` alike; kwp said them in German before, and
a profile that extends one of them has no reason to word them differently.

## How a prompt is written

Every prompt is compact, precise and unambiguous (owner decision 2026-11-05).
It starts with the result a request returns, and it keeps every rule that
decides which answer is correct, the field names, the reply format and what a
missing or unsure value means, and nothing else. An example stays only where it
settles a concrete ambiguity. A prompt is split into two requests where it
holds two decisions that can be checked apart and the split gains something
concrete: the second decision comes only with a hit, needs reference data of
its own or is asked again on its own. Otherwise it stays one request. The
prompts only the field-by-field flow sent, `queries`, `places`, `frame`, `rows`
and `field`, are gone (2026-11-08); `anchors`, `review`, `example` and the core's
contract templates were left as they are.

## The extraction prompts: the core's template and a profile's parts

Two prompts of the extraction stage, `review` and `example`, are written in two
halves (the templates of `rows`, `field` and `frame` went with the field-by-field
flow on 2026-11-08). The core holds the contract text of each, in German and in
English, as a template under `docpipe/extraction/contract/<language>/<name>.md`:
what the reply looks like, that the quote stands in a shown passage, that the
answer stands in the quote, what "not stated" is. A profile's own file holds what
is about its corpus: the role, the examples, the sentences about its own tables.
A file that names a template in its front matter, `template: review`, is a parts
file, and `docpipe/prompts.py` puts it together with the template of the
profile's language when the prompt is loaded. A request, a stamp and
`scripts/render_prompts.py` see the composed prompt and never the two halves.
The other extraction prompts (the requests of the harvest, `transcribe`, `find`,
`docfield`, `coord`, `search`, `list`, `check`, `follow` and `names`, the compute,
`phrase` and `anchors`) and every prompt of the other stages are plain files, read as they are
written.

A parts file is a front matter and sections that each start with a line
`<!-- part: name -->`. This is the whole of kwp's review prompt:

```markdown
---
template: review
without: [corpus_language]
temperature: 0
max_tokens: 1024
---
<!-- part: role -->
Du liest deutsche kommunale Wärmepläne ("Kommunale Wärmeplanung").

<!-- part: example_reply -->
{"value": 241.0, "unit": "MWh/a", "unit_raw": "MWh p.a.", "value_quote": "| Erdgas | 241 | MWh p.a. |", "carrier": "Erdgas", "carrier_raw": "Gas H", "carrier_quote": "| Gas H | 241 |"}
```

`template` names the template and `without` lists the blocks of it that this
profile leaves out. The loader keeps both out of the prompt's settings, so
`temperature` and `max_tokens` are what a stage reads from the prompt. What a
template asks of a profile it says in its own front matter: its `required` and
`optional` parts, its `blocks` (a stretch of contract text, between
`<!-- block: name -->` and `<!-- /block -->`) and which of the blocks are
`omittable`. A profile does three things with that:

- It gives every required part, here the `role` of the model for this corpus
  and the `example_reply` the prompt ends on, and each optional part it has a
  sentence for.
- It leaves out a block it never had, with `without: [name]`, and only a block
  the template lists as omittable. The review template has a block
  `corpus_language`, a sentence about the language of the corpus' texts, which
  kwp has none of. A rule that is left out takes its number with it: the rules
  of a template (`<!-- rule: name -->`) are numbered when the prompt is loaded,
  without a gap, and a reference to a rule (`{{rule:name}}`) follows the
  numbers.
- It words a block itself, where the template's sentence fits it less well, by
  giving a part with the name of the block. Scenarios does it for
  `row_note` and `field_unit` of the review prompt. A block with no part of its name says what the template
  says.

A part is put in as it is written, apart from the blank lines around it, so a
part that continues a sentence starts with a space. A part may name a fact and a rule, and no other double brace or
comment mark. A fact is a value the code decides and a prompt only repeats: the
least length of a quote (the rule `quote_min_chars`, `verify.min_quote_chars()`), the word for "not stated"
(`fields.UNSTATED`), and the keys and words the closed list is shown in and the
key a closed coordinate's list goes under, which are sentences of the profile's
`prompts/extraction/phrases.json`. No template types one of them, so the prompt and the
request cannot disagree on it.

The language is a declaration of the profile that holds the parts file,
`extraction.CONTRACT_LANGUAGE` in its `extraction.py`: `"de"` in kwp,
`"en"` in scenarios and the built-in profile. It is read with `Profile.own`, so it
is not inherited. A profile that extends another and keeps its parts files gets
the language they are in, and one that writes parts files of its own declares
the language of those. A profile with no declaration, or one the core has no
templates for, does not load its prompt, and the error names the languages the
core has.

A parts file that does not fit its template is refused when the prompt is
loaded, with `PromptPartsError` (`docpipe/prompts.py:103-123`). It names the
prompt, the part or the block, the profile and the two files. Refused are a
required part that is missing, a part the template does not know (the nearest
name is offered), a part whose place is gone because `without` removed its
block, a `without` entry that is no block or not an omittable one, a reference
to a rule that is not in the prompt, and a double brace or comment mark left in
a part or in the text. Nothing is filled in for what is missing. `docpipe
doctor` shows the error as a failed `prompts` line with a hint on what a parts
file holds, and `docpipe preflight` as a failed prompt line (see [the command and its
settings](stages/command.md) and [the extraction stage](stages/extraction.md)).

A composed prompt has the sha256 of the file a person would have written by
hand: its front matter without `template` and `without`, then the text a request
sends. The stamp records it under `extraction/<name>` as it records a plain
file's, and compares none, so no stored document turns stale because a prompt
was put together from parts. `scripts/render_prompts.py` lists, for each composed
prompt, its template, the blocks the profile words itself and the blocks it
leaves out; `--what-if` renders each left out block back in, and
`--check-domain` holds a rewrite to "the profile's own sentences stand word for
word" (see [Running the pipeline](running.md)).

## The two profiles in comparison

| | `kwp` | `scenarios` |
|---|---|---|
| Corpus | German municipal heat plans, 801 documents (`profiles/kwp/profile.py:15`) | publications on climate and energy scenarios, a 164-document harvest |
| Target graph | MHPKG, Open Energy Platform | OEKG, Open Energy Platform |
| `document_noun` | "Wärmeplan" | "Publikation" |
| `column_layout` | `"auto"`; 184 of 801 documents carry multi-column pages, 44 throughout (`profiles/kwp/profile.py:15-17`) | `"auto"`; journal and agency layouts run two columns more often still |
| Facets in the answer app | `gemeinde`, `bundesland_lang`, `jahr` | `year`, `venue` |
| `catalog.CATALOG` | `KwpCatalog` | `ScenarioCatalog` |
| `--backfill-meta` | provided, refreshes `MunicipalityMeta` from a re-read KWW sheet | not provided |
| `FRAME` | the frame coordinates scenario and year | not set |
| `of` at the plan fields `base_year` and `target_year` (spec) | the pairs `{"scenario": "status_quo"}` and `{"scenario": "target"}` | none |
| `flow.json` of the profile's folder | none; the default's numbers are read | none; the default's numbers are read |
| Per-document choice lists (`document_axes`) | not used | the study regions a publication names, out of 249 in `regions.json` (`profiles/scenarios/extraction.py`) |
| Answer app's graph route (`kg_route`) | wired; a coordinate question can be answered straight from MHPKG | not wired; every answer comes from retrieval |

## Adding a profile

0. **Start from the default profile.** `docpipe init` writes `docpipe.toml`
   and a profile under `profiles/<name>/` that extends `default`, which
   already has a folder source, English prompts, wording and a
   catalog. Write only what the project knows better: its title, its filters,
   a prompt, its fields. The steps below are what a profile that stands alone
   has to supply, and what an extending one replaces.

1. **The smallest profile that loads.** `profiles/<name>/__init__.py`
   (empty) and `profiles/<name>/profile.py` exporting
   `PROFILE = Profile(name="<name>")`. Verify with
   `python -c "from docpipe.profile import load_profile;
   print(load_profile('<name>').display_title)"`.

2. **Register documents.** Add `source.py` with a `SOURCE` class
   implementing `docpipe.ingest.models.Source`
   (`documents(connection)`, `after_document(connection, doc)`), and, if
   `SourceDoc.meta` carries fields, a `schema.sql` with a `DocumentMeta`
   table plus a `store.py` for the SQL that fills it.

3. **Teach text extraction the corpus's language, together with the first
   prompt file.** Add `preprocessing.py`'s constants (the table
   above), and one file under `prompts/`.

4. **Add the prompts each stage asks for.** The id set is fixed by the
   core's own code, not invented per profile; copying an existing
   profile's `prompts/` tree gives the identical set, since both shipped
   profiles are asked for the same one (confirmed above,
   `_requested_prompt_ids`). `refinement/` and `visuals/` need no Python
   module beyond their prompts and `prompts/reading/phrases.json`, which holds the ten
   sentences that refinement, the visuals stage, page transcription and the chat
   say to a model whose reply was not the one JSON object, in the language of the
   profile's prompts for these stages (`reading.REQUIRED` names them; a profile
   that extends `default` has the built-in ones and writes only the ones it
   words differently). `preprocessing/page_transcribe.md` is
   exercised only when a PDF carries no text layer, but `preprocessing`
   is not one of `OPTIONAL_STAGES`' two keys, `extraction` and `kg`, so the stage needs it on
   disk for every profile once its `prompts/` directory holds any `.md`
   file, regardless of whether its corpus has a textless PDF.

5. **Wire up the answer app.** Add `inference.py`
   (`READOFF_MARKER`, `READOFF_NOTE`), the sentences in
   `prompts/inference/phrases.json`, and the twelve
   `prompts/inference/*.md` the answer loop loads (`llm_client.PROMPT_IDS`), then
   `catalog.py` if the generic picker (filename, published date, current or superseded) is not enough. A
   missing one of these two `inference.py` attributes, or a missing sentence,
   fails only at the answer app's first real question.

6. **Add extraction, if this corpus should feed a knowledge graph.** Write
   `extraction_spec.json` by hand, add `extraction.py` with `SPEC_PATH` at
   least, a `graph.json` whose `map` draws what the fields become in the graph
   (`docpipe compile apply --out` writes a first one beside a drafted spec; the
   Graph tab of `docpipe edit` draws it), a `kg.py` with `BRICKS` where the core's bricks do
   not suffice, and `prompts/extraction/*.md`. Two
   of those prompts, `review` and `example`, are parts files that name a template
   of the core, and `extraction.py` then declares
   `CONTRACT_LANGUAGE` for the language they are in (see The extraction
   prompts).
   Name the passages the prompts have to hold in `extraction.PROMPT_CHECKS`.
   `docpipe preflight <name>` then exercises, without a GPU, a model, or a
   database, what a run rests on: the spec the profile names
   (`extraction.SPEC_PATH`, and no other: a profile that names none fails on
   `spec present`, also when an `extraction_spec.json` lies beside it), one
   anchor per axis question and none for the
   value, the anchors prompt's presence and non-empty text, the passages of
   `PROMPT_CHECKS`, the drawing of the graph
   (held to the spec, the shapes and the bricks as the run holds it,
   `graph.check`, so a field the spec does not ask or a brick no code has
   fails `graph drawing`), the checked-in schema, and the ontology pin of a profile that
   has a `vocabulary` module. It prints one line per check and exits 1 when
   one fails, so it stands before a corpus run; with no name it checks the
   profile in effect, and a profile may be named by its directory, as for
   `--profile`. See [the extraction stage](stages/extraction.md).

Throughout, `docpipe preflight <name>` reports what is missing by name
rather than by where it crashes later; `docpipe.extraction.schema`'s
generator and `docpipe.extraction`'s `--serialize` path each read a
profile's checked-in files directly.
