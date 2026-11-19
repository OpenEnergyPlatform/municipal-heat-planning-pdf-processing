"""
flowparts.py: Steps drawn once and used by several frames, and a profile's
drawing as what it changes in the drawing it inherits (owner request
2026-11-19, point C2 of the review of that day).

The steps for one value stood twice in every flow file, once in the frame of
the fields a document has once and once in that of the values of its pieces,
and every profile held the whole drawing: a change to them was made six times
by hand, and a change to the default's drawing reached no profile. Now:

- A drawing names steps once, a part (`"parts": {name: [steps]}`), and a
  frame uses them where it stands: "part" (and "prefix") in place of
  "steps". Drawn (`expand`), the frame's steps are the part's, every id in
  them prefixed with the prefix, so that the frames that use one part have
  ids of their own. What a frame goes through, its order and its rules stay
  the frame's: the default uses the steps for one value in the frame of the
  fields a document has once (order "document", prefix "document_") and in
  that of the values of its pieces (order "names_first", no prefix), with
  the ids they always had.
- A profile that extends another writes what it changes in the drawing it
  inherits ("changes", `apply`): a step set to other settings, inserted,
  moved or removed, named by its id, in the drawing or, with "part", in a
  part, where it changes every frame that uses it; a part of its own is
  defined.
- The page edits the drawn drawing. Saved, it is folded back (`fold`): each
  frame that used a part uses it again, and the steps it shows, their ids
  without its prefix, are the part; a part changed in one frame is changed
  in all; changed differently in two is refused. A profile's file then holds
  the changes from the drawing it inherits (`as_changes`), checked by
  applying them; where they do not give the drawing, the whole drawing.

The run reads the drawn drawing (`flow.Flow.tree`) and nothing of this.

Author: Felix Vossel
"""
from __future__ import annotations

import copy
from typing import Optional

PART = "part"
PREFIX = "prefix"
FRAMES = ("each", "round")


class PartError(ValueError):
    """A part that is not named, a change that names no step, a part
    changed differently in two frames."""


# -- the nodes of a drawing ----------------------------------------------------

def kind(node: dict) -> str:
    for key in ("box", "each", "round", "if"):
        if key in node:
            return key
    return ""


def is_use(node) -> bool:
    """Is *node* a frame that uses a part?"""
    return isinstance(node, dict) and PART in node


def lists_of(node: dict) -> list:
    """[(way, steps)] of a node: "steps" of a frame, each way of an "if"
    by its number, "else"; [] for a box and a frame that uses a part."""
    if not isinstance(node, dict) or is_use(node):
        return []
    out = []
    if isinstance(node.get("steps"), list):
        out.append(("steps", node["steps"]))
    if isinstance(node.get("if"), list):
        for i, way in enumerate(node["if"]):
            if isinstance(way, dict) and isinstance(way.get("steps"), list):
                out.append((i, way["steps"]))
    if isinstance(node.get("else"), list):
        out.append(("else", node["else"]))
    return out


def places(steps: list, parent=None, way=None):
    """(node, the list it stands in, its index, its frame's id, the way of
    the frame) of every node of *steps*, in reading order."""
    for at, node in enumerate(steps):
        if not isinstance(node, dict):
            continue
        yield node, steps, at, parent, way
        for inner_way, inner in lists_of(node):
            yield from places(inner, node.get("id"), inner_way)


def _where(steps: list) -> dict:
    """{id: (list, index, frame id, way)} of every node of *steps*."""
    return {node.get("id"): (items, at, parent, way)
            for node, items, at, parent, way in places(steps)}


def own(node: dict) -> dict:
    """What a step says of itself, the steps in it left out: its settings,
    the conditions of an "if"'s ways, whether it has an "else"."""
    out: dict = {}
    for key, value in node.items():
        if key == "steps":
            continue
        if key == "else":
            out["else"] = []
        elif key == "if" and isinstance(value, list):
            out["if"] = [{k: v for k, v in way.items() if k != "steps"}
                         if isinstance(way, dict) else way for way in value]
        else:
            out[key] = value
    return copy.deepcopy(out)


