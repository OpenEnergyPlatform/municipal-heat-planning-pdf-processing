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
- `pass_names`, `pass_view`, `pass_judge`, `pass_save`: the same for the
  flow of a follow-up pass (`extraction.passflow`), one file for each, by
  name: the flow of `--top-up`, `--remap` and the others, which a profile
  overrides by its own `flows/<name>.json`.

No file is read here but through the run's loader; the server checks every
path first and hands in the bytes of the profile's own file.

Author: Felix Vossel
"""
from __future__ import annotations

import difflib
import hashlib
import json
import os
from pathlib import Path
from typing import Callable, Optional

from .. import graphfile, rules, settings
from ..extraction import blocks, conditions
from ..extraction import flow as flow_map
from ..extraction import passflow
from ..extraction.spec import YEAR_FIELDS
from . import prompts as prompt_files
from . import rulespage as rule_page

STAGE = "extraction"
# The passes that take a document's own years from its stored values.
PASSES = "--top-up, --top-up-open"
STALE = ("Saving a changed flow does not make the harvests that are "
         "already written stale. They stay valid, and a run you start reads "
         "with the new flow.")
CR, LF = "\r", "\n"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# -- the switches of a spec a step shows --------------------------------------

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
        if box.flow:
            continue
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
        if box.flow:
            continue
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
    return rule_page.masked(value), bool(value)


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


# -- what a step can set for itself -------------------------------------------

def step_rules(profile) -> dict:
    """What a box or frame can set for itself (`"rules"` in flow.json,
    owner 2026-11-11: "alles soll anpassbar sein"): every rule and number of
    the flow a step reads, with its standard (the files of the profile), the
    run's value and where that comes from, and per kind of step
    (`rules.step_kind`) the names it reads. A key's value is never sent."""
    known = flow_map.known_rules(profile)
    files = rules.load(profile, environ={})
    taken = rules.load(profile)
    try:
        drawn = graphfile.load(profile, environ={})
        graph = graphfile.load(profile)
    except graphfile.GraphError:
        # A graph file the run cannot read offers none of its rules at a
        # step; the Graph tab says what is wrong with it.
        drawn = graph = None

    def standard(name: str) -> tuple:
        if name in files.values:
            return files.values[name], files.owners.get(name, "")
        return drawn.rules[name], drawn.owners.get(f"rules/{name}", "")

    def taken_of(name: str) -> tuple:
        if name in taken.values:
            return taken.values[name], taken.owners.get(name, "")
        return graph.rules[name], graph.owners.get(f"rules/{name}", "")
    flow = flow_map.load(profile)
    in_effect = flow_map.in_effect(profile)
    out, kinds = [], {}
    for one in known.values():
        if not one.steps or (one.name not in files.values
                             and (drawn is None
                                  or one.name not in drawn.rules)):
            continue
        hidden = one.secret
        out.append({
            "name": one.name, "source": "rule", "tab": one.tab,
            "group": one.group, "kind": one.kind, "help": one.help,
            "least": one.least, "most": one.most,
            "choices": list(one.choices), "columns": list(one.columns),
            "of": one.of, "empty": one.empty, "decided": one.decided,
            "setting": one.env, "machine": one.machine, "secret": hidden,
            "steps": list(one.steps),
            "standard": rule_page.value_shown(one, standard(one.name)[0]),
            "standard_from": standard(one.name)[1],
            "in_effect": rule_page.value_shown(one, taken_of(one.name)[0]),
            "origin": taken_of(one.name)[1]})
    for number in flow_map.NUMBERS:
        out.append({
            "name": number.name, "source": "number", "tab": "flow",
            "group": "Numbers of the flow", "kind": "whole",
            "help": number.help, "least": number.least, "most": None,
            "choices": [], "columns": [], "of": "text", "empty": False,
            "decided": "", "setting": number.env, "machine": False,
            "secret": False, "steps": list(number.steps),
            "standard": flow.numbers[number.name],
            "standard_from": f"{flow_map.FILE} of "
                             f"{flow.owners[number.name]}",
            "in_effect": getattr(in_effect, number.name),
            "origin": in_effect.origin[number.name]})
    for row in out:
        for kind in row["steps"]:
            kinds.setdefault(kind, []).append(row["name"])
    # the tab each rule stands in, for a link to it from any step
    return {"rules": out, "kinds": kinds,
            "tabs": {name: one.tab for name, one in known.items()}}


