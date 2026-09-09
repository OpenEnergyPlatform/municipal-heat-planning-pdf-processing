# docpipe.refinement.pipeline

`docpipe/refinement/pipeline.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

pipeline.py: Orchestrates the textrefinement stage.

Refines one document directory, or every document subdirectory under
a processed root with `--batch`, sending each document's Stage 3
sections through the LLM refinement pass in refine.py.
`_build_parser` lists the CLI flags.

Before refining, `assert_serving` (docpipe.llm_preflight) checks that
the configured LLM server accepts a request of the worst-case size
this stage can send, so an undersized server is caught before the
first document rather than mid-run.

Author: Felix Vossel

## Functions

### run_single

```python
def run_single(doc_dir: Path, *, force: bool = False,
               force_stale: bool = False) -> Optional[dict]
```

Refines one document directory. With ``force`` the cached
``sections_refined.json`` is ignored and the LLM re-refines; the old file
stays until the new one atomically replaces it. ``force_stale`` does the
same, but only when the prompt has changed since the cached output was
written.
Returns the refined dict, or None on failure.

### run_batch

```python
def run_batch(root_dir: Path, *, force: bool = False,
              force_stale: bool = False) -> dict[str, bool]
```

Refines every document subdirectory under *root_dir* that has a Stage-3
structured output. Returns a dict mapping directory name → success boolean.

### run

```python
def run(
    input_path: str | Path,
    *,
    batch: bool = False,
    force: bool = False,
    force_stale: bool = False,
) -> Optional[dict] | dict[str, bool]
```

Entry point: auto-selects single or batch mode.

### main

```python
def main() -> None
```

CLI entry point.

[Back to the index](../README.md)
