# 1. Getting the documents in

## Purpose

File processing is the first stage of the pipeline (see [How the parts fit
together](../pipeline.md)) and the only one that loads no model and opens no
GPU. Its job is narrow: decide which documents exist in the corpus. A
profile supplies a list of documents through
its own `Source` implementation (`profiles/<name>/source.py`); the core
turns that list into rows of the shared `Documents` table by doing the same
four things for every corpus (`docpipe/ingest/pipeline.py`): fetch the file,
refuse it if its text layer is unusable, write the `Documents` row, and link
versions.

Everything project-specific, a document's identity, its metadata, and what
other tables it needs, is delegated to the profile
through `SourceDoc.meta`/`payload` and the `Source.documents()`/
`after_document()` hooks (`docpipe/ingest/models.py`); the core never
inspects `payload`. Two profiles ship: `kwp` reads an Excel workbook of
German municipal heat plans and writes `OrganisationUnits`, `Municipalities`
and `MunicipalityMeta` rows alongside the shared tables; `scenarios` reads a
JSON crawl index of the literature the AR6 scenario database cites and
writes `Scenarios` and `DocumentScenarios` link rows instead. Every stage
after this one, from preprocessing onward, iterates the `Documents` table
and nothing else: a document this stage never registers does not exist for
the rest of the run, regardless of the PDF's quality.

## Position in the pipeline

| | |
|---|---|
| In | The profile's document list, read by `profiles/<name>/source.py`, plus any PDFs already staged in the data directory |
| Out | `Documents` and `DocumentMeta` rows, plus whichever tables the profile owns, in the SQLite database; the fetched PDFs in the data directory; up to three worklists next to the database |
| Resumes on | The document's filename already present in `Documents` (partially, see Method and Failure modes) |
| Needs | No served model and no GPU: a network connection for each download, and the profile's `Source` class |

No stage precedes file processing. The next stage is
[preprocessing](preprocessing.md), which opens the PDF the `Documents` row
names and reads its layout; nothing later in the chain looks at the source
PDF again until extraction locates a quote in it. The commands for running
the whole chain end to end are on [Running the pipeline](../running.md).

## Method

### Parsing the command line

`python -m scripts.fileprocessing` is the entry point
(`scripts/fileprocessing/pipeline.py:main`). `_build_parser()` declares
`--source` (aliased `--excel`, kept because existing job scripts still pass
it), `--db`, `--data-dir`, `--backfill-meta`, `--profile`, and
`--log-level`.

### Loading the profile

`main()` calls `load_profile(args.profile)` (`docpipe/profile.py`), which
imports `profiles.<name>.profile` and returns its `PROFILE` object, raising
`LookupError` for an unknown name. What a profile directory may contain is
described on [Profiles](../profiles.md).

### The backfill branch

If `--backfill-meta` is given, `main()` looks up
`profile.component("source", "backfill_meta")` and calls it with
`(source_path, db_path)`, then returns without touching `Documents`,
`Sections` or `Embeddings`. Only `kwp` provides one
(`profiles/kwp/source.py:backfill_meta`): it re-reads the full KWW sheet,
matches rows to municipalities already in the database by
`Gemeindeschlüssel`, and refreshes `MunicipalityMeta` alone. `scenarios`
exports no such function; `--backfill-meta` for it ends the run with
`SystemExit`.

### Resolving the source and starting the run

Otherwise `main()` looks up `profile.component("source", "SOURCE")`, again
`SystemExit` if absent, requires `--data-dir`, and calls
`docpipe.ingest.ingest(source_class(Path(args.source)), db_file, data_dir,
profile)`. `ingest()` (`docpipe/ingest/pipeline.py`) coerces its paths,
creates the data directory, opens the SQLite connection, and applies the
core schema plus the profile's own `schema.sql` in one transaction
(`docpipe/store/schema.py:apply`), which also sets `PRAGMA foreign_keys =
ON`; every statement is `CREATE TABLE IF NOT EXISTS`, unchanged by a
second run against the same database. The pragma is what enforces
`Documents.supersedes`'s `ON DELETE SET NULL` and the profile tables'
`ON DELETE CASCADE` references during this stage's run.

### Enumerating documents

`source.documents(connection)` is iterated; each call yields one
`SourceDoc`. The connection lets a profile write its own rows before it
can name a document's metadata:
`KwwSource.document_for()` writes an `OrganisationUnits` row through
`store.update_organisation_unit()` on every row it reads, before the PDF
has been fetched or gated at all. `Ar6Source` has no such early write.

