# 8. The knowledge graph

## Purpose

This area turns an extraction harvest, a directory of per-document JSONL
files written by [extraction](extraction.md), into the profile's target
knowledge graph: MHPKG on the Open Energy Platform for
[`kwp`](../profiles/kwp.md), OEKG for
[`scenarios`](../profiles/scenarios.md), the last hop from a value
that survived verification and trust scoring to a fact a query engine
can walk. The walk from JSONL to Turtle splits in two:
`docpipe/extraction/serialize.py` is a profile free core guaranteeing
the file walk and that a refusal line never reaches a serializer,
while `profiles/<name>/kg.py` decides IRI minting, node shape
and predicate choice for a profile that has a writer of its own. A
profile whose spec carries a `graph` block and which has no `kg.py` is
written by the generic writer, `docpipe/extraction/graph.py`. `kwp`'s Turtle
file is read back by `docpipe/inference/kg_route.py` when the chat
(`docpipe/app`) has a graph configured; `scenarios`' `kg.py`
declares no `COORDINATE_AXES` or `VALUE_QUERY`, so its file has no
reader here. Beside the graph a run also writes where each value comes from,
as a second file (see The provenance file under Method).

A second, unrelated tool lives here: `docpipe/ontology.py`, with
`profiles/<name>/vocabulary.py` and `docpipe/upstream.py`, writes a
checked-in JSON snapshot of the terms a profile's
`extraction_spec.json` may reference, and checks the spec's `kg`
blocks and a serializer's declared edges against it. `upstream.py`
pulls a profile's declared `SOURCES`, the OEO closure among them, at
whichever version upstream currently calls its own; `vocabulary.py`
no longer needs a closure file handed to it by hand. Auditing the spec
stays ahead of a corpus run rather than inspecting Turtle afterward,
with one exception: where a profile's `vocabulary.shapes()` names
SHACL files pulled by the last refresh, `--serialize` holds the
written graph against them and logs a report, never a gate on the
write. The two tools otherwise do
not call each other: `vocabulary.py`'s `edges()` imports the profile's
`kg.py` module directly to read its `EDGES` table, and that import
alone runs `kg.py`'s own module level calls to `spec.py`'s
`kg_name` and `load` and `trust.py`'s `check_prose`, a side effect
rather than a call the ontology check makes itself.

## Position in the pipeline

| | |
|---|---|
| **In** | A document's accepted JSONL tuple lines (`kind == "tuple"`), the profile's SQLite corpus database, and its `extraction_spec.json` `kg` blocks, parsed once at import. |
| **Out** | One Turtle file per `--serialize` call: a shared prefix header plus one block per document that produced anything (`kwp`'s read back by `kg_route.py`; `scenarios`' by nothing here), and beside it the provenance file `<graph>.prov.ttl`. |
| **Resumes on** | Nothing. Every call re walks the harvest and re renders the whole output; a run's dedupe state (which identities are claimed) is never persisted. |
| **Needs** | No served model and no GPU: a read only SQLite connection and local text; the ontology check also needs `rdflib`. `vocabulary.py --refresh` needs network access to pull `SOURCES`, and, for `scenarios`, `OEP_API_TOKEN`; `--write` needs an external OEO closure file by hand instead. The SHACL report a `kwp` `--serialize` run writes needs `pyshacl`. |

Extraction precedes this stage
([Reading the values out](extraction.md)); `kwp`'s output is followed
by `kg_route.py`, `scenarios`' by nothing in this repository.

## Method

### Walking the harvest and choosing a serializer

`serialize.collect` globs every `*.jsonl` file, logs a warning and
skips a line that does not parse, and keeps only rows whose `kind` is
`"tuple"`; a refusal or summary line never reaches a serializer.
`serialize.run` calls the profile's `serializer(name, rows)` once per
document (`None` skips it), concatenates what came back, and refuses to
write at all, raising `ValueError` with the output path untouched, when
nothing came back. The CLI, `--serialize` on `python -m
docpipe.extraction` (`docpipe extract`), resolves the profile, takes its
`kg.make_serializer` where it has one and otherwise the generic writer built
from the spec's `graph` block (see below), and logs and exits 1 on that
`ValueError`:

```bash
python -m docpipe.extraction <db> <index> <out> \
    --serialize <ttl path> --profile kwp
```

The `index` positional is still required by the parser, though this
branch returns before it is touched.

### The generic writer

A spec drafted by [`docpipe compile`](./compile.md) carries a `graph` block,
the base IRI, the prefixes, the nodes and how they are linked, and every
parameter's `kg` names the node and the property its value is written to. That
is everything a writer needs, so a project whose spec was compiled needs no
`kg.py` (`docpipe/extraction/graph.py`). A profile that has a serializer keeps
it: its graph knows things no shape says.

Per document the writer writes a node of each kind the block declares
`per: document`, once it carries something; a property for the value of a
parameter, a literal of the property's datatype or the term chosen from the
parameter's list; a node of its own for a value that names one, at
`<base><node>/<its wording>`, with the wording written under the parameter's
`kg.property` and the edge to it; and a link between two nodes that are both
there. Three things are left out and counted in the log, none silently: a
parameter with coordinates (where a year or a scenario goes is not something
the block says, and two values of two years would become one property with two
numbers); a property that allows fewer values than the harvest has (`max`: the
values of the best trust level are taken, and if those are still too many none
is written, because picking one would be a guess, and a value that is left out
leaves no node of its own behind either); and an answer that is not a term
where a term has to be written.

