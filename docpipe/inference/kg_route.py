"""
kg_route.py: Answers a question from the graph the harvest wrote,
before the documents are searched.

`--serialize` turns a plan's harvested numbers into Turtle: one value
node per coordinate tuple (the part of the plan it hangs under, the
quantity class, the carrier, the sector, the year, the aggregation),
with the trust line and the evidence the serializer wrote as comments
above each node. A question that names those coordinates has an
answer in that graph, one no retrieval has to find and no model has
to read off a page: the number, its unit, and how far the run stands
behind it.

The route does not guess. Every coordinate is one closed question
over the spec's own list (one request per field, the harvest's own
rule); an answer outside the list leaves the axis unbound, and an
unbound axis adds no constraint. A value with no trust line is not
shown with a blank badge: the route states why it did not answer,
and the caller falls back to the documents.

Which graph, which query and which axes are the profile's own.
`Hooks` carries them the way `answer.Corpus` carries the corpus, and
this module imports neither `profiles` nor `streamlit`. rdflib is
imported inside the functions that need it, the convention
`docpipe/ontology.py` states: the batch path never touches this
module, and the check that does can run on the cluster without it.

Author: Felix Vossel
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from .. import prompts
from ..extraction import fields
from ..extraction.spec import fold_label
from ..extraction.trust import LEVEL_A, LEVEL_B, LEVEL_C

# The profile's prompt for one closed question. Optional the way the
# extraction prompts are: a profile without kg.VALUE_QUERY has no route and
# is asked for no prompt.
COORDINATE_PROMPT_ID = "kg/coordinate"

# Where the profile's query takes the constraint lines an answered
# coordinate contributes. Text, not initBindings alone: an unbound axis has to
# contribute NO line, and a binding cannot express absence.
CONSTRAINTS_MARKER = "##CONSTRAINTS##"

# Why the route did not answer, as a closed machine vocabulary. The profile
# words each in the reader's language (`inference.ROUTE_NOTES`), and
# `check_notes` holds the two against each other so a token nobody worded is
# reported when the route is built and not as a blank caption once in a
# thousand turns.
REASONS = ("no_graph", "no_plan", "no_coordinates", "no_rows", "no_trust")

# The axes that decide whether a question is one the graph can answer at all.
# A carrier alone is not: "Erdgas" names every gas figure of every year.
DECIDING_AXES = ("quantity", "scenario", "year")

LEVELS = (LEVEL_A, LEVEL_B, LEVEL_C)


@dataclass(frozen=True)
class Hooks:
    """What a profile contributes to the KG route. None of it is core."""
    query: str            # SPARQL with CONSTRAINTS_MARKER
    axes: tuple           # coordinate axes to ask, in order
    spec: Any             # a LOADED docpipe.extraction.spec.Spec
    plan_iri: Callable    # (db_path, document name) -> str | None
    bindings: Callable    # ({axis: uri | int}) -> (constraint text, {var: (kind, value)})
    label: Callable       # (IRI or bare id) -> what a reader calls it
    prose: dict           # the profile's trust wording, kg.TRUST_PROSE
    notes: dict           # reason token -> sentence, inference.ROUTE_NOTES
    prompt: Any           # the coordinate prompt, a docpipe.prompts.Prompt


def check_notes(notes: dict, where: str) -> dict:
    """`notes` back, or raise if it does not word every reason exactly once.

    Mirrors trust.check_prose: the reason tokens are the core's, the sentences
    are the profile's, and a token without a sentence is a KeyError on a user's
    screen rather than a finding at import.
    """
    missing = sorted(set(REASONS) - set(notes or {}))
    extra = sorted(set(notes or {}) - set(REASONS))
    if missing or extra:
        raise LookupError(f"{where} words {missing} nowhere and {extra} for "
                          f"no reason of kg_route.REASONS")
    return notes


def hooks(profile) -> Optional[Hooks]:
    """The profile's contribution, or None where it has no graph to ask.

    `component`, never `require`: a require with two constant arguments is
    read by test_architecture as a demand on EVERY profile, and the scenarios
    profile writes a different graph and answers from none.
    """
    if profile is None:
        return None
    query = profile.component("kg", "VALUE_QUERY")
    if query is None:
        return None
    pieces = {name: profile.component("kg", name)
              for name in ("COORDINATE_AXES", "SPEC", "heatplan_iri",
                           "value_bindings", "label_of", "TRUST_PROSE")}
    pieces["ROUTE_NOTES"] = profile.component("inference", "ROUTE_NOTES")
    missing = sorted(name for name, value in pieces.items() if value is None)
    if missing:
        raise LookupError(f"profile {profile.name!r} has kg.VALUE_QUERY and "
                          f"lacks {missing}")
    return Hooks(query=query, axes=tuple(pieces["COORDINATE_AXES"]),
                 spec=pieces["SPEC"], plan_iri=pieces["heatplan_iri"],
                 bindings=pieces["value_bindings"], label=pieces["label_of"],
                 prose=pieces["TRUST_PROSE"],
                 notes=check_notes(pieces["ROUTE_NOTES"],
                                   f"profiles/{profile.name}/inference.py "
                                   f"ROUTE_NOTES"),
                 prompt=prompts.load(COORDINATE_PROMPT_ID, profile))


def load_graph(ttl_path) -> tuple:
    """(graph, {value IRI: comment lines}) from the file `--serialize` wrote."""
    return load_graph_from_text(Path(ttl_path).read_text(encoding="utf-8"))


def load_graph_from_text(text: str) -> tuple:
    """The same, from a string. rdflib is imported here and nowhere above.

    The serializer writes the prefix header once per run, so a file made of
    several runs carries several headers, which is legal Turtle -- and a
    fragment cut from a run's second document onward carries none and
    would not parse. That case is named here rather than left to rdflib's
    parser error on a prefixed name.
    """
    if not re.search(r"^\s*@prefix\s", text, re.M):
        raise ValueError("no @prefix line: this is a fragment of a run, not "
                         "the file --serialize wrote")
    from rdflib import Graph
    graph = Graph()
    graph.parse(data=text, format="turtle")
    return graph, trust_comments(text)


def trust_comments(text: str) -> dict:
    """{value IRI: [comment line, ...]}: the lines standing over each node.

    A convention, not a contract: the serializer joins evidence_comment's
    lines and the node's own lines into ONE block, so the comments sit
    directly above the `<iri>` line, and parts are joined with a blank line
    between them. A blank line, a prefix line or any other statement resets
    the buffer, which is what keeps a plan or a year node from inheriting the
    comment of the value written before it. The trust line is LAST because
    evidence_comment appends it last.
    """
    out: dict = {}
    buffer: list = []
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("#"):
            buffer.append(line[1:].strip())
        elif re.fullmatch(r"<[^>\s]+>", line):
            if buffer:
                out[line[1:-1]] = buffer
            buffer = []
        else:
            buffer = []
    return out


def to_coordinates(task: str, spec, axes, ask) -> dict:
    """{axis: uri | int} for what the question fixes, and nothing it does not.

    Every axis is one closed question over the spec's own list, `ask(task,
    slot)` returning one label or None. A label outside the list resolves
    through the same fold_label / label_to_uri pair verify.py applies to a
    harvested coordinate, so a synonym the spec knows lands and a wording it
    does not is left unbound, never matched by nearest string.
    """
    slot = fields.parameter_slot(spec)
    by_label = {fold_label(p.label): p.uri for p in spec.parameters}
    parameter_uri = by_label.get(fold_label(ask(task, slot) or ""))
    if parameter_uri is None:
        return {}
    parameter = spec.by_uri[parameter_uri]
    out: dict = {}
    for slot in fields.axis_slots(parameter):
        if slot.name not in axes:
            continue
        answer = ask(task, slot)
        if answer is None or str(answer).strip() == fields.UNSTATED:
            continue
        if slot.kind == fields.NUMBER:
            digits = re.search(r"\b\d{4}\b", str(answer))
            if digits:
                out[slot.name] = int(digits.group())
            continue
        uri = parameter.axes[slot.name].label_to_uri().get(fold_label(answer))
        if uri is not None:
            out[slot.name] = uri
    return out


def by_axis(spec, axes, iris) -> list:
    """[(axis name, [iri, ...])] in the profile's axis order, each IRI under
    the axis whose own list holds it, and the rest under "".

    Membership in the spec's lists and no third copy: the serializer writes a
    carrier and a sector under the same predicate, so the query hands them
    back mixed and only the lists can tell them apart. An IRI is matched to
    a list entry by its bare id, the way the serializer minted it from one.
    """
    lists: dict = {}
    for parameter in spec.parameters:
        for name, axis in (parameter.axes or {}).items():
            if name in axes and axis.vocabulary:
                lists.setdefault(name, set()).update(axis.vocabulary)
    out, placed = [], set()
    for name in axes:
        keys = lists.get(name) or ()
        mine = [iri for iri in iris if iri not in placed
                and any(iri == key or iri.endswith("/" + key)
                        or iri.endswith("#" + key) for key in keys)]
        if mine:
            out.append((name, mine))
            placed.update(mine)
    rest = [iri for iri in iris if iri not in placed]
    if rest:
        out.append(("", rest))
    return out


def run_query(graph, text: str, bindings: dict) -> list:
    """[{variable: string}] for one SPARQL over the loaded graph.

    `bindings` are (kind, value) pairs, "iri" or "literal", so the profile
    that builds them stays rdflib-free. A literal binds UNTYPED: the
    serializer writes the year node's label as a plain string, and
    Literal(2030) with an integer datatype matches nothing.
    """
    from rdflib import Literal, URIRef
    init = {name: (URIRef(value) if kind == "iri" else Literal(value))
            for name, (kind, value) in bindings.items()}
    rows = []
    for row in graph.query(text, initBindings=init):
        rows.append({str(var): (None if term is None else str(term))
                     for var, term in row.asdict().items()})
    return rows


def _fallback(reason: str, coordinates: Optional[dict] = None) -> dict:
    assert reason in REASONS, reason
    return {"route": "rag", "reason": reason, "values": [],
            "coordinates": coordinates or {}}


def answer_from_graph(task: str, hooks: Hooks, graph, comments: dict, *,
                      db_path, document: Optional[str], ask) -> dict:
    """The graph's answer, or why there is none.

    {"route": "kg", "reason": None, "values": [...], "coordinates": {...}}
    when the graph answered, each value carrying the row the query returned
    plus `evidence` (the comment lines above its node) and `trust` (the last
    of them). Otherwise route "rag" with one of REASONS, cheapest checked
    first: no plan node costs one SQLite read, no coordinates costs the field
    requests, no rows one SPARQL. The key is `values`, never `rows`: the app
    dispatches a history entry with `rows` into the comparison render.
    """
    plan = hooks.plan_iri(db_path, document) if document else None
    if plan is None:
        return _fallback("no_plan")
    coordinates = to_coordinates(task, hooks.spec, hooks.axes, ask)
    if not any(axis in coordinates for axis in DECIDING_AXES):
        return _fallback("no_coordinates", coordinates)
    text, bindings = hooks.bindings(coordinates)
    bindings = dict(bindings, PLAN=("iri", plan))
    rows = run_query(graph, hooks.query.replace(CONSTRAINTS_MARKER, text),
                     bindings)
    if not rows:
        return _fallback("no_rows", coordinates)
    values = []
    for row in rows:
        lines = comments.get(row.get("value") or "")
        if not lines:
            # Fails closed: a number with no trust line would be shown as a
            # number the run stands behind, and nothing said that.
            return _fallback("no_trust", coordinates)
        values.append(dict(row, evidence=lines[:-1], trust=lines[-1]))
    return {"route": "kg", "reason": None, "values": values,
            "coordinates": coordinates}


def trust_level(line: str, prose: dict) -> Optional[str]:
    """The level a trust line states, read by the profile's own wording."""
    for level in LEVELS:
        if prose["level"].format(level=level) in line:
            return level
    return None
