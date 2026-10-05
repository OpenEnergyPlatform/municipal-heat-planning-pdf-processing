# Drafting a spec from shapes

## What it is for

An extraction spec says which parameters to look for, which closed list each
answer is chosen from, which node of the graph a value belongs to and, per
parameter, one real example. When the graph already has SHACL shapes and an
ontology, most of that is written once already by whoever maintains the
graph. `docpipe compile` reads them and drafts the spec instead of having it
written by hand. The result is a profile's `extraction_spec.json`, which
[extraction](extraction.md) loads.

```
docpipe compile spec --shapes shapes.ttl --ontology onto.owl --out draft.json
docpipe compile check draft.json
docpipe compile examples draft.json --profile mine
docpipe compile apply draft.json --out profiles/mine/extraction_spec.json
docpipe compile diff --shapes shapes.ttl --profile mine
```

| command | does |
|---|---|
| `spec` | one property shape becomes one parameter; the closed list, its labels and definitions, the datatype, the number of values and the graph node are carried over as they stand |
| `check` | lists what the draft still lacks; exit 1 while anything is open |
| `examples` | proposes the missing examples from a processed corpus into a review file; needs `--profile` (its prompt), the corpus and a model |
| `apply` | carries the examples somebody accepted into the draft, and writes the spec once nothing is missing |
| `diff` | holds a spec somebody wrote by hand against the shapes and changes nothing |

What shapes and ontology cannot state is left open and listed: how a
document words a term, what a number's unit is, and the example. A draft is
therefore not a spec yet; `spec.load` stays the judge of the finished file.

For a number's unit the draft only suggests, and the suggestion decides
nothing. Two things hang on the number under `_drafted`. One is the unit family
the ontology gives the shape's class (`unit_families`): a restriction "has unit
some X" on the class itself, on its `subClassOf` or `equivalentClass`, also
inside an intersection, else the nearest such statement on the classes above it,
else none; with the units of the family, its classes and named individuals, and
the other names the ontology has for each, which is where a symbol such as kWh
stands (`Terms.unit_families`, `Terms.units`). The relation is the OEO's
`OEO_00040010` by the end of its IRI (`terms.UNIT_PROPERTIES`) and is not yet the
profile's to name. The other is the unit list a shape itself holds
under that property (`units_listed`): beside a number it is not a category
parameter of its own, because a unit is part of the number. A unit list with no
number beside it stays a category parameter. `docpipe compile check` appends the
suggestion to the one open point for the number's units, after the sentence that
each entry of `units_accepted` needs its factor and, unless the number is a rate
(`integrated: false`), `names_period`: "Suggestion, not decided: ..." with the
first eight units named and all of them in the draft. `units_accepted`, the
factors and `unit_target` stay the author's to write. An entry listed without
`names_period`, or with one that is no true or false, gets a line of its own,
exactly where `spec.load` would refuse it, and `finished()` drops the suggestion
from the spec. The units a shape lists are not written to the graph by the
generic writer, which writes no unit statement for a number, so the draft's note
says that the has-unit triple a separate category parameter would have carried
is the author's to provide. When a shape has several numeric properties the
listed units hang on all of them, a year typed as an integer included.

A proposed example is never an example until a person has read it. The model
is asked which values of a parameter a passage states, and a proposal is
kept only where each value brings a quote that stands in the passage and
contains the value, the two checks every harvested value passes. A tuple whose
quote lies outside the part of the passage an example can show is not
proposed either (`NOT_SHOWN`), since it would be refused when applied. The
proposals go into `<draft>.examples.review.json` beside the draft
(`review_path`), so two drafts in one folder do not share a file; `apply`
takes exactly the entries with `"accept": true`.

A second run of `examples` keeps what somebody accepted and does not ask for
those parameters again. Passages are asked by rank across documents
(`by_rank`): the best passage of every document before the second best of any,
so each document looked in can give a proposal. A reply that is not the one
JSON object asked for is asked again once, with its cause, as the harvest does
(`ask_for_example`); nothing is repaired. A passage whose request got no reply
that could be read is not counted as read, and the review counts it as
`reply:<cause>`. The review records the profile it was proposed with, because a
number is held to its quote the way that profile's documents write one, and
`apply` refuses to run under another.

`diff` takes the class of a node from the `graph` block of the spec, and from
the block of the parameter that mints the node only where the graph block does
not say, and it reads the links from the same block: a property the graph
block links is not asked for, and neither is a unit list a shape holds beside a
number the spec asks for. It reports a cardinality only where the shapes
state one and the spec says something else (`differences` in `draft.py`). A
`not_asked` row (and its `--json` entry) carries the `shape` the property belongs
to, which `docpipe preflight` keys its record of properties left out on purpose
by. `examples` embeds its probes with the configured model and says in the log,
as the harvest does, when the index was built with another.

`docpipe init NAME --shapes [FILE]` is the other way to start: it writes the
draft of `compile spec` for FILE, or for the metadata shape the package brings
(`compile/bundled/metadata.shacl.ttl`, shipped as package data: a node on
`schema:CreativeWork` with eight text fields, title, author, publisher, date,
version, language, abstract and keywords, each with a name and a description),
with no ontology and the placeholder base, into the new profile as
`extraction_spec.draft.json`, never as the spec (see [the command](command.md)).
`draft_of` stops with the file's name, before anything is made, when it is not a
file, cannot be read as SHACL, whatever the reader fails with, or holds no shape
with a target class and a property to ask for. A draft made that way has nine
open points in `compile check` (the placeholder base and one example per field)
and no unit family, since it has no ontology; `compile spec` and
`compile diff` themselves still show a traceback for an unreadable file. The
comment the draft carries names `docpipe compile spec` as its writer, which is
not the command `init` ran.

