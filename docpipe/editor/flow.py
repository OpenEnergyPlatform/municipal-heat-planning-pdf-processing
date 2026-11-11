"""
flow.py: A profile's flow for the editor: its drawing of boxes and frames,
the library they come from, its numbers with where each comes from, the
check of an edited drawing and what a save writes.

The flow itself is the run's (`extraction.flow`): its file, its strict
reading, the drawing the run does (`extraction.engine`), the numbers a run
takes and the settings that win over them. This module only turns it into
what the page draws and decides what a save does to the profile's own file:

- `view`: the drawing as the file says it, the library of boxes and frames
  (`extraction.blocks`), what a condition can be about
  (`extraction.conditions`), every number with its value, whether the
  profile sets it itself, what it inherits and what a run started here
  would read with; for each kind of box why this profile never takes it
  (its prompt unwritten, its switch of the spec off), the prompt of each
  request and the entries of the spec each switch stands for, each a link
  into the spec; and what the run could not do with the drawing.
- `judge`: whether edited numbers are numbers of the flow and an edited
  drawing one the run can do (`flow.problems`, `flow.prompt_problems`),
  what changes and what the profile's file would then be. A profile that
  extends another writes only the numbers that differ from what it
  inherits and the drawing where it differs, so a number set back leaves
  the file, and a file that would hold nothing is removed.
- `save`: `judge`, and the bytes to write where it holds.

No file is read here but through the run's loader; the server checks every
path first and hands in the bytes of the profile's own file.

Author: Felix Vossel
"""
from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
from typing import Callable, Optional
from urllib.parse import urlsplit, urlunsplit

from .. import rules, settings
from ..extraction import blocks, conditions
from ..extraction import flow as flow_map
from ..extraction.spec import YEAR_FIELDS
from . import prompts as prompt_files

STAGE = "extraction"
# The passes that take a document's own years from its stored values.
PASSES = "--top-up, --top-up-open"
STALE = ("Saving a changed flow does not make the harvests that are "
         "already written stale. They stay valid, and a run you start reads "
         "with the new flow.")
CR, LF = "\r", "\n"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# -- the switches of a spec a step shows ---------------------------------------

def _fields(data: dict) -> list:
    return [p for p in data.get("parameters") or ()
            if isinstance(p, dict) and isinstance(p.get("uri"), str)]


def _field(parameter: dict) -> dict:
    return {"label": parameter["uri"],
            "to": {"t": "param", "uri": parameter["uri"]}}


def _plan_fields(data: dict) -> list:
    fields = data.get("plan_fields")
    return [{"label": key, "to": {"t": "plan", "key": key}}
            for key in (fields if isinstance(fields, dict) else {})]


def _works(data: dict) -> list:
    works = data.get("works")
    if not isinstance(works, dict):
        return []
    return [{"label": works.get("name") or "works", "to": {"t": "works"}}]


def _of_group(key: str) -> Callable:
    def items(data: dict) -> list:
        groups = data.get("groups")
        return [{"label": f"{coordinate} ({name})",
                 "to": {"t": "group", "name": name}}
                for name, group in (groups if isinstance(groups, dict)
                                    else {}).items()
                for coordinate in (group.get(key) or ()
                                   if isinstance(group, dict) else ())]
    return items


def _names(data: dict) -> list:
    """The fields and coordinates the document's lists of names are built
    from, each coordinate once (at the first field that carries it), and
    the list of other works."""
    out = [_field(p) for p in _fields(data) if p.get("merged")]
    seen: set = set()
    for parameter in _fields(data):
        for name, axis in (parameter.get("axes") or {}).items():
            if isinstance(axis, dict) and axis.get("merged") \
                    and name not in seen:
                seen.add(name)
                out.append({"label": name,
                            "to": {"t": "axis", "uri": parameter["uri"],
                                   "name": name}})
    return out + _works(data)


