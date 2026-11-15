"""
conditions.py: The conditions a flow's boxes and frames are set with, as
`docpipe edit` writes them (owner decisions 2026-11-10 evening: the flow is
a free drawing, its conditions written in the page, no JSON typed).

A condition is one row or several; each row says [what it is about] [which
of its properties] [a comparison] [a value], and may be negated ("not").
All rows are joined by "and", or all by "or":

    {"all": [{"of": "quote", "is": "length", "op": "less", "value": 20}]}
    {"any": [{"of": "coordinate", "is": "state", "op": "one_of",
              "value": ["read"]},
             {"of": "coordinate", "is": "state", "op": "one_of",
              "value": ["unbacked"]}]}

What a row can be about, and each thing's properties, the code provides
(`SUBJECTS`); the page offers only what there is at a box's place (`where`
of the flow). A property is a yes or no (`yes`, no comparison), a number
(`is`, `is_not`, `less`, `more`, `at_least`, `at_most`), a text (`is`,
`contains`, `empty`) or one of a list (`one_of`).

`problems` says why a condition cannot be evaluated where it stands: a row
about something there is not yet at that place (a quote before the first
question), a comparison its property does not take, a value of the wrong
kind, a value missing. `holds` evaluates a condition against what the run
knows at that place (`Facts`), and `sentence` says it as the page shows it
at its box ("when the quote is shorter than 20 characters").

A property whose entries a spec adds to (`Prop.added_by`: the kind of
value of a field, whose entries are the spec's value types, owner request
2026-11-15) takes the entries of the spec where one is known (`added`,
`catalogue(added=...)`), and any name where none is: a flow is drawn for
every spec of its profile's line, and the run compares the field's type by
its name.

"open" as a state of a coordinate means what `--top-up-open` reads again:
the states of the rule `open_states` (exhausted, unanswered, unbacked
unless a step says otherwise); "none" that it has no state yet.

Author: Felix Vossel
"""
from __future__ import annotations

import contextlib
import contextvars
import re
from dataclasses import dataclass
from typing import Callable, Optional

from .. import rules
from .fields import (DERIVED, EXHAUSTED, OUT_OF_SLICE, READ, SAID_UNSTATED,
                     UNANSWERED, UNBACKED)

YES, NUMBER, TEXT, CHOICE = "yes", "number", "text", "choice"
# The comparisons each kind of property takes.
OPS = {YES: (),
       NUMBER: ("is", "is_not", "less", "more", "at_least", "at_most"),
       TEXT: ("is", "contains", "empty"),
       CHOICE: ("one_of",)}
OP_WORDS = {"is": "is", "is_not": "is not", "less": "is less than",
            "more": "is more than", "at_least": "is at least",
            "at_most": "is at most", "contains": "contains",
            "empty": "is empty", "one_of": "is one of"}
# A coordinate's state as a condition names it; "open" and "none" are not
# states a run writes but kinds of them ("open": the rule `open_states`,
# one collection with fields, topup and stats).
from .fields import OPEN  # noqa: E402,F401  (rule `open_states`)
STATES = (READ, SAID_UNSTATED, UNBACKED, EXHAUSTED, UNANSWERED, DERIVED,
          OUT_OF_SLICE, "open", "none")
ROLES = ("text", "title", "head", "body", "foot", "figure", "number",
         "heading")
COORDINATE_KINDS = ("number", "list", "text", "name", "work", "quantity")
PASSAGE_KINDS = ("section", "table", "figure")
# What the page shows for each choice; the code word stays in the flow file.
STATE_WORDS = {
    READ: "read", SAID_UNSTATED: "not stated in the document",
    UNBACKED: "answer not backed by its quote",
    EXHAUSTED: "still open when the search ended", UNANSWERED: "no answer",
    DERIVED: "derived, not asked",
    OUT_OF_SLICE: "not asked: another dimension excludes the value",
    "open": "still open (search ended, no answer or not backed)",
    "none": "no state yet"}
ROLE_WORDS = {"text": "sentence", "title": "title of a table",
              "head": "table head", "body": "table row",
              "foot": "line under a table",
              "figure": "line of a figure's caption",
              "number": "number of a figure", "heading": "heading"}
KIND_WORDS = {"number": "number", "list": "entry of a list", "text": "text",
              "name": "name", "work": "work",
              "quantity": "what a number is"}
