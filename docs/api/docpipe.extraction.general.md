# docpipe.extraction.general

`docpipe/extraction/general.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

general.py: The general steps of a flow (owner decision 2026-11-12, plan
of the general blocks, points 2 to 7) and "Ask the model", which every
step that asks the model is (owner decision 2026-11-12 evening: "alles
umbauen").

A flow can be built from steps that know nothing of a use case: ask the
model (`ask`), search the document's chunks (`search`), order a list of
chunks again (`rerank`), set a variable (`set`), keep the entries of a
list a condition holds for (`filter`), join lists (`merge`), run a piece of
Python (`python`), and go through any list (`each_list`). Each takes named
inputs and gives named outputs (`variables`): a variable the page makes
lives in the item it was made for, or for the whole document where its
step says so.

A step of "Ask the model" has five parts (`parts_of`): the request it is
in the log and whose rules it reads, its prompt, its inputs, the form of
its answer and its target; a preset (`presets`) gives all five for one
question the use cases ask, and whatever the step sets of its own wins.
What a request shows is built from its inputs (`shows`): each a key of the
message, the variable it comes from and how it is shown: as it is, as a
field with what it means, as numbered lines the answer can name, as the
title page or the headings, as the next search hits. An input whose key the
prompt names as {{key}} stands in the prompt and not in the message, so
that a prompt says each thing once. The answer is read in its form
(`forms`) and its target (`targets`) does with it what the question is
for: a variable, values of a field, a dimension of a value, a search
sentence, a list entry; an answer that names lines and words is checked as
every answer is (the line was shown, the words stand in it) and asked again
with what did not hold.

Author: Felix Vossel

## Classes

### Ask

```python
class Ask
```

One question a step of "Ask the model" asks: its parts
(`parts_of`), where it stands (*scope*; with *values* the variables a
target gives the request, `PAGE`), and how it asks. Its requests are
built from its inputs (`shows.build`) and sent as the request its step
is (`Reader._ask`), under the step's prompt where it is not the prompt
of its kind (`addressed.PROMPT`).

#### Ask.\_\_init\_\_

```python
def __init__(self, engine, node: Optional[dict], scope,
             values: Optional[dict] = None, plan=None,
             document_id: Optional[int] = None)
```

#### Ask.setting

```python
def setting(self, key: str)
```

#### Ask.number

```python
def number(self, key: str) -> int
```

#### Ask.fetch

```python
@property
def fetch(self) -> bool
```

May the answer ask to see more (`fetches`)?

#### Ask.picture

```python
@property
def picture(self) -> bool
```

May the answer ask for the picture of a figure it shows?

#### Ask.holds

```python
def holds(self, condition) -> bool
```

#### Ask.with_values

```python
def with_values(self, values: dict) -> "Ask"
```

The same question with *values* as variables of its request.

#### Ask.request

```python
def request(self, values: Optional[dict] = None, **over)
```

A request built from the step's inputs, with *values* as
variables of its own and *over* as what it shows already (`batch`,
`first`: the chunks of a half of the hits).

#### Ask.chunk_input

```python
def chunk_input(self) -> Optional[dict]
```

The input that shows the request's chunks.

#### Ask.source

```python
def source(self, spec: Optional[dict])
```

The variable an input comes from.

#### Ask.field

```python
def field(self)
```

The field of the Spec the answer reads values of: the one the
target names, else the field of the step's frame.

#### Ask.standard

```python
@property
def standard(self) -> bool
```

Is the step's prompt the prompt of its kind of request?

#### Ask.prompting

```python
def prompting(self)
```

The step's prompt for the requests of its kind while it asks,
where it is not the prompt of that kind (`addressed.PROMPT`).

#### Ask.noted

```python
def noted(self, noted: dict) -> dict
```

What the log notes of a request: a step of the page's own is
named by its id.

#### Ask.ask

```python
def ask(self, req, shape: dict, example, counts, /, **noted)
```

#### Ask.follow

```python
def follow(self, req, shape: dict, example, reply, what: list,
           counts, /, **noted)
```

#### Ask.asks

```python
def asks(self) -> bool
```

Is there a prompt this question can be asked with: its own, or
the profile's for its kind (`addressed.OPTIONAL`)?

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

### preset_of

```python
def preset_of(node: Optional[dict])
```

The preset a step of "Ask the model" names, None where it names
none (`presets`).

### default_prompt

```python
def default_prompt(request: str) -> str
```

The prompt a request has where its step names none: the prompt of
its kind (`extraction/<request>`), for a step of the page's own the
general one (`extraction/ask`).

### into_of

```python
def into_of(into) -> dict
```

The target of an answer as {"to": name, ...}: a step that names a
field keeps values of it, one that names nothing a variable.

### parts_of

```python
def parts_of(node: Optional[dict]) -> dict
```

The five parts of a step of "Ask the model": its own where it sets
them, else its preset's, else the general step's.

### schema_with_more

```python
def schema_with_more(schema: dict) -> dict
```

*schema* with "more" beside its keys, where the step lets the model
ask to see more (`addressed.with_more`).

### nested

```python
def nested(reader, target: str, plan, values: dict, node=None) -> Ask
```

A question asked inside the answer of another (a list entry, a
name, the year of a wording, whether a place speaks about the value):
as the step after the asking question says that has this target, else
the first of the flow, else its preset (owner decision 2026-11-12
evening, plan "modell_fragen", point 7); built in the step that asks,
as it always was.

### ask_step

```python
def ask_step(engine, node: dict, scope) -> None
```

Ask the model as the step's parts say (owner decisions 2026-11-12):
the request built from its inputs, the answer in its form, and what
becomes of the answer as its target says (`targets.TARGETS`), with the
ways the target goes (rounds over the search hits, halves of a request
whose answer did not fit, what the answer asks to see, the picture of a
figure, follow-up questions).

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
