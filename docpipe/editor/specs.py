"""
specs.py: What the editor does with a profile's extraction spec.

No page and no file in here: text in, text out, so each promise the page makes
can be held to in a test without a server. The page keeps the parsed spec,
changes it and sends it back; what happens to it then is decided here.

The file is written in one fixed form (`dump`), the one `json.dumps` gives
with two spaces, in the line endings the file has. Both profile specs were
brought into that form once, so a save changes the lines an edit changed and
no others; a number the page sends back unchanged is written as the file has
it (`as_written`), because a browser does not tell `1.0` from `1`.

A spec is written only if the run's own loader takes it (`problem`,
`spec.load`). What an edit costs the next run is said with the run's own
functions and nothing else: the fingerprint of every question
(`spec.fingerprints`, in `changes`) and, where a harvest lies beside, the
documents whose stamps the edit makes stale (`runner.stale`, in `affected`).
An edit that takes something away (a field, a coordinate, an entry of a list,
a spelling) is written only after it is confirmed (`save`).

Author: Felix Vossel
"""
from __future__ import annotations

import copy
import difflib
import inspect
import json
import re
from pathlib import Path
from typing import Optional

from .. import ontology, rules
from ..extraction import spec as spec_module
from ..extraction.spec import SpecError

# -- the one writing form ------------------------------------------------------

# A key a browser would move: an object key that is a whole number goes to the
# front of its object in JavaScript, so a spec with one cannot go through the
# page and keep its order.
_WHOLE_NUMBER = re.compile(r"^(?:0|[1-9][0-9]*)$")


def newline_of(raw: bytes) -> str:
    """The line ending a file is written in."""
    return "\r\n" if b"\r\n" in raw else "\n"


def parse(raw: bytes) -> dict:
    """The spec of a file's bytes; ValueError where they are no JSON object."""
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("the top level of a spec is an object")
    return data


def dump(data: dict, newline: str = "\n") -> str:
    """A spec as the editor writes it: two spaces, every character as it is
    typed, one line break at the end, in the file's line endings."""
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    return text if newline == "\n" else text.replace("\n", newline)


def as_written(old, new):
    """*new* with every number the edit left alone as the file writes it.

    A browser has one kind of number: it reads the file's `1.0` and sends
    back `1`, and written like that every factor of the spec would be a
    changed line. A number that equals the one at the same place of the
    file is therefore written as the file has it; one the edit changed or
    added is written as it was sent. Objects are matched by key, the fields
    of a spec by their `uri` (a copy or a removal moves the ones after it),
    any other list by position.
    """
    if isinstance(new, dict) and isinstance(old, dict):
        return {key: as_written(old.get(key), value)
                for key, value in new.items()}
    if isinstance(new, list) and isinstance(old, list):
        def uris(items) -> Optional[dict]:
            if items and all(isinstance(item, dict) and "uri" in item
                             for item in items):
                return {item["uri"]: item for item in items}
            return None
        known = uris(old) if uris(new) is not None else None
        if known is not None:
            return [as_written(known.get(item["uri"]), item) for item in new]
        return [as_written(old[position] if position < len(old) else None,
                           item) for position, item in enumerate(new)]
    number = (int, float)
    if isinstance(new, number) and isinstance(old, number)             and not isinstance(new, bool) and not isinstance(old, bool)             and new == old:
        return old
    return new


def _numbered_key(node, path: str = "spec") -> Optional[str]:
    """The path of the first object key that is a whole number, else None."""
    if isinstance(node, dict):
        for key, value in node.items():
            if _WHOLE_NUMBER.match(str(key)):
                return f"{path}.{key}"
            found = _numbered_key(value, f"{path}.{key}")
            if found:
                return found
    elif isinstance(node, list):
        for position, value in enumerate(node):
            found = _numbered_key(value, f"{path}[{position}]")
            if found:
                return found
    return None


# -- the check: the run's loader -----------------------------------------------

def problem(data) -> Optional[dict]:
    """{"where", "message"} of why the run would refuse this spec, None
    where it loads. The loader's own words: a refusal names the field."""
    numbered = _numbered_key(data)
    if numbered:
        return {"where": numbered,
                "message": "a key that is a whole number: a browser moves "
                           "such a key to the front of its object, so the "
                           "page cannot keep the order of the file"}
    try:
        spec_module.load(data)
    except SpecError as exc:
        where, _, message = str(exc).partition(": ")
        return {"where": where, "message": message}
    except Exception as exc:           # a shape the loader does not expect
        return {"where": "spec", "message": f"{type(exc).__name__}: {exc}"}
    return None


