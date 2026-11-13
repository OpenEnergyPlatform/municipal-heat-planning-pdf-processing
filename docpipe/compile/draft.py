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

For a number's unit the draft only suggests. The units a shape lists itself
and the unit family the ontology gives the shape's class hang on the number
under `_drafted`, and `todo` names them; `units_accepted` and the factors
between the entries stay the author's to write.

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
from .terms import UNIT_PROPERTIES, Terms, says_unit

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


def path_name(predicate: str) -> str:
    """The end of a property's IRI, from the IRI or a prefixed name."""
    text = str(predicate)
    if "://" not in text and ":" in text:
        return text.split(":", 1)[1]
    return local(text)


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


def _is_number(prop: Property) -> bool:
    """A property whose value is a number: a numeric XSD datatype, and no
    list and no class that would make it something else."""
    return bool(prop.datatype and prop.datatype.startswith(XSD)
                and NUMBERS.get(local(prop.datatype))
                and not prop.choices and not prop.classes
                and prop.node is None)


def unit_listing(shape: Shape, unit_properties=UNIT_PROPERTIES) -> tuple:
    """(the properties of this shape that list units, the properties that
    are numbers). The first is empty where there is no number to hang a list
    of units on."""
    numbers = [prop for prop in shape.properties if _is_number(prop)]
    if not numbers:
        return [], []
    return [prop for prop in shape.properties
            if prop.choices and says_unit(prop.path, unit_properties)], numbers


def _unit(iri: str, terms: Terms) -> dict:
    """One unit as a suggestion names it: its label and the other names the
    ontology has for it, which is where a symbol such as kWh stands."""
    out = {"iri": iri, "label": terms.label(iri) or local(iri)}
    others = terms.other_names(iri)
    if others:
        out["spellings"] = others
    return out


def _family_suggestions(shape: Shape, terms: Terms,
                        unit_properties) -> list:
    """What the ontology says about the unit of a quantity of this shape's
    class: [{family, family_iri, stated_on, units: [..]}], none where it
    says nothing."""
    if not shape.target_class:
        return []
    return [{"family": terms.label(one["family"]) or local(one["family"]),
             "family_iri": one["family"],
             "stated_on": terms.label(one["stated_on"])
             or local(one["stated_on"]),
             "units": sorted((_unit(iri, terms)
                              for iri in terms.units(one["family"])),
                             key=lambda unit: unit["label"].casefold())}
            for one in terms.unit_families(shape.target_class,
                                           unit_properties)]


