# docpipe.inference.kg_route

`docpipe/inference/kg_route.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

kg_route.py: Answers a question from the graph the harvest wrote,
before the documents are searched.

`--serialize` turns a plan's harvested numbers into Turtle: one value
node per coordinate tuple (the part of the plan it hangs under, the
quantity class, the carrier, the sector, the year, the aggregation),
with the trust line and the evidence the serializer wrote as comments
above each node. A question that names those coordinates has an
answer in that graph, one no retrieval has to find and no model has
to read off a page: the number, its unit, and how far the run stands
behind it.

The route does not guess. Every coordinate is one closed question
over the spec's own list (one request per field, the harvest's own
rule); an answer outside the list leaves the axis unbound, and an
unbound axis adds no constraint. A value with no trust line is not
shown with a blank badge: the route states why it did not answer,
and the caller falls back to the documents.

Which graph, which query and which axes are the profile's own.
`Hooks` carries them the way `answer.Corpus` carries the corpus, and
this module imports neither `profiles` nor `streamlit`. rdflib is
imported inside the functions that need it, the convention
`docpipe/ontology.py` states: the batch path never touches this
module, and the check that does can run on the cluster without it.

Author: Felix Vossel

## Classes

### Hooks

```python
@dataclass(frozen=True)
class Hooks
```

What a profile contributes to the KG route. None of it is core.

Fields:

- `query: str`: SPARQL with CONSTRAINTS_MARKER
- `axes: tuple`: coordinate axes to ask, in order
- `spec: Any`: a LOADED docpipe.extraction.spec.Spec
- `plan_iri: Callable`: (db_path, document name) -> str | None
- `bindings: Callable`: ({axis: uri | int}) -> (constraint text, {var: (kind, value)})
- `label: Callable`: (IRI or bare id) -> what a reader calls it
- `prose: dict`: the profile's trust wording, kg.TRUST_PROSE
- `notes: dict`: reason token -> sentence, inference.ROUTE_NOTES
- `prompt: Any`: the coordinate prompt, a docpipe.prompts.Prompt

## Functions

### check_notes

```python
def check_notes(notes: dict, where: str) -> dict
```

`notes` back, or raise if it does not word every reason exactly once.

Mirrors trust.check_prose: the reason tokens are the core's, the sentences
are the profile's, and a token without a sentence is a KeyError on a user's
screen rather than a finding at import.

### hooks

```python
def hooks(profile) -> Optional[Hooks]
```

The profile's contribution, or None where it has no graph to ask.

`component`, never `require`: a require with two constant arguments is
read by test_architecture as a demand on EVERY profile, and the scenarios
profile writes a different graph and answers from none.

### load_graph

```python
def load_graph(ttl_path) -> tuple
```

(graph, {value IRI: comment lines}) from the file `--serialize` wrote.

### load_graph_from_text

```python
def load_graph_from_text(text: str) -> tuple
```

The same, from a string. rdflib is imported here and nowhere above.

The serializer writes the prefix header once per run, so a file made of
several runs carries several headers, which is legal Turtle -- and a
fragment cut from a run's second document onward carries none and
would not parse. That case is named here rather than left to rdflib's
parser error on a prefixed name.

### trust_comments

```python
def trust_comments(text: str) -> dict
```

{value IRI: [comment line, ...]}: the lines standing over each node.

A convention, not a contract: the serializer joins evidence_comment's
lines and the node's own lines into ONE block, so the comments sit
directly above the `<iri>` line, and parts are joined with a blank line
between them. A blank line, a prefix line or any other statement resets
the buffer, which is what keeps a plan or a year node from inheriting the
comment of the value written before it. The trust line is LAST because
evidence_comment appends it last.

### to_coordinates

```python
def to_coordinates(task: str, spec, axes, ask) -> dict
```

{axis: uri | int} for what the question fixes, and nothing it does not.

Every axis is one closed question over the spec's own list, `ask(task,
slot)` returning one label or None. A label outside the list resolves
through the same fold_label / label_to_uri pair verify.py applies to a
harvested coordinate, so a synonym the spec knows lands and a wording it
does not is left unbound, never matched by nearest string.

### by_axis

```python
def by_axis(spec, axes, iris) -> list
```

[(axis name, [iri, ...])] in the profile's axis order, each IRI under
the axis whose own list holds it, and the rest under "".

Membership in the spec's lists and no third copy: the serializer writes a
carrier and a sector under the same predicate, so the query hands them
back mixed and only the lists can tell them apart. An IRI is matched to
a list entry by its bare id, the way the serializer minted it from one.

### run_query

```python
def run_query(graph, text: str, bindings: dict) -> list
```

[{variable: string}] for one SPARQL over the loaded graph.

`bindings` are (kind, value) pairs, "iri" or "literal", so the profile
that builds them stays rdflib-free. A literal binds UNTYPED: the
serializer writes the year node's label as a plain string, and
Literal(2030) with an integer datatype matches nothing.

### answer_from_graph

```python
def answer_from_graph(task: str, hooks: Hooks, graph, comments: dict, *,
                      db_path, document: Optional[str], ask) -> dict
```

The graph's answer, or why there is none.

{"route": "kg", "reason": None, "values": [...], "coordinates": {...}}
when the graph answered, each value carrying the row the query returned
plus `evidence` (the comment lines above its node) and `trust` (the last
of them). Otherwise route "rag" with one of REASONS, cheapest checked
first: no plan node costs one SQLite read, no coordinates costs the field
requests, no rows one SPARQL. The key is `values`, never `rows`: the app
dispatches a history entry with `rows` into the comparison render.

### trust_level

```python
def trust_level(line: str, prose: dict) -> Optional[str]
```

The level a trust line states, read by the profile's own wording.

[Back to the index](../README.md)
