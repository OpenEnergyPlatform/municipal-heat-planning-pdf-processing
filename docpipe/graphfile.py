"""
graphfile.py: How a harvest becomes the graph, read from a file of the
profile (owner, 2026-11-10: "sodass man steuern kann, wie die Ernte in den
Graphen aufgenommen wird und welche constraints erfüllt sein müssen").

    <profile folder>/graph.json

    {"classes": {class: {"written": false} |
                        {"address": {"folder": ..., "key": [property, ...],
                                     "base": ...}}},
     "constraints": {"<constraint> <property> <class>": effect},
     "rules": {name: value}}

What a writer does stays code (`profiles/<name>/kg.py`); the file says what
the writer is to do with it:

- a class that is not written: its nodes, and every triple that names them,
  leave the written graph;
- an address rule: the nodes of the class are named anew, the folder under
  the writer's base and a UUID over the values of the named properties, and
  every triple that names them follows;
- a constraint's effect, after the written graph is held to the shapes:
  `report` (what every constraint does where the file says nothing),
  `leave_out_value` (the node the violation is about leaves the graph),
  `leave_out_paper` (every node of its document does) or `stop` (the gate,
  `docpipe.extraction.gate`, shuts before a job starts its model);
- the rules a profile's writer declares (`rules.py: GRAPH`), each read by the
  writer where it applies it.

A class is named by its identifier (`OEO_00030022`), a property by its
identifier or `prefix:name`, a constraint by the words the validation
reports it with (`MinCount OEO_00390079 OEO_00020227`: the constraint, the
property, the class of the node). The file of the default profile has no
entry; a profile writes what its writer reads and what it sets otherwise,
laid over the files it extends entry by entry. A file named by
`DOCPIPE_GRAPH_FILE` is laid over all of them: what `docpipe edit` writes a
probe with before anything is saved.

With nothing set, the written graph is the writer's, byte for byte: no file
is rewritten. Where something is set, the graph is edited as text, block by
block, so the writer's comments stay; a block the edit cannot read is
written anew by rdflib, and the result is held against the graph the rule
asks for before it is written.

Author: Felix Vossel
"""
from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .rules import Rule, _setting as rule_setting, \
    problem as rule_problem

FILE = "graph.json"
DEFAULT = Path(__file__).resolve().parent / "builtin" / "default" / FILE
DEFAULT_NAME = "default"
ENV = "DOCPIPE_GRAPH_FILE"
EFFECTS = ("report", "leave_out_value", "leave_out_paper", "stop")
SECTIONS = ("classes", "constraints", "rules")
ADDRESS_KEYS = ("folder", "key", "base")


class GraphError(ValueError):
    """A graph file a run cannot read. It names the file and the entry."""


@dataclass(frozen=True)
class Graph:
    classes: dict = field(default_factory=dict)
    constraints: dict = field(default_factory=dict)
    rules: dict = field(default_factory=dict)
    owners: dict = field(default_factory=dict)
    files: tuple = ()
    sha256: str = ""

    def written(self, klass: str) -> bool:
        return (self.classes.get(klass) or {}).get("written", True)

    def address(self, klass: str) -> Optional[dict]:
        return (self.classes.get(klass) or {}).get("address")

    def effect(self, key: str) -> str:
        return self.constraints.get(key, "report")

    def acts(self) -> bool:
        """Whether the file asks anything of a written graph."""
        return any(not self.written(k) or self.address(k)
                   for k in self.classes) or any(
            effect in ("leave_out_value", "leave_out_paper")
            for effect in self.constraints.values())


def _nearest(name, known) -> str:
    close = difflib.get_close_matches(str(name), list(known), n=3, cutoff=0.6)
    return f" (did you mean {', '.join(close)}?)" if close else ""


def declared(profile) -> dict:
    """{name: Rule} the writers of *profile*'s line declare."""
    out: dict = {}
    if profile is None or not callable(getattr(profile, "lineage", None)):
        return out
    for one in reversed(profile.lineage()):
        for made in (one.own("rules", "GRAPH") or ()):
            if isinstance(made, Rule):
                out[made.name] = made
    return out


