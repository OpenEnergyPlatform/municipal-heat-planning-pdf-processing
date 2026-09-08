# 1. Getting the documents in

| | |
|---|---|
| **In** | A profile's Source (its document list -- Excel sheet, crawl index, etc., via `profiles/<name>/source.py`) plus any PDFs already cached in the data directory. |
| **Out** | `Documents` and `DocumentMeta` rows in the profile's SQLite database, the downloaded PDFs in the data directory, and `unreachable_pdfs.txt` / `rejected_pdfs.txt` / `scanned_pdfs.txt` next to the database. |
| **Resumes on** | `document_exists()` skips any filename already in `Documents`, so a re-run only touches new documents -- delete a document's `Documents` row (and its file, to force re-download) to make it redone. |

This is the first of the pipeline's six stages, and the only one that has nothing to do with a PDF's content -- its job is to decide which documents exist at all. A profile hands it a list of documents to source (an Excel export for kwp, a link list for scenarios, whatever `profiles/<name>/source.py`'s `SOURCE` class yields as `SourceDoc` objects), and this stage turns that list into rows in the shared `Documents` table: one row for every document it can fetch and that clears the text-quality gate -- including a scanned PDF with no text layer of its own, which is registered too, because a later stage renders its pages and has a model read them instead of PyMuPDF. Every stage after this one -- layout detection, text extraction, refinement, image processing, chunking -- iterates the `Documents` table and nothing else, so a document this stage never registers does not exist for the rest of the run, no matter how good the PDF actually is.

An engineer runs it as `python -m scripts.fileprocessing --profile <name> --source <path> --db <path> --data-dir <path>` (`scripts/fileprocessing/pipeline.py`), which resolves the profile's `SOURCE` class and calls `docpipe.ingest.ingest()` (`docpipe/ingest/pipeline.py`). For each `SourceDoc` the source yields, `register()` downloads the PDF into the data directory if it is not already there (`fetch.download_pdf`), counts its pages with PyMuPDF (`fetch.get_num_pages`), and writes one row into `Documents` -- filename, external_id, group_key, published, num_pages, added -- through `add_document` in `docpipe/store/documents.py`, plus whatever the profile put into `SourceDoc.meta` into that profile's own `DocumentMeta` table. The core writes nothing else to the database: a profile's own rows (`OrganisationUnits` and `Municipalities` for kwp, per the README) are written by the source itself, once per accepted document, through `Source.after_document`. At the end of a run the stage also writes up to three plain-text worklists next to the database: `unreachable_pdfs.txt`, `rejected_pdfs.txt` and `scanned_pdfs.txt`.

The decision most likely to surprise a reader sits in `docpipe/ingest/pdf_quality.py`: a PDF with no text layer at all and a PDF with garbled text both fail `check()`, but only one of them is fatal. `is_missing_text_layer()` is the switch `register()` uses to tell the two apart. A scan (verdict `NO_TEXT`) is registered anyway and logged to `scanned_pdfs.txt`, because its pages are still there to be rendered and read by a model in preprocessing's `--transcribe-missing-text` step. A broken ToUnicode map (`BROKEN_ENCODING`) is refused and logged to `rejected_pdfs.txt`, because symbol garbage is useless at every later stage and nothing downstream can repair it. The module docstring is explicit about why the two are not treated alike: an earlier version of this code refused a missing text layer as well, and that verdict is what kept eleven complete plans out of the corpus.

The garbled-text check has a second trap in the same file. Ordinary prose runs at roughly 70-80% letters (`MIN_ALPHA_RATIO` is set to 0.5), and `check()` accepts a document the moment any single sampled page clears that ratio (`m["best_alpha"]`), not the sample's average. That is deliberate: a flat average over the 40-page sample would fail a real, readable 300-page outlook whenever the sample happens to land inside its statistical annex. An earlier version of the rule also required the text to contain no umlauts, which discounted German prose specifically and cost the first non-German corpus a readable 318-page English report. Both details exist because each one broke on a real document, not because someone reasoned it out in the abstract.

This stage is the only one of the six that never loads a model or touches a GPU: its cost is a normal HTTP download per document plus a PyMuPDF page count and text sample, so it runs anywhere Python and a network connection do. What it depends on instead is the municipal websites the PDFs live on, and that dependency fails constantly -- links rot faster than the source register gets corrected. A failed download (`requests.RequestException` or `OSError`) does not stop the run: `ingest()` catches it per document, logs it, and continues, so one dead link costs one entry in the corpus, not the run. Everything unreachable is collected and written to `unreachable_pdfs.txt` (group key, filename, reason, URL, tab-separated) so a single run produces the whole worklist at once. A replacement sourced by hand goes into the profile's `PDF_OVERRIDES` and a copy of the file into the data directory under the expected filename; `download_pdf()` no-ops whenever that filename already exists, so the override is read once from disk and never fetched again.

The stage resumes by filename: `document_exists()` checks `Documents` before `register()` does anything else, so re-running the same source against the same database only processes filenames that are not in it yet, and a PDF already sitting in the data directory is not re-downloaded either. To force a document to be redone, delete its row from `Documents` by hand -- with the file left in the data directory, the next run reuses it and only repeats the quality check and the write; delete the file too to force an actual re-download. `link_document_versions()`, by contrast, is not incremental: it recomputes `is_current` and `supersedes` across every document sharing a `group_key` on every run, because a new publication anywhere in a group can change who is current everywhere in it.

Two more defenses are worth knowing before they look like bugs. First, both `get_num_pages()` and `download_pdf()` check that the first bytes are `%PDF` before handing anything to `fitz.open()`, because PyMuPDF can segfault rather than raise a catchable exception on a non-PDF or truncated file, and a segfault takes the whole run down rather than just one document. Second, `download_pdf()` writes to a temp file in the data directory and only `os.replace()`s it into the real filename once the write is complete, so a job killed mid-download cannot leave a partial `.pdf` that a later run's existence check mistakes for a finished file and hands straight to PyMuPDF. And a clean run -- nothing unreachable, rejected or scanned -- deletes any `unreachable_pdfs.txt`, `rejected_pdfs.txt` or `scanned_pdfs.txt` left over from an earlier one, because a worklist nobody wrote this time would otherwise read as this run's result.

## The modules

Verbatim from the module docstrings, generated by `scripts/build_docs.py`. Edit the docstring, not this page.

### `docpipe/ingest/__init__.py`

Getting a profile's documents into its database.

### `docpipe/ingest/pipeline.py`

pipeline.py – Register a profile's documents in its database.

The core does the same four things for every corpus: get the file, refuse it if
it has no usable text layer, write the Documents row, and link versions. What
the documents are and where they come from is the profile's Source.

Author: Felix Vossel

### `docpipe/ingest/fetch.py`

fetch.py – Getting a source PDF onto disk and counting its pages.

Author: Felix Vossel

### `docpipe/ingest/pdf_quality.py`

pdf_quality.py – What a source PDF's text layer is worth.

Stage 1 reads text with PyMuPDF, never OCR. A PDF with a broken ToUnicode map
yields symbol garbage, which is useless at every later stage; a PDF with no text
layer at all yields nothing, which preprocessing can now make good by rendering
the page and having the model read it (page_text_fallback).

`check()` reports the fact and nothing more. What to do about it is policy and
lives in the ingest pipeline: garbage is refused, a scan is registered and put on
a worklist. Keeping the two apart is the point — this module used to decide both,
and its verdict on a scan cost the corpus eleven complete plans.

### `docpipe/ingest/models.py`

models.py – What a profile hands the ingest step.

The core knows a document by four things: what to call it, where to get it,
who it is, and which other documents are versions of it. Everything else is
the profile's business and travels in `meta` (written to DocumentMeta) or
`payload` (never inspected by the core).

Author: Felix Vossel

### `scripts/fileprocessing/__init__.py`

fileprocessing – CLI entry point for registering a profile's source PDFs.

The generic half lives in docpipe.ingest, the KWW half in profiles/kwp/source.py.

Usage:
  python -m scripts.fileprocessing --profile kwp --excel kww.xlsx --db data/kwp/kwp.db --data-dir data/kwp/pdf

### `scripts/fileprocessing/pipeline.py`

pipeline.py – CLI for registering a profile's documents.

The work lives in docpipe.ingest (generic) and profiles/<name>/source.py
(project-specific); this module is only the entry point.

Author: Felix Vossel

[Back to the index](../README.md)
