# docpipe.chunking.chunking

`docpipe/chunking/chunking.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

chunking.py: Builds embedding inputs from merged section data.

For each section, produces a text input and, when the section has a
title, a title input; for each table and figure, a text input and,
when its image file exists on disk, a vision-language input. Table
and figure placeholders inside a section's text are replaced by the
referenced item's caption before the section is embedded. A section
longer than the configured word budget is truncated, and the cut is
logged rather than left silent.

Author: Felix Vossel

## Classes

### EmbeddingInput

```python
@dataclass
class EmbeddingInput
```

A single item to be embedded; ``image`` is set only for VL inputs.

Fields:

- `embedding_type: str`
- `pdf_name: str`
- `section_index: int`
- `item_id: Optional[str]`
- `text: str`
- `image: Optional[str] = None`

## Functions

### build_embedding_inputs

```python
def build_embedding_inputs(
    merged_data: dict,
    pdf_name: str,
    output_dir: Path,
) -> list[EmbeddingInput]
```

Build the section/table/figure embedding inputs (text + VL) for one PDF.

`output_dir` is the base for resolving each item's image path; VL inputs are
only emitted for images that exist on disk. Returns [] if nothing qualifies.

[Back to the index](../README.md)