def draft(shapes: list, prefixes: dict, terms: Optional[Terms] = None, *,
          base: Optional[str] = None, sources: tuple = (),
          unit_properties=UNIT_PROPERTIES) -> dict:
    """The spec these shapes ask for, as far as they and the ontology say.

    A number's unit stays open: the author writes `units_accepted` and the
    factors. What is known about it is hung on the parameter as a suggestion
    (`_drafted`): the units the shape itself lists, which are no parameter of
    their own, and the unit family the ontology gives the shape's class.
    """
    terms = terms or Terms()
    names = Names(prefixes)
    targets = {shape.target_class: shape for shape in shapes
               if shape.target_class}
    by_iri = {shape.iri: shape for shape in shapes if shape.iri}
    boxes: dict = {}        # box id -> box of the drawing
    box_of: dict = {}       # shape name -> its box id
    links: list = []        # (shape name, shape name, property) to resolve
    arrows: list = []
    parameters: list = []
    notes: list = []
    taken: set = set()

    def unique(wanted: str) -> str:
        name, number = wanted, 2
        while name in taken:
            name, number = f"{wanted}_{number}", number + 1
        taken.add(name)
        return name

    def box_id(wanted: str) -> str:
        wanted = slug(wanted) or "node"
        wanted = wanted if wanted[0].isalpha() else f"node_{wanted}"
        name, number = wanted, 2
        while name in boxes:
            name, number = f"{wanted}_{number}", number + 1
        return name

    for shape in shapes:
        if not shape.target_class:
            notes.append(f"{shape.name}: a shape without sh:targetClass "
                         f"names no node of the graph and was left out")
            continue
        here = box_of[shape.name] = box_id(shape.name)
        boxes[here] = {
            "id": here, "class": names.curie(shape.target_class),
            "count": "per_document",
            "address": {"folder": here, "key": here, "from": []},
            "note": f"Drafted from the shape {shape.name}. What its nodes "
                    f"are named after is the author's: `address.from` "
                    f"lists the fields or facts the address is made of."}
        notes += [f"{shape.name}: {note}" for note in shape.notes]
        listing, numbers = unit_listing(shape, unit_properties)
        families = _family_suggestions(shape, terms, unit_properties) \
            if numbers else []
        listed: list = []       # the units this shape's own list names
        made: list = []         # the number parameters of this shape
        for prop in shape.properties:
            label, said = _label_of(prop, terms)
            where = f"{shape.name}.{local(prop.path)}"
            notes += [f"{where}: {note}" for note in prop.notes]
            if prop in listing:
                # The unit of a number is part of the number, not a value of
                # its own to ask for: the list hangs on the number.
                listed += [_unit(iri, terms) if prop.choices_are_terms
                           else {"label": iri} for iri in prop.choices]
                continue
            # A property that leads to another node of the graph is the
            # graph's own structure and asks a document nothing.
            linked = [targets[klass] for klass in prop.classes
                      if klass in targets]
            if prop.node in by_iri:
                linked.append(by_iri[prop.node])
            if linked:
                for other in linked:
                    links.append((shape.name, other.name,
                                  names.curie(prop.path)))
                if len(linked) == len(prop.classes) + bool(prop.node):
                    continue
            raw: dict = {
                "uri": unique(f"{shape.name}_{slug(label) or 'value'}"),
                "label": label,
                "description": _description(prop, label, terms),
                "value_type": "text",
                "axes": {},
            }
            # What the field becomes in the graph is an arrow of the drawing,
            # from the field to the box of its shape.
            arrow: dict = {"from": raw["uri"], "to": box_of[shape.name],
                           "property": names.curie(prop.path)}
            free = [klass for klass in prop.classes if klass not in targets]
            if prop.choices:
                raw["value_type"] = "category"
                if prop.choices_are_terms:
                    raw["vocabulary"] = {iri: _entry(iri, terms)
                                         for iri in prop.choices}
                    arrow["brick"] = "entry"
                else:
                    raw["vocabulary"] = {text: [text]
                                         for text in prop.choices}
            elif free:
                individuals = sorted({iri for klass in free
                                      for iri in terms.individuals(klass)})
                if individuals:
                    # "One of this class", and the ontology names them all.
                    raw["value_type"] = "category"
                    raw["vocabulary"] = {iri: _entry(iri, terms)
                                         for iri in individuals}
                    arrow["brick"] = "entry"
                else:
                    # A thing the document names, of a class the ontology
                    # has: its own node, labelled with the wording.
                    klass = free[0]
                    entity = box_id(terms.label(klass) or local(klass))
                    boxes[entity] = {
                        "id": entity, "class": names.curie(klass),
                        "count": "per_distinct", "of": raw["uri"],
                        "address": {"folder": entity, "key": entity,
                                    "from": ["@name"], "fold": True}}
                    arrows.append({"from": box_of[shape.name], "to": entity,
                                   "property": names.curie(prop.path)})
                    arrow = {"from": raw["uri"], "to": entity,
                             "property": names.curie(RDFS_LABEL),
                             "brick": "node_name"}
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
                    arrow["brick"] = ("decimal" if kind == "float"
                                      else "whole_number")
                else:
                    arrow["note"] = (
                        f"The shape asks for "
                        f"{names.curie(prop.datatype)}; the reading is "
                        f"written as a text until a brick says otherwise.")
            if prop.max_count == 1 and arrow["to"] == box_of[shape.name]:
                # The shapes allow one value: one reading is written.
                arrow.update({"pick": "one_reading", "single": True})
            arrows.append(arrow)
            raw["_drafted"] = {"label_from_ontology": said}
            unnamed = [iri for iri, entry in (raw.get("vocabulary")
                                              or {}).items()
                       if isinstance(entry, dict)
                       and terms.label(iri) is None]
            if unnamed:
                raw["_drafted"]["unnamed"] = unnamed
            parameters.append(raw)
            if raw["value_type"] in spec_module.NUMERIC_TYPES:
                made.append(raw)
        for raw in made:
            if listed:
                raw["_drafted"]["units_listed"] = copy.deepcopy(listed)
            if families:
                raw["_drafted"]["unit_families"] = copy.deepcopy(families)
        if listing:
            notes.append(
                f"{shape.name}: the units listed under "
                f"{', '.join(local(prop.path) for prop in listing)} hang on "
                f"{', '.join(raw['uri'] for raw in made)} and are no "
                f"parameter of their own; the generic graph writer writes no "
                f"unit statement for a number")
    for one, other, predicate in links:
        if one in box_of and other in box_of:
            arrows.append({"from": box_of[one], "to": box_of[other],
                           "property": predicate})
    out = {
        "_comment": (
            "Drafted by `docpipe compile spec`"
            + (" from " + ", ".join(sources) if sources else "")
            + ". It says what the shapes and the ontology say. What only "
              "the author knows is open: `docpipe compile check` lists it, "
              "and the file is a spec once that list is empty."),
        # What the project's graph file (graph.json) holds: where the nodes
        # live (rule `base`) and the drawing of what the fields become there.
        "graph": {"rules": {"base": base or PLACEHOLDER_BASE},
                  "map": {"prefixes": dict(sorted(names.used.items())),
                          "prefix_width": max(
                              (len(one) for one in names.used),
                              default=0) + 2,
                          "boxes": list(boxes.values()),
                          "arrows": arrows}},
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
    out.pop("graph", None)      # the project's graph file, `graph_file`
    for parameter in out.get("parameters") or ():
        parameter.pop("_drafted", None)
        if parameter.get("example") is None:
            parameter.pop("example", None)
    return out


def graph_file(raw: dict) -> dict:
    """What the draft says for the project's graph file (graph.json): the
    rule `base` and the drawing, {} where it says nothing."""
    graph = raw.get("graph") or {}
    return {key: copy.deepcopy(graph[key]) for key in ("rules", "map")
            if graph.get(key)}


UNITS_SHOWN = 8         # units named in one line of `todo`; the draft has all


def _named(unit: dict) -> str:
    others = unit.get("spellings") or []
    return str(unit.get("label") or unit.get("iri") or "") \
        + (f" ({', '.join(others[:2])})" if others else "")


def _unit_suggestion(drafted: dict) -> str:
    """What the draft knows about a number's unit, said as a suggestion: the
    author decides, and nothing of it is in the spec until they write it."""
    said = []
    listed = drafted.get("units_listed") or []
    if listed:
        said.append(f"the shape lists {len(listed)} unit(s): "
                    + ", ".join(_named(unit) for unit in listed))
    for family in drafted.get("unit_families") or ():
        units = family.get("units") or []
        text = (f"the ontology gives {family.get('stated_on')!r} the unit "
                f"family {family.get('family')!r} with {len(units)} unit(s)")
        if units:
            text += ": " + ", ".join(_named(unit)
                                     for unit in units[:UNITS_SHOWN])
            if len(units) > UNITS_SHOWN:
                text += f" and {len(units) - UNITS_SHOWN} more"
        said.append(text)
    return ". Suggestion, not decided: " + "; ".join(said) if said else ""


def todo(raw: dict) -> list:
    """What stands between this draft and a spec, one line each.

    The lines this function can name itself, and after them whatever
    `spec.load` still refuses: that is the judge, and a draft is done when
    it has nothing left to say.
    """
    lines = []
    graph = (raw.get("graph") or {}).get("rules") or {}
    if graph.get("base") == PLACEHOLDER_BASE:
        lines.append(f"graph.rules.base: still the placeholder "
                     f"{PLACEHOLDER_BASE}; say where the nodes of this "
                     f"graph live")
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
                             f"document may state it in, each with its "
                             f"factor and, unless the number is a rate "
                             f"(integrated: false), whether it names a "
                             f"period (names_period)"
                             + _unit_suggestion(drafted))
            elif parameter.get("integrated", True) is not False \
                    and isinstance(parameter["units_accepted"], dict):
                # The statement is the author's: the draft cannot read it
                # off the ontology, and `spec.load` refuses an entry
                # without it. A null or a non-bool is no statement either,
                # so the list agrees with the loader.
                unsaid = [unit for unit, entry in
                          parameter["units_accepted"].items()
                          if not (isinstance(entry, dict) and isinstance(
                              entry.get("names_period"), bool))]
                if unsaid:
                    lines.append(
                        f"{name}.units_accepted: {len(unsaid)} entr"
                        f"{'y' if len(unsaid) == 1 else 'ies'} without "
                        f"names_period, which says whether the unit names "
                        f"a period (first: {unsaid[0]})")
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