# name -> (what the list is, what is said where it is empty, its entries)
SWITCHES = {
    "plan_fields": (
        "fields of the whole document",
        "The spec has no field of the whole document, so nothing is asked "
        "once for all values. To change it: add a field under the fields of "
        "the whole document in the Spec tab.",
        _plan_fields),
    "works": (
        "the list of other works",
        "The spec keeps no list of other works, so every value belongs to "
        "this publication. To change it: add the works in the Spec tab.",
        _works),
    "names": (
        "the names the document's lists are built from",
        "The spec builds no list of names, so no list of scenarios or works "
        "grows while a document is read. To change it: set the key `merged` "
        "on a field or a dimension in the Spec tab.",
        _names),
    "once_per_document": (
        "fields asked once per document",
        "The spec marks no field as asked once per document, so every "
        "field is asked in every chunk. To change it: check "
        "`once_per_document` on a field in the Spec tab.",
        lambda data: [_field(p) for p in _fields(data)
                      if p.get("once_per_document")]),
    "own_passage": (
        "dimensions stated only where the value stands, so never searched",
        "No group of the spec names a dimension that is stated only where "
        "the value stands. To change it: list the dimension under "
        "`own_passage` of a group in the Spec tab.",
        _of_group("own_passage")),
    "own_value": (
        "dimensions printed with the number itself, asked once and never "
        "searched",
        "No group of the spec names a dimension that is printed with the "
        "number itself. To change it: list the dimension under `own_value` "
        "of a group in the Spec tab.",
        _of_group("own_value")),
    "takes_group": (
        "fields that keep the words of a group as they stand",
        "Every field splits the words of a group into its members, so no "
        "field keeps them as they stand. To change it: uncheck "
        "`takes_group` on a field in the Spec tab.",
        lambda data: [_field(p) for p in _fields(data)
                      if not p.get("takes_group",
                                   rules.get("default_takes_group"))]),
    "compute": ("what the profile computes",
                "This profile computes nothing, so the step never takes "
                "part in a run.",
                lambda data: []),
}
def _switch(name: str, data: Optional[dict]) -> dict:
    label, none, items = SWITCHES[name]
    return {"name": name, "label": label, "none": none,
            "items": items(data) if data is not None else []}


def _prompts(profile) -> dict:
    """{request kind: {"id", "written", "owner"}} of every request a box
    asks."""
    owners = {row["id"]: row["owner"]
              for row in prompt_files.listing(profile)}
    out = {}
    for box in blocks.LIBRARY.values():
        if box.asks and box.asks not in out:
            prompt_id = f"{STAGE}/{box.asks}"
            owner = owners.get(prompt_id)
            out[box.asks] = {"id": prompt_id, "written": owner is not None,
                             "owner": owner}
    return out


def _never(prompts: dict, data: Optional[dict], computes: bool) -> dict:
    """{kind of box: why this profile never takes it}: no profile of its
    line writes its prompt, or its switch of the spec is off."""
    out = {}
    for box in blocks.LIBRARY.values():
        why = None
        if box.asks and not prompts[box.asks]["written"]:
            why = (f"Neither this profile nor the profiles it builds on "
                   f"write the prompt {prompts[box.asks]['id']}, so no run "
                   f"asks it. To change it: write that prompt for this "
                   f"profile.")
        if why is None and box.spec is not None:
            if box.spec == "compute":
                held = computes
            else:
                held = data is not None and bool(SWITCHES[box.spec][2](data))
            if not held:
                why = (SWITCHES[box.spec][1] if data is not None
                       or box.spec == "compute"
                       else "This profile has no extraction spec, so no "
                       "run takes this step.")
        if why:
            out[box.type] = why
    return out


def _notes(data: Optional[dict]) -> list:
    """What stands below the diagram: which stored values a pass over a
    stored harvest takes a document's own years from (`plan_fields`, `of`),
    which no step of a run reads."""
    out = []
    fields = (data or {}).get("plan_fields")
    for key in YEAR_FIELDS:
        entry = (fields or {}).get(key) if isinstance(fields, dict) else None
        rule = entry.get("of") if isinstance(entry, dict) else None
        if not isinstance(rule, dict) or not rule:
            continue
        which = ", ".join(f"{name} = {value}"
                          for name, value in rule.items())
        out.append({
            "says": f"{key}: a later run over a stored harvest ({PASSES}) "
                    f"takes this year from the stored values with {which}. "
                    f"A run that reads a document asks the model for the "
                    f"year and does not use this rule. To change it: edit "
                    f"the key `of` of this field in the Spec tab.",
            "to": {"t": "plan", "key": key}})
    return out


