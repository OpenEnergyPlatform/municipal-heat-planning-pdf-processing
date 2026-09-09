# docpipe.visuals.models

`docpipe/visuals/models.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

models.py – Data structures for the imageprocessing module.

Author: Felix Vossel

## Classes

### EnrichedTable

```python
@dataclass
class EnrichedTable
```

A table reference enriched with extracted Markdown content.

Fields:

- `id: str`
- `path: str`
- `page_number: Optional[int] = None`
- `caption: Optional[str] = None`
- `markdown: Optional[str] = None`

#### EnrichedTable.to_dict

```python
def to_dict(self) -> dict
```

#### EnrichedTable.from_dict

```python
@classmethod
def from_dict(cls, d: dict) -> EnrichedTable
```

### EnrichedFigure

```python
@dataclass
class EnrichedFigure
```

A figure reference enriched with a textual description.

Fields:

- `id: str`
- `path: str`
- `page_number: Optional[int] = None`
- `caption: Optional[str] = None`
- `description: Optional[str] = None`

#### EnrichedFigure.to_dict

```python
def to_dict(self) -> dict
```

#### EnrichedFigure.from_dict

```python
@classmethod
def from_dict(cls, d: dict) -> EnrichedFigure
```

### ProcessingStats

```python
@dataclass
class ProcessingStats
```

Tracks progress and outcomes of the enrichment run.

Fields:

- `total_tables: int = 0`
- `total_figures: int = 0`
- `processed_tables: int = 0`
- `processed_figures: int = 0`
- `failed_tables: int = 0`
- `failed_figures: int = 0`
- `skipped_missing: int = 0`
- `captions_generated: int = 0`
- `qa_failed_tables: int = 0`: extracted but flagged low-quality by the QA gate
- `rescued_tables: int = 0`: Answered on the plain-text attempt after the JSON path gave up.
- `rescued_figures: int = 0`

#### ProcessingStats.summary

```python
def summary(self) -> str
```

[Back to the index](../README.md)