def _class_problem(name: str, said) -> Optional[str]:
    if not re.fullmatch(r"[A-Za-z]+_\d+|[A-Za-z][\w.-]*:[\w.-]+", str(name)):
        return f"class {name!r} is no identifier (OEO_00030022)"
    if not isinstance(said, dict) or set(said) - {"written", "address"}:
        return (f"class {name}: an object with \"written\" and/or "
                f"\"address\"")
    if "written" in said and not isinstance(said["written"], bool):
        return f"class {name}: written is true or false"
    address = said.get("address")
    if address is None:
        return None
    if not isinstance(address, dict):
        return f"class {name}: an address is an object"
    unknown = sorted(set(address) - set(ADDRESS_KEYS))
    if unknown:
        return (f"class {name}: an address has no {unknown[0]!r}"
                f"{_nearest(unknown[0], ADDRESS_KEYS)}")
    folder = address.get("folder")
    if not isinstance(folder, str) or not re.fullmatch(r"[a-z][a-z0-9_-]*",
                                                       folder):
        return f"class {name}: the address folder is a lower-case word"
    key = address.get("key")
    if not isinstance(key, list) or not key or not all(
            isinstance(one, str) and one for one in key):
        return (f"class {name}: the address key names the properties whose "
                f"values make the address, at least one")
    base = address.get("base")
    if base is not None and not (isinstance(base, str)
                                 and re.match(r"https?://\S+/$", base)):
        return f"class {name}: a base is an address that ends in /"
    return None


def parse(raw: str, where, known: Optional[dict] = None) -> dict:
    """The entries of the text *raw*, read strictly: {"classes",
    "constraints", "rules"}."""
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise GraphError(f"{where}: {exc}") from exc
    if not isinstance(data, dict) or set(data) - set(SECTIONS):
        raise GraphError(f"{where}: a graph file is one JSON object with "
                         f"{', '.join(SECTIONS)}")
    out = {section: data.get(section) or {} for section in SECTIONS}
    if not all(isinstance(out[section], dict) for section in SECTIONS):
        raise GraphError(f"{where}: {', '.join(SECTIONS)} are objects")
    for name, said in out["classes"].items():
        wrong = _class_problem(name, said)
        if wrong:
            raise GraphError(f"{where}: {wrong}")
    for key, effect in out["constraints"].items():
        if effect not in EFFECTS:
            raise GraphError(f"{where}: constraint {key}: {effect!r} is "
                             f"none of {', '.join(EFFECTS)}"
                             f"{_nearest(effect, EFFECTS)}")
        if len(str(key).split()) != 3:
            raise GraphError(f"{where}: constraint {key!r}: the constraint, "
                             f"the property and the class, by spaces")
    known = {} if known is None else known
    for name, value in out["rules"].items():
        said = rule_problem(name, value, known)
        if said is not None:
            raise GraphError(f"{where}: {said}")
    return out


def dump(data: dict, known: Optional[dict] = None, newline: str = "\n") -> str:
    """A graph file's text in the one form it is written in."""
    known = {} if known is None else known
    rules = data.get("rules") or {}
    ordered = {name: rules[name] for name in known if name in rules}
    ordered.update({k: v for k, v in rules.items() if k not in ordered})
    text = json.dumps({"classes": dict(sorted((data.get("classes") or {})
                                              .items())),
                       "constraints": dict(sorted(
                           (data.get("constraints") or {}).items())),
                       "rules": ordered},
                      ensure_ascii=False, indent=2) + "\n"
    return text if newline == "\n" else text.replace("\n", newline)


def path_of(profile) -> Path:
    return Path(profile.package_dir) / FILE