PASSAGE_WORDS = {"section": "text", "table": "table", "figure": "figure"}
FIELD_KINDS = ("float", "int", "text", "category")
FIELD_WORDS = {"float": "number with decimals", "int": "whole number",
               "text": "text", "category": "entry of a list"}
LANGUAGES = ("de", "en", "other")
LANGUAGE_WORDS = {"de": "German", "en": "English", "other": "another "
                  "language"}
# Why an answer was refused, as `Counts.failed` says it; "own_check" is any
# check of the flow's own, "other" any reason not listed here.
REFUSALS = ("none", "not_an_address", "words_not_in_line", "not_an_option",
            "name_not_listed", "quote_not_in_source", "quote_too_short",
            "answer_not_in_quote", "wrong_type", "unbacked", "own_check",
            "other")
REFUSAL_WORDS = {
    "none": "none", "not_an_address": "names no line that was shown",
    "words_not_in_line": "words not in the line it names",
    "not_an_option": "not an entry of the list",
    "name_not_listed": "name not on the list",
    "quote_not_in_source": "quote not in the source",
    "quote_too_short": "quote too short",
    "answer_not_in_quote": "answer not in its quote",
    "wrong_type": "wrong kind of value", "unbacked": "not backed",
    "own_check": "refused by a check of the flow", "other": "another reason"}


def open_states() -> tuple:
    """The states "open" stands for (rule `open_states`), as the step that
    runs reads it."""
    from .fields import open_states as states
    return states()


class ConditionError(ValueError):
    """A condition that cannot be evaluated where it stands."""


@dataclass(frozen=True)
class Prop:
    """One property of a thing a condition can be about."""
    name: str
    kind: str
    label: str
    choices: tuple = ()
    words: Optional[dict] = None    # choice -> what the page shows
    # the list of the spec that adds entries to *choices* ("value_types"):
    # its entries where a spec is known (`added`), any name where none is
    added_by: str = ""


@dataclass(frozen=True)
class Subject:
    """A thing a condition can be about, and its properties."""
    name: str
    label: str
    props: tuple

    def prop(self, name: str) -> Optional[Prop]:
        return next((p for p in self.props if p.name == name), None)


