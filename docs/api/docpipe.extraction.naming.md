# docpipe.extraction.naming

`docpipe/extraction/naming.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

naming.py: Which of a document's names mean the same thing, asked once the
document is read (owner decisions 2026-11-06).

A coordinate the spec marks `merged`, and a free-text value so marked, are
read as the document prints them: the scenario of a number is "the Zero
Carbon scenario" in one sentence and "LCEO Zero Carbon" in a table. Once a
document is folded, every name read for a kind of thing, the word `merged`
names ("scenario"), is asked on its own (owner decision 2026-11-06, after
two probes in which one request over all 145 to 158 names gave every name
the same simplest answer: once the nearest other name, once itself). Each
request shows the one name with the places it was read at: its quote and
500 characters before and after it in the passage it stands in
(`CONTEXT_CHARS`), stretches of one passage that overlap shown once. Beside
it stand all the document's names, each under a number (N1, N2, …) and with
the quote it was read with, the one asked among them. The model answers
with numbers, never copying a name: the name's own number, the number of
another name of the same thing, or several where it means several things
("the EC LTS scenarios"). A name whose thing has no other name in the
request means itself, even where the model knows the thing by a name the
request does not show. Names of the same thing are one thing, called by the
name the others point to; a name of several things stands for each of them
(`meanings`). Each row keeps the name it was read as and gets the names of
what it means under `<coordinate>_means`, `value_means` for its own value,
and the graph writes the row to each of them.

Nothing is checked beyond the list: a reply without "means", or with a
number the request did not show, is asked once more with its reason
(`key_missing`, `name_not_listed`); a name answered in neither means itself.
The answer quotes nothing, since each name keeps the quote it was read with
(owner decision 2026-11-06). A request that does not fit its room is asked
against each half of the other names, and what the halves name is the
name's answer: a name that names itself beside another means the other
(`meanings`).

Author: Felix Vossel

## Classes

### Namer

```python
class Namer
```

(document_id, rows, passages) -> {kind: {name: [names it means]}},
each row marked on the way (`mark`).

*ask(payload, shape, document_id, kind, example)* is one request: the
reply as a dict, CUT, or None, *example* the reply its prompt shows
(`example_of`). *passages* is {(owner kind, owner id): Source} of the
document in the order of the plan. The requests of one kind run in
*pool* where one is given.

#### Namer.\_\_init\_\_

```python
def __init__(self, spec, ask: Callable, trace: Optional[Callable] = None,
             pool=None)
```

#### Namer.answered

```python
def answered(self, document_id: int, kind: str, order: list,
             names: dict, passages: dict) -> dict
```

{name: [names it means]} of the names *order*, one request per
name (owner decision 2026-11-06); a name no reply answered is left
out and means itself (`meanings`).

## Functions

### merged_slots

```python
def merged_slots(spec) -> dict
```

{parameter uri: {key: kind}} of what *spec* merges: `VALUE` for a
parameter's own value, the coordinate's name for an axis, each with the
kind of thing its names name.

### merges

```python
def merges(spec) -> bool
```

Does *spec* merge any names?

### read_name

```python
def read_name(row: dict, key: str) -> Optional[tuple]
```

(name, owner, quote) of what *row* read under *key*, its own value
for `VALUE`, or None where it read no name there.

### names_of

```python
def names_of(rows: list, slots: dict) -> dict
```

{kind: {name: [(owner, quote)]}} of every name *rows* read for what
is merged (`merged_slots`), in the order the rows read them.

### located

```python
def located(source, quote: str) -> tuple
```

(which, text, start, end): the text of *source* *quote* stands in and
where, *which* in the order they are tried: 0 the passage's own, 1 the
heading of its section, 2 the passage brought into one shape with the
quote (`verify.flat`) where only that shape holds it, 3 the quote alone
where none does.

### places_of

```python
def places_of(names: dict, passages: dict) -> tuple
```

({place: text}, {name: [place]}) of *names* ({name: [(owner,
quote)]}): each quote with `CONTEXT_CHARS` before and after it in the
text it stands in, stretches of one text that overlap joined into one
place, the places in the order of the plan.

### numbered

```python
def numbered(order: list) -> dict
```

{name: its number} of the names *order*: N1, N2, … in their order.

### payload

```python
def payload(kind: str, name: str, places: list, numbers: dict, quotes: dict,
            corrections: Optional[dict] = None) -> dict
```

One request: what the names name, the name asked under its number
(*numbers*, `numbered`) with the texts of the places it was read at
(*places*), and every name under its number with the quote it was read
with (*quotes*); with *corrections* the same request asked once more.

### response_format

```python
def response_format(numbers: list) -> dict
```

The numbers of the names the name asked means, under `MEANT`: its
own, another's or several, each one of *numbers*.

### example_of

```python
def example_of(numbers: dict, name: str) -> dict
```

The reply the prompt shows for the request about *name*: the name
meaning itself, in its own number (owner decision 2026-11-06: every
request's example is its own reply).

### means_of

```python
def means_of(reply, numbers: dict) -> tuple
```

([names the name asked means], None) of a naming *reply*
({"means": [numbers]}) whose list holds only numbers the request showed,
turned back into names; (None, what was wrong) of any other: a reply
without "means" (`key_missing`), or one whose list is empty or names a
number the request did not show (`name_not_listed`).

### meanings

```python
def meanings(order: list, answers: dict) -> dict
```

{name: [the names of the things it means]} of the names *order*,
from *answers* ({name: [names it means]}): a name answered with one
other name is a name of that one's thing, and a thing is called by the
name of it that answered itself, else by its first; a name answered with
several names stands for each of their things. An answer with no name of
*order* means the name itself.

### mark

```python
def mark(rows: list, slots: dict, meant: dict) -> int
```

Each row's names under `<key>_means` (`VALUE`: `value_means`): the
names of the things it means (*meant*, {kind: {name: [names]}}). How
many names were marked.

[Back to the index](../README.md)
