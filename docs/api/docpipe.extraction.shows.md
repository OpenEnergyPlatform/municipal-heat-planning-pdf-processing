# docpipe.extraction.shows

`docpipe/extraction/shows.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

shows.py: What a request of "Ask the model" shows (owner decision
2026-11-12 evening: every step that asks the model is "Ask the model" with a
preset; plan "modell_fragen", points 1 to 3).

A request is built from the inputs of its step, in their order: each input
is a key of the message, the variable it comes from and how it is shown
(`SHOWS`), and where it says so a condition under which it is shown at all
(`when`). A show that has nothing to show leaves its key out (`OMIT`); a
show whose key always stands in the message gives its empty value.

Lines a request shows carry an address (`units.Shown`): a chunk of the
request's own under "", the title page, the headings and the settings each
under their letter, every other chunk under a letter of its own. The order
of the inputs is the order the blocks are added in, so that the addresses
come out as they always did.

What each show shows is set by the rules it reads (`show_headings`,
`show_title_page`, `show_settled`, `show_known`, `lines_around`, ...), as
the step that asks says (`rules.in_step`).

Author: Felix Vossel

## Classes

### Request

```python
class Request
```

What one request shows: its lines by letter (`units.Shown`), the
message (`payload`), the chunk shown as its own lines, the letters of
the other chunks, every chunk it shows, the chunks it took from a
supply and what they were (*label*), whether it is the first request
over that supply, and the list a find names its entry in.

#### Request.\_\_init\_\_

```python
def __init__(self, ask)
```

#### Request.letter_blocks

```python
def letter_blocks(self, chunks: list) -> dict
```

{letter: block} of *chunks*, each under a letter of its own (the
letter of its passage where one is shown already), as a request
shows other chunks than its own.

## Functions

### around

```python
def around(passage, first: int, last: int) -> list
```

The numbers of the lines shown around a value: its row and the rows
the rule `rows_around` adds in a table, else the lines the rule
`lines_around` adds.

### take

```python
def take(req: Request, supply, size: int)
```

The chunks a request takes from the scope's *supply* (`engine`'s
`ListSupply` for a field, `SearchSupply` for a dimension), noted on the
request; None where the supply has nothing left.

### sentences_before

```python
def sentences_before(ask, coord) -> list
```

The sentences of the rounds before that a new search sentence is
written knowing: where the step says "anew", from the round the rule
`phrase_new_from_round` names.

### has_place

```python
def has_place(plan, claim: dict) -> bool
```

Does the value of *claim* stand in a passage of *plan*?

### shows_catalogue

```python
def shows_catalogue() -> dict
```

### register

```python
def register(name: str, label: str, says: str, how: Callable) -> None
```

A show of a profile (`profiles/<name>/blocks.py: SHOWS`).

### source_of

```python
def source_of(req: Request, spec: dict)
```

The value an input comes from: the variable it names, or a part of
it (`general.get`).

### apart

```python
def apart(inputs: list, values: dict) -> dict
```

The message of a request asked apart from the reading of a
document, from *values* alone (the sentence a field's chunks are
ordered by, `runner.document_anchor`): each input as its show says,
where its condition holds of them.

### build

```python
def build(req: Request, inputs: list, holds: Optional[Callable] = None
          ) -> dict
```

The message of *req*: each input under its key, in their order, as
its show says; an input whose condition does not hold (*holds(when)*)
or whose show has nothing is left out. Stops where an input of the
hits finds nothing left (`Request.used_up`): the hits are taken
first, before any input is shown.

[Back to the index](../README.md)
