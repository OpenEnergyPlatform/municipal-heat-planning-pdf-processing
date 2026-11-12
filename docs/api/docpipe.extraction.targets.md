# docpipe.extraction.targets

`docpipe/extraction/targets.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

targets.py: What becomes of the answer of "Ask the model" (owner decision
2026-11-12 evening, plan "modell_fragen", point 5).

A step of "Ask the model" names its target (`Target`): a variable; values of
a field, kept at once or gathered over the rounds of a field of the whole
document; a dimension of a value, at its own place or over the search hits;
a search sentence; and the questions asked inside the answer of another, a
list entry, a name of the document's list, the plan's year of a wording,
whether a place speaks about the value. A target checks an answer as the
reading always has (the line was shown, the answer stands in it, a list's
answer is one of its entries) and asks again with what did not hold; it
adds no check and no reason of refusal.

A target goes the ways its question goes: the search hits taken a few a
request, a request whose answer did not fit its room asked in halves of its
chunks, what an answer asks to see shown first in the next request, the
picture of a figure asked once a value. A profile adds its own targets
(`profiles/<name>/blocks.py: TARGETS`).

Author: Felix Vossel

## Classes

### Target

```python
@dataclass(frozen=True)
class Target
```

One target: its name and what the page calls it and says of it, the
code that asks and takes the answer, run(ask, counts) -> what the
question came to (`engine.Answer`) or None; *nested* for a question the
target of another asks inside its answer, which no frame runs; the
variables it gives the request besides those of the flow (*gives*), and
the forms its answer may have (*forms*, () for any).

Fields:

- `name: str`
- `label: str`
- `says: str`
- `run: Optional[Callable] = None`
- `nested: bool = False`
- `gives: tuple = ()`
- `forms: tuple = ()`
- `profile: str = ""`
- `outputs: tuple = ("answer",)`: What it makes for the steps after it (`flow.outputs_of`).
- `apart: bool = False`: Its request is asked apart from the reading of a document, from what it gives alone: the lines of a figure before the chunks are cut, the sentence a field's chunks are ordered by.
- `facts: tuple = ()`: What a condition of its step tells of, where not what is known where the step stands: the figure, for a step asked once a figure.
- `pass_run: Optional[Callable] = None`: What it does in the flow of a follow-up pass, pass_run(run, doc, node) (`passflow.act_of`); None where no run starts it there.

## Functions

### came_to

```python
def came_to(ask, counts) -> dict
```

### to_var

```python
def to_var(ask, counts)
```

The answer kept as the step's variable, after the step's own checks:
one whose condition holds of the answer is asked again with its
sentence, as often as the step's follow-ups say (owner 2026-11-12:
"eine extra Prüfung ... auf einfachem Niveau"). Where the step lets
the model ask to see more, it is asked again with what it asked to see
(`fetched_again`).

### fetched_again

```python
def fetched_again(ask, req, shape: dict, example, reply, counts)
```

A reply asked again with the chunks it asked to see, each under a
letter of its own, as often as the rule `fetch_rounds` says (owner
decision 2026-11-12: where the document points to a missing detail,
the model may fetch that place itself).

### chunk_notes

```python
def chunk_notes(chunk) -> dict
```

What the log notes of the chunk a request shows: its passage, its
place and, for a piece of several passages, how many it has.

### values

```python
def values(ask, counts)
```

Values of a field: each the address of its line and its words,
checked as every value is, what did not hold asked again with why.
Kept at once in the read of the passage they stand in (*keep* "now",
the values of a chunk), or gathered over the rounds of a field of the
whole document and kept when its frame is through (*keep*
"gathered").

### at_once

```python
def at_once(ask, counts)
```

The values a chunk holds (`find`). A request whose answer did not
fit its room is asked in halves of its own lines, each with the lines
every piece of its passage shows, until a single line is a hole of its
own (owner decision 2026-09-12: a request is split, never its answer
rescued); a piece of several passages is halved by its passages
first.

### gathered

```python
def gathered(ask, counts)
```

A field of the whole document asked over its search hits, a few a
request (`docfield`, owner decision 2026-11-08): what each request
finds is gathered with what the requests before it found, and kept
when the field's frame is through (`engine.Engine.field_reads`). A
request whose answer did not fit its room is asked in halves, and what
an answer asks to see comes first in the field's next request (owner
decision 2026-11-12).

### coord_notes

```python
def coord_notes(coord) -> dict
```

What the log notes of a request about a value's dimension.

### dimension

```python
def dimension(ask, counts)
```

A dimension of a value read from the line an answer names: at the
value's own place (*where* "own"), or over the search hits a few a
request (*where* "hits"). Its finds are each read onto the value's row,
one row per entry where several are named, and checked
(`pipeline.merge_field`); what does not hold is asked again with its
reason, then stays unbacked. The answer may ask for the picture of a
figure the request shows, once a value (owner decision 2026-11-12).

### at_own_place

```python
def at_own_place(ask, counts)
```

A dimension asked at its value's own place (`coord`): its line with
the head of its table or the sentences beside it, the headings up to
it, the title page and the plan's settings; the answer an address and
words, or 0. Not answered where the value has no place or no answer
came. What the answer asks to see comes first in the search after it
(owner decision 2026-11-12).

### over_hits

```python
def over_hits(ask, counts)
```

A dimension asked over the search hits (`search`): the value's place
and the next hits under letters of their own. A find from another
passage is kept only where the step after it that checks says the
place speaks about the value (`keep_find`).

### keep_find

```python
def keep_find(ask, keeper: dict, got, counts, noted: dict) -> bool
```

Does the place a find of another passage stands in speak about this
value (`check`, owner decision 2026-11-07)? Asked as the step that
checks says, in its own values (`about_no_reply`).

### sentence

```python
def sentence(ask, counts)
```

The sentence the search of a dimension goes with (`phrase`, owner
decision 2026-11-09): as the document would print the answer for this
value (HyDE), written once per document, field, dimension and wording
of the value; a question where the rule `question_as_sentence` takes
none is the field's own sentence instead, and a question taken is
counted. The rule `search_with` may take the dimension's question or
name instead, with no request.

### search_sentence

```python
def search_sentence(ask, coord, counts, before: Optional[list]) -> str
```

### figure_lines

```python
def figure_lines(ask, counts)
```

The lines of the figure in the variable "figure": its caption
(title, axes, legend), then its numbers, written out once from its
picture (owner decisions 2026-11-08, e, and 2026-11-09) and kept for
the run (`addressed.Transcripts`, `engine.Engine.plan`): the reply, or
None where its picture cannot be sent, for a figure is written out
from its picture or not at all.

### chunk_order

```python
def chunk_order(ask, counts)
```

The order in which each field read chunk by chunk goes through the
chunks: ranked by a sentence the model writes for the field as this
document would print a value of it (owner decisions 2026-11-05 and
2026-11-09), made once a field and kept with the harvest
(`addressed.Orders`); its request (`runner.document_anchor`) is built
from this step's inputs.

### review_marks

```python
def review_marks(run, doc, node) -> None
```

Each row of the trust levels in the rule read a second time
(`passboxes.box_review`), its request built from the step's inputs
(`runner.make_review_asker`).

### register

```python
def register(target: Target) -> None
```

A target of a profile (`profiles/<name>/blocks.py: TARGETS`).

### targets_catalogue

```python
def targets_catalogue() -> dict
```

[Back to the index](../README.md)
