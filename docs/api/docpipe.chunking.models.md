# docpipe.chunking.models

`docpipe/chunking/models.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

models.py – Data structures for the chunkingandembedding module.

Author: Felix Vossel

## Classes

### MergeStats

```python
@dataclass
class MergeStats
```

Statistics for the merge step.

Fields:

- `total_sections: int = 0`
- `tables_merged: int = 0`
- `figures_merged: int = 0`
- `tables_missing: int = 0`
- `figures_missing: int = 0`

[Back to the index](../README.md)