### Registering one document

`register()` first checks `docs.document_exists(doc.filename, connection)`;
a filename already in `Documents` ends the call immediately, with no fetch
and no quality check. Otherwise it fetches the PDF (`fetch.download_pdf` if
the file is missing and `doc.url` is set, else `FileNotFoundError`), runs
the quality gate (`pdf_quality.check`), and on a usable or merely
text-missing verdict writes the row through `docs.add_document()`, counting
pages with `fetch.get_num_pages()` first.

### The text-quality gate

`pdf_quality.check()` samples up to `SAMPLE_PAGES` pages evenly across the
document, so an early page of ordinary text does not prevent detecting a
scanned body elsewhere. Three verdicts are possible: `UNREADABLE` (an exception, or zero
pages sampled), `NO_TEXT` (more than `MAX_EMPTY_FRACTION` of the sample
counts as near empty), and `BROKEN_ENCODING`, reached either by a
`(cid:N)` artefact anywhere in the sample, which fires regardless of how
much text was seen, or, only once at least `MIN_TEXT_CHARS` characters
were sampled, by a letters-to-characters ratio under `MIN_ALPHA_RATIO` on
both the whole sample and every individual page. Ordinary prose runs at
roughly 70 to 80 percent letters against a 0.5 threshold, and the check
accepts a document the moment any single sampled page carrying at least
`PROSE_PAGE_CHARS` characters of text clears that ratio, rather than
averaging the whole sample, because a flat average over a long report is
dominated by a numeric annex. `is_missing_text_layer()`
reads whether a reason string starts with `NO_TEXT`; that one check is the
whole switch between refusing a document and registering it anyway.

### Handling a refusal or an unreachable link

`register()` raises `UnusablePDF` for anything but a missing text layer;
`ingest()` catches it per document, logs the filename once, and continues
rather than stopping the run. `requests.RequestException` and `OSError`
(a failed request, a body not starting with `%PDF`, a missing local file
with no `url`) are caught the same way, keyed by filename, so several rows
sharing one broken file are reported once.

### Running the profile hook

`source.after_document(connection, doc)` runs for every `SourceDoc` that
did not raise inside `register()`, whether that document was newly
written, already present, or registered as a scan.
`KwwSource.after_document()` writes `Municipalities` and
`MunicipalityMeta`; `Ar6Source.after_document()` refreshes the
publication's `DocumentMeta` row and writes
`Scenarios`/`DocumentScenarios` links. A document that raised inside
`register()` is skipped here, `OrganisationUnits` being the one
exception noted above.

### Linking versions and reporting

After the whole loop, `docs.link_document_versions()`
(`docpipe/store/documents.py`) recomputes `is_current` and `supersedes`
across every `group_key`: the newest `published` date in a group becomes
current, and every older row points at its predecessor. It is not
incremental, recomputing the full grouping on every call, since a new
document anywhere in a group can change who is current elsewhere in it.
Finally, `ingest()` writes a worklist for each of the refused, unreachable
and scanned documents, or deletes a stale one left from an earlier run
(`_drop_stale`) when that category is empty this time. Only the refused
dictionary is also returned from `ingest()`; the rest reach a caller only
through logging and these files.

## Data model

`SourceDoc` (`docpipe/ingest/models.py`) is the core's normalized unit of
work: `external_id` (the profile's stable identity for the document, `kwp`:
the filename, `scenarios`: the DOI or, absent one, the crawl's slug),
`filename`, `url` (`None` means the file must already be in the data
directory), `group_key` (ties versions together), `published`, `meta`
(written into `DocumentMeta`), and `payload` (opaque to the core,
round-tripped to `after_document`).

`Source` is the interface a profile implements: `documents(connection)`
yields `SourceDoc` objects; `after_document(connection, doc)` runs once per
accepted document; an optional `__len__` drives the progress bar, and its
absence, the default, leaves the bar unbounded.

The `Documents` row (`docpipe/store/schema.sql`) carries `id`,
`external_id` (unique), `group_key`, `filename` (unique, not null),
`published`, `num_pages`, `added`, `is_current` (default 1), `supersedes`
(a self-reference), and `page_text_transcribed`, a column this stage never
writes: it stays `NULL` until preprocessing decides how many of a scanned
document's pages a model, rather than the PDF's own text layer,
supplied.

`DocumentMeta` is a one-row-per-document table the profile defines through
its own `schema.sql`, applied on top of the core schema. `kwp`'s carries
`organisation_unit` and `municipality_ags`; `scenarios`' carries `doi`,
`title`, `year`, `venue`, `is_oa` and `scenario_count`. `kwp` additionally
maintains `OrganisationUnits`, `Municipalities`, and a 30-column
`MunicipalityMeta` (`ags` plus the 29 columns `MUNICIPALITY_META_COLUMNS`
lists in `profiles/kwp/config.py`) copied from the KWW sheet; `scenarios`
maintains
`Scenarios` (one row per AR6 scenario id) and `DocumentScenarios`, the
many-to-many link between a publication and the scenarios it documents.
Both profiles are described further on their own pages,
[kwp](../profiles/kwp.md) and [scenarios](../profiles/scenarios.md).

Unlike every stage from preprocessing on, file processing writes nothing
under a document's `results/` directory (see [What each stage leaves
behind](../artifacts.md)); its only artifacts are database rows, the PDF
file on disk, and the worklists below.

