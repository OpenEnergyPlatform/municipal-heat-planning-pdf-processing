"""
flow.py: The steps a document is read in and the numbers that bound them,
read from a file of the profile.

How a document is read stood in four places: the order in the code of the
reading (`addressed.Reader`), some of its numbers in the settings, others as
constants in three modules, its switches in the spec. Since 2026-11-10 the
numbers stand in one file and the steps beside them, so that both can be
seen and the numbers set where the spec and the prompts are (`docpipe
edit`):

    <profile folder>/flow.json

The default profile writes the whole file: every number the reading takes
(`NUMBERS`) and its steps. A profile that extends it writes only the numbers
it sets differently, and its file is laid over the default's number by
number (`load`); the steps are the default's. A setting of the run wins over
the file for the numbers that have one (`Number.env`): the environment, then
the project file, then this file (`in_effect`).

The steps say what the code does and are not run from the file: the order is
the code's until the reading is cut into steps that can be (the plan's stage
4). So that the file cannot say something else than the code, it is read
strictly: every request the code sends stands in a step (`kinds`), a step
asks no request the code does not send, every number bounds a step, and a
number the code does not take is refused.

Nothing here decides whether a harvest is current. A stamp names, in the
entry of each pass that asked a model, the numbers the pass read with and
the sha256 of the flow's files (`runner.producer`, `Numbers.sha256`), for a
reader, as it names every prompt (owner decision 2026-09-10: a stamp rests on
the questions alone).

Author: Felix Vossel
"""
from __future__ import annotations

import dataclasses
import difflib
import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

FILE = "flow.json"
# The file every flow starts from.
DEFAULT_NAME = "default"
DEFAULT = Path(__file__).resolve().parent.parent / "builtin" / DEFAULT_NAME \
    / FILE


class FlowError(ValueError):
    """A flow a run cannot read. It names the file or the setting."""


@dataclass(frozen=True)
class Number:
    """One number the reading takes."""
    name: str
    least: int
    help: str
    env: Optional[str] = None       # the setting that wins over the file
    part: Optional[int] = None      # its place where the setting lists several


# Every number the reading takes from the flow, in the order a file writes
# them. What each is by default stands in the default profile's file and
# nowhere in the code.
NUMBERS = (
    Number("piece_lines", 1,
           "Lines of a piece a document is read in; a table's head is shown "
           "with each of its pieces."),
    Number("title_page_lines", 1,
           "Lines of the document's first page a request shows as its title "
           "page."),
    Number("headings", 0,
           "Headings a request shows up to a value's place, its own last."),
    Number("list_meanings", 0,
           "Entries up to which a list is shown with what each entry means; "
           "a longer list shows its names only, and one whose entries name "
           "groups is asked group first."),
    Number("search_pieces", 1,
           "Pieces a search shows for an open coordinate or for a field the "
           "document has once.", "EXTRACT_SEARCH_PIECES"),
    Number("search_tables", 0,
           "Share of a search's pieces that are the best pieces of tables, "
           "taken first; the three shares are scaled to the pieces of the "
           "search, the rest are the best of any kind.",
           "EXTRACT_SEARCH_SHARES", 0),
    Number("search_figures", 0,
           "Share of a search's pieces that are the best pieces of figures, "
           "taken first.", "EXTRACT_SEARCH_SHARES", 1),
    Number("search_text", 0,
           "Share of a search's pieces that are the best pieces of text, "
           "taken first.", "EXTRACT_SEARCH_SHARES", 2),
    Number("search_per_request", 1,
           "Pieces one request of a search shows.", "EXTRACT_SEARCH_CHUNKS"),
    Number("listed_field_factor", 1,
           "Times the pieces of a search that a field the document has once "
           "reads where its values come from a list."),
    Number("follow_ups", 0,
           "Times a request is asked again whose answer did not hold, each "
           "time with the answer and why it did not hold."),
    Number("replies", 1,
           "Replies out of their form a request takes before it is left "
           "unanswered; a request the server refuses is asked as often.",
           "EXTRACT_MAX_RETRIES"),
)
BY_NAME = {number.name: number for number in NUMBERS}

# What a step may say of itself.
STEP_KEYS = ("id", "ask", "each", "when", "says", "bound", "shows", "needs",
             "steps")