# -- what an edit changes for the run ------------------------------------------

REMAP, READ, APPEND, GONE = "remap", "read", "append", "gone"


def _prints(data) -> dict:
    """The fingerprints of a spec's questions, {} where it does not load."""
    try:
        return spec_module.fingerprints(spec_module.load(data))
    except Exception:
        return {}


def _lists_of(data: dict, key: str) -> Optional[tuple]:
    """(the list a key's answers come from, everything else that asks it) of
    an answer-space key, None where the spec has no such key.

    The list as {entry: its labels}; the rest is the raw block without that
    list, so two specs can be asked whether anything but the list moved.
    """
    parts = key.split("/")
    parameters = {p.get("uri"): p for p in data.get("parameters", [])
                  if isinstance(p, dict)}
    parameter = parameters.get(parts[1]) if len(parts) > 1 else None
    if parameter is None:
        return None
    if parts[0] == "value" and len(parts) == 2:
        block = {k: parameter.get(k) for k in ("vocabulary",
                                               "vocabulary_dynamic")}
    elif parts[0] == "axis" and len(parts) == 3:
        block = (parameter.get("axes") or {}).get(parts[2])
        if not isinstance(block, dict):
            return None
    else:
        return None
    rest = {k: v for k, v in block.items() if k not in ("vocabulary", "kg")}
    return _entries(block.get("vocabulary")), rest


def _entries(raw) -> dict:
    """{entry: (labels, what else the entry says)} of a list in either
    form."""
    out: dict = {}
    for uri, entry in (raw or {}).items() if isinstance(raw, dict) else ():
        if isinstance(entry, dict):
            labels = [entry.get("label")] + list(entry.get("spellings")
                                                 or [])
            said = {k: v for k, v in entry.items()
                    if k not in ("label", "spellings", "note")}
        else:
            labels, said = list(entry or []), {}
        out[uri] = (labels, said)
    return out


def _grew(old: dict, new: dict, key: str) -> bool:
    """Whether an answer space only gained: every entry it had is still
    there with all its labels and its meaning, and nothing but the list
    changed. That is the case `--remap` exists for."""
    before, after = _lists_of(old, key), _lists_of(new, key)
    if before is None or after is None or before[1] != after[1]:
        return False
    for uri, (labels, said) in before[0].items():
        if uri not in after[0]:
            return False
        now_labels, now_said = after[0][uri]
        if said != now_said or not set(labels) <= set(now_labels) \
                or labels[:1] != now_labels[:1]:
            return False
    return True


def _by_addition(old: dict, new: dict, before: dict, after: dict) -> set:
    """The keys that moved only because the spec gained fields, by the rule
    of the pass that appends a field (`topup_parameter.addition`): the keys
    the new fields own, and a question no field owns that reads as it did
    once the new fields are taken out again."""
    from ..extraction import topup_parameter as appending
    known = set(_by_uri(old))
    try:
        loaded = spec_module.load(new)
    except Exception:
        return set()
    gained = [p for p in loaded.parameters if p.uri not in known]
    if not gained or not before:
        return set()
    out: set = set()
    for parameter in gained:
        out |= appending.owned_keys(parameter.uri, after)
    without = spec_module.fingerprints(appending.without(loaded, gained))
    out |= {key for key in appending.SHARED_KEYS
            if key in after and without.get(key) == before.get(key)}
    return out


