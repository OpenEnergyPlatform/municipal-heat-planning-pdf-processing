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
prompts and phrase tables.

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
wording tables (the chat's in `inference.py`, the sentences a model hears when
its reply was not the one JSON object in `reading.py`) and a catalog that
filters by subfolder, and has no extraction spec. `kwp` and `scenarios` both
extend it, and a test holds that each writes every part itself, so no English
prompt ever stands in for a missing German one.

`kwp` covers German municipal heat plans, a corpus of
801 documents at the point its `column_layout` comment was written
(`profiles/kwp/profile.py:15`), and answers in German; its accepted
values go into MHPKG on the Open Energy Platform. `scenarios` covers the
literature the IIASA AR6 scenario database cites
(`profiles/scenarios/profile.py:1`), a 164-document harvest
(`profiles/scenarios/kg.py:815`), and answers in English; its values go
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
(`docpipe/profile.py:6`), and `tests/test_architecture.py` holds it
mechanically. `test_core_imports_neither_profiles_nor_streamlit` walks the
AST of every `.py` file under `docpipe/` (`ast.walk`, so a nested import
counts as well as a module-level one) and fails at the exact line of any
`import profiles...` or `import streamlit...`
(`tests/test_architecture.py:25-32,28-35`).

Five entry points, preprocessing, refinement, visuals, extraction, and
chunking, reach `load_profile` through `resolve_profile(args)` rather than
calling it directly (`docpipe/preprocessing/pipeline.py:599`,
`docpipe/chunking/pipeline.py:390`), except that refinement, visuals and
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
(`scenarios`) is not forced to provide one; its own comment names why: "a
require with two constant arguments is read by test_architecture as a
demand on EVERY profile" (`docpipe/inference/kg_route.py:98-99, 104`).
`preprocessing.py`'s constants, by contrast, are all read through
`require` or `profile_value`, so their absence is a hard failure for any
profile the pipeline runs text through.

That comment points at the fourth and last of `tests/test_architecture.py`'s
checks. The other two share the same gate: they run only for a profile
whose `prompts/` directory already holds one `.md` file (`_profile_homes()`,
`tests/test_architecture.py:98-101`). The first finds every prompt id the
core's own source asks for, by walking `docpipe/`'s AST for literal
arguments to `prompts.load()` / `.text()` or a module constant named
`..._PROMPT_ID`, and checks each exists on disk under that profile's
`prompts/`, excusing an id under `extraction/` when `extraction.SPEC_PATH`
is absent and one under `kg/` when `kg.VALUE_QUERY` is absent
(`OPTIONAL_STAGES`, `tests/test_architecture.py:84-95`). The second checks
the reverse: every `.md` file on disk names an id the core actually
requested. The fourth check is what `kg_route.py` is written around: every
`(module, attr)` pair reached through **two literal strings** passed to
`require()` or `profile_value()` anywhere under `docpipe/` must resolve to
something other than `None`, for every profile `_profile_homes()` finds
(`tests/test_architecture.py:133-171`). It is a syntactic scan, and that
literalness is its whole limit: `docpipe/inference/wording.py:120` calls
`profile.require("inference", attr)` with `attr` a variable, so a profile
missing `PHRASES` is invisible to it and surfaces only as a
`LookupError` the first time the answer app is asked a question. The reading
table is not invisible to it: `docpipe/reading.py` asks for
`("reading", "PHRASES")` with two literal strings, so the same check holds every
profile to it.

One consequence follows from all three checks sharing `_profile_homes()`: a
profile with only a `profile.py` and no `prompts/` directory is invisible
to all three, not because it passes but because none exercises it.

## Extending a profile

