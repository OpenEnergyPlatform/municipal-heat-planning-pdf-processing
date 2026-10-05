# docpipe.profile

`docpipe/profile.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

profile.py: A profile is everything a project contributes to the generic
pipeline: where its documents come from, what extra tables it needs, which
prompts it overrides and which filters its app offers.

The core never imports a profile; it receives one.

A profile is a directory. It is found by its name on a search path, first
match first: the directories $DOCPIPE_PROFILE_PATH names, `profiles/` of the
project, what installed packages register under the entry-point group
`docpipe.profiles`, `profiles/` beside this package, and last the profile
this package brings itself (`builtin/default`). So a project keeps its
profile in its own repository, and `--profile` also takes the directory
itself.

A profile may extend another one (`extends="default"`). What it does not
provide itself, a module's attribute, a prompt, the schema of its tables,
is then taken from the profile it extends. Nothing is taken from a profile
that was not named: a profile without `extends` stands alone, and a part it
lacks is an absence, as before.

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
- `column_layout: str = "auto"`: auto | single | double
- `data_root: Optional[Path] = None`
- `home: Optional[Path] = None`: where the profile's own files live; defaults to where it was found
- `facets: Sequence[Facet] = field(default_factory=tuple)`
- `title: str = ""`: what the app calls the project and one of its documents
- `document_noun: str = "Dokument"`
- `extends: Optional[str] = None`: the profile whose parts stand in for the ones this one does not provide
- `documents_shareable: bool = False`: Whether the text of the documents may be passed on. A recorded run (docpipe/providers/cassette.py) holds what it read, and is refused for a profile that does not say so.

#### Profile.display_title

```python
@property
def display_title(self) -> str
```

#### Profile.lineage

```python
def lineage(self) -> list
```

This profile and the ones it extends, nearest first.

#### Profile.component

```python
def component(self, module: str, attr: str)
```

`profiles/<name>/<module>.py: <attr>`, or None if not provided.

Its own, else that of the nearest profile it extends.

#### Profile.layers

```python
def layers(self, module: str, attr: str) -> list
```

Every value along the line of profiles, nearest first: for a
table a profile lays over the one it extends, entry by entry.

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

The schema of the profile's own tables: its file, else the file
of the nearest profile it extends. A profile that adds a column
writes the whole file.

#### Profile.has_prompts

```python
def has_prompts(self) -> bool
```

Whether a stage binds prompts under this profile at import.

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

### search_path

```python
def search_path() -> list
```

The directories whose subdirectories are profiles, in order.

### profile_locations

```python
def profile_locations() -> dict
```

{name: directory} of every profile the search path holds.

### name_profile

```python
def name_profile(text: str) -> str
```

The name for what --profile was given: a name, or a profile's
directory, whose parent then leads the search path.

### data_dir

```python
def data_dir() -> Path
```

Where data lives when no profile says otherwise.

$DOCPIPE_DATA_ROOT; else `data/` beside the project file; else, for a
checkout run without one, `data/` in the checkout; else `data/` in the
working directory.

### shared_file

```python
def shared_file(name: str, without_project: Path) -> Path
```

A file no profile owns: in the project's `data/`, else where it was.

A project that has a `docpipe.toml` keeps everything beside it. Without
one the caller's own place stands, so a run that never had a project file
finds its files where it left them.

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

### program

```python
def program(module: str) -> str
```

What a stage's usage line calls it: the command it was started as.

### add_profile_argument

```python
def add_profile_argument(parser) -> None
```

### bind_command_line

```python
def bind_command_line(argv: Optional[Sequence[str]] = None) -> None
```

Put a --profile given on the command line into the environment.

For a stage's `__main__`, before it imports the stage. What a stage binds
when it is imported (how many sections fit one request, the chat's
prompts) is read from the environment, and the command line is parsed
only after the import. Read the way the stage's own parser reads it, so
an abbreviation it accepts (--prof) is one this accepts too.

### available_profiles

```python
def available_profiles() -> list
```

### resolve_profile

```python
def resolve_profile(args=None, name: Optional[str] = None) -> Optional[Profile]
```

The profile for this run, or None.

A stage binds some of what a profile says when it is imported, which
happens before the command line is parsed. `bind_command_line` puts the
flag into the environment before that. A caller that imported the stage
under one profile and names another here would run on a mix of both;
that case is refused rather than run.

### require_profile

```python
def require_profile(args=None, name: Optional[str] = None) -> Profile
```

`resolve_profile` for a stage that has nothing to run without one.

[Back to the index](../README.md)
