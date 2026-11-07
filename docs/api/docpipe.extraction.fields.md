# docpipe.extraction.fields

`docpipe/extraction/fields.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

fields.py: Computes the deterministic skeleton of a tuple from the spec.

A tuple's shape is not something a model decides. The spec already
states which coordinates a parameter has, which of them are a choice
from a closed list, and which are a number or a wording, and that
shape is identical for every value in the corpus. So the shape is
computed here, from the spec, and the model is never asked for it. It
is asked, one field at a time, to fill the shape in.

Asking per field is the point. One request for every coordinate lets a
model quietly drop one it is unsure of, and dropping is
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
- `definition: str = ""`: What the term means, as the request shows it: the spec's gloss where it has one, else the definition (owner decision 2026-11-05, ticket 26).

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
- `merged: Optional[str] = None`: The kind of thing whose name the document gives here, such as "scenario" (`spec.Axis.merged`): a value stated for several of them is one row per name, and which of the document's names mean the same thing is asked once the document is read (`naming.py`).
- `keeps_print: bool = False`: Whether an answer may be the print itself where the list has no entry for it: the unit, which is never refused (owner decision 2026-11-07, `pipeline.printed_only`).
- `keep: Optional[str] = None`: The entry a value must have here to be a value of its parameter (`spec.Axis.keep`, owner decisions 2026-11-07, `kept`).

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

### reader_of

```python
def reader_of(row: dict, name: str, producers) -> tuple
```

(who, index, entry) for the coordinate `name` of a stored row.

No key: the harvest read it (BY_HARVEST). A key that points at an entry
of `producers`: that pass did (BY_PASS). A key that points at none:
BY_UNKNOWN, and never the harvest. `--recheck` deletes the stamps, so a
position can outlive the list it was written for; reading that as the
harvest would put a top-up's answer under a model that never saw it.

### beside_names

```python
def beside_names(slot: Slot) -> bool
```

Does a coordinate of names take entries beside them
(`spec.Axis.beside`, owner decision 2026-11-07): a free-text slot with a
list?

### wording_asked

```python
def wording_asked(slot: Slot) -> bool
```

Is the printed wording (`value_raw`) asked beside a coordinate's
answer? Only where the answer is not the print itself: an entry of a
list or a number, and a coordinate of names that takes entries beside
them, whose entry the wording backs. A free text answer is its own
wording; the request does not ask it twice, and the row keeps it as its
wording (`pipeline.merge_field`, owner decision 2026-11-06).

### value_schema

```python
def value_schema(slot: Slot, unstated: bool = True) -> dict
```

The answers a coordinate can take in a grammar: one entry of its list,
UNSTATED included; for a number an integer or UNSTATED; else a wording.
UNSTATED is an answer of every kind: a grammar that takes only an integer
for a year leaves the model no way to say the passage prints none.
Without *unstated* it is none: the combing leaves a coordinate it did not
find out of its reply, and the run, not the model, says the plan does not
state it once every passage was listed (owner decision 2026-11-06).

### value_example

```python
def value_example(slot: Slot)
```

A coordinate's answer as the example of a request shows it, read and
of the kind `value_schema` takes: an entry of its list or a wording as a
placeholder, a number as a year. Never UNSTATED: an example shows every
coordinate read (owner decision 2026-11-06), and the prompt's rule line
shows how an unstated one looks.

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

### holds

```python
def holds(parameter: Parameter, claim: dict) -> bool
```

Is the row's value one of this parameter's entries?

A category parameter's value is an answer to its closed list (owner,
2026-09-11). The value is read before the parameter, as the wording the
passage prints, so a row whose parameter is read with a value its list
does not hold has the value asked again, to that list (`value_choice`).
The lookup is the one `verify._check_value` resolves the value with.

A value left out with the wording beside it is the answer that no entry
fits, and fits every category parameter. A text or numeric parameter
holds any value here; its own checks are elsewhere.

### has_number

```python
def has_number(claim: dict) -> bool
```

Is this row's value a number, so that a unit belongs to it?

Asked only where a unit can be: of a spec with a numeric parameter. A
wording there is a text parameter's value and carries no unit, whatever
the value request wrote beside it. A spec without one has no unit
question, and what counts as a wording there is `is_wording`'s to say.

### unit_slot

```python
def unit_slot(spec, parameter: Optional[Parameter] = None) -> Optional[Slot]
```

Which entry of units_accepted a number is in: a choice, with a passage.

A coordinate like the parameter, and asked before it: the value request
writes the unit as the passage prints it, and which entry that means is a
reading, not a lookup. "450 kWh über das Jahr" is kWh/a and a storage
capacity of 200 kWh is kWh; "Gigawattstunden" is GWh; "kWh/m²a" is in no
list and the number keeps the unit as printed, unconverted. A
spelling table stood in for this reading once, and measured on 641 plans
of corpus_m5 it let 3,324 tuples carry an entry their wording
contradicts.

Every numeric parameter's list at once when no parameter is named,
because the entry chosen is what settles the parameter
(`derive_parameter`); beside each entry stands the parameter it belongs
to, which is the meaning the model decides by. One parameter's list for a
stored row that already knows its parameter (the schema, a top-up). None
for a spec without a numeric parameter.

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

### is_wording

```python
def is_wording(spec, claim: dict) -> bool
```

Is this row's value a wording, which only a parameter that is not
numeric can hold?

A string that is no number is one. In a spec without a numeric parameter
every string is: "2030" is a year there, and that a number without a
unit belongs to no parameter is a rule about parameters that have units.
Read as a number, every bare year and every dotted date of such a spec
left the harvest `out_of_slice`, unasked.

There a row whose value was left out, with the wording in `value_raw`,
is one too: that is how the value request says no entry of the list
fits, and the row is kept with its wording. A value that is no string
and has no wording beside it is not one. No parameter takes it, so
asking would pay for a refusal.

The rule stops at a spec with a numeric parameter: there a digit string
is a number, whichever text parameter might have held a year.

### derive_parameter

```python
def derive_parameter(spec, claim: dict)
```

Which parameter this row belongs to, or None when that is a question.

A wording belongs to the text parameter when the spec has exactly one.
A number is decided by its unit alone.

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

### derived_by_unit

```python
def derived_by_unit(claim: dict, parameter) -> bool
```

Does the spec decide the coordinates it derives from the unit for this
value: the unit question read an entry of the parameter's list that
converts onto the parameter's own unit? Where it read the print without
one, the model is asked them (owner decision 2026-11-07: "wo es nicht
automatisch geht, soll es das LLM versuchen"); so is a value whose entry
converts onto a unit of its own, an emission factor in g CO2/kWh being
no annual amount.

### derives

```python
def derives(slot, claim: dict, parameter) -> bool
```

Does the spec set *slot* for this value instead of asking it: the
unit decides it (`derived_by_unit`), and the coordinate the spec names in
`unless_read` was not read. "im Mittel der Jahre 2019 bis 2021" in MWh/a
is a mean and no annual sum, so where the plan names the start of a span
the aggregation is asked (owner decision 2026-11-07: "Wenn es nach OEO
ein Mittelwert ist, dann ist es ein Mittelwert").

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

### value_choice

```python
def value_choice(parameter: Parameter) -> Slot
```

The value of a category parameter, asked again as one of its entries.

The rows request reads a value before its parameter, so what it writes is
the wording the passage prints: "includes only adopted policies" where
the list holds the types of a scenario. Once the parameter is read, which
entry that wording is becomes a question of its own, with a quote like
every coordinate, and the wording stays in value_raw. Asking the
parameter again instead left the model no answer that could pass: on one
corpus run 8,810 rows were asked it in every window to the end of their
document, and 5,636,615 answers were refused.

### axis_slots

```python
def axis_slots(parameter: Parameter) -> list
```

Every coordinate of this parameter, in spec order, as its own question.

A dynamic axis whose list the profile could not fill for this document has
no options left, so it degrades to a wording, the same rule verify.py
follows one step later.

### kept

```python
def kept(slot: Slot, claim: dict) -> Optional[bool]
```

Is the value of *claim* a value of its parameter by *slot*, a
coordinate with an entry it must have (`Slot.keep`, owner decisions
2026-11-07)? True where the coordinate was read as that entry, False
where it was read as another, None where it is open or *slot* has no
such entry. The answer is the entry's label, as `pipeline.merge_field`
writes it, or its key.

### closed

```python
def closed(slots: list, claim: dict) -> bool
```

Has a coordinate of *slots* read the value of *claim* as no value of
its parameter (`kept` False), so that nothing after it is asked?

### in_parameter

```python
def in_parameter(parameter: Parameter, claim: dict) -> bool
```

Is the value of *claim* a value of *parameter* on every coordinate
with an entry it must have, each read as that entry? The graph takes
only such a value; one read with another entry, or whose entry stayed
open, stays in the harvest (owner decisions 2026-11-07).

### slots

```python
def slots(parameter: Parameter) -> list
```

The full skeleton: the value slot first, then every coordinate.

[Back to the index](../README.md)