# -- an existing spec and its drawing against the shapes ----------------------

ROW_KEYS = ("value", "value_raw", "value_uri", "value_short", "value_target",
            "unit", "unit_raw", "unit_target")


def _listed(parameter: dict, source: Optional[str]) -> dict:
    """What an arrow from *source* writes as its object for *parameter*, as
    a list to hold against the shapes': a value the spec fixes (a key of
    the parameter that holds one identifier, the unit a value is converted
    to), else the list of the coordinate the arrow starts at, else the
    parameter's own list."""
    axes = parameter.get("axes") or {}
    said = parameter.get(source) if source and source not in axes \
        and source != parameter.get("uri") else None
    owner = axes.get(source) if source in axes else parameter
    owner = owner if isinstance(owner, dict) else {}
    return {"fixed": said if isinstance(said, str) else None,
            "from": source if isinstance(said, str) else None,
            "axis": source if source in axes else None,
            "vocabulary": owner.get("vocabulary"),
            "dynamic": bool(owner.get("vocabulary_dynamic")),
            "edgeless": set()}


def drawn(drawing: Optional[dict], spec_raw: dict) -> tuple:
    """What a drawing (`map` of a graph file) writes, as `differences`
    holds it to the shapes: ({field: [(predicate, listed)]}, {field: the
    local names of the classes of its nodes}, {(class, predicate)} every
    arrow writes, {field: whether its node takes its class from a
    coordinate}).

    An arrow from a field, from one of its coordinates or from a key of its
    reading is the field's; an arrow from a box to a box of one node per
    distinct reading is the field's whose readings those are; any other
    arrow between boxes, and an arrow from a box to itself, is the
    drawing's structure and no field's: it only says the property is
    written."""
    drawing = drawing or {}
    parameters = {one["uri"]: one for one in spec_raw.get("parameters") or ()
                  if isinstance(one, dict) and one.get("uri")}
    boxes = {box["id"]: box for box in drawing.get("boxes") or ()
             if isinstance(box, dict) and box.get("id")}

    def fields_of(box: dict, seen=()) -> list:
        of = box.get("of")
        names = [of] if isinstance(of, str) else [
            one for one in of if isinstance(one, str)] \
            if isinstance(of, list) else []
        out = [one for one in names if one in parameters]
        among = box.get("among")
        if among in boxes and among not in seen:
            out += [one for one in fields_of(boxes[among], seen + (among,))
                    if one not in out]
        return out

    def classes_of(box: dict, field: Optional[str] = None) -> set:
        """The classes the nodes of *box* are written as; for a box that
        takes them from a coordinate, those *field* offers, else every
        field of the box."""
        if isinstance(box.get("class"), str):
            return {local(box["class"].split(":")[-1])}
        coordinate = ((box.get("class_brick") or {}).get("settings")
                      or {}).get("coordinate")
        out: set = set()
        for uri in ([field] if field else fields_of(box)):
            offered = (((parameters[uri].get("axes") or {}).get(coordinate)
                        or {}).get("vocabulary") or {})
            out.update(local(str(key).split(":")[-1]) for key in offered
                       if not str(key).startswith("out:"))
        for entry in (box.get("table") or {}).values():
            if isinstance(entry, dict) and isinstance(entry.get("class"),
                                                      str):
                out.add(local(entry["class"].split(":")[-1]))
        return out

    writes: dict = {}
    classes: dict = {}
    written: set = set()
    from_axis: dict = {}
    for arrow in drawing.get("arrows") or ():
        if not isinstance(arrow, dict):
            continue
        source, target = arrow.get("from"), arrow.get("to")
        predicate = arrow.get("property")
        if target not in boxes or not isinstance(predicate, str):
            continue
        if source in boxes:
            subject = boxes[source]
            node = boxes[target]
            owners = [node["of"]] if source != target \
                and node.get("count") == "per_distinct" \
                and node.get("of") in parameters else []
        else:
            subject = node = boxes[target]
            if source in parameters:
                owners = [source]
            else:
                owners = [uri for uri in fields_of(subject)
                          if source in (parameters[uri].get("axes") or {})
                          or source in ROW_KEYS]
        for klass in classes_of(subject):
            written.add((klass, path_name(predicate)))
        for uri in owners:
            listed = _listed(parameters[uri], None if source in boxes
                             else source)
            writes.setdefault(uri, []).append((predicate, listed))
            classes.setdefault(uri, set()).update(classes_of(node, uri))
            from_axis[uri] = from_axis.get(uri, False) or (
                not isinstance(node.get("class"), str)
                and bool(node.get("class_brick")))
    return writes, classes, written, from_axis


