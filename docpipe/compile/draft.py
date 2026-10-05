"""
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

The same reading, held against a spec somebody wrote by hand, gives the
differences: a list entry the shapes have and the spec lacks, a property
nobody asks for, a parameter the shapes do not know. That is a report and
changes nothing.

Author: Felix Vossel
"""
from __future__ import annotations

import copy
import re
import unicodedata
from typing import Optional

from ..extraction import spec as spec_module
from .shapes import Property, Shape
from .terms import Terms

XSD = "http://www.w3.org/2001/XMLSchema#"
RDFS_LABEL = "http://www.w3.org/2000/01/rdf-schema#label"
NUMBERS = {"decimal": "float", "float": "float", "double": "float",
           "integer": "int", "int": "int", "long": "int", "short": "int",
           "nonNegativeInteger": "int", "positiveInteger": "int"}
# Where the nodes of a drafted graph live until the author says where.
PLACEHOLDER_BASE = "https://example.org/id/"
MIN_DESCRIPTION_WORDS = 8       # what spec.load holds a description to
PARAMETER_QUESTION = "Which of the listed fields does this value state?"


def local(iri: str) -> str:
    return str(iri).rsplit("/", 1)[-1].rsplit("#", 1)[-1]


def slug(text: str) -> str:
    plain = unicodedata.normalize("NFKD", str(text))
    plain = "".join(char for char in plain if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "_", plain.lower()).strip("_")


class Names:
    """IRIs as the spec writes them: a prefix of the file and a local name."""

    def __init__(self, prefixes: dict):
        self.prefixes = dict(prefixes)
        self.used: dict = {}

    def split(self, iri: str) -> tuple:
        """(prefix, local name). A namespace no prefix is bound to gets one."""
        best = None
        for prefix, namespace in self.prefixes.items():
            if iri.startswith(namespace) and (
                    best is None or len(namespace) > len(best[1])):
                rest = iri[len(namespace):]
                if rest and re.fullmatch(r"[\w.-]+", rest):
                    best = (prefix, namespace)
        if best is None:
            cut = max(iri.rfind("/"), iri.rfind("#")) + 1
            namespace = iri[:cut]
            number = 1
            while f"ns{number}" in self.prefixes:
                number += 1
            best = (f"ns{number}", namespace)
            self.prefixes[best[0]] = namespace
        self.used[best[0]] = best[1]
        return best[0], iri[len(best[1]):]

    def curie(self, iri: str) -> str:
        prefix, name = self.split(iri)
        return f"{prefix}:{name}"


def _label_of(prop: Property, terms: Terms) -> tuple:
    """(label, whether anybody but the identifier said it)."""
    said = prop.name or terms.label(prop.path)
    return (said, True) if said else (local(prop.path), False)


def _description(prop: Property, label: str, terms: Terms) -> str:
    meaning = prop.description or terms.definition(prop.path)
    if not meaning:
        return ""
    meaning = meaning.strip()
    return meaning if meaning.lower().startswith(label.lower()) \
        else f"{label}: {meaning}"


def _entry(iri: str, terms: Terms) -> dict:
    entry: dict = {"label": terms.label(iri) or local(iri)}
    others = terms.other_names(iri)
    if others:
        entry["spellings"] = others
    meaning = terms.definition(iri)
    if meaning:
        entry["definition"] = meaning
    return entry


def _predicate(prop: Property, label: str, names: Names) -> dict:
    prefix, name = names.split(prop.path)
    return {"prefix": prefix, "predicate": name, "label": label}


