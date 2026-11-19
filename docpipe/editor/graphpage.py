"""
graphpage.py: How a profile's harvest becomes its graph, as `docpipe edit`
shows and sets it (owner, 2026-11-10: "sodass man steuern kann, wie die
Ernte in den Graphen aufgenommen wird und welche constraints erfüllt sein
müssen").

The file and what it does are the run's (`docpipe.graphfile`); the shapes
are the ones the profile's last refresh pulled. This module turns them into
what the page draws and decides what a save writes:

- `view`: every class of the shapes with its properties, each with the
  fields that write it, its constraints (required, at most so many, a closed
  list, a class, a datatype) and the effect the graph file gives each; per
  class the groups of properties one of which the shapes demand of a node
  (an sh:or on the node) with that constraint and its effect, whether the
  class is written and its address rule; the rules the writer declares,
  each with its value, what it inherits and the setting that wins over it.
- `judge` and `save`: an edited graph file, read by the run's own parser.
  A profile that extends another writes only what differs from what it
  inherits, and the rules its writer reads.
- the drawing: `view` also returns `map` (how the harvest becomes the
  graph, `graphfile.get_map`), the fields of the harvest as the spec asks
  them (with a real example of each where a harvest is loaded), the bricks
  the run knows and the harvest's documents. `judge` holds an edited drawing
  to the run's own checks (`graphfile.map_problem`, `graph.check`) and
  names the box or arrow each problem is about. `preview` writes one
  document of the harvest as the edited drawing says.
- the blocks (owner request 2026-11-14, wish 4): `view` also returns the
  presets, blocks ready to put in where a brick stands, and what a
  condition of the graph can be about; `try_block` writes one document as
  the edited drawing says and shows what one block of it was given and
  gave, reading by reading.
- `probe`: the graph of the harvest the page was given, written twice into
  the temp directory, with the saved file and with the edited one, and what
  differs: per document the nodes kept and left out, per constraint its
  violations, the nodes named anew. No model is asked and nothing is saved.

Author: Felix Vossel
"""
from __future__ import annotations

import dataclasses
import difflib
import hashlib
import json
import os
import subprocess
import re
import sys
import tempfile
import threading
from pathlib import Path
from typing import Optional

from docpipe import graphfile, ontology
from docpipe.editor import RDFLIB_MISSING

CR, LF = "\r", "\n"
PROBE_FOLDER = "docpipe-graph-probe"
PROBE_TIMEOUT = 1800          # seconds, one writing of the graph
COST = ("A change of the graph needs no model. It takes effect the next "
        "time the graph is written from the stored harvest. \"Test write\" "
        "shows what the change does to the harvest the page was given, "
        "before you rely on it.")
GATE = ("A rule set to \"stop\" refuses the run in the check that a job "
        "makes before it starts its model. No job script makes this check "
        "yet, so \"stop\" has no effect on a job today.")
PREVIEW_LOCK = threading.Lock()
# What a field of the harvest shows beside its name: the first reading a
# document gives, found in at most this many documents.
EXAMPLE_DOCUMENTS = 400
EXAMPLE_LENGTH = 90
ROW_KEYS = ("value", "value_raw", "value_uri", "value_short", "value_target",
            "unit", "unit_raw", "unit_target")
COMPONENTS = (("min_count", "MinCount"), ("max_count", "MaxCount"),
              ("choices", "In"), ("classes", "Class"),
              ("datatype", "Datatype"), ("node", "Node"))


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _rules(profile, files, below) -> list:
    known = graphfile.declared(profile)
    out = []
    for name, one in known.items():
        owner = files.owners.get(f"rules/{name}", "")
        out.append({
            "name": name, "title": one.title, "group": one.group,
            "kind": one.kind, "help": one.help, "least": one.least,
            "most": one.most, "choices": list(one.choices),
            "columns": list(one.columns), "of": one.of, "empty": one.empty,
            "decided": one.decided, "where": one.where, "setting": one.env,
            "setting_set": bool(one.env and one.env in os.environ),
            "value": files.rules.get(name),
            "inherited": below.rules.get(name),
            "has_inherited": name in below.rules,
            "owner": owner,
            "own": owner == f"{graphfile.FILE} of {profile.name}"})
    return out