def differences(shapes: list, spec_raw: dict,
                terms: Optional[Terms] = None,
                unit_properties=UNIT_PROPERTIES,
                pairs: Optional[list] = None,
                drawing: Optional[dict] = None) -> list:
    """What the spec and its drawing (`map` of the graph file) say
    differently from the shapes, and what one of them does not say at all.
    [{kind, parameter, path, detail}], nothing changed.

    A field is held against the property shape whose path an arrow of the
    drawing writes for it (`drawn`). Where several shapes carry that path (a
    label, on every node), the one is taken whose target class is the class
    of the field's node. A node that takes its class from a coordinate is
    held against the shape of every class that coordinate offers. Where that
    settles nothing, the field is compared to nothing rather than to a
    guess, and is listed as ambiguous only if no other property it writes
    found its shape. A property no shape carries, or none of the classes its
    node is written as, is named on its own. A property of the shapes no
    arrow writes is `not_asked`.

    An entry of a list that starts with `out:` is the profile's own word for
    "none of these" and no term, so the shapes are not expected to have it.
    The units a shape lists are no property to ask for where the spec asks
    for the shape's number. *pairs*, where given, is filled with (field,
    shape, property) for every property a field was held against.
    """
    terms = terms or Terms()
    by_path: dict = {}
    for shape in shapes:
        for prop in shape.properties:
            by_path.setdefault(local(prop.path), []).append((shape, prop))
    writes, classes_of, written, from_axis = drawn(drawing, spec_raw)
    out: list = []
    asked: set = set()

    def note(kind, parameter, path, detail, shape=None, entries=None,
             axis=None):
        row = {"kind": kind, "parameter": parameter, "path": path,
               "detail": detail}
        if shape is not None:
            row["shape"] = shape        # a property of a shape, said by it
        if entries is not None:
            row["entries"] = entries    # the IRIs a list row names
            row["axis"] = axis          # whose list: an axis, or the value
        out.append(row)

    for parameter in spec_raw.get("parameters") or ():
        if not isinstance(parameter, dict):
            continue
        name = parameter.get("uri")
        found = writes.get(name) or []
        predicates = [predicate for predicate, _listed_ in found]
        if not predicates:
            note("no_graph_block", name, None,
                 "no arrow of the drawing writes the field, so it cannot be "
                 "held against the shapes")
            continue
        classes = classes_of.get(name) or set()
        source = from_axis.get(name)
        matched, unsettled, absent = [], [], []
        for predicate, listed in found:
            candidates = by_path.get(path_name(predicate), [])
            if len(candidates) > 1:
                narrowed = [(shape, prop) for shape, prop in candidates
                            if local(shape.target_class or "") in classes]
                if len(narrowed) == 1 or (narrowed and source):
                    candidates = narrowed
                elif classes and not narrowed:
                    absent.append(predicate)
                    continue
                else:
                    unsettled.append((predicate, candidates))
                    continue
            matched += [(shape, prop, listed) for shape, prop in candidates]
        if not matched:
            for predicate, candidates in unsettled:
                note("ambiguous", name, path_name(predicate),
                     f"{len(candidates)} shapes carry this path and the "
                     f"drawing does not say which node is meant")
                asked.update((shape.name, prop.path)
                             for shape, prop in candidates)
        # Every predicate the drawing writes is one the shapes are asked
        # for: one no shape of its node carries is named, whatever the
        # others of the field found.
        for predicate in absent:
            note("not_in_shapes", name, path_name(predicate),
                 "shapes carry this path, but none of the class(es) this "
                 "node is written as")
        for predicate in dict.fromkeys(predicates):
            if not by_path.get(path_name(predicate)):
                note("not_in_shapes", name, path_name(predicate),
                     "no property shape has this path")
        for shape, prop, listed in matched:
            asked.add((shape.name, prop.path))
            if pairs is not None:
                pairs.append((name, shape.name, local(prop.path)))
            if prop.min_count or prop.max_count is not None:
                note("cardinality", name, local(prop.path),
                     f"the shapes allow min {prop.min_count or 0}, max "
                     f"{'any' if prop.max_count is None else prop.max_count}")
            if not prop.choices:
                continue
            theirs = {local(iri): iri for iri in prop.choices}
            if listed["fixed"] is not None:
                # One object, the same on every node: the shapes have to
                # take it, the rest of their list is theirs to offer.
                if local(listed["fixed"]) not in theirs:
                    note("list_extra", name, local(prop.path),
                         f"the spec writes {listed['fixed']} "
                         f"({listed['from']}), which the shapes' list of "
                         f"{len(theirs)} does not have",
                         entries=[listed["fixed"]], axis=listed["axis"])
                continue
            vocabulary = listed["vocabulary"]
            if isinstance(vocabulary, dict) and vocabulary:
                ours = {local(iri): iri for iri in vocabulary
                        if not str(iri).startswith("out:")
                        and iri not in listed["edgeless"]}
                missing = sorted(set(theirs) - set(ours))
                extra = sorted(set(ours) - set(theirs))
                if missing:
                    note("list_missing", name, local(prop.path),
                         f"{len(missing)} entr"
                         f"{'y' if len(missing) == 1 else 'ies'} of the "
                         f"shapes' list not in the spec: "
                         + ", ".join(missing),
                         entries=[theirs[key] for key in missing],
                         axis=listed["axis"])
                if extra:
                    note("list_extra", name, local(prop.path),
                         f"{len(extra)} entr"
                         f"{'y' if len(extra) == 1 else 'ies'} of the spec "
                         f"not in the shapes' list: " + ", ".join(extra),
                         entries=[ours[key] for key in extra],
                         axis=listed["axis"])
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
                             f"{said!r}", axis=listed["axis"])
                    meaning = terms.definition(theirs[key])
                    theirs_said = entry.get("definition") \
                        if isinstance(entry, dict) else None
                    if meaning and theirs_said and \
                            " ".join(meaning.split()) != \
                            " ".join(theirs_said.split()):
                        note("definition", name, key,
                             "the spec's definition is not the ontology's",
                             axis=listed["axis"])
            elif listed["dynamic"]:
                pass        # the list is the profile's, per document
            else:
                note("list_missing", name, local(prop.path),
                     f"the shapes close this property over "
                     f"{len(prop.choices)} entries and the spec has no list",
                     entries=list(prop.choices), axis=listed["axis"])
    for shape in shapes:
        listing, numbers = unit_listing(shape, unit_properties)
        # The units a shape lists belong to its number, as the draft hangs
        # them: a spec that asks for the number answers them with its units.
        hung = any((shape.name, number.path) in asked for number in numbers)
        for prop in shape.properties:
            if (shape.name, prop.path) in asked:
                continue
            if hung and prop in listing:
                continue
            if (local(shape.target_class or ""), local(prop.path)) \
                    in written:
                continue
            needed = " (required: min %d)" % prop.min_count \
                if prop.min_count else ""
            note("not_asked", None, local(prop.path),
                 f"{shape.name}: no arrow of the drawing writes this "
                 f"property" + needed, shape=shape.name)
    return out
