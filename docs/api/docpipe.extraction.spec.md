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

Three kinds of text a model is shown stand in the spec beside its parameters
(owner decision 2026-11-10; they stood in each profile's Python before): what a
document settles once for all its values (`plan_fields`), the other works a
document presents and what is asked of each (`works`), and the fixed entries of
a list the profile closes per document (`beside` of such a parameter). They
are loaded as strictly as a parameter and are in no fingerprint: a reworded
one leaves a harvest current, as a reworded prompt does.

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
the countries ONE publication names, for instance. The profile supplies
that list per document and the runner fills `vocabulary` in before the
harvest; where no profile does, the axis behaves like a text axis and the
wording is simply carried through.

Fields:

- `name: str`
- `vocabulary: Optional[dict] = None`: target URI -> corpus labels
- `definitions: dict = field(default_factory=dict)`: target URI -> what the ontology says the term means, one sentence. The field prompt has promised since the first run that the question names what each entry means, and nothing did: the model was given a class identifier and a list of German words and asked to decide by meaning.
- `glosses: dict = field(default_factory=dict)`: target URI -> one line in the profile's language saying what the entry means, shown instead of its definition (owner decision 2026-11-05, ticket 26): the ontology's English sentences were a third of every list a classification request showed. Written once by the model from the definition, which stays beside it to say when the line is due again.
- `type: Optional[str] = None`: "int" for years, "text" for wording
- `enum: Optional[tuple] = None`
- `required: bool = False`
- `dynamic: bool = False`
- `merged: Optional[str] = None`: A free-text coordinate whose answer is the name the document gives a thing, the kind of thing named here ("scenario", owner decisions 2026-11-06): a value stated for several of them is one row per name, and which of the document's names of that kind mean the same thing is asked while it is read (`addressed.Names`).
- `beside: Optional[dict] = None`: What such an axis answers instead of a name, uri -> labels like a vocabulary, each an out: entry with its meaning in `definitions` (owner decision 2026-11-07): "status quo" for a value of a past or the current year, which belongs to no scenario, as KWP's closed list has "Bestand". Read with its wording like an entry of a list, and never a name.
- `question: Optional[str] = None`: The one line the field request asks. It lives on the axis because the harvest asks per field: a rule buried in a prompt that covers sixteen fields at once is a rule the model can skip, and skipping is what cost the corpus run 63.5% of its years.
- `derive: Optional[dict] = None`: A coordinate the SPEC already decides, so no request asks for it: {"from": "unit", "value": "\<a key of this axis' vocabulary>"}.  Principle one, applied one step further. The structure of a tuple is deterministic, and so is a coordinate every accepted unit of the parameter fixes: measured over Kassel, all 452 aggregations the model answered were `integral`, every one of them evidenced by the unit string it had just been handed. Asking cost a fifth of the reply of every five-field request for a coordinate the spec knew. What the unit does NOT fix stays a question — the profile decides which is which.
- `keep: Optional[str] = None`: The entry of this coordinate's list a value must have to be a value of its parameter at all (owner decisions 2026-11-07): "scenario year" for a year, "this publication" for an author. Asked before the coordinates after it; a value read with another entry is asked for its parameter once more, told it was read wrongly, is asked nothing further, and stays out of the graph, as does one whose entry stays open (`fields.kept`).
- `several: bool = False`: Whether a value the plan states for several entries of this list is one row per entry (owner decision 2026-11-07: "Fernwärme + Gas-NT" is the value once with Fernwärme and once with Gas), as a value stated for several names is (`merged`).
- `groups: dict = field(default_factory=dict)`: uri -> the group an entry belongs to ("group" of an entry object, owner decision 2026-11-08): a list longer than a request shows with what each entry means is asked group first (`flow.Numbers.list_meanings`).

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
- `unit_names_period: dict = field(default_factory=dict)`: unit -> bool
- `unit_targets: dict = field(default_factory=dict)`: unit -> target
- `vocabulary: Optional[dict] = None`: category parameters: uri -> labels
- `definitions: dict = field(default_factory=dict)`
- `glosses: dict = field(default_factory=dict)`: as on an axis
- `brief: Optional[str] = None`: What a value of this parameter is, in one paragraph (owner decision 2026-11-05, ticket 26). The requests that find values and the groups that do not classify them show this; a group whose spec entry says "definition": "full" shows `description`, and so does every request where it is None.
- `vocabulary_dynamic: bool = False`: A category whose closed list is real but per document, filled in by the profile before the harvest. Same rule as a dynamic axis, one level up.
- `merged: Optional[str] = None`: A free-text value that is the name the document gives a thing, merged with the document's other names for it as on an axis.
- `once_per_document: bool = False`: Asked once per document, with its title page and the pieces a search finds best, never in every piece (owner decision 2026-11-08): a field the document has once, its title, its authors, its organisation.
- `takes_group: bool = True`: Whether a value whose scenario is the words of a group of scenarios ("all scenarios") takes the members the document names, one row each (owner decision 2026-11-08, i): years, regions, types do, a description does not.
- `groups: dict = field(default_factory=dict)`: uri -> the group an entry of the value's list belongs to, as on an axis.
- `beside: Optional[dict] = None`: The entries a list closed per document always has beside the document's own, uri -> labels like a vocabulary, each an out: entry (spec: "beside", for a parameter with vocabulary_dynamic): "several regions" and "other region" beside the regions one publication names, so the list exists where a document names none. In no fingerprint.

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

#### Parameter.target_of

```python
def target_of(self, unit) -> Optional[str]
```

The unit one entry of units_accepted converts onto: its own
target, else unit_target; None for no entry.

#### Parameter.names_period

```python
def names_period(self, unit) -> bool
```

Does this entry of units_accepted name a period, as the spec says?

Only the entry's own statement. A parameter whose entries carry none
(a rate, or one built without `load`) has no answer to give, and
guessing one would put a claim about a passage on a row.

#### Parameter.value_to_uri

```python
def value_to_uri(self) -> dict
```

Corpus label (folded) -> URI, for a category parameter.

### Group

```python
@dataclass
class Group
```

Coordinates a plan prints together, and the step that reads them.

The ontology says what a value is; it does not say where a plan writes
it. A number and its unit stand in one cell or one sentence, a scenario
and its year in a title or a heading above a whole table. Asked one
coordinate per request, the same passage went out once for each of them:
245,762 field requests for 100 plans in corpus_m8_100. A group is asked
in one request, each coordinate still answered and quoted for itself.

Fields:

- `name: str`
- `coordinates: tuple`
- `read_in: str`
- `where: str`: Where a plan prints the group, in the words the prompts show.
- `full_definition: bool = False`: Whether its requests show a parameter's full definition rather than its `brief` (spec: "definition": "full"): the group that classifies a value needs every distinction the definition draws, the others only what a value of the parameter is (owner decision 2026-11-05, ticket 26).
- `own_passage: tuple = ()`: Coordinates only the value's own passage states, such as what the number counts: asked again with the passages around it, never searched for in the rest of the plan (spec: "own_passage", owner decision 2026-11-06).
- `own_value: tuple = ()`: Coordinates printed with the number itself, such as "ca." or "bis zu": read once with the value, its "not stated" an answer that nothing qualifies the number, never asked again (spec: "own_value", owner decision 2026-11-06).
- `pair: tuple = ()`: The plan's frame (spec: "pair"): the scenario and the year, which the plan's base and target years date a value by (`addressed.Plan`). The reading asks them per value (owner decision 2026-11-07: each value is asked its own scenario and year, none takes its passage's).

#### Group.paired

```python
@property
def paired(self) -> tuple
```

The coordinates of the frame: its pair, else all of the group's
coordinates.

#### Group.asked_near

```python
def asked_near(self, slots: list) -> list
```

The slots the second reading asks again with the passages around
a value: all but those printed with the number itself.

### Spec

```python
@dataclass
class Spec
```

Fields:

- `parameters: list`
- `parameter_question: Optional[str] = None`: The one line that asks which parameter a value belongs to. The harvest reads a passage once and finds the numbers in it; WHICH quantity each number is, is a coordinate like any other and is asked for like any other, with its own closed list and its own evidence. Reading the same table once per parameter is how the plan came to be three times the document.
- `unit_question: Optional[str] = None`: The one line that asks which entry of units_accepted a number is in. A coordinate like the parameter, asked before it and with the lists of every numeric parameter, because the entry is what settles the parameter. Only a spec with a numeric parameter has a use for it.
- `groups: dict = field(default_factory=dict)`: name -> Group; empty for a spec read the old way only.
- `by_uri: dict = field(default_factory=dict)`
- `plan_fields: dict = field(default_factory=dict)`: What a document settles once for all its values, each asked once in the form of a document's field (spec: "plan_fields", owner decision 2026-11-08): key of `PLAN_FIELDS` -> {"name", "means", "sentence"}. The settings' lines stand beside every value's coordinates, the years are the document's own base and target years. A year may say which pairs of the document's frame are that state of it (`of`, coordinate -> the key of an entry of its list: {"scenario": "status_quo"}, owner decision 2026-11-10): a pass over a stored harvest, which asks no document its years, takes them from the stored pairs by it (`pipeline.state_years`); a run that reads a document asks them and does not read it. Empty where a spec asks none. In no fingerprint.
- `works: Optional[dict] = None`: The works a document presents, compares, reviews or cites beside itself (spec: "works", owner decision 2026-11-08, h): {"name", "means", "fields": {parameter uri: the question asked at a new work's line}}. None where a spec keeps no list of works. In no fingerprint.

#### Spec.groups_read_in

```python
def groups_read_in(self, step: str) -> list
```

## Functions

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

The classes and their spellings, which is all the rows request shows the
model for this list (`runner._parameter_payload` and
`_quantities_payload`: the class name and the other spellings). The
definitions are not in it: no request of the harvest puts them in front of
the model for a category value, so counting them made a document stale
over a sentence no model had read. An axis is another case, its field
request does show them, and `axis_fingerprint` keeps them.

A stamp written while the definitions were counted holds another digest,
so a stored scenarios stamp reports its `value/<parameter>` keys stale
once. `--remap` (no model) settles them; `--force-stale` first would read
the document again for nothing. A document with a wording no list holds
stays stale in that key (`not listed` in the remap's count) and is the
one `--force-stale` is left for.

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

[Back to the index](../README.md)