SUBJECTS = {s.name: s for s in (
    Subject("line", "the next line", (
        Prop("heading", YES, "is a heading"),
        Prop("passage_begins", YES, "begins a section, table or figure"),
        Prop("table_begins", YES, "begins a table"),
        Prop("figure_begins", YES, "begins a figure"),
        Prop("new_page", YES, "stands on a new page"),
        Prop("role", CHOICE, "kind of line", ROLES, ROLE_WORDS),
        Prop("lines_in_piece", NUMBER, "lines of the chunk so far"),
    )),
    Subject("field", "the field", (
        Prop("has_list", YES, "has a list"),
        Prop("numbers", YES, "is a field of numbers"),
        Prop("once", YES, "is asked once per document"),
        Prop("takes_group", YES, "splits a group of entries into its "
             "members"),
        Prop("name", TEXT, "name"),
        Prop("unit", TEXT, "unit of its values"),
        Prop("kind", CHOICE, "kind of value", FIELD_KINDS, FIELD_WORDS,
             added_by="value_types"),
        Prop("rows", NUMBER, "values read of it so far"),
    )),
    Subject("value", "the value", (
        Prop("field", TEXT, "field"),
        Prop("words", TEXT, "wording"),
        Prop("length", NUMBER, "length of its wording"),
        Prop("scenario_name", YES, "names a scenario of the document's "
             "list"),
        Prop("passage", CHOICE, "stands in", PASSAGE_KINDS, PASSAGE_WORDS),
        Prop("in_table", YES, "was read in a table"),
        Prop("in_text", YES, "was read in running text"),
        Prop("number", NUMBER, "the number read"),
        Prop("quote", TEXT, "quote"),
    )),
    Subject("chunk", "the chunk", (
        Prop("kind", CHOICE, "kind", PASSAGE_KINDS, PASSAGE_WORDS),
    )),
    Subject("figure", "the figure", (
        Prop("description", TEXT, "description from the intake"),
        Prop("has_image", YES, "has an image"),
        Prop("page", NUMBER, "page"),
        Prop("image_width", NUMBER, "width of its image in pixels"),
        Prop("image_height", NUMBER, "height of its image in pixels"),
    )),
    Subject("coordinate", "the dimension", (
        Prop("name", TEXT, "name"),
        Prop("state", CHOICE, "state", STATES, STATE_WORDS),
        Prop("kind", CHOICE, "kind", COORDINATE_KINDS, KIND_WORDS),
        Prop("own_only", YES, "is stated only where the value stands"),
        Prop("required", YES, "must be read for the value to count"),
        Prop("year", YES, "is a year"),
        Prop("closed_before", YES, "follows a dimension that found the "
             "value does not belong to its field"),
        Prop("plan_years", YES, "has base or target years in the "
             "document"),
        Prop("unanswered", YES, "had a request about it that got no "
             "answer in form"),
        Prop("own_value", YES, "is printed with the number"),
    )),
    Subject("answer", "the answer", (
        Prop("answered", YES, "came back in the expected form"),
        Prop("zero", YES, "names no line (0)"),
        Prop("finds", NUMBER, "number of finds that pass the checks"),
        Prop("other_passage", YES, "comes from another section, table or "
             "figure than the value"),
        Prop("words_empty", YES, "has no wording"),
        Prop("follow_ups_used", NUMBER, "follow-up questions used"),
        Prop("refusal", CHOICE, "the reason it was refused", REFUSALS,
             REFUSAL_WORDS),
    )),
    Subject("quote", "the quote", (
        Prop("length", NUMBER, "length in characters"),
        Prop("lines", NUMBER, "number of lines"),
        Prop("number", YES, "contains a number"),
        Prop("year", YES, "contains a year"),
    )),
    Subject("pieces", "the chunks", (
        Prop("shown", NUMBER, "shown so far"),
        Prop("left", NUMBER, "left among the search hits"),
        Prop("never_shown", NUMBER, "of the document not shown yet"),
    )),
    Subject("round", "the round", (
        Prop("number", NUMBER, "number of the round"),
    )),
    Subject("document", "the document", (
        Prop("works", YES, "keeps a list of works"),
        Prop("plan_years", YES, "has base or target years"),
        Prop("pieces", NUMBER, "number of chunks"),
        Prop("language", CHOICE, "language", LANGUAGES, LANGUAGE_WORDS),
        Prop("pages", NUMBER, "number of pages"),
        Prop("title", TEXT, "title"),
        Prop("requests", NUMBER, "requests asked so far"),
        Prop("seconds", NUMBER, "seconds spent on it so far"),
    )),
    Subject("run", "the run", (
        Prop("whole", YES, "reads the whole document (not only the places "
             "an earlier harvest found)"),
    )),
    # Any variable of the flow (owner decision 2026-11-12): its property is
    # the path to it, "answer.finds" or "hits.0.kind"; it takes every
    # comparison, and with none it holds where the value is there and not
    # empty, 0 or no.
    Subject("var", "the variable", ()),
    # What a drawing of the graph decides on (owner request 2026-11-14,
    # wish 4: "die Baublöcke und Einstellungsmöglichkeiten genau wie im Flow
    # fein"): any key of a reading of the harvest, its answers, wordings and
    # states ("quantity", "spatial_scope_raw", "year_state"), and what is
    # known of the document ("place", "ags"), each by its path.
    Subject("reading", "the reading", ()),
    Subject("fact", "what is known of the document", ()),
)}
# The thing a row about a variable is about.
VAR = "var"
# Every comparison, which a row about a variable may make.
ALL_OPS = ("is", "is_not", "less", "more", "at_least", "at_most",
           "contains", "empty", "one_of")
# The comparisons only a reading of the graph makes, each without a value
# but `answer_of` (the box): an entry of the list the spec gives this
# dimension of the reading's field and no out: entry; a text that names
# something once its words are folded; an answer of the table of a box; a
# whole number; an identifier of a term (OEO_00000128).
GRAPH_OPS = ("listed", "names", "answer_of", "whole", "term")
OP_WORDS.update({"listed": "is an entry of its list in the spec",
                 "names": "names something", "answer_of":
                 "is an answer of the table of the box", "whole":
                 "is a whole number", "term": "is the identifier of a term"})
# The things whose property is a path, and the comparisons each takes.
FREE = {VAR: ALL_OPS, "reading": ALL_OPS + GRAPH_OPS, "fact": ALL_OPS}
# The things a condition of the graph's drawing is about, and only those.
GRAPH_SUBJECTS = ("reading", "fact")