# The switches of a spec and a profile a step can show (`shows`) or need to
# be asked at all (`needs`); what each is in a profile is `docpipe edit`'s to
# say (`editor.flow`).
SWITCHES = ("plan_fields", "works", "names", "once_per_document",
            "own_passage", "own_value", "takes_group", "compute")
PLACE = re.compile(r"\{([^{}]*)\}")


@dataclass(frozen=True)
class Numbers:
    """The numbers one run reads with, and where each comes from."""
    piece_lines: int
    title_page_lines: int
    headings: int
    list_meanings: int
    search_pieces: int
    search_tables: int
    search_figures: int
    search_text: int
    search_per_request: int
    listed_field_factor: int
    follow_ups: int
    replies: int
    # name -> where its value comes from: "flow.json of <profile>", or what
    # set the setting that won over the file (`settings.origin`).
    origin: dict = field(default_factory=dict, compare=False, repr=False)
    # Of the flow's file as laid over each other, steps and numbers; the
    # settings that won are not in it.
    sha256: str = field(default="", compare=False, repr=False)

    def shares(self) -> dict:
        """{kind of passage: its share of a search's pieces}."""
        return {"table": self.search_tables, "figure": self.search_figures,
                "section": self.search_text}

    def as_dict(self) -> dict:
        return {number.name: getattr(self, number.name)
                for number in NUMBERS}


if tuple(f.name for f in dataclasses.fields(Numbers)
         if f.name not in ("origin", "sha256")) \
        != tuple(number.name for number in NUMBERS):
    raise AssertionError("flow.Numbers and flow.NUMBERS name different "
                         "numbers")


@dataclass(frozen=True)
class Flow:
    """A profile's flow as its files say it, no setting applied."""
    numbers: dict                   # name -> value, in the order of NUMBERS
    owners: dict                    # name -> the profile whose file says it
    steps: list
    files: tuple                    # ((profile name, path)), nearest first
    sha256: str


# -- the file ------------------------------------------------------------------

def path_of(profile) -> Path:
    """Where *profile* writes its flow."""
    return Path(profile.package_dir) / FILE


def kinds() -> tuple:
    """The requests the code sends while it reads a document: those of the
    reading (`addressed.KINDS`) and the calculation after it."""
    from . import addressed, compute
    return tuple(addressed.KINDS) + (
        compute.COMPUTE_PROMPT_ID.rsplit("/", 1)[-1],)


def _nearest(name: str, known) -> str:
    close = difflib.get_close_matches(str(name), list(known), n=3, cutoff=0.6)
    return f" (did you mean {', '.join(close)}?)" if close else ""


def problem(name: str, value) -> Optional[str]:
    """Why *value* is not the number *name* of the flow, None where it
    is: *name* is none of its numbers, or *value* no whole number of at
    least its least value."""
    number = BY_NAME.get(name)
    if number is None:
        return (f"{name!r} is no number of the flow"
                f"{_nearest(name, BY_NAME)}")
    if isinstance(value, bool) or not isinstance(value, int):
        return f"{name} must be a whole number, not {value!r}"
    if value < number.least:
        return f"{name} must be at least {number.least}, not {value}"
    return None


def checked(where, name: str, value) -> int:
    """*value* as the number *name* of the flow, FlowError where it is
    none (`problem`). *where* names the file in what is said about it."""
    said = problem(name, value)
    if said is not None:
        raise FlowError(f"{where}: {said}")
    return value