Each worklist holds one tab-separated line per document, sorted by key:

| file | line shape |
|---|---|
| `rejected_pdfs.txt` | `filename`, `reason` |
| `unreachable_pdfs.txt` | `group_key`, `filename`, `reason`, `url` |
| `scanned_pdfs.txt` | `filename`, `reason` |

## Configuration

| name | kind | default | effect | where |
|---|---|---|---|---|
| `--source` / `--excel` | CLI flag | none, required | Path to the profile's document list | `scripts/fileprocessing/pipeline.py` |
| `--db` | CLI flag | none, required | Path to the SQLite database file | `scripts/fileprocessing/pipeline.py` |
| `--data-dir` | CLI flag | none; required unless `--backfill-meta` | Directory PDFs are read from and downloaded into | `scripts/fileprocessing/pipeline.py` |
| `--backfill-meta` | CLI flag | off | Skips the run; only refreshes a profile's own metadata | `scripts/fileprocessing/pipeline.py` |
| `--profile` | CLI flag | `$DOCPIPE_PROFILE` | Selects which `profiles/<name>` supplies `SOURCE` | `docpipe/profile.py` |
| `DOCPIPE_PROFILE` | environment variable | unset | Default for `--profile` | `docpipe/profile.py` |
| `--log-level` | CLI flag | `INFO` | Logging verbosity | `scripts/fileprocessing/pipeline.py` |
| `SAMPLE_PAGES` | module constant | 40 | Pages sampled evenly for the quality check | `docpipe/ingest/pdf_quality.py` |
| `EMPTY_PAGE_CHARS`, `MAX_EMPTY_FRACTION` | module constant | 50 chars, 0.8 | A page below 50 characters counts empty; above 0.8 of the sample empty gives `NO_TEXT` | `docpipe/ingest/pdf_quality.py` |
| `MIN_TEXT_CHARS`, `MIN_ALPHA_RATIO` | module constant | 2000 chars, 0.5 | Below 2000 sampled characters the letters ratio check is skipped; below 0.5 it is `BROKEN_ENCODING` | `docpipe/ingest/pdf_quality.py` |
| `PROSE_PAGE_CHARS` | module constant | 200 chars | Minimum text a sampled page needs before its ratio can accept the document | `docpipe/ingest/pdf_quality.py` |
| `BROWSER_HEADERS`, timeout | module constant, hardcoded | Chrome 126 UA, 30 seconds | Sent on every download; avoids a 403 from municipal servers | `docpipe/ingest/fetch.py` |
| `EXCEL_SHEET` | module constant, `kwp` | `"Datensatz Status quo KWP"` | Which sheet of the KWW workbook is read | `profiles/kwp/config.py` |
| `PDF_OVERRIDES`, `SHARED_FILE_OWNERS` | module constant, `kwp` | 329, 4 entries | Per-municipality filename override; owner of a shared non-convoy file | `profiles/kwp/config.py` |
| `SCENARIO_FILE`, `PUBLICATION_META_FILE` | module constant, `scenarios` | two JSON filenames | Optional siblings of `pdf_index.json` for scenario names and OpenAlex fields | `profiles/scenarios/config.py` |
| `AVAILABLE_STATUS`, `PUBLISHED_DAY` | module constant, `scenarios` | `"pdf"`, `"0101"` | Index status meaning a PDF exists; day suffix for a publication's year | `profiles/scenarios/config.py` |
| `PDF_SUFFIX` | module constant, `scenarios` | `".pdf"` | Appended to a publication's slug to build its filename | `profiles/scenarios/config.py` |

