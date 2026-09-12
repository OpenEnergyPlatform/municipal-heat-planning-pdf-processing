# docpipe.extraction.verify

`docpipe/extraction/verify.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

verify.py: Checks a claimed tuple against the spec and the source text before
it is written to the harvest.

An extraction reply states a value and cites the passage that supports it.
Before anything is written, the claim is checked against what the model does
not control: the spec's closed vocabularies, and the source text the quote has
to sit in verbatim.

A claim that passes carries an evidence tier stating how well it is backed.
`TIER_TEXT` applies when the quote sits in the document's refined section text
and the passage was located in the source PDF; the value can then be shown
highlighted on its page, the strongest evidence available. `TIER_VISUAL`
applies when the quote sits in a table transcription, a caption, or a figure
description, or the model read it off the image itself; the evidence is then
the page and that image. A `TIER_VISUAL` claim cannot be confirmed
automatically, because the transcription is itself a model output, so checking
the claim against it would compare one model output to another; confirmation is
left to a person who looks at the picture. A claim backed by neither tier is
refused: it is recorded with a reason and never reaches the output.

Values are not only numbers. An ontology asks for categories and for plain
statements as often as for numbers, and each is evidenced the same way, by the
passage it stands in. Only the comparison between a value and its quote
differs: digits for a number, text for anything else.

Author: Felix Vossel

## Classes

### Verified

```python
@dataclass
class Verified
```

Fields:

- `tuple: dict`
- `tier: str`
- `flags: list = field(default_factory=list)`: non-fatal findings
- `rects: Optional[list] = None`: highlight boxes, tier TEXT

### Refusal

```python
@dataclass
class Refusal
```

Fields:

- `raw: dict`
- `reason: str`

## Functions

### canonical_number

```python
def canonical_number(raw) -> Optional[str]
```

One spelling for a number, whatever locale wrote it.

'1.036.767,8', '1,036,767.8' and '1036767.8' all become '1036767.8'.
Digit-exact comparison then reduces to string equality — no float
round-tripping, which matters for 9-digit kWh values.

### numbers_in

```python
def numbers_in(text: str) -> set
```

### flat

```python
def flat(text: str) -> str
```

One shape for both sides of every comparison in this file.

NFKC because a ligature and a decomposed umlaut are the same letters:
`ﬁ` is `fi` and `u` plus a combining diaeresis is `ü`, and a quote that
came out of the PDF one way and out of the model the other was read as
two different sentences. This is not a check, it is the form both sides
are brought into before the one check that exists runs.

### quote_in

```python
def quote_in(source: str, quote: str) -> bool
```

Whitespace-collapsed literal containment — corrections.py semantics.

### computed_in_output

```python
def computed_in_output(raw: dict, parameter: Parameter) -> bool
```

Did the sandbox actually print this number?

A computed value cannot stand in its quote — the document prints the
inputs, not the result. What replaces the quote as the check on the value
is the sandbox's own output: the number has to be in what the code printed.
That is machine-checked, unlike a number the model works out in its head,
which is exactly why the arithmetic goes to the sandbox at all. The quote
is still required and still checked: it proves the inputs are in the
document.

### value_in_quote

```python
def value_in_quote(raw: dict, parameter: Parameter, quote: str) -> bool
```

Is the claimed value actually in the passage it cites?

### verify_tuple

```python
def verify_tuple(raw: dict, parameter: Parameter, source_text: str, *,
                 owner_kind: str = "section",
                 locate: Optional[Callable[[str], Optional[list]]] = None,
                 repair_text: Optional[str] = None)
```

One claimed tuple against everything the model does not control.

Returns Verified or Refusal. *owner_kind* decides the tier: prose gets
TIER_TEXT, a table or figure gets TIER_VISUAL. *locate* is a lazy lookup
that maps the quote to highlight rectangles in the source PDF — lazy
because opening the PDF is the expensive step and a claim refused earlier
never needs it.

*repair_text* is what a missing quote is rebuilt from, when the heading
prefixed into *source_text* is not part of it. The repair rests on the
value occurring exactly once, and 1.9% of this corpus's table numbers
also stand in their own caption.

[Back to the index](../README.md)
