# docpipe.visuals.pipeline

`docpipe/visuals/pipeline.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

pipeline.py: Orchestrates the imageprocessing stage.

Enriches one PDF's output directory, or every PDF subdirectory under
a root directory with `--batch`, by sending each table and figure
image to a vision language model. `_build_parser` lists the CLI
flags.

Author: Felix Vossel

## Functions

### run_single

```python
def run_single(
    output_dir: Path,
    *,
    input_json: Optional[str] = None,
    dry_run: bool = False,
    force: bool = False,
    force_stale: bool = False,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
) -> Optional[dict]
```

Sends each table/figure image in one PDF's output directory to the vision
model and writes the enriched output.

Caching is item-level: tables that already have a "markdown" key and figures
that already have a "description" key are reused from a previous enriched
output unless *force* is set. *input_json* is relative to *output_dir*.

Returns:
    Enriched data dict, or None on failure.

### run_batch

```python
def run_batch(
    root_dir: Path,
    **kwargs,
) -> dict[str, bool]
```

Runs enrichment for every subdirectory under *root_dir* that contains one of
the expected structured output JSONs.

Returns:
    Dict mapping directory name → success boolean.

### run

```python
def run(
    input_path: str | Path,
    *,
    batch: bool = False,
    **kwargs,
) -> Optional[dict] | dict[str, bool]
```

Entry point: auto-selects single or batch mode.

### main

```python
def main() -> None
```

CLI entry point.

[Back to the index](../README.md)
