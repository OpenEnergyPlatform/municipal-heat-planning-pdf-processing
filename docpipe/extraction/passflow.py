"""
passflow.py: The follow-up passes as flows of their own (owner decision
2026-11-11).

A follow-up pass reads a harvest that is already written: it reads the
questions that moved again, the dimensions that stayed open, the parameters
the spec gained, the lists a grown vocabulary moves, the quotes, the rows
nobody can stand behind. Each is a file `flows/<name>.json` of boxes, shipped
with the default profile and overridden by a profile's own file of the same
name, as the main flow is (`flow.line`). The call switch of a pass only
chooses its flow, and `--flow NAME` starts any flow by name.

A flow of a pass is a list of boxes (`blocks.LIBRARY`, those that say
`flow == "pass"`) and, around the boxes that read one dimension, frames "each
dimension". Its boxes run in the order the file gives. What a box leaves for
the next is held for one harvest file or document (`passboxes.Doc`), so a
box says in the library which boxes stand before it. A box that starts the
chain (the stored harvest, the classification of a new parameter, the
unread passages, the main flow) takes the documents; the boxes after it run
for each document, in order; a box that runs once (the working list, the
clearing of the stamps) runs after them. A box that is off does not run, and
the values a box or frame sets for itself hold inside it and nowhere else
(`rules.STEP`).

What the file may say is checked before a run starts (`problems`), each
reason a sentence at its box.

Author: Felix Vossel
"""
from __future__ import annotations

import json
import logging
import threading
import time
from collections import Counter
from pathlib import Path
from typing import Callable, Optional

from .. import rules
from . import blocks
from . import flow as flow_map

log = logging.getLogger(__name__)

MAIN = "main"
FOLDER = "flows"
KEYS = ("flow",)
BOX_KEYS = ("id", "box", "preset", "set", "rules", "off", "note")
FRAME_KEYS = ("id", "each", "rules", "steps", "off", "note")
# What a frame of a pass goes through: the dimensions a box before it chose.
FRAMES = ("dimension",)
# ... what it does, and its name on the page
EACH = {"dimension": "The steps inside run once for each dimension that "
                     "the step before chose: the questions that may be "
                     "read again or the open dimensions, in the order that "
                     "step gives them. To change it: switch the loop off, "
                     "or choose in the step before which dimensions it "
                     "takes."}
EACH_TITLES = {"dimension": "For each dimension"}


class PassError(RuntimeError):
    """A pass that cannot start or go on; the run says why and stops."""


# -- where the files are ------------------------------------------------------

def line(profile, name: str) -> list:
    """[(profile name, path)] of the files the flow *name* can stand in,
    nearest first: the profile's own `flows/<name>.json`, then those of the
    profiles it extends, the default profile's last."""
    return [(owner, Path(path).parent / FOLDER / f"{name}.json")
            for owner, path in flow_map.line(profile)]


def path_of(profile, name: str) -> Path:
    """Where *profile* writes its own file of the flow *name*."""
    return Path(profile.package_dir) / FOLDER / f"{name}.json"


def names(profile=None) -> list:
    """The flows a run of *profile* can start: the main flow, and each
    follow-up pass of the default profile or the profile's line."""
    found = set()
    for _owner, path in flow_map.line(profile):
        folder = Path(path).parent / FOLDER
        if folder.is_dir():
            found |= {one.stem for one in folder.glob("*.json")}
    return [MAIN] + sorted(found)


def parse(raw: str, where) -> list:
    """The drawing of the text *raw*, read strictly: one JSON object with
    "flow", the list of boxes. *where* names the file in what is said."""
    def once(pairs: list) -> dict:
        out: dict = {}
        for key, value in pairs:
            if key in out:
                raise flow_map.FlowError(f"{where}: {key!r} stands twice")
            out[key] = value
        return out

    try:
        data = json.loads(raw, object_pairs_hook=once)
    except flow_map.FlowError:
        raise
    except ValueError as exc:
        raise flow_map.FlowError(f"{where}: {exc}") from exc
    if not isinstance(data, dict) or set(data) != set(KEYS):
        raise flow_map.FlowError(
            f"{where}: a flow of a pass is one JSON object with \"flow\", "
            f"the list of its boxes")
    return data["flow"]


def dump(tree: list) -> str:
    """A pass flow's text in the one form it is written in."""
    return json.dumps({"flow": tree}, ensure_ascii=False, indent=2) + "\n"


