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
while `profiles/<name>/kg.py` alone decides IRI minting, node shape
and predicate choice. `kwp`'s Turtle file is read back by
`docpipe/inference/kg_route.py` when
`scripts/inference_app` has a graph configured; `scenarios`' `kg.py`
declares no `COORDINATE_AXES` or `VALUE_QUERY`, so its file has no
reader here.

A second, unrelated tool lives here: `docpipe/ontology.py`, with
`profiles/<name>/vocabulary.py`, reads an external OEO closure file,
writes a checked-in JSON snapshot of the terms a profile's
`extraction_spec.json` may reference, and checks the spec's `kg`
blocks and a serializer's declared edges against it. It is not invoked
by `--serialize` and produces no graph, auditing the spec ahead of a
corpus run rather than inspecting Turtle afterward. The two tools do
not call each other: `vocabulary.py`'s `edges()` imports the profile's
`kg.py` module directly to read its `EDGES` table, and that import
alone runs `kg.py`'s own module level calls to `spec.py`'s
`kg_name` and `load` and `trust.py`'s `check_prose`, a side effect
rather than a call the ontology check makes itself.

## Position in the pipeline

| | |
|---|---|
| **In** | A document's accepted JSONL tuple lines (`kind == "tuple"`), the profile's SQLite corpus database, and its `extraction_spec.json` `kg` blocks, parsed once at import. |
| **Out** | One Turtle file per `--serialize` call: a shared prefix header plus one block per document that produced anything (`kwp`'s read back by `kg_route.py`; `scenarios`' by nothing here). |
| **Resumes on** | Nothing. Every call re walks the harvest and re renders the whole output; a run's dedupe state (which identities are claimed) is never persisted. |
| **Needs** | No served model and no GPU: a read only SQLite connection and local text; the ontology check also needs `rdflib` and an external OEO closure file, only for `--write`. |

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
docpipe.extraction`, resolves the profile, requires
`profiles/<name>/kg.py` to export `make_serializer`, and logs and exits
1 on that `ValueError`:

```bash
python -m docpipe.extraction <db> <index> <out> \
    --serialize <ttl path> --profile kwp