## Failure modes

- A broken ToUnicode map or an unreadable file (`BROKEN_ENCODING` or
  `UNREADABLE`) makes `register()` raise `UnusablePDF`. No `Documents` row
  is written and `after_document` never runs; the filename is logged once
  and added to `rejected_pdfs.txt`. Fatal only for that one document, the
  run continues.
- A missing text layer (`NO_TEXT`) is not a refusal. The document is
  registered, `after_document` still runs, and the filename goes to
  `scanned_pdfs.txt` instead, because preprocessing's
  `--transcribe-missing-text` step can still read its pages with a model.
- A failed download, a response or local file that does not start with
  `%PDF`, or a `SourceDoc` with no local file and no `url`, raises inside
  `register()`; `ingest()` catches it, logs it once per filename, records
  it in `unreachable_pdfs.txt`, and continues. One dead municipal link
  excludes one document, not the run.
- A filename already in `Documents` short-circuits `register()` before the
  fetch and the quality gate, but `after_document` still runs for that
  `SourceDoc`. A re-run against an unchanged filename therefore still
  refreshes `MunicipalityMeta` (`kwp`) or publication metadata and
  scenario links (`scenarios`); it does not do nothing.
- `KwwSource.document_for()` writes an `OrganisationUnits` row during
  enumeration, before the PDF is fetched or gated, so a refused or
  unreachable `kwp` document can still leave that one row behind, unlike
  `Municipalities`/`MunicipalityMeta`, which wait for `after_document`.
- A job killed mid-download leaves nothing under the real filename:
  `download_pdf()` writes to a temporary file, replacing the target only
  once the write completes.
- `fetch.get_num_pages()` checks for a `%PDF` header before calling
  `fitz.open()`, which can crash on a malformed file, and
  `fetch.download_pdf()` checks the same header on a downloaded body
  before ever saving it; `pdf_quality.inspect()` performs no such check
  before its own `fitz.open()` call, so a malformed file already in the
  data directory reaches the quality gate unguarded.
- A worklist left over from an earlier run is deleted once the current
  run has nothing to report for that category (`_drop_stale`), so an
  empty `unreachable_pdfs.txt` never survives as this run's result.
- A KWW export that drops or renames a metadata column leaves that column
  out of `extract_meta()`'s result, rather than writing it as `NULL`, so a
  later, poorer export cannot erase a value an earlier one stored.
- Two municipalities sharing one file with no `Konvoi ID` between them are
  logged as a warning; a single member's convoy id suppresses the warning
  for the whole file, which is why `SHARED_FILE_OWNERS` exists as a manual
  correction.
- `profile.component("source", "SOURCE")` returning `None` ends the run
  with `SystemExit`, naming the missing `SOURCE` attribute;
  `"backfill_meta"` returning `None` also raises `SystemExit`, but names
  the `--backfill-meta` flag, not the attribute. So does calling the CLI
  without `--data-dir` when `--backfill-meta` is not given.

## Measured behaviour

- An earlier version of the quality gate refused any PDF with no text layer
  instead of registering it as a scan; that verdict kept eleven complete
  plans out of the corpus (`docpipe/store/schema.sql`, the
  `Documents.page_text_transcribed` comment; `docpipe/ingest/pdf_quality.py`
  module docstring).
- An earlier version of the garbled-text check also required the sample to
  contain no umlauts. That rule accepted German prose only and excluded the
  first non-German corpus's readable 318-page report
  (`docpipe/ingest/pdf_quality.py`, comment on the alpha-ratio check).
- The August 2026 KWW export carried 24 of the sheet's usual 35 metadata
  columns (`profiles/kwp/source.py`, the `extract_meta` docstring;
  `tests/test_kwp_source.py`, comment).
- The smallest-ags rule for a shared, non-convoy file picked the wrong
  municipality in all three cases it is known to have applied to, which is
  why `SHARED_FILE_OWNERS` exists at all (`profiles/kwp/source.py`, comment
  on `group_keys_by_filename`).
- One publication can document up to 146 AR6 scenarios, and one scenario
  can be documented by up to three publications
  (`profiles/scenarios/schema.sql`, comment; exercised in
  `tests/test_scenarios_source.py` with 146 scenario ids).

## Verification