def load(name: str, profile=None) -> list:
    """The drawing of the pass *name* as the nearest file of *profile*'s
    line says it, refused with every reason where the run could not do
    it. LookupError where no profile of the line writes the flow."""
    for _owner, path in line(profile, name):
        if not path.is_file():
            continue
        tree = parse(path.read_text(encoding="utf-8"), path)
        said = problems(tree, flow_map.known_rules(profile)
                        if profile is not None else None)
        if said:
            first = said[0]
            raise flow_map.FlowError(
                f"{path}: " + (f"{first['id']}: " if first["id"] else "")
                + first["message"])
        return tree
    raise LookupError(f"no profile of the line of "
                      f"{getattr(profile, 'name', 'default')!r} writes the "
                      f"flow {name!r}")


def tree_of(name: str, profile=None) -> list:
    """The same, for a caller that has no use for the difference."""
    return load(name, profile)


# -- what a drawing may say ---------------------------------------------------

def _on(node: dict) -> bool:
    return not node.get("off")


def _setting_problem(kind: blocks.Box, node: dict, check) -> None:
    given = node.get("set") or {}
    if not isinstance(given, dict):
        check.say(node, "set is an object: setting -> value")
        return
    by_key = {s.key: s for s in kind.settings}
    for key, value in given.items():
        setting = by_key.get(key)
        if setting is None:
            check.say(node, f"{kind.label} has no setting {key!r}"
                      f"{flow_map._nearest(key, by_key)}")
            continue
        said = flow_map._value_problem(kind, setting, value, set())
        if said:
            check.say(node, said)


def problems(tree, known: Optional[dict] = None) -> list:
    """Everything the run could not do with the drawing *tree* of a pass:
    [{"id": the box or frame or None, "message"}], [] where it can run."""
    if known is None:
        from ..profile import active_profile
        known = rules.registry(active_profile())
    check = flow_map._Check(known)
    if not isinstance(tree, list) or not tree:
        return [{"id": None, "message": "the flow of a pass is a list of "
                 "boxes, not empty"}]
    seen_on: list = []              # the boxes on, before this one
    chain: Optional[list] = None    # the boxes on of the running chain
    for node in tree:
        if not isinstance(node, dict):
            check.say({}, f"a step is an object, not {node!r}")
            continue
        _identify(check, node)
        kind = flow_map.kind_of(node)
        if kind == "each":
            _frame(check, node, chain, seen_on)
            continue
        if kind != "box":
            check.say(node, "a step of a pass is a box or an each frame")
            continue
        box = _box(check, node)
        if box is None:
            continue
        if not _on(node):
            if box.scope in ("files", "documents"):
                chain = None
            continue
        if box.scope in ("files", "documents"):
            chain = []
        elif box.scope == "chain":
            if chain is None:
                check.say(node, f"{box.label} runs for each document, so "
                          f"it stands after the step that takes the "
                          f"documents (the stored harvest, the new "
                          f"parameter, the unread passages, or the "
                          f"documents), and that step is on")
                continue
        else:
            chain = None
        _after(check, node, box, chain if box.scope == "chain" else seen_on)
        if box.inside:
            check.say(node, f"{box.label} stands in an each "
                      f"{box.inside} frame, where the dimensions are "
                      f"read one after the other")
        if box.scope == "chain":
            _how(check, node, box, chain)
        seen_on.append(rules.step_kind(node))
        if chain is not None:
            chain.append(rules.step_kind(node))
    return check.out


def _identify(check, node: dict) -> None:
    ident = node.get("id")
    if not isinstance(ident, str) or not ident.strip():
        check.say(node, "every box and frame needs an id")
    elif ident in check.ids:
        check.say(node, f"the id {ident} stands twice")
    else:
        check.ids[ident] = node


def _box(check, node: dict):
    """The library entry of a box of a pass, or None with the reason said."""
    box = blocks.LIBRARY.get(node.get("box"))
    if box is None:
        check.say(node, f"there is no box {node.get('box')!r}"
                  f"{flow_map._nearest(node.get('box'), blocks.LIBRARY)}")
        return None
    if "preset" in node:
        if node.get("box") != "ask":
            check.say(node, "only a step of \"Ask the model\" has a preset")
            return None
        if blocks.preset_of(node) is None:
            from .presets import PRESETS
            check.say(node, f"there is no preset {node.get('preset')!r}"
                      f"{flow_map._nearest(node.get('preset'), PRESETS)}")
            return None
    box = blocks.box_of(node)
    if box.flow != "pass":
        check.say(node, f"{box.label} is a box of the main flow: a pass "
                  f"reads a harvest that is written, and has no use for "
                  f"the steps that write one")
        return None
    for key in node:
        if key not in BOX_KEYS:
            check.say(node, f"a box has no key {key!r}")
    flow_map._rules_of(check, node)
    _setting_problem(box, node, check)
    if "off" in node and not isinstance(node["off"], bool):
        check.say(node, "off is yes or no")
    return box