def _effect(key: str, state: str, old: dict, new: dict,
            added: bool) -> tuple:
    """(effect, the sentence the page shows) of one moved key, in the terms
    of the passes a run has for it. *added*: only a gained field moved it."""
    kind = key.split("/")[0]
    if state == "gone":
        return GONE, ("the spec no longer asks this: a document stamped "
                      "with it is stale until it is harvested again "
                      "(--force-stale)")
    if added:
        if kind == "parameter":
            return APPEND, ("a new field: --top-up-parameters searches each "
                            "stored document for it alone and appends its "
                            "rows")
        if kind == "slot":
            return APPEND, ("moved only because the spec gained a field: "
                            "answered by the pass that appends it "
                            "(--top-up-parameters)")
        return APPEND, ("belongs to the new field: answered by the pass "
                        "that appends it (--top-up-parameters)")
    if kind == "parameter":
        return READ, ("what this field asks changed: its documents are "
                      "stale until they are harvested again (--force-stale)")
    if kind in ("axis", "value"):
        if state == "new":
            return READ, ("a stored document was not asked this: --top-up "
                          "asks it of the stored values"
                          if kind == "axis" else
                          "a stored document was not asked this list and is "
                          "stale in this key")
        if _grew(old, new, key):
            return REMAP, "the list grew: --remap settles it without a model"
        if kind == "axis":
            return READ, ("the question or an entry of this coordinate "
                          "changed: --remap maps the stored wordings onto "
                          "the list without a model, --top-up asks the "
                          "coordinate again (a coordinate of the frame "
                          "needs --force-stale)")
        return READ, ("an entry of this field's own list changed: --remap "
                      "maps the stored wordings onto the list without a "
                      "model; a wording it cannot place leaves the document "
                      "stale")
    if key == "slot/parameter":
        return READ, ("the question that assigns a value to a field, or the "
                      "fields it offers, changed: stored documents are "
                      "stale until they are harvested again (--force-stale)")
    if key == "slot/unit":
        return READ, ("the unit question or the units it offers changed: "
                      "--top-up asks the unit of the stored values again")
    return READ, "a stored document is stale in this key"


def changes(old: dict, new: dict) -> list:
    """What an edit changes for the run: one entry per question whose
    fingerprint moved, [] where it moved none.

    The keys are the stamp's (`spec.fingerprints`), in the order of the new
    spec, a key the new spec no longer has last.
    """
    before, after = _prints(old), _prints(new)
    added = _by_addition(old, new, before, after)
    out: list = []
    for key in list(after) + [k for k in before if k not in after]:
        if before.get(key) == after.get(key):
            continue
        state = ("new" if key not in before
                 else "gone" if key not in after else "changed")
        effect, text = _effect(key, state, old, new, key in added)
        out.append({"key": key, "state": state, "effect": effect,
                    "text": text, "documents": None})
    return out


def name_of(stamp: Path) -> str:
    """The document a stamp file belongs to."""
    name = stamp.name
    return name[:-len(".stamp.json")] if name.endswith(".stamp.json") \
        else stamp.stem


def affected(stamps: list, old: dict, new: dict) -> dict:
    """{key: [documents]} an edit makes stale: the documents whose stamp is
    current in that key under the spec on disk and not under the edited one,
    asked of the run's own comparison (`runner.stale`)."""
    from ..extraction import runner            # heavy, and only needed here
    before, after = _prints(old), _prints(new)
    out: dict = {}
    for stamp in stamps:
        was = set(runner.stale(Path(stamp), before))
        for key in runner.stale(Path(stamp), after):
            if key not in was:
                out.setdefault(key, []).append(name_of(Path(stamp)))
    return out


# -- what an edit takes away ---------------------------------------------------

def _labels(entry) -> list:
    if isinstance(entry, dict):
        return [entry.get("label")] + list(entry.get("spellings") or [])
    return list(entry or []) if isinstance(entry, list) else []


def _gone_from_list(where: str, old, new) -> list:
    """What a list lost: entries, and names or spellings of entries it
    still has."""
    out: list = []
    for uri, entry in (old or {}).items() if isinstance(old, dict) else ():
        if not isinstance(new, dict) or uri not in new:
            out.append(f"entry {uri} of {where}")
            continue
        kept = set(map(str, _labels(new[uri])))
        for position, label in enumerate(_labels(entry)):
            if str(label) not in kept:
                what = "name" if position == 0 else "spelling"
                out.append(f"{what} {label!r} of entry {uri} of {where}")
    return out


def _by_uri(data: dict) -> dict:
    return {p.get("uri"): p for p in data.get("parameters", [])
            if isinstance(p, dict)} if isinstance(data, dict) else {}