def line(profile) -> list:
    """[(profile name, path)] of the files, nearest first, the default's
    last."""
    if profile is None or getattr(profile, "package_dir", None) is None:
        return [(DEFAULT_NAME, DEFAULT)]
    out = [(one.name, path_of(one)) for one in profile.lineage()]
    if not any(Path(path) == DEFAULT for _name, path in out):
        out.append((DEFAULT_NAME, DEFAULT))
    return out


def _lay(into: dict, owners: dict, said: dict, owner: str) -> None:
    for section in SECTIONS:
        for key, value in said[section].items():
            if section == "classes":
                into[section][key] = {**into[section].get(key, {}), **value}
            else:
                into[section][key] = value
            owners[f"{section}/{key}"] = owner


def load(profile=None, environ=None, skip_own: bool = False) -> Graph:
    """The graph file of *profile*: the default's, the files of its line
    laid over it farthest first, and the file `DOCPIPE_GRAPH_FILE` names
    over all. *skip_own* leaves the profile's own file and the named one
    out: what it inherits."""
    environ = os.environ if environ is None else environ
    known = declared(profile)
    places = list(reversed(line(profile)))
    if skip_own:
        places = places[:-1]
    data = {section: {} for section in SECTIONS}
    owners: dict = {}
    files, digest = [], hashlib.sha256()
    for owner, path in places:
        if not Path(path).is_file():
            continue
        raw = Path(path).read_text(encoding="utf-8")
        _lay(data, owners, parse(raw, path, known), f"{FILE} of {owner}")
        files.append(str(path))
        digest.update(raw.encode("utf-8"))
    named = environ.get(ENV) if not skip_own else None
    if named:
        raw = Path(named).read_text(encoding="utf-8")
        _lay(data, owners, parse(raw, named, known), ENV)
        files.append(named)
        digest.update(raw.encode("utf-8"))
    for name, one in known.items():
        if name not in data["rules"] and not skip_own:
            raise GraphError(f"no graph file of {getattr(profile, 'name', '')}"
                             f"'s line names the rule {name}, which its "
                             f"writer reads")
    # A setting wins over the files (`Rule.env`), as for the rules of
    # `docpipe.rules`; what it inherits has none.
    if not skip_own:
        for name, one in known.items():
            raw = environ.get(one.env) if one.env else None
            if raw is None:
                continue
            data["rules"][name] = rule_setting(one, raw)
            if environ is os.environ:
                from . import settings
                owners[f"rules/{name}"] = settings.origin(one.env)
            else:
                owners[f"rules/{name}"] = "environment"
    return Graph(data["classes"], data["constraints"], data["rules"], owners,
                 tuple(files), digest.hexdigest())


_cache: dict = {}
_envs: dict = {}


def get(name: str, owner: str):
    """The value of the graph rule *name* of the profile called *owner*,
    as its files, `DOCPIPE_GRAPH_FILE` and the settings of its rules say it
    now."""
    from .profile import load_profile
    envs = _envs.get(owner)
    if envs is None:
        envs = _envs[owner] = tuple(sorted({
            one.env for one in declared(load_profile(owner)).values()
            if one.env}))
    key = (owner, os.environ.get(ENV),
           tuple(os.environ.get(env) for env in envs))
    if key not in _cache:
        _cache[key] = load(load_profile(owner))
    rules = _cache[key].rules
    if name not in rules:
        raise GraphError(f"{name!r} is no graph rule of {owner}")
    return rules[name]


def reset() -> None:
    _cache.clear()
    _envs.clear()


# -- what the file does to a written graph -------------------------------------

_PREFIX = re.compile(r"^@prefix\s+([\w-]*):\s*<([^>]+)>\s*\.\s*$", re.M)
_SUBJECT = re.compile(r"^<([^>]+)>\s*$")
_ID = re.compile(r"([A-Za-z]+_\d+)$")


def local(iri) -> str:
    text = str(iri)
    return re.split(r"[/#]", text)[-1]


def _expand(name: str, prefixes: dict) -> str:
    if name.startswith("http"):
        return name
    prefix, colon, rest = name.partition(":")
    if colon and prefix in prefixes:
        return prefixes[prefix] + rest
    return name


