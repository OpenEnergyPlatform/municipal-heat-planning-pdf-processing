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
- `hole_causes: dict = field(default_factory=dict)`: Why the items that ended without content have none, counted in items: {cause: tables and figures}. The causes are those of `reading.Hole`.

#### ProcessingStats.hole

```python
def hole(self, kind: str, cause: str) -> None
```

Count one item that ended without content, by *kind* ("table" or
"figure") and by cause. The caller holds the lock of the shared stats.

#### ProcessingStats.summary

```python
def summary(self) -> str
```

[Back to the index](../README.md)