def draft(shapes: list, prefixes: dict, terms: Optional[Terms] = None, *,
          base: Optional[str] = None, sources: tuple = ()) -> dict:
    """The spec these shapes ask for, as far as they and the ontology say."""
    terms = terms or Terms()
    names = Names(prefixes)
    targets = {shape.target_class: shape for shape in shapes
               if shape.target_class}
    by_iri = {shape.iri: shape for shape in shapes if shape.iri}
    nodes: dict = {}
    links: list = []
    parameters: list = []
    notes: list = []
    taken: set = set()

    def unique(wanted: str) -> str:
        name, number = wanted, 2
        while name in taken:
            name, number = f"{wanted}_{number}", number + 1
        taken.add(name)
        return name

    for shape in shapes:
        if not shape.target_class:
            notes.append(f"{shape.name}: a shape without sh:targetClass "
                         f"names no node of the graph and was left out")
            continue
        nodes[shape.name] = {"class": names.curie(shape.target_class),
                             "per": "document"}
        notes += [f"{shape.name}: {note}" for note in shape.notes]
        for prop in shape.properties:
            label, said = _label_of(prop, terms)
            where = f"{shape.name}.{local(prop.path)}"
            notes += [f"{where}: {note}" for note in prop.notes]
            # A property that leads to another node of the graph is the
            # graph's own structure and asks a document nothing.
            linked = [targets[klass] for klass in prop.classes
                      if klass in targets]
            if prop.node in by_iri:
                linked.append(by_iri[prop.node])
            if linked:
                for other in linked:
                    links.append({"from": shape.name, "to": other.name,
                                  **_predicate(prop, label, names)})
                if len(linked) == len(prop.classes) + bool(prop.node):
                    continue
            raw: dict = {
                "uri": unique(f"{shape.name}_{slug(label) or 'value'}"),
                "label": label,
                "description": _description(prop, label, terms),
                "value_type": "text",
                "axes": {},
            }
            kg: dict = {"node": shape.name,
                        "property": _predicate(prop, label, names)}
            free = [klass for klass in prop.classes if klass not in targets]
            if prop.choices:
                raw["value_type"] = "category"
                if prop.choices_are_terms:
                    raw["vocabulary"] = {iri: _entry(iri, terms)
                                         for iri in prop.choices}
                    kg["object"] = "term"
                else:
                    raw["vocabulary"] = {text: [text]
                                         for text in prop.choices}
                    kg["object"] = "literal"
            elif free:
                individuals = sorted({iri for klass in free
                                      for iri in terms.individuals(klass)})
                if individuals:
                    # "One of this class", and the ontology names them all.
                    raw["value_type"] = "category"
                    raw["vocabulary"] = {iri: _entry(iri, terms)
                                         for iri in individuals}
                    kg["object"] = "term"
                else:
                    # A thing the document names, of a class the ontology
                    # has: its own node, labelled with the wording.
                    klass = free[0]
                    entity = slug(terms.label(klass) or local(klass))
                    nodes.setdefault(entity, {"class": names.curie(klass),
                                              "per": "value"})
                    kg = {"node": entity,
                          "property": {**dict(zip(
                              ("prefix", "predicate"),
                              names.split(RDFS_LABEL))), "label": "label"},
                          "edge_from": {"node": shape.name,
                                        **_predicate(prop, label, names)}}
                    if len(free) > 1:
                        notes.append(f"{where}: several classes are allowed "
                                     f"and the first one was taken")
            elif prop.datatype:
                kind = NUMBERS.get(local(prop.datatype)) \
                    if prop.datatype.startswith(XSD) else None
                if kind:
                    raw["value_type"] = kind
                    raw["unit_target"] = None
                    raw["units_accepted"] = {}
                kg["property"]["datatype"] = (
                    "xsd:" + local(prop.datatype)
                    if prop.datatype.startswith(XSD)
                    else names.curie(prop.datatype))
            if prop.min_count:
                kg["min"] = prop.min_count
            if prop.max_count is not None:
                kg["max"] = prop.max_count
            raw["kg"] = kg
            raw["_drafted"] = {"label_from_ontology": said}
            unnamed = [iri for iri, entry in (raw.get("vocabulary")
                                              or {}).items()
                       if isinstance(entry, dict)
                       and terms.label(iri) is None]
            if unnamed:
                raw["_drafted"]["unnamed"] = unnamed
            parameters.append(raw)
    out = {
        "_comment": (
            "Drafted by `docpipe compile spec`"
            + (" from " + ", ".join(sources) if sources else "")
            + ". It says what the shapes and the ontology say. What only "
              "the author knows is open: `docpipe compile check` lists it, "
              "and the file is a spec once that list is empty."),
        "graph": {"base": base or PLACEHOLDER_BASE,
                  "prefixes": dict(sorted(names.used.items())),
                  "nodes": nodes, "links": links},
        "parameter_question": PARAMETER_QUESTION,
        "parameters": parameters,
    }
    if notes:
        out["_notes"] = notes
    return out


def finished(raw: dict) -> dict:
    """The draft as a spec: without the marks only the drafting needs."""
    out = copy.deepcopy(raw)
    out.pop("_notes", None)
    for parameter in out.get("parameters") or ():
        parameter.pop("_drafted", None)
        if parameter.get("example") is None:
            parameter.pop("example", None)
    return out


