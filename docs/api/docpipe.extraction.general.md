# docpipe.extraction.general

`docpipe/extraction/general.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

general.py: The general steps of a flow (owner decision 2026-11-12, plan
of the general blocks, points 2 to 7).

A flow can be built from steps that know nothing of a use case: ask the
model with a prompt of one's own (`ask`), and let it fetch what a shown
line points to (`ask` with tools), search the document's chunks
(`search`), order a list of chunks again (`rerank`), set a variable
(`set`), keep the entries of a list a condition holds for (`filter`), join
lists (`merge`), run a piece of Python (`python`), and go through any list
(`each_list`). Each takes named inputs and gives named outputs
(`variables`): a variable the page makes lives in the item it was made
for, or for the whole document where its step says so.

What a request shows is built from its inputs: each a key of the message,
the variable it comes from and how it is shown (`SHOWS`): as it is, as a
field with what it means, as numbered lines the answer can name, as the
title page or the headings. An input whose key the prompt names as
{{key}} stands in the prompt and not in the message, so that a prompt says
each thing once. The answer is read in the form of its JSON schema; an
answer that names lines and words is checked as every answer is (the line
was shown, the words stand in it), asked again with what did not hold, and
kept as values of a field of the Spec where the step says so.

Author: Felix Vossel

## Classes

### Request

```python
class Request
```

What one request shows: its lines by letter (`units.Shown`), the
document, and the reading.

#### Request.\_\_init\_\_

```python
def __init__(self, plan, reader, scope)
```

## Functions

### raw

```python
def raw(scope, name: str)
```

The object the variable *name* holds at *scope*, None where there
is none: one of the page's (`PAGE`, the item's or the document's), or
one the run keeps (`variables.VARIABLES`).

### view

```python
def view(obj)
```

*obj* as JSON: a chunk with its numbered lines, a field with what it
means, a value with its words and line, the answer of a question; a
dict, list, text or number as it is.

### get

```python
def get(scope, path: str)
```

The value at *path* ("answer.finds", "frage.jahr", "hits.0.text")
as JSON, None where it leads nowhere.

### put

```python
def put(scope, name: str, value, lasting: bool = False) -> None
```

The page's variable *name* set to *value*: for the item it was made
for, or for the whole document (*lasting*).

### shows_catalogue

```python
def shows_catalogue() -> dict
```

### payload_of

```python
def payload_of(req: Request, inputs: list) -> dict
```

The message of a request: each input under its key, shown as it
says; an input that shows nothing is left out.

### placed

```python
def placed(text: str) -> set
```

The names a prompt writes as {{key}} or {{key.field}}, its example
replies aside.

### in_prompt

```python
def in_prompt(text: str, payload: dict) -> tuple
```

(the prompt with each {{key}} and {{key.field}} of the message
written in, the message without the keys the prompt holds whole): a
prompt says each thing once (owner 2026-11-12: "die Prompts nicht
überladen"). A place whose input shows nothing is empty.

### reply_schema

```python
def reply_schema(node: dict) -> dict
```

The JSON schema the answer of an ask step has: its own, or for a
step that keeps values of a field, the form of a find (line and words,
the entry of a list).

### example_of

```python
def example_of(schema: dict)
```

An answer in the form of *schema*, for the request's prompt to show
({{example}}): each key with a value of its type, the first entry of a
list of choices, one entry of an array.

### first_key

```python
def first_key(schema: dict) -> str
```

The key an answer must hold: the first the schema requires.

### schema_problem

```python
def schema_problem(schema) -> Optional[str]
```

Why *schema* is no reply a request can ask for, None where it is
one: an object with properties.

### python_problem

```python
def python_problem(code) -> Optional[str]
```

Why *code* is no Python step, None where it is one: Python that
defines run(inputs) and returns a dict.

### run_python

```python
def run_python(code: str, inputs: dict) -> dict
```

What run(inputs) of *code* returns, a dict of the outputs. The code
runs in the run's own process, as a profile's own code does (owner
decision 2026-11-12, point 12).

### var_facts

```python
def var_facts(scope, item=None, item_name: str = "item"
              ) -> conditions.Facts
```

What a condition about variables (`conditions.VAR`) knows at
*scope*, with *item* as the variable *item_name* (`filter`).

### joined_facts

```python
def joined_facts(first: conditions.Facts, second: conditions.Facts
                 ) -> conditions.Facts
```

Facts that ask *second* about variables and *first* about all
else.

### to_list

```python
def to_list(value) -> list
```

### ask_step

```python
def ask_step(engine, node: dict, scope) -> None
```

Ask the model with the step's prompt, inputs and form of the answer
(owner decision 2026-11-12): the answer becomes the step's variable,
or the values of a field of the Spec, each with its line, checked as
every value is and asked again with what did not hold.

### retrieve_step

```python
def retrieve_step(engine, node: dict, scope) -> None
```

The chunks of the document best for a text: the best of each kind
first up to its share, then the best of the rest, ordered by the
reranker where the rule `rerank` is on (`addressed.Reader.shown_order`).
The hits become the step's variable.

### rerank_step

```python
def rerank_step(engine, node: dict, scope) -> None
```

A list of chunks ordered by how well each matches a text, best
first (`addressed.Reader.rerank_left`).

### set_step

```python
def set_step(engine, node: dict, scope) -> None
```

### filter_step

```python
def filter_step(engine, node: dict, scope) -> None
```

### merge_step

```python
def merge_step(engine, node: dict, scope) -> None
```

### python_step

```python
def python_step(engine, node: dict, scope) -> None
```

### list_items

```python
def list_items(node: dict, scope) -> list
```

[(child scope values)] of a loop over a list: each entry under the
name the loop gives it.

[Back to the index](../README.md)
