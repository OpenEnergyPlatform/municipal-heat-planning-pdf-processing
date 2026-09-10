# How the parts fit together

Every stage has its own chapter, built from its own module docstrings, and
each carries the depth this page does not: failure modes, configuration
tables, measured numbers, the tests that pin them. This page is the one
`docs/` page nobody generates (`build_docs.HANDWRITTEN`, checked by
`tests/test_docs_build.py::test_the_hand_written_page_is_never_overwritten`).
Its job is the view no stage chapter has on its own: the shape of the whole
run, what one stage leaves for the next, and the resume logic that only
makes sense once several stages are read together.

## The stage sequence

The pipeline has ten stages, each a package or an app, connected only by
the files and the database rows one leaves for the next.

| Stage | Consumes | Produces |
|---|---|---|
| [1. File processing](stages/fileprocessing.md) | the profile's document list (an Excel register for `kwp`, a publication crawl index for `scenarios`) | a `Documents` and `DocumentMeta` row per accepted PDF, plus the profile's own tables |
| [2. Layout detection](stages/preprocessing.md) | the PDF file | `pages.json`, one entry per page with every detected table, figure, title and caption |
| [3. Structure assembly](stages/preprocessing.md) | `pages.json` | `sections.json`, an ordered section list with table and figure placeholders |
| [4. Refinement](stages/refinement.md) | `sections.json` | `sections_refined.json` |
| [5. Visuals](stages/visuals.md) | `sections_refined.json`, or `sections.json` where refinement has not run | `visuals.json`: a Markdown transcription per table, a description per figure |
| [6. Chunking, embedding, database](stages/chunking.md) | `sections_refined.json` and `visuals.json`, then `document.json` | `document.json`, then rows in SQLite and vectors in the FAISS index |
| [7. Extraction](stages/extraction.md) | the corpus itself: SQLite and the FAISS index, plus, by default, the table and figure crops under each document's `images/` directory | one `<doc>.jsonl` harvest and one `<doc>.stamp.json` per document |
| [8. The graph](stages/graph.md) | the accepted tuple lines of a harvest | one Turtle file, written by the profile's own `kg.make_serializer` |
| [Inference](stages/inference.md) | one question, SQLite and the FAISS index, read live | a grounded answer with a citation; nothing written to the corpus |
| [The app](stages/app.md) | the same corpus, one chat turn at a time | a rendered answer, plus its own query cache and request log |

## The stages

Each subsection gives only a summary; the linked chapter carries the
failure modes, the configuration table and the module-by-module read.

### 1. File processing

Full account: [stages/fileprocessing.md](stages/fileprocessing.md).

The stage decides which documents exist in the corpus at all. It reads a
profile's own document list: an Excel register filtered to complete plans
with a usable PDF link for `kwp` (`profiles/kwp/source.py`), a publication
crawl index plus two optional sibling files for `scenarios`
(`profiles/scenarios/source.py`). For every entry it fetches or locates the
PDF and grades whether its text layer is usable. A garbled or unreadable
document is refused and left out of the corpus, but a scan, a PDF with no
text layer at all, is registered anyway and listed for stage 2's optional
`--transcribe-missing-text` pass rather than refused
(`docpipe/ingest/pipeline.py:52` to `61`). A `kwp` PDF missing from the data
directory is downloaded; a `scenarios` PDF is expected already staged and
never fetched over the network. This is the only stage with no model and no
GPU. Resume is keyed on the filename already present in `Documents`
(`docpipe/store/documents.py:29` to `32`); the profile's own metadata write
still runs on an already-registered document, which is how a profile
refreshes metadata without re-registering the file.

### 2. Layout detection

Full account: [stages/preprocessing.md](stages/preprocessing.md).

Each page is rendered and passed through PP-DocLayoutV3, an object
detector that classifies tables, figures, titles, captions, headers and
footers, each with a bounding box and a confidence score
(`docpipe/preprocessing/stage2_layout.py`). Detected tables and figures are
cropped from the rendered page and saved as PNGs under the document's
`images/` directory. A page with no PDF text layer can optionally be
transcribed by a vision model instead, off unless the flag
`--transcribe-missing-text` is set, since nothing else in preprocessing
calls a model. The result, one entry per page, is written to `pages.json`. Resume
works at the level of the whole document: the cache is invalidated by
`--force-reextract`, by a `pages.json` that will not parse, or by a prior
run that recorded a failed page.