def _after(check, node: dict, box: blocks.Box, before: list) -> None:
    if box.after and not any(kind in before for kind in box.after):
        wanted = " or ".join(blocks.label_of(kind) for kind in box.after)
        check.say(node, f"{box.label} works on what {wanted} gives, so "
                  f"{wanted} stands before it, and is on")


def _how(check, node: dict, box: blocks.Box, chain: list) -> None:
    """What a box of the chain needs that depends on its setting."""
    if box.type != "replace":
        return
    how = (node.get("set") or {}).get("how", "replace")
    if how == "replace" and "summary" not in chain:
        check.say(node, "a harvest file that is replaced is written from "
                  "its lines and a summary, so the step Summary stands "
                  "before it")
    if how == "append" and not {"read_parameters", "unread"} & set(chain):
        check.say(node, "rows are appended after what was read, so the "
                  "step that reads the new parameters or the unread "
                  "passages stands before it")


def _frame(check, node: dict, chain: Optional[list], seen_on: list) -> None:
    for key in node:
        if key not in FRAME_KEYS:
            check.say(node, f"a frame has no key {key!r}")
    flow_map._rules_of(check, node)
    if node.get("each") not in FRAMES:
        check.say(node, f"each {node.get('each')!r} is nothing a pass goes "
                  f"through; it goes through {', '.join(FRAMES)}")
        return
    if chain is None or not {"movable", "open"} & set(chain):
        check.say(node, "each dimension goes through the dimensions that "
                  "Questions that may be read again or Open dimensions "
                  "chose, so one of them stands before it, in the chain")
    if "off" in node and not isinstance(node["off"], bool):
        check.say(node, "off is yes or no")
    steps = node.get("steps")
    if not isinstance(steps, list) or not steps:
        check.say(node, "steps are a list of boxes, not empty")
        return
    inside = list(chain or [])
    for child in steps:
        if not isinstance(child, dict):
            check.say({}, f"a step is an object, not {child!r}")
            continue
        _identify(check, child)
        if flow_map.kind_of(child) != "box":
            check.say(child, "a frame of a pass holds boxes")
            continue
        box = _box(check, child)
        if box is None or not _on(child) or not _on(node):
            continue
        if box.inside != "dimension":
            check.say(child, f"{box.label} stands in the chain and not in "
                      f"an each dimension frame")
            continue
        _after(check, child, box, inside)
        inside.append(rules.step_kind(child))


def shared_trace(first: str, second: str, profile=None) -> Optional[str]:
    """The reason the flows *first* and *second* never run together, or
    None: they write their record into one folder, and the record of a
    document is written anew by every pass that writes it."""
    def folders(name: str) -> set:
        found = set()
        for node, _frames in flow_map.on(load(name, profile)):
            if node.get("box") in blocks.LIBRARY:
                value = (node.get("set") or {}).get("trace")
                if value:
                    found.add(value)
        return found

    both = folders(first) & folders(second)
    if not both:
        return None
    return (f"the flows {first} and {second} write their record into one "
            f"folder, {', '.join(sorted(both))}, and a pass writes the "
            f"record of a document anew: they do not run together")


def homes(profile=None) -> dict:
    """{kind of request: the first box of a pass flow that asks it}, the
    boxes of the flows that a profile's line writes and the run can do. A
    flow that cannot be read is left out and said."""
    found: dict = {}
    for name in names(profile):
        if name == MAIN:
            continue
        try:
            tree = load(name, profile)
        except (flow_map.FlowError, LookupError, OSError) as exc:
            log.warning("flow %s: %s", name, exc)
            continue
        for node, _frames in flow_map.on(tree):
            asks = blocks.asks_of(node) if "box" in node else None
            if asks:
                found.setdefault(asks, node)
    return found


# -- running a flow -----------------------------------------------------------

