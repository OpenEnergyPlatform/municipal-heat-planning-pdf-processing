## What this repository does

The repository holds `docpipe/`, a document pipeline that turns PDF reports
into a searchable corpus, a SQLite database paired with a FAISS vector
index, and then reads typed values out of that corpus into a knowledge
graph. A value is accepted into the graph only once a model's claim about
it has been checked against its source text or image and assigned an
evidence tier. `docpipe/` has no project-specific knowledge: it defines
how to read a PDF and how to harvest a value, and does not encode what a
municipal heat plan or a scenario report says. What is project specific
(where the documents come from, which extra database tables they need,
which prompts a stage runs on) lives in a `profiles/<name>/` directory,
selected by `DOCPIPE_PROFILE` or a `--profile` flag before a stage starts.

Two profiles exist. `kwp` covers German municipal heat plans and answers
in German; its accepted values go into MHPKG on the Open Energy Platform.
`scenarios` covers the literature the IPCC AR6 scenario database cites and
answers in English; its accepted values go into OEKG, whose identifiers
are minted under the Open Energy Platform's own domain by default
(`profiles/scenarios/kg.py`). The two share every module under `docpipe/`;
what differs is confined to their own directory: where the documents come
from, what a document's metadata looks like, and the questions their
extraction stage asks.

## Stages in order

The stages run in this order, each one resuming on what an earlier run
already wrote for a document; [how the parts fit together](pipeline.md)
states, stage by stage, what causes a re-run.

| Stage | Name | Reads | Writes | Page |
|---|---|---|---|---|
| 1 | Getting the documents in | a profile's document list | `Documents`/`DocumentMeta` rows, the downloaded PDF | [stages/fileprocessing.md](stages/fileprocessing.md) |
| 2 to 3 | Reading the page | the PDF file | `pages.json`, then `sections.json` | [stages/preprocessing.md](stages/preprocessing.md) |
| 4 | Repairing the text | `sections.json` | `sections_refined.json` | [stages/refinement.md](stages/refinement.md) |
| 5 | Reading the pictures | `sections_refined.json` (or `sections.json`), table or figure crops | `visuals.json` | [stages/visuals.md](stages/visuals.md) |
| 6 | Chunking, embedding, indexing | `sections_refined.json`, `visuals.json`, then `document.json` | `document.json`, then database rows and FAISS vectors | [stages/chunking.md](stages/chunking.md) |
| 7 | Reading the values out | the database and the FAISS index | one JSONL harvest and one stamp per document | [stages/extraction.md](stages/extraction.md) |
| 8 | The knowledge graph | the accepted tuples of a harvest | one Turtle file per `--serialize` call | [stages/graph.md](stages/graph.md) |

Filenames are the constants `docpipe/artifacts.py` defines; [what each
stage leaves behind](artifacts.md) lists them all, with the stage that
writes each one. The answer side, a Streamlit application
(`scripts/inference_app/app.py`) that reads the finished database and
index, writes nothing back, and installs from
`scripts/inference_app/requirements.txt` rather than the batch pipeline's,
is not a numbered stage and is documented under [asking the
corpus](stages/inference.md) and [the chat over the corpus](stages/app.md).

## How the documentation is organised

[How the parts fit together](pipeline.md) is one of three hand-written
pages under `docs/` that the generator leaves untouched, together with
[running the pipeline](running.md) and [glossary](glossary.md)
(`scripts/build_docs.py:63`). It states what a single stage's own chapter
cannot: the whole chain from a PDF to a graph, what one stage must supply
to the next, and the points where two stages read the same input and can
run at the same time.

Twelve chapters sit under `stages/`, one per pipeline stage or per part
every stage depends on (`scripts/build_docs.py:296`). [Getting the
documents in](stages/fileprocessing.md) through [the knowledge
graph](stages/graph.md) are the eight numbered stages of the table above;
[the embedders](stages/embedding.md), [asking the
corpus](stages/inference.md), [the chat over the corpus](stages/app.md),
[the database](stages/store.md) and [the parts every stage
uses](stages/core.md) cover what those stages and the chat application
depend on.

[Profiles](profiles.md) states what a profile is and is not: a directory
under `profiles/<name>/` that the core finds by name and asks for whatever
a stage needs, never a shared base class or registry entry. [The
kwp profile](profiles/kwp.md) and [the scenarios
profile](profiles/scenarios.md) list each profile's own parameters and
axes, read off its published contract rather than its hand-written
specification.

Four pages under `contract/` publish what an extraction run may write.
[The harvest contract: kwp](contract/kwp.md) and [the harvest contract:
scenarios](contract/scenarios.md) list every parameter, axis and closed
answer list a harvest can contain. [What a coordinate's state
means](contract/states.md) and [how much of a value the run can stand
behind](contract/trust.md) name the vocabulary both contracts share.

[Glossary](glossary.md) fixes one term per concept. [Running the
pipeline](running.md) covers how to invoke each stage from the command
line, with the flags and environment variables each one reads.

The [API reference](api/index.md) has one page per module of `docpipe/`,
`profiles/`, `scripts/inference_app/` and `scripts/fileprocessing/`: every
public function, class and method with its signature as written and its
docstring. The chapters say what a module is for; the reference says what
it defines.

## How these pages are produced and checked

Every page under `docs/` except the three hand-written pages named above
is rendered from the code it describes, by `scripts/build_docs.py`. A
stage chapter's module reference section is a package's own module
docstrings, read with Python's `ast` module and kept verbatim inside a
collapsed block at the end of the chapter, never retyped. A page of the
API reference is the same module read the same way, down to its public
functions and classes, their signatures and their docstrings. A contract page
is read off a profile's published `extraction_schema.json`, never off its
`extraction_spec.json`, whose examples are real tables from real plans and
are never quoted here.

`tests/test_docs_build.py` holds a page and the code it describes
together. It fails the moment a checked-in page and a fresh render
disagree (`test_the_checked_in_docs_are_the_generated_ones`), the moment a
page quotes a corpus passage
(`test_no_generated_page_quotes_a_corpus_passage`), or the moment a page
uses a dash as punctuation (`test_no_page_uses_a_dash_as_punctuation`; the
module pages of the API reference carry the code's docstrings verbatim and
are left out there).
`.github/workflows/docs.yml` runs that check on every pull request that
touches a documented source and on every `v*` tag, and, on a push to
`develop`, regenerates the pages instead and commits them when changed.
Either way, Sphinx then builds the site the way Read the Docs does, from
`docs/conf.py` and `.readthedocs.yaml`
(`test_the_docs_workflow_regenerates_on_develop_and_checks_everywhere_else`).
Read the Docs rebuilds the hosted site from its own webhook once new
pages are committed to a tracked branch or tag.

The pipeline's own correctness is checked separately: [running the
pipeline](running.md) describes a suite of about 1,500 tests
(`requirements.txt`, the comment above `pytest`), run with `pytest tests/
-n 8 --dist loadfile`.