def _steps(where, raw, seen: dict, asked: set, bounded: set) -> list:
    if not isinstance(raw, list) or not raw:
        raise FlowError(f"{where}: steps must be a list of steps, not empty")
    known = kinds()
    out = []
    for step in raw:
        if not isinstance(step, dict):
            raise FlowError(f"{where}: a step must be an object, not "
                            f"{step!r}")
        name = step.get("id")
        if not isinstance(name, str) or not name.strip():
            raise FlowError(f"{where}: every step needs an id")
        at = f"{where}: step {name}"
        if name in seen:
            raise FlowError(f"{at} stands twice")
        seen[name] = step
        for key in step:
            if key not in STEP_KEYS:
                raise FlowError(f"{at} has no key {key!r}"
                                f"{_nearest(key, STEP_KEYS)}")
        for key in ("says", "each", "when", "bound", "ask", "needs"):
            if key in step and not (isinstance(step[key], str)
                                    and step[key].strip()):
                raise FlowError(f"{at}: {key} must be a text, not empty")
        if "says" not in step:
            raise FlowError(f"{at} must say what it does (says)")
        if "ask" in step:
            if step["ask"] not in known:
                raise FlowError(
                    f"{at} asks {step['ask']!r}, which the code does not "
                    f"send{_nearest(step['ask'], known)}")
            asked.add(step["ask"])
        for place in PLACE.findall(step.get("bound", "")):
            if place not in BY_NAME:
                raise FlowError(f"{at} is bounded by {{{place}}}, which is "
                                f"no number of the flow"
                                f"{_nearest(place, BY_NAME)}")
            bounded.add(place)
        shows = step.get("shows", [])
        if not isinstance(shows, list) or ("shows" in step and not shows):
            raise FlowError(f"{at}: shows must be a list of switches, not "
                            f"empty")
        for switch in [*shows, *([step["needs"]] if "needs" in step
                                 else [])]:
            if switch not in SWITCHES:
                raise FlowError(f"{at} names {switch!r}, which is no switch "
                                f"a step shows{_nearest(switch, SWITCHES)}")
        made = dict(step)
        if "steps" in step:
            made["steps"] = _steps(where, step["steps"], seen, asked,
                                   bounded)
        out.append(made)
    return out


def parse(raw: str, where, whole: bool) -> dict:
    """{"numbers": {name: value}, "steps": [...]} of the text *raw*, read
    strictly. A *whole* file names every number and the steps; any other is
    laid over one and names numbers only. *where* names the file in what is
    said about it."""
    def once(pairs: list) -> dict:
        out: dict = {}
        for key, value in pairs:
            if key in out:
                raise FlowError(f"{where}: {key!r} stands twice")
            out[key] = value
        return out

    try:
        data = json.loads(raw, object_pairs_hook=once)
    except FlowError:
        raise
    except ValueError as exc:
        raise FlowError(f"{where}: {exc}") from exc
    if not isinstance(data, dict):
        raise FlowError(f"{where}: a flow file is one JSON object with "
                        f"\"numbers\" and, in the file a flow starts from, "
                        f"\"steps\"")
    for key in data:
        if key not in ("numbers", "steps"):
            raise FlowError(f"{where}: has no key {key!r}; a flow file "
                            f"holds \"numbers\" and \"steps\"")
    numbers = data.get("numbers", {})
    if not isinstance(numbers, dict):
        raise FlowError(f"{where}: numbers must be an object, the name of a "
                        f"number -> its value")
    read = {name: checked(where, name, value)
            for name, value in numbers.items()}
    if not whole:
        if "steps" in data:
            raise FlowError(
                f"{where}: the steps are those of the file the flow starts "
                f"from; this file sets numbers only")
        return {"numbers": read}
    missing = [number.name for number in NUMBERS if number.name not in read]
    if missing:
        raise FlowError(f"{where}: names no {', '.join(missing)}; the file "
                        f"a flow starts from names every number")
    asked: set = set()
    bounded: set = set()
    steps = _steps(where, data.get("steps"), {}, asked, bounded)
    unasked = [kind for kind in kinds() if kind not in asked]
    if unasked:
        raise FlowError(f"{where}: the code sends {', '.join(unasked)}, and "
                        f"no step of the flow asks it")
    loose = [number.name for number in NUMBERS
             if number.name not in bounded]
    if loose:
        raise FlowError(f"{where}: {', '.join(loose)} bounds no step")
    return {"numbers": read, "steps": steps}


def dump(data: dict, newline: str = "\n") -> str:
    """A flow file's text in the one form it is written in."""
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    return text if newline == "\n" else text.replace("\n", newline)


def line(profile) -> list:
    """[(profile name, path)] of the files a profile's flow can stand in,
    nearest first; the default's alone where no profile is given or it has
    no folder of its own."""
    if profile is None or getattr(profile, "package_dir", None) is None:
        return [(DEFAULT_NAME, DEFAULT)]
    lineage = getattr(profile, "lineage", None)
    line = lineage() if callable(lineage) else [profile]
    return [(one.name, path_of(one)) for one in line]


