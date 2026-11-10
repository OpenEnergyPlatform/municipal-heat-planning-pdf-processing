"""
flow.py: A profile's flow for the editor: its steps as a diagram shows them,
its numbers with where each comes from, the check of edited numbers and what
a save writes.

The flow itself is the run's (`extraction.flow`): its file, its strict
reading, the numbers a run takes and the settings that win over them. This
module only turns it into what the page draws and decides what a save does
to the profile's own file:

- `view`: every number with its value, whether the profile sets it itself,
  what it inherits and what a run started here would read with; every step
  with its bound cut into texts and numbers, the prompt of the request it
  asks, why this profile never takes it (`off`), and the switches of the
  spec that belong to it, each entry a link into the spec.
- `judge`: whether edited numbers are numbers of the flow, what changes and
  what the profile's file would then be. A profile that extends another
  writes only the numbers that differ from what it inherits, so a number
  set back leaves the file, and a file that would hold none is removed.
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

from .. import settings
from ..extraction import flow as flow_map
from ..extraction.spec import YEAR_FIELDS
from . import prompts as prompt_files

STAGE = "extraction"
# The passes that take a document's own years from its stored values.
PASSES = "--top-up, --top-up-open"
STALE = ("A changed flow makes no harvest stale: a stamp names the numbers "
         "each pass read a document with and is compared by its questions "
         "alone.")
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
    "plan_fields": ("asked once of a document",
                    "the spec asks nothing once of a document", _plan_fields),
    "works": ("the list of other works",
              "the spec keeps no list of other works", _works),
    "names": ("the names a document's lists are built from",
              "the spec builds no list of names", _names),
    "once_per_document": (
        "fields the document has once",
        "the spec marks no field as once per document",
        lambda data: [_field(p) for p in _fields(data)
                      if p.get("once_per_document")]),
    "own_passage": (
        "only the value's own passage says them, so they are never searched",
        "the spec names no such coordinate", _of_group("own_passage")),
    "own_value": (
        "printed with the value itself, asked once and never searched",
        "the spec names no such coordinate", _of_group("own_value")),
    "takes_group": (
        "fields that keep the words of a group as they stand",
        "every field takes the members of a group",
        lambda data: [_field(p) for p in _fields(data)
                      if p.get("takes_group") is False]),
    "compute": ("the profile computes", "this profile computes nothing",
                lambda data: []),
}
if set(SWITCHES) != set(flow_map.SWITCHES):
    raise AssertionError("editor.flow.SWITCHES and extraction.flow.SWITCHES "
                         "name different switches")


def _switch(name: str, data: Optional[dict]) -> dict:
    label, none, items = SWITCHES[name]
    return {"name": name, "label": label, "none": none,
            "items": items(data) if data is not None else []}


def _bound(text: Optional[str]) -> Optional[list]:
    """A bound cut into its texts and its numbers, in order."""
    if not text:
        return None
    out: list = []
    for i, part in enumerate(flow_map.PLACE.split(text)):
        if i % 2:
            out.append({"number": part})
        elif part:
            out.append(part)
    return out


def _step(step: dict, data: Optional[dict], owners: dict,
          computes: bool) -> dict:
    kind = step.get("ask")
    prompt = None
    off = None
    if kind is not None:
        prompt_id = f"{STAGE}/{kind}"
        owner = owners.get(prompt_id)
        prompt = {"id": prompt_id, "written": owner is not None,
                  "owner": owner}
        if owner is None:
            off = (f"no profile of the line writes the prompt {prompt_id}, "
                   f"so no run asks it")
    needs = step.get("needs")
    if needs is not None and off is None:
        if needs == "compute":
            held = computes
        else:
            held = data is not None and bool(SWITCHES[needs][2](data))
        if not held:
            off = (SWITCHES[needs][1] if data is not None
                   or needs == "compute"
                   else "this profile has no extraction spec")
    return {"id": step["id"], "ask": kind, "each": step.get("each"),
            "when": step.get("when"), "says": step["says"],
            "bound": _bound(step.get("bound")), "prompt": prompt, "off": off,
            "switches": [_switch(name, data)
                         for name in step.get("shows") or ()],
            "steps": [_step(inner, data, owners, computes)
                      for inner in step["steps"]]
            if step.get("steps") else None}


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
        which = " and ".join(f"{name} is {value}"
                             for name, value in rule.items())
        out.append({
            "says": f"{key}: a pass over a stored harvest ({PASSES}) takes "
                    f"it from the stored values whose {which}. A run that "
                    f"reads a document asks it for the year (the step "
                    f"\"settled\") and does not read this rule.",
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
    owners = {row["id"]: row["owner"]
              for row in prompt_files.listing(profile)}
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
    return {"file": shown(flow_map.path_of(profile)),
            "exists": own_raw is not None,
            "base": sha256(own_raw) if own_raw is not None else None,
            "whole": below is None, "starts_from": flow.files[-1][0],
            "numbers": numbers,
            "steps": [_step(step, data, owners, computes)
                      for step in flow.steps],
            "notes": _notes(data), "settings": _settings()}


# -- check and save ----------------------------------------------------------------

def _text(raw: Optional[bytes]) -> Optional[str]:
    return None if raw is None else raw.decode("utf-8").replace(CR + LF, LF)


def judge(profile, own_raw: Optional[bytes], numbers, name: str) -> dict:
    """What a save of *numbers* ({name: value}, those not named as the
    files say them) would do: {"ok", "errors": [{"name", "message"}],
    "changed": [{"name", "from", "to"}], "file", "writes" ("created",
    "changed", "removed", "unchanged"), "diff", "says", "text"}. *text* is
    the profile's file as it would stand, in the line ends it has (plain
    ones where it is new), None where it would be removed. *name* is the
    file as the user sees it."""
    flow = flow_map.load(profile)
    below = flow_map.inherited(profile)
    errors = []
    values = dict(flow.numbers)
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
        # The profile's own file is the whole flow: its steps stay.
        whole = json.loads(old) if old is not None else {}
        new = flow_map.dump({**whole, "numbers": {
            number.name: values[number.name]
            for number in flow_map.NUMBERS}})
    else:
        own = {number.name: values[number.name]
               for number in flow_map.NUMBERS
               if values[number.name] != below.numbers[number.name]}
        new = flow_map.dump({"numbers": own}) if own else None
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
                f"{number.env} is set here "
                f"({in_effect.origin[number.name]}: "
                f"{os.environ[number.env]}) and wins over the file for a "
                f"run started here.")
    return {"ok": not errors, "errors": errors,
            "changed": [{"name": number.name,
                         "from": flow.numbers[number.name],
                         "to": values[number.name]}
                        for number in flow_map.NUMBERS
                        if values[number.name] != flow.numbers[number.name]],
            "file": name, "writes": writes, "diff": diff, "says": says,
            "text": None if new is None else new.replace(LF, newline)}


def save(profile, own_raw: Optional[bytes], numbers, base: Optional[str],
         name: str) -> tuple:
    """(what the page is told, the bytes to write or None, whether the
    file is to be removed). Bytes come back only for numbers the flow
    takes, and only where the file is as the page loaded it (*base*, the
    sha256 of its bytes, None where it had none)."""
    report = judge(profile, own_raw, numbers, name)
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
