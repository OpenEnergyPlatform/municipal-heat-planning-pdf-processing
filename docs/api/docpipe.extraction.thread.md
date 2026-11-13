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

Where a rule chooses how a request asks, the words of each choice stand
side by side, and a request is told those of the choice its rule has in its
step (owner decision 2026-11-12: a second wording of a sentence, and the
rule chooses which is sent):

    <!-- way: answer_with=address -->
    ... with the address of its line ...
    <!-- way: answer_with=quote -->
    ... with the words of its line, character for character ...
    <!-- /way -->

Each marker stands on a line of its own; a group holds one way for every
choice of its rule and is closed by "\<!-- /way -->" (`chosen`).

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
nothing beyond what every request is told. Of each group of ways,
the way its rule has in the request's step (`chosen`).

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

### ways_of

```python
def ways_of(text: str, where: str = "") -> list
```

[(start, end, rule, {choice: words})] of the groups of ways in
*text*, in its order, *start* and *end* spanning a group from its first
marker to the line break of its close. LookupError where a group is not
closed, a close has no group, or a group names two rules or one choice
twice.

### chosen

```python
def chosen(text: str, where: str = "") -> str
```

*text* with each group of ways replaced by the words of the way its
rule has now, read in the step of the request that is asked
(`rules.get`). Text without ways is returned as it is.

### widest

```python
def widest(text: str, where: str = "") -> str
```

*text* with each group of ways replaced by its longest way, in
words: the most a request of it can be told, whatever its rule says.

### check_ways

```python
def check_ways(text: str, where: str = "",
               known: Optional[dict] = None) -> None
```

LookupError where a group of ways in *text* names a rule that is
none of *known* (the rules of the ambient profile where not given) or
has no choices, or does not hold exactly one way for each choice of its
rule: a request would be sent words its rule never chooses, or none.

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
twice, a follow-up field without its words, or a group of ways that is
not one way for each choice of its rule (`check_ways`) raises
LookupError, which the run raises at its start.

[Back to the index](../README.md)
