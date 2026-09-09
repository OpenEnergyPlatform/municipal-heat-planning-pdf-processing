# docpipe.chunking.merge

`docpipe/chunking/merge.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

merge.py: Merges the preprocessing and imageprocessing outputs as
chunking's first step.

Replaces each table and figure in sections_refined.json with its
enriched counterpart from visuals.json, matched by item id, and
writes the result to document.json with an atomic replace. A
directory is cached and skipped on rerun once document.json is newer
than both inputs, unless force is set.

Author: Felix Vossel

## Functions

### merge_single

```python
def merge_single(output_dir: Path, *, force: bool = False) -> Optional[dict]
```

Merge final + images JSONs for a single PDF output directory.

Sections come from sections_refined.json; each table/figure is
replaced by its enriched counterpart from visuals.json,
matched by item id. Writes output.json and returns the merged dict, or
None if the final JSON is missing. `force` re-merges past a cached
output.json.

### merge_batch

```python
def merge_batch(root_dir: Path, *, force: bool = False) -> dict[str, bool]
```

Run merge for every PDF subdirectory under root_dir.

[Back to the index](../README.md)