def with_steps(said: dict, old: Optional[dict] = None) -> dict:
    """The step *said* (as `own` says one) with the steps of *old* in it,
    way by way, or none where *old* is None or has no such way."""
    new = copy.deepcopy(said)
    old = old or {}
    if kind(new) in FRAMES and not is_use(new):
        new["steps"] = old["steps"] if isinstance(old.get("steps"), list) \
            else []
    if isinstance(new.get("if"), list):
        ways = [way.get("steps") or [] if isinstance(way, dict) else []
                for way in old.get("if") or []] \
            if isinstance(old.get("if"), list) else []
        new["if"] = [dict(way, steps=ways[i] if i < len(ways) else [])
                     if isinstance(way, dict) else way
                     for i, way in enumerate(new["if"])]
    if "else" in new:
        new["else"] = old["else"] if isinstance(old.get("else"), list) \
            else []
    return new


def with_prefix(node: dict, prefix: str) -> dict:
    """A copy of *node* whose id and every id in it start with *prefix*."""
    out = copy.deepcopy(node)
    if prefix:
        for one, *_ in places([out]):
            if one.get("id") is not None:
                one["id"] = prefix + str(one["id"])
    return out


def without_prefix(node: dict, prefix: str) -> dict:
    """A copy of *node* whose ids lose *prefix* where they start with it."""
    out = copy.deepcopy(node)
    if prefix:
        for one, *_ in places([out]):
            ident = one.get("id")
            if isinstance(ident, str) and ident.startswith(prefix):
                one["id"] = ident[len(prefix):]
    return out


def uses(tree: list) -> list:
    """The frames of *tree* that use a part, in reading order."""
    return [node for node, *_ in places(tree) if is_use(node)]


# -- drawing the parts where they are used --------------------------------------

def _drawn(node: dict, steps: list) -> dict:
    """The frame *node* with *steps* where it names its part."""
    out = {}
    for key, value in node.items():
        if key == PART:
            out["steps"] = steps
        elif key != PREFIX:
            out[key] = copy.deepcopy(value)
    return out


def expand(tree: list, parts: Optional[dict], where: str = "flow") -> list:
    """*tree* with the steps of every part drawn in each frame that uses it,
    every id in them prefixed with the frame's prefix. A part uses no part.
    PartError where a frame uses one the drawing does not name."""
    parts = parts or {}

    def go(steps: list) -> list:
        out = []
        for node in steps:
            if not isinstance(node, dict):
                out.append(copy.deepcopy(node))
                continue
            ident = node.get("id")
            if is_use(node):
                name, prefix = node[PART], node.get(PREFIX, "")
                if kind(node) not in FRAMES:
                    raise PartError(f"{where}: {ident}: only a frame of "
                                    f"each or round uses a part")
                if "steps" in node:
                    raise PartError(f"{where}: {ident}: uses the part "
                                    f"{name!r} and draws steps of its own; "
                                    f"a frame that uses a part draws none")
                if not isinstance(prefix, str):
                    raise PartError(f"{where}: {ident}: the prefix is a "
                                    f"text")
                if name not in parts:
                    named = ", ".join(sorted(parts)) or "no part"
                    raise PartError(f"{where}: {ident}: uses the part "
                                    f"{name!r}, which the drawing does not "
                                    f"name (it names {named})")
                if uses(parts[name]):
                    raise PartError(f"{where}: the part {name!r} uses a "
                                    f"part; a part uses none")
                out.append(_drawn(node, [with_prefix(one, prefix)
                                         for one in parts[name]]))
                continue
            copied = {}
            for key, value in node.items():
                if key in ("steps", "else") and isinstance(value, list):
                    copied[key] = go(value)
                elif key == "if" and isinstance(value, list):
                    copied[key] = [dict(way, steps=go(way.get("steps") or []))
                                   if isinstance(way, dict)
                                   and isinstance(way.get("steps"), list)
                                   else copy.deepcopy(way) for way in value]
                else:
                    copied[key] = copy.deepcopy(value)
            out.append(copied)
        return out
    return go(tree)


def checked_parts(parts, where: str = "flow") -> dict:
    """*parts* as a file writes them: {name: [steps]}; PartError if not."""
    if parts is None:
        return {}
    if not isinstance(parts, dict) or not all(
            isinstance(steps, list) for steps in parts.values()):
        raise PartError(f"{where}: parts must be an object, the name of a "
                        f"part -> its steps")
    return parts


