"""
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
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

SH = "http://www.w3.org/ns/shacl#"


@dataclass
class Property:
    path: str                           # the property's IRI
    datatype: Optional[str] = None      # IRI of an XSD type
    choices: list = field(default_factory=list)     # sh:in, as written
    choices_are_terms: bool = False     # IRIs, as opposed to literals
    classes: list = field(default_factory=list)     # sh:class, sh:or of them
    node: Optional[str] = None          # sh:node: the shape of the object
    min_count: Optional[int] = None
    max_count: Optional[int] = None
    name: Optional[str] = None          # sh:name
    description: Optional[str] = None   # sh:description
    notes: list = field(default_factory=list)


@dataclass
class Shape:
    iri: str                            # "" for a shape without a name
    name: str
    target_class: Optional[str] = None
    properties: list = field(default_factory=list)
    notes: list = field(default_factory=list)


def read(paths) -> tuple:
    """(shapes, {prefix: namespace}) of the files at *paths*."""
    from rdflib import Graph
    # Without rdflib's own prefixes: `dc:` is the file's to bind, and bound
    # twice it comes back as `dc1:`.
    graph = Graph(bind_namespaces="none")
    for path in paths:
        graph.parse(str(path))
    return shapes_of(graph), {
        prefix: str(namespace) for prefix, namespace in graph.namespaces()
        if prefix}


def shapes_of(graph) -> list:
    from rdflib import RDF, URIRef
    sh = _namespace()
    found = set(graph.subjects(RDF.type, sh.NodeShape))
    found |= set(graph.subjects(sh.targetClass, None))
    out = []
    for node in sorted(found, key=str):
        target = graph.value(node, sh.targetClass)
        iri = str(node) if isinstance(node, URIRef) else ""
        shape = Shape(iri=iri, name=_shape_name(iri, target),
                      target_class=str(target) if target is not None else None)
        if len(list(graph.objects(node, sh.targetClass))) > 1:
            shape.notes.append("more than one sh:targetClass; the first in "
                               "the file's order is taken")
        for constraint in graph.objects(node, sh.property):
            read_one = _property(graph, constraint)
            if isinstance(read_one, str):
                shape.notes.append(read_one)
            else:
                shape.properties.append(read_one)
        shape.properties.sort(key=lambda p: p.path)
        out.append(shape)
    return out


def _namespace():
    from rdflib import Namespace
    return Namespace(SH)


def _shape_name(iri: str, target) -> str:
    """What a node of this shape is called in a spec: the shape's own name
    without the word Shape, else the end of its target class."""
    text = iri or (str(target) if target is not None else "node")
    local = text.rsplit("/", 1)[-1].rsplit("#", 1)[-1]
    for ending in ("NodeShape", "Shape"):
        if local.endswith(ending) and len(local) > len(ending):
            local = local[:-len(ending)]
    out = []
    for i, char in enumerate(local):
        if char.isupper() and i and (local[i - 1].islower()
                                     or local[i - 1].isdigit()):
            out.append("_")
        out.append(char.lower() if char.isalnum() else "_")
    return "".join(out).strip("_") or "node"


def _members(graph, head) -> list:
    from rdflib.collection import Collection
    return list(Collection(graph, head))


def _count(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _property(graph, constraint):
    """A Property, or one line that says why this one was not read."""
    from rdflib import Literal, URIRef
    sh = _namespace()
    path = graph.value(constraint, sh.path)
    if not isinstance(path, URIRef):
        return ("a property shape whose sh:path is no single property was "
                "not read")
    out = Property(path=str(path))
    datatype = graph.value(constraint, sh.datatype)
    if datatype is not None:
        out.datatype = str(datatype)
    listed = graph.value(constraint, sh["in"])
    if listed is not None:
        members = _members(graph, listed)
        out.choices_are_terms = bool(members) and all(
            isinstance(member, URIRef) for member in members)
        if members and not out.choices_are_terms and not all(
                isinstance(member, Literal) for member in members):
            out.notes.append("sh:in mixes terms and literals; read as "
                             "literals")
        out.choices = [str(member) for member in members]
    for klass in graph.objects(constraint, sh["class"]):
        out.classes.append(str(klass))
    for alternatives in graph.objects(constraint, sh["or"]):
        for alternative in _members(graph, alternatives):
            classes = list(graph.objects(alternative, sh["class"]))
            if classes:
                out.classes.extend(str(klass) for klass in classes)
            else:
                out.notes.append("an sh:or alternative that names no "
                                 "sh:class was not read")
    out.classes = sorted(set(out.classes))
    node = graph.value(constraint, sh.node)
    if node is not None:
        out.node = str(node)
    out.min_count = _count(graph.value(constraint, sh.minCount))
    out.max_count = _count(graph.value(constraint, sh.maxCount))
    name = graph.value(constraint, sh.name)
    out.name = str(name) if name is not None else None
    description = graph.value(constraint, sh.description)
    out.description = str(description) if description is not None else None
    for predicate, what in ((sh.sparql, "an sh:sparql constraint"),
                            (sh.pattern, "an sh:pattern"),
                            (sh.hasValue, "an sh:hasValue")):
        if graph.value(constraint, predicate) is not None:
            out.notes.append(f"{what} is stated and not carried into the "
                             f"spec")
    return out
