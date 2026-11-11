"""
sourcespage.py: Where a profile's ontology, shapes and graph come from, as
`docpipe edit` shows, fetches and applies them, and what they say differently
from the spec.

The sources themselves are the run's (`docpipe.sources`, `docpipe.upstream`):
the profile's sources.json, the fetch of each kind, the lock that names what
the last refresh took. This module turns them into what the page shows and
decides what each button does (owner, 2026-11-10: "einfach die URLs angeben
für Ontologie und KG und dann eben die auch die Felder auswählen und
zusammenlegen"):

- `view`: every source with its address, the kind of version it stands at
  (a release, the head of a branch, a live query) and the version the lock
  holds; a token only as set or not set, never its value; the lists and
  which coordinate answers from which.
- `judge` and `save`: an edited sources.json, read strictly by the run's own
  parser before it is written.
- `fetch`: the profile's own refresh into a folder of the temp directory,
  never into the profile or the cache: which source moved, what that does
  to each list (entries added, gone, renamed, redefined) and to the other
  files the refresh writes.
- `apply`: a fetch made the profile's: the files the refresh writes into the
  profile's folder, the fetched files into the cache and the lock beside
  them, its paths moved from the temp folder to the cache. The spec never.
- `differences`: per field, what the shapes and the ontology say otherwise
  than the spec (`draft.differences`, held to the shapes as the profile names
  its properties; `ontology.definition_differences`), each row the page can
  act on with an id.
- `take`: the chosen rows applied to the spec, for the Spec tab to check and
  save with what it costs: a new entry of a list with the ontology's name
  and definition, a definition replaced by the ontology's, a property no
  field asks as a new field (a draft: it needs an example before the strict
  check takes it), or merged into an existing field as one more property it
  writes: an arrow of the drawing of the profile's graph file, from the
  field to the box of the property's class (`take` hands the drawing back
  beside the spec).

Author: Felix Vossel
"""
from __future__ import annotations

import copy
import datetime
import difflib
import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Optional

from docpipe import ontology
from docpipe import sources as source_files
from docpipe import upstream

CR, LF = "\r", "\n"
FETCH_FOLDER = "docpipe-sources-fetch"
FETCH_ID = re.compile(r"^fetch-\d{8}-\d{6}-[A-Za-z0-9_-]+$")
COST = ("A change takes effect at the next fetch. \"Fetch\" downloads the "
        "sources into a folder of their own and shows what changed; "
        "\"Apply\" then writes the lists and the lock file. Harvests that "
        "are already written stay valid. A list with a new entry needs a "
        "remap of the stored harvest, which asks no model.")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch_root() -> Path:
    return Path(tempfile.gettempdir()) / FETCH_FOLDER


def _module(profile, name: str):
    return profile.component("vocabulary", name)


def lock_name(profile) -> str:
    """The name the profile's refresh writes its lock under."""
    return _module(profile, "PROFILE") or profile.name


def _address(source: dict) -> str:
    kind = source.get("kind")
    if kind in ("release_asset", "release_file"):
        what = source.get("asset") or source.get("file")
        return f"github.com/{source['repo']}, latest release, {what}"
    if kind in ("repo_files", "repo_tree"):
        return f"github.com/{source['repo']} @ {source['ref']}"
    if kind == "sparql":
        return source.get("endpoint", "")
    return source.get("url", "")


def _token(source: dict) -> Optional[dict]:
    variable = source.get("token_env")
    if not variable:
        return None
    return {"env": variable,
            "set": bool(os.environ.get(variable, "").strip())}


def _locked(record: Optional[dict]) -> Optional[dict]:
    if not record:
        return None
    return {"version": record.get("version"),
            "files": len(record.get("files") or ()),
            "rows": record.get("rows"), "note": record.get("note"),
            "changed_since_reviewed": record.get("changed_since_reviewed"),
            "compare": record.get("compare")}


def _snapshot_of(path: Path) -> Optional[dict]:
    return ontology.load(path) if path.is_file() else None


