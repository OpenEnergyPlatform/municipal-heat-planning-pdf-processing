# docpipe.profile

`docpipe/profile.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

profile.py: A profile is everything a project contributes to the generic
pipeline: where its documents come from, what extra tables it needs, which
prompts it overrides and which filters its app offers.

The core never imports a profile; it receives one.

Author: Felix Vossel

## Classes

### Facet

```python
@dataclass(frozen=True)
class Facet
```

One filter the inference app offers over the profile's metadata.

Fields:

- `field: str`
- `label: str`
- `widget: str = "multiselect"`

### Profile

```python
@dataclass(frozen=True)
class Profile
```

Fields:

- `name: str`
- `source_language: str = "de"`: language of the documents
- `answer_language: str = "de"`: language the app answers in
- `column_layout: str = "auto"`: auto | single | double
- `data_root: Optional[Path] = None`
- `home: Optional[Path] = None`: where the profile's own files live; defaults to profiles/\<name>
- `facets: Sequence[Facet] = field(default_factory=tuple)`
- `title: str = ""`: what the app calls the project and one of its documents
- `document_noun: str = "Dokument"`

#### Profile.display_title

```python
@property
def display_title(self) -> str
```

#### Profile.component

```python
def component(self, module: str, attr: str)
```

`profiles/<name>/<module>.py: <attr>`, or None if not provided.

A module the profile does not have is an absence; a module it has that
fails to import is an error. Swallowing the second would silently
degrade to the generic behaviour over a typo.

#### Profile.require

```python
def require(self, module: str, attr: str)
```

`component`, for the parts the pipeline cannot run without.

#### Profile.package_dir

```python
@property
def package_dir(self) -> Path
```

#### Profile.prompts_dir

```python
@property
def prompts_dir(self) -> Path
```

#### Profile.schema_sql

```python
@property
def schema_sql(self) -> Optional[Path]
```

#### Profile.root

```python
@property
def root(self) -> Path
```

#### Profile.pdf_dir

```python
@property
def pdf_dir(self) -> Path
```

#### Profile.processed_dir

```python
@property
def processed_dir(self) -> Path
```

#### Profile.db_path

```python
@property
def db_path(self) -> Path
```

#### Profile.index_path

```python
@property
def index_path(self) -> Path
```

## Functions

### load_profile

```python
def load_profile(name: Optional[str] = None) -> Profile
```

Import profiles.\<name>.profile and return its PROFILE object.

### active_profile

```python
def active_profile() -> Optional[Profile]
```

The ambient profile, or None. Used where no profile is passed in.

### profile_value

```python
def profile_value(module: str, attr: str)
```

The ambient profile's *attr*, resolved once per profile.

For the facts about a corpus the core must not invent: which words open a
caption, how long a caption gets, how many sections fit one request. A
core constant looks harmless until a second corpus arrives and the value
is quietly wrong for it — with no error, only worse output.

### add_profile_argument

```python
def add_profile_argument(parser) -> None
```

### resolve_profile

```python
def resolve_profile(args=None, name: Optional[str] = None) -> Optional[Profile]
```

The profile for this run, or None.

A stage binds its prompts when it is imported, which happens before the
command line is parsed. So a profile that overrides prompts has to be in the
environment from the start; --profile alone would silently use the core
prompts. That case is refused rather than run.

[Back to the index](../README.md)
