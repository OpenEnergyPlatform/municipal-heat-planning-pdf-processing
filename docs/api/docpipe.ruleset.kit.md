# docpipe.ruleset.kit

`docpipe/ruleset/kit.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

kit.py: what a rule is, the tabs and kinds of a rule, and the kinds of
steps that read rules.

The modules of the ruleset make their rules with `rule` while rules.py
gathers them, so they import these from here and nothing of docpipe:
whichever of them is imported first, neither waits for the other.
rules.py names them again, as it always did.

## Classes

### Rule

```python
@dataclass(frozen=True)
class Rule
```

One rule a run follows: what the code knows of it.

Fields:

- `name: str`
- `tab: str`
- `group: str`
- `kind: str`
- `help: str`
- `least: Optional[float] = None`
- `most: Optional[float] = None`
- `choices: tuple = ()`
- `columns: tuple = ()`: a table's columns
- `of: str = "text"`: a map's values: text, texts or whole
- `empty: bool = False`: an empty text, list or map; no range
- `env: Optional[str] = None`: the setting that wins over the file
- `env_flag: tuple = ()`: (the value where that setting is off,
- `decided: str = ""`: the owner's decisions that set it
- `where: str = ""`: where the code applies it
- `steps: tuple = ()`: the kinds of steps that read it
- `machine: bool = False`: a value of the machine (a server's
- `secret: bool = False`: a key: set at the start only (.env),

## Functions

### rule

```python
def rule(name, tab, group, kind, help, **more) -> Rule
```

[Back to the index](../README.md)