def view(profile, own_raw: Optional[bytes], shown,
         cache: Path = upstream.CACHE, snapshot: Optional[dict] = None,
         spec_raw: Optional[dict] = None) -> dict:
    """The sources of *profile* as the page shows them."""
    made = source_files.load(profile)
    lock = upstream.load_lock(lock_name(profile), cache) or {}
    locked = lock.get("sources") or {}
    sets = (snapshot or {}).get("sets") or {}
    rows = []
    for name, source in made.sources.items():
        rows.append({
            "name": name, "kind": source["kind"],
            "stands": source_files.STANDS.get(source["kind"], ""),
            "address": _address(source),
            "source": {key: value for key, value in source.items()
                       if key != "kind"},
            "keys": list(source_files.KEYS[source["kind"]][0]
                         + source_files.KEYS[source["kind"]][1]),
            "token": _token(source), "locked": _locked(locked.get(name))})
    lists = [{"name": name, "kind": one["kind"], "root": one["root"],
              "members": len(sets.get(name) or ()) if name in sets else None}
             for name, one in made.lists.items()]
    own = source_files.path_of(profile)
    return {"file": shown(own), "exists": own_raw is not None,
            "inherited_from": (shown(made.path) if made.path is not None
                               and Path(made.path) != own else None),
            "base": sha256(own_raw) if own_raw is not None else None,
            "sources": rows, "lists": lists,
            "axis_lists": dict(made.axis_lists),
            "kinds": {kind: {"needs": list(needed), "may": list(optional),
                             "stands": source_files.STANDS[kind]}
                      for kind, (needed, optional)
                      in source_files.KEYS.items()},
            "list_kinds": list(source_files.LIST_KINDS),
            "lock": {"file": shown(upstream.lock_path(lock_name(profile),
                                                      cache)),
                     "fetched_at": lock.get("fetched_at")},
            "fetches": _module(profile, "refresh") is not None,
            "writes": list(_module(profile, "WRITES") or ()),
            "cost": COST,
            "differences": (differences(profile, spec_raw, snapshot,
                                        shape_files(profile, cache))
                            if spec_raw is not None else None)}


# -- the file ------------------------------------------------------------------

def _text(raw: Optional[bytes]) -> Optional[str]:
    return None if raw is None else raw.decode("utf-8").replace(CR + LF, LF)


def judge(profile, own_raw: Optional[bytes], data, name: str) -> dict:
    """What a save of *data* ({"sources", "lists", "axis_lists"}) would do:
    {"ok", "errors", "file", "writes", "diff", "says", "text"}."""
    errors = []
    old = _text(own_raw)
    newline = CR + LF if (CR + LF).encode() in (own_raw or b"") else LF
    new = old
    if not isinstance(data, dict):
        errors.append("the body needs \"data\": the sources as an object")
    else:
        try:
            made = source_files.parse(json.dumps(data), name)
            new = source_files.dump(made)
        except source_files.SourcesError as exc:
            errors.append(str(exc))
    writes = ("unchanged" if new == old else "created" if old is None
              else "changed")
    diff = [] if writes == "unchanged" else list(difflib.unified_diff(
        (old or "").splitlines(), (new or "").splitlines(), name, name,
        lineterm=""))
    return {"ok": not errors, "errors": errors, "file": name,
            "writes": writes, "diff": diff,
            "says": [COST] if writes != "unchanged" and not errors else [],
            "text": None if new is None or errors
            else new.replace(LF, newline)}


def save(profile, own_raw: Optional[bytes], data, base: Optional[str],
         name: str) -> tuple:
    """(what the page is told, the bytes to write or None)."""
    report = judge(profile, own_raw, data, name)
    text = report.pop("text")
    if not report["ok"]:
        return {"saved": False, "reason": "invalid",
                "errors": report["errors"],
                "message": "; ".join(report["errors"])}, None
    if base != (sha256(own_raw) if own_raw is not None else None):
        return {"saved": False, "reason": "moved",
                "message": "the file changed on disk since the page loaded "
                           "it; reload it before saving"}, None
    told = {"saved": True, "writes": report["writes"], "file": name}
    if report["writes"] == "unchanged":
        return {**told, "base": base}, None
    written = text.encode("utf-8")
    return {**told, "base": sha256(written)}, written


# -- fetch and apply -----------------------------------------------------------