def _parsed(text: str):
    from rdflib import Graph as RdfGraph
    return RdfGraph().parse(data=text, format="turtle")


def _blocks(text: str) -> list:
    return text.split("\n\n")


def _entries(block: str) -> Optional[tuple]:
    """(subject line, [(comments, predicate, [objects])]) of a subject
    block as the writers write it, None where it is not one."""
    lines = block.split("\n")
    if not lines or not _SUBJECT.match(lines[0]):
        return None
    entries, comments = [], []
    for line_ in lines[1:]:
        if not line_.strip():
            continue
        stripped = line_.strip()
        if stripped.startswith("#"):
            comments.append(line_)
            continue
        end = stripped[-2:] if len(stripped) > 2 else ""
        if end not in (" ,", " ;", " ."):
            return None
        body = stripped[:-2]
        if line_.startswith("        ") and entries \
                and entries[-1][3] == " ,":
            entries[-1][2].append(body)
            entries[-1][3] = end
            continue
        if not line_.startswith("    ") or line_.startswith("     "):
            return None
        predicate, _, obj = body.partition(" ")
        entries.append([comments, predicate, [obj], end])
        comments = []
    if comments or not entries or entries[-1][3] != " .":
        return None
    return lines[0], entries


def _render(subject: str, entries: list) -> str:
    out = [subject]
    for number, (comments, predicate, objects, _end) in enumerate(entries):
        out += comments
        last = number == len(entries) - 1
        for index, obj in enumerate(objects):
            end = " ," if index < len(objects) - 1 else (" ." if last
                                                         else " ;")
            out.append(f"    {predicate} {obj}{end}" if index == 0
                       else f"        {obj}{end}")
    return "\n".join(out)


def _drop(text: str, nodes: set) -> str:
    """*text* without the blocks of *nodes* and without every triple that
    names one of them; the writers' comments stay."""
    named = {f"<{node}>" for node in nodes}
    out = []
    for block in _blocks(text):
        head = block.split("\n", 1)[0]
        found = _SUBJECT.match(head)
        if found and found.group(1) in nodes:
            continue
        if not any(token in block for token in named):
            out.append(block)
            continue
        parsed = _entries(block)
        if parsed is None or _render(*parsed) != block.rstrip("\n"):
            raise ValueError("a block the edit cannot read")
        subject, entries = parsed
        kept = []
        for comments, predicate, objects, end in entries:
            left = [obj for obj in objects if obj not in named]
            if any(token in obj for obj in left for token in named):
                raise ValueError("a node named inside a value")
            if left:
                kept.append([comments, predicate, left, end])
        if kept:
            out.append(_render(subject, kept) + block[len(block.rstrip(
                "\n")):])
    return "\n\n".join(out)


def _without(graph, nodes: set):
    """The rdflib graph without every triple naming one of *nodes*."""
    from rdflib import URIRef
    for node in nodes:
        ref = URIRef(node)
        graph.remove((ref, None, None))
        graph.remove((None, None, ref))
    return graph


def remove(text: str, nodes: set) -> str:
    """*text* without *nodes*: edited as text where every block can be
    read, else written anew by rdflib; held against the graph the removal
    asks for either way."""
    from rdflib.compare import isomorphic
    if not nodes:
        return text
    wanted = _without(_parsed(text), nodes)
    try:
        edited = _drop(text, nodes)
        if isomorphic(_parsed(edited), wanted):
            return edited
    except ValueError:
        pass
    return wanted.serialize(format="turtle")


