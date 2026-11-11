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
the file walk and that a refusal line never reaches a serializer, and
one program, `docpipe/extraction/graph.py`, writes every profile's graph
from a drawing: the `map` part of the profile's `graph.json`, which says
which node each field becomes, which property each value is written
under and which brick turns a reading into the object of a triple. What a
profile needs beyond the core's bricks is code in its `kg.py`
(`BRICKS`), and nothing else about its graph. `kwp`'s Turtle
file is read back by `docpipe/inference/kg_route.py` when the chat
(`docpipe/app`) has a graph configured; `scenarios`' `kg.py`
declares no `COORDINATE_AXES` or `VALUE_QUERY`, so its file has no
reader here. Beside the graph a run also writes where each value comes from,
as a second file (see The provenance file under Method).

A second, unrelated tool lives here: `docpipe/ontology.py`, with
`profiles/<name>/vocabulary.py` and `docpipe/upstream.py`, writes a
checked-in JSON snapshot of the terms a profile's
`extraction_spec.json` and its drawing may reference, and checks the
drawing's terms and the triple shapes its arrows write against it. `upstream.py`
pulls a profile's declared sources (`sources.json`), the OEO closure among them, at
whichever version upstream currently calls its own; `vocabulary.py`
no longer needs a closure file handed to it by hand. Auditing the spec
stays ahead of a corpus run rather than inspecting Turtle afterward,
with one exception: where a profile's `vocabulary.shapes()` names
SHACL files pulled by the last refresh, `--serialize` holds the
written graph against them and logs a report, never a gate on the
write. The gate is a step of its own, before a corpus run
(`docpipe.extraction.gate`, below). The two tools otherwise do
not call each other: `vocabulary.py`'s `edges()` reads the profile's
drawing (`graphfile.load`) and hands it to `ontology.drawing_edges`, which
derives every triple shape the arrows write, and its `check` hands the
drawing to `ontology.drawing_term_problems`; a profile's `kg.py` is
imported only for what the check asks of it (`has_property`, the
container classes of `kwp`).

## Position in the pipeline

| | |
|---|---|
| **In** | A document's accepted JSONL tuple lines (`kind == "tuple"`), the profile's SQLite corpus database, its `extraction_spec.json` (the fields the drawing reads) and the drawing in its `graph.json`. |
| **Out** | One Turtle file per `--serialize` call: a shared prefix header plus one block per document that produced anything (`kwp`'s read back by `kg_route.py`; `scenarios`' by nothing here), and beside it the provenance file `<graph>.prov.ttl`. `kwp` also writes `<graph>.strict.ttl`, the values the MHPKG data schema takes (see below). |
| **Resumes on** | Nothing. Every call re walks the harvest and re renders the whole output; a run's dedupe state (which identities are claimed) is never persisted. |
| **Needs** | No served model and no GPU: a read only SQLite connection and local text; the ontology check also needs `rdflib`. `vocabulary.py --refresh` needs network access to pull the sources of `sources.json`, and, for `scenarios`, `OEP_API_TOKEN`; `--write` needs an external OEO closure file by hand instead. The SHACL report a `--serialize` run writes, and the gate, need `pyshacl`. |

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
docpipe.extraction` (`docpipe extract`), resolves the profile, builds the
writer from the drawing of its graph file (`graph.make_serializer`; a graph
file without a drawing stops the run with the reason), and logs and exits 1 on
that `ValueError`:

```bash
python -m docpipe.extraction <db> <index> <out> \
    --serialize <ttl path> --profile kwp
