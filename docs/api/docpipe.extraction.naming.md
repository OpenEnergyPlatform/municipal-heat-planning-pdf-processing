# docpipe.extraction.naming

`docpipe/extraction/naming.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

naming.py: Which of a document's names mean the same thing, asked once the
document is read (owner decisions 2026-11-06).

A coordinate the spec marks `merged`, and a free-text value so marked, are
read as the document prints them: the scenario of a number is "the Zero
Carbon scenario" in one sentence and "LCEO Zero Carbon" in a table. Once a
document is folded, the names read for a kind of thing, the word `merged`
names ("scenario"), are put together in two steps (owner decision
2026-11-06, after a probe that asked every name against all 240 names of a
publication: answers mostly right, cost growing with the square of the
names).

First the candidates, from two sources. One request shows every name under
a number (N1, N2, …) with the quote it was read with and asks for the
groups of names that may name the same thing, generously, a name with no
partner left out (`groups_payload`); one that does not fit is asked for
each half of the names. And every name is embedded with the text around it
where it was first read, `EMBED_CONTEXT_CHARS` before and after it
(`context_of`): its `NEIGHBOURS` nearest names are its candidates too, and
so is every name that has it among its nearest (`candidates`).

Then every name is asked on its own against its candidates (owner decision
2026-11-06: "Je Name gegen seine Gruppe"): the request shows the one name
with the places it was read at, its quote and 500 characters before and
after it in the passage it stands in (`CONTEXT_CHARS`), stretches of one
passage that overlap shown once, and beside it its candidates under their
numbers with their quotes. The model answers with numbers, never copying a
name: every name of the same thing, its own included, or, where the name
stands for several things ("the EC LTS scenarios"), the names of each of
them without its own. Two names are one thing only where each gives the
other, and a thing is called by its first name; a name of several things
stands for each of them (`meanings`). A name with no candidate asks nothing
and means itself. Each row keeps the name it was read as and gets the names
of what it means under `<coordinate>_means`, `value_means` for its own
value, and the graph writes the row to each of them.

Nothing is checked beyond the list: a reply without its key, or with a
number the request did not show, is asked once more with its reason
(`key_missing`, `name_not_listed`); a name answered in neither means itself,
and a request over all names answered in neither gives no groups. The
answer quotes nothing, since each name keeps the quote it was read with
(owner decision 2026-11-06). A request about one name that does not fit its
room is asked against each half of its candidates, and what the halves name
is the name's answer.

Author: Felix Vossel

## Classes

### Namer

```python
class Namer
```

(document_id, rows, passages) -> {kind: {name: [names it means]}},
each row marked on the way (`mark`).

*ask(payload, shape, document_id, kind, example)* is the request about
one name, *ask_groups* with the same arguments the request over all
names (`groups_payload`): the reply as a dict, CUT, or None, *example*
the reply its prompt shows. *embed(texts)* is a vector per text
(`context_of`). Without *ask_groups*, or without *embed*, that source
gives no candidates. *passages* is {(owner kind, owner id): Source} of
the document in the order of the plan. The requests about the names of
one kind run in *pool* where one is given.

#### Namer.\_\_init\_\_

```python
def __init__(self, spec, ask: Callable, trace: Optional[Callable] = None,
             pool=None, ask_groups: Optional[Callable] = None,
             embed: Optional[Callable] = None)
```

#### Namer.answered

```python
def answered(self, document_id: int, kind: str, order: list,
             names: dict, passages: dict,
             noted: Optional[dict] = None) -> dict
```

{name: [names it gave]} of the names *order*: one request per name
against its candidates (`candidates`, owner decision 2026-11-06); a
name with none, or that no reply answered, is left out and means
itself (`meanings`). *noted* gets how many `groups` the request over
all names gave and how many names were `asked`.

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

### context_of

```python
def context_of(name: str, places: list, passages: dict) -> str
```

What is embedded of *name* (owner decision 2026-11-06): the name, and
the text around it where it was first read (*places*, [(owner,
quote)]), `EMBED_CONTEXT_CHARS` before and after it; around its quote
where the quote does not print the name.

### neighbours

```python
def neighbours(vectors: list, many: int) -> list
```

[[the indices of the *many* vectors nearest to each, nearest first]]
of *vectors*, by the cosine of their angle; no vector is its own.

### candidates

```python
def candidates(order: list, groups: list, near: dict) -> dict
```

{name: [the names it is asked against, in the order of *order*]}
(owner decision 2026-11-06: both sources): the other names of each
group of the request over all names it stands in (*groups*, [[names]]),
its nearest names by embedding (*near*, {name: [names]}), and every
name that has it among its nearest.

### groups_payload

```python
def groups_payload(kind: str, numbers: dict, quotes: dict,
                   corrections: Optional[dict] = None) -> dict
```

The request over all names: what they name, and every name under
its number (*numbers*, `numbered`) with the quote it was read with
(*quotes*); with *corrections* the same request asked once more.

### groups_format

```python
def groups_format(numbers: list) -> dict
```

The groups of names that may name the same thing, under `GROUPS`:
each a list of two or more of *numbers*.

### groups_example

```python
def groups_example(numbers: dict) -> dict
```

The reply the prompt shows for the request over all names: one group
of its first two names (owner decision 2026-11-06: every request's
example is its own reply). A group the model copies from it is a
candidate, which the request about each name decides.

### groups_of

```python
def groups_of(reply, numbers: dict) -> tuple
```

([[names]], None) of a reply to the request over all names whose
groups name only numbers it showed, each group of two names or more;
(None, what was wrong) of any other: a reply without `GROUPS`
(`key_missing`), or one whose groups are no lists of shown numbers
(`name_not_listed`).

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
from *answers* ({name: [names it gave]}, owner decision 2026-11-06): an
answer that holds the name itself gives the other names of its thing,
and so does an answer of one other name; two names are one thing only
where each gives the other, and a thing is called by its first name in
*order*. An answer of several names without the name itself stands for
each of their things. An answer with no name of *order* means the name
itself.

### mark

```python
def mark(rows: list, slots: dict, meant: dict) -> int
```

Each row's names under `<key>_means` (`VALUE`: `value_means`): the
names of the things it means (*meant*, {kind: {name: [names]}}). How
many names were marked.

[Back to the index](../README.md)