def _rows(condition) -> tuple:
    """(joiner, rows) of a condition, ConditionError where it is none."""
    if not isinstance(condition, dict) or len(condition) != 1:
        raise ConditionError("a condition is {\"all\": [rows]} or "
                             "{\"any\": [rows]}")
    (joiner, rows), = condition.items()
    if joiner not in ("all", "any"):
        raise ConditionError(f"a condition joins its rows by all or any, "
                             f"not {joiner!r}")
    if not isinstance(rows, list) or not rows:
        raise ConditionError("a condition needs one row at least")
    return joiner, rows


# The entries a spec adds to an open property, by `Prop.added_by`, where
# the code that checks a condition knows the spec (`added`).
_ADDED: contextvars.ContextVar = contextvars.ContextVar("added", default=None)


@contextlib.contextmanager
def added(entries: Optional[dict]):
    """Check conditions inside against the entries of a spec: *entries*
    maps `Prop.added_by` ("value_types") to all its names, the built-in
    ones among them. None: no spec is known, any name counts."""
    token = _ADDED.set(dict(entries) if entries else None)
    try:
        yield
    finally:
        _ADDED.reset(token)


def choices_of(prop: Prop, entries: Optional[dict] = None) -> tuple:
    """The entries *prop* is one of: those of the spec for an open property
    where *entries* (else the spec of `added`) names them, its own
    otherwise."""
    entries = entries if entries is not None else _ADDED.get()
    if prop.added_by and entries and prop.added_by in entries:
        return tuple(entries[prop.added_by])
    return tuple(prop.choices)


def row_problem(row, where) -> Optional[str]:
    """Why one row cannot be evaluated at a place that knows the things
    *where* (names of `SUBJECTS`), None where it can."""
    if not isinstance(row, dict):
        return "a row of a condition is an object"
    for key in row:
        if key not in ("of", "is", "op", "value", "not"):
            return f"a row has no key {key!r}"
    subject = SUBJECTS.get(row.get("of"))
    if subject is None:
        return f"{row.get('of')!r} is nothing a condition can be about"
    if subject.name in FREE:
        return _var_problem(row, where)
    if where is not None and subject.name not in where:
        return (f"{subject.label} is not known here (no question before it)"
                if subject.name in ("answer", "quote")
                else f"{subject.label} is not known here")
    prop = subject.prop(row.get("is"))
    if prop is None:
        return f"{subject.label} has no property {row.get('is')!r}"
    if "not" in row and not isinstance(row["not"], bool):
        return "not is yes or no"
    op = row.get("op")
    if prop.kind == YES:
        if op is not None or "value" in row:
            return f"{subject.label} · {prop.label}: a yes or no takes no " \
                   f"comparison"
        return None
    if op not in OPS[prop.kind]:
        return (f"{subject.label} · {prop.label} takes "
                f"{', '.join(OP_WORDS[o] for o in OPS[prop.kind])}, "
                f"not {op!r}")
    if op == "empty":
        return None if "value" not in row else \
            f"{subject.label} · {prop.label} is empty: no value"
    if "value" not in row:
        return f"{subject.label} · {prop.label} {OP_WORDS[op]}: the value " \
               f"is missing"
    value = row["value"]
    if prop.kind == NUMBER and (isinstance(value, bool)
                                or not isinstance(value, (int, float))):
        return f"{subject.label} · {prop.label} is a number, not {value!r}"
    if prop.kind == TEXT and not isinstance(value, str):
        return f"{subject.label} · {prop.label} is a text, not {value!r}"
    if prop.kind == CHOICE:
        if not isinstance(value, list) or not value:
            return f"{subject.label} · {prop.label}: pick one at least"
        if prop.added_by and _ADDED.get() is None:
            # no spec known: any name, the spec's own types among them
            wrong = [v for v in value if not (isinstance(v, str)
                                              and v.strip())]
            if wrong:
                return (f"{subject.label} · {prop.label} is a name, not "
                        f"{wrong[0]!r}")
            return None
        choices = choices_of(prop)
        wrong = [v for v in value if v not in choices]
        if wrong:
            return (f"{subject.label} · {prop.label} is one of "
                    f"{', '.join(choices)}, not {wrong[0]!r}")
    return None