def shape_files(profile, cache: Path = upstream.CACHE) -> list:
    """The shapes the profile's spec is held against, as the lock in *cache*
    names them."""
    shapes = _module(profile, "shapes")
    if shapes is None:
        return []
    return [path for path in shapes(cache) if Path(path).is_file()]


def _members(snapshot: Optional[dict]) -> dict:
    return {name: list(members)
            for name, members in ((snapshot or {}).get("sets") or {}).items()}


def _term(snapshot: Optional[dict], key: str) -> dict:
    return ((snapshot or {}).get("terms") or {}).get(key) or {}


def list_changes(before: Optional[dict], after: Optional[dict]) -> list:
    """Per list of the snapshot: the entries a fetch adds, takes away,
    renames or defines anew, each with its name."""
    old, new = _members(before), _members(after)
    out = []
    for name in sorted(set(old) | set(new)):
        was, now = set(old.get(name) or ()), set(new.get(name) or ())
        renamed, redefined = [], []
        for key in sorted(was & now):
            a, b = _term(before, key), _term(after, key)
            if a.get("label") != b.get("label"):
                renamed.append({"id": key, "from": a.get("label"),
                                "to": b.get("label")})
            if " ".join(str(a.get("definition") or "").split()) != \
                    " ".join(str(b.get("definition") or "").split()):
                redefined.append({"id": key, "label": b.get("label"),
                                  "from": a.get("definition"),
                                  "to": b.get("definition")})
        added = [{"id": key, "label": _term(after, key).get("label")}
                 for key in sorted(now - was)]
        gone = [{"id": key, "label": _term(before, key).get("label")}
                for key in sorted(was - now)]
        if added or gone or renamed or redefined or name not in old:
            out.append({"list": name, "before": len(was), "after": len(now),
                        "added": added, "gone": gone, "renamed": renamed,
                        "redefined": redefined})
    return out


def _file_change(before: Path, after: Path) -> dict:
    """What a fetch does to one file the refresh writes."""
    old = before.read_bytes() if before.is_file() else None
    new = after.read_bytes() if after.is_file() else None
    out = {"file": after.name, "changed": old != new,
           "existed": old is not None, "written": new is not None}
    try:
        was = json.loads(old) if old is not None else None
        now = json.loads(new) if new is not None else None
    except ValueError:
        return out
    if isinstance(was, dict) and isinstance(now, dict) \
            and after.name != "vocabulary.json":
        out["entries"] = {"before": len(was), "after": len(now),
                          "added": sorted(set(now) - set(was))[:50],
                          "gone": sorted(set(was) - set(now))[:50]}
    return out


def _source_changes(before: dict, after: dict) -> list:
    old = (before or {}).get("sources") or {}
    new = (after or {}).get("sources") or {}
    out = []
    for name in list(new) + [one for one in old if one not in new]:
        a, b = old.get(name) or {}, new.get(name) or {}
        out.append({"name": name, "before": a.get("version"),
                    "after": b.get("version"),
                    "moved": a.get("version") != b.get("version"),
                    "note": b.get("note"),
                    "changed_since_reviewed":
                        b.get("changed_since_reviewed"),
                    "compare": b.get("compare")})
    return out


def fetch(profile, root: Optional[Path] = None,
          cache: Path = upstream.CACHE, spec_raw: Optional[dict] = None,
          now: Optional[datetime.datetime] = None) -> dict:
    """The profile's refresh into a folder of *root* (the temp directory's
    where not given): nothing is written into the profile or the cache.
    Returns what moved, with the id `apply` takes."""
    refresh = _module(profile, "refresh")
    if refresh is None:
        raise ValueError(f"profile {profile.name!r} has no refresh of its "
                         f"sources (vocabulary.py: refresh)")
    root = Path(root) if root is not None else fetch_root()
    stamp = (now or datetime.datetime.now()).strftime("%Y%m%d-%H%M%S")
    name = f"fetch-{stamp}-{profile.name}"
    where = root / name
    (where / "cache").mkdir(parents=True, exist_ok=False)
    (where / "profile").mkdir()
    refresh(cache=where / "cache", out=where / "profile")
    return compare(profile, where, cache, spec_raw)