def _safe(setting, value: Optional[str]) -> tuple:
    """(what the page is sent of a setting's value, whether it is set): a
    secret is never sent, and what an address carries before its host (a
    user, a password) is left out."""
    secret = setting.secret or bool(settings.SECRET_NAME.search(setting.env))
    if secret:
        return None, bool(value)
    if value and re.match(r"^[a-z][a-z0-9+.-]*://[^/]*@", value, re.I):
        parts = urlsplit(value)
        host = parts.hostname or ""
        if parts.port:
            host += f":{parts.port}"
        value = urlunsplit(parts._replace(netloc=f"***@{host}"))
    return value, bool(value)


def _settings() -> list:
    """The settings an extraction run reads, each with its value in effect
    and where it comes from, as `docpipe config` lists them."""
    out = []
    for setting, value, origin, _shadowed in settings.rows("extract"):
        shown, is_set = _safe(setting, value)
        secret = setting.secret or bool(
            settings.SECRET_NAME.search(setting.env))
        out.append({"key": setting.key, "env": setting.env, "value": shown,
                    "origin": origin, "help": setting.help, "secret": secret,
                    "set": is_set})
    return out


# -- what the page draws ---------------------------------------------------------

def view(profile, own_raw: Optional[bytes], data: Optional[dict],
         shown: Callable, computes: bool = False) -> dict:
    """The flow of *profile* as the page draws it (see the module's head).
    *own_raw* are the bytes of the profile's own flow file, None where it
    has none; *data* its spec as written, None where it has none;
    *shown(path)* a path as the user sees it; *computes* whether the
    profile computes."""
    flow = flow_map.load(profile)
    below = flow_map.inherited(profile)
    in_effect = flow_map.in_effect(profile)
    numbers = []
    for number in flow_map.NUMBERS:
        name = number.name
        numbers.append({
            "name": name, "help": number.help, "least": number.least,
            "value": flow.numbers[name],
            "own": flow.owners[name] == profile.name,
            "inherited": below.numbers[name] if below is not None else None,
            "owner": flow.owners[name], "setting": number.env,
            "in_effect": getattr(in_effect, name),
            "origin": in_effect.origin[name]})
    prompts = _prompts(profile)
    return {"file": shown(flow_map.path_of(profile)),
            "exists": own_raw is not None,
            "base": sha256(own_raw) if own_raw is not None else None,
            "whole": below is None, "starts_from": flow.files[-1][0],
            "drawn_by": flow.tree_from,
            "inherited_tree": below.tree if below is not None else None,
            "numbers": numbers, "tree": flow.tree,
            "library": blocks.catalogue(),
            "conditions": conditions.catalogue(),
            "prompts": prompts,
            "never": _never(prompts, data, computes),
            "switches": {name: _switch(name, data) for name in SWITCHES},
            "problems": flow_map.problems(flow.tree)
            + flow_map.prompt_problems(flow.tree, profile),
            "notes": _notes(data), "settings": _settings()}


# -- check and save ----------------------------------------------------------------

def _text(raw: Optional[bytes]) -> Optional[str]:
    return None if raw is None else raw.decode("utf-8").replace(CR + LF, LF)


def _boxes(tree: list) -> dict:
    return {node.get("id"): node for node, _ in flow_map.walk(tree)}


def tree_changes(old: list, new: list) -> list:
    """What an edit did to a drawing, one line each: boxes and frames added,
    removed, changed or moved."""
    before, after = _boxes(old), _boxes(new)
    out = [f"added {ident}" for ident in after if ident not in before]
    out += [f"removed {ident}" for ident in before if ident not in after]
    for ident, node in after.items():
        was = before.get(ident)
        if was is None:
            continue
        same = {k: v for k, v in node.items()
                if k not in ("steps", "if", "else")}
        were = {k: v for k, v in was.items()
                if k not in ("steps", "if", "else")}
        if same != were:
            out.append(f"changed {ident}")
    order_old = [i for i in before if i in after]
    order_new = [i for i in after if i in before]
    if order_old != order_new:
        out.append("moved: " + ", ".join(
            i for i, j in zip(order_new, order_old) if i != j))
    return out