- `test_registers_documents_and_calls_the_profile_hook` and
  `test_a_document_is_registered_once`: two documents each get a row and
  each trigger the profile hook; two entries sharing one filename produce
  one `Documents` row but still fire `after_document` twice.
- `test_works_without_a_profile`: `ingest()` with `profile=None` still
  writes the `Documents` row and creates no `DocumentMeta` table.
- `test_gate_accepts_normal_german_text`,
  `test_english_prose_passes_without_an_umlaut_in_sight`, and
  `test_a_statistical_annex_is_not_a_broken_glyph_map`: ordinary German
  and English prose pass, and so does a document mostly made of numeric
  tables with one prose page in twelve.
- `test_gate_rejects_scan_without_text`, `test_gate_rejects_garbled_text`,
  and `test_gate_rejects_unreadable_file`: an all-blank sample, 40 pages of
  garbled encoding, and a truncated non-real PDF yield `NO_TEXT`,
  `BROKEN_ENCODING`, and `UNREADABLE`.
- `test_gate_samples_across_the_document`: a 60-page PDF with text only on
  its first two pages is rejected `NO_TEXT`, so a cover page does not
  prevent detecting a scanned body elsewhere.
- `test_only_a_missing_text_layer_gets_the_benefit_of_the_doubt`:
  `is_missing_text_layer()` is true only for a `NO_TEXT`-prefixed reason.
- `test_a_scan_is_registered_rather_than_refused` and
  `test_a_registered_scan_is_named_on_its_own_worklist`: a `NO_TEXT`
  verdict is registered, not refused, and named on `scanned_pdfs.txt`,
  never `rejected_pdfs.txt`.
- `test_unusable_pdf_leaves_nothing_behind`: a `BROKEN_ENCODING` verdict
  leaves an empty `Documents` table and a `rejected_pdfs.txt`.
- `test_a_scan_reaches_the_register_and_its_municipality_with_it`: a
  scanned `kwp` document reaches both `Documents` and `Municipalities`.
- `test_missing_local_file_without_url_is_an_error`: `register()` raises
  `FileNotFoundError` for a missing file with no `url`.
- `test_a_dead_link_does_not_stop_the_run`,
  `test_the_dead_links_are_written_out_as_a_worklist`, and
  `test_one_dead_convoy_link_is_reported_once`: one 404 among several
  documents does not abort the run, `unreachable_pdfs.txt`'s line is
  `group_key`, `filename`, `reason`, `url`, and several entries pointing
  at one dead filename log one warning and one worklist line.
- `test_a_missing_override_file_lands_on_the_worklist_too`: an override
  naming a file absent from the data directory is reported, not a crash.
- `test_a_clean_run_clears_the_previous_worklists` and
  `test_the_scan_worklist_is_cleared_by_a_clean_run`: a worklist from an
  earlier run is removed once the current run has nothing to put on it.
- `test_versions_are_linked_after_ingest`: of two documents sharing a
  `group_key`, the one with the newer `published` date ends
  `is_current=1`.
- `test_override_replaces_broken_link` and
  `test_non_override_uses_kww_link`: `PDF_OVERRIDES` decides the filename
  when present, the KWW link otherwise.
- `test_the_three_pasted_links_are_resolved_by_their_own_plans`: all three
  known `SHARED_FILE_OWNERS` cases resolve the wrongly linked municipality
  to its own plan.
- `test_a_doi_identifies_a_publication` and
  `test_an_entry_without_a_doi_falls_back_to_its_slug`: `external_id` is
  the DOI when present, the crawl's slug otherwise.
- `test_a_publication_with_many_scenarios_is_counted_and_linked`: 146
  scenario ids yield `scenario_count=146` and 146 `DocumentScenarios` rows.
- `test_a_second_import_refreshes_instead_of_duplicating` and
  `test_metadata_that_arrives_later_reaches_an_imported_corpus`: a re-run
  refreshes metadata and links rather than duplicating them, and fills in
  fields a first import left null.

## Modules

`docpipe/ingest/__init__.py` re-exports the area's public surface:
`Source`, `SourceDoc`, `UnusablePDF`, `ingest`, `register`. It is what
`scripts/fileprocessing/pipeline.py` and `tests/test_ingest.py` import
from.

`docpipe/ingest/pipeline.py` holds the stage's orchestration: `register()`
for one document, `ingest()` for a whole run, and the worklist reporting
helpers. It is called by `scripts/fileprocessing/pipeline.py:main()` and
directly by `tests/test_ingest.py`, `tests/test_kwp_source.py`, and
`tests/test_scenarios_source.py`.

