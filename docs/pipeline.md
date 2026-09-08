# How the parts fit together

This is the only page under `docs/` nobody generates. Every stage now has its
own deep-dive page, built from its own module docstrings plus an intro that
explains what a reader would get wrong -- so this page stays short on purpose
and links out rather than repeating that depth. Its job is the view none of
those pages can have: the shape of the whole run, what one stage owes the
next, and the handful of rules that only make sense across a boundary.

## The whole chain

```
PDF
 |  1 file processing   docpipe.ingest + profile        network only
 v
Documents row (SQLite)
 |  2 preprocessing      docpipe.preprocessing            PP-DocLayoutV3, GPU
 v
pages.json
 |  3 preprocessing      docpipe.preprocessing            deterministic
 v
sections.json
 |-----------------------------------------------+
 |  4 refinement          docpipe.refinement       |  5 visuals   docpipe.visuals
 |  vLLM, sliding window over sections            |  vLLM, per table/figure
 v                                                 v
sections_refined.json                        visuals.json
 |-----------------------------------------------+
                        |  6a merge   docpipe.chunking
                        v
                  document.json
                        |  6b db, 6c embed   docpipe.chunking
                        v
        +---------------+----------------+
        v                                v
  SQLite (<profile>.db)          FAISS index (faiss_index.bin)
        +---------------+----------------+
                        |
        +---------------+----------------------------+
        v                                             v
  the app                                     7 extraction   docpipe.extraction
  docpipe.inference                           retrieval + vLLM harvest
  reads the DB + index live, per question              |
                                                         v
                                          <doc>.jsonl + <doc>.stamp.json
                                                         |  8 graph  --serialize
                                                         v
                                                    Turtle graph
```

Names checked against `docpipe/artifacts.py`: `pages.json`, `sections.json`,
`sections_refined.json`, `visuals.json` and `document.json` are exactly the
constants defined there (`PAGES_JSON`, `SECTIONS_JSON`,
`SECTIONS_REFINED_JSON`, `VISUALS_JSON`, `DOCUMENT_JSON`), each one sitting
under `results/` in a document's own output directory.

## The stages

Each entry is deliberately thin. Follow the link for the failure modes,
the measured numbers and the module-by-module read.

### 1. File processing -- [docs](stages/fileprocessing.md)

| | |
|---|---|
| in | the profile's document list, via `profiles/<name>/source.py` |
| out | rows in `Documents` -- there is no `results/` file yet |
| costs | a plain HTTP download per document; no model, no GPU |
| watch for | resume is keyed on the **filename** already sitting in `Documents`. Deleting the PDF from the data directory does nothing on its own; deleting the row is what earns a re-fetch |

### 2-3. Layout and structure -- [docs](stages/preprocessing.md)

| | |
|---|---|
| in | the PDF file, or a cached `pages.json` for stage 3 alone |
| out | `pages.json`, then `sections.json` |
| costs | GPU for PP-DocLayoutV3; PyMuPDF and section assembly are plain CPU; a model server only enters the picture with `--transcribe-missing-text` |
| watch for | `pages.json` is written only once every page came out clean -- a killed run leaves no cache at all and starts stage 1+2 over, it never resumes mid-document |

### 4. LLM refinement -- [docs](stages/refinement.md)

| | |
|---|---|
| in | `sections.json` |
| out | `sections_refined.json` |
| costs | one served instance of the shared LLM, reached over HTTP |
| watch for | "already done" means the output file is there, not that it still matches today's prompt -- a prompt edit changes nothing on disk unless the next run is told `--force-stale` |

### 5. Image processing -- [docs](stages/visuals.md)

| | |
|---|---|
| in | `sections_refined.json`, falling back to `sections.json` |
| out | `visuals.json` |
| costs | its own served instance of the same model -- the reason it can run beside stage 4 instead of waiting for it |
| watch for | caching is per table or figure, not per document -- a run interrupted partway through a large plan resumes on exactly the items still missing `markdown` or `description`, not on the whole document |

### 6. Chunking, embedding, database -- [docs](stages/chunking.md)

| | |
|---|---|
| in | `sections_refined.json` + `visuals.json` (merge); `document.json` (db, embed) |
| out | `document.json`, then rows in SQLite and vectors in the FAISS index |
| costs | merge and db cost only disk; embedding needs a GPU per replica of the embedding model |
| watch for | asking for `--force` across the db and embed steps together needs a document's old FAISS ids read off **before** the db step deletes its `Embeddings` rows -- once those rows are gone nothing names the vectors left to evict |

