"""
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
"""
from __future__ import annotations

import logging
import re
from collections import Counter
from typing import Callable, Optional
from urllib.parse import quote

from . import identity, trust

log = logging.getLogger(__name__)

RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
XSD = "http://www.w3.org/2001/XMLSchema#"
WELL_KNOWN = {"xsd": XSD,
              "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
              "rdfs": "http://www.w3.org/2000/01/rdf-schema#"}
WHOLE = {"integer", "int", "long", "short", "nonNegativeInteger",
         "positiveInteger", "gYear"}
_RANK = {trust.LEVEL_A: 0, trust.LEVEL_B: 1, trust.LEVEL_C: 2}
_IRI = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://[^\s<>\"{}|\\^`]+$")


class GraphError(ValueError):
    """A spec that does not describe a graph this writer can write."""


def ttl_string(text) -> str:
    """A text as a Turtle string literal, quotes included."""
    escaped = (str(text).replace("\\", "\\\\").replace('"', '\\"')
               .replace("\n", "\\n").replace("\r", "\\r")
               .replace("\t", "\\t"))
    return f'"{escaped}"'


def slug(text) -> str:
    """What a wording becomes in an IRI: the same for the same name written
    with other spacing or capitals."""
    return re.sub(r"[^\w]+", "-", " ".join(str(text).split()).casefold(),
                  flags=re.UNICODE).strip("-")


class Names:
    """Prefixed names and IRIs of one spec, as IRIs."""

    def __init__(self, prefixes: dict):
        self.prefixes = {**WELL_KNOWN, **(prefixes or {})}

    def iri(self, name) -> Optional[str]:
        """The IRI a prefixed name or an IRI stands for, or None."""
        name = str(name or "")
        if _IRI.match(name):
            return name
        prefix, colon, rest = name.partition(":")
        if colon and prefix in self.prefixes and rest \
                and not rest.startswith("//"):
            return self.prefixes[prefix] + rest
        return None

    def predicate(self, described: dict) -> Optional[str]:
        prefix = described.get("prefix")
        name = described.get("predicate")
        if not name:
            return None
        if prefix:
            base = self.prefixes.get(prefix)
            return base + name if base else None
        return self.iri(name)


def _check(raw: dict) -> tuple:
    graph = raw.get("graph")
    if not isinstance(graph, dict):
        raise GraphError(
            "the spec has no `graph` block: it does not say what an answer "
            "becomes in a graph. `docpipe compile spec` drafts one from "
            "shapes; a profile can instead bring its own writer "
            "(kg.make_serializer).")
    base = str(graph.get("base") or "")
    if not _IRI.match(base) or base[-1] not in "/#":
        raise GraphError(f"graph.base is {base!r}: it must be an IRI that "
                         f"ends in / or #")
    if "example.org" in base or "example.com" in base:
        raise GraphError(f"graph.base is still a placeholder ({base}): say "
                         f"where the nodes of this graph live")
    names = Names(graph.get("prefixes") or {})
    nodes = graph.get("nodes") or {}
    if not isinstance(nodes, dict) or not nodes:
        raise GraphError("graph.nodes names no node")
    classes = {}
    for name, node in nodes.items():
        klass = names.iri((node or {}).get("class"))
        if klass is None:
            raise GraphError(f"graph.nodes.{name}.class is "
                             f"{(node or {}).get('class')!r}: not an IRI, "
                             f"and not a name with a prefix the block "
                             f"declares")
        if node.get("per") not in ("document", "value"):
            raise GraphError(f"graph.nodes.{name}.per must be document or "
                             f"value")
        classes[name] = klass
    links = []
    for position, link in enumerate(graph.get("links") or []):
        predicate = names.predicate(link)
        if link.get("from") not in nodes or link.get("to") not in nodes \
                or predicate is None:
            raise GraphError(f"graph.links[{position}] needs two declared "
                             f"nodes and a predicate with a declared prefix")
        links.append((link["from"], predicate, link["to"]))
    return base, names, nodes, classes, links


