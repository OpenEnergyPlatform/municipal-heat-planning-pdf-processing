# docpipe.extraction.thread

`docpipe/extraction/thread.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

thread.py: Each request with exactly the words of its own task (owner
decisions 2026-11-07).

A prompt file holds what every request of its kind is told and parts only
some are told, each opened by a marker line and running to the next one:

- "\<!-- with: \<key> ... -->": what a field means that only some requests
  carry, such as the headings up to a value or the plan's settings; part of
  the system prompt of a request whose message carries one of these fields
  (`Parts.system`);
- "\<!-- follow-up: \<key> ... -->": the words of a message that follows an
  answer in the compute step's conversation and carries one of these
  fields, such as what a search fetched; never part of a system prompt
  (`Parts.follow_up`).

No request is told what another one may bring (owner decision 2026-11-07:
"Jede Anfrage sollte genau die Prompt bekommen, die beschreibt, was sie tun
soll").

Author: Felix Vossel

## Classes

### Part

```python
@dataclass(frozen=True)
class Part
```

One marked part of a prompt file: its kind, the fields it is about,
and its words.

Fields:

- `kind: str`
- `keys: tuple`
- `text: str`

### Parts

```python
@dataclass(frozen=True)
class Parts
```

A prompt file cut at its markers (`cut`): what every request of its
kind is told (*common*) and its parts in the order of the file.

Fields:

- `prompt: object`
- `common: str`
- `parts: tuple`

#### Parts.of

```python
def of(self, kind: str) -> list
```

#### Parts.system

```python
def system(self, carried: Iterable = ())
```

The system prompt of a request whose message carries the fields
*carried*: what every request is told, then the part of each field
it carries, in the order of the file. A field no part names is told
nothing beyond what every request is told.

#### Parts.words

```python
def words(self, carried: Iterable) -> str
```

The words of a follow-up that carries the fields *carried*: the
follow-up part of each, in the order of the file, each part once.
LookupError where a field has none: the model would get a field
nobody told it the meaning of.

#### Parts.follow_up

```python
def follow_up(self, follow: dict, example: Optional[dict] = None) -> str
```

A follow-up message: its words (`words`), then the fields that
carry something, as JSON; a field whose value is None is told by
its words alone. *example* is the reply of the request the message
asks, written in where the words have the place for one; words with
that place and no example are an error before anything is sent.

## Functions

### shown_with

```python
def shown_with(text: str, example: Optional[dict], where: str) -> str
```

*text* with the reply it shows written in where it has the place for
one; a place without an example, or an example without a place, is an
error before anything is sent.

### cut

```python
def cut(prompt, follows: Iterable = ()) -> Parts
```

*prompt* cut at its markers. *follows* are the fields the code sends
follow-ups with, each of which needs a follow-up part. A part marked
twice or a follow-up field without its words raises LookupError, which
the run raises at its start.

[Back to the index](../README.md)