# -- folding a drawn drawing back -------------------------------------------------

def fold(drawn: list, top: list, parts: Optional[dict]) -> tuple:
    """(drawing, parts) of the drawn drawing *drawn*, in which the frames of
    *top* that use a part were drawn: each of them, found by its id, uses
    its part again, its settings as *drawn* shows them; the steps it shows,
    their ids without its prefix, are the part. A part changed in one frame
    is changed in all; changed differently in two is PartError. A frame
    whose id the edit changed or that it removed no longer uses its part,
    and a part no frame uses is left out."""
    parts = copy.deepcopy(parts or {})
    tree = copy.deepcopy(drawn)
    at = _where(tree)
    shown: dict = {}
    for use in uses(top):
        hit = at.get(use.get("id"))
        if hit is None:
            continue
        items, index, _frame, _way = hit
        node = items[index]
        if kind(node) not in FRAMES or not isinstance(node.get("steps"), list):
            continue
        prefix = use.get(PREFIX, "")
        shown.setdefault(use[PART], []).append(
            (use.get("id"), [without_prefix(one, prefix)
                             for one in node["steps"]]))
        folded = {}
        for key, value in node.items():
            if key == "steps":
                folded[PART] = use[PART]
                if prefix:
                    folded[PREFIX] = prefix
            else:
                folded[key] = value
        items[index] = folded
    for name, found in shown.items():
        changed: list = []
        for _ident, steps in found:
            if steps != parts.get(name) and steps not in changed:
                changed.append(steps)
        if len(changed) > 1:
            frames = ", ".join(str(ident) for ident, _ in found)
            raise PartError(
                f"the steps of the part {name!r} stand in {frames}, and two "
                f"of them were changed differently; a change there is a "
                f"change of every frame that uses them, so change them in "
                f"one of them and save")
        if changed:
            parts[name] = changed[0]
    used = {node[PART] for node in uses(tree)}
    return tree, {name: steps for name, steps in parts.items()
                  if name in used}


# -- a drawing as changes to another ------------------------------------------------

def _found(steps: list, ident, what: str) -> tuple:
    hit = _where(steps).get(ident)
    if hit is None:
        raise PartError(f"a change says {what} {ident!r}, and there is no "
                        f"step of that id")
    return hit


def _place(steps: list, change: dict, node: dict) -> None:
    """Put *node* where *change* says: right after a step ("after"), or
    first in a frame's steps ("into" its id; "way" the number of a way of
    an "if", or "else"), or first of all ("into" null)."""
    if "after" in change:
        items, at, _f, _w = _found(steps, change["after"], "after")
        items.insert(at + 1, node)
        return
    if change.get("into") is None:
        steps.insert(0, node)
        return
    items, at, _f, _w = _found(steps, change["into"], "into")
    frame = items[at]
    way = change.get("way", "steps")
    if isinstance(way, int):
        ways = frame.get("if") if isinstance(frame.get("if"), list) else []
        if not 0 <= way < len(ways) or not isinstance(ways[way], dict):
            raise PartError(f"a change puts {node.get('id')!r} into way "
                            f"{way} of {change['into']!r}, which has none")
        inner = ways[way].setdefault("steps", [])
    elif way in ("steps", "else") and not is_use(frame):
        inner = frame.setdefault(way, [])
    else:
        raise PartError(f"a change puts {node.get('id')!r} into "
                        f"{change['into']!r}, which has no {way}")
    inner.insert(0, node)


def _apply_one(steps: list, change: dict) -> None:
    """Make one change in the list *steps*."""
    if "remove" in change:
        items, at, _f, _w = _found(steps, change["remove"], "remove")
        del items[at]
    elif "set" in change:
        items, at, _f, _w = _found(steps, change["set"], "set")
        if not isinstance(change.get("to"), dict):
            raise PartError(f"a change sets {change['set']!r} to no step")
        items[at] = with_steps(change["to"], items[at])
    elif "insert" in change:
        if not isinstance(change["insert"], dict):
            raise PartError("a change inserts no step")
        _place(steps, change, copy.deepcopy(change["insert"]))
    elif "move" in change:
        items, at, _f, _w = _found(steps, change["move"], "move")
        node = items.pop(at)
        _place(steps, change, node)
    else:
        raise PartError(f"a change says none of define, set, insert, move, "
                        f"remove: {sorted(change)}")