def addresses(text: str, made: Graph, base: str) -> dict:
    """{old IRI: new IRI} for the nodes of every class with an address
    rule."""
    from rdflib import RDF, URIRef
    rules = {klass: made.address(klass) for klass in made.classes
             if made.address(klass)}
    if not rules:
        return {}
    graph = _parsed(text)
    prefixes = dict(_PREFIX.findall(text))
    out = {}
    for node, klass in graph.subject_objects(RDF.type):
        rule = rules.get(local(klass))
        if not rule or not isinstance(node, URIRef):
            continue
        parts = []
        for name in rule["key"]:
            predicate = URIRef(_expand(name, prefixes))
            found = sorted(str(one) for one in graph.objects(node, predicate))
            parts.append(f"{name}=" + ",".join(found))
        made_id = uuid.uuid5(uuid.NAMESPACE_URL, "|".join(parts))
        new = f"{rule.get('base') or base}{rule['folder']}/{made_id}"
        if new != str(node):
            out[str(node)] = new
    return out


def readdress(text: str, moved: dict) -> str:
    for old, new in moved.items():
        text = text.replace(f"<{old}>", f"<{new}>")
    return text


def of_class(text: str, classes: set) -> set:
    from rdflib import RDF, URIRef
    graph = _parsed(text)
    return {str(node) for node, klass in graph.subject_objects(RDF.type)
            if local(klass) in classes and isinstance(node, URIRef)}


def violations(text: str, shapes: list, context=()) -> list:
    """[(constraint key, focus node)] of the graph held to *shapes*."""
    from rdflib import Graph as RdfGraph
    shapes_graph = RdfGraph()
    for path in shapes:
        shapes_graph.parse(str(path), format="turtle")
    return violations_of(_parsed(text), shapes_graph, context)


def violations_of(data, shapes_graph, context=()) -> list:
    """[(constraint key, focus node)] of the rdflib graph *data* held to the
    rdflib graph *shapes_graph*, with what the target graph holds about the
    nodes it points at (*context*). The key is the constraint, the path and
    the focus node's class: what a constraint of the file names."""
    from pyshacl import validate
    from rdflib import RDF, Namespace

    from . import ontology
    sh = Namespace("http://www.w3.org/ns/shacl#")
    ontology.with_context(data, context)
    _conforms, results, _text = validate(data, shacl_graph=shapes_graph,
                                         advanced=True)
    out = []
    for result in results.subjects(RDF.type, sh.ValidationResult):
        focus = results.value(result, sh.focusNode)
        path = results.value(result, sh.resultPath)
        component = results.value(result, sh.sourceConstraintComponent)
        classes = sorted(local(one) for one in data.objects(focus, RDF.type))
        key = " ".join((local(component).replace("ConstraintComponent", ""),
                        local(path) if path is not None else "-",
                        classes[0] if classes else "?"))
        out.append((key, str(focus)))
    return out


def finish(path: Path, made: Graph, base: str, shapes: list = (),
           context=(), index: Optional[dict] = None, follow=()) -> dict:
    """What the graph file asks of the graph written to *path*, done: the
    classes not written leave it, the classes with an address rule are named
    anew, and the effects of the constraints are applied after the graph is
    held to *shapes*. *index* is {document: [its subjects]}, which a
    paper's leaving out needs. The files *follow* names speak of the graph's
    nodes (its provenance) and follow it: a node named anew is named anew
    there, a node left out takes every triple that names it along. A file is
    rewritten only where something changed. Returns what was done,
    counted."""
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    report = {"classes_left_out": {}, "readdressed": 0, "left_out": [],
              "stop": []}
    done: list = []                 # what the followers repeat, in order
    off = {klass for klass in made.classes if not made.written(klass)}
    changed = False
    if off:
        nodes = of_class(text, off)
        if nodes:
            report["classes_left_out"] = {klass: len(of_class(text, {klass}))
                                          for klass in sorted(off)}
            text = remove(text, nodes)
            done.append(("remove", nodes))
            changed = True
    moved = addresses(text, made, base)
    if moved:
        text = readdress(text, moved)
        done.append(("move", moved))
        report["readdressed"] = len(moved)
        changed = True
        if index:
            for document, subjects in index.items():
                index[document] = [moved.get(one, one) for one in subjects]
    effects = {key: effect for key, effect in made.constraints.items()
               if effect != "report"}
    if effects and shapes:
        found = violations(text, list(shapes), context)
        values, papers = set(), set()
        for key, focus in found:
            effect = effects.get(key)
            if effect == "leave_out_value":
                values.add(focus)
                report["left_out"].append({"constraint": key, "node": focus,
                                           "what": "value"})
            elif effect == "leave_out_paper":
                document = next((name for name, subjects in (index or {})
                                 .items() if focus in subjects), None)
                if document is None:
                    values.add(focus)
                else:
                    papers.add(document)
                report["left_out"].append({"constraint": key, "node": focus,
                                           "what": "paper",
                                           "document": document})
            elif effect == "stop":
                report["stop"].append({"constraint": key, "node": focus})
        for document in papers:
            values |= set((index or {}).get(document) or ())
        if values:
            text = remove(text, values)
            done.append(("remove", values))
            changed = True
    if changed:
        _write(path, text)
    for other in follow or ():
        other = Path(other)
        if done and other.is_file():
            _write(other, _repeat(other.read_text(encoding="utf-8"), done))
    return report