def removed(old: dict, new: dict) -> list:
    """What the edited spec no longer has that the spec on disk has, in
    words: fields, coordinates, entries of lists, names and spellings, units,
    groups, and the blocks of what a document settles and of its works.

    A changed text is no removal. These are the things a harvest was read
    against or asked through, so taking one away is confirmed before it is
    written.
    """
    out: list = []
    now = _by_uri(new)
    for uri, parameter in _by_uri(old).items():
        if uri not in now:
            out.append(f"field {uri}")
            continue
        other = now[uri]
        for key in ("vocabulary", "beside"):
            out += _gone_from_list(f"field {uri}" if key == "vocabulary"
                                   else f"field {uri} (beside)",
                                   parameter.get(key), other.get(key))
        for unit in (parameter.get("units_accepted") or {}):
            if unit not in (other.get("units_accepted") or {}):
                out.append(f"unit {unit!r} of field {uri}")
        axes, other_axes = parameter.get("axes") or {}, other.get("axes") or {}
        for name, axis in axes.items():
            if name not in other_axes:
                out.append(f"coordinate {name} of field {uri}")
                continue
            where = f"coordinate {uri}.{name}"
            for key in ("vocabulary", "beside"):
                out += _gone_from_list(where if key == "vocabulary"
                                       else f"{where} (beside)",
                                       (axis or {}).get(key),
                                       (other_axes[name] or {}).get(key))
            kept = set(other_axes[name].get("enum") or [])
            out += [f"choice {choice!r} of {where}"
                    for choice in (axis or {}).get("enum") or []
                    if choice not in kept]
    for name in (old.get("groups") or {}):
        if name not in (new.get("groups") or {}):
            out.append(f"group {name}")
    for key in (old.get("plan_fields") or {}):
        if key not in (new.get("plan_fields") or {}):
            out.append(f"what a document settles: {key}")
    if old.get("works") is not None:
        if new.get("works") is None:
            out.append("the list of other works")
        else:
            kept = (new["works"].get("fields") or {})
            out += [f"question for {uri} of the list of other works"
                    for uri in (old["works"].get("fields") or {})
                    if uri not in kept]
    for key in ("parameter_question", "unit_question"):
        if old.get(key) is not None and new.get(key) is None:
            out.append(f"the question {key}")
    return out


# -- the report of a check, and a save -----------------------------------------

NO_HARVEST = ("no harvest folder was given (--harvest), so the documents an "
              "edit makes stale are not counted")
NO_STAMPS = ("the harvest folder holds no stamp (*.stamp.json), so the "
             "documents an edit makes stale are not counted")


def judge(old_raw: bytes, data: dict, stamps: Optional[list] = None,
          snapshot: Optional[dict] = None, name: str = "extraction_spec.json"
          ) -> dict:
    """Everything the page shows after "Check", for the spec *data* against
    the file's bytes *old_raw*; nothing is written.

    *stamps* are the stamp files of a harvest, None where the editor was
    given none; *snapshot* the profile's ontology snapshot, for the notes on
    definitions that differ from it.
    """
    try:
        old = parse(old_raw)
    except (ValueError, UnicodeDecodeError):
        old = {}
    data = as_written(old, data)
    error = problem(data)
    moved = changes(old, data) if error is None else []
    note = None
    if stamps is None:
        note = NO_HARVEST
    elif not stamps:
        note = NO_STAMPS
    elif moved:
        hit = affected(stamps, old, data)
        for change in moved:
            change["documents"] = sorted(hit.get(change["key"], []))
    newline = newline_of(old_raw)
    before = old_raw.decode("utf-8", errors="replace").replace("\r\n", "\n")
    after = dump(data)
    diff = list(difflib.unified_diff(
        before.splitlines(), after.splitlines(),
        f"a/{name}", f"b/{name}", lineterm="", n=2))
    body = [line for line in diff if not line.startswith(("+++", "---"))]
    return {"ok": error is None, "error": error, "changes": moved,
            "documents_note": note, "removed": removed(old, data),
            "notes": notes(data, snapshot) if snapshot else [],
            "lines": {"added": sum(line.startswith("+") for line in body),
                      "removed": sum(line.startswith("-") for line in body)},
            "diff": "\n".join(diff), "text": dump(data, newline)}


def save(old_raw: bytes, data: dict, *, confirm: bool = False,
         stamps: Optional[list] = None, snapshot: Optional[dict] = None,
         name: str = "extraction_spec.json") -> tuple:
    """(what the page is told, the bytes to write or None).

    Bytes come back only for a spec the loader takes, and for one that takes
    something away only with *confirm*. The caller writes them; this decides.
    """
    report = judge(old_raw, data, stamps, snapshot, name)
    text = report.pop("text")
    if not report["ok"]:
        return {"saved": False, "reason": "check", **report}, None
    if report["removed"] and not confirm:
        return {"saved": False, "reason": "confirm", **report}, None
    return {"saved": True, **report}, text.encode("utf-8")


# -- copies and removals -------------------------------------------------------

class Refused(ValueError):
    """An operation the editor does not carry out; `where` names the place."""

    def __init__(self, where: str, message: str):
        super().__init__(f"{where}: {message}")
        self.where, self.message = where, message

    def said(self) -> dict:
        return {"where": self.where, "message": self.message}