_loaded: dict = {}
LOADED_KEPT = 16


def _merged(written: list) -> Flow:
    """The flow of the files *written* ([(profile name, path)], nearest
    first, each a file): the farthest is the whole flow, the numbers of
    every nearer one are laid over it. Read once per state of the files."""
    key = tuple((str(path), path.stat().st_mtime_ns, path.stat().st_size)
                for _, path in written)
    if key in _loaded:
        return _loaded[key]
    (first, start), nearer = written[-1], written[:-1]
    whole = parse(start.read_text(encoding="utf-8"), start, True)
    numbers = dict(whole["numbers"])
    owners = {name: first for name in numbers}
    for name, path in reversed(nearer):
        own = parse(path.read_text(encoding="utf-8"), path, False)
        for number, value in own["numbers"].items():
            numbers[number], owners[number] = value, name
    numbers = {number.name: numbers[number.name] for number in NUMBERS}
    sha = hashlib.sha256(json.dumps(
        {"numbers": numbers, "steps": whole["steps"]}, ensure_ascii=False,
        sort_keys=True).encode("utf-8")).hexdigest()
    flow = Flow(numbers, owners, whole["steps"], tuple(written), sha)
    while len(_loaded) >= LOADED_KEPT:
        _loaded.pop(next(iter(_loaded)))
    _loaded[key] = flow
    return flow


def load(profile=None) -> Flow:
    """The flow of *profile* as its files say it: the file of the farthest
    profile of its line that writes one is the whole flow, and the numbers
    of every nearer one are laid over it. LookupError where no profile of
    the line writes one."""
    written = [(name, path) for name, path in line(profile)
               if path.is_file()]
    if not written:
        names = [name for name, _ in line(profile)]
        raise LookupError(f"profile {names[0]!r} writes no {FILE}"
                          + (f", nor does {', '.join(names[1:])}, which it "
                             f"extends" if names[1:] else ""))
    return _merged(written)


def inherited(profile) -> Optional[Flow]:
    """The flow of the profiles *profile* extends, its own file left out:
    what a number is where the profile does not set it. None where no
    profile it extends writes a flow, so that its own file is the whole
    one."""
    written = [(name, path) for name, path in line(profile)[1:]
               if path.is_file()]
    return _merged(written) if written else None


# -- what a run reads with -----------------------------------------------------

def _setting(number: Number, raw: str) -> int:
    """The value of a number as its setting spells it."""
    text = raw
    if number.part is not None:
        parts = raw.split(",")
        if len(parts) != 3:
            raise FlowError(f"{number.env} must be three numbers (tables, "
                            f"figures, text), not {raw!r}")
        text = parts[number.part]
    try:
        value = int(text.strip())
    except ValueError:
        raise FlowError(f"{number.env} must be "
                        f"{'whole numbers' if number.part is not None else 'a whole number'}"
                        f", not {raw!r}") from None
    if value < number.least:
        raise FlowError(f"{number.env}: {number.name} must be at least "
                        f"{number.least}, not {value}")
    return value


def in_effect(profile=None, environ=None) -> Numbers:
    """The numbers a run of *profile* reads with: the flow of its files, and
    over it the settings that are set (*environ*, the environment where not
    given, into which the project file was put). `Numbers.origin` says for
    each where it comes from."""
    from .. import settings
    flow = load(profile)
    own = environ is None
    environ = os.environ if own else environ
    values: dict = {}
    origin: dict = {}
    for number in NUMBERS:
        raw = environ.get(number.env) if number.env else None
        if raw is None:
            values[number.name] = flow.numbers[number.name]
            origin[number.name] = f"{FILE} of {flow.owners[number.name]}"
        else:
            values[number.name] = _setting(number, raw)
            origin[number.name] = settings.origin(number.env) if own \
                else "environment"
    return Numbers(**values, origin=origin, sha256=flow.sha256)


def default() -> Numbers:
    """The numbers of the default profile's file, no setting applied: what
    a reading takes where it is given none."""
    return in_effect(None, environ={})
