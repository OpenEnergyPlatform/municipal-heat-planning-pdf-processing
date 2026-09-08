# 8. The knowledge graph

| | |
|---|---|
| **In** | The accepted-tuple rows of the JSONL harvest under the extraction stage's `out` directory, the corpus SQLite `Documents`/`DocumentMeta`/`Municipalities` tables, and the profile's `extraction_spec.json` `kg` blocks. |
| **Out** | One Turtle file per `--serialize` call (one shared prefix header, one block per document), written by `docpipe.extraction.serialize.run` through the profile's `kg.make_serializer`. |
| **Resumes on** | No stamps: every `--serialize` call re-walks the whole harvest directory and re-renders the whole output file, so redoing the work is only running the command again; `run()` refuses to write at all when nothing in the harvest serializes, so a bad or empty harvest cannot truncate a good file already on disk. |

This stage is the last hop from a harvested, evidence-checked value to an actual graph. It takes the tuples that survived extraction's verification and trust scoring (stage 7) and writes them as RDF, in the vocabulary and IRI scheme of the Municipal Heat Planning Knowledge Graph, so a heat plan's numbers sit next to OEO and MHPO classes instead of a private schema only this repository understands. Two pieces do the writing and one keeps them honest. `docpipe/extraction/serialize.py` is the profile-free core: it only knows how to walk a harvest directory, group its accepted tuples by document, hand each document to a serializer the profile supplies, and refuse to overwrite a good file with an empty one. `profiles/kwp/kg.py` is that serializer for the kwp corpus (the scenarios profile has its own): it owns the IRI minting policy, the predicate table, and which of a document's tuples the target-scenario schema can actually hold. `docpipe/ontology.py` is neither reader nor writer of this graph. It is the check that a `kg` block's chosen predicate, domain, and range are things the pinned OEO/MHPO ontology actually says, so the Turtle kg.py writes is not just well-formed but consistent with the ontology it claims to extend.

Concretely, `make_serializer(db_path)` closes over two inputs. The JSONL harvest, one file per document, whose lines `serialize.collect()` filters to `kind == "tuple"` -- refusals never reach this file, by serialize.py's own guarantee, so kg.py never has to re-derive what was already accepted. And the corpus SQLite database, opened read-only once per document (`_document_identity`) for `Documents.published` and, via `DocumentMeta`/`Municipalities`, the document's `municipality_ags` and place name -- the two coordinates every minted IRI is keyed on. It also reads the profile's `extraction_spec.json` once at import, for every parameter's `kg` block: which predicate an axis becomes, which class a parameter's node is, which scenario key maps to which MHPO container. The output is a single Turtle file written by `serialize.run(jsonl_dir, out_path, serializer)`, invoked as `python -m docpipe.extraction <db> <index> <out> --serialize <ttl path> --profile kwp` (see `runner.py`'s `--serialize` branch, which returns before any model or GPU setup runs) -- the FAISS index positional is still required by the parser, but nothing here reads it.

The first decision a newcomer would get wrong is where the provenance goes. Every value node carries the wording it was read as, its quote, its page, and a computed A/B/C trust level -- but all of it as a Turtle comment above the node, never as an extra triple hanging off it. That is because the target-scenario schema's SHACL shapes are `sh:closed`: a triple this serializer did not anticipate does not warn, it invalidates the shape outright. A reification or a `prov`-style edge would fail exactly the same way, so the evidence a person needs to trust or challenge a number lives in the file next to it, not in the graph a query engine walks.

The second is which predicate the carrier, sector, and year axes use, and it is not what the class names would suggest. All three are `obo:IAO_0000136 is about`, a bare annotation with no declared range, rather than a domain-specific relation. The domain-specific one used to be `covers energy carrier`, and that predicate's OEO domain is `study`, an occurrent, while every value node this graph mints is a continuant. OEO asserts occurrent and continuant disjoint, so those triples did not just say the wrong thing, they made the whole graph unsatisfiable, and nothing already in place had caught it: checking that the predicate exists, and that it is a property, both still passed. `ontology.edge_problems` is built for exactly this gap -- it asks whether an emitted triple's subject is under the predicate's declared domain, or disjoint from it -- and it runs against the same `EDGES` list kg.py assembles from its own predicate constants, so the shapes checked cannot silently drift from the shapes actually written. Nine carrier classes the plans name constantly (district heat, electricity, solar thermal, the ambient heat sources) sit outside OEO's `energy carrier` root for real ontological reasons and are declared as such in the spec's `kg.outside_root` rather than discovered by a mis-mapping: before that list existed, the model had mapped 36 such readings onto solar thermal energy, a wrong triple rather than a missing one.