def _constraints(prop, klass: str, made) -> list:
    out = []
    for attribute, component in COMPONENTS:
        said = getattr(prop, attribute, None)
        if not said:
            continue
        key = f"{component} {graphfile.local(prop.path)} {klass}"
        shown = (len(said) if attribute == "choices"
                 else [graphfile.local(one) for one in said]
                 if attribute == "classes"
                 else graphfile.local(said) if attribute in ("datatype",
                                                             "node")
                 else said)
        out.append({"key": key, "component": component, "says": shown,
                    "effect": made.effect(key)})
    return out


def curie(iri, prefixes: dict) -> str:
    """*iri* as a prefixed name of *prefixes* (the longest namespace wins),
    else as <iri>."""
    text = str(iri)
    best = ""
    for prefix, namespace in (prefixes or {}).items():
        if text.startswith(namespace) and text[len(namespace):] \
                and len(namespace) > len((prefixes or {}).get(best, "")):
            best = prefix
    if best:
        return f"{best}:{text[len(prefixes[best]):]}"
    return f"<{text}>"


def _label(prop, terms: dict) -> str:
    """What a property is called: the shape's own name, else the label of
    its term in the ontology, else the end of its address."""
    local = graphfile.local(prop.path)
    term = terms.get(ontology.identifier(local) or "") or {}
    if re.fullmatch(r"[A-Za-z]+_\d+", local):
        return prop.name or term.get("label") or local
    return prop.name or term.get("label") or _humane(local)


def _merge_property(known: dict, one: dict) -> None:
    """What two property shapes of one class say of one path, as the one
    property they are on the page: both hold, so the greater minimum, the
    smaller maximum, and the constraints of both."""
    if (one["min"] or 0) > (known["min"] or 0):
        known["min"] = one["min"]
    if one["max"] is not None and (known["max"] is None
                                   or one["max"] < known["max"]):
        known["max"] = one["max"]
    for said in one["constraints"]:
        if said not in known["constraints"]:
            known["constraints"].append(said)


def _one_of_constraint(klass: str, groups: list, made) -> dict:
    """The sh:or on the nodes of *klass*, as the box lists its constraints:
    named as the validation reports it (no path, `graphfile.violations_of`),
    so that an effect set here is the effect of that violation."""
    key = f"Or - {klass}"
    return {"key": key, "component": "Or",
            "says": [[graphfile.local(one) for one in group]
                     for group in groups],
            "effect": made.effect(key)}


def classes(profile, made, spec_raw: Optional[dict], files: list,
            snapshot: Optional[dict],
            prefixes: Optional[dict] = None) -> dict:
    """{"classes": [...], "skipped": why or None}: the shapes' classes with
    their properties and the constraints; per class also the groups of
    properties one of which the shapes demand of a node (an sh:or on the
    node, `Shape.one_of`), each as the curies of its properties, and that
    constraint with its effect."""
    if not files:
        return {"classes": [], "skipped": "no shapes file: fetch the "
                                          "sources first (Sources tab)"}
    try:
        from docpipe.compile import shapes
        found, _prefixes = shapes.read(files)
    except ImportError:
        return {"classes": [], "skipped": RDFLIB_MISSING}
    terms = (snapshot or {}).get("terms") or {}
    out = []
    seen: dict = {}
    # {class: [[property IRI]]}: the groups of the sh:or on its nodes
    groups: dict = {}
    for shape in found:
        if not shape.target_class:
            continue
        klass = graphfile.local(shape.target_class)
        if klass not in seen:
            seen[klass] = {
                "id": klass, "shape": shape.name,
                "iri": str(shape.target_class),
                "curie": curie(shape.target_class, prefixes or {}),
                "label": (terms.get(ontology.identifier(klass) or "") or {})
                .get("label"),
                "written": made.written(klass),
                "address": made.address(klass), "properties": [],
                "one_of": [], "constraints": []}
            out.append(seen[klass])
        # several shapes of one class may say the same sh:or: one group
        for group in shape.one_of:
            if list(group) not in groups.setdefault(klass, []):
                groups[klass].append(list(group))
                seen[klass]["one_of"].append(
                    [curie(path, prefixes or {}) for path in group])
        # several shapes may target one class, and one shape may say several
        # things of one path: it is one box with one row per property
        known = {one["path"]: one for one in seen[klass]["properties"]}
        for prop in shape.properties:
            one = {
                "path": graphfile.local(prop.path), "iri": str(prop.path),
                "curie": curie(prop.path, prefixes or {}),
                "label": _label(prop, terms), "min": prop.min_count,
                "max": prop.max_count,
                "constraints": _constraints(prop, klass, made)}
            if one["path"] in known:
                _merge_property(known[one["path"]], one)
            else:
                known[one["path"]] = one
                seen[klass]["properties"].append(one)
    for klass, said in groups.items():
        if said:
            seen[klass]["constraints"].append(
                _one_of_constraint(klass, said, made))
    for klass, said in made.classes.items():
        if klass not in seen:
            out.append({"id": klass, "shape": None, "label": None,
                        "iri": None, "curie": None,
                        "written": made.written(klass),
                        "address": made.address(klass), "properties": [],
                        "one_of": [], "constraints": []})
    return {"classes": out, "skipped": None}