def _write(path: Path, text: str) -> None:
    partial = path.with_name(path.name + ".part")
    partial.write_text(text, encoding="utf-8")
    partial.replace(path)


def _repeat(text: str, done: list) -> str:
    """*text* with what was done to the graph done to it too: the nodes
    named anew named anew, the nodes left out with every triple that names
    them."""
    for what, nodes in done:
        if what == "move":
            text = readdress(text, nodes)
        else:
            named = {node for node in nodes if f"<{node}>" in text}
            text = remove(text, named) if named else text
    return text


# -- `also`: a value written under further predicates ------------------------

def _listed(said) -> list:
    if isinstance(said, dict):
        return [said]
    if isinstance(said, list):
        return [one for one in said if isinstance(one, dict)]
    return []


def also_pairs(spec_raw: dict) -> list:
    """[(classes, predicate block, [further predicate blocks])] of a spec
    read as its shapes name its properties (`draft.read_as_shapes`): every
    block that writes a predicate and names further ones (`also`), with the
    classes of the node it writes on (`draft.field_classes`). A parameter's
    `kg` block may name them beside its `property`, for that property."""
    from .compile import draft
    node_class = draft._node_classes(spec_raw)
    out = []
    for parameter in spec_raw.get("parameters") or ():
        if not isinstance(parameter, dict):
            continue
        classes = draft.field_classes(parameter, node_class)
        kg = parameter.get("kg")
        if isinstance(kg, dict) and kg.get("also") \
                and isinstance(kg.get("property"), dict):
            out.append((classes, kg["property"], _listed(kg["also"])))
        for _where, block in draft.predicate_places(parameter):
            if block.get("also"):
                out.append((classes, block, _listed(block["also"])))
    return [one for one in out if one[2]]


def _iri_of(block: dict, prefixes: dict) -> Optional[str]:
    predicate = block.get("predicate")
    if not isinstance(predicate, str):
        return None
    if predicate.startswith("http"):
        return predicate
    prefix = block.get("prefix")
    return prefixes[prefix] + predicate if prefix in prefixes else None


def _short(iri: str, prefixes: dict) -> Optional[str]:
    """The prefixed name of *iri* under one of *prefixes*, None where none
    binds it with a plain local name."""
    for name, namespace in prefixes.items():
        rest = iri[len(namespace):]
        if iri.startswith(namespace) and re.fullmatch(r"[A-Za-z_][\w-]*",
                                                      rest):
            return f"{name}:{rest}"
    return None


def shape_prefixes(shapes) -> dict:
    """{prefix: namespace} the shapes files declare."""
    out: dict = {}
    for path in shapes or ():
        try:
            out.update(dict(_PREFIX.findall(
                Path(path).read_text(encoding="utf-8"))))
        except OSError:
            continue
    return out


