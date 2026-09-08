<a href="https://openenergy-platform.org/"><img align="right" width="200" height="200" src="https://avatars2.githubusercontent.com/u/37101913?s=400&u=9b593cfdb6048a05ea6e72d333169a65e7c922be&v=4" alt="OpenEnergyPlatform"></a>

# Open Energy Family – municipal-heat-planning-pdf-processing

Tools and scripts developed to support the [MHPO development](https://github.com/OpenEnergyPlatform/municipal-heat-planning-ontology) by automating data extraction, enrichment, and semantic indexing of municipal heat planning documents (Kommunale Wärmepläne).

## Profiles

The pipeline itself is generic: `docpipe/` knows about PDFs, not about heat
plans. What a project contributes lives in `profiles/<name>/` — where its
documents come from (`source.py`), the tables it adds (`schema.sql`), the
prompts it runs on (`prompts/<stage>/`) and the filters its app offers.

Pick one per run. The profile also decides where the data lives
(`data/<name>/`), so two projects never share a database or an index:

```bash
export DOCPIPE_PROFILE=kwp
python -m docpipe.preprocessing            # paths come from the profile
```

The prompts belong to the profile, all of them — the core has no defaults. A
prompt names the corpus it was written for and the language it answers in, and
neither is something `docpipe/` could guess; a fallback could only be some
other project's prompt. A stage whose profile has no prompt for it says so and
stops.

Set the profile in the environment rather than only passing `--profile`: a
stage binds its prompts when it is imported, before the command line is parsed.
A profile that carries prompts and is named only on the command line is refused
rather than run with the wrong ones.

Per-module reference, the artifact hand-off and the harvest contract are under
[docs/](docs/README.md). Every page there except `docs/pipeline.md` is
generated from the code it describes by `scripts/build_docs.py`, and the test
suite fails when a page and its source disagree. `.github/workflows/docs.yml`
publishes the pages on every push to `develop` and every tag, one directory per
version, to
[openenergyplatform.github.io/municipal-heat-planning-pdf-processing](https://openenergyplatform.github.io/municipal-heat-planning-pdf-processing/);
`.readthedocs.yaml` builds the same tree on Read the Docs.

## Pipeline Overview

The pipeline transforms raw PDF documents into a searchable, semantically indexed, versioned knowledge base. Five independent Python modules, run in sequence, cover six logical processing stages:

| # | Stage | Module | Writes |
| --- | --- | --- | --- |
| 1 | File processing – download PDFs, extract metadata, populate the document database | `docpipe.ingest` + profile | *(database)* |
| 2 | Layout detection – identify tables, figures, titles, headers via PP-DocLayoutV3 | `docpipe.preprocessing` | `pages.json` |
| 3 | Text extraction & structure – build a structured JSON document, deterministic cleanup | `docpipe.preprocessing` | `sections.json` |
| 4 | LLM refinement – clean extraction artefacts, normalize titles/captions, bibliographies to BibTeX | `docpipe.refinement` | `sections_refined.json` |
| 5 | Image processing – Markdown transcriptions for tables, descriptions for figures | `docpipe.visuals` | `visuals.json` |
| 6 | Chunking, embedding & database population | `docpipe.chunking` | `document.json` |

The artefacts live under `data/pdf/processed/<doc>/results/` and are named after
what they hold, not after the stage that wrote them; `docpipe/artifacts.py` is
the single place they are spelled out. Each stage resumes incrementally — only
documents or items missing their output are reprocessed — so any stage can be
re-run in isolation. A tree processed before the rename is brought forward with
`python -m docpipe.migrate_artifact_names <processed root> --apply`.

### 1. File processing (`docpipe.ingest` + profile)

The source of truth is an Excel export from the KWW listing every published Wärmeplan (municipality, organisation unit, state, publication date, PDF link). For every completed plan with a valid PDF link, the pipeline downloads the PDF, extracts its page count, and creates `Documents` / `OrganisationUnits` / `Municipalities` rows.

Municipal links rot faster than the register is corrected, so a download failure
does not end the run: unreachable links are collected and written to
`unreachable_pdfs.txt` next to the database (PDFs that download but fail the
quality gate go to `rejected_pdfs.txt`), and a clean run deletes both. A
replacement found by hand is recorded in the profile's `PDF_OVERRIDES` — the
file is then read from the data directory and never fetched.

Documents sharing a municipality key (`ags`, the German Gemeindeschlüssel) are versions of the same plan — see [Versioning](#versioning).

### 2. Layout detection (`docpipe.preprocessing`, stage 2)

Each PDF page is rendered to a high-resolution PNG and analysed by [PP-DocLayoutV3](https://huggingface.co/PaddlePaddle/PP-DocLayoutV3_safetensors), which classifies structural elements — tables, figures, titles, text blocks, headers/footers, page numbers, captions — each with a bounding box and a confidence score.

### 3. Text extraction & structure (`docpipe.preprocessing`, stage 3)

PyMuPDF extracts character-level text from each page and matches it against the Stage 2 layout to build a structured JSON representation of the document. Each document is split into sections carrying a title, page number, body text, and placeholder tokens (e.g. `[p13_tbl0]`) marking where a table or figure sits in the reading order. Tables/figures are cropped from the rendered page images and saved as individual PNGs.

A deterministic cleanup pass (no LLM) strips repeated header/footer lines, drops directory/index-listing pages, and normalises section titles.

Output: `sections.json` per PDF.

### 4. LLM refinement (`docpipe.refinement`)

An LLM served locally via [vLLM](https://github.com/vllm-project/vllm) cleans the artefacts that are hard to catch deterministically: misattributed captions, residual boilerplate, bibliography pages. It operates in a sliding window over a document's sections (carrying context from the previous window so it can merge across window boundaries) and, per section, decides to keep, merge into the previous section, split, remove, or replace it. Bibliographies are converted to BibTeX.

Output: `sections_refined.json`.

### 5. Image processing (`docpipe.visuals`)

Every visual element is enriched with a vision-language model — the same model as Stage 4, but served by its own vLLM instance so the two stages can run concurrently. Tables get a structured Markdown transcription; figures get a textual description; missing captions are generated from the image and its surrounding context. A QA gate checks each table transcription for content coverage (against the PyMuPDF source text) and repeated-row duplication, retrying poor transcriptions with feedback.

Output: `visuals.json`.

### 6. Chunking, embedding & database population (`docpipe.chunking`)

1. **Merge** — Stage-4 sections and Stage-5 enrichments are combined by ID into `document.json`.
2. **Database population** — sections, tables, and images are written to SQLite with page-level provenance: each `Sections` row records which pages it spans (`SectionPages`) and an ordered list of page-tagged text/table/figure pieces (`Segments`), so a retrieved chunk can be cited down to the exact source page. A segment also carries the `bbox` it occupied in the source PDF, which lets a citation be highlighted in place rather than searched for by text.
3. **Embedding** — six embedding types per document (see below) are produced by [Qwen3-VL-Embedding-8B](https://huggingface.co/Qwen/Qwen3-VL-Embedding-8B), loaded in bfloat16 and data-parallel across every visible GPU (one model replica per GPU). Documents are read and prepared in a thread pool while the GPUs work on the items already collected, and each block of them is embedded in batches sorted by text length, so a batch pads to the length of its own members rather than to the longest text in the corpus. Vectors are L2-normalised and added to a single global FAISS index (`IndexIDMap` over `IndexFlatIP`). The database is the source of truth for what has already been embedded, so re-runs only embed missing items.

## Key Dependencies and Models

### Models

| Model | Provider | Parameters | Usage in Pipeline |
| --- | --- | --- | --- |
| [PP-DocLayoutV3](https://huggingface.co/PaddlePaddle/PP-DocLayoutV3_safetensors) | PaddlePaddle | — | Document layout detection (Stage 2) |
| Qwen3.5-122B-A10B-FP8 | Alibaba / Qwen | 122B MoE (FP8) | LLM section refinement (Stage 4) **and** vision-language image processing (Stage 5) — one model, one vLLM instance per stage |
| [Qwen3-VL-Embedding-8B](https://huggingface.co/Qwen/Qwen3-VL-Embedding-8B) | Alibaba / Qwen | 8B | Multimodal embeddings (Stage 6): 4096-dimensional text and vision-language vectors |

### Python Libraries

[vLLM](https://github.com/vllm-project/vllm) serves the LLM stages (one instance each for 4 and 5),
reached through the [openai](https://github.com/openai/openai-python) client.
[Transformers](https://huggingface.co/docs/transformers/) runs PP-DocLayoutV3 (Stage 2) and the
embedding model (Stage 6), with [qwen-vl-utils](https://github.com/QwenLM/Qwen2.5-VL) for vision
input preprocessing. [PyMuPDF](https://pymupdf.readthedocs.io/) (rawdict mode) extracts text and
renders pages; [Pillow](https://pillow.readthedocs.io/) crops layout regions.
[FAISS](https://github.com/facebookresearch/faiss) holds the vectors, [SQLite](https://www.sqlite.org/)
the metadata, and [pandas](https://pandas.pydata.org/) reads the KWW Excel manifest.

## Database Schema

SQLite, foreign keys enabled:

| Table | Content |
| --- | --- |
| OrganisationUnits | Municipal planning bodies |
| Municipalities | Municipalities linked to an organisation unit (unique `ags` / Gemeindeschlüssel) |
| Documents | PDF metadata (filename, publication date, page count) plus versioning: `municipality_ags` groups re-published plans, `is_current` marks the latest, `supersedes` chains each older version to its successor |
| Pages | One row per physical page of a document |
| Sections | Retrieval chunks: title, primary page number, full content |
| SectionPages | Which pages a section spans (many-to-many) |
| Segments | Ordered, page-tagged text/table/figure pieces inside a section — the fine-grained provenance used to cite a chunk down to the exact page. `Segments.page` is a FK to `Pages.id`, not a page number |
| Tables | Extracted tables: image path, caption, Markdown transcription |
| Images | Extracted figures: image path, caption, textual description |
| Embeddings | One row per FAISS vector (`faiss_id`), typed (`embedding_type`) and linked to its owning section/table/figure (`owner_kind`, `owner_id`) |

## Versioning

Municipalities occasionally re-publish their Wärmeplan. Every version is kept: documents sharing a `municipality_ags` are grouped, the one with the newest publication date is flagged `is_current`, and each older version points at its successor via `supersedes`. Retrieval can filter to current-only documents.

One plan often covers several municipalities that planned jointly, so the same PDF appears under many `ags`. The group key is then the smallest of them, computed from the register rather than from whichever row was registered first — otherwise re-sorting the source sheet would drop next year's edition into a different group and leave both editions flagged current. Where a shared file belongs to a municipality that is *not* the smallest, the profile names the owner explicitly (`SHARED_FILE_OWNERS`).

## Embedding Strategy

Six embedding types are produced per document, all stored in a single global FAISS index:

| Type | Content | Owner |
| --- | --- | --- |
| `section_text` | Title + full section content (placeholders replaced with table/figure content) | Section |
| `section_title` | Section title alone | Section |
| `table_text` | Caption + Markdown transcription | Table |
| `table_vl` | Table image + caption + Markdown | Table |
| `figure_text` | Caption + description | Image |
| `figure_vl` | Figure image + caption + description | Image |

## Querying the corpus

The batch pipeline above produces the corpus; `docpipe.inference` reads it. One
question becomes a search phrase, an embedded query, a sub-index over the
selected document and scopes, and finally an answer with a citation resolved
down to the page — and, where a `bbox` was stored, to the highlighted passage in
the source PDF. `docpipe.embedding` provides the query-side embedder (a local
model or an API), separately from the batch embedder so a query does not need a
whole GPU.

[`scripts/inference_app/`](scripts/inference_app/README.md) is the Streamlit
front-end around it, and documents its own configuration.

## Collaboration

Everyone is invited to develop this repository with good intentions.