def view(profile, own_raw: Optional[bytes], shown,
         spec_raw: Optional[dict] = None, files: list = (),
         snapshot: Optional[dict] = None, spec=None,
         harvest: Optional[Path] = None) -> dict:
    files_ = graphfile.load(profile, environ={})
    below = graphfile.load(profile, environ={}, skip_own=True)
    drawing = dict(files_.map or {})
    drawn = classes(profile, files_, spec_raw, list(files), snapshot,
                    drawing.get("prefixes"))
    lay = fields(spec, drawing)
    documents = harvest_documents(harvest) if harvest is not None else []
    if documents:
        found = examples(harvest, [one["name"] for one in lay], lay)
        for one in lay:
            one["example"] = found.get(one["name"])
    return {"file": shown(graphfile.path_of(profile)),
            "exists": own_raw is not None,
            "base": sha256(own_raw) if own_raw is not None else None,
            "rules": _rules(profile, files_, below),
            "classes": drawn["classes"], "skipped": drawn["skipped"],
            "constraints": dict(files_.constraints),
            "set": {"classes": dict(files_.classes),
                    "constraints": dict(files_.constraints)},
            "effects": list(graphfile.EFFECTS),
            "map": drawing, "map_owner": files_.owners.get("map", ""),
            "fields": lay, "bricks": bricks_of(profile),
            "presets": presets_of(profile),
            "conditions": graph_conditions(),
            "part_from": list(_blocks().PART_FROM),
            "part_forms": list(_blocks().PART_FORMS),
            "part_absent": list(_blocks().PART_ABSENT),
            "counts": list(graphfile.COUNTS),
            "harvest": harvest is not None, "documents": documents,
            "cost": COST, "gate": GATE}


# -- the fields and the bricks the drawing is made of -----------------------

def _humane(name: str) -> str:
    return name.replace("_", " ").strip().capitalize()


def fields(spec, drawing: dict) -> list:
    """The fields of the harvest as the spec asks them, in spec order: one
    per parameter; then the dimensions of the numbers a box of one node per
    number reads, as fields of their own (unit, carrier, sector, year, ...),
    and what a reading carries of itself (`ROW_KEYS`). A dimension or a
    reading the drawing names is a field wherever it comes from."""
    if spec is None:
        return []
    out = [{"name": uri, "label": one.label, "kind": "field",
            "help": (one.brief or one.description or "")}
           for uri, one in spec.by_uri.items()]
    axes: dict = {}
    boxes = list(drawing.get("boxes") or ())
    wanted: list = []
    for box in boxes:
        if box.get("count") == "per_value":
            of = box.get("of")
            wanted += [of] if isinstance(of, str) else list(of or ())
    for uri in wanted:
        one = spec.by_uri.get(uri)
        for name, axis in (getattr(one, "axes", None) or {}).items():
            axes.setdefault(name, {"label": _humane(name), "of": [],
                                   "help": getattr(axis, "question", "")
                                   or ""})
            axes[name]["of"].append(one.label)
    named = {arrow.get("from") for arrow in drawing.get("arrows") or ()}
    named |= {box.get("value") for box in boxes}
    named |= {box.get("of") for box in boxes
              if isinstance(box.get("of"), str)}
    named -= {box.get("id") for box in boxes}
    every = {name for one in spec.by_uri.values()
             for name in (getattr(one, "axes", None) or {})}
    for name in sorted(n for n in named if isinstance(n, str)):
        base = name[:-4] if name.endswith("_raw") else name
        if name not in axes and name not in spec.by_uri \
                and name not in ROW_KEYS and base in every:
            axes[name] = {"label": _humane(name), "help": "", "of": []}
    out += [{"name": name, "label": one["label"], "kind": "dimension",
             "help": one["help"], "of": one["of"]}
            for name, one in axes.items()]
    if wanted or any(name in named for name in ROW_KEYS):
        out += [{"name": name, "label": _humane(name), "kind": "reading",
                 "help": ""} for name in ROW_KEYS]
    return out


