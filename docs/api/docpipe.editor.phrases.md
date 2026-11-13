# docpipe.editor.phrases

`docpipe/editor/phrases.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

phrases.py: What the editor does with the sentences a stage says outside its
prompts (`docpipe/phrases.py`: `prompts/<module>/phrases.json`).

It shows, per module, every sentence the profile runs with: its own wording
or the one it takes from the profile it extends. The page edits the
profile's own table; a sentence it does not word itself is not in it. A
table is checked before it is written:

- a name no stage reads is refused, and a sentence a stage cannot run
  without may not go missing (`REQUIRED` of the stage);
- a sentence stays what it is, a text or a list of as many texts;
- a sentence is a template for `str.format`, and the code fills the names
  the wordings on disk use. So a changed sentence may use those names and no
  other, and where no wording of a sentence has a brace, a changed one has
  none either: whether such a sentence is run through `str.format` is not
  to be seen from here.

A sentence is seen in recorded requests where they show it: a follow-up
names why an answer did not hold in these sentences. `shown_in` finds them
and says each as the changed wording would.

Author: Felix Vossel

## Functions

### stage_of

```python
def stage_of(module: str)
```

The module that reads the sentences of *module*: its `REQUIRED`
names and its `NOTES`.

### layers

```python
def layers(profile, module: str, read: Callable) -> list
```

[(profile, its path, its table, its bytes)] along the line of
profiles, nearest first, for those that have a file (*read(path)*).

### detail

```python
def detail(profile, module: str, read: Callable) -> dict
```

What the page shows of the sentences of one module.

### judge

```python
def judge(profile, module: str, table, read: Callable) -> dict
```

Everything the page shows after "Check" for *table*, the profile's
own sentences of *module* as the page holds them (name -> text or list
of texts); nothing is written.

### save

```python
def save(profile, module: str, table, read: Callable,
         confirm: bool = False) -> tuple
```

(the report of `judge`, the bytes to write or None, where). Nothing
to write where the check fails (`reason: "check"`), nothing changed
(`"same"`), or a sentence the profile worded itself is taken away and
that is not confirmed (`"confirm"`).

### shown_in

```python
def shown_in(requests: list, old: str, new: str,
             limit: int = SHOWN_LIMIT) -> dict
```

Where the recorded *requests* (`requests.requests_of`) show the
sentence worded *old*, each as it stood and as the wording *new* would
say it: `searched`, `found` and the first *limit* of them (`shown`).

[Back to the index](../README.md)