class Run:
    """What a pass runs with: where the harvest is, the spec, the stamp
    this run would write, the means to read a document again, and what the
    boxes count between them. The runner fills it; a box takes what it
    needs."""

    def __init__(self, **given):
        self.out: Optional[Path] = None
        self.spec = None
        self.current: dict = {}
        self.deps: dict = {}
        self.only = None                # the keys a call names
        self.documents: list = []       # [(id, file name)] the run reads
        self.named: Callable = lambda: None
        self.in_flight = 1
        self.room: Optional[Callable] = None
        self.stats: Counter = Counter()
        self.locate = None
        self.document_spec: Callable = lambda document_id: self.spec
        # the second reading
        self.ask: Optional[Callable] = None
        self.sources_for: Optional[Callable] = None
        self.prompt_sha = ""
        self.model = ""
        self.review_producer: Optional[dict] = None
        self.reviewed = 0
        self.untouched: set = set()
        self.failed = 0
        self.done = 0                   # the documents a chain went through
        self.working: list = []
        self.ended = False
        # reading a document again
        self.take_parameters: Optional[Callable] = None
        self.take_passages: Optional[Callable] = None
        self.passages_of: Optional[Callable] = None
        self.found = None
        self.make_found: Optional[Callable] = None
        self.harvest_documents: Optional[Callable] = None
        self.harvest_document: Optional[Callable] = None
        self.open_trace: Callable = lambda folder: None
        self.begin_archive: Callable = lambda name: None
        self.flush_trace: Callable = lambda document_id: None
        self.traces: list = []          # the folders the run wrote into
        self.lock = threading.Lock()
        self.__dict__.update(given)


def setting(node: dict, key: str):
    """What a box of a pass says for the setting *key*: its own value or
    the library's."""
    own = node.get("set") or {}
    if key in own:
        return own[key]
    box = blocks.box_of(node)
    found = next(s.default for s in box.settings if s.key == key)
    return "" if found is None and next(
        s.kind for s in box.settings if s.key == key) == blocks.TEXT \
        else found


def stepped(node: dict) -> rules.Step:
    """The values *node* sets for itself, laid over those of the frames it
    stands in (`rules.STEP`)."""
    return rules.stepped(node, dict(node.get("rules") or {}))


def run_node(run: Run, doc, node: dict) -> None:
    """One box or frame for one document, with its own values for as long
    as it runs. A node that is off does not run."""
    if node.get("off"):
        return
    from . import passboxes
    with rules.in_step(stepped(node)):
        if "each" in node:
            for unit in list(doc.units):
                doc.unit = unit
                for child in node.get("steps") or ():
                    if doc.stop:
                        return
                    run_node(run, doc, child)
            doc.unit = None
            return
        act = act_of(node)
        if act is None:
            raise PassError(f"{blocks.box_of(node).label} is not "
                            f"a step a run starts")
        act(run, doc, node)


def act_of(node: dict) -> Optional[Callable]:
    """What runs a step of a pass, act(run, doc, node), None where no run
    starts it: its box's (`passboxes.ACTS`), for "Ask the model" its
    target's (`targets.Target.pass_run`)."""
    from . import passboxes, targets
    if node.get("box") == "ask":
        target = targets.TARGETS.get(blocks.target_of(node))
        return target.pass_run if target is not None else None
    return passboxes.ACTS.get(node.get("box"))


def _chains(tree: list) -> list:
    """[(the nodes of a chain, or the one box that runs once)] of *tree* in
    order, the chains with the box that starts them first."""
    out: list = []
    for node in tree:
        box = blocks.box_of(node)
        if "each" in node:
            if out and isinstance(out[-1], list):
                out[-1].append(node)
            continue
        if box.scope in ("files", "documents"):
            out.append([node])
        elif box.scope == "chain":
            if out and isinstance(out[-1], list):
                out[-1].append(node)
        else:
            out.append(node)
    return out


def run_flow(tree: list, run: Run) -> Counter:
    """Every box of *tree*, in order: the chains for each of their
    documents, the boxes that run once where they stand. What a chain
    counted is in the returned counts, and in `run.stats`."""
    from . import passboxes
    for part in _chains(tree):
        if isinstance(part, dict):
            if not part.get("off"):
                with rules.in_step(stepped(part)):
                    act = act_of(part)
                    if act is None:
                        raise PassError(
                            f"{blocks.box_of(part).label} is not "
                            f"a step a run starts")
                    act(run, None, part)
            continue
        if part[0].get("off"):
            continue
        _chain(run, part)
    return run.stats


def _poll(start: dict) -> tuple:
    """(seconds between two looks at the documents, the same while they
    wait for room): the values of the box that starts the chain."""
    with rules.in_step(stepped(start)):
        return (rules.get("document_poll_s"),
                rules.get("document_poll_room_s"))


def _one(run: Run, chain: list, make_doc: Callable, key) -> tuple:
    """The chain for one document: (what it counted, the document)."""
    from . import passboxes
    doc = make_doc(key)
    for node in chain:
        if doc.stop:
            break
        run_node(run, doc, node)
    if not doc.stats[passboxes.UNREADABLE]:
        doc.stats["documents"] += 1
    return doc.stats, doc