def _new_key(where: str, key, taken) -> str:
    key = str(key or "").strip()
    if not key:
        raise Refused(where, "a copy needs a key of its own")
    if any(char.isspace() for char in key) or "/" in key:
        raise Refused(where, f"{key!r} cannot be a key: no blank and no "
                             f"slash, a stamp names a question by "
                             f"<field>/<coordinate>")
    if key in taken:
        raise Refused(where, f"{key!r} is taken already")
    return key


def _field(data: dict, uri: str) -> tuple:
    for position, parameter in enumerate(data.get("parameters") or []):
        if isinstance(parameter, dict) and parameter.get("uri") == uri:
            return position, parameter
    raise Refused(f"field {uri}", "the spec has no such field")


def _after(mapping: dict, key: str, new_key: str, value) -> dict:
    """*mapping* with *new_key* right after *key*."""
    out: dict = {}
    for name, held in mapping.items():
        out[name] = held
        if name == key:
            out[new_key] = value
    return out


def copy_field(data: dict, uri: str, key: str) -> dict:
    """The spec with a copy of a field under a new key, right after it: all
    its coordinates and lists, and no example, because an example is a
    passage of a document with the values it states and a field has its
    own."""
    out = copy.deepcopy(data)
    position, original = _field(out, uri)
    key = _new_key(f"field {uri}", key, _by_uri(out))
    made = {name: value for name, value in copy.deepcopy(original).items()
            if name != "example"}
    made["uri"] = key
    out["parameters"].insert(position + 1, made)
    return out


def copy_coordinate(data: dict, uri: str, name: str, key: str) -> dict:
    """The spec with a copy of a coordinate of a field under a new name,
    right after it, in the group of its original and with what the group
    says of the original."""
    out = copy.deepcopy(data)
    _, parameter = _field(out, uri)
    axes = parameter.get("axes") or {}
    if name not in axes:
        raise Refused(f"coordinate {uri}.{name}",
                      "the field has no such coordinate")
    key = _new_key(f"coordinate {uri}.{name}", key, axes)
    parameter["axes"] = _after(axes, name, key, copy.deepcopy(axes[name]))
    for group in (out.get("groups") or {}).values():
        for listed in ("coordinates", "own_passage", "own_value", "pair"):
            members = group.get(listed)
            if isinstance(members, list) and name in members \
                    and key not in members:
                members.insert(members.index(name) + 1, key)
    return out


def _prune_groups(data: dict) -> None:
    """Takes out of the groups every coordinate no field has any more, and a
    group left without one: the loader refuses both."""
    known = {name for parameter in data.get("parameters") or []
             if isinstance(parameter, dict)
             for name in (parameter.get("axes") or {})}
    numeric = any(isinstance(p, dict)
                  and p.get("value_type", "float") in spec_module.NUMERIC_TYPES
                  for p in data.get("parameters") or [])
    if data.get("unit_question") and numeric:
        known.add(spec_module.UNIT)
    groups = data.get("groups")
    if not isinstance(groups, dict):
        return
    for name in list(groups):
        group = groups[name]
        for listed in ("coordinates", "own_passage", "own_value", "pair"):
            if isinstance(group.get(listed), list):
                group[listed] = [c for c in group[listed] if c in known]
        if not group.get("coordinates"):
            del groups[name]


def _list_of(data: dict, uri: str, coordinate: Optional[str],
             which: str) -> tuple:
    """(the block that holds a list, the list) of a field or a
    coordinate."""
    if which not in ("vocabulary", "beside"):
        raise Refused(f"field {uri}", f"{which!r} is no list")
    _, parameter = _field(data, uri)
    where = f"field {uri}"
    block = parameter
    if coordinate is not None:
        block = (parameter.get("axes") or {}).get(coordinate)
        where = f"coordinate {uri}.{coordinate}"
        if not isinstance(block, dict):
            raise Refused(where, "the field has no such coordinate")
    listed = block.get(which)
    if not isinstance(listed, dict):
        raise Refused(where, f"has no {which}")
    return where, listed


