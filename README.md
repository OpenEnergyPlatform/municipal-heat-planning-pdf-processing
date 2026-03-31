<a href="https://openenergy-platform.org/"><img align="right" width="200" height="200" src="https://avatars2.githubusercontent.com/u/37101913?s=400&u=9b593cfdb6048a05ea6e72d333169a65e7c922be&v=4" alt="OpenEnergyPlatform"></a>

# Open Energy Family – municipal-heat-planning-pdf-processing

Tools and scripts developed to support the [MHPO development](https://github.com/OpenEnergyPlatform/municipal-heat-planning-ontology) by automating data extraction and processing of municipal heat planning documents are stored here.

## Key Dependencies and Models

### Inference Runtime

| Tool | Purpose |
| --- | --- |
| [Ollama](https://ollama.com/) | Local model serving and inference runtime for all LLM and vision-language model interactions |

### Models

| Model | Provider | Parameters | Usage in Pipeline |
| --- | --- | --- | --- |
| [PP-DocLayoutV3](https://huggingface.co/PaddlePaddle/PP-DocLayoutV3_safetensors) | PaddlePaddle | — | Document layout detection (Stage 2): identifies tables, figures, titles, headers, footers, and other structural elements in PDF pages |
| [gpt-oss:120b](https://ollama.com/library/gpt-oss) | OpenAI (open-weight) | 120B | LLM-based section refinement (Stage 4): cleans extraction artefacts, normalizes titles and captions, removes directory pages, converts bibliographies to BibTeX |
| [Qwen3-VL](https://github.com/QwenLM/Qwen3-VL) | Alibaba / Qwen | 32B (Q8) | Vision-language model for image processing: converts table images to structured Markdown, generates detailed textual descriptions of figures, and produces captions where missing |

### Python Libraries

| Library | Purpose |
| --- | --- |
| [PyMuPDF (fitz)](https://pymupdf.readthedocs.io/) | PDF text extraction (rawdict mode) and page rendering to PNG |
| [Pillow](https://pillow.readthedocs.io/) | Image handling, cropping detected layout regions |
| [NumPy](https://numpy.org/) | Array operations for image crop processing |
| [Transformers](https://huggingface.co/docs/transformers/) | Loading and running the PP-DocLayoutV3 layout detection model |
| [ollama (Python)](https://github.com/ollama/ollama-python) | Python client for Ollama API (chat, model management) |
| [httpx](https://www.python-httpx.org/) | HTTP client with timeout control, used internally by the Ollama Python library |
| [spaCy](https://spacy.io/) | NLP processing for text analysis and entity recognition |


## Collaboration

Everyone is invited to develop this repository with good intentions.