### 3. Structure assembly

Full account: [stages/preprocessing.md](stages/preprocessing.md).

No model runs here. PyMuPDF's extracted text is combined with the stage 2
layout into an ordered list of sections, each with a title, a page number
and placeholder tokens such as `[p13_tbl0]` marking where a table or figure
sits in the reading order (`docpipe/preprocessing/stage3_structure.py`). A
page with more than one text column has its blocks reordered column by
column instead of by raw position (`docpipe/preprocessing/columns.py`),
governed by the profile's `column_layout` setting. Repeated running headers
and footers are stripped, directory and index-listing sections are
dropped, and a caption is resolved by the same rule the read side uses
later (`docpipe/captions.py`). The output is `sections.json`. A narrower
`--rebuild-stage3` reruns only this step from an existing `pages.json`,
touching neither the PDF nor the layout model.

### 4. Refinement

Full account: [stages/refinement.md](stages/refinement.md).

An LLM repairs what a fixed rule cannot: hyphen breaks across a line,
leaked headers or footers, garbled ligatures, and numbering or label
prefixes left on a caption; it also converts bibliography sections to
BibTeX. It reads a sliding window of a document's sections at a time,
`WINDOW_SIZE` sections per call, 3 by default
(`docpipe/refinement/config.py:38` to `40`), keeping
context from the previous window so a merge can cross a boundary. A second,
mechanical pass then holds every section to a fixed word ceiling for the
embedding stage that follows; the model only proposes where to cut, the cut
itself always happens at a segment boundary (`docpipe/refinement/
split.py:11` to `12`). The output, `sections_refined.json`, is written
atomically, so a run killed mid-document leaves the previous refinement
rather than nothing (`docpipe/refinement/refine.py:1036` to `1040`). Resume
skips a document once
that file exists; `--force-stale` redoes only documents whose recorded
prompt hash no longer matches the profile's current prompts.

### 5. Visuals

Full account: [stages/visuals.md](stages/visuals.md).

Every cropped table and figure PNG is sent to a vision-capable model behind
its own OpenAI-compatible endpoint: a table gets a Markdown transcription,
a figure gets a prose description, both with a caption
(`docpipe/visuals/process.py`). The model is the same one refinement uses,
served by a second vLLM instance, which is what lets stage 5 run beside
stage 4 rather than after it. A QA gate checks a table's transcription for
coverage against the page's native PDF text and for repeated-row
duplication, and retries a transcription that fails the gate, with
feedback (`docpipe/visuals/qa.py`). The stage prefers `sections_refined.json` over
`sections.json`, and separately rereads `sections.json` for the native
table text the QA gate needs, since refinement drops that field. The
output is `visuals.json`. Resume is per item, not per document: an item
already carrying a `markdown` or `description` key is not sent again, so a
run interrupted partway through a large plan continues from exactly what
is still missing.

### 6. Chunking, embedding, database

Full account: [stages/chunking.md](stages/chunking.md).

Three steps run in sequence, each independently resumable and each callable
alone with `--step`. Merge combines `sections_refined.json` and
`visuals.json` into one `document.json` per PDF, cached against the mtimes
of both inputs. The db step loads `document.json` into the shared SQLite
corpus as `Sections`, `Pages`, `SectionPages`, `Segments`, `Tables` and
`Images` rows, carrying page-level provenance down to a bounding box for
some segments. The embed step produces up to six typed vectors per
document (section text, section title, table text, figure text, plus a
table or figure with its image) with the Qwen3-VL-Embedding-8B model, adds
them to one shared FAISS index, and writes matching `Embeddings` rows
recording the vector's
`faiss_id`, type and owner. Three further, additive steps (`enrich-bbox`,
`enrich-page-source`, `enrich-caption`) backfill one column family on an
already-built corpus without touching a section, an embedding or the FAISS
index. Resume differs by step: merge on the mtime cache, db on whether a
document already has `Sections` rows, embed on whether the database
already has a matching embedding, reconciled against what the FAISS index
file actually holds so a crash between a database write and an index save
is never read as done (`docpipe/chunking/database.py:724` to `755`).