```

The `index` positional is still required by the parser, though this
branch returns before it is touched.

### The writer and its drawing

`docpipe/extraction/graph.py` writes every profile's graph from a drawing, the
`map` part of `<profile folder>/graph.json`, and from nothing else: no profile
has a writer of its own. The Graph tab of `docpipe edit` draws it (see
[the editor](editor.md)); `docpipe/graphfile.py` loads it and checks its shape
(`map_problem`: every key known, every box named once, every arrow from a field
or a box to a box, with a property), and `graph.check` holds what it names to
the spec, the shapes and the bricks. A spec no longer says what a field becomes
in the graph: `docpipe/extraction/spec.py` refuses a `kg` block and points to the
drawing.

| Part of `map` | What it says |
|---|---|
| `prefixes`, `prefix_width`, `legal_forms` | the Turtle header, and the legal forms a name is folded without |
| `document` | `facts` (a brick that looks up what is known of the document beyond its harvest), `admit` (conditions a row must meet to be taken at all), `check` (diagnostics over what was chosen), `front_pages` (the field whose readings find the title pages), `claims` (what the provenance file records), `decisions` (people's decisions are kept beside the values), `strict` (the profile also writes a strict graph) |
| `evidence` | how a passage is shown above a triple: the `prose` of a trust line, the `join`, the `nodes` an evidence node is addressed with |
| `boxes` | a class of the graph: `class`, `count`, `address`, `written`, `required`, `once`, `same_node`, `uuid`, `evidence`, `admit`, `table` and the keys a count asks for (below) |
| `arrows` | from a field, a fact or a box to a box: `property`, `brick` with `settings`, `objects`, `evidence`, `pick`, `first_in_file`, `when`, `note`, `label`, `accepted` |

The order of the boxes is the order of the nodes in the graph, and the order of
the arrows the order of the properties on a node. A box's `count` says how many
nodes it has in a document: `per_document` (one), `per_name` (one for each
name a brick finds in the readings of the box's fields), `per_distinct` (one for
each distinct reading of a field), `per_answer` (one for each entry of a table of
answers a coordinate was read as), `per_value` (one for each number, addressed
by a brick), `per_object` (one for each object another arrow wrote). `address`
says how a node is named: a fixed name made of facts, or a folder and a key
over the fields (or `@name`, `@key`) the UUID is minted from. `required` leaves
a document out of the graph whole where the box has no node, `once` writes a
node once per file, `same_node` says what happens where a second document mints
the same node (`warn` or `refuse` the document), and `uuid` writes the node's
address as a property of its own.

An arrow is kept by where it starts. From a field it writes what the field
reads, as a literal or, with `brick: entry` or `answer_class`, as a term of the
field's or the coordinate's list. From a box to itself it writes what a brick
knows of the node (`template`, `fact`, `fixed`). From a box to another it
links the nodes that share a row, or every node of the other box where either is
one per document, if the other box is `written` and its `when` holds. `pick:
one_reading` writes one reading where the shapes allow one, `first_in_file`
keeps the first value a file gave a property for the later documents
(`keep_first`) or leaves a later, different one out (`skip_other`), `objects:
joined` writes a node's values as one object list, and `evidence` puts the
passages above the triple.

A brick is code that takes one kind of thing and gives one kind back, with a
sentence saying what it does (`docpipe/extraction/bricks.py`; a profile's own in
`profiles/<name>/kg.py`, `BRICKS`). The kinds are `object` (on an arrow),
`condition` (admits or holds back a row, with the reason it was held back),
`facts`, `nodes`, `address`, `class`, `evidence`, `name`, `check` and `claims`
(on a box or the document). A name that no brick has, or a brick of another
kind, is a problem the check lists. Bricks of the core: `text`, `node_name`,
`year_to_datetime`, `entry`, `fixed`, `template`, `fact`, `decimal`,
`whole_number`, `answer_class` (`out:total` becomes the class set for a figure
without the breakdown, an answer outside the list writes nothing and a class the
property's range does not cover is counted under `outside_root`),
`kept_coordinates`, `answer_is`, `has_words`, `named`, `trimmed`,
`without_legal_form`.

What the writer does for every drawing, with the rules of the graph file
(`docpipe/extraction/readings.py`): it takes the one reading the most sources
agree on where the shapes allow one, and the front pages first for the fields of
the rule `front_first_fields`; it settles the numbers of one address (the same
number twice is one node, different numbers under different wording are nodes
of their own, a reading within `rounding_tolerance` of a more precise one loses
to it, a lower trust level to a higher, and what stays open is a node marked
contested in the full graph, `contested_in_full`, and left out of the strict
one); and it writes every triple's passages as comment lines above it, or as
evidence nodes with the rule `evidence_as`. A row an `admit` condition holds
back and a count a brick makes are summed per document and logged, none silently.
The full and the strict graph are one drawing: where the document asks for
`strict`, the writer runs a second time with a condition or a requirement that
holds only for the strict graph (`graph: strict` on a reference, a box's
`strict: {"requires": [...]}`).

A project that has a spec and shapes starts from a draft: `docpipe compile`
writes a drawing beside the spec (`compile apply --out` writes a `graph.json` next
to it where there is none), with a box for each shape and an arrow from each
field to the box and property of its shape, that its author completes in the
Graph tab (see [compile](./compile.md)).

### The graph file

`<profile folder>/graph.json` (`docpipe/graphfile.py`) says what the writer does
with a harvest: the drawing of how the harvest becomes a graph (`map`, above),
the rules of the writer and what is done to the written graph; what a brick does
stays code (`bricks.py`, `profiles/<name>/kg.py`). The default profile's
`graph.json` sets nothing; a profile writes only what it sets.

| Key | What it says |
|---|---|
| `classes` | per class `{"written": false}` (its nodes and every triple that names them leave the graph) or `{"address": {"folder", "key", "base"}}` (the nodes are named anew: the folder under the base and a UUID over the values of the key properties) |
| `constraints` | per `"<constraint> <property> <class>"` an effect: `report` (the default), `leave_out_value`, `leave_out_paper` or `stop` |
| `map` | the drawing (above): prefixes, document, evidence, boxes and arrows; checked by `map_problem` on every load and save |
| `rules` | writer rules the profile's `rules.py: GRAPH` declares: kwp `base`, `rounding_tolerance`, `contested_in_full`; scenarios `base`, `scenario_types_always`, `evidence_as`, `front_first_fields` |

`serialize.apply_graph_file` runs after the graph is written, by `--serialize`
and by the gate. The gate shuts for a constraint whose effect is `stop`. With
nothing set the graph is byte-identical to one written without the file.
`DOCPIPE_GRAPH_FILE` lays a file over every profile's. A setting of a graph
rule (`OEKG_ID_BASE` for `base`, `OEKG_EVIDENCE` for `evidence_as`) wins over
the files, applied by `graphfile.load` as for the rules of `docpipe.rules`
(`Rule.env`); the Graph tab shows it as in effect. The Graph tab of
`docpipe edit` edits the file (see [the editor](editor.md)).

The file's effects reach the other outputs beside the graph. The provenance
file follows it (`graphfile.finish`, its `follow` argument, which
`apply_graph_file` fills with `<graph>.prov.ttl`): a node named anew is named
anew there, a node left out takes every triple that names it. The OEKG dry run
of `scenarios` follows it too (see [the scenarios profile](../profiles/scenarios.md)).

The arrows write every predicate of a graph, a value under a further predicate
included: a second arrow from the same field to the box of the property's class.
No pass after the writer adds triples. The Sources tab of the editor, where it
merges a property of the shapes into a field, draws that arrow (see
[the editor](editor.md)).

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
writes one (kwp) a decision is a node of its own,
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

### kwp: the drawing of the plan

`profiles/kwp/graph.json` draws a plan node (class MHPO heat plan, named from
the plan's AGS and publication date), one node per plan part the document's
values are read in (inventory analysis, trend scenario, target scenario, from a
table of answers of the `scenario` coordinate, each with its class, folder and
label), one node per number, one per planning office, one per named sub area and
the municipality. The plan reaches its parts and offices, a part its numbers, a
sub area its municipality.

`plan_register` looks the plan up in the register (`document_identity`,
`facts_of`): its AGS and its publication date, from `Documents` and
`DocumentMeta`/`Municipalities`. A document whose AGS or date does not parse is
logged once and written for nothing. Another document claiming the same plan
node is refused whole, the box saying `same_node: refuse`, rather than merged
onto it.

The numbers are the box `value`, one node per number. Its `admit` list is the
gate, in order, each brick naming its reason: `quantity_listed` (the quantity is
a class, else counted `not_a_class:<quantity>`; first, so such a row never
reaches the scenario check), `part_known` (the scenario is an answer of the table
of parts), `scope_listed` (`municipality`, a named `sub_area` or not read),
`sub_area_named`, `year_read` (an `int`), `unit_listed` (a numeric row
without `value_target` is counted `unit_unlisted:<unit_raw>`),
`unit_in_ontology` (`unit_not_in_ontology:<target>`, for example an emission
factor in g CO2/kWh, a unit OEO 2.14 lacks) and `aggregation_listed` (where an
aggregation was read, it is known). A value without an aggregation is written
without that edge, and one without a spatial scope is kept in the full graph;
the strict graph refuses it (owner decision 2026-11-07: no more than the
ontology and the graph schema demand). A row failing a gate is counted by
reason in the log, never silently; a plan with no number left is written for
nothing (`required`).

`value_identity` mints a number's IRI as a UUIDv5 over its part, quantity,
carrier, sector, year and aggregation, plus the area wording for a named sub
area only, so several wordings of one fact do not split into separate nodes, and
the technology only where one was read, so a value without one keeps the IRI
it had before the dimension existed. A carrier or sector enters the IRI only
where it is a real OEO class: a deliberate `out:` answer or an unmapped wording
is left out exactly like an absent one, so the identity matches what gets an
edge. The box's `settle` setting lists the words that tell two numbers of one
address apart (`subject`, `whole`, `carrier_raw`, `sector_raw`; no column head,
owner decision 2026-11-07). The writer settles every reading of one address
together (see above): the same number twice is one node, counted `duplicate`
and marked `corroborated` only where a second passage prints it (one passage
read twice is one statement, whatever its quotes, owner decision 2026-11-05);
different numbers under different wording split into a node per wording,
counted `split:wording`; a reading within the rule `rounding_tolerance` (2%) of
another loses to the more precise one, `conflict:rounding`; the lower trust
level (`A` best, `D` worst) loses to the higher, `conflict:trust`; what none of
those settles stays in the full graph as a node per number, marked contested and
counted `conflict:open`, and stays out of the strict graph, counted
`conflict`. Each winner's comment states what it won over.

`value_class` writes a number as its quantity's OEO class, in the strict graph
also as the schema's class above it. The arrows write the number as `xsd:float`,
the unit (`value_unit`, the unit the number was converted onto), the carrier,
sector, technology and aggregation (`answer_class`) and the year (`xsd:integer`,
`whole_number`, no year node). The carrier, sector and technology edges are the
MHPKG schema's slots (`refers to energy carrier`, `refers to sector`, `refers to
technology`, resolved by `profiles/kwp/mhpkg.py`). A total sector (`out:total`)
is written as the schema's parent sector `OEO_00000128`, a total carrier or
technology as no edge. A class outside the schema stays in the full graph. Nine
carrier classes plans name constantly sit outside OEO's `energy carrier` root;
the carrier arrow's `outside_root` setting keeps their edge, counted. An office
is one node per distinct spelling of the plan's office without its legal form
(`without_legal_form`), written once per file with the first spelling in
harvest order, so a later plan does not give it a second `rdfs:label`; a row
whose `role` is `municipality` mints no office and links the plan to the
municipality node (MHPKG: a municipality acting as planning authority is not a
second entity). A named sub area is linked `part of` the municipality.
Above each number `value_passage` writes its wording, quote (for a number read
off a figure, the reading in its place), location and the trust line as Turtle
comments, since the target shapes are `sh:closed` with no triples toggle. The
inventory part's IRI folder is `inventoryanalysis`.

The document asks for `strict`: `<graph>.strict.ttl` is written from the same
drawing beside the full one, with `schema_admits` as one more condition (a value
class its part holds, every required slot, every carrier, sector and technology
on the schema's lists; each refusal counted `mhpkg:<reason>`: `class`, `area`,
`no_slot:<slot>`, `missing:<slot>`, `off_list:<slot>`) and a plan with no
target-scenario number left out whole (`part` requires `target`). The full graph
keeps everything read. Both files are held against the refreshed shapes.

### kwp: asking the graph

`COORDINATE_AXES` lists what a query can fix, in spec order:
`scenario`, `quantity`, `carrier`, `sector`, `year`; `spatial_scope`
and `aggregation`, both part of a value's identity, are left out: no
edge links a value to its area, and aggregation is returned rather
than constrained. `VALUE_QUERY`, a SPARQL template built from the
serializer's predicate constants, selects a value's quantity, number,
unit, year, aggregation (optional in the query) and plan part, gathering every carrier, sector
and technology object into one `abouts` string. `value_bindings` turns a
coordinate dict into `##CONSTRAINTS##` lines and a `{variable: (kind,
value)}` binding map, one line per bound axis, dropping an `out:`
quantity, since `oeo:out:share` names no graph IRI. `label_of`
picks the label a reader sees: the spec's first spelling where named,
else the pinned vocabulary's label, else the identifier itself.

### scenarios: the drawing of the study

`profiles/scenarios/graph.json` draws one study report, one bundle, a factsheet
for each scenario, one node for each distinct author, organisation and funder,
and the nodes the other arrows point at (the study regions, the tags and the
scenario types, as terms of their lists).

The document admits a row only where `kept_coordinates` finds every dimension
with an entry it must have read as that entry (a value of another work, or one
whose work entry stayed open, stays in the harvest and out of the graph), and
`crawl_crosscheck` logs, never gates, where the chosen title, date or DOI
differs from the crawl's record of the document (`DocumentMeta`). The report is
`required`: a document with no `publication_title` is written for nothing; a
missing date or author is only logged. For the fields the OEKG shapes allow
at most once the arrows say `pick: one_reading` (`readings.pick_one`: the reading
most sources agree on, a tie to the one located on its page, then to the
longer; a reading contained in another never wins) and the rest are counted
contested. The fields in the graph file's rule `front_first_fields` are read on
the front pages first, then the catalogue's record, then anywhere.

Every scenario scope row belongs to the scenarios its name means
(`scenario_names`, the `names` of the box `scenario`): `value_means` for a
`scenario_label` row, `scenario_means` for any other, written while the document
was read (`addressed.Reader.name_of`, the `names` request), else the scenario of
its own name as the publication prints it; the words of several scenarios stand
for each of its member scenarios; a name absent from its own quoted passage
mints nothing. A row whose scenario never resolves reaches no triple, comment
or number; it is counted `unplaceable`, keyed by state, since without it the gap
read as zero.

The study report's IRI is minted from the title, the bundle's from
`study_project_name` or else the title; a second document reusing either IRI is
logged (`same_node: warn`), not refused, its triples landing on the shared
subject. The bundle takes one triple for each tag entry the model picked off
the shapes' lists (the arrows with the brick `entry`), and none for an `out:`
entry or an unmapped wording, which are counted. One factsheet is minted for each
scenario: `rdfs:label` and `dc:acronym` are the name the scenario is called by
(`node_name`, `short_name`), each factsheet carrying the fixed type
`OEO_00020517` (rule `scenario_types_always`, the brick `fixed`) beside the types
read. The `region` brick writes a matched study region as its existing OEKG
IRI, never minted, a group answer as its members, and a region the list does not
carry as a node of its own with the printed name; a name the graph points at gets
its label from the last refresh (`known_name`). Authors, organisations and funders
are one node per distinct name folded to one spelling, each keeping every
reading of it in its evidence; the authors are those the front pages name, else
those looked up in the catalogue, else those read anywhere
(`profiles/scenarios/front.py`). Evidence for a triple is a flattened comment,
or, with the graph rule `evidence_as` set to `node` (or `OEKG_EVIDENCE` on), a
linked `oekgprov:ExtractionEvidence` node; either way the rendered trust line
follows it. `profiles/scenarios/kg.py`'s `make_study_reader` hands the same
document, read by the same writer, as plain data to
`profiles/scenarios/oekg_api.py`, a dry run of the OEKG scenario-bundle API
that sends nothing, described on [the scenarios profile](../profiles/scenarios.md).

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
cover. It also carries every term the drawing names (`drawing`) and what a
profile's own edges name (`also`, which `kwp` fills from
`vocabulary.edge_terms`): `edge_problems` asks
whether a subject is under a predicate's domain, and a class the
snapshot lacks has no parents to answer with. `vocabulary.py --write`
calls this with an external `--closure`
file (plus, for `kwp`, `--mhpo`) and overwrites `vocabulary.json`;
`--refresh` does the same pull automatically, through `upstream.py`
(below), and then runs `--check` on what it wrote. `--check` runs
`term_problems` and `drawing_term_problems` (a name of the spec or of the
drawing absent or deprecated),
`kind_problems` (the property of an arrow that the ontology calls a class),
`edge_problems` (a triple shape the arrows write, `drawing_edges`, outside its
predicate's domain or range),
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

`docpipe/upstream.py` resolves each of a profile's sources (`sources.json`) to a
version and caches it under `data/upstream/<source>/<version>/`: a
`release_asset` is an asset of the repository's latest GitHub release,
found from the redirect `github.com/<repo>/releases/latest` gives,
never the GitHub API; a `release_file` is a file in the repository at
that release's tag, for a project that attaches nothing to its
releases; a `repo_files` source is files at a branch
head, versioned by a digest over their bytes and, where the source
names a `reviewed` commit, compared against it so a schema `kg.py`
mirrors by hand is named the moment it moves; a `repo_tree` source is
every file under some folders at a branch head, taken from the branch's
archive on github.com (`tree_members` refuses a member that would land
outside its folder), for a tree no file list can name without the API; a
`sparql` source
queries the OEKG endpoint with a token read from the environment
variable it names and written nowhere. `kwp` reads MHPO's `mhpo.owl`
as `repo_files` at the head of `develop`, where the team builds it from
its edit file, and OEO at its latest release, whose closure is reasoned:
OEO's development state is Manchester sources whose class hierarchy only a
reasoner completes, and read without one 5 of the release's 126 energy
carriers stay carriers (owner decision 2026-11-03).
`write_lock` records every
source's result in `data/upstream/<profile>.lock.json`.

`vocabulary.py --refresh` pulls the sources of `sources.json`, rebuilds `vocabulary.json`
from what came back, writes the lock, then runs `--check` against the
fresh snapshot; a source that cannot be resolved raises and stops the
refresh before anything is rewritten. `kwp`'s `mhpkg` source also
carries the MHPKG SHACL files: `vocabulary.py`'s `shapes()` names the
last refresh's copies, and `--serialize` holds the written Turtle
(the strict one too) against them through `serialize.validate`, which calls
`ontology.shacl_report` (with what the profile's `vocabulary.context()`
pulled of the target graph about the nodes the graph only references) and
writes `<ttl>.shacl.txt` beside each graph,
a report and not a gate, and `<ttl>.shacl.json`, the same violations
counted by kind (constraint, path, collection). `scenarios`' refresh pulls
the OEKG shapes (`oekg_shapes`, `oekg/shapes/oekg_shapes.ttl` at the head
of `production`) the same way, and its `shapes()` names them. Its `kg.py`
is written to them: `bind` reads, through
`docpipe/extraction/shapemodel.py`, which properties a report, a bundle
and a factsheet have, which occur once and which must occur, and refuses
with `SchemaError` a shapes file that no longer has a path it writes
([../profiles/scenarios.md](../profiles/scenarios.md)). `shapemodel.Model`
answers by path, by the class at a property's end, by the entries of its
`sh:in` list or by its datatype, holds a class no shape targets to the
nearest one above it, and treats no answer and two answers alike as an
error. The same refresh also pulls the schema's LinkML
file into `profiles/kwp/mhpkg_schema.yaml`, which `kg.py` takes its slots,
classes and closed lists from; the vocabulary check prints `note mhpkg:` for
schema terms the pinned OEO or MHPO lack and for schema edges the pinned
domains or ranges contradict, and fails on neither.

## Data model

The harvest tuple row this area reads carries the resolved value and
unit, each axis coordinate with its own `_state`/`_source` pair, a
`tier`, `quote`, `compute` and `flags`, and a `provenance` block; the
full field list is at [contract/kwp.md](../contract/kwp.md) and
[contract/scenarios.md](../contract/scenarios.md).

The node kinds each file carries, one per document, are described
above under Method: for `kwp`, plan, part, value, year, organisation,
sub area and municipality; for `scenarios`, report, bundle, factsheet,
author, organisation and funder, plus, only where `evidence_as` is `node`,
one evidence node per cited passage. Both carry a single `@prefix`
header, emitted once per run.

The ontology snapshot both profiles check against is `{pin, sets,
terms, disjoint}`, plus `regions` for `scenarios`; `pin` carries
`sources`, one version per entry of `sources.json`, once a snapshot has
come from `--refresh`. A declared edge, the
unit `edge_problems` checks, is `{where, subject, predicate,
object|datatype, accepted}`: `accepted` lets a serializer name why a
triple contradicts the pinned domain or range, for example `scenarios`' `has
uuid` on a bundle, though domained on report or factsheet alone, or
`kwp`'s publication date on the plan, a slot the MHPKG schema
prescribes with range `date` where OEO says `xsd:dateTime`.

Every value's trust verdict, `{level, reasons, image_origin,
corroborated}`, is rendered into one line by the
`evidence.prose` of the profile's drawing (kwp's brick `value_passage` takes it from its box), written as the last comment above the value's
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
| `db` (positional) | required argument | none | SQLite path the writer reads the register and the crawl from (`graph.make_serializer`) | `runner.py` |
| `out` (positional) | required argument | none | Harvest directory `serialize.collect` walks | `runner.py` |
| `--serialize TTL` | CLI flag | none | Switches to serialize only mode, writing the graph here | `runner.py` |
| `--no-provenance`, `EXTRACT_PROVENANCE` | CLI flag, env var | provenance written (`1`) | With `--serialize`: leave out the provenance file beside the graph | `runner.py` |
| `--profile NAME` | CLI flag | `$DOCPIPE_PROFILE` | Selects which graph file, `kg.py` and spec the run uses | `docpipe/profile.py` |
| `DOCPIPE_PROFILE` | environment variable | unset | Default for `--profile` | `docpipe/profile.py` |
| `OEKG_ID_BASE` | env var, `scenarios` only | unset: the graph rule `base` of the profile's `graph.json` | Overrides the IRI prefix every node and namespace uses; wins over the file (`graphfile.load`) | `docpipe/graphfile.py`, `profiles/scenarios/kg.py` |
| `OEKG_EVIDENCE` | env var, `scenarios` only, a flag (1 = node, 0 = comment) | unset: the graph rule `evidence_as` of `graph.json` (`comment`) | Links each passage as an `oekgprov:` node, not a comment; provisional under `sh:closed` OEKG shapes; wins over the file (`graphfile.load`) | `docpipe/graphfile.py`, `profiles/scenarios/kg.py` |
| `--refresh` | CLI flag | off | Pulls the sources of `sources.json` at their current version, rebuilds the snapshot and the lock, then runs `--check` | both `vocabulary.py` |
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
- A profile's `kg.py` reads the drawing at import time (`graphfile.get_map`)
  and raises `KeyError` rather than default for a box or an arrow it needs
  that the drawing no longer has, so a drawing that stops backing it fails
  the whole import before any document runs; an `evidence.prose` missing or
  adding a `trust.MARKS` mark raises `LookupError` the same way. A drawing
  the program cannot write from is a `GraphError` that names the entry, a
  graph file without a drawing stops `--serialize` with the reason, and
  `spec.py` refuses a `kg` block in a spec and points to the drawing.
- The ontology checks never raise, and exit 1 only if a problem exists
  (see Method above); `--write` without `--closure` returns exit code
  2, and `--check` against a missing `vocabulary.json` returns exit
  code 1. `--refresh` against a source that cannot be resolved, an
  unset token, no release yet, an unreachable host, prints
  `refresh failed: ...` and returns exit code 2 before rewriting
  anything.
- The SHACL check a `--serialize` run makes never raises and
  never withholds the graph: a profile with no refreshed shapes only
  logs a warning naming the missing `--refresh`, and a graph the
  shapes reject is still written, with the violations in
  `<ttl>.shacl.txt`, `<ttl>.shacl.json` and the log.
- `python -m docpipe.extraction.gate HARVEST DB TTL --against
  REPORT.shacl.json` is the gate. It writes the graph of the harvest that
  is already there, with the code and the shapes a run will use, and exits
  3 when the serializer does not build, no document reaches the graph, the
  Turtle does not parse, there are no shapes, the validator does not run,
  or a kind of violation appears that the report of the last written
  graph did not have. Counts are not compared, since they move with the
  harvest. Without an earlier report it stays open and says so. A job
  runs it before it starts its model.

## Measured behaviour

- Only the target scenario was ever written; the rest of what a
  harvest reads was collected, verified and dropped at the gate. On
  Kassel this dropped 45 tuples belonging to the non-target parts, 25
  of them a stock take WPG paragraph 15 requires, which is why all
  three parts are serialized today, not the target alone
  (`profiles/kwp/graph.json`, the box `part`).
- Writing a value's area wording into its identity made 129 of 1,294
  value nodes over twenty plans into repeats of one fact under
  different wordings (`profiles/kwp/kg.py`, `_identity`).
- Counting only the second claimant of a contested identity
  undercounted every conflict report by one: on Kassel the log said
  217 tuples lost where 317 were, across 100 identities.
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
  by hand; both numbers move the day upstream does.
- Over one 164 document harvest, 298 of 11,129 scenario scope tuples
  had no scenario to attach a factsheet to: 289 `exhausted` (a window
  budget finding), 9 `unstated` (a finding about the paper), counted
  separately so the first does not hide the second (`unplaceable`,
  `docpipe/extraction/graph.py`).

## Modules

`docpipe/extraction/serialize.py` is the profile free core walking the
harvest and choosing a serializer (see Method above); called only from
`runner.py`'s `--serialize` branch. `docpipe/extraction/graph.py` is the
program that writes every profile's graph from its drawing,
`docpipe/extraction/bricks.py` the core's bricks,
`docpipe/extraction/readings.py` the rules for which reading a node takes,
and `docpipe/extraction/provenance.py` writes the provenance file; all are
chosen and called there too. `docpipe/extraction/graphkit.py` is what the
writer and the provenance file share: the UUIDv5 an IRI is minted from
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
profile's sources to a version, caches what it fetched, and writes
the lock both `vocabulary.py --refresh` and
`docpipe preflight` read back; it never imports a profile
either.

`profiles/kwp/kg.py` holds what only the `kwp` drawing needs: its bricks
(`BRICKS`: the register lookup, the gates of a number, its identity, class,
unit, passage and provenance claims), `context`, `has_property` and the
schema helpers. The same module carries the query half `kg_route.py`
calls when a graph is configured: `COORDINATE_AXES`, `VALUE_QUERY`,
`value_bindings`, `label_of`, `SPEC` and `heatplan_iri`, the function
locating a document's plan node; the predicates `VALUE_QUERY` is built from are
read from the drawing. `profiles/scenarios/kg.py` holds the scenarios bricks
(scenario names, short name, region, known name, crawl cross-check) and
`make_study_reader`, which hands the same writer's decisions to the API dry run;
it declares no `COORDINATE_AXES` or `VALUE_QUERY` (see Purpose). Each
profile's `vocabulary.py` is otherwise its half of the ontology
snapshot: which roots its lists draw from, its own extra check
(`carrier_problems`, `region_problems`), its own `sources.json` declaring
what it is written against, and the `--refresh`/`--write`/`--check`
CLI; only `kwp`'s also names `shapes()`, read by a `--serialize` run.

`docpipe/extraction/spec.py` parses and validates
`extraction_spec.json` into typed `Spec`, `Parameter` and `Axis`
objects, and refuses a `kg` block, since what a field becomes in the graph is
drawn in the graph file. `docpipe/graphfile.py` loads the drawing and holds
its shape (`map`, `map_problem`, `get_map`).
`docpipe/extraction/trust.py` computes the trust verdict
for one tuple and renders it against the words of a profile's drawing (`evidence.prose`).
`docpipe/extraction/fields.py`'s `DERIVED` state, imported only by
`profiles/kwp/kg.py`, marks a derived aggregation in its evidence
comment. `docpipe/extraction/runner.py`'s `--serialize` branch
resolves the profile and wires the harvest into `serialize.run` (see
Method above). `docpipe/profile.py`'s `Profile.component` lazily
imports a profile module and returns one attribute, or `None` for one
it lacks; used here to find a profile's bricks (`kg.BRICKS`) and context, and by
`kg_route.py`'s `hooks()` to find a `kwp` profile's query pieces,
named above. `Profile.require` is a distinct method elsewhere that
raises `LookupError` instead of returning `None`; this stage never
calls it, since `scenarios` answers from no graph and a `require` here
would demand one of every profile (`kg_route.py` docstring).

## Module reference

The docstring of each module of this stage, verbatim from the code and generated by `scripts/build_docs.py`. The chapter above is the account; this is the reference. Edit the docstring, not this page.

<details>
<summary><code>docpipe/extraction/serialize.py</code></summary>

serialize.py: Turns a document harvest into the profile's target graph.

The module walks the JSONL harvest directory and keeps only the rows
a run accepted (kind is "tuple"), grouped by document name (collect).
run() hands each document's rows to a serializer: the one writer of
graph.py (`graph.make_serializer`), which writes what the drawing of
the profile's graph file (`map` in graph.json) draws, with the bricks
of the profile. The module guarantees only the walk, the per-document
grouping, and that a refusal row never reaches the serializer.

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

graph.py: Writes a harvest as the graph the drawing of its profile says.

How the harvest becomes the graph is a drawing in the profile's graph file
(`map` in graph.json, `docpipe.graphfile`), drawn in the Graph tab of
`docpipe edit`. This program writes the graph from that drawing alone,
without a model and without a new harvest:

    a box       a class of the graph; how many nodes it has in a document
                (one per document, per name, per distinct reading, per
                answer of a table, per number, per object another arrow
                wrote) and how a node's address is made
    an arrow    from a field or a coordinate of the harvest to a property
                of a box, from a box to itself (what a brick knows of the
                node), or from a box to a box over a property
    a brick     on an arrow or a box: the code that turns a reading into
                the object of a triple (`bricks.py`, and a profile's own in
                `profiles/<name>/kg.py`)

What the program does for every drawing, with the rules of the graph file
it reads (`readings.py`): one reading where the drawing says the shapes
allow one (rule `front_first_fields` for the fields a publication states on
its front pages), the numbers of one address settled (`rounding_tolerance`,
`contested_in_full`), the first value a file gives a property of a node
kept for later documents, and every triple's passages as comment lines
above it or as evidence nodes (`evidence_as`). The full and the strict
graph are one drawing: a condition or a requirement marked `strict` holds
only for the strict one.

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

The kind recorded for each term matters beyond bookkeeping. The arrows
of a drawing name predicates, and a predicate is an owl:ObjectProperty; an
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

A profile names its sources in `profiles/<name>/sources.json` (`docpipe.sources`). This
module resolves each one to a version, downloads it into a cache keyed by that
version, and returns a record of what it got. What a file is for (a closure to
snapshot, shapes to validate against, regions to offer) is the profile's.

Six kinds:

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
  repo_tree      Every file under some folders at the head of a branch, taken
                 from the branch's archive, for a tree a profile cannot name
                 file by file without the API. The version is a digest over
                 the files taken.
  sparql         A query against the OEKG endpoint. The token comes from the
                 environment variable `token_env` names and is written nowhere.
  url            One file at a fixed address, for a publisher that is not a
                 repository. Fetched again on every refresh; the version is a
                 digest over its bytes.

Of GitHub, only github.com (which redirects an archive to
codeload.github.com) and raw.githubusercontent.com are asked, never
api.github.com: the API allows 60 unauthenticated requests an hour per
address, and every user of a shared machine shares one address.

Network access goes through urllib with the proxy settings the environment
already has. A source that cannot be fetched raises. A run against an old
ontology that believes it has the current one is what this module prevents.

Author: Felix Vossel

</details>

[Back to the index](../README.md)
