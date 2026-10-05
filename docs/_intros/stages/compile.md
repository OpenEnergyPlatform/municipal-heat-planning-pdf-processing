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
block links is not asked for. It reports a cardinality only where the shapes
state one and the spec says something else (`differences` in `draft.py`).

The `graph` block of a drafted spec is what lets
[the generic graph writer](graph.md) serialize a harvest for a project that
has no writer of its own. Reading shapes needs `rdflib` (the `kg` extra); the
command says so and names the extra where it is not installed.