def judge(profile, own_raw: Optional[bytes], numbers, name: str,
          tree=None) -> dict:
    """What a save of *numbers* ({name: value}, those not named as the
    files say them) and of the drawing *tree* (None: as the files say it)
    would do: {"ok", "errors": [{"name" or "id", "message"}], "changed":
    [{"name", "from", "to"}], "file", "writes" ("created", "changed",
    "removed", "unchanged"), "diff", "says", "text"}. *text* is the
    profile's file as it would stand, in the line ends it has (plain ones
    where it is new), None where it would be removed. *name* is the file
    as the user sees it. A drawing the run cannot do is refused with every
    reason, each at its box (`flow.problems`, `flow.prompt_problems`)."""
    flow = flow_map.load(profile)
    below = flow_map.inherited(profile)
    errors = []
    values = dict(flow.numbers)
    drawing = flow.tree if tree is None else tree
    if tree is not None:
        said = flow_map.problems(drawing) if isinstance(drawing, list) \
            else [{"id": None, "message": "the flow is a list of boxes and "
                   "frames"}]
        if not said:
            said = flow_map.prompt_problems(drawing, profile)
        errors += [{"name": None, "id": one["id"],
                    "message": one["message"]} for one in said]
    if not isinstance(numbers, dict):
        errors.append({"name": None,
                       "message": "numbers must be an object, the name of a "
                                  "number -> its value"})
        numbers = {}
    for key, value in numbers.items():
        said = flow_map.problem(key, value)
        if said is not None:
            known = key in flow_map.BY_NAME
            # The page names the number itself where it is one.
            errors.append({"name": key if known else None,
                           "message": said[len(key) + 1:]
                           if known and said.startswith(f"{key} ")
                           else said})
        else:
            values[key] = value
    old = _text(own_raw)
    # A file keeps its line ends; one that is new is written with plain ones.
    newline = CR + LF if (CR + LF).encode() in (own_raw or b"") else LF
    if below is None:
        # The profile's own file is the whole flow.
        new = flow_map.dump({"numbers": {
            number.name: values[number.name]
            for number in flow_map.NUMBERS}, "flow": drawing})
    else:
        own = {number.name: values[number.name]
               for number in flow_map.NUMBERS
               if values[number.name] != below.numbers[number.name]}
        data = {"numbers": own} if own else {}
        if drawing != below.tree:
            data["flow"] = drawing
        new = flow_map.dump(data) if data else None
    if errors:
        new = old
    writes = ("unchanged" if new == old else "created" if old is None
              else "removed" if new is None else "changed")
    diff = [] if writes == "unchanged" else list(difflib.unified_diff(
        (old or "").splitlines(), (new or "").splitlines(), name, name,
        lineterm=""))
    says = [STALE]
    told: set = set()
    in_effect = flow_map.in_effect(profile)
    for number in flow_map.NUMBERS:
        if number.env and number.env in os.environ \
                and number.env not in told:
            told.add(number.env)
            says.append(
                f"The run setting {number.env} is set here "
                f"({in_effect.origin[number.name]}: "
                f"{os.environ[number.env]}). It overrides the number of the "
                f"flow for a run started here, but not a step's own value. "
                f"To change it: unset the setting, or give the step its "
                f"own value.")
    edited = [] if errors or drawing == flow.tree else tree_changes(
        flow.tree, drawing)
    return {"ok": not errors, "errors": errors,
            "changed": [{"name": "flow", "from": "", "to": line}
                        for line in edited]
            + [{"name": number.name, "from": flow.numbers[number.name],
                "to": values[number.name]}
               for number in flow_map.NUMBERS
               if values[number.name] != flow.numbers[number.name]],
            "file": name, "writes": writes, "diff": diff, "says": says,
            "text": None if new is None else new.replace(LF, newline)}


def save(profile, own_raw: Optional[bytes], numbers, base: Optional[str],
         name: str, tree=None) -> tuple:
    """(what the page is told, the bytes to write or None, whether the
    file is to be removed). Bytes come back only for numbers the flow
    takes and an order the run can read in, and only where the file is as
    the page loaded it (*base*, the sha256 of its bytes, None where it had
    none)."""
    report = judge(profile, own_raw, numbers, name, tree)
    text = report.pop("text")
    if not report["ok"]:
        return {"saved": False, "reason": "invalid",
                "errors": report["errors"],
                "message": "; ".join(e["message"]
                                     for e in report["errors"])}, None, False
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