def bricks_of(profile) -> list:
    from docpipe.extraction import bricks
    own = {one.name for one in (profile.component("kg", "BRICKS") or ())}
    out = []
    for name, one in sorted(bricks.registry(profile).items(),
                            key=lambda pair: (pair[1].kind, pair[0])):
        # The brick's own logic as the Python of a block, for the page to
        # show where the form of a block is changed.
        out.append({**one.describe(), "own": name in own,
                    "python": _blocks().python_of(one)})
    return out


def _blocks():
    from docpipe.extraction import graphblocks
    return graphblocks


def python_of_block(profile, ref, kind) -> dict:
    """A block of the drawing as the Python of a block that does the same,
    for the page to show when the form "Python" is chosen:
    {"python", "per", "writes"}; {"python": ""} where *ref* is no block of
    *kind* or a step's source is not to be had."""
    from docpipe.extraction import bricks, graph
    graphblocks = _blocks()
    kind = str(kind or "")
    try:
        registry = bricks.registry(profile)
        space = graph.python_space(profile)
        found = graphblocks.resolve(ref, kind, registry, space)
        code = graphblocks.python_block(ref, kind, registry, space)
    except graphblocks.BlockError:
        return {"python": ""}
    return {"python": code, "per": found.per or "row",
            "writes": found.writes or ""}


def presets_of(profile) -> list:
    """The blocks ready to put in where a brick stands, the core's and the
    profile's own (`bricks.presets`): {name, kind, does, block, own}."""
    from docpipe.extraction import bricks
    own = {one["name"] for one in (profile.component("kg", "PRESETS")
                                   or ())}
    return [{"name": one["name"], "kind": one["kind"], "does": one["does"],
             "block": one["block"], "own": one["name"] in own}
            for one in bricks.presets(profile)]


def graph_conditions() -> list:
    """What a condition of the drawing can be about (`conditions.catalogue`
    with graph): the reading by its keys, what is known of the document."""
    from docpipe.extraction import conditions
    return conditions.catalogue(graph=True)


def harvest_documents(harvest: Optional[Path]) -> list:
    """The documents of a harvest folder, by name."""
    if harvest is None or not Path(harvest).is_dir():
        return []
    return sorted(one.stem for one in Path(harvest).glob("*.jsonl"))


def _shown(value) -> Optional[str]:
    if value is None or value == "":
        return None
    text = value if isinstance(value, str) else json.dumps(
        value, ensure_ascii=False)
    text = " ".join(text.split())
    return text if len(text) <= EXAMPLE_LENGTH \
        else text[:EXAMPLE_LENGTH - 1] + "…"


_EXAMPLES: dict = {}


def examples(harvest: Path, names: list, lay: list) -> dict:
    """{field: {"value", "document"}}: the first reading of each field a
    document of the harvest has, a real one. A parameter is read off the
    rows of its own, a dimension or a reading off any row."""
    from docpipe import jsonl
    folder = Path(harvest)
    paths = sorted(folder.glob("*.jsonl"))[:EXAMPLE_DOCUMENTS]
    stamp = (str(folder), tuple(names), len(paths),
             max((one.stat().st_mtime_ns for one in paths), default=0))
    if stamp in _EXAMPLES:
        return _EXAMPLES[stamp]
    kinds = {one["name"]: one["kind"] for one in lay}
    found: dict = {}
    for path in paths:
        if len(found) == len(names):
            break
        for line in jsonl.read(path):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("kind") != "tuple":
                continue
            for name in names:
                if name in found:
                    continue
                said = (row.get("value") if row.get("parameter") == name
                        else None) if kinds.get(name) == "field" \
                    else row.get(name)
                text = _shown(said)
                if text is not None:
                    found[name] = {"value": text, "document": path.stem}
    _EXAMPLES.clear()
    _EXAMPLES[stamp] = found
    return found


def _text(raw: Optional[bytes]) -> Optional[str]:
    return None if raw is None else raw.decode("utf-8").replace(CR + LF, LF)


def _normal(said: dict) -> dict:
    """A class entry without what every class has where nothing is said:
    written, and named as its writer names it."""
    return {key: value for key, value in (said or {}).items()
            if not (key == "written" and value is True)
            and not (key == "address" and value is None)}


