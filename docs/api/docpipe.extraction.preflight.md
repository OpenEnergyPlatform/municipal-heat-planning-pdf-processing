# docpipe.extraction.preflight

`docpipe/extraction/preflight.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

preflight.py: A profile, everything a corpus run rests on.

Not a smoke test. Every line here failed at least once in a way that cost a
GPU run or a night: a prompt whose max_tokens was sized for a contract two
versions old, a vocabulary entry that means "I do not know" sitting where a
class belongs, an axis with no question so the field request carried no
rule.

Prints a table and exits non-zero on a hard failure, so it can stand before
a GPU run:

    docpipe preflight                   the profile in effect
    docpipe preflight kwp scenarios     these

It holds for any profile, wherever it lives. What it reads of a profile is
what the run reads: the spec the profile names (`extraction.SPEC_PATH`),
its prompts, the drawing of its graph (`map` of `graph.json`), its
`vocabulary` module where it has one.
The keys of a request and a reply are the stage's and are checked here by
name. A wording the run depends on is the profile's, in the language of its
prompts, so the profile says which passages its prompts have to hold
(`extraction.PROMPT_CHECKS`). The shapes of its graph are the profile's as
well: it says where they are (`extraction.shapes_files`) and which of their
properties it leaves out on purpose (the rule `not_extracted`).

Two lines only say what they find and never fail: the properties of the
shapes that nobody asks and the definitions of the spec that are not the
pin's.

Author: Felix Vossel

## Functions

### prompt_checks

```python
def prompt_checks(declared) -> tuple
```

A profile's `PROMPT_CHECKS` as (entries, what is wrong with them).

An entry is (what is checked, prompt id, passage, whether the passage
has to be there or must not be). One that is anything else is named
and not run: a check that cannot be read holds nothing.

### silent_parameters

```python
def silent_parameters(raw: dict, drawing=None) -> list
```

Which parameters of a raw spec the drawing of the graph does not name.

A field says what it becomes in the graph when the drawing names it as a
source: an arrow starts at it, a box is of it or takes its value, name
or address from it, or a brick or a box's `settle` names it
(`graph.Drawing.says`). No drawing names nothing.

A function rather than three lines inside `audit`, because a gate that
cannot be handed a failing input is decoration, and `audit` can only be
handed a profile's own files, which are, by the time anyone runs it, the
ones that pass.

### left_out_of

```python
def left_out_of(profile) -> object
```

The properties of the shapes *profile* leaves out on purpose, as its
rule `not_extracted` says them: {(shape, property): why}, None where its
line knows no such rule.

### not_extracted

```python
def not_extracted(declared) -> tuple
```

The properties a profile leaves out on purpose (`left_out_of`) as
({(shape, property): why}, what is wrong with it).

The shape properties the profile leaves out on purpose, each with a
sentence of reason. An entry that is anything else is named and not
counted: a record that cannot be read records nothing, so what it was
meant to cover warns as if it were not there. The same holds for a value
that is no mapping at all, which is named once.

### shape_properties

```python
def shape_properties(files, raw: dict, profile=None) -> tuple
```

(properties no arrow writes, all properties) of the shapes.

Both as sorted (shape, property) pairs, the property by the end of its
IRI. A property is written when an arrow of the drawing of the
profile's graph file writes it: `docpipe compile diff` decides that and
this reads what it lists as "not_asked". The shapes file is read as the
compiler reads it, which needs rdflib.

### shapes_verdict

```python
def shapes_verdict(profile, raw: dict) -> tuple
```

(ok, detail) for the shape properties nobody asks, never a failure.

The profile says where its shapes are (`extraction.shapes_files`, the
files of its last refresh) and which of their properties it leaves out on
purpose (the rule `not_extracted`). Where it names no shapes, or the
file is not there, or rdflib is not, the line says it is skipped: a
check that was not run is not a gap found.

### audit

```python
def audit(name: str) -> list
```

Every check of one profile: (profile, what, ok | warn | FAIL, detail).

Makes the profile the one in effect for this process (the environment
names it), because its prompts and its wording are read through that.

### report

```python
def report(rows: list) -> int
```

Print the table; how many checks failed hard.

### main

```python
def main(argv: Optional[list] = None) -> int
```

[Back to the index](../README.md)