def own_at(tree: list) -> dict:
    """{rule or number: [{"id", "kind"} of the steps of *tree* that give it
    a value of their own]}: what a box or frame writes under "rules", and
    what a box writes under "own" for a number setting (named by its
    number)."""
    out: dict = {}

    def note(name: str, node: dict) -> None:
        out.setdefault(name, []).append(
            {"id": str(node.get("id") or ""),
             "kind": rules.step_kind(node)})
    for node, _frames in flow_map.walk(tree):
        if not isinstance(node, dict):
            continue
        given = node.get("rules")
        for name in (given if isinstance(given, dict) else {}):
            note(name, node)
        box = blocks.LIBRARY.get(node.get("box"))
        mine = node.get("own")
        for setting in (box.settings if box is not None else ()):
            if (setting.number and isinstance(mine, dict)
                    and setting.key in mine
                    and setting.number not in (given or {})):
                note(setting.number, node)
    return out


def _refused_at_steps(tree: list, known: dict) -> list:
    """[{"id", "message"}]: a key or a value of the machine set at a step.
    A key is set at the start and a value of the machine in the project
    file, so neither is a value of a step."""
    out = []
    for node, _frames in flow_map.walk(tree):
        given = node.get("rules") if isinstance(node, dict) else None
        for name in (given if isinstance(given, dict) else {}):
            one = known.get(name)
            if one is not None and one.secret:
                out.append({"id": node.get("id"), "message":
                            f"{name} is a key: it is set in .env or in the "
                            f"environment, never at a step"})
            elif one is not None and one.machine:
                out.append({"id": node.get("id"), "message":
                            f"{name} is a value of this machine: it is set "
                            f"in the project file docpipe.toml, never at "
                            f"a step"})
    return out


# -- what the page draws ------------------------------------------------------

def view(profile, own_raw: Optional[bytes], data: Optional[dict],
         shown: Callable, computes: bool = False,
         project: Optional[Path] = None) -> dict:
    """The flow of *profile* as the page draws it (see the module's head).
    *own_raw* are the bytes of the profile's own flow file, None where it
    has none; *data* its spec as written, None where it has none;
    *shown(path)* a path as the user sees it; *computes* whether the
    profile computes. *project* is the project file the machine's values
    are written to, None where the page cannot say."""
    flow = flow_map.load(profile)
    below = flow_map.inherited(profile)
    in_effect = flow_map.in_effect(profile)
    owned = own_at(flow.tree)
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
            "origin": in_effect.origin[name],
            "own_at": owned.get(name, [])})
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
            "problems": flow_map.problems(flow.tree,
                                          flow_map.known_rules(profile))
            + flow_map.prompt_problems(flow.tree, profile),
            "notes": _notes(data), "settings": _settings(),
            "step_rules": step_rules(profile),
            "run": {"machine": rule_page.machine_rows(profile),
                    "project": rule_page.project_state(project, shown)
                    if project is not None else None}}


# -- check and save -----------------------------------------------------------

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
        said = flow_map.problems(drawing, flow_map.known_rules(profile)) \
            if isinstance(drawing, list) \
            else [{"id": None, "message": "the flow is a list of boxes and "
                   "frames"}]
        if not said:
            said = flow_map.prompt_problems(drawing, profile)
        if not said:
            said = _refused_at_steps(drawing,
                                     flow_map.known_rules(profile))
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


# -- the flows of the follow-up passes ----------------------------------------

def pass_names(profile) -> list:
    """[{"name", "path" (where the profile writes its own file of it),
    "own" (the profile writes one), "starts_from" (the profile whose file
    is the farthest of the line)}] of every flow of a follow-up pass that a
    run of *profile* can start. The main flow is the page's own tab and not
    among them."""
    out = []
    for name in passflow.names(profile):
        if name == passflow.MAIN:
            continue
        written = [owner for owner, path in passflow.line(profile, name)
                   if path.is_file()]
        out.append({"name": name, "path": passflow.path_of(profile, name),
                    "own": bool(written) and written[0] == profile.name,
                    "starts_from": written[-1] if written else None})
    return out


def _pass_below(profile, name: str) -> Optional[list]:
    """The drawing of the flow *name* that *profile* would have without a
    file of its own: that of the nearest profile of its line below it that
    writes one, None where none does."""
    for _owner, path in passflow.line(profile, name)[1:]:
        if path.is_file():
            return passflow.parse(path.read_text(encoding="utf-8"), path)
    return None