def _chain(run: Run, chain: list) -> None:
    from . import passboxes
    start = chain[0]
    box = blocks.box_of(start)
    folder, archive_as, label = (
        setting(start, key) if any(s.key == key for s in box.settings)
        else "" for key in ("trace", "archive", "label"))
    if archive_as:
        run.begin_archive(archive_as)
    if folder:
        run.open_trace(folder)
        run.traces.append(folder)
    counted: Counter = Counter()

    def make_doc(key):
        return passboxes.Doc(run, *key)

    if box.scope == "files":
        paths = passboxes.files_of(run, setting(start, "files"))
        keys = [(path,) for path in paths]
        if setting(start, "parallel"):
            _beside(run, start, chain, make_doc, keys, counted)
        else:
            for key in keys:
                if run.ended:
                    break
                stats, _doc = _one(run, chain, make_doc, key)
                counted.update(stats)
    else:
        def per_document(document_id: int, filename: str) -> tuple:
            stats, doc = _one(run, chain, make_doc, (
                Path(run.out) / f"{Path(filename).stem}.jsonl",
                document_id, filename))
            if label:
                run.flush_trace(document_id)
                with run.lock:
                    counted.update(stats)
                    counted["documents looked at (documents)"] += 1
            return doc.written, doc.failed

        done, _written, failed = run.harvest_documents(run.documents,
                                                       per_document)
        run.done += done
        run.failed += failed
    run.stats.update(counted)
    if label:
        width = 64 if box.scope == "documents" else 32
        for key, value in sorted(counted.items()):
            log.info("%s: %-*s %d", label, width, key, value)
    if counted[passboxes.UNREADABLE]:
        log.warning("%s: %d document(s) left alone, their choice lists "
                    "could not be closed", label or "pass",
                    counted[passboxes.UNREADABLE])


def _beside(run: Run, start: dict, chain: list, make_doc: Callable,
            keys: list, counted: Counter) -> None:
    """The documents of the chain side by side, as many as the run says and
    the server has room for."""
    from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
    workers = max(1, int(run.in_flight))
    pending: set = set()
    keys = list(keys)
    with ThreadPoolExecutor(max_workers=workers,
                            thread_name_prefix="open") as pool:
        while keys or pending:
            poll, poll_room = _poll(start)
            allowed = workers - len(pending)
            if run.room is not None:
                allowed = min(allowed, run.room(len(pending)))
            while keys and allowed > 0:
                pending.add(pool.submit(_one, run, chain, make_doc,
                                        keys.pop(0)))
                allowed -= 1
            if not pending:
                # No room with nothing of this pass open: something else
                # holds the server, so look again in a moment.
                time.sleep(poll_room)
                continue
            finished, pending = wait(
                pending,
                timeout=poll_room if run.room is not None and keys
                else poll, return_when=FIRST_COMPLETED)
            for future in finished:
                stats, _doc = future.result()
                counted.update(stats)


def one(tree: list, run: Run, document_id: int, filename: str,
        start: Optional[str] = None):
    """The first chain of *tree* (the one that starts with the box *start*,
    where one is named) for one document of the run, the document that
    comes out of it. For the callers that read a single document."""
    from . import passboxes
    for part in _chains(tree):
        if isinstance(part, list) and not part[0].get("off") \
                and start in (None, part[0].get("box")):
            _stats, doc = _one(
                run, part, lambda key: passboxes.Doc(run, *key),
                (Path(run.out) / f"{Path(filename).stem}.jsonl",
                 document_id, filename))
            return doc
    raise PassError("the flow has no step that takes documents"
                    + (f" and starts with {start}" if start else ""))


def run_named(name: str, run: Run, profile=None) -> Counter:
    """The flow *name* of *profile* (the active profile where none is
    given), run with *run*; what it counted."""
    if profile is None:
        from ..profile import active_profile
        profile = active_profile()
    return run_flow(load(name, profile), run)


def startable(tree: list) -> Optional[str]:
    """Why no run starts this flow, or None: a box that stands in the
    library for a request no run starts (the example of a field is asked
    while a spec is compiled) cannot be started from here."""
    for node, _frames in flow_map.on(tree):
        if node.get("box") in blocks.LIBRARY and act_of(node) is None:
            return (f"{blocks.box_of(node).label} is not a step a run "
                    f"starts: it stands in the library so that its "
                    f"request has values of its own")
    return None
