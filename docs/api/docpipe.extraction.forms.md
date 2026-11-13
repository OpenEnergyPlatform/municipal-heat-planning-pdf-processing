# docpipe.extraction.forms

`docpipe/extraction/forms.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

forms.py: The forms an answer of "Ask the model" can have (owner decision
2026-11-12 evening, plan "modell_fragen", point 4).

Each form is a JSON schema the request sends as its grammar and an example
answer its prompt shows (`FORMS`): the values a request finds, each with
its line and words; one place or several; the entry of a list; a name of
the document's list or a new one; a search sentence; yes or no; the works
a chunk names; a work, a year of the plan's; or a schema of the step's own.
A form takes what the request showed (`shows.Request`) and what its target
says of the question: whether a dimension takes several entries, whether a
field has a list, whether the answer may ask to see more, whether a figure's
picture may be asked for.

Author: Felix Vossel

## Functions

### finds

```python
def finds(req, closed: bool = False, more: bool = False,
          at: str = "own") -> tuple
```

The values a request finds, each an address and its words, and the
number of its entry where the field has a list (*closed*); an empty list
where nothing shown holds one; and two example answers, one with a find
and the empty one.

### place

```python
def place(req, several: bool = False, more: bool = False,
          image: bool = False) -> tuple
```

One place and its words, or several, or 0 where no shown line says
it.

### entry

```python
def entry(req, several: bool = False) -> tuple
```

The number of a list's entry, 0 for none; several where several may
be meant.

### name

```python
def name(req, several: bool = False, more: bool = False) -> tuple
```

The number of an entry of the document's list of names, "new" for a
name not on it yet, 0 for none; several where the words may name
several.

### phrase

```python
def phrase(req) -> tuple
```

A sentence as the document would print what a search looks for.

### yes_no

```python
def yes_no(req) -> tuple
```

Whether a place speaks about the value: yes or no.

### works

```python
def works(req) -> tuple
```

The lines of a chunk that name other works and the line that shows
the rest are this publication's own.

### work_choice

```python
def work_choice(req) -> tuple
```

The work of a value as an entry of the document's list of works,
and the line that shows it.

### year_choice

```python
def year_choice(req) -> tuple
```

The line that names the plan's word for a state and the entry of the
plan's years it means.

### lines

```python
def lines(req) -> tuple
```

A figure written out: its caption (title, axes, legend) and its
numbers, each a line (owner decision 2026-11-09); the example begins
with the figure's title where the request shows one.

### compute

```python
def compute(req, labels: tuple = (), more=None, take=None,
            quote: bool = False) -> tuple
```

A calculation's answer: an action of the sandbox, or the number with
the numbers it came from (`replies.compute`).

### review

```python
def review(req, slots: tuple = ()) -> tuple
```

A second reading's answer: each dimension asked with its words and
its quote (`replies.review`).

### example

```python
def example(req, numeric: bool = False) -> tuple
```

The values a passage holds of a field, proposed as its example
(`compile.examples.reply_shape`).

### register

```python
def register(name_: str, label: str, says: str, how: Callable) -> None
```

A form of a profile (`profiles/<name>/blocks.py: FORMS`).

### forms_catalogue

```python
def forms_catalogue() -> dict
```

### of

```python
def of(reply, req, **options) -> tuple
```

(shape, example) of the answer form *reply* (a name of `FORMS`, or a
JSON schema of the step's own) for *req*, with the options its target
gives (several, closed, more, image).

### problem

```python
def problem(reply) -> Optional[str]
```

Why *reply* is no answer form, None where it is one.

[Back to the index](../README.md)
