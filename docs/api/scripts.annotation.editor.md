# scripts.annotation.editor

`scripts/annotation/editor.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

Local web editor for correcting the layout pre-annotations.

Adapted from CSGOAimAssistant/scripts/editor.py. The pre-annotation happens at
workspace build time (sample_and_preannotate.py, on the GPU host), so this
editor never loads a model: labels/*.txt already exist, confirming a correct
page costs one keystroke (space bar).

Workspace layout: see sample_and_preannotate.py. Deleting moves a page and its
sidecars into \<root>/deleted/ instead of unlinking.

Usage:
    python -m scripts.annotation.editor --dir data/annotation/kwp250

## Classes

### BoxModel

```python
class BoxModel(BaseModel)
```

A box in normalized YOLO coordinates.

Fields:

- `cls: int`
- `cx: float`
- `cy: float`
- `w: float`
- `h: float`

### SaveRequest

```python
class SaveRequest(BaseModel)
```

Body of PUT /api/labels/{stem}.

Fields:

- `boxes: list[BoxModel]`
- `confirm: bool = False`

### Workspace

```python
@dataclass
class Workspace
```

A workspace directory with its subfolders.

Fields:

- `root: Path`
- `index: int = 0`
- `label: str = ""`

#### Workspace.images

```python
@property
def images(self) -> Path
```

#### Workspace.labels

```python
@property
def labels(self) -> Path
```

#### Workspace.preds

```python
@property
def preds(self) -> Path
```

#### Workspace.preann

```python
@property
def preann(self) -> Path
```

Frozen pre-annotation — evaluate.py scores it against labels/.

#### Workspace.meta

```python
@property
def meta(self) -> Path
```

#### Workspace.trash

```python
@property
def trash(self) -> Path
```

#### Workspace.state_file

```python
@property
def state_file(self) -> Path
```

#### Workspace.image_files

```python
def image_files(self) -> list[Path]
```

#### Workspace.label_path

```python
def label_path(self, stem: str) -> Path
```

#### Workspace.pred_path

```python
def pred_path(self, stem: str) -> Path
```

#### Workspace.delete

```python
def delete(self, image: Path) -> list[str]
```

Move an image + all sidecars into deleted/ — a misclick must be recoverable.

### State

```python
class State
```

Confirmation status, read and written thread-safely and atomically.

#### State.\_\_init\_\_

```python
def __init__(self, path: Path) -> None
```

#### State.is_confirmed

```python
def is_confirmed(self, stem: str) -> bool
```

#### State.set

```python
def set(self, stem: str, confirmed: bool) -> None
```

## Functions

### natural_key

```python
def natural_key(stem: str) -> tuple[int, str]
```

### status_for

```python
def status_for(ws: Workspace, state: State, stem: str) -> str
```

### build_app

```python
def build_app(ws: Workspace, state: State) -> Any
```

### main

```python
def main(argv: list[str] | None = None) -> int
```

[Back to the index](../README.md)