### 7. Extraction -- [docs](stages/extraction.md)

| | |
|---|---|
| in | SQLite and the FAISS index -- the corpus, not a `results/` file |
| out | one `<doc>.jsonl` harvest and one `<doc>.stamp.json` per document |
| costs | the harvesting model, the query embedder, and the source PDF for placing a quote |
| watch for | resume here is not "does the file exist" -- see the dedicated section below |

### 8. The knowledge graph -- [docs](stages/graph.md)

| | |
|---|---|
| in | the accepted-tuple lines of the JSONL harvest |
| out | one Turtle file, written by the profile's own `kg.make_serializer` |
| costs | nothing -- a read-only pass over SQLite and local files, no model, no GPU |
| watch for | a refused claim never reaches the serializer at all, and a profile with no `kg.py` cannot run this step -- exactly like extraction being optional for a profile with no spec |

### The app -- [asking](stages/inference.md) / [chat](stages/app.md)

| | |
|---|---|
| in | SQLite and the FAISS index, read live, one question at a time |
| out | nothing written to the corpus -- only its own query cache and request log |
| costs | the answering model, the query-side embedder (kept apart from the batch one so one question does not need a whole GPU), and optionally a code sandbox |
| watch for | it grounds an answer with a citation resolved at query time -- that is not the same thing as extraction's verified tuples, and a claim extraction would refuse can still surface, unchecked, in a chat answer |

## The hand-off

Chunking's db step is the last one to open anything under `results/`.
Extraction, the graph and the app all read SQLite and the FAISS index and
nothing else -- neither of them ever opens `sections.json` or
`document.json` again.

That follows from how each of them decides "already done": from stage 6 on,
the answer lives in a database row or a FAISS id, not in a file's presence.
Extraction checks a document's stamp; the embed step checks whether an
`(embedding_type, section_index, item_id)` triple is already in
`Embeddings`; the app has no notion of a results directory at all. Once
`document.json` has been folded in, the database is what "current" means.

The consequence: a document repaired on disk after that point -- a
hand-edited `sections.json`, a swapped-in PDF -- is invisible to everything
downstream until it is pushed back through chunking's db step. Nothing later
in the chain re-reads `results/` on its own, so the repair sits there,
correct and unread, until someone re-ingests it on purpose.

One more pairing worth naming: refinement (4) and visuals (5) both read
`sections.json`, and neither reads the other's output. They can run at the
same time on two separate model servers, and the only point where their two
files meet again is the merge half of stage 6.

## Resuming

| stage | skips work when | force it with |
|---|---|---|
| 1 file processing | the filename is already a row in `Documents` | delete the row |
| 2-3 preprocessing | `pages.json` / `sections.json` exist and load cleanly | `--force-reextract` for both; `--rebuild-stage3` for stage 3 alone (no PDF, no GPU) |
| 4 refinement | `sections_refined.json` exists | `--force` for every document; `--force-stale` only where the recorded prompt moved |
| 5 visuals | an item already carries `markdown` / `description` | `--force` for every item; `--force-stale` only for stale items |
| 6, merge | `document.json` is not older than either input | `--force` |
| 6, db | the document's rows are already in `Sections` | `--force` |
| 6, embed | the DB already has an `Embeddings` row for that item | `--force` (also evicts its old FAISS ids first) |
| 7 extraction | the document's stamp matches what today's run would produce | `--force`, `--force-stale`, or repair one key with `--top-up` |
| 8 graph | never -- a `--serialize` call always re-walks the harvest | (nothing to force) |
| the app | nothing to resume -- one question is one turn | (nothing to force) |

## The extraction stamp

Extraction is the one stage whose resume answers per **question**, not per
document, so it earns its own section.

**What it records.** `<doc>.stamp.json` is written only once
`finish_document` decides a harvest actually happened -- a server that
answers every request with the same sentinel does not get one, or a run
against a dead endpoint would write up to a thousand empty documents down as
finished. Inside it: a handful of coarse keys (`spec`, the sha256 of the
whole spec file; `model`; `anchors`; one entry per prompt id the stage
uses), and, from `spec.py`'s `fingerprints()`, one fine key per question the
model is actually asked -- `slot/parameter` for the value question itself,
`parameter/<uri>` per parameter, `value/<uri>` where the value is its own
closed list, `axis/<uri>/<name>` per axis. Two more prefixes ride along
without ever being compared: `question_text/<key>`, the sentence this
document was really searched with, and `review/*`, what a second reading
came to -- both there for a person to read, neither a reason to redo a
harvest.