The `graph` block of a drafted spec is what lets
[the generic graph writer](graph.md) serialize a harvest for a project that
has no writer of its own. Reading shapes needs `rdflib` (the `kg` extra); the
command says so and names the extra where it is not installed.

## Module reference

The docstring of each module of this stage, verbatim from the code and generated by `scripts/build_docs.py`. The chapter above is the account; this is the reference. Edit the docstring, not this page.

<details>
<summary><code>docpipe/compile/__init__.py</code></summary>

An extraction spec drafted from the shapes and the ontology of a graph.

</details>

<details>
<summary><code>docpipe/compile/cli.py</code></summary>

cli.py: `docpipe compile`, from the shapes of a graph to an extraction spec.

    docpipe compile spec --shapes shapes.ttl --ontology onto.owl --out draft.json
    docpipe compile check draft.json
    docpipe compile examples draft.json --db corpus.db --index faiss_index.bin
    docpipe compile apply draft.json --out profiles/mine/extraction_spec.json
    docpipe compile diff --shapes shapes.ttl --profile scenarios

`spec` drafts, `check` says what the draft still lacks, `examples` proposes
the missing examples from a processed corpus into a review file, `apply`
carries the accepted ones over and writes the spec once nothing is missing.
`diff` holds a spec somebody wrote by hand against the shapes and changes
nothing.

Author: Felix Vossel

</details>

<details>
<summary><code>docpipe/compile/shapes.py</code></summary>

shapes.py: What SHACL shapes say about a graph, read into plain records.

A shapes file states which nodes a graph has (a node shape and its target
class), which properties each carries (a property shape and its path), what
a value may be (a datatype, a class, a closed list) and how many there may
be. That is most of an extraction spec, written once already by whoever
maintains the graph. This module reads it and decides nothing: the records
say what the file says, and `draft.py` turns them into a spec.

What a property shape says in a way this reader does not follow (a path
that is no single property, a constraint only SPARQL states) is kept as a
note on the record, so the draft can say what it left out.

rdflib is imported where it is used, as in `docpipe.ontology`.

Author: Felix Vossel

</details>

<details>
<summary><code>docpipe/compile/terms.py</code></summary>

terms.py: What an ontology calls a term and says it means.

The lists and the properties of a shapes file are identifiers. What stands
behind one, its label, the other names it goes by and its definition, is in
the ontology. This module reads those for any IRI, from whichever of the
usual annotation properties a given ontology uses, so a spec's closed list
can offer the model the ontology's own words.

It also reads one kind of statement about a class: the unit family an
ontology gives a quantity ("has unit some energy unit"), and the units of that
family. That is a suggestion for whoever writes a number's units; which
spellings a document uses and the factors between them are not in an ontology.

Nothing is made up here: a term the files say nothing about has no label,
and the draft says so.

Author: Felix Vossel

</details>

<details>
<summary><code>docpipe/compile/draft.py</code></summary>

draft.py: An extraction spec drafted from shapes and an ontology, and what
an existing spec says differently.

One property shape becomes one parameter. What the shapes and the ontology
state is carried over as it stands: the closed list with the ontology's own
labels, other names and definitions, the datatype, how many values there may
be, and which node of the graph a value belongs to. What they cannot state
is left open and listed: how a document words a term, what a number's unit
is, and the one real example every parameter needs. A draft is therefore
not a spec yet. `todo` says what is missing, and `spec.load` stays the judge
of the finished file.

For a number's unit the draft only suggests. The units a shape lists itself
and the unit family the ontology gives the shape's class hang on the number
under `_drafted`, and `todo` names them; `units_accepted` and the factors
between the entries stay the author's to write.

The same reading, held against a spec somebody wrote by hand, gives the
differences: a list entry the shapes have and the spec lacks, a property
nobody asks for, a parameter the shapes do not know. That is a report and
changes nothing.

Author: Felix Vossel

</details>

<details>
<summary><code>docpipe/compile/examples.py</code></summary>

examples.py: Proposes, from the corpus, the example a parameter still lacks.

Every parameter of a spec carries one real example: a snippet of a document
and the tuples it yields. It is the prompt's demonstration and the dry run's
test, and writing one per parameter is the heaviest part of a new spec. This
module finds candidate passages in a processed corpus, asks the model which
values of the parameter a passage states, and keeps a proposal only where
each value brings a quote that stands in the passage and contains the value.
Those are the checks every harvested value passes, and nothing else is
asked of a proposal.

A proposal is never an example. It goes into a review file beside the
draft, with the document it came from; a person reads it, sets `accept`,
and `apply` carries exactly the accepted ones into the spec. What a model
drafted becomes a demonstration only after somebody has read it.

The two things this module needs from a run are handed in: `find`, which
returns passages for a parameter, and `ask`, which returns the model's
reply for one passage. So the logic is tested without a corpus and without
a model.

Author: Felix Vossel

</details>

[Back to the index](../README.md)