```

The `index` positional is still required by the parser, though this
branch returns before it is touched.

### kwp: gating, identity and rendering the plan

`profiles/kwp/kg.py`'s `serializer` pulls `planning_organisation` rows
into a normalised `offices` dict; every other row passes a gate:
`scenario` a key of `PARTS` (`status_quo`, `trend`, `target`),
`spatial_scope` `municipality` or a named `sub_area`, `year` an `int`,
`quantity` a class in `UNIT_TARGET`, `aggregation` present and known. A
row failing any gate is dropped and counted by reason.
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
nodes. Two rows minting one IRI with the same target are a repeat,
counted `duplicate`; with different targets they disagree, both
dropped, and every later claimant too, counted twice per pair as
`conflict`. The plan node gets `has part` edges only to parts with a
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
`scenario_label`/`scenario_region`/`scenario_type` row, into
`out_of_graph`, logged but never written. For fields the OEKG shapes
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
rendered trust line follows it.

### Checking a spec against the ontology

`ontology.read` parses OWL or Turtle into an `rdflib` graph; `index`
walks every labelled class, individual and property into a per
identifier record (kind, label, `alt_labels`, definition, parents,
deprecated, and, for a property, its domain and range); `alt_labels`
holds the term's German alternative spellings, checked by
`foreign_labels` below. `closures` computes, per declared root, every
class under it or individual it types. `build` grows a profile's
closures plus its spec's identifiers to a fixpoint over parents,
domains and ranges, and writes a pin recording the ontology's version
IRI, each file's sha256, and which identifier families the files
cover. `vocabulary.py --write` calls this with an external `--closure`
file (plus, for `kwp`, `--mhpo`) and overwrites `vocabulary.json`.
`--check` runs `term_problems` (name absent or deprecated),
`kind_problems` (a `kg` predicate the ontology calls a class),
`edge_problems` (a triple outside its predicate's domain or range),
`set_problems` (an axis option outside its root), plus `kwp`'s
`carrier_problems` or `scenarios`' `region_problems`; each a string,
never an exception, and the CLI exits 1 if any exist. Both CLIs then
print `foreign_labels`' notes, one line per corpus label whose first
spelling is not the term's own, and both end on a summary line naming
identifiers checked, problems found, and such labels noted. Only
`scenarios`' `--check` also prints `uncovered` notes, for a family no
parsed file covers.

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
terms, disjoint}`, plus `regions` for `scenarios`. A declared edge, the
unit `edge_problems` checks, is `{where, subject, predicate,
object|datatype, accepted}`: `accepted` lets a serializer name why a
triple contradicts the pinned domain, for example `scenarios`' `has
uuid` on a bundle, though domained on report or factsheet alone.

Every value's trust verdict, `{level, reasons, image_origin,
corroborated}`, is rendered into one line by a profile's own
`TRUST_PROSE` table, written as the last comment above the value's
node, in English for both `kwp` and `scenarios`. The level is a floor,
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
| `--profile NAME` | CLI flag | `$DOCPIPE_PROFILE` | Selects which `kg.py` and spec the run uses | `docpipe/profile.py` |
| `DOCPIPE_PROFILE` | environment variable | unset | Default for `--profile` | `docpipe/profile.py` |
| `OEKG_ID_BASE` | env var, `scenarios` only | `https://openenergyplatform.org/ontology/oekg/` | Overrides the IRI prefix every node and namespace uses | `profiles/scenarios/kg.py` |
| `OEKG_EVIDENCE` | env var, `scenarios` only, truthy unless `"0"` | off | Links each passage as an `oekgprov:` node, not a comment; provisional under `sh:closed` OEKG shapes | `profiles/scenarios/kg.py` |
| `--closure PATH` | flag, `vocabulary.py --write` | required with `--write` | OEO closure file `rdflib` parses; not vendored here | both `vocabulary.py` |
| `--mhpo PATH` | flag, `kwp` `--write` only | none | Extra MHPO ontology file parsed into the same graph | `profiles/kwp/vocabulary.py` |
| `--write` | CLI flag | off | Rebuilds and overwrites `vocabulary.json` | both `vocabulary.py` |
| `--check` | CLI flag | off; also runs without `--write` | Holds the spec against the snapshot; exits 1 on any problem | both `vocabulary.py` |

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
  code 1.

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
- The checked-in `kwp` snapshot holds 335 terms, 6 sets and 10 disjoint
  pairs, pinned to OEO 2.13.0, against a spec naming 58 identifiers;
  `scenarios`' holds 53 terms and 249 OEKG regions, same release,
  against a spec of 32 (inspected directly; `ontology.spec_terms`).
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
  `test_both_date_spellings_mint_the_same_iris` and
  `test_a_carrier_oeo_does_not_call_a_carrier_keeps_its_edge_and_is_counted`:
  minting is a pure function of a value's coordinates; a
  `CARRIER_OUTSIDE_ROOT` carrier keeps its edge, counted.
- `test_every_plan_part_the_ontology_names_is_serialized` and
  `test_a_part_with_no_value_is_neither_a_node_nor_a_has_part_edge`: a
  part gets a node only when it has a value.
- `test_a_value_conflict_on_one_coordinate_drops_every_claimant` and
  `test_a_repeat_alone_still_serializes_one_node`: a disagreement drops
  both claimants; an exact repeat, one node, no conflict.
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
`runner.py`'s `--serialize` branch. `docpipe/ontology.py` is the
profile free snapshot builder and checker (see Method above),
providing the complaint functions both `vocabulary.py` modules compose
into their own `check`; it never imports a profile.

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
(`carrier_problems`, `region_problems`), and the `--write`/`--check`
CLI, never called from a `--serialize` run.

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