def compare(profile, where: Path, cache: Path = upstream.CACHE,
            spec_raw: Optional[dict] = None) -> dict:
    """What the fetch in *where* would change against what the profile and
    the cache hold now."""
    where = Path(where)
    before_lock = upstream.load_lock(lock_name(profile), cache) or {}
    after_lock = upstream.load_lock(lock_name(profile),
                                    where / "cache") or {}
    writes = list(_module(profile, "WRITES") or ())
    before = _snapshot_of(_read_by_run(profile, "vocabulary.json"))
    after = _snapshot_of(where / "profile" / "vocabulary.json")
    report = {
        "id": where.name, "sources": _source_changes(before_lock, after_lock),
        "lists": list_changes(before, after),
        "files": [_file_change(_read_by_run(profile, one),
                               where / "profile" / one)
                  for one in writes],
        "pin": {"before": (before or {}).get("pin"),
                "after": (after or {}).get("pin")},
        "differences": (differences(profile, spec_raw, after,
                                    shape_files(profile, where / "cache"))
                        if spec_raw is not None else None)}
    (where / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1, default=str) + "\n",
        encoding="utf-8")
    return report


def _read_by_run(profile, file: str) -> Path:
    """The file a fetch is compared to: the one "Apply" would replace in
    the profile's folder, else the one a run reads now, beside the module
    that refreshes it."""
    own = Path(profile.package_dir) / file
    if own.is_file():
        return own
    path = _module(profile, "VOCABULARY_PATH")
    folder = (Path(path).parent if path is not None
              else Path(profile.package_dir))
    return folder / file


def fetched(root: Path, fetch_id: str) -> Path:
    if not isinstance(fetch_id, str) or not FETCH_ID.match(fetch_id):
        raise ValueError(f"{fetch_id!r} is no fetch of this page")
    where = Path(root) / fetch_id
    if not (where / "cache").is_dir() or not (where / "profile").is_dir():
        raise ValueError(f"no fetch {fetch_id} in {root}")
    return where


def apply(profile, where: Path, write_profile, write_cache,
          cache: Path = upstream.CACHE) -> dict:
    """The fetch in *where* made the profile's: every file its refresh
    writes into the profile's folder (through *write_profile*, the editor's
    guard), every fetched file into the cache and the lock with its paths in
    the cache (through *write_cache*). The spec is no file a refresh writes,
    so it is never touched."""
    where = Path(where)
    taken = []
    for file in _module(profile, "WRITES") or ():
        source = where / "profile" / file
        if source.is_file():
            target = Path(profile.package_dir) / file
            write_profile(target, source.read_bytes())
            taken.append(str(target))
    fetched_cache = (where / "cache").resolve()
    cache = Path(cache).resolve()
    lock_file = upstream.lock_path(lock_name(profile), fetched_cache).name
    copied = 0
    for path in sorted(fetched_cache.rglob("*")):
        if not path.is_file() or path.name == lock_file \
                or path.name.endswith(".part"):
            continue
        write_cache(cache / path.relative_to(fetched_cache),
                    path.read_bytes())
        copied += 1
    lock = upstream.load_lock(lock_name(profile), fetched_cache)
    if lock is None:
        raise ValueError(f"the fetch {where.name} wrote no lock")
    moved = json.loads(json.dumps(lock).replace(
        json.dumps(str(fetched_cache))[1:-1], json.dumps(str(cache))[1:-1]))
    write_cache(upstream.lock_path(lock_name(profile), cache),
                (json.dumps(moved, ensure_ascii=False, indent=1,
                            sort_keys=True) + "\n").encode("utf-8"))
    return {"applied": where.name, "profile_files": taken,
            "cache_files": copied,
            "lock": str(upstream.lock_path(lock_name(profile), cache))}


# -- what the shapes and the ontology say otherwise ---------------------------

ACTIONS = {"list_missing": ("add",), "definition_rewritten": ("replace",),
           "definition_pin_only": ("replace",),
           "not_asked": ("new_field", "merge")}


def _row_id(*parts) -> str:
    return "|".join("" if part is None else str(part) for part in parts)