def remove(data: dict, kind: str, **named) -> dict:
    """The spec without one thing: a field, a coordinate, an entry of a
    list, a spelling, something a document settles, or the works block.

    Nothing is written here. What follows from a removal goes with it, so
    the result still loads: a coordinate no field has any more leaves its
    group, and a question the works block asks of a removed field leaves the
    block.
    """
    out = copy.deepcopy(data)
    if kind == "field":
        position, _ = _field(out, named.get("field"))
        del out["parameters"][position]
        fields = (out.get("works") or {}).get("fields")
        if isinstance(fields, dict):
            fields.pop(named.get("field"), None)
        _prune_groups(out)
    elif kind == "coordinate":
        uri, name = named.get("field"), named.get("coordinate")
        _, parameter = _field(out, uri)
        if name not in (parameter.get("axes") or {}):
            raise Refused(f"coordinate {uri}.{name}",
                          "the field has no such coordinate")
        del parameter["axes"][name]
        _prune_groups(out)
    elif kind in ("entry", "spelling"):
        where, listed = _list_of(out, named.get("field"),
                                 named.get("coordinate"),
                                 named.get("list") or "vocabulary")
        entry = named.get("entry")
        if entry not in listed:
            raise Refused(where, f"has no entry {entry!r}")
        if kind == "entry":
            del listed[entry]
        else:
            spelling = named.get("spelling")
            held = listed[entry]
            rest = held.get("spellings") if isinstance(held, dict) \
                else held[1:] if isinstance(held, list) else None
            if not isinstance(rest, list) or spelling not in rest:
                raise Refused(where, f"entry {entry!r} has no spelling "
                                     f"{spelling!r}; its name is changed, "
                                     f"not removed")
            if isinstance(held, dict):
                held["spellings"].remove(spelling)
            else:
                del held[1 + rest.index(spelling)]
    elif kind == "plan_field":
        fields = out.get("plan_fields")
        key = named.get("key")
        if not isinstance(fields, dict) or key not in fields:
            raise Refused("what a document settles",
                          f"the spec has no {key!r}")
        del fields[key]
        if not fields:
            del out["plan_fields"]
    elif kind == "works":
        if out.pop("works", None) is None:
            raise Refused("the list of other works", "the spec has none")
    else:
        raise Refused("remove", f"{kind!r} is nothing the editor removes")
    return out


# -- the ontology snapshot beside the spec -------------------------------------

def _folded(text) -> str:
    return " ".join(str(text or "").split())


def _all_lists(data: dict):
    """(where, the uri of the field, the coordinate or None, list key, the
    list) for every closed list of the spec."""
    for parameter in data.get("parameters") or []:
        if not isinstance(parameter, dict):
            continue
        uri = parameter.get("uri")
        for key in ("vocabulary", "beside"):
            if isinstance(parameter.get(key), dict):
                yield f"{uri}", uri, None, key, parameter[key]
        for name, axis in (parameter.get("axes") or {}).items():
            for key in ("vocabulary", "beside"):
                if isinstance(axis, dict) and isinstance(axis.get(key), dict):
                    yield f"{uri}.{name}", uri, name, key, axis[key]


def pin(data: dict, snapshot: dict) -> dict:
    """{entry: the snapshot's term} for every entry of the spec's lists that
    is a term of the profile's ontology snapshot."""
    terms = snapshot.get("terms") or {}
    out: dict = {}
    for _where, _uri, _name, _key, listed in _all_lists(data):
        for entry in listed:
            term = terms.get(ontology.identifier(entry) or "")
            if term is not None and entry not in out:
                out[entry] = _term(ontology.identifier(entry), term)
    return out


def _term(key: str, term: dict) -> dict:
    return {"id": key, "label": term.get("label"),
            "definition": term.get("definition"),
            "alt_labels": list(term.get("alt_labels") or []),
            "deprecated": bool(term.get("deprecated"))}


def notes(data: dict, snapshot: dict) -> list:
    """Where the spec's definition of an entry is not the snapshot's, one
    note per entry and list: the rule and the line of the profile check
    (`ontology.definition_differences`, `ontology.definition_note`), said
    for every place and not once per class, so the page can mark the row."""
    terms = snapshot.get("terms") or {}
    out: list = []
    for where, _uri, _name, key, listed in _all_lists(data):
        if key != "vocabulary":
            continue
        for entry, held in listed.items():
            name = ontology.identifier(entry)
            term = terms.get(name or "")
            if term is None:
                continue
            theirs = _folded(term.get("definition"))
            ours = _folded(held.get("definition")
                           if isinstance(held, dict) else "")
            if not theirs or ours == theirs:
                continue
            kind = ontology.REWRITTEN if ours else ontology.PIN_ONLY
            out.append({"where": where, "id": entry, "kind": kind,
                        "text": ontology.definition_note(
                            (where, name, kind, ours, theirs)).strip()})
    return out