### The provenance file

A graph carries a number. That it was read on page 97, from which words, by
which run and how far the run stands behind it, the harvest knows and the graph
does not say. `--serialize` writes that in a file of its own beside the graph,
`<graph>.prov.ttl` (`docpipe/extraction/provenance.py`), as PROV-O and W3C Web
Annotation statements: per value an annotation whose body is the value and
whose target is the page, refined by the quote and, where it was located, by
its rectangles; per coordinate an annotation of its own with what was read, the
wording and how the reading ended; the trust level with its reasons; and once
per document the run, with its model and the fingerprints of the spec and the
prompts. A coordinate that a pass after the harvest wrote, a top-up that read it again
or the pass that appended its row (it carries `<axis>_producer`,
see [Reading the values out](extraction.md)), is generated by an activity of its
own, `<base>prov/run/<document>/producer-<n>` (n is the position in the stamp's `producers` list),
with the pass as its label, the document it used, the model as its agent, the
time it ended and a hash of its prompts; a pointer to an entry the stamp does
not have leaves the coordinate with no generating activity and no mapping
agent, not the run's. Every statement points at a value and none starts from
one, so the graph itself is the same with and without the file, and a reader
who does not want it leaves it away.

The file is written where the writer names a base IRI for its terms (a
profile's `kg.PROVENANCE`, or the `graph` block of the spec), from what a
serializer leaves in its `claims`. `--no-provenance`, or `EXTRACT_PROVENANCE=0`,
leaves it out. A file that this run did not write is not removed, and the run
warns that it describes an earlier graph. Not written is the decision between
two readings that claim one value: the writers settle that before a value
reaches this module. A decision of a person is not that: it is recorded and
judges nothing.

What people decided about a value is kept beside it. After the harvest is
read, `serialize.run` reads `gold.jsonl` from where `evaluate` finds it by
default, next to the harvest directory (`gold.path_beside`), and looks each
decision up by the row's name (`gold.decisions_in`; not in `collect`, which
`evaluate` and the review page read their rows through). The decisions the
review page wrote to another path, `INFERENCE_GOLD_PATH`, are not read by
`--serialize`: the file has to lie beside the harvest. What is kept is the
settled verdict of each decided field (`Gold.settled`): correct or wrong, who
decided, when, and the note. The value is the same with it and without it,
and none is left out because of one. In the provenance file of a profile that
writes one (kwp, and the generic writer) a decision is a node of its own,
`Decision`, with `about` the value, the coordinate, the verdict as `rdf:value`,
`dcterms:creator`, `dcterms:created` and `rdfs:comment` for the note. The
scenarios graph writes against closed shapes, so there a decision is one
comment line after the value's trust line: `decision: FIELD VERDICT, by NAME,
TIME, note: NOTE`, the parts that are missing left out, a line break in the
note flattened. The kwp graph itself carries no decision, so the comment block
`kg_route.py` reads above a node, whose last line is the trust line, is as it
was.

The run says what it did. `serialize: N decision(s) on M row(s) of K
document(s) read` is the count of what was read. A decision about a row the
harvest does not hold is applied to nothing and named in a warning (ten names,
then "and N more"). The last line, `N of M decision(s) recorded beside their
value in the provenance file; K decision(s) are about rows the writer left out
of the graph`, counts the ones that found no value: a losing reading of two
for one value, a repeat row the node was not made from, a kwp organisation, a
document the writer wrote nothing for. A run that writes no provenance file
(`--no-provenance`, `EXTRACT_PROVENANCE=0`) and whose serializer takes none
says `N decision(s) read and recorded nowhere`. A decisions file that does not
read is a warning and the run goes on; no exit code depends on any of it. A
decision on a field the row no longer has is neither found nor counted.

### kwp: gating, identity and rendering the plan

`profiles/kwp/kg.py`'s `serializer` pulls `planning_organisation` rows
into a normalised `offices` dict; every other row passes a gate,
`quantity` checked first: `quantity` a class in `UNIT_TARGET`,
`scenario` a key of `PARTS` (`status_quo`, `trend`, `target`),
`spatial_scope` `municipality` or a named `sub_area`, `year` an `int`,
`aggregation` present and known. A row failing any gate is dropped and
counted by reason; quantity first, so a row closed on it is counted
`not_a_class:<quantity>` and never reaches the scenario check.
Before the reorder it counted `scenario_unread` as well, about 37,300 of
corpus_m5's 42,882, a gate decision reported as a reading failure.
`_document_identity` resolves a document's AGS and publication date
from `Documents` and `DocumentMeta`/`Municipalities`; a document whose
AGS or date does not parse yields `None` and its tuples are skipped
whole, logged once. A
`claimed` dict maps each `(ags, published)` pair to its first
claimant; a second document claiming the same pair is refused whole
rather than merged onto it.

`_value_iri` mints a surviving value's IRI as a UUIDv5 over the
scenario part, quantity, carrier, sector, year and aggregation, plus,
only for a named `sub_area`, the area wording, left out for a whole
plan value so several wordings of one fact do not split into separate
nodes. A carrier or sector enters the IRI only where `is_class` calls it
a real OEO class; a deliberate `out:` answer or an unmapped wording is
left out exactly like an absent one, so the identity matches what gets
an edge. `settle` resolves every row minting one identity together: the
same number twice is one node, marked read twice, counted `duplicate`;
different numbers under different plan wording (`carrier_raw`/
`sector_raw`) split into a node per wording, named by it, counted
`split:wording`; failing that, a reading within `ROUNDING_TOLERANCE`
(2%) of another loses to the more precise one, counted
`conflict:rounding`; failing that, the lower trust level loses to the
higher, counted `conflict:trust`; what none of those settles still
drops every claimant, counted `conflict`. Each winner's comment states
what it won over. The plan node gets `has part` edges only to parts with a
surviving value; all three parts are
written (docstring stale, naming only target). A value node's type is
its quantity's OEO class; its carrier, sector and year edges share one
edgeless predicate, `obo:IAO_0000136 is about`; nine carrier classes
plans name constantly sit outside OEO's `energy carrier` root, so
`kg.outside_root` keeps their edge, counted, not lost. A year
is one node per calendar year, keyed by the year, not minted. Above
each value node, `evidence_comment` writes its wording, quote,
location and rendered trust line as Turtle comments, since target
shapes are `sh:closed` with no triples toggle.

### kwp: asking the graph

`COORDINATE_AXES` lists what a query can fix, in spec order:
`scenario`, `quantity`, `carrier`, `sector`, `year`; `spatial_scope`
and `aggregation`, both part of a value's identity, are left out: no
edge links a value to its area, and aggregation is returned rather
than constrained. `VALUE_QUERY`, a SPARQL template built from the
serializer's predicate constants, selects a value's quantity, number,
unit, year, aggregation and plan part, gathering every `is about`
object into one `abouts` string and excluding the year node by its
class so it does not return as a carrier. `value_bindings` turns a
coordinate dict into `##CONSTRAINTS##` lines and a `{variable: (kind,
value)}` binding map, one line per bound axis, dropping an `out:`
quantity, since `oeo:out:potential` names no graph IRI. `label_of`
picks the label a reader sees: the spec's first spelling where named,
else the pinned vocabulary's label, else the identifier itself.

### scenarios: fields, scenario identity and rendering

`profiles/scenarios/kg.py`'s `serializer` groups rows by parameter and
counts every `out:` answer, and every unresolved
`scenario_label`/`scenario_region`/`scenario_type` or bundle tag row,
into `out_of_graph`, logged but never written. For fields the OEKG shapes
allow at most once, `_pick_one` ranks readings, dropping a substring
candidate first, then by vote count, location and length; the rest
are `contested`. A document with no `publication_title` is skipped
whole; a missing date or author is only logged. A read only
connection cross checks the chosen fields against the crawl's
`DocumentMeta`, logging disagreement, not substituting it,
and loads the document's AR6 scenario list, continuing empty if the
connection fails. Every scenario scope row is resolved by
`scenario_key` against that list: an `out:` answer clears the
identity; a wording matching exactly one run, even one the model
refused, is resolved; a wording fitting several runs equally names a
family instead, so the rows fall back to the wording alone, logged by
name; a wording absent from its own quoted passage is refused as an
identity entirely.

The study report IRI is minted from the title, the bundle IRI from
`study_project_name` or the title; a second document reusing either
IRI is logged, not refused, its triples landing on the shared subject.
The bundle also takes one triple for each tag entry the model picked off
the shapes' lists (`BUNDLE_TAGS`), and none for an `out:` entry or an
unmapped wording, which are counted.
One factsheet is minted per resolved identity: `rdfs:label` is the AR6
database's own spelling when known, `dc:acronym` the document's own; a
matched study region is referenced by its existing OEKG IRI, never
minted; an unmatched wording mints nothing and is counted. `entities()`
mints one node per distinct author, organisation or funder by
normalised spelling, keeping each row's passage in the evidence. A row
whose scenario coordinate never resolves reaches no triple, comment or
number; it is counted `unplaceable`, keyed by state, since without it
the gap read as zero. Evidence for a triple is a flattened comment, or,
with `OEKG_EVIDENCE`
on, a linked `oekgprov:ExtractionEvidence` node; either way the
rendered trust line follows it. That reading lives in `_make_builder`, which
`make_serializer` and `make_study_reader` share; the second hands the same
document as plain data to `profiles/scenarios/oekg_api.py`, a dry run of the
OEKG scenario-bundle API that sends nothing, described on
[the scenarios profile](../profiles/scenarios.md).

### Checking a spec against the ontology

`ontology.read` parses OWL or Turtle into an `rdflib` graph; `index`
walks every labelled class, individual and property into a per
identifier record (kind, label, `alt_labels`, definition, parents,
deprecated, and, for a property, its domain and range). The parents of a
class are its superclasses, those of a property its superproperties, and
those of an individual the classes the ontology asserts it into: a
predicate's range names a class, and an individual object is held to it
through its own class and nothing else. `alt_labels`
holds the term's alternative spellings in one language, the one the profile
names (`extraction.ALT_LABEL_LANGUAGE`: `de` for kwp and scenarios, `en` for
the built-in profile; `index` and `build` take it as `language`, without a
default), checked by `foreign_labels` below. `closures` computes, per declared root, every
class under it or individual it types. `build` grows a profile's
closures plus its spec's identifiers to a fixpoint over parents,
domains and ranges, and writes a pin recording the ontology's version
IRI, each file's sha256, and which identifier families the files
cover. It also carries what a writer's own edges name (`also`, which
`kwp` fills from `vocabulary.edge_terms`): `edge_problems` asks
whether a subject is under a predicate's domain, and a class the
snapshot lacks has no parents to answer with. `vocabulary.py --write`
calls this with an external `--closure`
file (plus, for `kwp`, `--mhpo`) and overwrites `vocabulary.json`;
`--refresh` does the same pull automatically, through `upstream.py`
(below), and then runs `--check` on what it wrote. `--check` runs
`term_problems` (name absent or deprecated),
`kind_problems` (a `kg` predicate the ontology calls a class),
`edge_problems` (a triple outside its predicate's domain or range),
`set_problems` (an axis option outside its root), plus `kwp`'s
`carrier_problems` or `scenarios`' `region_problems`; each a string,
never an exception, and the CLI exits 1 if any exist. Both CLIs then
print `foreign_labels`' notes, one line per corpus label whose first
spelling is not the term's own, and then one note per class whose
definition in the spec is not the pin's (`ontology.definition_differences`:
`REWRITTEN`, the spec has a definition and the pin's words are others, or
`PIN_ONLY`, the pin defines the class and the spec says nothing; white space
is folded, a definition only the spec has is the author's own, `out:` entries
and classes the pin does not know are skipped). Both end on a summary line
naming identifiers checked, problems found, such labels noted and definitions
that differ from the pin. The notes are printed and never counted as a
problem, so the exit code is what it was. Only
`scenarios`' `--check` also prints `uncovered` notes, for a family no
parsed file covers.

### Pulling the sources a profile is written against

`docpipe/upstream.py` resolves each of a profile's `SOURCES` to a
version and caches it under `data/upstream/<source>/<version>/`: a
`release_asset` is an asset of the repository's latest GitHub release,
found from the redirect `github.com/<repo>/releases/latest` gives,
never the GitHub API; a `release_file` is a file in the repository at
that release's tag, for a project that attaches nothing to its
releases; a `repo_files` source is files at a branch
head, versioned by a digest over their bytes and, where the source
names a `reviewed` commit, compared against it so a schema `kg.py`
mirrors by hand is named the moment it moves; a `sparql` source
queries the OEKG endpoint with a token read from the environment
variable it names and written nowhere. `kwp` reads MHPO's `mhpo.owl`
as a `release_file`, because MHPO's releases carry no attachment.
`write_lock` records every
source's result in `data/upstream/<profile>.lock.json`.

`vocabulary.py --refresh` pulls `SOURCES`, rebuilds `vocabulary.json`
from what came back, writes the lock, then runs `--check` against the
fresh snapshot; a source that cannot be resolved raises and stops the
refresh before anything is rewritten. `kwp`'s `mhpkg` source also
carries the MHPKG SHACL files: `vocabulary.py`'s `shapes()` names the
last refresh's copies, and `--serialize` holds the written Turtle
against them through `serialize.validate`, which calls
`ontology.shacl_report` and writes `<ttl>.shacl.txt` beside the graph,
a report and not a gate.

## Data model

The harvest tuple row this area reads carries the resolved value and
unit, each axis coordinate with its own `_state`/`_source` pair, a
`tier`, `quote`, `compute` and `flags`, and a `provenance` block; the
full field list is at [contract/kwp.md](../contract/kwp.md) and
[contract/scenarios.md](../contract/scenarios.md).

The node kinds each file carries, one per document, are described
above under Method: for `kwp`, plan, part, value, year, organisation,
sub area and municipality; for `scenarios`, report, bundle, factsheet,
author, organisation and funder, plus, only with `OEKG_EVIDENCE` on,
one evidence node per cited passage. Both carry a single `@prefix`
header, emitted once per run.

The ontology snapshot both profiles check against is `{pin, sets,
terms, disjoint}`, plus `regions` for `scenarios`; `pin` carries
`sources`, one version per entry of `SOURCES`, once a snapshot has
come from `--refresh`. A declared edge, the
unit `edge_problems` checks, is `{where, subject, predicate,
object|datatype, accepted}`: `accepted` lets a serializer name why a
triple contradicts the pinned domain or range, for example `scenarios`' `has
uuid` on a bundle, though domained on report or factsheet alone, or
`kwp`'s publication date on the plan, a slot the MHPKG schema
prescribes with range `date` where OEO says `xsd:dateTime`.

Every value's trust verdict, `{level, reasons, image_origin,
corroborated}`, is rendered into one line by a profile's own
`TRUST_PROSE` table, written as the last comment above the value's
node, in English for both `kwp` and `scenarios` (where a person decided
something about the value, the scenarios graph adds a decision line after it,
see The provenance file). The level is a floor,
computed once and never raised by later human review, and where a
coordinate's passage stands is no reason. The levels, reasons and
marks a trust line is built from are at
[contract/trust.md](../contract/trust.md).

## Configuration

| name | kind | default | effect | where |
|---|---|---|---|---|
| `db` (positional) | required argument | none | SQLite path passed to `make_serializer(db_path)` | `runner.py` |
| `out` (positional) | required argument | none | Harvest directory `serialize.collect` walks | `runner.py` |
| `--serialize TTL` | CLI flag | none | Switches to serialize only mode, writing the graph here | `runner.py` |
| `--no-provenance`, `EXTRACT_PROVENANCE` | CLI flag, env var | provenance written (`1`) | With `--serialize`: leave out the provenance file beside the graph | `runner.py` |
| `--profile NAME` | CLI flag | `$DOCPIPE_PROFILE` | Selects which `kg.py` and spec the run uses | `docpipe/profile.py` |
| `DOCPIPE_PROFILE` | environment variable | unset | Default for `--profile` | `docpipe/profile.py` |
| `OEKG_ID_BASE` | env var, `scenarios` only | `https://openenergyplatform.org/ontology/oekg/` | Overrides the IRI prefix every node and namespace uses | `profiles/scenarios/kg.py` |
| `OEKG_EVIDENCE` | env var, `scenarios` only, truthy unless `"0"` | off | Links each passage as an `oekgprov:` node, not a comment; provisional under `sh:closed` OEKG shapes | `profiles/scenarios/kg.py` |
| `--refresh` | CLI flag | off | Pulls `SOURCES` at their current version, rebuilds the snapshot and the lock, then runs `--check` | both `vocabulary.py` |
| `--closure PATH` | flag, `vocabulary.py --write` | required with `--write` | OEO closure file `rdflib` parses by hand; not vendored here | both `vocabulary.py` |
| `--mhpo PATH` | flag, `kwp` `--write` only | none | Extra MHPO ontology file parsed into the same graph | `profiles/kwp/vocabulary.py` |
| `--write` | CLI flag | off | Rebuilds and overwrites `vocabulary.json` from a hand-provided file | both `vocabulary.py` |
| `--check` | CLI flag | off; also runs without `--write`/`--refresh` | Holds the spec against the snapshot; exits 1 on any problem | both `vocabulary.py` |
| `OEP_API_TOKEN` | env var, `scenarios` only | unset | Token for the OEKG SPARQL endpoint; `--refresh` stops without it | `profiles/scenarios/vocabulary.py` |
| `DOCPIPE_UPSTREAM_CACHE` | env var | `data/upstream` | Where `--refresh` caches what it pulls and writes the lock | `docpipe/upstream.py` |