def differences(profile, spec_raw: Optional[dict], snapshot: Optional[dict],
                files: list) -> dict:
    """{"fields": [{"field", "rows"}], "unasked": [rows], "skipped": why}:
    what the shapes in *files* and the ontology in *snapshot* say otherwise
    than *spec_raw*, per field."""
    from docpipe.compile import draft
    if spec_raw is None:
        return {"fields": [], "unasked": [], "skipped": "no spec"}
    rows, skipped = [], None
    if not files:
        skipped = "no shapes file: fetch the sources first"
    else:
        try:
            from docpipe.compile import shapes
            found, _prefixes = shapes.read(files)
            from docpipe import graphfile
            rows = draft.differences(found, spec_raw,
                                     drawing=graphfile.load(profile).map)
        except ImportError:
            skipped = "rdflib is not installed"
    by_field: dict = {}
    unasked = []
    for row in rows:
        kind = row["kind"]
        if kind == "not_asked":
            unasked.append({**row, "id": _row_id(kind, row.get("shape"),
                                                 row["path"]),
                            "actions": list(ACTIONS[kind])})
            continue
        entries = []
        for iri in row.get("entries") or ():
            key = ontology.identifier(iri)
            term = _term(snapshot, key) if key else {}
            entries.append({
                "iri": iri, "label": term.get("label"),
                "definition": term.get("definition"),
                "id": _row_id(kind, row["parameter"], row.get("axis"),
                              row["path"], iri),
                "takes": bool(term.get("label")) and kind in ACTIONS,
                "why": None if term.get("label") or kind not in ACTIONS
                else "the pinned version of the ontology does not have "
                     "it; fetch and apply the sources first"})
        by_field.setdefault(row["parameter"], []).append(
            {**row, "entries": entries,
             "actions": list(ACTIONS.get(kind, ()))})
    for where, key, kind, ours, theirs in (
            ontology.definition_differences(spec_raw, snapshot)
            if snapshot else ()):
        field, _, axis = where.partition(".")
        kind = f"definition_{kind}"
        by_field.setdefault(field, []).append({
            "kind": kind, "parameter": field,
            "axis": None if axis == "value" else axis, "path": key,
            "detail": ("the ontology defines it otherwise" if ours
                       else "the ontology defines it, the spec does not"),
            "spec": ours, "ontology": theirs,
            "id": _row_id(kind, field, axis, key),
            "actions": list(ACTIONS[kind])})
    order = [one.get("uri") for one in spec_raw.get("parameters") or ()]
    fields = [{"field": name, "rows": by_field[name]}
              for name in order if name in by_field]
    fields += [{"field": name, "rows": rows_}
               for name, rows_ in by_field.items() if name not in order]
    return {"fields": fields, "unasked": unasked, "skipped": skipped,
            "targets": merge_targets(spec_raw)}


def _list_of(parameter: dict, axis: Optional[str]) -> Optional[dict]:
    if axis in (None, "", "value"):
        owner = parameter
    else:
        owner = (parameter.get("axes") or {}).get(axis)
        if not isinstance(owner, dict):
            return None
    if not isinstance(owner.get("vocabulary"), dict):
        owner["vocabulary"] = {}
    return owner["vocabulary"]


def _key_like(vocabulary: dict, iri: str) -> str:
    """An entry is keyed as the list keys the others: by IRI, or by its
    identifier where they are."""
    keys = [key for key in vocabulary if not str(key).startswith("out:")]
    if keys and not str(keys[0]).startswith("http"):
        return ontology.identifier(iri) or iri
    return iri


def _box_of_class(drawing: dict, shape_class: str,
                  field: str) -> Optional[dict]:
    """The box of *drawing* whose class is *shape_class*: the one *field*
    already has an arrow to where it has one, else the first."""
    from docpipe.compile import draft
    wanted = draft.local(shape_class or "")
    boxes = [box for box in drawing.get("boxes") or ()
             if isinstance(box.get("class"), str)
             and draft.local(box["class"].split(":")[-1]) == wanted]
    own = {arrow.get("to") for arrow in drawing.get("arrows") or ()
           if arrow.get("from") == field}
    return next((box for box in boxes if box["id"] in own),
                boxes[0] if boxes else None)