def own_of(profile, data: dict) -> dict:
    """What *profile*'s own file holds of *data* (the whole file as the page
    has it): what differs from what it inherits, and the rules its writer
    reads, which its file starts from where it declares them. The drawing
    is one piece: it is the profile's own where it differs from what the
    line below has."""
    below = graphfile.load(profile, environ={}, skip_own=True)
    mine = {one.name for one in (profile.own("rules", "GRAPH") or ())}
    out = {"classes": {}, "constraints": {}, "rules": {}, "map": {}}
    for klass, said in (data.get("classes") or {}).items():
        said = _normal(said)
        if said != _normal(below.classes.get(klass) or {}):
            out["classes"][klass] = said
    for key, effect in (data.get("constraints") or {}).items():
        if below.constraints.get(key, "report") != effect:
            out["constraints"][key] = effect
    for name, value in (data.get("rules") or {}).items():
        if name in mine or name not in below.rules \
                or below.rules[name] != value:
            out["rules"][name] = value
    if (data.get("map") or {}) != (below.map or {}):
        out["map"] = data.get("map") or {}
    return out


_BOX = re.compile(r"^box (\S+?)[: ]")
_ARROW = re.compile(r"^arrow (\d+)\b")
_ARROW_NAMED = re.compile(r"^arrow (\S+) -> (\S+) (\S+) is drawn twice")


def located(message: str, drawing: dict) -> dict:
    """{"box", "arrow", "message"}: what a sentence of the checks of a
    drawing is about, the box by its id and the arrow by the name the run
    gives it (`graph.arrow_key`); None where it is about neither."""
    from docpipe.extraction.graph import arrow_key
    arrows = list((drawing or {}).get("arrows") or ())
    boxes = {one.get("id") for one in (drawing or {}).get("boxes") or ()
             if isinstance(one, dict)}
    out = {"box": None, "arrow": None, "message": message}
    found = _ARROW.match(message)
    if found and 1 <= int(found.group(1)) <= len(arrows) \
            and isinstance(arrows[int(found.group(1)) - 1], dict):
        try:
            out["arrow"] = arrow_key(arrows[int(found.group(1)) - 1])
        except KeyError:
            pass
        return out
    found = _ARROW_NAMED.match(message)
    if found:
        out["arrow"] = (f"{found.group(1)}>{found.group(2)} "
                        f"{found.group(3)}")
        return out
    found = _BOX.match(message)
    if found and found.group(1) in boxes:
        out["box"] = found.group(1)
    return out


def drawing_problems(profile, drawing: dict, spec=None) -> list:
    """The sentences of the run's own checks of *drawing* against the spec,
    the shapes and the bricks (`graph.check`); the shape of the drawing
    itself is `graphfile.map_problem`, held by `graphfile.parse`."""
    from docpipe.extraction import graph
    try:
        return graph.check(graph.Drawing(drawing), profile, spec)
    except (graph.GraphError, KeyError, TypeError, ValueError) as exc:
        return [f"the drawing cannot be checked: {exc}"]


def judge(profile, own_raw: Optional[bytes], data, name: str,
          spec=None) -> dict:
    """What a save of *data* ({"classes", "constraints", "rules", "map"},
    the whole file as the page has it) would do. A problem of the drawing
    is in `problems` with the box or arrow it is about."""
    errors = []
    problems = []
    old = _text(own_raw)
    newline = CR + LF if (CR + LF).encode() in (own_raw or b"") else LF
    known = graphfile.declared(profile)
    new = old
    if not isinstance(data, dict):
        errors.append("the body needs \"data\": the graph file as an object")
    else:
        try:
            whole = graphfile.parse(json.dumps(data), name, known)
            drawn = whole.get("map") or {}
            if drawn:
                for said in drawing_problems(profile, drawn, spec):
                    problems.append(located(said, drawn))
                    errors.append(said)
            if not errors:
                own = own_of(profile, whole)
                empty = not any(own.values())
                new = None if empty else graphfile.dump(own, known)
        except graphfile.GraphError as exc:
            said = str(exc)
            errors.append(said)
            problems.append(located(said.split("map: ", 1)[-1],
                                    data.get("map")))
    writes = ("unchanged" if new == old else "created" if old is None
              else "removed" if new is None else "changed")
    diff = [] if writes == "unchanged" or errors else list(
        difflib.unified_diff((old or "").splitlines(),
                             (new or "").splitlines(), name, name,
                             lineterm=""))
    says = [COST] if writes != "unchanged" and not errors else []
    if not errors and any(effect == "stop" for effect in
                          (data.get("constraints") or {}).values()):
        says.append(GATE)
    return {"ok": not errors, "errors": errors, "problems": problems,
            "file": name,
            "writes": writes if not errors else "unchanged", "diff": diff,
            "says": says,
            "text": None if new is None or errors
            else new.replace(LF, newline)}