def apply(top: list, parts: Optional[dict], changes) -> tuple:
    """(drawing, parts) with *changes* made, in their order (see the
    module's head); PartError where one names a step or part that is not
    there."""
    top, parts = copy.deepcopy(top), copy.deepcopy(parts or {})
    if not isinstance(changes, list):
        raise PartError("changes is a list")
    for change in changes:
        if not isinstance(change, dict):
            raise PartError("a change is an object")
        if "define" in change:
            if not isinstance(change.get("steps"), list):
                raise PartError(f"a change defines the part "
                                f"{change['define']!r} with no steps")
            parts[change["define"]] = copy.deepcopy(change["steps"])
            continue
        name = change.get(PART)
        if name is not None and name not in parts:
            raise PartError(f"a change names the part {name!r}, which the "
                            f"drawing does not name")
        _apply_one(top if name is None else parts[name], change)
    return top, parts


def _location(steps: list, ident, keep: Optional[set] = None) -> dict:
    """Where the step *ident* stands in *steps*, as a change says it; with
    *keep*, the steps before it that are not in *keep* not counted."""
    items, at, frame, way = _where(steps)[ident]
    before = next((one.get("id") for one in reversed(items[:at])
                   if isinstance(one, dict)
                   and (keep is None or one.get("id") in keep)), None)
    if before is not None:
        return {"after": before}
    if frame is None:
        return {"into": None}
    return {"into": frame} if way == "steps" else {"into": frame, "way": way}


def _changes(base: list, target: list, part: Optional[str] = None) -> list:
    """The changes that make the steps *base* the steps *target*: settings
    first, then what is inserted and moved in the target's reading order,
    then what is removed."""
    tag = {PART: part} if part is not None else {}
    was, now = _where(base), _where(target)
    work = copy.deepcopy(base)
    out: list = []

    def do(change: dict) -> None:
        out.append(change)
        _apply_one(work, {k: v for k, v in change.items() if k != PART})

    for ident, (items, at, _f, _w) in now.items():
        if ident in was:
            old = was[ident][0][was[ident][1]]
            if own(old) != own(items[at]):
                do({"set": ident, "to": own(items[at]), **tag})
    whole: set = set()
    keep = set(now)
    for node, _items, _at, frame, _way in places(target):
        ident = node.get("id")
        if frame in whole:
            whole.add(ident)
            continue
        want = _location(target, ident)
        if ident not in _where(work):
            inner = {one.get("id") for one, *_ in places([node])}
            if inner & set(was):
                do({"insert": with_steps(own(node)), **want, **tag})
            else:
                whole |= inner
                do({"insert": copy.deepcopy(node), **want, **tag})
        elif _location(work, ident, keep) != want:
            do({"move": ident, **want, **tag})
    for ident, (_items, _at, frame, _way) in was.items():
        if ident not in now and (frame is None or frame in now):
            do({"remove": ident, **tag})
    return out


def diff(base_top: list, base_parts: Optional[dict], top: list,
         parts: Optional[dict]) -> list:
    """The changes that make the drawing (*base_top*, *base_parts*) the
    drawing (*top*, *parts*): a part the base does not name is defined, each
    part it names is changed, then the drawing."""
    base_parts, parts = base_parts or {}, parts or {}
    out: list = []
    for name, steps in parts.items():
        if name not in base_parts:
            out.append({"define": name, "steps": copy.deepcopy(steps)})
        elif base_parts[name] != steps:
            out += _changes(base_parts[name], steps, name)
    return out + _changes(base_top, top)


def as_changes(base_top: list, base_parts: Optional[dict], top: list,
               parts: Optional[dict]) -> Optional[list]:
    """`diff`, where making it in the base gives the drawing and every part
    it uses exactly; else None (the file then holds the whole drawing)."""
    try:
        changes = diff(base_top, base_parts, top, parts)
        got_top, got_parts = apply(base_top, base_parts, changes)
    except (PartError, KeyError, IndexError, TypeError, AttributeError):
        return None
    used = {node[PART] for node in uses(top)}
    if got_top != top or any(got_parts.get(name) != (parts or {}).get(name)
                             for name in used):
        return None
    return changes
