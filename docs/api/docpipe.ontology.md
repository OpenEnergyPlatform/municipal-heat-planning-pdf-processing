# docpipe.ontology

`docpipe/ontology.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

ontology.py: Reads the ontology a spec is written against once and
pins it in a snapshot.

Every closed list a profile offers names terms of an ontology, and a
spec that is never checked against one can come to describe a graph
that does not exist. This module reads an ontology file and writes a
snapshot: per term its label, its foreign alternative labels, its
definition, its parents, whether it is deprecated, and which kind of
thing it is (a class, an individual or a property). It also writes
the sets a list may draw from, and a pin (the version IRI and the
file's own sha256), so the question of which ontology a spec is
written against has an answer.

The module is profile free by design. What a profile keeps is its
own: which roots its sets draw from, where its closure lives, and the
rules that concern its own axes. The builder, the index, the
identifier walk, and the two checks every profile shares (a term the
ontology does not have, a term the ontology has deprecated) are the
same question in every profile, so they live here.

The kind recorded for each term matters beyond bookkeeping. A `kg`
block names predicates, and a predicate is an owl:ObjectProperty; an
index built over classes and individuals alone would report every
predicate as missing. That is why the scenarios profile had no
snapshot before this module existed: its seventeen identifiers are
mostly predicates.

rdflib is imported inside the functions that need it. The checks run
against the checked-in snapshot and need neither an ontology file nor
rdflib, which is what lets them run on the cluster.

Author: Felix Vossel

## Functions

### short

```python
def short(uri) -> str
```

The identifier at the end of an IRI, or the string as it stands.

### named

```python
def named(node) -> str
```

`short`, except a datatype keeps the prefix that tells it apart.

A property's range is a class or a datatype and the two are checked
differently: `dateTime` alone would read like an ontology term.

### identifier

```python
def identifier(value) -> Optional[str]
```

`OEO_00000510` out of either spelling, or None if it is not one.

A profile's own word is never one: `out:not_in_list` and `status_quo`
fail the shape, and so does an identifier inside a sentence, because the
match has to run to the end of the string.

### read

```python
def read(paths: list)
```

### index

```python
def index(graph) -> dict
```

identifier -> {kind, label, alt_labels, definition, parents, deprecated}.

Properties as well as classes and individuals. Without them a spec's `kg`
blocks -- which name predicates and nothing else -- read as a list of
terms the ontology does not have.

### closures

```python
def closures(graph, sets: dict) -> dict
```

Each set of `sets` as a sorted list of identifiers.

`sets` is the profile's: {name: ("class"|"individual", root IRI)}. Which
roots a profile's lists draw from is the one thing about a vocabulary that
is genuinely per profile, so it stays there.

### spec_terms

```python
def spec_terms(spec_raw: dict) -> dict
```

Every ontology identifier the spec names, and where it names it.

The whole spec, at any depth, in keys as well as values: a vocabulary
writes its terms as KEYS, a `kg` block writes them as values, and one
profile spells them bare while the other spells them as IRIs. The version
this replaces walked three named places, matched bare identifiers only,
and reported zero identifiers for the scenarios spec -- a checker that
checks nothing reads exactly like a spec with nothing wrong.

### build

```python
def build(closure: Path, sets: dict, spec_raw: dict, *,
          extra: Optional[list] = None, base: str = "") -> dict
```

The vocabulary snapshot, from the ontology files as they stand.

`extra` are further files parsed into the same graph (MHPO, say); `base`
is the IRI prefix whose ontology header carries the version to pin.

### serialize

```python
def serialize(snapshot: dict) -> str
```

### load

```python
def load(path: Path) -> dict
```

### uncovered

```python
def uncovered(spec_raw: dict, snapshot: dict) -> dict
```

{family: [where, ...]} for identifiers no file of this snapshot covers.

Not a problem and not silence either. It is the honest third answer to
"does the ontology have this": the snapshot cannot say.

### term_problems

```python
def term_problems(spec_raw: dict, snapshot: dict) -> list
```

The two complaints every profile shares: absent, and deprecated.

Silent about a family the snapshot does not cover; `uncovered` reports
those, so a term nobody can check is a named gap rather than an error.

### kind_problems

```python
def kind_problems(spec_raw: dict, snapshot: dict) -> list
```

A `kg` block's predicate that the ontology does not call a property.

The block says what a coordinate becomes in the graph, and a class written
where a predicate belongs emits Turtle that parses and asserts nonsense.
Only checkable since the index carries the kind.

### spec_edges

```python
def spec_edges(spec_raw: dict) -> list
```

Every triple shape the spec's `kg` blocks promise.

Derived, never listed: the parameter's `class_from` names the axis whose
options are the classes a value node can carry, so each of those is a
subject; `number` and `unit` are its own predicates, and an axis with
role `edge` is one predicate whose objects are that axis' options. A
parent axis contributes the edge from the node above down to the
container it mints. What is left over is the handful of edges behind no
parameter, and those are the profile's to declare.

### ancestors

```python
def ancestors(name: str, snapshot: dict) -> set
```

Every term above this one in the snapshot, transitively.

### edge_problems

```python
def edge_problems(edges, snapshot: dict) -> list
```

Emitted triples the pinned ontology contradicts.

`edges` is what a serializer writes, as {where, subject, predicate,
object, datatype} -- the subject's asserted class, the predicate, and
either the object's class or the literal's datatype. Every field but the
predicate may be absent, and an absent field is not checked.

Why this is worth its own check. `term_problems` asks whether a predicate
EXISTS and `kind_problems` asks whether it is a property; neither asks the
only question a reader of the graph cares about, which is whether the
triple is one the ontology allows. `rdfs:domain` is not a constraint a
reasoner refuses -- it TYPES the subject -- so a wrong domain does not
fail loudly anywhere, it silently asserts that our value nodes are
something they are not. Three kwp edges named a domain (`study`) that is
an occurrent while every value is a continuant, and the closure asserts
those two disjoint: the whole graph was unsatisfiable and every check we
had passed.

Silent about a family the snapshot does not cover, like every check here.

### set_problems

```python
def set_problems(spec_raw: dict, snapshot: dict, rules: dict) -> list
```

An axis option the ontology does not put under that axis' root.

`rules` is {axis name: set name} and is the profile's: which of its axes
draws from which root is a statement about that profile's spec.

### foreign_labels

```python
def foreign_labels(spec_raw: dict, snapshot: dict) -> list
```

Options whose first label is not one the ontology gives the term.

Not an error. The first label is what the model is offered and it is meant
to be the word the corpus writes: a heat plan says "Private Haushalte",
OEO says "household sector", and offering the ontology's word would ask
the model to translate before it reads.

It is worth listing all the same, because the same shape hides a real
defect: an option labelled with a specific word whose class is a generic
one. "Klaerschlamm" offered as OEO_00000439 waste fuel does not mean the
model chose badly -- it means every sewage-sludge reading in the corpus
becomes a generic waste fuel and nobody looking at the graph can tell.

[Back to the index](../README.md)
