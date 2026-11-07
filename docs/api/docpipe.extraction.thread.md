# docpipe.extraction.thread

`docpipe/extraction/thread.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

thread.py: Each request with exactly the words of its own task, and what
asks again about an answer in the same conversation (owner decisions
2026-11-07).

A prompt file holds what every request of its kind is told and parts only
some are told, each opened by a marker line and running to the next one:

- "\<!-- group: \<name> -->": the words of one group of the spec's
  coordinates, the message that asks that group;
- "\<!-- with: \<key> ... -->": what a field means that only some requests
  carry, such as the table right before a passage; part of the system
  prompt of a conversation whose first message carries one of these fields;
- "\<!-- follow-up: \<key> ... -->": the words of a message that follows an
  answer and carries one of these fields, such as a correction or what a
  search fetched; never part of a system prompt.

What asks again about an answer goes after it in the same conversation
(`Thread`): a correction, the next value of a passage, the next group of a
value, the second reading of a value beside its passage, the next round of
a search. Its message brings only what is new, in the words of the parts
its fields need: the model sees what it answered, and no request is told
what another one may bring (owner decisions 2026-11-07: "Jede Anfrage
sollte genau die Prompt bekommen, die beschreibt, was sie tun soll", and the
model should see its last answer "anstatt das da endlos Kontext
reingeballert wird"). A call still sends the whole conversation; a server
that keeps what it has read reads its beginning once.

Author: Felix Vossel

## Classes

### Part

```python
@dataclass(frozen=True)
class Part
```

One marked part of a prompt file: its kind, the group or the fields
it is about, and its words.

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

#### Parts.groups

```python
@property
def groups(self) -> tuple
```

#### Parts.system

```python
def system(self, carried: Iterable = ())
```

The system prompt of a conversation whose first message carries
the fields *carried*: what every request is told, then the part of
each field it carries, in the order of the file. A field no part
names is told nothing beyond what every request is told.

#### Parts.group

```python
def group(self, name: str, example: Optional[dict] = None) -> str
```

The words of the message that asks the group *name*, with the
reply it asks for where they show one (*example*); "" where the
prompt has no group parts, whose every request is told the same.
LookupError where it has group parts and none for that group.

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

### Thread

```python
@dataclass
class Thread
```

One conversation with the model: the system prompt it began with,
every message sent and the answer that stands last
(`runner.ask_in_grammar` keeps it), and what its first message carried.

Fields:

- `system: Optional[str] = None`
- `messages: list = field(default_factory=list)`
- `first: dict = field(default_factory=dict)`

#### Thread.begun

```python
@property
def begun(self) -> bool
```

#### Thread.then

```python
def then(self, content) -> list
```

The conversation with *content* as the next message: a follow-up
after the answer that stands.

#### Thread.branch

```python
def branch(self) -> "Thread"
```

A conversation that goes on from here without changing this one:
a second row a reply made of one value asks on in its own.

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
def cut(prompt, groups: Optional[Iterable] = None,
        follows: Iterable = ()) -> Parts
```

*prompt* cut at its markers. With *groups*, a prompt that has group
parts has one for each of them and none for another group; *follows*
are the fields the code sends follow-ups with, each of which needs a
follow-up part. A part marked twice, a group without its part or a part
without its group, or a follow-up field without its words raises
LookupError, which the run raises at its start
(`runner.surveyed_flow`).

[Back to the index](../README.md)
