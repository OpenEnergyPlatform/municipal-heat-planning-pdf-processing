# docpipe.extraction.naming

`docpipe/extraction/naming.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

naming.py: Which of a document's names mean the same thing, asked once the
document is read (owner decisions 2026-11-06).

A coordinate the spec marks `merged`, and a free-text value so marked, are
read as the document prints them: the scenario of a number is "the Zero
Carbon scenario" in one sentence and "LCEO Zero Carbon" in a table. Once a
document is folded, one request per kind of thing, the word `merged` names
("scenario"), shows the model every name read for it with the places it
was read at: its quote and 500 characters before and after it in the
passage it stands in (`CONTEXT_CHARS`), a stretch of a passage shown once
however many names stand in it. Each name stands under a number (N1, N2,
…), and the model answers with numbers, never copying a name (owner
decision 2026-11-06). It answers every name (owner decision 2026-11-06,
after a probe in which names it was to leave out to mean themselves were
put on the nearest name shown instead): with its own number, with the number
of another name of the same thing, or with several where it means several
things ("the EC LTS scenarios"). A name whose thing has no other name in
the request means itself, even where the model knows the thing by a name the
request does not show. Names of the same thing are one thing, called by the
name the others point to; a name of several things stands for each of them
(`meanings`). Each row keeps the name it was read as and gets the names of
what it means under `<coordinate>_means`, `value_means` for its own value,
and the graph writes the row to each of them.

Nothing is checked beyond the list: an answer under or with a number the
request did not show, and a name the reply left out, is asked once more with
its reason (`name_not_listed`, `key_missing`). The second reply counts only
for the names asked again, so an answer the first gave stands; a name
answered in neither means itself. The answer quotes nothing, since each name
keeps the quote it was read with (owner decision 2026-11-06). A request that
does not fit its room is asked in two halves of the names, and the things
the halves found are asked once more together, each by the places of the
name it is called by.

Author: Felix Vossel

## Classes

### Namer

```python
class Namer
```

(document_id, rows, passages) -> {kind: {name: [names it means]}},
each row marked on the way (`mark`).

*ask(payload, shape, document_id, kind)* is one request: the reply as a
dict, CUT, or None. *passages* is {(owner kind, owner id): Source} of the
document in the order of the plan.

#### Namer.\_\_init\_\_

```python
def __init__(self, spec, ask: Callable, trace: Optional[Callable] = None)
```

#### Namer.answered

```python
def answered(self, document_id: int, kind: str, order: list,
             names: dict, passages: dict) -> dict
```

{name: [names it means]} of the names *order*; a request that
does not fit asked in two halves and once more over what they
found.

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
def payload(kind: str, places: dict, at: dict, numbers: dict,
            corrections: Optional[list] = None) -> dict
```

One request: what the names name, the places, then each name under
its number (*numbers*, `numbered`) with the places it was read at (*at*);
with *corrections* the same request asked once more.

### response_format

```python
def response_format(numbers: list) -> dict
```

For every name, under its number, the numbers of the names it means:
its own, another's or several, each one of *numbers* (owner decision
2026-11-06: every name is answered).

The list of numbers is written once and referred to by every name, so the
schema grows with the names and not with their square.

### answers_of

```python
def answers_of(reply: dict, numbers: dict) -> tuple
```

({name: [names it means]}, [what was wrong]) of a naming *reply*
({number: [numbers]}): each entry under a number the request showed
whose list holds only numbers it showed, turned back into names. An
entry under any other key, or with a number it did not show, is wrong,
with its reason (`name_not_listed`), and so is a number the reply gave
no entry (`key_missing`).

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
