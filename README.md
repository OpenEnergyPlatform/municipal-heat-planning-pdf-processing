<a href="https://openenergy-platform.org/"><img align="right" width="200" height="200" src="https://avatars2.githubusercontent.com/u/37101913?s=400&u=9b593cfdb6048a05ea6e72d333169a65e7c922be&v=4" alt="OpenEnergyPlatform"></a>

# Open Energy Family – municipal-heat-planning-pdf-processing

Tools and scripts developed to support the [MHPO development](https://github.com/OpenEnergyPlatform/municipal-heat-planning-ontology) by automating data extraction, enrichment, and semantic indexing of municipal heat planning documents (Kommunale Wärmepläne).

## Pipeline Overview

The processing pipeline transforms raw PDF documents into a searchable, semantically indexed knowledge base in six stages:

1. **File Processing** – Download PDFs, extract metadata, populate the document database
2. **Layout Detection** – Identify structural elements (tables, figures, titles, headers) using PP-DocLayoutV3
3. **Text Extraction** – Extract text, crop detected regions, and build a structured JSON representation
4. **LLM Refinement** – Clean extraction artefacts, normalize titles/captions, convert bibliographies to BibTeX
5. **Image Processing** – Enrich tables with Markdown transcriptions and figures with textual descriptions via Qwen3-VL
6. **Chunking & Embedding** – Merge all outputs, populate the database with sections/tables/images, and create text + vision-language embeddings for semantic search

## Key Dependencies and Models

### Inference Runtime

| Tool | Purpose |
| --- | --- |
| [Ollama](https://ollama.com/) | Local model serving and inference runtime for LLM and vision-language model interactions (Stages 4–5) |

### Models

| Model | Provider | Parameters | Usage in Pipeline |
| --- | --- | --- | --- |
| [PP-DocLayoutV3](https://huggingface.co/PaddlePaddle/PP-DocLayoutV3_safetensors) | PaddlePaddle | — | Document layout detection (Stage 2): identifies tables, figures, titles, headers, footers, and other structural elements in PDF pages |
| [gpt-oss:120b](https://ollama.com/library/gpt-oss) | OpenAI (open-weight) | 120B | LLM-based section refinement (Stage 4): cleans extraction artefacts, normalizes titles and captions, removes directory pages, converts bibliographies to BibTeX |
| [Qwen3-VL](https://github.com/QwenLM/Qwen3-VL) | Alibaba / Qwen | 32B (Q8) | Vision-language model for image processing (Stage 5): converts table images to structured Markdown, generates detailed textual descriptions of figures, and produces captions where missing |
| [Qwen3-VL-Embedding-8B](https://huggingface.co/Qwen/Qwen3-VL-Embedding-8B) | Alibaba / Qwen | 8B | Multimodal embedding model (Stage 6): produces 4096-dimensional text and vision-language embeddings for semantic search and retrieval |

### Python Libraries

| Library | Purpose |
| --- | --- |
| [PyMuPDF (fitz)](https://pymupdf.readthedocs.io/) | PDF text extraction (rawdict mode) and page rendering to PNG |
| [Pillow](https://pillow.readthedocs.io/) | Image handling, cropping detected layout regions |
| [NumPy](https://numpy.org/) | Array operations for image crop processing and embedding vector handling |
| [Transformers](https://huggingface.co/docs/transformers/) | Loading and running PP-DocLayoutV3 (Stage 2) and Qwen3-VL-Embedding-8B (Stage 6) |
| [ollama (Python)](https://github.com/ollama/ollama-python) | Python client for Ollama API (chat, model management) |
| [httpx](https://www.python-httpx.org/) | HTTP client with timeout control, used internally by the Ollama Python library |
| [spaCy](https://spacy.io/) | NLP processing for text analysis and entity recognition |
| [FAISS](https://github.com/facebookresearch/faiss) | Vector similarity search index (IDMap with IndexFlatIP) for semantic retrieval |
| [SQLite](https://www.sqlite.org/) | Document, section, table, and image metadata storage with embedding ID references |
| [qwen-vl-utils](https://github.com/QwenLM/Qwen2.5-VL) | Vision input preprocessing for the Qwen3-VL embedding model |

## Database Schema

The SQLite database stores document metadata and links to FAISS embedding IDs:

| Table | Content |
| --- | --- |
| Documents | PDF metadata (filename, publication date, page count, organisation unit) |
| Sections | Document sections with title, page number, and embedding IDs for section text and title |
| Tables | Extracted tables with image path, caption, Markdown transcription, and embedding IDs (text + VL) |
| Images | Extracted figures with image path, caption, description, and embedding IDs (text + VL) |
| OrganisationUnits | Municipal planning bodies |
| Municipalities | Municipalities linked to organisation units |

## Embedding Strategy

Six embedding types are produced per document, all stored in a single global FAISS index:

| Type | Content | Target |
| --- | --- | --- |
| `section_text` | Title + full section content (placeholders replaced with table/figure content) | Sections.text_embedding |
| `section_title` | Section title alone | Sections.title_embedding |
| `table_text` | Caption + Markdown transcription | Tables.text_embedding |
| `table_vl` | Table image + caption + Markdown | Tables.image_embedding |
| `figure_text` | Caption + description | Images.text_embedding |
| `figure_vl` | Figure image + caption + description | Images.image_embedding |

## Collaboration

Everyone is invited to develop this repository with good intentions.