def _draw(drawing: dict, field: str, shape, prop, prefixes: dict) -> tuple:
    """Draw an arrow from *field* to the box of the class of *shape*,
    writing *prop*, into *drawing*: (done, what was said). Where no box of
    that class exists one is added; where the arrow is drawn already,
    nothing changes."""
    from docpipe.compile import draft
    if not drawing.get("boxes"):
        return False, "the profile's graph file has no drawing to draw it in"
    names = draft.Names({**prefixes, **(drawing.get("prefixes") or {})})
    curie = names.curie(prop.path)
    box = _box_of_class(drawing, shape.target_class, field)
    if box is None:
        klass = names.curie(shape.target_class)
        wanted = draft.slug(shape.name) or "node"
        wanted = wanted if wanted[0].isalpha() else f"node_{wanted}"
        taken = {one["id"] for one in drawing["boxes"]}
        name, number = wanted, 2
        while name in taken:
            name, number = f"{wanted}_{number}", number + 1
        box = {"id": name, "class": klass, "count": "per_document",
               "address": {"folder": name, "key": name, "from": [field],
                           "fold": True},
               "note": f"Added by a merge from the shape {shape.name}: one "
                       f"node of this class per document, named after the "
                       f"reading of {field}."}
        drawing["boxes"].append(box)
    if any(one.get("from") == field and one.get("to") == box["id"]
           and one.get("property") == curie
           for one in drawing.get("arrows") or ()):
        return False, f"{field} writes {curie} on {box['id']} already"
    drawing.setdefault("arrows", []).append(
        {"from": field, "to": box["id"], "property": curie})
    for prefix in names.used:
        drawing.setdefault("prefixes", {}).setdefault(
            prefix, names.prefixes[prefix])
    return True, f"{field} writes what it writes as {curie} on {box['id']}"


def take(spec_raw: dict, chosen: list, snapshot: Optional[dict],
         profile=None, files: Optional[list] = None) -> dict:
    """{"data": the spec with the chosen rows applied, "map": the drawing
    of the profile's graph file with the arrows a merge or a new field
    drew, None where it stayed as it was, "done": [...], "refused":
    [{"id", "why"}]}. *chosen* is [{"id", "action", "into"?}]; `into` names
    the field a property is merged into."""
    from docpipe import graphfile
    data = copy.deepcopy(spec_raw)
    drawing = copy.deepcopy(graphfile.load(profile).map or {}) \
        if profile is not None else {}
    before = copy.deepcopy(drawing)
    parameters = {one.get("uri"): one for one in data.get("parameters") or ()
                  if isinstance(one, dict)}
    found = None
    done, refused = [], []
    for pick in chosen or ():
        row_id = pick.get("id") if isinstance(pick, dict) else None
        action = pick.get("action") if isinstance(pick, dict) else None
        parts = str(row_id or "").split("|")
        kind = parts[0]
        if kind not in ACTIONS or action not in ACTIONS[kind]:
            refused.append({"id": row_id, "why": f"{action!r} is no action "
                                                 f"for {kind!r}"})
            continue
        if kind == "list_missing" and len(parts) == 5:
            _kind, field, axis, _path, iri = parts
            parameter = parameters.get(field)
            key = ontology.identifier(iri)
            term = _term(snapshot, key) if key else {}
            if parameter is None or not term.get("label"):
                refused.append({"id": row_id, "why": "no such field, or the "
                                "pinned ontology does not carry the entry"})
                continue
            listing = _list_of(parameter, axis or None)
            if listing is None:
                refused.append({"id": row_id,
                                "why": f"{field} has no dimension {axis}"})
                continue
            entry = {"label": term["label"], "spellings": []}
            if term.get("definition"):
                entry["definition"] = term["definition"]
            listing.setdefault(_key_like(listing, iri), entry)
            done.append({"id": row_id, "did": f"{field}: {term['label']} "
                                              f"added to the list"})
        elif kind.startswith("definition_") and len(parts) == 4:
            _kind, field, axis, key = parts
            parameter = parameters.get(field)
            listing = _list_of(parameter, axis or None) if parameter else None
            term = _term(snapshot, key)
            match = [one for one in (listing or {})
                     if ontology.identifier(one) == key]
            if not match or not term.get("definition") \
                    or not isinstance(listing[match[0]], dict):
                refused.append({"id": row_id, "why": "no such entry, or it "
                                                     "is no object"})
                continue
            listing[match[0]]["definition"] = term["definition"]
            done.append({"id": row_id, "did": f"{field}: the definition of "
                                              f"{key} is the ontology's"})
        elif kind == "not_asked" and len(parts) == 3:
            _kind, shape_name, path = parts
            if found is None:
                from docpipe.compile import shapes as shape_files_
                found = shape_files_.read(files or [])
            shape = next((one for one in found[0] if one.name == shape_name),
                         None)
            prop = next((one for one in (shape.properties if shape else ())
                         if one.path.rsplit("/", 1)[-1].rsplit("#", 1)[-1]
                         == path), None)
            if prop is None:
                refused.append({"id": row_id, "why": "the shapes have no "
                                                     "such property"})
                continue
            if action == "merge":
                said = _merge(parameters, drawing, pick.get("into"), shape,
                              prop, found[1])
            else:
                said = _new_field(data, parameters, drawing, shape, prop,
                                  found[1], snapshot)
            (done if said[0] else refused).append(
                {"id": row_id, ("did" if said[0] else "why"): said[1]})
        else:
            refused.append({"id": row_id, "why": "no such row"})
    return {"data": data, "map": drawing if drawing != before else None,
            "done": done, "refused": refused}