## Failure modes

- An unreadable harvest line is logged and skipped, uncounted (see
  Method above for the `ValueError` an empty or fully gated harvest
  directory raises, and the CLI's exit 1).
- `kwp`: a gate failure, an unresolvable document identity, a second
  claimant of an already claimed identity, an unnamed sub area row and
  a value conflict are each dropped and counted by reason (see Method
  above), never merged or guessed at.
- `scenarios`: a document with no resolved title is skipped whole,
  logged at `INFO` (see Method above for the date, author and cross
  check handling). An unresolved scenario identity, an unplaceable row
  and an `out:`/`out_of_graph` answer are each dropped and counted,
  never written as a triple.
- A profile's predicate and class constants are read at module import
  time and raise `KeyError` rather than default, so a spec that stops
  backing a promised `kg` block fails the whole import before any
  document runs; a `TRUST_PROSE` table missing or adding a
  `trust.MARKS` mark raises `LookupError` the same way. `spec.py`
  itself refuses a `kg` block with the wrong class or predicate shape
  at load time, and `kg_name` raises `KeyError` for an unbound prefix.
- The ontology checks never raise, and exit 1 only if a problem exists
  (see Method above); `--write` without `--closure` returns exit code
  2, and `--check` against a missing `vocabulary.json` returns exit
  code 1. `--refresh` against a source that cannot be resolved, an
  unset token, no release yet, an unreachable host, prints
  `refresh failed: ...` and returns exit code 2 before rewriting
  anything.
- The SHACL check a `kwp` `--serialize` run makes never raises and
  never withholds the graph: a profile with no refreshed shapes only
  logs a warning naming the missing `--refresh`, and a graph the
  shapes reject is still written, with the violations in
  `<ttl>.shacl.txt` and the log.

## Measured behaviour

- Only the target scenario was ever written; the rest of what a
  harvest reads was collected, verified and dropped at the gate. On
  Kassel this dropped 45 tuples belonging to the non-target parts, 25
  of them a stock take WPG paragraph 15 requires, which is why all
  three parts are serialized today, not the target alone
  (`profiles/kwp/kg.py`, comment above `_PART_MINT`).
- Writing a value's area wording into its identity made 129 of 1,294
  value nodes over twenty plans into repeats of one fact under
  different wordings (`profiles/kwp/kg.py`, comment above
  `_value_iri`).
- Counting only the second claimant of a contested identity
  undercounted every conflict report by one: on Kassel the log said
  217 tuples lost where 317 were, across 100 identities
  (`profiles/kwp/kg.py`, comment in `serializer`).
- Three `kwp` edges once named a domain disjoint from every value
  node's class, making the graph unsatisfiable while every check then
  in place still passed (`docpipe/ontology.py`, `edge_problems`
  docstring).
- The checked-in `kwp` snapshot holds 352 terms, 6 sets and 11 disjoint
  pairs, pinned to OEO 2.13.0 and MHPO v0.1.0, against a spec naming 58
  identifiers;
  `scenarios`' holds 322 terms and 249 OEKG regions, same release,
  against a spec of 280 (inspected directly; `ontology.spec_terms`).
  `--refresh` pulls that same release straight from GitHub rather than
  by hand; neither number is pinned in a test any more, since both
  move the day upstream does.
- Over a corpus run the model answered `out:` 1,171 times for a
  wording its document scoped AR6 list could resolve unambiguously,
  347 a character for character match (`profiles/scenarios/kg.py`,
  `resolve_wording` docstring).
- Over a 164 document ar6 harvest, 298 of 11,129 scenario scope tuples
  had no scenario to attach a factsheet to: 289 `exhausted` (a window
  budget finding), 9 `unstated` (a finding about the paper), counted
  separately so the first does not hide the second
  (`profiles/scenarios/kg.py`, comment above `unplaceable`).

## Verification

- `test_value_minting_matches_the_schema_repo_reference`,
  `test_both_date_spellings_mint_the_same_iris`,
  `test_a_carrier_oeo_does_not_call_a_carrier_keeps_its_edge_and_is_counted`
  and `test_a_non_class_names_no_node_just_as_an_unstated_coordinate_does`:
  minting is a pure function of a value's coordinates; a
  `CARRIER_OUTSIDE_ROOT` carrier keeps its edge, counted, and an `out:`
  or unmapped carrier or sector never enters the identity.
  `test_the_gate_names_the_quantity_before_the_scenario` holds the
  quantity gate ahead of the scenario one.
- `test_every_plan_part_the_ontology_names_is_serialized` and
  `test_a_part_with_no_value_is_neither_a_node_nor_a_has_part_edge`: a
  part gets a node only when it has a value.
- `test_a_value_conflict_on_one_coordinate_drops_every_claimant`,
  `test_a_repeat_alone_still_serializes_one_node`,
  `test_a_rounded_reading_loses_to_the_precise_one`,
  `test_different_wordings_are_different_nodes_named_by_the_wording`,
  `test_a_lower_trust_grade_loses_the_identity` and
  `test_what_no_rule_settles_is_still_a_question_for_a_human`: an exact
  repeat is one node; different plan wording splits into a node each; a
  rounded reading loses to a precise one and a lower trust level to a
  higher one; what none of those settles still drops every claimant.
- `test_a_second_document_claiming_the_same_identity_is_refused` and
  `test_one_heat_plan_comes_out_as_the_published_example`: a stale
  duplicate is refused after the first claimant succeeds, and a full
  render matches the schema repository's reference exactly.
- `test_every_edge_the_writer_emits_is_one_the_ontology_was_asked_about`
  (`kwp`) and
  `test_the_writers_own_edges_are_declared_for_the_pin_to_judge`
  (`scenarios`): every triple shape a serializer writes is one
  `edge_problems` checks.
- `test_the_reading_the_most_sources_agree_on_wins`,
  `test_a_running_header_does_not_outvote_the_located_title_page` and
  `test_the_crawl_is_the_cross_check_not_the_source`: `_pick_one`'s
  ranking, including the substring guard, and a `DocumentMeta`
  disagreement logged, never substituted.
- `test_a_scenario_becomes_its_own_factsheet_hung_off_the_bundle` and
  `test_a_scenario_wording_that_fits_several_runs_links_to_none`: a
  resolved run mints its own factsheet; an ambiguous wording is
  refused as an identity and its rows merge by wording alone.
- `test_every_value_can_name_the_passage_it_came_from` and
  `test_the_evidence_can_be_switched_off_for_a_closed_shape_run`: with
  `OEKG_EVIDENCE` on, every value points at its evidence node; off, no
  `oekgprov:` triple appears.

## Modules

`docpipe/extraction/serialize.py` is the profile free core walking the
harvest and choosing a serializer (see Method above); called only from
`runner.py`'s `--serialize` branch. `docpipe/extraction/graph.py` is the
generic writer for a spec with a `graph` block, and
`docpipe/extraction/provenance.py` writes the provenance file; both are
chosen and called there too. `docpipe/extraction/graphkit.py` is what the
two profile writers and these two share: the UUIDv5 an IRI is minted from
(`base_namespace`, `mint_uuid`), the folding of a name to one spelling
(`normalise`, to which each writer passes its own list of legal forms, since a
shared list would mint every organisation of one corpus anew), the Turtle
helpers (`ttl_string`, `ttl_escape`, `ttl_literal`, `ttl_comment`, a comment
cut at 400 characters) and `NOT_IN_GRAPH`, the `out:` prefix of the choice
list entries that are answers and not things of the graph. Every IRI and every
byte of Turtle is what it was before the move, which two golden Turtle files
per profile hold. Its `validate` holds a written
graph against a profile's refreshed SHACL shapes and is the one place
this stage calls into the ontology tooling. `docpipe/ontology.py` is
the profile free snapshot builder and checker (see Method above),
providing the complaint functions both `vocabulary.py` modules compose
into their own `check`, plus `shacl_report`, `serialize.validate`'s own
call; it never imports a profile. `docpipe/upstream.py` is the
profile free source puller (see Method above): it resolves a
profile's `SOURCES` to a version, caches what it fetched, and writes
the lock both `vocabulary.py --refresh` and
`docpipe preflight` read back; it never imports a profile
either.

`profiles/kwp/kg.py` is the `kwp` MHPKG serializer (see Method above),
plus the `EDGES` table of triples behind no spec parameter; called
through `Profile.component('kg', 'make_serializer')`, and read for
`EDGES` alone by its own `vocabulary.py`'s `edges()`, which imports
`kg` directly. The same module carries the query half `kg_route.py`
calls when a graph is configured: `COORDINATE_AXES`, `VALUE_QUERY`,
`value_bindings`, `label_of`, `SPEC` and `heatplan_iri`, the function
locating a document's plan node. `profiles/scenarios/kg.py` is the
`scenarios` OEKG serializer (see Method above), plus `edges()`; called
the same way and imported directly by its own `vocabulary.py`; it
declares no `COORDINATE_AXES` or `VALUE_QUERY` (see Purpose). Each
profile's `vocabulary.py` is otherwise its half of the ontology
snapshot: which roots its lists draw from, its own extra check
(`carrier_problems`, `region_problems`), its own `SOURCES` declaring
what it is written against, and the `--refresh`/`--write`/`--check`
CLI; only `kwp`'s also names `shapes()`, read by a `--serialize` run.

`docpipe/extraction/spec.py` parses and validates
`extraction_spec.json` into typed `Spec`, `Parameter` and `Axis`
objects, including a `kg` block's shape; `kg_name` qualifies a
`{prefix, predicate}` block against a profile's header at import
time. `docpipe/extraction/trust.py` computes the trust verdict
for one tuple and renders it against a profile's `TRUST_PROSE` table.
`docpipe/extraction/fields.py`'s `DERIVED` state, imported only by
`profiles/kwp/kg.py`, marks a derived aggregation in its evidence
comment. `docpipe/extraction/runner.py`'s `--serialize` branch
resolves the profile and wires the harvest into `serialize.run` (see
Method above). `docpipe/profile.py`'s `Profile.component` lazily
imports a profile module and returns one attribute, or `None` for one
it lacks; used here to find `kg.make_serializer`, and by
`kg_route.py`'s `hooks()` to find a `kwp` profile's query pieces,
named above. `Profile.require` is a distinct method elsewhere that
raises `LookupError` instead of returning `None`; this stage never
calls it, since `scenarios` answers from no graph and a `require` here
would demand one of every profile (`kg_route.py` docstring). Neither
`vocabulary.py` module calls `Profile.component`: each imports its
sibling `kg.py` directly, inside its own `edges()`.

## Module reference

The docstring of each module of this stage, verbatim from the code and generated by `scripts/build_docs.py`. The chapter above is the account; this is the reference. Edit the docstring, not this page.

<details>
<summary><code>docpipe/extraction/serialize.py</code></summary>

serialize.py: Turns a document harvest into the profile's target graph.

The module walks the JSONL harvest directory and keeps only the rows
a run accepted (kind is "tuple"), grouped by document name (collect).
run() hands each document's rows to a serializer, and the runner's
--serialize flag chooses it: profiles/<name>/kg.py exposes
make_serializer(db_path) where the profile writes its graph itself,
and a profile without one gets the generic writer of graph.py, which
writes what the `graph` block of the spec describes. What a profile's
own serializer emits (Turtle with project IRI rules, LinkML YAML, or
another format) is the profile's decision; the module guarantees only
the walk, the per-document grouping, and that a refusal row never
reaches the serializer.

A serializer may leave, per document, which values it wrote
(`claims`). run() then hands them to the provenance writer it was
given (provenance.py), and the provenance of the written values goes
to a file of its own beside the graph.

What people decided about the rows of the harvest (gold.py) is read
here, after the harvest is, and kept beside the value each decision
concerns: the provenance writer records it with the value's provenance,
and a serializer that declares a `decisions` dict gets it as
{document: {tuple name: [decision]}} to write itself. No row changes and
none is left out because of it. A decision about a row the harvest does
not hold is counted and named in the log.

run() concatenates the output of every document whose serializer
returned something and writes it to the output path. It raises
ValueError and leaves that path untouched when no document produced
anything. The check runs unconditionally at the end of a GPU job, so
a run that ended in a counted exception still yields a graph; without
the check, an empty or unreadable harvest directory would overwrite a
valid graph from an earlier run with nothing.

Author: Felix Vossel

</details>

<details>
<summary><code>docpipe/extraction/graph.py</code></summary>

graph.py: Writes a harvest as the graph a compiled spec describes.

`docpipe compile` drafts a spec from the shapes of a graph, and with it
what each answer becomes there: the `graph` block names the nodes and how
they are linked, and every parameter's `kg` names the node and the property
its value is written to. That is everything a writer needs, so a project
whose spec was compiled needs no writer of its own. A profile that has one
(`kg.make_serializer`) keeps it: its graph knows things no shape says.

What is written, per document:

    a node per document   one of each node the block declares as
                          `per: document`, at <base><node>/<document name>,
                          once it carries something
    a property            the value of a parameter on its node: a literal
                          of the property's datatype, or the term chosen
                          from the parameter's list (`object: term`)
    a named thing         a node of its own for a value that names one
                          (`edge_from`), at <base><node>/<its wording>, with
                          that wording under the parameter's property, and
                          the edge to it
    a link                between two nodes that are both there

Three things are left out and counted in the log, none silently:

  * a parameter with coordinates. Where a year or a scenario of a value
    goes is not something the block says, and written onto the node without
    them two values of two years would be one property with two numbers.
  * a property that allows fewer values than the harvest has for it
    (`max`). The values of the best trust level are taken; if those are
    still too many, none is written, because picking one would be a guess.
    A value that is left out leaves no node of its own behind either.
  * an answer that is not a term where a term has to be written.

Author: Felix Vossel

</details>

<details>
<summary><code>docpipe/extraction/graphkit.py</code></summary>

graphkit.py: The small tools the graph writers share.

A profile's graph is written by its own `kg.py`, and by `graph.py` where the
spec says what the graph is. All of them build an identifier from a name,
fold a name to one spelling, write Turtle text and refuse the entries of a
choice list that are not a thing in the graph. That is here, once.

What stays with each writer is what only it decides: which coordinates make
an IRI, which reading of one value wins over another, which legal forms a
name loses, which rows reach the graph at all. A tool here takes what differs
as an argument and never as a default of its own.

Author: Felix Vossel

</details>

<details>
<summary><code>docpipe/extraction/provenance.py</code></summary>

provenance.py: Where every value of a graph comes from, as a graph.

A graph carries a number. That it was read on page 97, from which words,
by which run and how far the run stands behind it, the harvest knows and
the graph does not say. This module says it, in a file of its own beside
the graph (`<graph>.prov.ttl`), with PROV-O and the W3C Web Annotation
vocabulary and a small vocabulary for what those two do not have. Every
statement points at a value and none starts from one, so the graph itself
is the same with and without it, and a reader who does not want it leaves
the file away. A run that should not write it is started with
EXTRACT_PROVENANCE=0.

Per value:

    its reading       an oa:Annotation whose body is the value and whose
                      target is the part of the document it stands in: the
                      page (a fragment selector), refined by the quote and,
                      where the quote was located, by its rectangles
    each coordinate   an annotation of its own: what was read (the body),
                      the wording it was read from, how the reading ended,
                      and its own passage where it had one; generated by
                      the run, or by the pass (a top-up, with its own model
                      and time) the coordinate's `<axis>_producer` points at
    its trust         an assessment with the level, the reasons below A and
                      whether it was read from an image
    a second reading  what it came to, where one was made
    a decision        what a person decided about one of its fields, where
                      someone did: correct or wrong, who, when and the note.
                      Kept beside the value, which stays as it is

and once per document the run (a prov:Activity with its model and the
fingerprints of the spec and the prompts) and each part of the document
that is quoted.

The vocabulary's terms live where the writer says (`vocabulary`: a prefix
and an IRI). A graph that has an ontology for them names it; one that has
none gets them under its own base.