**Why per question.** The earlier design hashed the whole spec file as a
single number, so one new label anywhere in it moved that number and made
every stamped document stale together -- about 93 GPU hours to re-read a
corpus over one added word, and the ontology behind the spec keeps moving,
so that bill would come due again and again. With one key per parameter,
per value list and per axis, `stale()` can name exactly which question
changed and leave the rest of a 1,082-document corpus untouched. It checks
both directions the moment any fine key is present, so a question dropped
from the spec counts as changed too, the one case the old whole-file hash
used to catch that a purely additive fine-key scheme would otherwise miss.
And a file with no stamp at all is read as fully stale, on principle: this
project has already paid once for the opposite reading, where a missing
stamp was taken as "nothing left to do" instead of "never ran," and a run
silently skipped 165 documents that way with exit code 0.

**The three passes.** Each acts on a moved key without opening the document
again.

- `--remap` -- no model, no index. Maps a coordinate's recorded wording
  onto the vocabulary as the spec reads today, a pure function of the
  harvest file and the spec file. It carries a document's stamp forward for
  exactly the answer spaces it could fully resolve; a wording that matches
  nothing in either list is left open for `--top-up` rather than guessed.
- `--recheck` -- no model, no index. Re-applies the evidence rule as it
  reads today to what a harvest already wrote, drops any coordinate whose
  recorded quote does not actually carry the answer, and clears the stamp
  (unless `--keep-stamps`) so the next harvest knows to redo exactly those.
- `--top-up` -- the only one of the three that needs the model and the
  index. It re-reads only the coordinates a document's stamp says moved,
  over the harvest's own sweep logic, instead of harvesting the document
  from its first passage again; `--top-up-key axis/<uri>/<name>` narrows it
  to one named key. It skips a document whole rather than half-repair it
  whenever the stamp names something other than a coordinate -- a changed
  frame axis, model or prompt decides which rows exist at all, and that is
  not something one coordinate's re-sweep can safely patch.

## Running it end to end

One profile, one run, in order. Step 4 needs the LLM already served at
`LLM_BASE_URL`; step 5 needs its own instance of the same model at
`VLM_BASE_URL`, which is what lets it run at the same time as step 4
rather than after it; step 6's embed half needs a visible GPU for the
embedding model. Every one of those checks the server's context size
before the first document and refuses to start rather than fail midway.

1. `export DOCPIPE_PROFILE=kwp`
2. `python -m scripts.fileprocessing --source kww.xlsx --db data/kwp/kwp.db --data-dir data/kwp/pdf`
3. `python -m docpipe.preprocessing data/kwp/pdf`
4. `python -m docpipe.refinement --batch`
5. `python -m docpipe.visuals --batch`
6. `python -m docpipe.chunking`
7. `python -m docpipe.extraction data/kwp/kwp.db data/kwp/faiss_index.bin data/kwp/extraction`
8. `python -m docpipe.extraction data/kwp/kwp.db data/kwp/faiss_index.bin data/kwp/extraction --serialize data/kwp/graph.ttl`
9. `DOCPIPE_PROFILE=kwp streamlit run scripts/inference_app/app.py`

With the file from step 8 in place (`INFERENCE_KG_TTL_PATH`, by default the
profile's `graph.ttl`), the app offers the graph as the first answer path and
searches the documents only where the graph says why it has none.

Paths after step 1 mostly come from the profile on their own: step 3's
output, and all of step 6, need nothing more than the env var. Extraction's
three positionals (`db`, `index`, `out`) have no profile default and always
need to be spelled out.

## Where the promises are written down

- [What a coordinate's state means](contract/states.md) -- the seven
  states, and why "the plan does not say it" and "we stopped looking" stay
  two different findings.
- [How much of a value the run can stand behind](contract/trust.md) -- the
  three levels and the closed list of reasons behind a C.
- The harvest contract per profile: [kwp](contract/kwp.md),
  [scenarios](contract/scenarios.md).

[Back to the index](README.md)