### 7. Extraction

Full account: [stages/extraction.md](stages/extraction.md).

Extraction reads the already-built corpus, SQLite and the FAISS index,
plus, by default, the table and figure crops under each document's own
`images/` directory (`EXTRACT_ATTACH_IMAGES=0` turns that off); no PDF and
no `results/` file. For each document it plans which passages
answer which of the active profile's spec questions, groups them into
model requests, and checks every claim's quote against its source before
a claim becomes an accepted tuple; a claim that fails is a refusal, not a
row (`docpipe/extraction/verify.py`). The output is one JSONL harvest file
per document (tuples, refusals, one summary line) and one stamp file
recording what produced it. Five further passes act on an already-written
harvest without repeating the whole document: `--recheck` reapplies the
answer-in-quote rule with no model, `--remap` re-resolves a coordinate's wording
against a changed vocabulary with no model, `--top-up` resweeps only the
coordinates a stamp says moved, `--review` reads the lowest trust level
values a second time, and `--serialize` hands accepted tuples to stage 8.
Resume answers per question rather than per document; see
[The extraction stamp](#the-extraction-stamp) below.

### 8. The graph

Full account: [stages/graph.md](stages/graph.md).

A profile-agnostic core walks a harvest directory and groups tuple lines
per document (`docpipe/extraction/serialize.py`); a profile-owned
serializer, `profiles/<name>/kg.py`, alone decides IRI minting, node shape
and predicate choice, turning tuples into the profile's target graph:
MHPKG Turtle for `kwp`, OEKG Turtle for `scenarios`. A refusal never
reaches the serializer. Every IRI a serializer mints is a pure function of
a normalized name, so two runs over one document produce identical Turtle
(pinned by `tests/test_scenarios_extraction.py::
test_the_iri_is_a_pure_function_of_the_name`). Nothing here is a model call
or a GPU step, only a read-only pass over SQLite for a document's identity
and over the harvest files themselves. There is no resume: a `--serialize`
call always walks the whole harvest directory again.

### Inference

Full account: [stages/inference.md](stages/inference.md).

`docpipe.inference`, paired with `docpipe.embedding`, is the
retrieval-and-answer core the app is built on. It opens the corpus's SQLite
database read-only (`docpipe/inference/db.py:21` to `33`) and its FAISS
index once, then answers one question at a time: a search phrase, an
embedded query, a search over the selected documents, and an answer with a
citation resolved down to the page, and where a bounding box was stored,
to the passage highlighted in the source PDF. The query is embedded with
its own embedder, kept separate from the one that built the corpus, so one
question does not need a whole GPU. Where a profile's Turtle graph exists,
a closed question can be answered from it directly before falling back to
document retrieval, a different guarantee from extraction's verified
tuples: a claim extraction would refuse can still surface, unchecked, in a
grounded answer. It writes nothing to the corpus; its own durable side
effects are two SQLite files, a query-embedding cache, read on every
question to skip re-embedding a repeated query (`scripts/inference_app/
app.py:112` to `122`), and a request log that is write-only.

### The app

Full account: [stages/app.md](stages/app.md).

`scripts/inference_app/app.py` is the Streamlit front end over
`docpipe.inference`, and the only module in the whole pipeline that
imports Streamlit (`scripts/inference_app/app.py:1` to `16`). It opens one
profile's SQLite database, FAISS index, and, once a `--serialize` run has
produced one, a Turtle graph; every retrieval and answering decision is
made by `docpipe.inference` and `docpipe.embedding`, never reimplemented
in the app. A conversation's state, which documents are open and its turns
so far, lives only in the running process and is discarded when the
selection changes or the process restarts. An optional code-exec sandbox
lets an answer run a short calculation (sums, shares, unit conversions) in
an isolated container reached over a localhost HTTP service rather than in
the app's own process. Nothing here is a resumable batch job; one question
is one turn.

## The hand-off between stages

**Artifacts.** Every per-document file the pipeline writes is named once,
in `docpipe/artifacts.py`, so no stage hard-codes a filename of its own. A
document's own output directory holds a `results/` folder (`pages.json`,
`sections.json`, `sections_refined.json`, `visuals.json`, `document.json`,
each written by the stage that owns it) and an `images/` folder holding the
cropped table and figure PNGs stage 2 produces. Stage 1 writes three
further worklists at the top of the data directory, each removed before a
clean run leaves nothing stale on it: `rejected_pdfs.txt` names a garbled
document refused from the corpus, `unreachable_pdfs.txt` names a link that
could not be fetched, and `scanned_pdfs.txt` names a document registered
with no text layer (`docpipe/ingest/pipeline.py:105` to `116`). All three
are written for an operator to read, in the log and on disk; none is read
back by any stage. Stage 2's `--transcribe-missing-text` pass instead
decides, per page and per document, at run time, which pages carry no
usable text, through `needs_transcription`
(`docpipe/preprocessing/page_text_fallback.py:76`), called from
`fill_missing_page_text`
(`docpipe/preprocessing/page_text_fallback.py:161` to `189`), itself
called from `docpipe/preprocessing/pipeline.py:353` to `387`.

