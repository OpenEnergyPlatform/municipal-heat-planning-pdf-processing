# docpipe.settings

`docpipe/settings.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

settings.py: What an installation can set, in one list, and where each value
came from.

A stage reads its settings from the environment, most of them when it is
imported. That stays the interface: a variable set there wins over
everything else. Underneath it sits the project file, `docpipe.toml`. Its
values are put into the environment, for the names not set there, before a
stage is imported. A stage reads what it always read, and a project is one
file instead of a hundred variables.

    profile = "kwp"                 # top level: the DOCPIPE_* names
    data_root = "data"              # a relative path is relative to the file
    [llm]
    base_url = "http://localhost:8000/v1"
    [extract]
    batch_sources = 2
    [env]                           # a profile's own names, verbatim
    MY_SETTING = "x"
    [prices]                        # per million tokens, in one currency
    "some-model" = { input = 2.0, output = 10.0 }

A key that names no setting is refused with the nearest ones. So is a secret:
a key or a token belongs in `.env` or the environment, not in a file that is
checked in. That holds for the [env] table too, by the name's ending.

SETTINGS is that list. A test holds it against every environment name the
code reads, so a new setting cannot be added without a line here.

Author: Felix Vossel

## Classes

### ConfigError

```python
class ConfigError(ValueError)
```

A project file that cannot be turned into settings.

### Setting

```python
@dataclass(frozen=True)
class Setting
```

Fields:

- `env: str`: the environment name: the stable interface
- `key: str`: where it lives in docpipe.toml: "llm.model"
- `kind: str`: one of KINDS
- `default: Optional[str]`: as the environment would carry it, or None
- `help: str`
- `secret: bool = False`: a key or a token: never from the project file
- `bootstrap: bool = False`: read before any file is: environment only
- `on: str = "1"`: how this flag is spelled in the environment
- `off: str = "0"`
- `sep: str = ","`: what joins this list in the environment
- `stages: tuple = ()`: the commands that read it

## Functions

### S

```python
def S(env: str, key: str, kind: str, default: Optional[str], help: str,
      **options) -> Setting
```

### find

```python
def find(start: Optional[Path] = None) -> Optional[Path]
```

The project file that applies, or None.

The one $DOCPIPE_CONFIG names; else the nearest docpipe.toml from the
working directory upwards, so a command run in a subdirectory of a
project is run in that project. An empty $DOCPIPE_CONFIG means no file.

### prices

```python
def prices() -> dict
```

What a million tokens of each model cost, as the project file says.

Empty without a project file or without its [prices] table. The currency
is whichever the file's author meant: nothing here converts one.

### read

```python
def read(path: Path) -> dict
```

{environment name: value as the environment carries it} of one file.

### apply

```python
def apply(path: Optional[Path] = None) -> Optional[Path]
```

Put the project file's values into the environment, for every name
that is not set there. Returns the file, or None when there is none.

Called once when the package is imported, and again by the command line
for a file named with --config: what an earlier call put into the
environment is taken back first, the first project's own .env included,
so the two projects do not mix.

### project_file

```python
def project_file() -> Optional[Path]
```

### project_dir

```python
def project_dir() -> Path
```

Where the project is: beside its file, else the working directory.

### origin

```python
def origin(env: str) -> str
```

Where the value of `env` in effect comes from.

### rows

```python
def rows(stage: Optional[str] = None) -> list
```

[(setting, value in effect or None, origin, what the file says or
None)], for the settings one command reads or for all of them.

[Back to the index](../README.md)
