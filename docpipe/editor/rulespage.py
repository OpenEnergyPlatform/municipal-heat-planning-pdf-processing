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
import re
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlsplit, urlunsplit

from docpipe import rules as rule_files
from docpipe import settings


ADDRESS_WITH_USER = re.compile(r"^[a-z][a-z0-9+.-]*://[^/]*@", re.I)


def masked(value):
    """What the page is sent of a value: an address keeps its host, port
    and path but not the user and password before its host, in a list or
    a map as well."""
    if isinstance(value, list):
        return [masked(one) for one in value]
    if isinstance(value, dict):
        return {key: masked(one) for key, one in value.items()}
    if isinstance(value, str) and ADDRESS_WITH_USER.match(value):
        parts = urlsplit(value)
        host = parts.hostname or ""
        if parts.port:
            host += f":{parts.port}"
        return urlunsplit(parts._replace(netloc=f"***@{host}"))
    return value


def value_shown(rule, value):
    """What the page is sent of *rule*'s value: nothing for a key
    (`secret`), else the value `masked`."""
    return None if rule.secret else masked(value)


def unmasked(value, real):
    """The value the page sends back for one it was sent `masked`: the real
    one while it is still the mask, else what the page says."""
    return real if real != value and masked(real) == value else value

CR, LF = "\r", "\n"

# What a change of a rule costs, by its tab.
COST = {
    "spec": "A change takes effect the next time a document is read. "
            "Harvests that are already written stay valid.",
    "prompts": "A change takes effect with the next request the run sends. "
               "Harvests that are already written stay valid.",
    "flow": "A change takes effect the next time a document is read. "
            "Harvests that are already written stay valid.",
    "sources": "A change takes effect the next time the sources are fetched "
               "in the Sources tab. That fetch writes the lists anew.",
    "graph": "A change takes effect the next time the graph is written "
             "from the stored harvest. No model is asked for it.",
}

# The form the page gives each kind of rule (ui/src/rules/RuleInputs.tsx);
# no kind is typed as JSON. `rows` is a table with + and -, `pair` a
# two-column table, `bounds` two number fields.
FORMS = {"whole": "number", "number": "number", "switch": "checkbox",
         "choice": "select", "text": "line", "chars": "line",
         "texts": "lines", "map": "pairs", "table": "rows",
         "range": "bounds"}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _own_names(profile) -> set:
    """The rules *profile* declares itself, which its own file names."""
    return {one.name for owner, own, _beside in rule_files.declared(profile)
            if owner == profile.name for one in own}