**The per-document results directory.** Chunking's db step is the last
one to open anything under `results/`. Extraction, the graph and the app
read only SQLite and the FAISS index; none of them opens `sections.json`
or `document.json` again. Refinement (stage 4) reads `sections.json`
alone. Visuals (stage 5) reads whichever of `sections_refined.json` and
`sections.json` is already on disk, preferring the refined file, and
separately rereads `sections.json` on its own for the native table text
its QA gate needs (`docpipe/visuals/pipeline.py:54` to `63`). This is what
lets the two stages run against two separate model servers at the same
time in the common case, visuals starting on a document before refinement
has finished it; visuals does read refinement's file once it exists, so
the two stages are not fully independent, only not blocking on each
other.

**The database.** From stage 6 on, "already done" is answered by a
database row or a FAISS id, never by a file's presence: extraction checks
a document's stamp, the embed step checks a `(embedding_type,
section_index, item_id)` triple, and the app has no notion of a results
directory at all. Once `document.json` has been folded in, the database is
what current means. A document repaired on disk after that point, a
hand-edited `sections.json`, a swapped-in PDF, stays invisible downstream
until it is pushed back through chunking's db step; no later stage rereads
`results/` on its own.

## Resuming

| Stage | Skips work when | Force it with |
|---|---|---|
| 1 file processing | the filename is already a row in `Documents` | delete the row |
| 2 layout detection | `pages.json` exists and loads cleanly | `--force-reextract` |
| 3 structure assembly | `sections.json` exists and loads cleanly | `--force-reextract`, or `--rebuild-stage3` for stage 3 alone |
| 4 refinement | `sections_refined.json` exists | `--force` for every document, `--force-stale` only where the recorded prompt moved |
| 5 visuals | an item already carries `markdown` or `description` | `--force` for every item, `--force-stale` only for stale items |
| 6, merge | `document.json` is newer than both its inputs | `--force` |
| 6, db | the document's rows are already in `Sections` | `--force` |
| 6, embed | the database already has a matching `Embeddings` row | `--force`, which also evicts the item's old FAISS ids first |
| 7 extraction | the document's stamp matches what today's run would produce | `--force`, `--force-stale`, or repair one key with `--top-up` |
| 8 the graph | never; a `--serialize` call always rewalks the harvest | nothing to force |
| inference and the app | nothing to resume; one question is one turn | nothing to force |

Running `--force` across the db and embed steps together needs one detail
the two steps cannot each see on their own: a document's old FAISS ids
have to be read off before the db step's forced delete removes its
`Embeddings` rows, or the embed step has nothing left naming which vectors
to evict from the index (`docpipe/chunking/pipeline.py:146` to `147`).

## The extraction stamp

Extraction is the one stage whose resume answers per question rather than
per document, so this section documents its stamp on its own.
`<doc>.stamp.json` is
written only once `finish_document` decides a harvest actually happened;
a document is left unstamped, so the next run redoes it, when more than
half its planned sources came back unreachable or nothing answered at all
(`UNREACHABLE_LIMIT = 0.5`, `docpipe/extraction/runner.py:3584`). Inside
it:

| Key | What it records | Compared on a redo |
|---|---|---|
| `spec` | sha256 of the whole `extraction_spec.json` file | only while no finer key is present |
| `model` | the model served at harvest time (`LLM_MODEL`) | yes |
| `anchors` | sha of the retrieval anchors the plan searched with | yes |
| one entry per `PROMPT_IDS` id | sha256 of that prompt file | yes |
| `parameter/<uri>` | fingerprint of one parameter's own question | yes |
| `value/<uri>` | fingerprint of a value's own closed list | yes |
| `axis/<uri>/<name>` | fingerprint of one axis's question and vocabulary | yes |
| `slot/parameter` | fingerprint of the value question itself | yes |
| `question_text/<key>` | the sentence this document was actually searched with | never |
| `review/*` | what a second reading of a value came to | never |

The fine keys (`parameter/`, `value/`, `axis/`, `slot/`) come from
`spec.fingerprints()` (`docpipe/extraction/spec.py:618` to `640`), and
their presence is what licenses ignoring the coarse `spec` key. An earlier
design hashed the whole spec file as one number, so one new label anywhere
in it made a whole corpus stale together, about 93 GPU hours to reread
1,082 documents over one added word (`docpipe/extraction/runner.py:3377`
to `3380`); the ontology behind the spec is revised repeatedly, so the
same cost would recur each time it is. With one key per parameter, per value list
and per axis, `stale()` names exactly which question changed and leaves
the rest of the corpus alone; it checks both directions, so a question
dropped from the spec counts as changed too, the one case the old
whole-file hash used to catch that a purely additive scheme would
otherwise miss (`docpipe/extraction/runner.py:3483` to `3487`). A file
with no stamp at all is read as fully stale, on principle: the opposite
reading, a missing stamp taken as nothing left to do, had already let a
run silently skip 165 documents with exit code 0
(`scripts/change_audit.py:10`).

The review prompt (`extraction/review`) is deliberately left out of
`PROMPT_IDS` itself, not merely out of the comparison: a review leaves a
value unchanged, only its `flags` grow, so folding the review prompt's sha
into every stamp would report the whole corpus stale the day that one
prompt is edited (`docpipe/extraction/runner.py:146` to `152`).

Three passes act on a moved key without opening the document again.

- `--remap`, no model, no index: maps a coordinate's recorded wording onto
  the vocabulary as the spec reads today, a pure function of the harvest
  file and the spec file. It carries a document's stamp forward for
  exactly the answer spaces it could fully resolve; a wording that matches
  nothing in either list is left open for `--top-up` instead of guessed.
- `--recheck`, no model, no index: reapplies the answer-in-quote rule to
  what a harvest already wrote, drops a coordinate whose recorded
  quote does not actually carry the answer, and clears the stamp (unless
  `--keep-stamps`) so the next harvest redoes exactly those.
- `--top-up`, the only one of the three that needs the model and the
  index: rereads only the coordinates a document's stamp says moved, over
  the harvest's own sweep logic, instead of harvesting the document again
  from its first passage; `--top-up-key axis/<uri>/<name>` narrows it to
  one named key. It skips a document whole rather than half repairing it
  whenever the stamp names something other than a coordinate, since a
  changed frame axis, model or prompt decides which rows exist at all,
  and that is not something one coordinate's resweep can safely settle.

## Running it end to end

One profile, one run, in this order. Refinement needs the LLM already
served at `LLM_BASE_URL`; visuals needs its own instance of the same model
at `VLM_BASE_URL`, which is what lets it run beside refinement rather than
after it; the embed half of chunking needs a visible GPU. Each of
refinement, visuals and extraction checks the served model's context size
before its first document and refuses to start rather than fail midway
(`docpipe/llm_preflight.py`, called from `docpipe/refinement/
pipeline.py:165` and `247`, `docpipe/visuals/pipeline.py:501`, and
`docpipe/extraction/runner.py:4045` and `4113`).

Select the profile once, in the environment, before any stage that
overrides prompts is imported:

```bash
export DOCPIPE_PROFILE=kwp
```

File processing, reading the profile's own document list:

```bash
python -m scripts.fileprocessing --source kww.xlsx --db data/kwp/kwp.db \
    --data-dir data/kwp/pdf
```

Layout detection and structure assembly, stages 2 and 3, over the whole
data directory:

```bash
python -m docpipe.preprocessing data/kwp/pdf
```

Refinement over every document under the profile's processed directory:

```bash
python -m docpipe.refinement --batch
```

Visuals, over the same processed directory, against its own served model:

```bash
python -m docpipe.visuals --batch
```

Chunking, embedding and the database, merge, db and embed in one call:

```bash
python -m docpipe.chunking
```

Extraction, over the corpus the previous steps built:

```bash
python -m docpipe.extraction data/kwp/kwp.db data/kwp/faiss_index.bin \
    data/kwp/extraction
```

The graph, serializing the same harvest directory:

```bash
python -m docpipe.extraction data/kwp/kwp.db data/kwp/faiss_index.bin \
    data/kwp/extraction --serialize data/kwp/graph.ttl
```

The app, reading the corpus and, once it exists, the graph:

```bash
DOCPIPE_PROFILE=kwp streamlit run scripts/inference_app/app.py
```

With the Turtle file from the previous step in place at
`INFERENCE_KG_TTL_PATH` (by default the profile's own `graph.ttl`), the
app offers the graph as the first answer path for a closed question and
searches the documents only where the graph has nothing to say.

Every path after the first command comes from the profile on its own:
stage 3's output directory and all of stage 6 need nothing more than the
environment variable. Extraction's three positionals, `db`, `index` and
`out`, have no profile default and always have to be spelled out.

## Where the promises are written down

**The contracts.** [What a coordinate's state means](contract/states.md)
names the seven states a coordinate can carry, so `unstated` (the plan does
not say it) and `exhausted` (the run stopped looking) stay two different
findings rather than one. [How much of a value the run can stand
behind](contract/trust.md) names the three trust levels and the closed
list of reasons behind the lowest one. The harvest contract per profile,
[kwp](contract/kwp.md) and [scenarios](contract/scenarios.md), is
generated from `profiles/<name>/extraction_schema.json`, itself generated
from that profile's `extraction_spec.json` by `docpipe/extraction/
schema.py`, never hand-written.

**The tests.** `tests/test_docs_build.py::test_the_checked_in_docs_are_the_generated_ones`
requires every generated page under `docs/` to equal a fresh render; this
page, `running.md` and `glossary.md` are the three the build refuses to
overwrite and refuses to run without
(`build_docs.HANDWRITTEN`). The command list two sections above is itself
checked: `test_every_command_the_hand_written_pages_print_can_be_run`
confirms every `python -m` module this page names against the packages on
disk, and every flag named in backticks against every `add_argument`
call under `docpipe/` and `scripts/`. `tests/test_architecture.py` holds
the profile boundary from the other side: the core under `docpipe/` never
imports a profile module, and every prompt id or `profile.require()` call
the core code makes by name is something each profile actually supplies,
with no prompt file left over that the core never loads.

**The docs build.** `scripts/build_docs.py` renders every page but the
three hand-written ones from the docstrings, schemas and constants already
in the code, so a page can never say something the code no longer does.
`.github/workflows/docs.yml` runs `build_docs.py --check` on a pull
request and on a tag, before anything is rendered, and regenerates and
commits the pages on a push to `develop`; Read the Docs builds the same
Sphinx project from `.readthedocs.yaml`, with warnings treated as errors,
so a broken cross-reference fails the build rather than shipping quietly.