def _pass_unknown(name: str, profile) -> Optional[str]:
    """Why *name* is no flow of a follow-up pass of *profile*, or None."""
    if name == passflow.MAIN or name not in passflow.names(profile):
        names = ", ".join(one["name"] for one in pass_names(profile))
        return (f"there is no flow of a follow-up pass named {name!r}; "
                f"there are {names}")
    return None


def _pass_drawn(profile, own_raw: Optional[bytes], name: str) -> list:
    if own_raw is not None:
        return passflow.parse(own_raw.decode("utf-8"), name)
    for _owner, path in passflow.line(profile, name):
        if path.is_file():
            return passflow.parse(path.read_text(encoding="utf-8"), path)
    raise LookupError(f"no profile of the line writes the flow {name!r}")


def pass_library() -> dict:
    """The library a flow of a follow-up pass is drawn with, in the form of
    the main flow's: its boxes, and the one frame a pass knows, which goes
    through the dimensions a box before it chose."""
    whole = blocks.catalogue()
    return {"boxes": whole["pass_boxes"], "each": dict(passflow.EACH),
            "each_titles": dict(passflow.EACH_TITLES), "which": {},
            "orders": {}, "order_words": {}, "arrows": whole["arrows"]}


def pass_view(profile, own_raw: Optional[bytes], name: str,
              shown: Callable) -> dict:
    """The flow *name* as the page draws it: its drawing (the profile's own
    file where it has one, else the nearest below), the boxes of the
    library a pass takes, what the run could not do with the drawing, and
    why no run starts it. *own_raw* are the bytes of the profile's own file
    of it, None where it has none."""
    said = _pass_unknown(name, profile)
    if said:
        raise LookupError(said)
    tree = _pass_drawn(profile, own_raw, name)
    return {"name": name, "file": shown(passflow.path_of(profile, name)),
            "exists": own_raw is not None,
            "base": sha256(own_raw) if own_raw is not None else None,
            "tree": tree, "inherited_tree": _pass_below(profile, name),
            "library": pass_library(),
            "problems": passflow.problems(
                tree, flow_map.known_rules(profile)),
            "not_started": passflow.startable(tree)}


def pass_judge(profile, own_raw: Optional[bytes], name: str,
               shown_name: str, tree=None) -> dict:
    """What a save of the drawing *tree* of the flow *name* would do, as
    `judge` says it for the main flow: {"ok", "errors": [{"id",
    "message"}], "file", "writes", "diff", "text"}. A drawing the run
    cannot do is refused with every reason, each at its box. A profile
    that extends another writes the file only where the drawing differs
    from what it inherits."""
    said = _pass_unknown(name, profile)
    if said:
        return {"ok": False, "errors": [{"name": None, "id": None,
                                         "message": said}],
                "file": shown_name, "writes": "unchanged", "diff": [],
                "text": None}
    old = _text(own_raw)
    drawing = _pass_drawn(profile, own_raw, name) if tree is None else tree
    errors = [{"name": None, "id": one["id"], "message": one["message"]}
              for one in passflow.problems(
                  drawing, flow_map.known_rules(profile))]
    below = _pass_below(profile, name)
    newline = CR + LF if (CR + LF).encode() in (own_raw or b"") else LF
    if errors:
        new = old
    elif below is not None and drawing == below:
        new = None
    else:
        new = passflow.dump(drawing)
    writes = ("unchanged" if new == old else "created" if old is None
              else "removed" if new is None else "changed")
    diff = [] if writes == "unchanged" else list(difflib.unified_diff(
        (old or "").splitlines(), (new or "").splitlines(), shown_name,
        shown_name, lineterm=""))
    return {"ok": not errors, "errors": errors, "file": shown_name,
            "writes": writes, "diff": diff,
            "text": None if new is None else new.replace(LF, newline)}


def pass_save(profile, own_raw: Optional[bytes], name: str,
              base: Optional[str], shown_name: str, tree=None) -> tuple:
    """(what the page is told, the bytes to write or None, whether the file
    is to be removed), as `save` for the main flow: bytes come back only for
    a drawing the run can do, and only where the file is as the page loaded
    it (*base*, the sha256 of its bytes, None where it had none)."""
    report = pass_judge(profile, own_raw, name, shown_name, tree)
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
    told = {"saved": True, "writes": report["writes"], "file": shown_name}
    if report["writes"] == "unchanged":
        return {**told, "base": base}, None, False
    if text is None:
        return {**told, "base": None}, None, True
    written = text.encode("utf-8")
    return {**told, "base": sha256(written)}, written, False
