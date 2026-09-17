# docpipe.extraction.spec

`docpipe/extraction/spec.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

spec.py: The contract between a profile's ontology knowledge and the core.

The core never reads OWL or TTL. A profile distils its ontology into this
declarative form: which parameters to extract, along which axes, with which
closed vocabularies, and one real example per parameter. Everything the
extraction stage does downstream (prompt building, verification, refusal of
out-of-vocabulary answers) leans on this file being right, so loading is
strict. `load` fails loudly here, naming the field, rather than three hours
into a batch.

The module also computes a fingerprint per question a spec asks: one sha256 per
parameter, per category answer space and per axis (`fingerprints`), plus one
for the coordinate that names which parameter a value belongs to
(`parameter_slot_fingerprint`). `runner.stale` compares a document's stamp
against these keys rather than against the whole file's hash, so an edit that
touches no question a document was asked through, such as a graph block or a
comment, costs nothing on the next run.

Author: Felix Vossel

## Classes

### SpecError

```python
class SpecError(ValueError)
```

A spec that must not be run with. Message names the offending field.

### Axis

```python
@dataclass
class Axis
```

One dimension of a value: a closed vocabulary, an int, an enum — or a
vocabulary that only exists per document (`dynamic`).

Dynamic is for a coordinate whose closed list is real but not corpus-wide:
the AR6 scenarios of ONE publication, for instance. The profile supplies
that list per document and the runner fills `vocabulary` in before the
harvest; where no profile does, the axis behaves like a text axis and the
wording is simply carried through.

Fields:

- `name: str`
- `vocabulary: Optional[dict] = None`: target URI -> corpus labels
- `definitions: dict = field(default_factory=dict)`: target URI -> what the ontology says the term means, one sentence. The field prompt has promised since the first run that the question names what each entry means, and nothing did: the model was given a class identifier and a list of German words and asked to decide by meaning.
- `type: Optional[str] = None`: "int" for years, "text" for wording
- `enum: Optional[tuple] = None`
- `required: bool = False`
- `dynamic: bool = False`
- `question: Optional[str] = None`: The one line the field request asks. It lives on the axis because the harvest asks per field: a rule buried in a prompt that covers sixteen fields at once is a rule the model can skip, and skipping is what cost the corpus run 63.5% of its years.
- `derive: Optional[dict] = None`: A coordinate the SPEC already decides, so no request asks for it: {"from": "unit", "value": "\<a key of this axis' vocabulary>"}.  Principle one, applied one step further. The structure of a tuple is deterministic, and so is a coordinate every accepted unit of the parameter fixes: measured over Kassel, all 452 aggregations the model answered were `integral`, every one of them evidenced by the unit string it had just been handed. Asking cost a fifth of the reply of every five-field request for a coordinate the spec knew. What the unit does NOT fix stays a question — the profile decides which is which.
- `kg: Optional[dict] = None`: What this coordinate becomes in the graph: {"role": "type"|"edge"| "parent"|"comment", ...}. The serializer reads the predicate from here and the JSON schema publishes it, so the two cannot drift: a predicate changed in one place used to leave the other describing a graph nobody was writing.

#### Axis.label_to_uri

```python
def label_to_uri(self) -> dict
```

Corpus label (folded) -> URI. Built once, used per tuple.

### Parameter

```python
@dataclass
class Parameter
```

Fields:

- `uri: str`
- `label: str`
- `description: str`
- `value_type: str`
- `axes: dict`: name -> Axis
- `example: dict`: {"source": str, "tuples": [...]}
- `unit_target: Optional[str] = None`: numeric parameters only
- `units_accepted: dict = field(default_factory=dict)`: unit -> factor
- `integrated: bool = True`: Whether this parameter's unit is an amount over a span or a rate. A consumption in MWh/a is integrated over a year and a plan that states one without saying over what has left something out; a power in MW is not, and has no period to leave out. The verifier flags the first and must not flag the second, or the flag fires on every row of one parameter and means nothing.
- `vocabulary: Optional[dict] = None`: category parameters: uri -> labels
- `definitions: dict = field(default_factory=dict)`
- `vocabulary_dynamic: bool = False`: A category whose closed list is real but per document, filled in by the profile before the harvest. Same rule as a dynamic axis, one level up.
- `kg: Optional[dict] = None`: What a row of this parameter becomes in the graph: which node, which class, which predicate carries the number and which the unit. Read by the serializer and published by the JSON schema, so neither can drift from the other.

#### Parameter.is_numeric

```python
@property
def is_numeric(self) -> bool
```

#### Parameter.unit_factor

```python
def unit_factor(self, unit) -> Optional[float]
```

Factor onto unit_target for one entry of units_accepted, as listed.

Exact and nothing else. Which entry a document's wording means is
read by the model with its own passage (`fields.unit_slot`); a
spelling table here would be a second reader that nothing checks.

#### Parameter.value_to_uri

```python
def value_to_uri(self) -> dict
```

Corpus label (folded) -> URI, for a category parameter.

### Spec

```python
@dataclass
class Spec
```

Fields:

- `parameters: list`
- `parameter_question: Optional[str] = None`: The one line that asks which parameter a value belongs to. The harvest reads a passage once and finds the numbers in it; WHICH quantity each number is, is a coordinate like any other and is asked for like any other, with its own closed list and its own evidence. Reading the same table once per parameter is how the plan came to be three times the document.
- `unit_question: Optional[str] = None`: The one line that asks which entry of units_accepted a number is in. A coordinate like the parameter, asked before it and with the lists of every numeric parameter, because the entry is what settles the parameter. Only a spec with a numeric parameter has a use for it.
- `by_uri: dict = field(default_factory=dict)`

## Functions

### states_a_year

```python
def states_a_year(unit) -> bool
```

Does this entry of units_accepted say the amount is per year?

Asked of the entry the model chose, which is the spec's own spelling. The
period is part of what the model reads off the passage -- "450 kWh über
das Jahr" is kWh/a, a storage capacity of 200 kWh is kWh -- so the entry
carries that reading and nothing looks at the passage a second time.

### fold_label

```python
def fold_label(raw) -> str
```

One spelling for a vocabulary label, so a list need not list them all.

NFKC and casefold, nothing else. It exists for one measured reason: a
plan prints "CO₂-Emissionen" with U+2082 and every spec, schema and
ontology writes "CO2-Emissionen" with the digit. Casefold alone leaves
those two strings different, so 132 of Kassel's 204 emission readings
were recorded as the model's own judgement call over one character, and
a reading that answers with the document's spelling resolves to no class
at all.

Word order, hyphens and plurals stay distinct. Those are real differences
between two labels, and folding them would map "CO2-Emissionen je Kopf"
onto "CO2-Emissionen".

### load

```python
def load(source: Union[Path, str, dict]) -> Spec
```

Parse and validate a spec from a JSON file or an already-parsed dict.

### axis_fingerprint

```python
def axis_fingerprint(axis: "Axis") -> str
```

What this coordinate asks and what it may answer.

Everything the model sees for this axis, and nothing else: a changed
comment, a reordered vocabulary or a new parameter elsewhere in the spec
must not make a document stale for this axis. Options are sorted for the
same reason -- the list is a set, and the order it happens to be written
in is not part of the question.

### parameter_fingerprint

```python
def parameter_fingerprint(parameter: "Parameter") -> str
```

What this parameter asks, WITHOUT its axes and without its own list.

Without, because that is the whole point: a new energy carrier must open
the carrier coordinate of the rows that could carry it, not every value
of the parameter. The axes have fingerprints of their own, and so does
the list a category parameter answers from -- an answer space that can
be re-mapped from the wording is a different kind of change from a
rewritten question, and a stamp that cannot tell them apart cannot say
which one a run has to redo.

### value_fingerprint

```python
def value_fingerprint(parameter: "Parameter") -> str
```

The list a category parameter answers from, or "" when it has none.

Spellings AND meanings, the same three things an axis fingerprint takes:
all of them reach the model when it picks (`fields.Slot.answerable`), so
a changed definition is a changed question. Left out, a term whose
meaning was rewritten would leave every document current.

### parameter_slot_fingerprint

```python
def parameter_slot_fingerprint(spec: "Spec") -> str
```

The one coordinate that belongs to no parameter: which quantity a
number is.

It is asked like every other coordinate (`fields.parameter_slot`), with
its own question and its own closed list, and that list is the parameters
themselves. So it needs its own key.

It also moves when a parameter is REMOVED, which no per-parameter key
can: every key here is written from what the spec still has. That is not
the general answer to a removal, though, and reading it as one is how a
dropped AXIS came to move nothing at all. `runner.stale` reports a
question key the stored stamp carries and the run no longer asks, which
covers every kind; this key earns its place for the question and for the
list the model chooses from.

The uri and the label, because both reach the model. The description does
not -- it is in `parameter/<uri>` instead, where the question that uses it
is.

### unit_slot_fingerprint

```python
def unit_slot_fingerprint(spec: "Spec") -> str
```

The unit question and the entries it is answered from, "" without any.

Its own key, like "slot/parameter": the unit is asked once, before the
parameter, against every numeric parameter's list at once, so no
per-parameter key says that this question moved. A harvest stamped before
the question existed has no such key at all, which is what makes it stale
in exactly this coordinate and in no other -- the top-up re-reads the
unit of every row and leaves the rest of the document as it was.

### fingerprints

```python
def fingerprints(spec: "Spec") -> dict
```

{key: sha} for every question of a spec: parameter, answer space, axis.

Flat, and the keys read as what they are: the stamp is compared key by
key, and "parameter/\<uri>" or "axis/\<uri>/\<name>" is what a run should be
able to say changed. One nested block would only ever report that
something inside it moved.

Together they have to cover everything a document is asked through, or
`runner.stale` -- which ignores the whole-file sha once these are present
-- would call a document current over a changed question. That is what
"slot/parameter" is doing here: without it the spec's own question and
the list it offers would be in no key at all.

### kg_name

```python
def kg_name(block: dict, prefixes: str) -> str
```

`{"prefix": "oeo", "predicate": "OEO_00000506"}` -> "oeo:OEO_00000506".

Qualified from the spec rather than from an f-string in a serializer, and
only against a prefix the profile's own Turtle header binds: the scenarios
graph writes four namespaces where kwp writes five, and the same block is
legal in one profile and unwritable in the other. `dc:abstract` in a kwp
block would look right in the diff and produce a file no reader can load.

[Back to the index](../README.md)