def _var_problem(row: dict, where) -> Optional[str]:
    """Why a row about a variable cannot be evaluated where the variables
    *where* names ("var:<name>") are there, None where it can."""
    subject = row.get("of")
    path = row.get("is")
    if not isinstance(path, str) or not path.strip():
        return ("a row about a variable names the variable" if subject == VAR
                else f"a row about {SUBJECTS[subject].label} names what of it")
    root = path.split(".")[0]
    if subject == VAR:
        if where is not None and f"var:{root}" not in where:
            return f"the variable {root} is not there yet at this place"
    elif where is not None and subject not in where:
        return f"{SUBJECTS[subject].label} is not known here"
    if "not" in row and not isinstance(row["not"], bool):
        return "not is yes or no"
    op = row.get("op")
    if op is None:
        return None if "value" not in row else \
            f"{path}: a row without a comparison takes no value"
    ops = FREE[subject]
    if op not in ops:
        return f"{path} takes {', '.join(ops)}, not {op!r}"
    if op == "answer_of":
        value = row.get("value")
        return None if isinstance(value, str) and value.strip() else \
            f"{path} {OP_WORDS[op]}: name the box"
    if op == "empty" or op in GRAPH_OPS:
        return None if "value" not in row else f"{path} {OP_WORDS[op]}: " \
                                                f"no value"
    if "value" not in row:
        return f"{path} {OP_WORDS[op]}: the value is missing"
    value = row["value"]
    if op in ("less", "more", "at_least", "at_most") and (
            isinstance(value, bool) or not isinstance(value, (int, float))):
        return f"{path} {OP_WORDS[op]} a number, not {value!r}"
    if op == "one_of" and (not isinstance(value, list) or not value):
        return f"{path} is one of: pick one at least"
    return None


def problems(condition, where=None) -> list:
    """Why *condition* cannot be evaluated at a place that knows the things
    *where* (None: anywhere), [] where it can."""
    try:
        _joiner, rows = _rows(condition)
    except ConditionError as exc:
        return [str(exc)]
    return [said for said in (row_problem(row, where) for row in rows)
            if said]


def rows_of(condition) -> list:
    """The rows of a condition, [] where it is none."""
    try:
        return [row for row in _rows(condition)[1] if isinstance(row, dict)]
    except ConditionError:
        return []


def subjects_of(condition) -> set:
    """The things a condition is about."""
    try:
        return {row.get("of") for row in _rows(condition)[1]
                if isinstance(row, dict)}
    except ConditionError:
        return set()


class Facts:
    """What the run knows at one place: *get(subject, property)* -> the
    value, a LookupError where the place does not know it; *test(subject,
    path, op, value)* -> the truth of a comparison only the place can make
    (`GRAPH_OPS` but `whole` and `term`)."""

    def __init__(self, get: Callable, test: Optional[Callable] = None):
        self.get = get
        self.test = test


_TERM = re.compile(r"[A-Za-z]+_\d+")


def _same(have, want) -> bool:
    if isinstance(have, str) and isinstance(want, str):
        return have.casefold() == want.casefold()
    if isinstance(have, (int, float)) and not isinstance(have, bool) \
            and isinstance(want, (int, float)):
        return float(have) == float(want)
    return have == want


def _var_holds(row: dict, facts: Facts) -> bool:
    have = facts.get(row["of"], row["is"])
    op, want = row.get("op"), row.get("value")
    if op is None:
        got = bool(have)
    elif op == "whole":
        got = isinstance(have, int)
    elif op == "term":
        got = bool(_TERM.fullmatch(str(have or "")))
    elif op in GRAPH_OPS:
        if facts.test is None:
            raise ConditionError(f"{OP_WORDS[op]} is not known here")
        got = bool(facts.test(row["of"], row["is"], op, want))
    elif op == "empty":
        got = have in (None, "", [], {}) or (
            isinstance(have, str) and not have.strip())
    elif op in ("is", "is_not"):
        got = _same(have, want) == (op == "is")
    elif op in ("less", "more", "at_least", "at_most"):
        if isinstance(have, bool) or not isinstance(have, (int, float)):
            try:
                have = float(str(have))
            except ValueError:
                return bool(row.get("not"))
        got = {"less": have < want, "more": have > want,
               "at_least": have >= want, "at_most": have <= want}[op]
    elif op == "contains":
        if isinstance(have, (list, tuple)):
            got = any(_same(one, want) for one in have)
        else:
            got = str(want).casefold() in str(have or "").casefold()
    else:
        got = any(_same(have, one) for one in want)
    return got != bool(row.get("not"))