def save(profile, own_raw: Optional[bytes], data, base: Optional[str],
         name: str, spec=None) -> tuple:
    """(what the page is told, the bytes to write or None, whether the file
    is to be removed)."""
    report = judge(profile, own_raw, data, name, spec)
    text = report.pop("text")
    if not report["ok"]:
        return {"saved": False, "reason": "invalid",
                "errors": report["errors"], "problems": report["problems"],
                "message": "; ".join(report["errors"])}, None, False
    if base != (sha256(own_raw) if own_raw is not None else None):
        return {"saved": False, "reason": "moved",
                "message": "the file changed on disk since the page loaded "
                           "it; reload it before saving"}, None, False
    told = {"saved": True, "writes": report["writes"], "file": name}
    if report["writes"] == "unchanged":
        return {**told, "base": base}, None, False
    if text is None:
        return {**told, "base": None}, None, True
    written = text.encode("utf-8")
    return {**told, "base": sha256(written)}, written, False


# -- the preview ------------------------------------------------------------

class PreviewError(ValueError):
    """What stops a preview; the sentence is the page's to show."""


def preview(profile, data, harvest: Optional[Path], document,
            db: Optional[Path] = None, strict: bool = False,
            spec=None, root: Optional[Path] = None) -> dict:
    """One document of *harvest* written as *data* (the graph file as the
    page has it, drawing and rules) says, with the run's own program, into
    no file of the profile: {"document", "text", "triples", "nodes"}. No
    model is asked; the rows are the harvest's."""
    used = Path(db) if db and Path(db).is_file() else None
    text, rows = _written(profile, data, harvest, document, used, strict,
                          spec, root, None)
    text = text or ""
    triples = None
    try:
        from rdflib import Graph
        triples = len(Graph().parse(data=text, format="turtle"))
    except Exception:                  # the text is shown either way
        pass
    return {"document": document, "text": text, "tuples": len(rows),
            "triples": triples, "strict": strict,
            "database": str(used) if used else None}


def _written(profile, data, harvest: Optional[Path], document, used,
             strict: bool, spec, root: Optional[Path], prepare):
    """(the Turtle, the rows) of one document of *harvest* written as *data*
    says, with the run's own program and into no file of the profile;
    *prepare(writer)* is called before it is written. PreviewError with the
    reason where it cannot be."""
    from docpipe import jsonl
    from docpipe.extraction import graph
    if harvest is None:
        raise PreviewError("the page was started without a harvest "
                           "(docpipe edit --harvest DIR): there is nothing "
                           "to write a graph of")
    if document not in harvest_documents(harvest):
        raise PreviewError(f"the harvest has no document {document!r}")
    known = graphfile.declared(profile)
    try:
        whole = graphfile.parse(json.dumps(data), "the page's graph file",
                                known)
    except graphfile.GraphError as exc:
        raise PreviewError(str(exc))
    if not whole.get("map"):
        raise PreviewError("the graph file has no drawing: nothing says how "
                           "the harvest becomes a graph")
    problems = drawing_problems(profile, whole["map"], spec)
    if problems:
        raise PreviewError(problems[0])
    rows = []
    for line in jsonl.read(Path(harvest) / f"{document}.jsonl"):
        if line.strip():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("kind") == "tuple":
                rows.append(row)
    where = Path(root) if root is not None else probe_root()
    where = where / f"preview-{os.getpid()}-{profile.name}"
    where.mkdir(parents=True, exist_ok=True)
    edited = where / graphfile.FILE
    edited.write_text(graphfile.dump(whole, known), encoding="utf-8",
                      newline="\n")
    with PREVIEW_LOCK:
        was = os.environ.get(graphfile.ENV)
        os.environ[graphfile.ENV] = str(edited)
        graphfile.reset()
        try:
            serializer = graph.make_serializer(profile, used, strict=strict)
            if prepare is not None:
                prepare(serializer.writer)
            return serializer(document, rows), rows
        except PreviewError:
            raise
        except Exception as exc:       # what the program raises is the reason
            raise PreviewError(f"the drawing cannot be written: {exc}")
        finally:
            if was is None:
                os.environ.pop(graphfile.ENV, None)
            else:
                os.environ[graphfile.ENV] = was
            graphfile.reset()