`docpipe/ingest/fetch.py` downloads a PDF to disk, atomically, and counts
its pages with PyMuPDF, guarding both against a non-PDF file that could
crash the process. It is called from `register()`.

`docpipe/ingest/pdf_quality.py` grades a PDF's text layer as usable, a
scan, garbled, or unreadable, by sampling pages with PyMuPDF; it states the
fact and leaves the decision of what to do with it to the caller. It is
called from `register()`, whose `is_missing_text_layer()` reading of its
verdict decides refusal from registration.

`docpipe/ingest/models.py` holds the contract a profile implements:
`SourceDoc`, what a document is, and `Source`, how a profile yields and
finishes documents, plus the `UnusablePDF` exception. It is imported by
`docpipe/ingest/pipeline.py` and by `profiles/kwp/source.py` and
`profiles/scenarios/source.py`.

`scripts/fileprocessing/__init__.py` re-exports `main()` as the package's
public entry point.

`scripts/fileprocessing/pipeline.py` is the command-line interface:
argument parsing, profile resolution, the `--backfill-meta` branch, and the
call into `docpipe.ingest.ingest()`. It holds no pipeline logic of its own.

## Module reference

The docstring of each module of this stage, verbatim from the code and generated by `scripts/build_docs.py`. The chapter above is the account; this is the reference. Edit the docstring, not this page.

<details>
<summary><code>docpipe/ingest/__init__.py</code></summary>

__init__.py: Exposes the Source contract and the ingest and register
functions that get a profile's documents into its database.

</details>

<details>
<summary><code>docpipe/ingest/pipeline.py</code></summary>

pipeline.py: Registers a profile's documents in its database.

The core repeats four steps for every corpus: it fetches the file,
checks its text layer, writes the Documents row, and links versions.
A file whose text is unreadable or garbled is refused and left out
of the corpus. A file with no text layer at all is registered
anyway and listed for preprocessing to read with the vision model,
because the pages exist to be read. What the documents are and
where they come from is defined by the profile's Source.

Author: Felix Vossel

</details>

<details>
<summary><code>docpipe/ingest/fetch.py</code></summary>

fetch.py: Downloads a source PDF to disk and counts its pages.

download_pdf sends a browser User-Agent, because municipal sites answer a
default requests client with 403, and writes the response through a temporary
file before the atomic rename, so a killed job leaves no partial PDF for a
later run to reuse. get_num_pages and download_pdf both check the file for a
%PDF header before handing it to PyMuPDF, which can segfault on a truncated or
non-PDF file rather than raise.

Author: Felix Vossel

</details>

<details>
<summary><code>docpipe/ingest/pdf_quality.py</code></summary>

pdf_quality.py: Grades what a source PDF's text layer is worth.

Stage 1 reads text with PyMuPDF, never OCR. A PDF with a broken ToUnicode map
yields symbol garbage, useless at every later stage. A PDF with no text layer
at all yields nothing, which preprocessing can now make good by rendering the
page and having the model read it (page_text_fallback).

`check()` reports the fact and nothing more. What to do about it is policy, and
lives in the ingest pipeline: garbled text is refused, a scan is registered and
put on a worklist. Keeping the two apart is the point. This module used to
decide both, and its verdict on a scan cost the corpus eleven complete plans.

</details>

<details>
<summary><code>docpipe/ingest/models.py</code></summary>

models.py: What a profile hands the ingest step.

The core knows a document by four things: what to call it, where to get it, who
it is, and which other documents are versions of it. Everything else is the
profile's business and travels in `meta` (written to DocumentMeta) or `payload`
(never inspected by the core).

Author: Felix Vossel

</details>

<details>
<summary><code>scripts/fileprocessing/__init__.py</code></summary>

__init__.py: CLI entry point for registering a profile's source PDFs.

The generic half lives in docpipe.ingest, the project-specific half in
profiles/<name>/source.py.

Runs as a command line module:
  python -m scripts.fileprocessing --profile kwp --source kww.xlsx
      --db data/kwp/kwp.db --data-dir data/kwp/pdf

</details>

<details>
<summary><code>scripts/fileprocessing/pipeline.py</code></summary>

pipeline.py: CLI for registering a profile's documents.

The work lives in docpipe.ingest (generic) and profiles/<name>/source.py
(project-specific); this module is only the entry point.

Author: Felix Vossel

</details>

[Back to the index](../README.md)
