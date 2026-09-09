# docpipe.extraction.fields

`docpipe/extraction/fields.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

fields.py: Computes the deterministic skeleton of a tuple from the spec.

A tuple's shape is not something a model decides. The spec already
states which coordinates a parameter has, which of them are a choice
from a closed list, and which are a number or a wording, and that
shape is identical for every value in the corpus. So the shape is
computed here, from the spec, and the model is never asked for it. It
is asked, one field at a time, to fill the shape in.

Asking per field is the point. One request for a whole tuple lets a
model quietly drop a coordinate it is unsure of, and dropping is
free: the field stays nullable, nothing refuses it, nothing counts
it. Measured on the 204 document corpus run, the year was missing on
63.5 percent of all values, and on 13 percent of those it stood in
the very quote the model had itself cited. A request that asks for
one field and shows the choices has no such exit: it names the entry
and the passage it was read in, or it states that the passage does
not say.

Author: Felix Vossel

## Classes

### Option

```python
@dataclass(frozen=True)
class Option
```

One entry of a closed list, as the model sees it and as it comes back.

Fields:

- `label: str`: what the model answers
- `uri: str`: what the label resolves to
- `synonyms: tuple = ()`: the other spellings the spec knows
- `definition: str = ""`: what the ontology says the term means

### Slot

```python
@dataclass(frozen=True)
class Slot
```

One field of one parameter: a single question with a single answer.

Fields:

- `name: str`
- `kind: str`
- `required: bool = False`
- `question: Optional[str] = None`
- `options: tuple = ()`
- `derive: Optional[dict] = None`: {"from": "unit", "value": uri} when the spec decides this coordinate.
- `evidence: str = "any"`: "own" | "local" | "any": how far from the row its evidence may stand.

#### Slot.is_closed

```python
@property
def is_closed(self) -> bool
```

#### Slot.answerable

```python
def answerable(self) -> dict
```

The closed list as the request shows it, UNSTATED included.

A finite set of correct answers is a choice, and "the passages do not
state it" is one of the correct answers, so it belongs in the list the
model picks from, not only in the prose above it. It was in the prompt
and not in the options, which asks the model to remember a rule instead
of reading a row.

## Functions

### parameter_slot

```python
def parameter_slot(spec) -> Slot
```

Which quantity a value is: a choice from the spec's own parameters.

The plan used to be built per parameter, so a table holding a consumption
and an emission was retrieved twice, read twice and paid for twice. It
made the document's whole owner set into three documents' worth of
requests, which was 804 planned sources against 234 owners.

Asked instead of assumed, it is the same shape as every other coordinate:
a finite list, one request, one quote. And it is a real question: a
passage rarely says "this is an emission", it says "t CO2-Äq", so the
evidence is the wording that makes it one.

### asked_slots

```python
def asked_slots(parameter: Parameter) -> list
```

The coordinates a request has to ask for: every axis the spec does not
already decide.

### frame_slots

```python
def frame_slots(spec, names) -> list
```

The coordinates the profile says span the document's frame, in its order.

A frame coordinate belongs to the DOCUMENT and not to the row. A plan has
three scenario containers and a handful of reference years, and they stand
in headings, captions and column headers, while the carrier and the
sector stand in the table row itself and are different in every cell. The
first kind can be found once and then asked about; the second cannot.

WHICH ones those are is the profile's business. The core never names a
coordinate, so this takes a list of names and resolves it against the
spec, exactly like `SLICE` does for the gate.

Read off the first parameter that has all of them, because a frame is one
per document: a spec whose parameters disagreed about it would have two
frames and no way to say which one a value hangs in. A name no parameter
has yields nothing at all rather than a shorter frame: half a frame is
a pair set that is silently missing a coordinate.

### derive_parameter

```python
def derive_parameter(spec, claim: dict)
```

Which parameter this row belongs to, from its unit alone, or None.

The spec says it itself: "the unit separates the two parameters". Measured
over the kwp spec the nine energy units and the forty-two emission units
share not one spelling, and over Kassel not one of 559 accepted tuples
contradicted its unit. Asking anyway cost 322 of 1,043 field windows, 30.9
percent, and 18.0 of 187.5 field minutes per plan.

None whenever the unit does not settle it: no unit, a unit no parameter
accepts (the row is refused later, with the unit as the reason), or a unit
two parameters accept. Then the question is a real question and is asked.

### parameter_undecidable

```python
def parameter_undecidable(spec, claim: dict) -> bool
```

True when NO parameter of the spec could hold this row.

`derive_parameter` returns None for three different situations and only
one of them is a question: a unit two parameters accept. The other two,
no unit at all, and a unit no parameter accepts, are already decided
AGAINST every answer the model could give, because `verify._check_value`
refuses on the same `unit_factor` lookup that just failed.

Measured on the M3 acceptance run: 69 rows reached the parameter sweep,
45 with a unit no parameter accepts and 24 with no unit. Not one was
ambiguous, because the kwp spec's two numeric unit lists share no
spelling. They cost 178 of 853 field requests, 20.9 percent, and every
one of the five answers they produced was refused afterwards anyway.

### apply_derived

```python
def apply_derived(rows: list, slot: Slot) -> int
```

Write a derived coordinate onto every row that has none. Returns how many.

The wording it was derived from is kept, and so is the row's own passage:
a derived coordinate is not evidence-free, it is evidenced by the unit the
value request already quoted.

### value_slot

```python
def value_slot(parameter: Parameter) -> Slot
```

The row maker: the one request that decides how many values there are.

### axis_slots

```python
def axis_slots(parameter: Parameter) -> list
```

Every coordinate of this parameter, in spec order, as its own question.

A dynamic axis whose list the profile could not fill for this document has
no options left, so it degrades to a wording, the same rule verify.py
follows one step later.

### slots

```python
def slots(parameter: Parameter) -> list
```

The full skeleton: the value slot first, then every coordinate.

[Back to the index](../README.md)