def terms(snapshot: dict, query: str, limit: int = 50) -> dict:
    """The terms of the snapshot whose identifier, label and alternative
    labels together contain every word of *query*, for choosing a new
    entry: {"terms", "total"}."""
    wanted = str(query or "").casefold().strip()
    found: list = []
    for key, term in (snapshot.get("terms") or {}).items():
        said = " ".join([key, term.get("label") or ""] + list(
            term.get("alt_labels") or [])).casefold()
        if all(word in said for word in wanted.split()):
            found.append(_term(key, term))
    # A label that starts with the words first, then by label.
    found.sort(key=lambda t: (not str(t["label"] or "").casefold()
                              .startswith(wanted),
                              str(t["label"] or "").casefold(), t["id"]))
    return {"terms": found[:max(1, int(limit))], "total": len(found)}


# -- the form: the fields `spec.py` knows, with its comments -------------------

def _comments(cls) -> dict:
    """{field: the comment the code writes at it} of a dataclass of
    `spec.py`: the comment lines above a field and the one behind it."""
    out: dict = {}
    pending: list = []
    for line in inspect.getsource(cls).splitlines():
        text = line.strip()
        if text.startswith("#"):
            pending.append(text.lstrip("#").strip())
            continue
        match = re.match(r"^    (\w+): [^#]*?(?:#\s*(.*))?$", line)
        if match:
            words = pending + ([match.group(2)] if match.group(2) else [])
            if words:
                out[match.group(1)] = " ".join(w for w in words if w)
        pending = []
    return out


# What the form says of a key the dataclasses leave without a comment.
_OWN_HELP = {
    ("parameter", "uri"): "The key of the field: it names the field in "
                          "every stamp and in every row of a harvest.",
    ("parameter", "label"): "The name of the field as a request shows it.",
    ("parameter", "description"): "What a value of this field is, in the "
                                  "ontology's words: the definition a "
                                  "request shows (at least 8 words).",
    ("parameter", "value_type"): "What a value is: a number (float, int), "
                                 "the document's own words (text) or an "
                                 "entry of a list (category).",
    ("parameter", "unit_target"): "The unit every value of a numeric field "
                                  "is converted onto.",
    ("parameter", "units_accepted"): "The units a number of this field may "
                                     "be printed in, each with its factor "
                                     "onto the target unit.",
    ("parameter", "example"): "A real passage of a document and the values "
                              "it states: the example a request shows and "
                              "the run's golden test.",
    ("axis", "required"): "Whether a value without this coordinate is "
                          "refused.",
    ("entry", "label"): "The name of the entry: what the model is offered "
                        "and answers with.",
    ("entry", "spellings"): "Other ways a document writes this entry; a "
                            "stored wording is mapped onto the entry by "
                            "them.",
    ("unit", "factor"): "The factor onto the field's target unit.",
    ("spec", "_comment"): "A note for people; no request shows it and no "
                          "stamp depends on it.",
    ("group", "coordinates"): "The coordinates of this group; each "
                              "coordinate of the spec is in exactly one "
                              "group.",
    ("group", "read_in"): "The step that reads the group.",
    ("plan_field", "name"): "The name a request shows for it.",
    ("plan_field", "means"): "What it is, as a request shows it.",
    ("plan_field", "sentence"): "A sentence in the document's form, which "
                                "the pieces it is asked over are found "
                                "with.",
    ("plan_field", "of"): "Which values of the document are of this state "
                          "of it: a coordinate of a group's pair and the "
                          "entry of its list. Read only by a pass over a "
                          "stored harvest (--top-up, --top-up-open), which "
                          "takes this year from the stored values; a run "
                          "that reads a document asks it the year and does "
                          "not read this.",
    ("works", "name"): "The name a request shows for another work.",
    ("works", "means"): "What counts as another work, as a request shows "
                        "it.",
    ("works", "fields"): "What is asked at the line of a new work: field "
                         "-> the question.",
}

