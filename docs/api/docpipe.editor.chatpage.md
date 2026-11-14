# docpipe.editor.chatpage

`docpipe/editor/chatpage.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

chatpage.py: The drawing of the chat in the Flow tab (owner request
2026-11-14: "den Chat Flow so zu bearbeiten, wie auch der Extraktionsflow,
sodass man sich sehr einfach einen eigenen Chat Flow bauen kann").

The tab draws it as it draws a flow of a follow-up pass: the profile's own
`chat.json` where it has one, else the one it extends, else the one the
package brings (`inference.chatflow`), with the chat's library, the
conditions about its variables, what the check says and the variables
there before each step. A save writes the profile's own file only where
the drawing differs from what it inherits, and only where the file is as
the page loaded it.

A try runs one turn of the drawing on the page with made-up answers, and
nothing of the plan or the question is sent (`try_turn`): every request is
answered here in its own form ("nothing": each key empty; "example": the
example of its form), the search gives the passages of a document of the
corpus database (or of a plan made up from the examples of the spec) in the
document's order, no embedder, no reranker and no sandbox is asked, and the
harvest, the graph and the comparison of other plans say that they are not
there. The tokenizer that counts the batches is the chat's, loaded as the
chat loads it.
What comes back: each step with what it gave, each request with the step
that asked it, its prompt and the made-up answer, and the message the page
would show.

Author: Felix Vossel

## Exports

What `__all__` names, and where each name is defined:

- `MODES`
- `EXAMPLE_LABEL`

## Classes

### Refused

```python
class Refused(ValueError)
```

What cannot be tried, said.

### MadeUp

```python
class MadeUp
```

The model of a try: answers each request in its own form, keeps
what it was asked and by which step, and sends nothing.

#### MadeUp.\_\_init\_\_

```python
def __init__(self, mode: str)
```

#### MadeUp.create

```python
def create(self, **kw)
```

## Functions

### library

```python
def library() -> dict
```

The chat's library in the form of the flow's: its boxes, its one
loop (each entry of a list), its variables, no presets, forms or
targets.

### view

```python
def view(profile, own_raw: Optional[bytes], shown: Callable) -> dict
```

The drawing of the chat as the page draws it. *own_raw* are the
bytes of the profile's own file, None where it has none; *shown(path)*
a path as the user sees it.

### judge

```python
def judge(profile, own_raw: Optional[bytes], shown_name: str,
          tree=None) -> dict
```

What a save of the drawing *tree* would do: {"ok", "errors": [{"id",
"message"}], "file", "writes", "diff", "text", "available",
"routes"}. A drawing the run cannot do is refused with every reason,
each at its step. A profile that extends another writes the file only
where the drawing differs from what it inherits.

### save

```python
def save(profile, own_raw: Optional[bytes], base: Optional[str],
         shown_name: str, tree=None) -> tuple
```

(what the page is told, the bytes to write or None, whether the file
is to be removed): bytes come back only for a drawing the run can do,
and only where the file is as the page loaded it (*base*, the sha256 of
its bytes, None where it had none).

### nothing

```python
def nothing(schema)
```

The answer of the form *schema* that names nothing: every key of
it, each empty (an empty list or text, 0, off, the last of a choice of
words, the first of several forms).

### example_sources

```python
def example_sources(spec=None) -> list
```

The passages of a plan made up from the examples of *spec*
(`flowtry.example_sources`); without a spec, one passage that says it
is made up.

### try_turn

```python
def try_turn(profile, tree: list, sources: list, *, question: str,
             route: str = "auto", as_json: bool = False,
             scopes: Optional[list] = None, mode: str = "nothing",
             label: str = EXAMPLE_LABEL) -> dict
```

One turn of the drawing *tree* on the passages *sources*
(`flowtry.sources_of`, `flowtry.example_sources`) with made-up answers;
see the module's head. Refused where the drawing cannot run or the
question is empty.

[Back to the index](../README.md)