def view(profile, tab: str, own_raw: Optional[bytes], shown,
         own_at: Optional[dict] = None) -> dict:
    """The rules of *tab* of *profile* as the page shows them. *own_at* is
    {rule: [{"id", "kind"} of the steps of the saved flow that give it a
    value of their own]}; a key's value is never sent."""
    known = rule_files.registry(profile)
    taken = rule_files.load(profile)
    files = rule_files.load(profile, environ={})
    below = rule_files.inherited(profile)
    mine = _own_names(profile)
    out = []
    for one in rule_files.of_tab(tab, profile):
        name = one.name
        owner = files.owners.get(name, "")
        hidden = one.secret
        out.append({
            "name": name, "group": one.group, "kind": one.kind,
            "help": one.help, "least": one.least, "most": one.most,
            "choices": list(one.choices), "columns": list(one.columns),
            "of": one.of, "empty": one.empty, "decided": one.decided,
            "where": one.where, "setting": one.env,
            "value": value_shown(one, files.values[name]),
            "steps": list(one.steps), "machine": one.machine,
            "secret": hidden,
            "own_at": (own_at or {}).get(name, []),
            "inherited": (value_shown(one, below.values.get(name))
                          if below is not None
                          and name not in mine and not hidden else None),
            "has_inherited": below is not None and name not in mine
            and name in below.values,
            "owner": owner, "own": owner == f"{rule_files.FILE} of "
                                            f"{profile.name}",
            # the profile whose file sets it, for "set in profile ..."
            "set_in": owner.rpartition(" of ")[2] or None,
            "declared_here": name in mine,
            "in_effect": value_shown(one, taken.values[name]),
            "origin": taken.owners.get(name, owner)})
    return {"tab": tab, "file": shown(rule_files.path_of(profile)),
            "exists": own_raw is not None,
            "base": sha256(own_raw) if own_raw is not None else None,
            "whole": below is None, "rules": out, "forms": FORMS,
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
        value = unmasked(value, files.values.get(key))
        said = rule_files.problem(key, value, known)
        if said is None and key in known and known[key].secret:
            said = (f"{key} is a key: it is set in .env or in the "
                    f"environment, never on this page")
        elif said is None and key in known and known[key].machine \
                and value != files.values[key]:
            said = (f"{key} is a value of this machine: it is set in the "
                    f"project file docpipe.toml (the Run section of the "
                    f"Flow tab), never in the rules file of the repository")
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


# -- the values of the machine, in the project file ---------------------------

def machine_rows(profile) -> list:
    """The rules that are values of this machine, each with its value, where
    it comes from and the key of the project file it is written under. A key
    (`secret`) is left out: it is never shown and never written here."""
    taken = rule_files.load(profile)
    files = rule_files.load(profile, environ={})
    out = []
    for one in rule_files.registry(profile).values():
        if not one.machine or one.secret:
            continue
        setting = settings.BY_ENV.get(one.env) if one.env else None
        out.append({
            "name": one.name, "tab": one.tab, "group": one.group,
            "kind": one.kind, "help": one.help, "least": one.least,
            "most": one.most, "choices": list(one.choices),
            "columns": list(one.columns), "of": one.of,
            "empty": one.empty, "decided": one.decided,
            "setting": one.env, "key": setting.key if setting else None,
            "value": value_shown(one, files.values[one.name]),
            "in_effect": value_shown(one, taken.values[one.name]),
            "origin": taken.owners.get(one.name, "")})
    return out


def project_state(path, shown: Callable) -> dict:
    """What the page is told of the project file: where it is, whether it
    exists, and why a value may not be written there (None where it may)."""
    path = Path(path)
    return {"file": shown(path), "exists": path.is_file(),
            "refused": settings.git_refusal(path)}


def machine_save(profile, values, path, shown: Callable) -> dict:
    """Write {rule: value} of the machine's rules into the project file
    *path* (never a rule that is no value of the machine, never a key; never
    a file git would commit). What the page is told: {"saved", "reason",
    "errors", "message", "file", "writes", "changed"}."""
    known = rule_files.registry(profile)
    errors = []
    if not isinstance(values, dict):
        errors.append({"name": None, "message": "values must be an object, "
                       "the name of a rule -> its value"})
        values = {}
    keyed = {}
    in_effect = rule_files.load(profile).values
    for name, value in values.items():
        one = known.get(name)
        value = unmasked(value, in_effect.get(name))
        said = rule_files.problem(name, value, known)
        if one is not None and one.secret:
            said = (f"{name} is a key: it is set in .env or in the "
                    f"environment, never on this page")
        elif said is None and not one.machine:
            said = (f"{name} is not a value of this machine: it is set in "
                    f"the rules file or at a step")
        elif said is None:
            setting = settings.BY_ENV.get(one.env) if one.env else None
            if setting is None or setting.secret or setting.bootstrap:
                said = (f"{name} has no key in the project file: set it "
                        f"at the start")
            elif one.kind not in ("switch", "whole", "number", "text",
                                  "chars", "texts"):
                said = f"{name} cannot be written to the project file"
            else:
                keyed[setting.key] = value
        if said is not None:
            errors.append({"name": name if one is not None else None,
                           "message": said})
    if errors:
        return {"saved": False, "reason": "invalid", "errors": errors,
                "message": "; ".join(e["message"] for e in errors)}
    path = Path(path)
    refused = settings.git_refusal(path)
    if refused:
        return {"saved": False, "reason": "git", "message": refused}
    try:
        writes = settings.write_project(path, keyed)
    except settings.ConfigError as exc:
        return {"saved": False, "reason": "invalid",
                "message": str(exc)}
    return {"saved": True, "file": shown(path), "writes": writes,
            "changed": [{"name": name, "to": value}
                        for name, value in values.items()]}
