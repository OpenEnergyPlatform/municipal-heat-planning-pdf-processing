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
  class whether it is written and its address rule; the rules the writer
  declares, each with its value, what it inherits and the setting that wins
  over it.
- `judge` and `save`: an edited graph file, read by the run's own parser.
  A profile that extends another writes only what differs from what it
  inherits, and the rules its writer reads.
- `probe`: the graph of the harvest the page was given, written twice into
  the temp directory, with the saved file and with the edited one, and what
  differs: per document the nodes kept and left out, per constraint its
  violations, the nodes named anew. No model is asked and nothing is saved.

Author: Felix Vossel
"""
from __future__ import annotations

import difflib
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

from docpipe import graphfile, ontology

CR, LF = "\r", "\n"
PROBE_FOLDER = "docpipe-graph-probe"
PROBE_TIMEOUT = 1800          # seconds, one writing of the graph
COST = ("A change of the graph file costs no model: it takes effect the next "
        "time the graph is written from the stored harvest. \"Write probe\" "
        "shows what it does to the harvest the page was given.")
GATE = ("\"stop\" works through the gate (python -m docpipe.extraction.gate), "
        "which shuts before a job starts its model; no job script runs the "
        "gate yet.")
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
            "name": name, "group": one.group, "kind": one.kind,
            "help": one.help, "least": one.least, "most": one.most,
            "choices": list(one.choices), "columns": list(one.columns),
            "of": one.of, "empty": one.empty, "decided": one.decided,
            "where": one.where, "setting": one.env,
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


def classes(profile, made, spec_raw: Optional[dict], files: list,
            snapshot: Optional[dict]) -> dict:
    """{"classes": [...], "skipped": why or None}: the shapes' classes with
    their properties, the fields that write each and the constraints."""
    if not files:
        return {"classes": [], "skipped": "no shapes file: fetch the "
                                          "sources first (Sources tab)"}
    try:
        from docpipe.compile import draft, shapes
        found, _prefixes = shapes.read(files)
    except ImportError:
        return {"classes": [], "skipped": "rdflib is not installed"}
    pairs: list = []
    if spec_raw is not None:
        draft.differences(found, draft.read_as_shapes(spec_raw, profile),
                          pairs=pairs)
    fields: dict = {}
    for parameter, shape, path in pairs:
        fields.setdefault((shape, path), [])
        if parameter not in fields[(shape, path)]:
            fields[(shape, path)].append(parameter)
    terms = (snapshot or {}).get("terms") or {}
    out = []
    seen = set()
    for shape in found:
        if not shape.target_class:
            continue
        klass = graphfile.local(shape.target_class)
        seen.add(klass)
        out.append({
            "id": klass, "shape": shape.name,
            "label": (terms.get(ontology.identifier(klass) or "") or {})
            .get("label"),
            "written": made.written(klass), "address": made.address(klass),
            "properties": [{
                "path": graphfile.local(prop.path),
                "label": prop.name, "min": prop.min_count,
                "max": prop.max_count,
                "fields": fields.get((shape.name,
                                      graphfile.local(prop.path)), []),
                "constraints": _constraints(prop, klass, made)}
                for prop in shape.properties]})
    for klass, said in made.classes.items():
        if klass not in seen:
            out.append({"id": klass, "shape": None, "label": None,
                        "written": made.written(klass),
                        "address": made.address(klass), "properties": []})
    return {"classes": out, "skipped": None}


def view(profile, own_raw: Optional[bytes], shown,
         spec_raw: Optional[dict] = None, files: list = (),
         snapshot: Optional[dict] = None) -> dict:
    files_ = graphfile.load(profile, environ={})
    below = graphfile.load(profile, environ={}, skip_own=True)
    drawn = classes(profile, files_, spec_raw, list(files), snapshot)
    return {"file": shown(graphfile.path_of(profile)),
            "exists": own_raw is not None,
            "base": sha256(own_raw) if own_raw is not None else None,
            "rules": _rules(profile, files_, below),
            "classes": drawn["classes"], "skipped": drawn["skipped"],
            "constraints": dict(files_.constraints),
            "set": {"classes": dict(files_.classes),
                    "constraints": dict(files_.constraints)},
            "effects": list(graphfile.EFFECTS),
            "cost": COST, "gate": GATE}


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
    reads, which its file starts from where it declares them."""
    below = graphfile.load(profile, environ={}, skip_own=True)
    mine = {one.name for one in (profile.own("rules", "GRAPH") or ())}
    out = {"classes": {}, "constraints": {}, "rules": {}}
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
    return out


def judge(profile, own_raw: Optional[bytes], data, name: str) -> dict:
    """What a save of *data* ({"classes", "constraints", "rules"}, the whole
    file as the page has it) would do."""
    errors = []
    old = _text(own_raw)
    newline = CR + LF if (CR + LF).encode() in (own_raw or b"") else LF
    known = graphfile.declared(profile)
    new = old
    if not isinstance(data, dict):
        errors.append("the body needs \"data\": the graph file as an object")
    else:
        try:
            whole = graphfile.parse(json.dumps(data), name, known)
            own = own_of(profile, whole)
            empty = not any(own.values())
            new = None if empty else graphfile.dump(own, known)
        except graphfile.GraphError as exc:
            errors.append(str(exc))
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
    return {"ok": not errors, "errors": errors, "file": name,
            "writes": writes if not errors else "unchanged", "diff": diff,
            "says": says,
            "text": None if new is None or errors
            else new.replace(LF, newline)}


def save(profile, own_raw: Optional[bytes], data, base: Optional[str],
         name: str) -> tuple:
    """(what the page is told, the bytes to write or None, whether the file
    is to be removed)."""
    report = judge(profile, own_raw, data, name)
    text = report.pop("text")
    if not report["ok"]:
        return {"saved": False, "reason": "invalid",
                "errors": report["errors"],
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


# -- the probe -----------------------------------------------------------------

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
