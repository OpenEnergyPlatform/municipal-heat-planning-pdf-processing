# docpipe.inference.chatflow

`docpipe/inference/chatflow.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

chatflow.py: One turn of the chat as the profile's drawing of it says
(owner request 2026-11-14: "den Chat Flow so zu bearbeiten, wie auch der
Extraktionsflow, sodass man sich sehr einfach einen eigenen Chat Flow bauen
kann", and "der Chat sollte aber auch ein paar Extra blöcke bekommen wie
outputformat etc., sodass man wirklich auch neue Routen implementieren
kann").

The drawing is `chat.json` of the profile, else of the profile it extends,
else the one the package brings (`builtin/default/chat.json`): a list of
steps, each a box of the library (`LIBRARY`) or a frame. "if" takes the
first way whose condition holds, else the last; "each" runs its steps for
each entry of a list, one after the other; "round" runs its steps again, at
most N times, until a condition holds; "together" runs every way at the
same time and goes on when all are done. The run does what the drawing says
and nothing else. The drawing the package brings is the turn as the code
asked it before there was a drawing, request for request.

A turn has variables (`VARIABLES`): what the page gives it (the question,
the turns before on the same document, the documents chosen, the parts
searched, an image, the route the sidebar chose, whether the answer is to
be JSON) and what its boxes give (the search sentence, the hits, the
statements, the answer, ...). A box takes its inputs from them and puts its
outputs into them; a condition reads them (`conditions` of the flow, its
subject "the variable"), and the check of a drawing refuses a box whose
input no step before it gives. What a box does is the code it names
(`answer`, `llm_client`, `values_route`, `kg_route`, `compare`); which box
runs when, for what and how often is the drawing's.

What the turn needs from where it runs (the corpus, the harvest, the graph,
the words of the page, the spinner) comes in as `Services`; the chat page
gives its own (`docpipe.app.app`), a test or the editor's try gives made-up
ones. The turn ends at "Show the answer" (`show`): what it shows is the
message the page draws.

Author: Felix Vossel

## Classes

### ChatFlowError

```python
class ChatFlowError(ValueError)
```

A drawing the run cannot do; `problems` says every reason.

### Drawing

```python
@dataclass
class Drawing
```

Fields:

- `tree: list`
- `owner: str`: the profile whose file it is
- `path: Path`

### Services

```python
class Services
```

What a turn needs from where it runs. The chat page gives its
resources; a test or the editor's try gives made-up ones. A method a
drawing never reaches is never called.

Fields:

- `words: dict = {}`

#### Services.corpus

```python
def corpus(self, image: Optional[bytes])
```

#### Services.values_outcome

```python
def values_outcome(self, task: str, document_id, history,
                   how: str = "auto") -> Optional[dict]
```

#### Services.values_answer

```python
def values_answer(self, task: str, got: dict, document_id, history,
                  corpus=None, progress=None) -> dict
```

#### Services.values_reason

```python
def values_reason(self, reason: str) -> str
```

#### Services.kg_turn

```python
def kg_turn(self, task: str, document_id) -> dict
```

#### Services.kg_note

```python
def kg_note(self, reason: str) -> str
```

#### Services.graph

```python
def graph(self)
```

#### Services.compare

```python
def compare(self, task: str, documents: list, scopes: list,
            as_json: bool, histories: dict) -> dict