def make_serializer(raw: dict) -> Callable:
    """(document name, accepted rows) -> Turtle or None, for a spec with a
    `graph` block. Raises GraphError when the block cannot be written
    from."""
    base, names, nodes, classes, links = _check(raw)
    plans: dict = {}
    for position, parameter in enumerate(raw.get("parameters") or []):
        kg = parameter.get("kg")
        uri = parameter.get("uri")
        if not isinstance(kg, dict):
            continue
        where = f"parameters[{position}] ({uri})"
        if kg.get("node") not in nodes:
            raise GraphError(f"{where}: kg.node {kg.get('node')!r} is not "
                             f"a node of the graph block")
        predicate = names.predicate(kg.get("property") or {})
        if predicate is None:
            raise GraphError(f"{where}: kg.property needs a predicate with "
                             f"a declared prefix")
        edge = None
        if kg.get("edge_from"):
            edge_predicate = names.predicate(kg["edge_from"])
            if kg["edge_from"].get("node") not in nodes \
                    or edge_predicate is None:
                raise GraphError(f"{where}: kg.edge_from needs a declared "
                                 f"node and a predicate with a declared "
                                 f"prefix")
            if nodes[kg["edge_from"]["node"]]["per"] != "document":
                raise GraphError(f"{where}: kg.edge_from.node must be a "
                                 f"node there is one of per document")
            edge = (kg["edge_from"]["node"], edge_predicate)
        elif nodes[kg["node"]]["per"] != "document":
            raise GraphError(f"{where}: node {kg['node']!r} is one per "
                             f"value, and only `edge_from` says which value "
                             f"names it")
        datatype = (kg.get("property") or {}).get("datatype")
        datatype_iri = names.iri(datatype) if datatype else None
        if datatype and datatype_iri is None:
            raise GraphError(f"{where}: datatype {datatype!r} has no "
                             f"declared prefix")
        plans[uri] = {
            "node": kg["node"], "predicate": predicate, "edge": edge,
            "datatype": datatype_iri, "object": kg.get("object"),
            "max": kg.get("max"), "axes": bool(parameter.get("axes")),
            "numeric": parameter.get("value_type") in ("float", "int"),
        }
    header_pending = [True]
    labelled: set = set()

    def node_iri(node: str, key: str) -> str:
        return f"{base}{node}/{quote(key, safe='')}"

    def literal(plan: dict, row: dict) -> str:
        content = row.get("value")
        if plan["numeric"] and row.get("value_target") is not None:
            content = row["value_target"]
        datatype = plan["datatype"]
        if datatype is None:
            if isinstance(content, bool):
                return f'"{str(content).lower()}"^^<{XSD}boolean>'
            if isinstance(content, int):
                return f'"{content}"^^<{XSD}integer>'
            if isinstance(content, float):
                return f'"{content!r}"^^<{XSD}double>'
            return ttl_string(content)
        if isinstance(content, float) and datatype.startswith(XSD) \
                and datatype[len(XSD):] in WHOLE and content.is_integer():
            content = int(content)
        lexical = repr(content) if isinstance(content, float) else content
        return f"{ttl_string(lexical)}^^<{datatype}>"

    def serializer(name: str, rows: list):
        skipped: Counter = Counter()
        document_key = name
        claims: list = []
        # node name -> its triples (predicate, object as Turtle); a node is
        # written once something stands on it
        on_node: dict = {}
        things: dict = {}       # entity IRI -> (class, property, name)
        by_parameter: dict = {}
        tuple_names = identity.tuple_ids(name, rows)
        for tuple_name, row in zip(tuple_names, rows):
            plan = plans.get(row.get("parameter"))
            if plan is None:
                skipped["not_in_graph"] += 1
            elif plan["axes"]:
                skipped[f"coordinates:{row.get('parameter')}"] += 1
            else:
                by_parameter.setdefault(row["parameter"], []).append(
                    (tuple_name, row))
        for uri, entries in by_parameter.items():
            plan = plans[uri]
            written: dict = {}      # object as Turtle -> entries saying it
            named: dict = {}        # object as Turtle -> (entity IRI, name)
            for tuple_name, row in entries:
                if plan["edge"] is not None:
                    key = slug(row.get("value"))
                    if not key:
                        skipped[f"unnamed:{uri}"] += 1
                        continue
                    thing = node_iri(plan["node"], key)
                    said = f"<{thing}>"
                    named.setdefault(said, (thing,
                                            str(row["value"]).strip()))
                elif plan["object"] == "term":
                    term = names.iri(row.get("value"))
                    if term is None:
                        skipped[f"not_a_term:{uri}"] += 1
                        continue
                    said = f"<{term}>"
                else:
                    said = literal(plan, row)
                written.setdefault(said, []).append((tuple_name, row))
            limit = plan["max"]
            if isinstance(limit, int) and len(written) > limit:
                # The best trust level any claimant of an object has is the
                # object's. Only the objects of the best level stay; if
                # they are still too many, nothing decides between them.
                level = {said: min(_RANK[trust.trust(row)["level"]]
                                   for _name, row in claimants)
                         for said, claimants in written.items()}
                best = min(level.values())
                kept = {said: claimants for said, claimants
                        in written.items() if level[said] == best}
                lost = sum(len(claimants) for said, claimants
                           in written.items() if said not in kept)
                if len(kept) > limit:
                    skipped[f"contested:{uri}"] += sum(
                        len(claimants) for claimants in written.values())
                    continue
                skipped[f"outranked:{uri}"] += lost
                written = kept
            # An entity is written for an object that is: a value the limit
            # took out leaves no node behind. Its name goes under the
            # property the parameter names.
            for said in written:
                if said in named:
                    thing, label = named[said]
                    things.setdefault(thing, (classes[plan["node"]],
                                              plan["predicate"], label))
            subject_node = plan["edge"][0] if plan["edge"] else plan["node"]
            predicate = plan["edge"][1] if plan["edge"] else plan["predicate"]
            subject = node_iri(subject_node, document_key)
            for said, claimants in written.items():
                on_node.setdefault(subject_node, set()).add((predicate, said))
                for tuple_name, row in claimants:
                    claims.append({
                        "about": f"{base}statement/{quote(name, safe='')}/"
                                 f"{tuple_name}",
                        "statement": (subject, predicate, said),
                        "row": row, "id": tuple_name, "bodies": {}})
        if not on_node:
            if skipped:
                log.info("graph: %s: nothing written (left out: %s)", name,
                         dict(skipped))
            return None
        # A node that only links to a node that is there is there too:
        # without it the link has no start.
        present = set(on_node)
        changed = True
        while changed:
            changed = False
            for start, _predicate, end in links:
                if end in present and start not in present \
                        and nodes[start]["per"] == "document":
                    present.add(start)
                    changed = True
        for start, predicate, end in links:
            if start in present and end in present \
                    and nodes[end]["per"] == "document":
                on_node.setdefault(start, set()).add(
                    (predicate, f"<{node_iri(end, document_key)}>"))
        parts = []
        for node in nodes:
            if node not in present or nodes[node]["per"] != "document":
                continue
            lines = [f"<{node_iri(node, document_key)}>",
                     f"    <{RDF_TYPE}> <{classes[node]}>"]
            lines += [f"    ; <{predicate}> {said}"
                      for predicate, said in sorted(on_node.get(node, ()))]
            parts.append("\n".join(lines) + " .\n")
        for thing, (klass, property_iri, label) in sorted(things.items()):
            if thing in labelled:
                continue                # one node, one name: the first
            labelled.add(thing)
            parts.append(f"<{thing}>\n    <{RDF_TYPE}> <{klass}>\n"
                         f"    ; <{property_iri}> {ttl_string(label)} .\n")
        if skipped:
            log.info("graph: %s: %d statement(s) written, left out: %s",
                     name, len(claims), dict(skipped))
        document_nodes = [node_iri(node, document_key) for node in nodes
                          if node in present
                          and nodes[node]["per"] == "document"]
        serializer.claims[name] = {"document": document_nodes[0],
                                   "values": claims}
        if header_pending[0]:
            header_pending[0] = False
            parts.insert(0, f"# written by docpipe from the graph block of "
                            f"its spec; base {base}\n")
        return "\n".join(parts)

    serializer.claims = {}
    serializer.base = base
    serializer.provenance = (raw.get("graph") or {}).get("provenance")
    return serializer