The third is what happens when two accepted tuples land on the same value identity. A value's IRI is a UUIDv5 minted from its full coordinate -- plan, quantity class, carrier, sector, year, aggregation, and, only where the scope is a named sub-area, the area itself, left out of the whole-plan-scope identity on purpose so one fact does not split into as many nodes as the document has words for the place. Two tuples at that identity with the same magnitude are one honest repeat and are counted as `duplicate`, not silently merged into it. Two tuples at that identity with different magnitudes are a disagreement no serializer should referee: both are dropped, loudly, and counted as `conflict` on both sides -- an earlier version of this code counted only the second claimant, so it logged 217 tuples lost on the Kassel corpus where 317 were actually lost, across 100 identities. A named sub-area with no name at all is dropped rather than silently merging two areas into one node, for the same reason. One document identity is claimed once, too: the first document to serialize an `(ags, published)` pair wins its IRI namespace, and a later document claiming the same pair -- a stale duplicate harvest left behind by, say, a register-link rename -- is refused whole and logged as an error, rather than having its numbers merged onto the first one's nodes.

None of this needs a GPU, a model, or the network. It is a read-only SQLite connection and a walk over local JSONL and Turtle text, and `--recheck`, `--remap`, and `--serialize` all return before the harvest loop's model and GPU setup runs, for exactly that reason. Its one hard dependency is the document's own metadata: a `Documents` row without a digit-only `municipality_ags` or an ISO `published` date makes `_document_identity` return `None`, and that drops the whole document's tuples, logged once as a warning, never partially -- there is no such thing as a heat-plan node with half its identity. The ontology check itself (`edge_problems`, `term_problems`, `kind_problems`) does not run inside `--serialize` at all. It runs from the profile's own vocabulary module against a JSON snapshot built and pinned ahead of time, reading kg.py's `EDGES` list, so a wrong domain is caught before a corpus run rather than by inspecting the Turtle afterward.

There is no incremental state to this stage the way the harvest upstream has resume stamps. `serialize.run()` re-reads the entire harvest directory and re-renders the entire output file on every call, so redoing the work is simply running `--serialize` again. The one thing it refuses to do is write nothing: if every document in the harvest directory comes back with no accepted, serializable tuple -- an empty or unreadable `out` directory, say -- it raises a `ValueError` instead of truncating `out_path`, specifically because this call is made unconditionally at the end of a GPU job, and a bad run must never be allowed to erase the last good graph already on disk.

## The modules

Verbatim from the module docstrings, generated by `scripts/build_docs.py`. Edit the docstring, not this page.

### `docpipe/extraction/serialize.py`

serialize.py – From harvested tuples to the profile's target graph.

The core walks the JSONL harvest and hands each document's accepted tuples to
a serializer the profile provides (profiles/<name>/kg.py exposes
make_serializer(db_path), the runner's --serialize calls it). What a
serializer emits — TTL with project IRI rules, LinkML YAML, anything — is
entirely its business; the core only guarantees the walk, the grouping and
that refusal rows never reach it.

Author: Felix Vossel

### `docpipe/ontology.py`

ontology.py – The ontology a spec is written against, read once and pinned.

Every closed list a profile offers names terms of an ontology, and a spec that
cannot be checked against one drifts into describing a graph nobody has. This
reads an ontology file and writes a snapshot: per term its label, its foreign
alternative labels, its definition, its parents, whether it is deprecated, and
WHAT KIND of thing it is — a class, an individual or a property. Plus the sets
a list may draw from, and the pin (version IRI and the file's own sha256), so
"which ontology is this spec written against" has an answer.

Profile-free by design. What a profile keeps is its own: which roots its sets
draw from, where its closure lives, and the rules that are about its own axes.
The builder, the index, the identifier walk and the two generic complaints
("the ontology does not have this" and "the ontology deprecated this") are the
same question in every profile and live here.

The kind matters more than it looks. A `kg` block names PREDICATES, and a
predicate is an owl:ObjectProperty; an index over classes and individuals
alone reports every one of them as missing. That is why the scenarios profile
had no snapshot: its seventeen identifiers are mostly predicates.

rdflib is imported inside the functions that need it. The check runs against
the checked-in snapshot and needs no ontology file and no rdflib, which is
what lets it run on the cluster.

Author: Felix Vossel

[Back to the index](../README.md)
