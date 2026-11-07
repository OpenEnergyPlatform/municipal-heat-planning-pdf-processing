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

### read_off

```python
def read_off(raw: dict, owner_kind: str) -> bool
```

Is this a figure's value read off its image: the switch the reading
sets where its request sent the image (`read_off`), and the sentence of
what was read (`reading`)? Then that sentence is the evidence of the
number, and neither quote check applies to it.

### decimal_mark

```python
def decimal_mark() -> str
```

How the documents of the ambient profile write the decimal: "," or
".". The profile says it (`extraction.py: DECIMAL_MARK`); one that does
not is read with the comma, as every corpus was before this was asked.

It decides only what the digits leave open. '1.036.767,8' reads the same
under both. '3,251' is 3.251 where the comma is the decimal mark and
3251 where the point is, and no rule about digits can tell which.

### canonical_number

```python
def canonical_number(raw, decimal: Optional[str] = None) -> Optional[str]
```

One spelling for a number, whatever locale wrote it.

'1.036.767,8', '1,036,767.8' and '1036767.8' all become '1036767.8'.
Digit-exact comparison then reduces to string equality — no float
round-tripping, which matters for 9-digit kWh values.

*decimal* is the mark the documents write the decimal with; without it,
the ambient profile's (`decimal_mark`).

### numbers_in

```python
def numbers_in(text: str, decimal: Optional[str] = None) -> set
```

The numbers *text* prints, each in `canonical_number`'s spelling.
*decimal* is the mark the text writes the decimal with: the documents'
by default.

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

### times_quoted

```python
def times_quoted(texts: list, quote: str) -> int
```

How often *quote* stands in the texts a request showed, each place
once where it stands for itself (owner decision 2026-11-07: a value's
quote pins it down, so it stands in what was shown exactly once).

### times_stated

```python
def times_stated(raw: dict, parameter: Parameter, quote: str) -> int
```

How often a value stands in its quote for itself: a number as a number
of its own, a wording where no letter or digit runs on from it ("OECD"
in "non-OECD" is no second one). The same split `value_in_quote` makes.

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

### printed_rounding

```python
def printed_rounding(value: float) -> float
```

Half a unit of the last digit a number is written with: 116.1 stands
for anything from 116.05 to 116.15, and 38892.0 for 38891.5 to 38892.5.

### computed_from_inputs

```python
def computed_from_inputs(raw: dict) -> bool
```

Is the number what the numbers it was worked out from make?

The output proves the code printed the number, not that the code worked
with the numbers the answer names: one summed a column of its table and
printed 1,948 t/a beside inputs of 20,345 and 1,399. What the inputs make
stands on the last run (`expected`, from the question: a share times its
whole, the sum of the parts), and the number has to be it, to the rounding
it is written with (owner decision 2026-11-03). A number the rows request
worked out names no inputs and is held to its output alone.

### wording_of

```python
def wording_of(raw: dict, parameter: Parameter)
```

The words a value's quote has to hold.

For a category the tuple carries two things: the class the model mapped
to and, in *\_raw, how the document worded it. The evidence check is
about the document, so it runs against the wording, never against the
class name the mapping produced. Any other value is its own wording: a
value_raw beside it vouches for nothing but itself (owner decision
2026-11-04).

### value_in_quote

```python
def value_in_quote(raw: dict, parameter: Parameter, quote: str) -> bool
```

Is the claimed value actually in the passage it cites?

### number_outside_quote

```python
def number_outside_quote(claim: dict) -> bool
```

A number the quote it stands under does not print. What
`value_in_quote` refuses, asked before the parameter of a row is known.

### not_in_quote

```python
def not_in_quote(raw: dict) -> str
```

Why the fold refuses a value its quote does not hold.

### verify_tuple

```python
def verify_tuple(raw: dict, parameter: Parameter, source_text: str, *,
                 owner_kind: str = "section",
                 locate: Optional[Callable[[str], Optional[list]]] = None)
```

One claimed tuple against everything the model does not control.

Returns Verified or Refusal. *owner_kind* decides the tier: prose gets
TIER_TEXT, a table or figure gets TIER_VISUAL. *locate* is a lazy lookup
that maps the quote to highlight rectangles in the source PDF — lazy
because opening the PDF is the expensive step and a claim refused earlier
never needs it.

A quote that does not stand in *source_text* is refused, and nothing
rebuilds it from the source (owner decision 2026-11-05).

### value_refused

```python
def value_refused(raw: dict, parameter: Parameter, source_text: str,
                  owner_kind: str = "section") -> Optional[str]
```

Why the fold would refuse a value read before its coordinates, or
None: what `verify_tuple` checks of the value itself (its type, its
entry of a closed list) and of its quote (long enough, standing in
*source_text*, holding the value), in its words; of a value read off a
figure of *owner_kind* (`read_off`) only the value itself. Not the unit
and not the axes, which a reading asks after the value and checks as it
reads them (`pipeline.merge_field`). A reading asks it of each value
while the model can still answer (`reading.round_failure`), and the walk
down a search's list of what it read (`surveyed.sought_walk`), so both
hold a value to the check the fold applies (owner decisions
2026-11-05).

[Back to the index](../README.md)