Not written yet: the decision between two readings that claim one value.
The writers settle that before a value reaches this module, and what lost
does not come with it. A decision of a person is not that: it is recorded
and judges nothing.

Author: Felix Vossel

</details>

<details>
<summary><code>docpipe/ontology.py</code></summary>

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
rdflib, so they run where rdflib is not installed.

Author: Felix Vossel

</details>

<details>
<summary><code>docpipe/upstream.py</code></summary>

upstream.py: Pulls the files a profile is written against, at the version
upstream currently calls its own.

A profile names its sources in `profiles/<name>/vocabulary.py: SOURCES`. This
module resolves each one to a version, downloads it into a cache keyed by that
version, and returns a record of what it got. What a file is for (a closure to
snapshot, shapes to validate against, regions to offer) is the profile's.

Four kinds:

  release_asset  An asset of the repository's latest GitHub release. A
                 repository without a release is an error, unless the source
                 says `until_released`: then it is skipped with a note.
  release_file   A file in the repository at the tag of its latest release,
                 for a project that attaches nothing to its releases. The
                 same rule for a repository without a release.
  repo_files     Files at the head of a branch. The version is a digest over
                 their bytes. A source may name the commit its profile was
                 `reviewed` against, and the record then lists every file that
                 differs from that commit.
  sparql         A query against the OEKG endpoint. The token comes from the
                 environment variable `token_env` names and is written nowhere.

Only github.com and raw.githubusercontent.com are asked, never
api.github.com: the API allows 60 unauthenticated requests an hour per
address, and every user of a shared machine shares one address.

Network access goes through urllib with the proxy settings the environment
already has. A source that cannot be fetched raises. A run against an old
ontology that believes it has the current one is what this module prevents.

Author: Felix Vossel

</details>

[Back to the index](../README.md)