def _row_holds(row: dict, facts: Facts) -> bool:
    if row.get("of") in FREE:
        return _var_holds(row, facts)
    subject = SUBJECTS[row["of"]]
    prop = subject.prop(row["is"])
    have = facts.get(subject.name, prop.name)
    op, want = row.get("op"), row.get("value")
    if prop.kind == YES:
        got = bool(have)
    elif op == "empty":
        got = not (have or "").strip() if isinstance(have, str) \
            else have in (None, "", [])
    elif prop.kind == NUMBER:
        number = float(have or 0)
        got = {"is": number == want, "is_not": number != want,
               "less": number < want, "more": number > want,
               "at_least": number >= want,
               "at_most": number <= want}[op]
    elif prop.kind == TEXT:
        text = str(have or "")
        got = text.casefold() == want.casefold() if op == "is" \
            else want.casefold() in text.casefold()
    else:
        wanted = set(want)
        if prop.name == "state" and subject.name == "coordinate":
            got = (have in wanted
                   or ("open" in wanted and have in open_states())
                   or ("none" in wanted and not have))
        else:
            got = have in wanted
    return got != bool(row.get("not"))


def holds(condition, facts: Facts) -> bool:
    """Does *condition* hold for what *facts* know? ConditionError where it
    cannot be evaluated (`problems`)."""
    said = problems(condition)
    if said:
        raise ConditionError(said[0])
    joiner, rows = _rows(condition)
    results = (_row_holds(row, facts) for row in rows)
    return all(results) if joiner == "all" else any(results)


def _said(value) -> str:
    if isinstance(value, list):
        return " or ".join(str(v) for v in value)
    return str(value)


def row_sentence(row: dict) -> str:
    if row.get("of") in FREE:
        no = "not " if row.get("not") else ""
        op = row.get("op")
        what = row.get("is") if row.get("of") == VAR else \
            f"{SUBJECTS[row['of']].label}'s {row.get('is')}"
        if op is None:
            return f"{no}{what}"
        if op == "empty":
            return f"{what} is {no}empty"
        if op in GRAPH_OPS and op != "answer_of":
            return f"{what} {no}{OP_WORDS.get(op, op)}"
        return f"{what} {no}{OP_WORDS.get(op, op)} " \
               f"{_said(row.get('value'))}"
    subject = SUBJECTS.get(row.get("of"))
    prop = subject.prop(row.get("is")) if subject else None
    if subject is None or prop is None:
        return "(a row that cannot be read)"
    no = bool(row.get("not"))
    if prop.kind == YES:
        return f"{subject.label} {'not: ' if no else ''}{prop.label}"
    op = row.get("op")
    if op == "empty":
        return f"{subject.label}'s {prop.label} is {'not ' if no else ''}" \
               f"empty"
    words = OP_WORDS.get(op, op or "")
    if no:
        words = f"not {words}" if op != "is" else "is not"
    return f"{subject.label}'s {prop.label} {words} {_said(row.get('value'))}"


def sentence(condition) -> str:
    """The condition as a box shows it: "when the quote's length is less
    than 20"."""
    try:
        joiner, rows = _rows(condition)
    except ConditionError:
        return "(a condition that cannot be read)"
    glue = " and " if joiner == "all" else " or "
    return "when " + glue.join(row_sentence(r) if isinstance(r, dict)
                               else "(a row that cannot be read)"
                               for r in rows)


def one(of: str, is_: str, op: Optional[str] = None, value=None,
        no: bool = False) -> dict:
    """One row, for the code that writes a condition."""
    row: dict = {"of": of, "is": is_}
    if op is not None:
        row["op"] = op
    if value is not None:
        row["value"] = value
    if no:
        row["not"] = True
    return row


def catalogue(graph: bool = False, added: Optional[dict] = None) -> list:
    """Every thing a condition can be about with its properties, as the
    page offers them: those of a flow, or with *graph* those of a drawing
    of the graph (`GRAPH_SUBJECTS`); an open property with the entries of
    the spec *added* names (`choices_of`)."""
    return [{"name": s.name, "label": s.label,
             **({"variable": True, "ops": list(FREE[s.name])}
                if s.name in FREE else {}),
             "props": [{"name": p.name, "kind": p.kind, "label": p.label,
                        "ops": list(OPS[p.kind]),
                        **({"choices": list(choices_of(p, added))}
                           if p.choices else {}),
                        **({"added_by": p.added_by} if p.added_by else {}),
                        **({"words": dict(p.words)} if p.words else {})}
                       for p in s.props]}
            for s in SUBJECTS.values()
            if (s.name in GRAPH_SUBJECTS) == graph]