# -- trying one block --------------------------------------------------------

# What a block of the drawing is called with at each place: the place's key
# and the kind of block it takes.
DOCUMENT_PLACES = {"facts": "facts", "admit": "condition", "check": "check",
                   "claims": "claims"}
BOX_PLACES = {"admit": "condition", "when": "condition", "names": "nodes",
              "class_brick": "class", "evidence": "evidence",
              "name_brick": "name", "address": "address"}
TRIED_MOST = 200              # calls of one block shown, the first ones
SHOWN_KEYS = ("parameter", "value", "quantity", "scenario", "year",
              "carrier", "sector", "technology", "aggregation", "unit",
              "spatial_scope", "spatial_scope_raw", "role")


def block_at(drawing: dict, where: dict) -> tuple:
    """(the block, the kind it is) at *where* of *drawing*: {"document":
    key, "index"}, {"box": id, "key", "index"} or {"arrow": number from 1}.
    An arrow's brick is made a block of its own first, so it stays the one
    object the writer is given."""
    where = where or {}
    if "arrow" in where:
        arrows = drawing.get("arrows") or []
        number = int(where["arrow"])
        if not 1 <= number <= len(arrows):
            raise PreviewError(f"the drawing has no arrow {number}")
        arrow = arrows[number - 1]
        if not isinstance(arrow.get("brick"), dict):
            arrow["brick"] = {"brick": arrow.get("brick") or "text",
                              "settings": arrow.pop("settings", None) or {}}
        return arrow["brick"], "object"
    if "document" in where:
        holder, places = drawing.get("document") or {}, DOCUMENT_PLACES
        key = where["document"]
    else:
        holder = next((one for one in drawing.get("boxes") or ()
                       if one.get("id") == where.get("box")), None)
        if holder is None:
            raise PreviewError(f"the drawing has no box {where.get('box')!r}")
        places, key = BOX_PLACES, where.get("key")
    if key not in places:
        raise PreviewError(f"no block stands at {key!r}")
    said = holder.get(key)
    if isinstance(said, list):
        index = int(where.get("index") or 0)
        if not 0 <= index < len(said):
            raise PreviewError(f"{key} has no block {index + 1}")
        said = said[index]
    if said is None:
        raise PreviewError(f"no block stands at {key!r}")
    return said, places[key]


def _shown(value, depth: int = 0):
    """A value as the page shows it: what JSON takes, cut short."""
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value if not isinstance(value, str) else value[:400]
    if isinstance(value, dict):
        return {str(k): _shown(v, depth + 1) for k, v in
                list(value.items())[:40]}
    if isinstance(value, (list, tuple)):
        return [_shown(v, depth + 1) for v in list(value)[:40]]
    return str(value)[:400]


def _reading(call) -> dict:
    """What a block was given, as the page shows it."""
    if call.row:
        return {key: _shown(call.row.get(key)) for key in SHOWN_KEYS
                if call.row.get(key) not in (None, "")}
    if call.node is not None:
        return {"node": call.node.iri or call.node.name,
                "readings": len(call.rows or call.node.rows or ())}
    if call.value is not None:
        return {"value": _shown(call.value)}
    return {"document": getattr(call.doc, "name", None)}