def merge_targets(spec_raw: Optional[dict]) -> list:
    """[{"into", "label"}]: every field a property of the shapes can be
    merged into. *into* is the field's name; the merge draws the arrow
    from it."""
    return [{"into": parameter["uri"],
             "label": f"{parameter['uri']}: {parameter.get('label') or ''}"
             .rstrip(": ")}
            for parameter in (spec_raw or {}).get("parameters") or ()
            if isinstance(parameter, dict) and parameter.get("uri")]


def _merge(parameters, drawing, into, shape, prop, prefixes) -> tuple:
    """Draw *prop* as one more property the field *into* writes: an arrow
    from the field to the box of the shape's class (`_draw`), so the graph
    holds the value the field reads under *prop* as well."""
    field = str(into or "")
    if field not in parameters:
        return False, f"{field!r} is no field"
    return _draw(drawing, field, shape, prop, prefixes)


def _new_field(data, parameters, drawing, shape, prop, prefixes,
               snapshot) -> tuple:
    from docpipe.compile import draft
    single = copy.copy(shape)
    single.properties = [prop]
    drafted = draft.draft([single], prefixes)
    if not drafted["parameters"]:
        return False, ("the property leads to another node of the graph; "
                       "the graph's links say it, no field asks it")
    raw = draft.finished({"parameters": drafted["parameters"]})[
        "parameters"][0]
    name, number = raw["uri"], 2
    while name in parameters:
        name, number = f"{raw['uri']}_{number}", number + 1
    shown = raw["uri"]
    raw["uri"] = name
    # Its arrow: the drafted one, into the box the drawing has for the
    # shape's class, else into the drafted box.
    said = drafted["graph"]["map"]
    boxes = {one["id"]: one for one in said["boxes"]}
    if drawing.get("boxes"):
        for arrow in [one for one in said["arrows"]
                      if one.get("from") == shown]:
            into = boxes[arrow["to"]]
            here = _box_of_class(drawing, shape.target_class, name) \
                if into.get("count") == "per_document" else None
            if here is None and not any(one["id"] == into["id"]
                                        for one in drawing["boxes"]):
                drawing["boxes"].append(copy.deepcopy(into))
            drawing.setdefault("arrows", []).append(
                {**arrow, "from": name,
                 "to": here["id"] if here is not None else into["id"]})
        for prefix, namespace in (said.get("prefixes") or {}).items():
            drawing.setdefault("prefixes", {}).setdefault(prefix, namespace)
    data.setdefault("parameters", []).append(raw)
    parameters[name] = raw
    return True, (f"{name}: a new field for {draft.local(prop.path)}; it "
                  f"needs an example from a real document before the spec "
                  f"takes it")