A profile that sets `extends="default"`, or the name of another profile, gets
what it does not provide from that profile. `Profile.component` walks the line
of profiles nearest first and returns the first attribute it finds;
`Profile.layers` returns the value of every profile along the line, for a
table a profile lays over the one it extends entry by entry. The wording
tables `extraction.PHRASES`, `inference.PHRASES`, `inference.UI` and
`reading.PHRASES` work that way: a profile writes only the phrases it words
differently. The words of the picker are in that table too (`version_current`, `version_old` and
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
file(s), 29 of its own` for scenarios. The list is held by
`tests/test_default_profile.py` (`INHERITED`): a built-in prompt that is neither
on it nor a file of the profile fails, and so does a listed one that returns as a
file of the profile. A later change to one of the two built-in prompts on the
list therefore reaches the profiles that inherit it, and its sha256 is entered
in `BEFORE` there; for `visuals/caption_keep` a changed hash also makes stage 3
say "described with older prompts" for stored documents. A prompt of the
extraction stage that is a parts file is inherited with its parts, and is read
in the language of the profile that holds the file (see The extraction prompts,
below).
`extraction.PROMPT_CHECKS` is not laid over entry by entry: a profile that declares it holds the whole
list, and one that declares none keeps the list of the profile it extends.
Nothing is taken from a
profile that was not named. A profile without `extends` stands alone, and a
part it lacks is an absence, as before. A line of profiles that leads back to
itself is refused.

## The profile interface, stage by stage

The table lists every `(module, attribute)` pair `docpipe/` or its
entry-point scripts asks a profile for, grouped by stage, with what each
shipped profile provides.

| Stage | Module.attribute | Required or optional | `kwp` provides | `scenarios` provides |
|---|---|---|---|---|
| Getting the documents in | `source.SOURCE` | required to run the stage (`component`, `docpipe/ingest/cli.py:76`) | a class over the KWW Excel sheet | a class over the crawl's `pdf_index.json` |
| Getting the documents in | `source.backfill_meta` | optional, for `--backfill-meta` (`component`, `docpipe/ingest/cli.py:67`) | provided (`profiles/kwp/source.py:199`) | not provided; the flag ends the run |
| Reading the page | `preprocessing.HYPHEN_EXCEPTIONS` | required (`profile.require`, `docpipe/preprocessing/stage1_extract.py:45`) | German continuation words ("und", "oder", ...) | English ones ("and", "or", ...) |
| Reading the page | `preprocessing.CAPTION_MAX_WORDS` | required (`profile_value`, `docpipe/preprocessing/config.py:182`) | 45 (median caption 8 words, 205 past 40, `profiles/kwp/preprocessing.py:35-39`) | 160 (journal/IPCC captions run 60 to 150 words, `profiles/scenarios/preprocessing.py:39-43`) |
| Reading the page | `preprocessing.CAPTION_START` | required, a non-empty list of regular expressions each carrying its own anchor (`profile.require`, `docpipe/captions.py:64-71`); an empty list, a bare string or a pattern that does not compile or matches the empty text is a `ValueError` naming the profile, a missing list a `LookupError` | one German-shaped pattern: a word, a number, a colon ("Tabelle 17:") | the same pattern; the built-in profile adds letter-numbered forms ("Table A.1:") and the colon-less forms ("Figure 3.", "Fig. 2", "Table 1 Annual totals") only where a text, a line or a sentence begins |
| Reading the page | `preprocessing.TITLE_EXCLUDE_PREFIXES` | required (`profile_value`, `docpipe/preprocessing/config.py:192`) | "abbildung", "tabelle", and their abbreviations | "figure", "table", "box", "plate", and their abbreviations |
| Reading the page | `preprocessing.DIRECTORY_FIGTAB_WORDS` | required (`profile_value`, `docpipe/preprocessing/stage3_structure.py:191`) | German figure/table list openers | English ones |
| Reading the page | `preprocessing.DIRECTORY_TITLE_WORDS` | required (`profile_value`, `docpipe/preprocessing/stage3_structure.py:230`); fragments of a pattern joined with `\|`, matched case-insensitively anywhere in a section title; an empty list never matches | "inhalt", "verzeichnis", "contents", "directory" | the same four, which keeps every verdict where they were |
| Reading the page | `preprocessing.BIBLIOGRAPHY_TITLE_WORDS` | required (`profile_value`, `docpipe/preprocessing/stage3_structure.py:214`) | "literatur", "quellen", ... | "references", "bibliography", ... |
| Repairing the text | `refinement.WINDOW_SIZE` | optional (`component`, `docpipe/refinement/config.py:41`) | not set, falls back to 3 | not set, falls back to 3 |
| Repairing the text, the visuals, page transcription, the answer app | `reading.PHRASES` | required, laid over the extended profile's entry by entry (`profile.require`, `profile.layers`, `docpipe/reading.py:87-105`); checked as a set against `reading.REQUIRED`, ten names, before the first request of refinement, of the visuals stage and of page transcription, and in the chat when a reply was not the one object asked for | the ten sentences said to a model whose reply was not the one JSON object, in English, the language of the profile's prompts for these stages | the same ten, in English; its extraction prompts are German and `extraction.PHRASES` is another table |
| The answer app | `catalog.CATALOG` | optional (`component`, `docpipe/inference/catalog.py:158`) | `KwpCatalog`: municipality, Land, year | `Ar6Catalog`: year, venue, AR6 scenario |
| The answer app | `inference.PHRASES`, `READOFF_MARKER`, `READOFF_NOTE` | required at first use (`profile.require`, variable `attr`, `docpipe/inference/wording.py:120`) | German phrasing, 30 keys checked against `wording.REQUIRED` | English phrasing, same 30 keys |
| Reading the values out | `extraction.PHRASES` | required, laid over the extended profile's (`profile.layers`, `docpipe/extraction/wording.py`) | German sentences the stage writes to the model | German sentences, the language of its extraction prompts |
| Reading the values out | `extraction.PROMPT_CHECKS` | optional, read by `docpipe preflight` (`component`); a profile that declares none has the extended profile's | two entries: the field prompt says `GENAU EIN Feld`, the rows prompt no longer fixes one parameter | the same two entries |
| Reading the values out | `extraction.CONTRACT_LANGUAGE` | required of a profile that holds a parts file: the language of the core's template the file is put together with, read from the profile that owns the file (`Profile.own`, `docpipe/extraction/contract.py:85-88`) and not inherited | `"de"` | `"de"` for scenarios, `"en"` for the built-in profile |
| Reading the values out | `extraction.ALT_LABEL_LANGUAGE` | required by the profile's own `vocabulary` module (`profile.require`), not by the core: the language tag of the alternative labels a vocabulary snapshot keeps (`ontology.index` and `ontology.build` take it as `language`, with no default) | `"de"` | `"de"` for scenarios, `"en"` for the built-in profile |
| Reading the values out | `extraction.NOT_EXTRACTED` | optional (`component`), read by `docpipe preflight`: a mapping `(shape, property)` to one sentence, the properties of the profile's shapes it leaves out on purpose | not provided | 21 entries, each with its reason |
| Reading the values out | `extraction.shapes_files` | optional (`component`), read by `docpipe preflight`: a callable returning the SHACL files the graph is held against | not provided; the shapes line says "skipped" | the shapes file of the last refresh of the OEKG sources |
| Reading the values out | `extraction.SPEC_PATH` | required in practice; refused with `SystemExit` otherwise (`component`, `docpipe/extraction/runner.py:5433-5436`) | `extraction_spec.json` | `extraction_spec.json` |
| Reading the values out | `extraction.SLICE` | optional (`component`, `docpipe/extraction/runner.py:5494`) | `{"quantity": None}`, gates a row on its quantity class alone | not provided; no gate |
| Reading the values out | `extraction.FRAME` | optional (`component`, `docpipe/extraction/runner.py:5517-5518`) | `("scenario", "year")`, found once per document | not provided; nothing repeats that way |
| Reading the values out | `extraction.BASE_YEAR`, `extraction.TARGET_YEAR` | optional (`component`, `docpipe/extraction/runner.py:5643-5649`): which frame pairs are the plan's own state and its target, so that a year answer naming only the plan's word for one of them ("Basisjahr", "Zieljahr") is read when its number is a year the frame found for those pairs | `{"scenario": "status_quo"}` and `{"scenario": "target"}` | not provided; no state has years |
| Reading the values out | `extraction.document_axes` | optional (`component`, `docpipe/extraction/runner.py:5505`) | not provided | this publication's AR6 scenarios and the study regions it names, out of 249 (`profiles/scenarios/regions.json`) |
| Reading the values out | `extraction.document_context` | optional (`component`, `docpipe/extraction/runner.py:5510`) | the plan's own municipality name | not provided |
| The knowledge graph | `kg.make_serializer` | optional for `--serialize` (`component`, `docpipe/extraction/runner.py:5371`); without one the generic writer built from the spec's `graph` block is used, and a profile with neither is refused with `SystemExit` (`docpipe/extraction/runner.py:5379-5383`) | tuples to MHPKG Turtle | tuples to OEKG Turtle |
| The answer app | `kg.VALUE_QUERY` plus six more attributes, and `inference.ROUTE_NOTES` | optional; absent returns `None` (`component`, `docpipe/inference/kg_route.py:104-106`), present but missing any of the other seven raises `LookupError` instead (`111-114`), all eight present builds the route | provided; the app can answer a coordinate question straight from the graph | not provided; the app never queries a graph |

Two entries of `extraction` say more than the table. `extraction.PHRASES` names
the key of a request as well as its sentences. The frame request lists the
entries of a closed frame coordinate under the key
`say("frame_options", slot=<coordinate name>)`, and `frame_options` is one of
the phrases a profile has to have. `kwp` and `scenarios` say `"scenarios"`, one
list for every closed frame coordinate, and the built-in profile says
`"{slot}_options"`, one list per coordinate. The German frame template names the
key through the fact `frame_options`, so the frame prompts of `kwp` and
`scenarios` say `"scenarios"` as the profile's phrase does, and their
`frame_not_an_option` phrase names `"scenarios"` in its own words; a test holds
the three together. The built-in frame prompt names
no key ("the list the request gives for `scenario`"), and its
`frame_not_an_option` phrase is handed the key that was sent, as `{options}`. A
profile that extends the built-in one and words only `frame_options`
differently has therefore moved the request, the correction and the prompt
together.

`extraction.PROMPT_CHECKS` is a tuple of entries `(what is checked, prompt id,
passage, has to be there)`: a passage the profile's prompts have to hold
(`True`) or must not hold (`False`), in the language of those prompts and in the
text a request sends, which for a parts file is the composed one. The
built-in profile declares one, that its field prompt says `EXACTLY ONE field`.
The shapes of a profile's graph are its own as well: `extraction.shapes_files`
says where they are and `extraction.NOT_EXTRACTED` which of their properties it
leaves out on purpose, and `docpipe preflight` warns about the rest (see [the
extraction stage](stages/extraction.md)).

Two more phrases of `extraction.PHRASES` are keys and not sentences:
`option_means` and `option_spellings`, the keys an entry of a closed list goes
to the model under. They are `means` and `spellings` in the built-in profile,
`kwp` and `scenarios` alike; kwp and scenarios said them in German before, and
a profile that extends one of them has no reason to word them differently.

## The extraction prompts: the core's template and a profile's parts

Five prompts of the extraction stage, `rows`, `field`, `frame`, `review` and
`example`, are written in two halves. The core holds the contract text of each,
in German and in English, as a template under
`docpipe/extraction/contract/<language>/<name>.md`: what the reply looks like,
that the quote stands in a shown passage, that the answer stands in the quote,
what "not stated" is, what to do with a closed list. A profile's own file holds
what is about its corpus: the role, the examples, the sentences about its own
tables. A file that names a template in its front matter, `template: rows`, is
a parts file, and `docpipe/prompts.py` puts it together with the template of
the profile's language when the prompt is loaded. A request, a stamp and
`scripts/render_prompts.py` see the composed prompt and never the two halves.
The other extraction prompts (`phrase`, `anchors`, `queries`) and every prompt
of the other stages are plain files, read as they are written.

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
  `invent_figures` and `source_kinds` of the rows prompt, `rows_carry` and
  `unstated_when` of the field prompt and `row_note` and `field_unit` of the
  review prompt; kwp for `value_text` of the rows prompt and `closed_out_text`
  of the field prompt. A block with no part of its name says what the template
  says.

A part is put in as it is written, apart from the blank lines around it, so a
part that continues a sentence starts with a space, as `quote_why` of the frame
template does. A part may name a fact and a rule, and no other double brace or
comment mark. A fact is a value the code decides and a prompt only repeats: the
least length of a quote (`verify.MIN_QUOTE_CHARS`), the word for "not stated"
(`fields.UNSTATED`), and the keys and words the closed list is shown in and the
key of the frame's list, which are sentences of the profile's
`extraction.PHRASES`. No template types one of them, so the prompt and the
request cannot disagree on it.

The language is a declaration of the profile that holds the parts file,
`extraction.CONTRACT_LANGUAGE` in its `extraction.py`: `"de"` in kwp and
scenarios, `"en"` in the built-in profile. It is read with `Profile.own`, so it
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
file holds, and `docpipe preflight` as a failed `prompt extraction/rows` or
`prompt extraction/field` line (see [the command and its
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
| Corpus | German municipal heat plans, 801 documents (`profiles/kwp/profile.py:15`) | the AR6 scenario literature, a 164-document harvest (`profiles/scenarios/kg.py:815`) |
| Target graph | MHPKG, Open Energy Platform | OEKG, Open Energy Platform |
| `document_noun` | "Wärmeplan" | "Publikation" |
| `column_layout` | `"auto"`; 184 of 801 documents carry multi-column pages, 44 throughout (`profiles/kwp/profile.py:15-17`) | `"auto"`; journal and agency layouts run two columns more often still |
| Facets in the answer app | `gemeinde`, `bundesland_lang`, `jahr` | `year`, `venue`, `scenario` |
| `catalog.CATALOG` | `KwpCatalog` | `Ar6Catalog` |
| `--backfill-meta` | provided, refreshes `MunicipalityMeta` from a re-read KWW sheet | not provided |
| `SLICE` / `FRAME` | gates on quantity; frames on scenario and year | neither set |
| `BASE_YEAR` / `TARGET_YEAR` | the frame pairs `{"scenario": "status_quo"}` and `{"scenario": "target"}` | neither set |
| Per-document choice lists (`document_axes`) | not used | the AR6 scenarios and study regions a publication names, out of 1389 scenarios and 249 regions in `regions.json` (`profiles/scenarios/extraction.py:7-12`) |
| Answer app's graph route (`kg_route`) | wired; a coordinate question can be answered straight from MHPKG | not wired; every answer comes from retrieval |

## Adding a profile

0. **Start from the default profile.** `docpipe init` writes `docpipe.toml`
   and a profile under `profiles/<name>/` that extends `default`, which
   already has a folder source, English prompts, wording tables and a
   catalog. Write only what the project knows better: its title, its filters,
   a prompt, its fields. The steps below are what a profile that stands alone
   has to supply, and what an extending one replaces.

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
   only when `docpipe ingest` runs (`docpipe/ingest/cli.py`; the older
   `scripts/fileprocessing/pipeline.py` re-exports it) and
   `profile.component("source", "SOURCE")` comes back `None`.

3. **Teach text extraction the corpus's language, together with the first
   prompt file.** Add `preprocessing.py`'s constants (the table
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
   module beyond their prompts and `reading.py`, whose `PHRASES` holds the ten
   sentences that refinement, the visuals stage, page transcription and the chat
   say to a model whose reply was not the one JSON object, in the language of the
   profile's prompts for these stages (`reading.REQUIRED` names them; a profile
   that extends `default` has the built-in ones and writes only the ones it
   words differently). `preprocessing/page_transcribe.md` is
   exercised only when a PDF carries no text layer, but `preprocessing`
   is not one of `OPTIONAL_STAGES`' two keys, `extraction` and `kg`
   (`tests/test_architecture.py:84-85`), so
   `test_a_profile_provides_every_prompt_the_core_loads` demands it on
   disk for every profile once its `prompts/` directory holds any `.md`
   file, regardless of whether its corpus has a textless PDF.

5. **Wire up the answer app.** Add `inference.py`
   (`PHRASES`, `READOFF_MARKER`, `READOFF_NOTE`) and the ten
   `prompts/inference/*.md` the answer loop loads (`llm_client.PROMPT_IDS`), then
   `catalog.py` if the generic picker (filename, published date, current or superseded) is not enough. A
   missing one of these three `inference.py` attributes is the case named
   above where `test_architecture.py` cannot catch it: it passes `pytest`
   and fails only at the answer app's first real question.

6. **Add extraction, if this corpus should feed a knowledge graph.** Write
   `extraction_spec.json` by hand, add `extraction.py` with `SPEC_PATH` at
   least, `kg.py` with `make_serializer` (or a `graph` block in the spec,
   which the generic writer reads instead), and `prompts/extraction/*.md`. Five
   of those prompts, `rows`, `field`, `frame`, `review` and `example`, are parts
   files that name a template of the core, and `extraction.py` then declares
   `CONTRACT_LANGUAGE` for the language they are in (see The extraction
   prompts).
   Name the passages the prompts have to hold in `extraction.PROMPT_CHECKS`.
   `docpipe preflight <name>` then exercises, without a GPU, a model, or a
   database, what a run rests on: the spec the profile names
   (`extraction.SPEC_PATH`, and no other: a profile that names none fails on
   `spec present`, also when an `extraction_spec.json` lies beside it), one
   anchor per axis question and none for the
   value, each extraction prompt's presence and non-empty text, `temperature`
   and `max_tokens` for `extraction/rows` and `extraction/field`
   specifically, the passages of `PROMPT_CHECKS`, the writer of the graph
   (built as the run builds it, so a `graph` block it refuses, such as the
   placeholder base `docpipe compile spec` drafts, fails `serializer
   present`), the checked-in schema, and the ontology pin of a profile that
   has a `vocabulary` module. It prints one line per check and exits 1 when
   one fails, so it stands before a corpus run; with no name it checks the
   profile in effect, and a profile may be named by its directory, as for
   `--profile`. See [the extraction stage](stages/extraction.md).

Throughout, `pytest tests/test_architecture.py -k <name>` is the one
command that reports what is missing by name rather than by where it
crashes later. Running the suite in full, at the end, is still necessary:
neither it nor `docpipe preflight` replaces the profile's own tests,
and `docpipe.extraction.schema`'s generator and `docpipe.extraction`'s
`--serialize` path each read a profile's checked-in files directly.

## Verification

A misconfigured profile fails more than one way. `Profile.__post_init__`
raises `ValueError` on an unusable `name` or unknown `column_layout`
(`docpipe/profile.py:188-192`), pinned by `tests/test_profile.py`'s
`test_rejects_unusable_names` and `test_rejects_unknown_column_layout`.
`load_profile` raises `LookupError` for a name given nowhere
(`docpipe/profile.py:359-361`) or unknown on disk
(`docpipe/profile.py:370-372`), pinned by
`test_no_profile_is_an_explicit_error` and
`test_unknown_profile_lists_the_available_ones`; it also raises
`ValueError`, unpinned by any test, when `PROFILE.name` does not match its
directory (`docpipe/profile.py:377-378`). `Profile.require` and
`profile_value` raise `LookupError` for a missing attribute or an unset
`$DOCPIPE_PROFILE` (`docpipe/profile.py:261-271,401-402`), the case
`kg_route.hooks()` turns into its own `LookupError` for a partial
`kg.VALUE_QUERY` route (above). `resolve_profile` raises `SystemExit` for a
profile named after a stage was imported under another one, when the named
profile ships prompts (`docpipe/profile.py:466-473`), pinned by
`test_late_profile_is_refused_when_it_overrides_prompts`; `require_profile`
raises it for no profile at all (`docpipe/profile.py:481-484`), pinned by
`test_a_stage_that_cannot_run_without_a_profile_says_which_there_are`
(`tests/test_entry_points.py`). Two entry points
add their own `SystemExit`, via `parser.error()` for extraction:
`docpipe/ingest/cli.py:69,78-79` for a missing `SOURCE` or
`backfill_meta`, and
`docpipe/extraction/runner.py:5379-5383,5433-5436` for a missing
`SPEC_PATH` (under `--serialize`, only when `make_serializer` is missing too).

A parts file that cannot be composed fails when its prompt is loaded and not
when a request is sent: `PromptPartsError`, pinned case by case in
`tests/test_prompt_parts.py`, among them
`test_a_missing_required_part_names_the_prompt_the_part_the_profile_and_both_files`
and `test_a_part_the_template_does_not_know_is_refused_and_the_near_one_named`.
That a profile declares its own language and inherits none is held by
`test_a_profile_declares_for_itself_and_inherits_nothing_of_it`.
