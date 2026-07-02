<a href="https://openenergy-platform.org/"><img align="right" width="200" height="200" src="https://avatars2.githubusercontent.com/u/37101913?s=400&u=9b593cfdb6048a05ea6e72d333169a65e7c922be&v=4" alt="OpenEnergyPlatform"></a>

# Open Energy Family – municipal-heat-planning-pdf-processing

Tools and scripts developed to support the [MHPO development](https://github.com/OpenEnergyPlatform/municipal-heat-planning-ontology) by automating data extraction, enrichment, and semantic indexing of municipal heat planning documents (Kommunale Wärmepläne).

## Pipeline Overview

The pipeline transforms raw PDF documents into a searchable, semantically indexed, versioned knowledge base. It is organised as five independent Python modules, run in sequence, that together cover six logical processing stages:

| # | Stage | Module |
| --- | --- | --- |
| 1 | File processing – download PDFs, extract metadata, populate the document database | `fileprocessing` |
| 2 | Layout detection – identify tables, figures, titles, headers via PP-DocLayoutV3 | `preprocessing` |
| 3 | Text extraction & structure – build a structured JSON document, deterministic cleanup | `preprocessing` |
| 4 | LLM refinement – clean extraction artefacts, normalize titles/captions, bibliographies to BibTeX | `textrefinement` |
| 5 | Image processing – Markdown transcriptions for tables, descriptions for figures | `imageprocessing` |
| 6 | Chunking, embedding & database population | `chunkingandembedding` |

Each module reads/writes a per-document JSON artefact under `data/pdf/processed/<doc>/results/`, so any stage can be re-run in isolation and resumes incrementally — only documents/items missing their output are reprocessed, not the whole corpus.

### 1. File processing (`fileprocessing`)

The source of truth is an Excel export from the KWW listing every published Wärmeplan (municipality, organisation unit, state, publication date, PDF link). For every completed plan with a valid PDF link, the pipeline downloads the PDF, extracts its page count, and creates `Documents` / `OrganisationUnits` / `Municipalities` rows.

Re-published plans are supported: documents that share a municipality key (`ags`, the German Gemeindeschlüssel) are versions of the same plan. The newest publication date becomes the current version (`is_current`); older ones are kept and chained to the version they precede via `supersedes`, so historical plans are retained rather than overwritten.

### 2. Layout detection (`preprocessing`, stage 2)

Each PDF page is rendered to a high-resolution PNG and analysed by [PP-DocLayoutV3](https://huggingface.co/PaddlePaddle/PP-DocLayoutV3_safetensors) (PaddlePaddle, via HuggingFace Transformers), which classifies structural elements — tables, figures, titles, text blocks, headers/footers, page numbers, captions — each with a bounding box and a confidence score. These spatial coordinates are what let later stages separate visual content from body text and attach captions correctly.

### 3. Text extraction & structure (`preprocessing`, stage 3)

PyMuPDF extracts character-level text from each page and matches it against the Stage 2 layout to build a structured JSON representation of the whole document. Each document is split into sections carrying a title, page number, body text, and placeholder tokens (e.g. `[p13_tbl0]`) marking where a table or figure sits in the reading order. Tables/figures are cropped from the rendered page images and saved as individual PNGs.

A deterministic cleanup pass (no LLM involved) runs here too: repeated header/footer lines are detected and stripped, directory/index-listing pages are dropped, and section titles are normalised.

Output: `structured_output.json` per PDF.

### 4. LLM refinement (`textrefinement`)

The structured output from Stage 3 still carries extraction artefacts that are hard to catch deterministically: misattributed captions, residual boilerplate, bibliography pages that need reformatting. These are cleaned by an LLM served locally via [vLLM](https://github.com/vllm-project/vllm) (OpenAI-compatible server, continuous batching).

The model operates in a sliding window over a document's sections (carrying context from the previous window so it can merge across window boundaries) and, per section, decides to keep, merge into the previous section, split, remove, or replace it. Bibliographies are converted to BibTeX.

Output: `structured_output_final.json`.

### 5. Image processing (`imageprocessing`)

Tables and figures detected in Stages 2–3 only have their cropped image and, where extractable, a caption pulled from the surrounding text. This stage enriches every visual element with a vision-language model — the same model as Stage 4, but served by its **own** vLLM instance (separate SLURM job, separate port) so the two stages can run concurrently.

Tables get a structured Markdown transcription of their contents; figures get a detailed textual description; missing captions are generated from the image and its surrounding context. A QA gate checks each table transcription for content coverage (against the PyMuPDF source text) and repeated-row duplication, retrying poor transcriptions with feedback.

Output: `structured_output_images.json`.

### 6. Chunking, embedding & database population (`chunkingandembedding`)

1. **Merge** — Stage-4 sections and Stage-5 enrichments are combined by ID into `output.json`.
2. **Database population** — sections, tables, and images are written to SQLite with page-level provenance: each `Sections` row records which pages it spans (`SectionPages`) and an ordered list of page-tagged text/table/figure pieces (`Segments`), so a retrieved chunk can be cited down to the exact source page.
3. **Embedding** — six embedding types per document (see below) are produced by [Qwen3-VL-Embedding-8B](https://huggingface.co/Qwen/Qwen3-VL-Embedding-8B), loaded in **bfloat16** and **data-parallel across every visible GPU** (one model replica per GPU). Inputs from all documents in the run are pooled and processed in full, cross-document batches so the GPUs stay saturated regardless of how many items any single document contributes. Vectors are L2-normalised and added to a single global FAISS index (`IndexIDMap` over `IndexFlatIP`). The database is the source of truth for what has already been embedded, so re-runs only embed missing items.

## Key Dependencies and Models

### Inference Runtime

| Tool | Purpose |
| --- | --- |
| [vLLM](https://github.com/vllm-project/vllm) | Local, OpenAI-compatible inference server with continuous batching and tensor parallelism; serves the LLM refinement (Stage 4) and vision-language image processing (Stage 5) models, each as its own server instance |

### Models

| Model | Provider | Parameters | Usage in Pipeline |
| --- | --- | --- | --- |
| [PP-DocLayoutV3](https://huggingface.co/PaddlePaddle/PP-DocLayoutV3_safetensors) | PaddlePaddle | — | Document layout detection (Stage 2): identifies tables, figures, titles, headers, footers, and other structural elements in PDF pages |
| Qwen3.5-122B-A10B-FP8 | Alibaba / Qwen | 122B MoE (FP8) | LLM-based section refinement (Stage 4) **and** vision-language image processing (Stage 5) — the same model serves both stages, each behind its own vLLM instance with tensor parallelism |
| [Qwen3-VL-Embedding-8B](https://huggingface.co/Qwen/Qwen3-VL-Embedding-8B) | Alibaba / Qwen | 8B | Multimodal embedding model (Stage 6): produces 4096-dimensional text and vision-language embeddings, run in bfloat16 and data-parallel across all available GPUs |

### Python Libraries

| Library | Purpose |
| --- | --- |
| [PyMuPDF (fitz)](https://pymupdf.readthedocs.io/) | PDF text extraction (rawdict mode) and page rendering to PNG |
| [Pillow](https://pillow.readthedocs.io/) | Image handling, cropping detected layout regions |
| [NumPy](https://numpy.org/) | Array operations for image crop processing and embedding vector handling |
| [Transformers](https://huggingface.co/docs/transformers/) | Loading and running PP-DocLayoutV3 (Stage 2) and Qwen3-VL-Embedding-8B (Stage 6) |
| [openai (Python client)](https://github.com/openai/openai-python) | Talks to the local vLLM OpenAI-compatible servers (Stages 4–5) |
| [pandas](https://pandas.pydata.org/) | Reading the KWW Excel manifest (Stage 1) |
| [spaCy](https://spacy.io/) | NLP processing for text analysis and entity recognition |
| [FAISS](https://github.com/facebookresearch/faiss) | Vector similarity search index (`IndexIDMap` over `IndexFlatIP`) for semantic retrieval |
| [SQLite](https://www.sqlite.org/) | Document, page-provenance, section, table, image, and embedding metadata storage |
| [qwen-vl-utils](https://github.com/QwenLM/Qwen2.5-VL) | Vision input preprocessing for the Qwen3-VL embedding model |

## Database Schema

The SQLite database (foreign keys enabled) stores document metadata, page-level provenance, and links to FAISS embedding IDs:

| Table | Content |
| --- | --- |
| OrganisationUnits | Municipal planning bodies |
| Municipalities | Municipalities linked to an organisation unit (unique `ags` / Gemeindeschlüssel) |
| Documents | PDF metadata (filename, publication date, page count) plus versioning: `municipality_ags` groups re-published plans, `is_current` marks the latest, `supersedes` chains each older version to its successor |
| Pages | One row per physical page of a document |
| Sections | Retrieval chunks: title, primary page number, full content |
| SectionPages | Which pages a section spans (many-to-many) |
| Segments | Ordered, page-tagged text/table/figure pieces inside a section — the fine-grained provenance used to cite a chunk down to the exact page |
| Tables | Extracted tables: image path, caption, Markdown transcription |
| Images | Extracted figures: image path, caption, textual description |
| Embeddings | One row per FAISS vector (`faiss_id`), typed (`embedding_type`) and linked to its owning section/table/figure (`owner_kind`, `owner_id`) |

## Versioning

Municipalities occasionally re-publish their Wärmeplan. Rather than overwriting the previous document, every version is kept: documents sharing a `municipality_ags` are grouped, the one with the newest publication date is flagged `is_current`, and each older version points at its successor via `supersedes`. This preserves the full history of a plan while retrieval can still filter to current-only documents.

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

## Infrastructure

The pipeline runs on the university's HPC cluster, scheduled via SLURM. Stages 4 and 5 each run as an independent SLURM job with its own vLLM server instance on 4× NVIDIA H100 80GB GPUs (tensor-parallel, TP=4, separate ports) and can execute concurrently — up to 8 GPUs in use at once. The embedding step (Stage 6) then runs as its own job, also on 4 GPUs, but data-parallel (one model replica per GPU) rather than tensor-parallel.

## Collaboration

Everyone is invited to develop this repository with good intentions.