# kind -> (key, widget, the dataclass field its comment stands at, extras)
_FORM = {
    "spec": [("_comment", "lines", None, {}),
             ("parameter_question", "text", "parameter_question", {}),
             ("unit_question", "text", "unit_question", {})],
    "group": [("coordinates", "strings", "coordinates", {}),
              ("where", "text", "where", {}),
              ("read_in", "choice", "read_in",
               {"choices": list(spec_module.READ_IN)}),
              ("definition", "choice", "full_definition",
               {"choices": list(spec_module.DEFINITIONS),
                "default": "brief"}),
              ("own_passage", "strings", "own_passage", {}),
              ("own_value", "strings", "own_value", {}),
              ("pair", "strings", "pair", {})],
    "parameter": [("uri", "line", "uri", {}),
                  ("label", "line", "label", {}),
                  ("description", "text", "description", {}),
                  ("brief", "text", "brief", {}),
                  ("value_type", "choice", "value_type",
                   {"choices": list(spec_module.VALUE_TYPES),
                    "default": "float"}),
                  ("once_per_document", "bool", "once_per_document",
                   {"default": False}),
                  ("takes_group", "bool", "takes_group",
                   {"default_rule": "default_takes_group"}),
                  ("merged", "line", "merged", {}),
                  ("vocabulary_dynamic", "bool", "vocabulary_dynamic",
                   {"default": False}),
                  ("unit_target", "line", "unit_target", {}),
                  ("integrated", "bool", "integrated", {"default": True}),
                  ("units_accepted", "units", "units_accepted", {}),
                  ("example", "example", "example", {}),
                  ("kg", "kg", "kg", {"of": "field"})],
    "axis": [("question", "text", "question", {}),
             ("required", "bool", "required", {"default": False}),
             ("several", "bool", "several", {"default": False}),
             ("merged", "line", "merged", {}),
             ("keep", "line", "keep", {}),
             ("derive", "derive", "derive", {}),
             ("kg", "kg", "kg", {"of": "axis"})],
    "entry": [("label", "line", None, {}),
              ("spellings", "strings", None, {}),
              ("definition", "text", "definitions", {}),
              ("gloss", "text", "glosses", {}),
              ("group", "line", "groups", {})],
    "unit": [("factor", "number", None, {}),
             ("names_period", "bool", "unit_names_period", {}),
             ("target", "line", "unit_targets", {})],
    "plan_field": [("name", "line", None, {}),
                   ("means", "text", None, {}),
                   ("sentence", "text", None, {}),
                   ("of", "entry_of", None,
                    {"only": list(spec_module.YEAR_FIELDS)})],
    "works": [("name", "line", None, {}),
              ("means", "text", None, {}),
              ("fields", "questions", None, {})],
}

# Where the comment of a form's keys stands in `spec.py`.
_SOURCE = {"spec": spec_module.Spec, "group": spec_module.Group,
           "parameter": spec_module.Parameter, "axis": spec_module.Axis,
           "entry": spec_module.Axis, "unit": spec_module.Parameter,
           "plan_field": spec_module.Spec, "works": spec_module.Spec}


def kg_keys(profile=None) -> dict:
    """{"field": [...], "axis": [...], "why": None or the reason none are
    known}: the keys of a `kg` block the profile's graph writer reads, each
    {"key", "kind", "help"} (`KG_KEYS` of its kg.py). A key not listed is
    one the writer does not name; the page keeps it and shows it greyed."""
    from ..profile import active_profile
    profile = profile or active_profile()
    if profile is None:
        return {"field": [], "axis": [], "why": "no profile is active"}
    try:
        declared = profile.component("kg", "KG_KEYS")
    except Exception as exc:         # a writer that does not import
        return {"field": [], "axis": [], "why": f"the writer of "
                f"{profile.name} cannot be loaded: {exc}"}
    if not isinstance(declared, dict):
        return {"field": [], "axis": [],
                "why": f"the writer of {profile.name} names no keys"}
    return {"field": list(declared.get("field", [])),
            "axis": list(declared.get("axis", [])), "why": None}


def form(profile=None) -> dict:
    """The form of each kind of node, {kind: [{"key", "widget", "help",
    ...}]}: the keys `spec.py` reads, each with the comment the code writes
    at its field. A key that is not here is one the form does not know; the
    page leaves it in the file as it is."""
    out: dict = {}
    for kind, fields in _FORM.items():
        comments = _comments(_SOURCE[kind])
        out[kind] = []
        for key, widget, attribute, extras in fields:
            said = _OWN_HELP.get((kind, key)) or comments.get(attribute, "")
            extras = dict(extras)
            if "default_rule" in extras:
                # The default a run takes is a rule's, as the rules say it.
                extras["default"] = rules.get(extras.pop("default_rule"))
            out[kind].append({"key": key, "widget": widget, "help": said,
                              **extras})
    for kind, attribute in (("plan_field", "plan_fields"),
                            ("works", "works")):
        out[kind][0]["about"] = _comments(spec_module.Spec).get(attribute, "")
    out["kg_keys"] = kg_keys(profile)
    return out