def todo(raw: dict) -> list:
    """What stands between this draft and a spec, one line each.

    The lines this function can name itself, and after them whatever
    `spec.load` still refuses: that is the judge, and a draft is done when
    it has nothing left to say.
    """
    lines = []
    graph = raw.get("graph") or {}
    if graph.get("base") == PLACEHOLDER_BASE:
        lines.append(f"graph.base: still the placeholder {PLACEHOLDER_BASE}; "
                     f"say where the nodes of this graph live")
    for parameter in raw.get("parameters") or ():
        name = parameter.get("uri")
        drafted = parameter.get("_drafted") or {}
        if drafted.get("label_from_ontology") is False:
            lines.append(f"{name}.label: nobody names this property; the "
                         f"label is its identifier")
        words = len(str(parameter.get("description") or "").split())
        if words < MIN_DESCRIPTION_WORDS:
            lines.append(f"{name}.description: {words} word(s); say what "
                         f"the field means, the model reads this")
        if parameter.get("value_type") in spec_module.NUMERIC_TYPES:
            if not parameter.get("unit_target") \
                    or not parameter.get("units_accepted"):
                lines.append(f"{name}.unit_target, units_accepted: name the "
                             f"unit the number is kept in and the units a "
                             f"document may state it in")
        # the entries nobody named, as long as they still read as their
        # identifier
        vocabulary = parameter.get("vocabulary") or {}
        unnamed = [iri for iri in drafted.get("unnamed") or ()
                   if isinstance(vocabulary.get(iri), dict)
                   and vocabulary[iri].get("label") == local(iri)]
        if unnamed:
            lines.append(f"{name}.vocabulary: {len(unnamed)} entr"
                         f"{'y has' if len(unnamed) == 1 else 'ies have'} no "
                         f"label in the ontology files given (first: "
                         f"{unnamed[0]})")
        if not parameter.get("example"):
            lines.append(f"{name}.example: missing; `docpipe compile "
                         f"examples` proposes one from the corpus")
    try:
        spec_module.load(finished(raw))
    except spec_module.SpecError as exc:
        if not lines:
            lines.append(str(exc))
    return lines


# -- an existing spec against the shapes --------------------------------------

def _predicates(block, found=None) -> list:
    """Every predicate a `kg` block names, at any depth."""
    found = [] if found is None else found
    if isinstance(block, dict):
        if isinstance(block.get("predicate"), str):
            found.append(block["predicate"])
        for value in block.values():
            _predicates(value, found)
    return found


def _classes(block, found=None) -> list:
    found = [] if found is None else found
    if isinstance(block, dict):
        if isinstance(block.get("class"), str):
            found.append(local(block["class"].split(":")[-1]))
        for value in block.values():
            _classes(value, found)
    return found


def _node_classes(spec_raw: dict) -> dict:
    """{node name: class}. A spec with a `graph` block says each node's
    class there, once. One without says it in the block of the parameter
    that mints the node; the others only name the node."""
    out: dict = {}
    nodes = (spec_raw.get("graph") or {}).get("nodes")
    for node, said in (nodes.items() if isinstance(nodes, dict) else ()):
        if isinstance(said, dict) and isinstance(said.get("class"), str):
            out[node] = local(said["class"].split(":")[-1])

    def walk(block):
        if not isinstance(block, dict):
            return
        if isinstance(block.get("node"), str) and \
                isinstance(block.get("class"), str):
            out.setdefault(block["node"],
                           local(block["class"].split(":")[-1]))
        for value in block.values():
            walk(value)

    for parameter in spec_raw.get("parameters") or ():
        walk(parameter.get("kg"))
    return out