def try_block(profile, data, harvest: Optional[Path], document, where,
              db: Optional[Path] = None, strict: bool = False, spec=None,
              root: Optional[Path] = None) -> dict:
    """One document written as *data* says, and what the block at *where*
    was given and gave each time it was called, the first `TRIED_MOST`:
    {"document", "kind", "calls", "shown": [{"reading", "gives"}]}; for an
    address made of parts, each number's parts and its address. Nothing is
    saved and no model is asked."""
    graphblocks = _blocks()
    if not isinstance(data, dict) or not isinstance(data.get("map"), dict):
        raise PreviewError("the body needs \"data\": the graph file with "
                           "its drawing")
    shown: list = []
    calls = [0]
    told: dict = {}

    def prepare(writer) -> None:
        ref, kind = block_at(writer.drawing.raw, where)
        told["kind"] = kind
        if kind == "address" and not graphblocks.shape(ref):
            box = writer.drawing.box[where["box"]]
            minted = writer.minted_address

            def recorded(doc, of, node, row=None, label=""):
                made = minted(doc, of, node, row, label)
                if of is box:
                    calls[0] += 1
                    if len(shown) < TRIED_MOST:
                        parts = graphblocks.parts_name(
                            doc, of, list(ref.get("from") or ()), node, row,
                            label)
                        shown.append({"reading": _reading(
                            graphblocks_call(row, node)),
                            "parts": parts, "gives": made[0]})
                return made
            writer.minted_address = recorded
            return
        found = writer.brick(ref, kind)

        def run(call, original=found.run):
            out = original(call)
            calls[0] += 1
            if len(shown) < TRIED_MOST:
                shown.append({"reading": _reading(call),
                              "gives": _shown(out)})
            return out
        writer._blocks[(id(ref), kind)] = (ref, dataclasses.replace(
            found, run=run))

    def graphblocks_call(row, node):
        from docpipe.extraction.bricks import Call
        return Call(row=row, node=node)

    used = Path(db) if db and Path(db).is_file() else None
    _written(profile, data, harvest, document, used, strict, spec, root,
             prepare)
    return {"document": document, "kind": told.get("kind"),
            "calls": calls[0], "shown": shown, "most": TRIED_MOST}


# -- the probe --------------------------------------------------------------

def probe_root() -> Path:
    return Path(tempfile.gettempdir()) / PROBE_FOLDER


def _run(profile, harvest: Path, db: Path, out: Path,
         graph_file: Optional[Path]) -> dict:
    environ = dict(os.environ)
    environ.pop(graphfile.ENV, None)
    if graph_file is not None:
        environ[graphfile.ENV] = str(graph_file)
    done = subprocess.run(
        [sys.executable, "-m", "docpipe.editor.graphprobe", profile.name,
         str(harvest), str(db), str(out)], capture_output=True, text=True,
        encoding="utf-8", errors="replace", env=environ,
        timeout=PROBE_TIMEOUT)
    if done.returncode != 0:
        tail = (done.stderr or done.stdout or "").strip().splitlines()[-5:]
        raise RuntimeError("the probe did not write a graph: "
                           + " / ".join(tail))
    return json.loads((out / "probe.json").read_text(encoding="utf-8"))


def compare(before: dict, after: dict) -> dict:
    """What the edited file does against the saved one, per document and
    per constraint."""
    documents = []
    for name in sorted(set(before["documents"]) | set(after["documents"])):
        a = before["documents"].get(name) or {}
        b = after["documents"].get(name) or {}
        if (a.get("kept"), a.get("violations"), len(a.get("left_out") or ())
                ) != (b.get("kept"), b.get("violations"),
                      len(b.get("left_out") or ())):
            documents.append({"document": name, "before": a, "after": b})
    keys = sorted(set(before["violations"]) | set(after["violations"]))
    return {"documents": documents,
            "violations": [{"key": key,
                            "before": before["violations"].get(key, 0),
                            "after": after["violations"].get(key, 0)}
                           for key in keys],
            "classes": {klass: {"before": before["classes"].get(klass, 0),
                                "after": after["classes"].get(klass, 0)}
                        for klass in sorted(set(before["classes"])
                                            | set(after["classes"]))},
            "readdressed": after["done"].get("readdressed", 0),
            # what the spec's `also` wrote under further predicates
            "also": after["done"].get("also", 0),
            "triples": {"before": before["triples"],
                        "after": after["triples"]}}


def probe(profile, data, harvest: Path, db: Path,
          root: Optional[Path] = None, stamp: str = "") -> dict:
    """The graph of *harvest* written with the saved graph file and with
    *data*, into a folder of *root*; what differs."""
    known = graphfile.declared(profile)
    whole = graphfile.parse(json.dumps(data), "the page's graph file", known)
    root = Path(root) if root is not None else probe_root()
    where = root / f"probe-{stamp or os.getpid()}-{profile.name}"
    where.mkdir(parents=True, exist_ok=True)
    edited = where / graphfile.FILE
    edited.write_text(graphfile.dump(whole, known), encoding="utf-8")
    before = _run(profile, harvest, db, where / "saved", None)
    after = _run(profile, harvest, db, where / "edited", edited)
    return {"folder": str(where), "saved": before, "edited": after,
            "differs": compare(before, after)}