```

#### Services.reranker

```python
def reranker(self)
```

The reranker of the search (`rerank.make_reranker`), None where
none is set up.

#### Services.sandbox

```python
def sandbox(self) -> Optional[Callable]
```

Where code of the turn runs (`answer.sandbox`), None where
nowhere.

#### Services.spinner

```python
def spinner(self, label: str)
```

#### Services.in_this_run

```python
def in_this_run(self, work: Callable) -> Callable
```

#### Services.prompt

```python
def prompt(self, prompt_id: str)
```

### Stop

```python
class Stop(Exception)
```

A step the run cannot do where it stands.

### Ran

```python
@dataclass
class Ran
```

One step as a try reports it.

Fields:

- `id: str`
- `box: str`
- `gave: dict`

### Turn

```python
class Turn
```

What one turn knows while its drawing runs.

#### Turn.\_\_init\_\_

```python
def __init__(self, services: Services, start: dict, trace=None)
```

#### Turn.get

```python
def get(self, path: str)
```

The value at *path* ("hits.0.text", "documents.count").

#### Turn.put

```python
def put(self, name: str, value) -> None
```

#### Turn.facts

```python
def facts(self, item=None, item_name: str = "item") -> conditions.Facts
```

#### Turn.holds

```python
def holds(self, condition) -> bool
```

#### Turn.document_id

```python
@property
def document_id(self)
```

#### Turn.question

```python
@property
def question(self) -> str
```

#### Turn.corpus

```python
def corpus(self)
```

#### Turn.progress

```python
def progress(self, label: str)
```

#### Turn.silent

```python
@property
def silent(self)
```

## Functions

### var

```python
def var(name: str) -> Optional[Var]
```

### variables_catalogue

```python
def variables_catalogue() -> dict
```

### catalogue

```python
def catalogue() -> dict
```

The library of the chat as the page shows it: its boxes in the
form of the flow's (`blocks._box_entry`), its frames, its variables
and what a condition can be about (the variables alone).

### conditions_catalogue

```python
def conditions_catalogue() -> list
```

### path_of

```python
def path_of(profile) -> Path
```

Where *profile* writes its drawing of the chat.

### line

```python
def line(profile) -> list
```

[(profile name, path)] of the files a profile's drawing can stand
in, nearest first, the package's own last.

### parse

```python
def parse(raw, where: str = FILE) -> list
```

The drawing of the text *raw* of a chat file; ChatFlowError where it
is none.

### dump

```python
def dump(tree: list, newline: str = "\n") -> str
```

### load

```python
def load(profile=None) -> Drawing
```

The drawing a turn of *profile* runs: the nearest file of its line.

### inherited

```python
def inherited(profile) -> Optional[Drawing]
```

The drawing *profile* would run without its own file.

### kind_of

```python
def kind_of(node) -> str
```

### ways_of

```python
def ways_of(node: dict) -> list
```

The lists of steps inside a frame: one for "each" and "round", one
per way of "if" (and its else) and of "together".

### walk

```python
def walk(tree: list)
```

### routes_in

```python
def routes_in(tree: list) -> list
```

The routes a drawing branches on: every word one of its conditions
compares the variable "route" with, in the order they stand. The
sidebar of the chat offers these (and "auto").

### setting

```python
def setting(node: dict, key: str)
```

The value of a box's setting: its own, else the library's default.

### gives

```python
def gives(node: dict) -> set
```

The variables a box gives, its settings for a name included.

### takes

```python
def takes(node: dict) -> set
```

The variables a box needs a step before it to give.

### problems

```python
def problems(tree, profile=None) -> list
```

[{"id", "message"}]: every reason the drawing *tree* cannot run, at
the step it is about; with *profile*, also each prompt it names that
the profile does not have. [] where it can.

### available_by_id

```python
def available_by_id(tree) -> dict
```

{id of a step: [the variables there before it], sorted} of every
step, for the page's choice of a variable; {} for a drawing whose form
the check refuses.

### run

```python
def run(tree: list, start: dict, services: Services, trace=None) -> dict
```

The reply of one turn of the drawing *tree*: {"message": what the
page shows, "result": the turn's answer as `answer_question` gives it,
"remember": [(document id, result)] the follow-up context keeps, and
"vars": the variables the turn ended with}.

### run_steps

```python
def run_steps(steps: list, turn: Turn) -> None
```

### run_node

```python
def run_node(node: dict, turn: Turn) -> None
```

### unread_replies

```python
def unread_replies(result: dict) -> list
```

The answer requests of a turn that stayed unreadable, where the turn
made no statement at all: the model's replies could not be read, so the
sources were not looked at, which is not the same as nothing standing
in them. A turn that made statements has its answer, and says the rest
in the faults under it.

### compose

```python
def compose(turn: Turn) -> dict
```

The message of the turn as the page draws it: the comparison, the
graph's values, the harvest asked alone, or the answer of the documents
with the harvest's beside it, by what the turn found.

[Back to the index](../README.md)