def differences(shapes: list, spec_raw: dict,
                terms: Optional[Terms] = None) -> list:
    """What the spec says differently from the shapes, and what one of them
    does not say at all. [{kind, parameter, path, detail}], nothing changed.

    A parameter is held against the property shape whose path its `kg` block
    names. Where several shapes carry that path (a label, on every node),
    the one is taken whose target class the block names, or the node of the
    block is of. Where that settles nothing, the parameter is compared to
    nothing rather than to a guess, and is listed as ambiguous only if no
    other predicate of its block found its shape.

    An entry of a list that starts with `out:` is the profile's own word for
    "none of these" and no term, so the shapes are not expected to have it.
    """
    terms = terms or Terms()
    by_path: dict = {}
    for shape in shapes:
        for prop in shape.properties:
            by_path.setdefault(local(prop.path), []).append((shape, prop))
    node_class = _node_classes(spec_raw)
    # What the `graph` block links: (class of the start node, predicate).
    # Nobody is asked for those; the graph writer draws them itself.
    linked = set()
    for link in (spec_raw.get("graph") or {}).get("links") or ():
        if isinstance(link, dict) and isinstance(link.get("predicate"), str):
            linked.add((node_class.get(link.get("from")),
                        local(link["predicate"])))
    out: list = []
    asked: set = set()

    def note(kind, parameter, path, detail):
        out.append({"kind": kind, "parameter": parameter, "path": path,
                    "detail": detail})

    for parameter in spec_raw.get("parameters") or ():
        name = parameter.get("uri")
        kg = parameter.get("kg")
        predicates = _predicates(kg)
        if not predicates:
            note("no_graph_block", name, None,
                 "the parameter names no predicate, so it cannot be held "
                 "against the shapes")
            continue
        classes = set(_classes(kg))
        if isinstance(kg, dict) and kg.get("node") in node_class:
            classes.add(node_class[kg["node"]])
        matched, unsettled = [], []
        for predicate in predicates:
            candidates = by_path.get(local(predicate), [])
            if len(candidates) > 1:
                narrowed = [(shape, prop) for shape, prop in candidates
                            if local(shape.target_class or "") in classes]
                if len(narrowed) != 1:
                    unsettled.append((predicate, candidates))
                    continue
                candidates = narrowed
            matched += candidates
        if not matched:
            for predicate, candidates in unsettled:
                note("ambiguous", name, predicate,
                     f"{len(candidates)} shapes carry this path and the "
                     f"block does not say which node is meant")
                asked.update((shape.name, prop.path)
                             for shape, prop in candidates)
            if not unsettled:
                note("not_in_shapes", name, ", ".join(predicates),
                     "no property shape has this path")
        for shape, prop in matched:
            asked.add((shape.name, prop.path))
            said_min = kg.get("min") if isinstance(kg, dict) else None
            said_max = kg.get("max") if isinstance(kg, dict) else None
            if (prop.min_count or prop.max_count is not None) and (
                    (prop.min_count or 0) != (said_min or 0)
                    or prop.max_count != said_max):
                spec_says = "" if said_min is None and said_max is None \
                    else (f"; the spec says min {said_min or 0}, max "
                          f"{'any' if said_max is None else said_max}")
                note("cardinality", name, local(prop.path),
                     f"the shapes allow min {prop.min_count or 0}, max "
                     f"{'any' if prop.max_count is None else prop.max_count}"
                     + spec_says)
            vocabulary = parameter.get("vocabulary")
            if prop.choices and isinstance(vocabulary, dict):
                theirs = {local(iri): iri for iri in prop.choices}
                ours = {local(iri): iri for iri in vocabulary
                        if not str(iri).startswith("out:")}
                missing = sorted(set(theirs) - set(ours))
                extra = sorted(set(ours) - set(theirs))
                if missing:
                    note("list_missing", name, local(prop.path),
                         f"{len(missing)} entr"
                         f"{'y' if len(missing) == 1 else 'ies'} of the "
                         f"shapes' list not in the spec: "
                         + ", ".join(missing))
                if extra:
                    note("list_extra", name, local(prop.path),
                         f"{len(extra)} entr"
                         f"{'y' if len(extra) == 1 else 'ies'} of the spec "
                         f"not in the shapes' list: " + ", ".join(extra))
                for key in sorted(set(theirs) & set(ours)):
                    entry = vocabulary[ours[key]]
                    label = terms.label(theirs[key])
                    said = entry.get("label") if isinstance(entry, dict) \
                        else (entry[0] if entry else None)
                    spellings = ([said] + list(entry.get("spellings") or [])
                                 if isinstance(entry, dict) else list(entry))
                    if label and label not in spellings:
                        note("label", name, key,
                             f"the ontology calls it {label!r}, the spec "
                             f"{said!r}")
                    meaning = terms.definition(theirs[key])
                    theirs_said = entry.get("definition") \
                        if isinstance(entry, dict) else None
                    if meaning and theirs_said and \
                            " ".join(meaning.split()) != \
                            " ".join(theirs_said.split()):
                        note("definition", name, key,
                             "the spec's definition is not the ontology's")
            elif prop.choices and parameter.get("vocabulary_dynamic"):
                pass        # the list is the profile's, per document
            elif prop.choices:
                note("list_missing", name, local(prop.path),
                     f"the shapes close this property over "
                     f"{len(prop.choices)} entries and the spec has no list")
    for shape in shapes:
        for prop in shape.properties:
            if (shape.name, prop.path) in asked:
                continue
            if (local(shape.target_class or ""), local(prop.path)) in linked \
                    or (None, local(prop.path)) in linked:
                continue
            needed = " (required: min %d)" % prop.min_count \
                if prop.min_count else ""
            note("not_asked", None, local(prop.path),
                 f"{shape.name}: no parameter asks for this property"
                 + needed)
    return out
