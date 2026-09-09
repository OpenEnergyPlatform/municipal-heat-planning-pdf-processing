# docpipe.preprocessing.pipeline

`docpipe/preprocessing/pipeline.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

pipeline.py: Orchestrates the PDF preprocessing pipeline, Stages 1 to 3.

Stage 1 reads text blocks with PyMuPDF, as rawdict. Stage 2 runs PP-DocLayoutV3
to detect table and image crops, layout labels, and caption resolution. Stage 3
assembles sections and writes sections.json. LLM-based section refinement lives
in docpipe.refinement, not in this module.

Author: Felix Vossel

## Functions

### run_single

```python
def run_single(
    pdf_path: Path,
    output_dir: Path,
    model_tuple=None,
    force_reextract: bool = False,
    page_range: Optional[tuple[int, int]] = None,
    column_layout: str = "auto",
    transcribe_missing_text: bool = False,
    profile=None,
) -> Optional[dict]
```

Processes a single PDF through Stages 1-3; returns the Stage-3 dict, or
None on failure. Stage 1+2 results are cached in pages.json and
reused unless *force_reextract*.

*transcribe_missing_text* sends pages whose text layer is missing to the
vision model and uses the reply as their text blocks. Off by default: it is
the only part of preprocessing that needs a model server, and a run that
does not ask for it must not depend on one.

### run_folder

```python
def run_folder(
    input_dir: Path,
    output_dir: Path,
    force_reextract: bool = False,
    glob: str = "*.pdf",
    column_layout: str = "auto",
    transcribe_missing_text: bool = False,
    profile=None,
) -> dict[str, Optional[dict]]
```

Processes all PDFs in *input_dir* sequentially, keyed by path relative to
*input_dir*. The layout model is loaded once and reused; it is not
thread-safe, so processing must stay sequential. \_index.json is rewritten
after each PDF so partial results survive an interruption.

### rebuild_stage3_from_cache

```python
def rebuild_stage3_from_cache(output_dir: Path, column_layout: str = "auto") -> int
```

Re-run ONLY Stage 3 for every doc under *output_dir* that has a readable
pages cache, overwriting its sections.json. No PDF input and no
layout model. Returns the number of docs rebuilt.

### report_columns

```python
def report_columns(output_dir: Path, top: int = 20) -> dict[str, tuple[int, int]]
```

Report how many pages the column detector would read as two columns, per
doc, from the cached pages. Changes nothing — this is what a corpus is
asked before its profile switches to column_layout: auto.

### run

```python
def run(
    input_path: str | Path,
    output_dir: str | Path,
    force_reextract: bool = False,
    page_range: Optional[tuple[int, int]] = None,
    glob: str = "*.pdf",
    rebuild_stage3: bool = False,
    column_layout: str = "auto",
    transcribe_missing_text: bool = False,
    profile=None,
) -> Optional[dict] | dict[str, Optional[dict]]
```

Entry point: dispatches to run_single() or run_folder() depending on
whether *input_path* is a file or a folder. With *rebuild_stage3*, ignores
*input_path* and re-runs only Stage 3 over *output_dir*'s caches.

### main

```python
def main() -> None
```

CLI entry point.

[Back to the index](../README.md)