def add_also(text: str, pairs: list, prefixes: Optional[dict] = None) -> tuple:
    """(*text* with what `also` asks, the triples added): for every triple
    whose predicate a block writes with `also`, on a node of one of the
    block's classes, the same node and object under each further predicate,
    where the node holds no value under it yet (a writer that writes it
    itself, a scenario's acronym, keeps its own). Edited as text where every
    block can be read, the writers' comments staying, else written anew by
    rdflib; held against the graph it asks for either way. *prefixes*
    {name: namespace} expand a further predicate the graph's header does not
    bind (the shapes' own, where a merged property came from)."""
    from rdflib import RDF, URIRef
    from rdflib.compare import isomorphic
    if not pairs:
        return text, 0
    own = dict(_PREFIX.findall(text))
    known = {**(prefixes or {}), **own}
    graph = _parsed(text)
    held = set(graph.subject_predicates())
    wanted: dict = {}
    added: set = set()
    for classes, main, further in pairs:
        predicate = _iri_of(main, known)
        if predicate is None:
            continue
        for subject, obj in graph.subject_objects(URIRef(predicate)):
            if classes and not {local(one) for one in graph.objects(
                    subject, RDF.type)} & set(classes):
                continue
            for block in further:
                iri = _iri_of(block, known)
                if iri is None or iri == predicate \
                        or (subject, URIRef(iri)) in held:
                    continue
                added.add((subject, URIRef(iri), obj))
                wanted.setdefault(str(subject), {}).setdefault(
                    predicate, set()).add(iri)
    if not added:
        return text, 0
    whole = _parsed(text)
    for triple in added:
        whole.add(triple)
    try:
        edited = _with_also(text, wanted, dict(own), known)
        if isomorphic(_parsed(edited), whole):
            return edited, len(added)
    except ValueError:
        pass
    return whole.serialize(format="turtle"), len(added)


def _with_also(text: str, wanted: dict, own: dict, known: dict) -> str:
    """*text* with an entry for each further predicate after the entry of the
    predicate it repeats, in the blocks of the nodes *wanted* names ({node:
    {predicate: {further}}}); a prefix the header lacks is declared."""
    header: list = []

    def name_of(iri: str) -> str:
        short = _short(iri, own)
        if short:
            return short
        short = _short(iri, {k: v for k, v in known.items() if k not in own})
        if short:
            prefix = short.split(":", 1)[0]
            own[prefix] = known[prefix]
            header.append(f"@prefix {prefix}: <{known[prefix]}> .")
            return short
        return f"<{iri}>"

    out = []
    for block in _blocks(text):
        found = _SUBJECT.match(block.split("\n", 1)[0])
        todo = wanted.get(found.group(1)) if found else None
        if not todo:
            out.append(block)
            continue
        parsed = _entries(block)
        if parsed is None or _render(*parsed) != block.rstrip("\n"):
            raise ValueError("a block the edit cannot read")
        subject, entries = parsed
        grown = []
        for comments, predicate, objects, end in entries:
            grown.append([comments, predicate, objects, end])
            bare = predicate[1:-1] if predicate.startswith("<") else \
                _expand(predicate, own)
            for further in sorted(todo.get(bare, ())):
                grown.append([[], name_of(further), list(objects), end])
        out.append(_render(subject, grown)
                   + block[len(block.rstrip("\n")):])
    edited = "\n\n".join(out)
    if header:
        lines = edited.split("\n")
        at = max((number for number, line_ in enumerate(lines)
                  if _PREFIX.match(line_)), default=-1)
        edited = "\n".join(lines[:at + 1] + header + lines[at + 1:])
    return edited


def also(path: Path, pairs: list, prefixes: Optional[dict] = None) -> int:
    """`add_also` on the graph written to *path*; the file is rewritten only
    where a triple is added. Returns how many were."""
    path = Path(path)
    edited, count = add_also(path.read_text(encoding="utf-8"), pairs,
                             prefixes)
    if count:
        _write(path, edited)
    return count
