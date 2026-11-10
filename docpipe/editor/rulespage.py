"""
rulespage.py: The rules of a profile as `docpipe edit` shows and sets them,
each in the tab it belongs to.

The rules themselves are the run's (`docpipe.rules`): their files, their
strict loader, what each is and where the code applies it. A tab shows the
rules of its kind (spec, prompts, flow, sources, graph) in their groups, each
with its value, the value it has where the profile says nothing (the
inherited one), who says it, the dates of the owner's decisions, and the
setting that wins over it where one is set. Saving writes the profile's own
rules.json with the rules it sets differently from what it inherits, and
every rule it declares itself (that file is where those start from); a file
with no rule left is removed. Nothing a rule says makes a harvest stale.

Author: Felix Vossel
"""
from __future__ import annotations

import difflib
import hashlib
import os
from typing import Optional

from docpipe import rules as rule_files

CR, LF = "\r", "\n"

# What a change of a rule costs, by its tab.
COST = {
    "spec": "A rule of what backs a value takes effect the next time a "
            "document is read; no harvest goes stale, the stamp names the "
            "rules and nothing compares them.",
    "prompts": "A rule of what a request shows takes effect with the next "
               "request; no harvest goes stale.",
    "flow": "A rule of the flow takes effect the next time a document is "
            "read; no harvest goes stale.",
    "sources": "A rule of the sources takes effect at the next fetch of the "
               "sources (the Sources tab), which writes the lists anew.",
    "graph": "A rule of the graph takes effect the next time the graph is "
             "written from the stored harvest; no model is asked.",
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _own_names(profile) -> set:
    """The rules *profile* declares itself, which its own file names."""
    return {one.name for owner, own, _beside in rule_files.declared(profile)
            if owner == profile.name for one in own}


def view(profile, tab: str, own_raw: Optional[bytes], shown) -> dict:
    """The rules of *tab* of *profile* as the page shows them."""
    known = rule_files.registry(profile)
    taken = rule_files.load(profile)
    files = rule_files.load(profile, environ={})
    below = rule_files.inherited(profile)
    mine = _own_names(profile)
    out = []
    for one in rule_files.of_tab(tab, profile):
        name = one.name
        owner = files.owners.get(name, "")
        out.append({
            "name": name, "group": one.group, "kind": one.kind,
            "help": one.help, "least": one.least, "most": one.most,
            "choices": list(one.choices), "columns": list(one.columns),
            "of": one.of, "empty": one.empty, "decided": one.decided,
            "where": one.where, "setting": one.env,
            "value": files.values[name],
            "inherited": (below.values.get(name) if below is not None
                          and name not in mine else None),
            "has_inherited": below is not None and name not in mine
            and name in below.values,
            "owner": owner, "own": owner == f"{rule_files.FILE} of "
                                            f"{profile.name}",
            "declared_here": name in mine,
            "in_effect": taken.values[name],
            "origin": taken.owners.get(name, owner)})
    return {"tab": tab, "file": shown(rule_files.path_of(profile)),
            "exists": own_raw is not None,
            "base": sha256(own_raw) if own_raw is not None else None,
            "whole": below is None, "rules": out,
            "cost": COST.get(tab, ""), "known": len(known)}


def _text(raw: Optional[bytes]) -> Optional[str]:
    return None if raw is None else raw.decode("utf-8").replace(CR + LF, LF)


def judge(profile, own_raw: Optional[bytes], values, name: str) -> dict:
    """What a save of *values* ({rule: value}; those not named stay as the
    files say them) would do: {"ok", "errors": [{"name", "message"}],
    "changed": [{"name", "from", "to"}], "file", "writes", "diff", "says",
    "text"}."""
    known = rule_files.registry(profile)
    files = rule_files.load(profile, environ={})
    below = rule_files.inherited(profile)
    mine = _own_names(profile)
    errors = []
    now = dict(files.values)
    if not isinstance(values, dict):
        errors.append({"name": None, "message": "values must be an object, "
                                                "the name of a rule -> its "
                                                "value"})
        values = {}
    for key, value in values.items():
        said = rule_files.problem(key, value, known)
        if said is not None:
            errors.append({"name": key if key in known else None,
                           "message": said})
        else:
            now[key] = value
    old = _text(own_raw)
    newline = CR + LF if (CR + LF).encode() in (own_raw or b"") else LF
    if below is None:
        own = {key: now[key] for key in known}
    else:
        own = {key: now[key] for key in known
               if key in mine or key not in below.values
               or now[key] != below.values[key]}
    new = rule_files.dump(own, known=known) if own else None
    if errors:
        new = old
    writes = ("unchanged" if new == old else "created" if old is None
              else "removed" if new is None else "changed")
    diff = [] if writes == "unchanged" else list(difflib.unified_diff(
        (old or "").splitlines(), (new or "").splitlines(), name, name,
        lineterm=""))
    changed = [{"name": key, "from": files.values.get(key), "to": now[key]}
               for key in known if now.get(key) != files.values.get(key)]
    tabs = sorted({known[row["name"]].tab for row in changed})
    says = [COST[tab] for tab in tabs if tab in COST]
    for row in changed:
        one = known[row["name"]]
        if one.env and one.env in os.environ:
            says.append(f"{one.env} is set here ({os.environ[one.env]}) and "
                        f"wins over the file for a run started here.")
    return {"ok": not errors, "errors": errors, "changed": changed,
            "file": name, "writes": writes, "diff": diff, "says": says,
            "text": None if new is None else new.replace(LF, newline)}


def save(profile, own_raw: Optional[bytes], values, base: Optional[str],
         name: str) -> tuple:
    """(what the page is told, the bytes to write or None, whether the file
    is to be removed); bytes only for values the rules take and where the
    file is as the page loaded it (*base*)."""
    report = judge(profile, own_raw, values, name)
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
    told = {"saved": True, "writes": report["writes"], "file": name,
            "changed": report["changed"]}
    if report["writes"] == "unchanged":
        return {**told, "base": base}, None, False
    if text is None:
        return {**told, "base": None}, None, True
    written = text.encode("utf-8")
    return {**told, "base": sha256(written)}, written, False
