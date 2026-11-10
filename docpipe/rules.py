"""
rules.py: The rules a run follows, read from a file of the profile.

Every rule of the reading that is a value stood in the code until
2026-11-10: a number ("a quote has at least 8 characters"), a switch, a
choice ("the documents write the decimal with a comma"), a list of words or
characters ("the abbreviations whose point ends no sentence"), a table. Since
then each stands in a file of the profile, beside its spec, its prompts and
its flow, so that `docpipe edit` shows and sets it in the tab it belongs to
(owner, 2026-11-10: "Alle Regeln etc. sollen auch immer über die GUI
Editierbar sein"):

    <profile folder>/rules.json

The code knows of each rule its name, its kind, its bounds and what it does
with it (`RULES`); its value stands in the file and nowhere in the code. The
default profile's file names every rule of the core. A profile that extends
it writes only the rules it sets differently, laid over the default's rule by
rule, as the numbers of its flow are (`flow.py`). A profile whose own code
follows rules the core does not know declares them (`profiles/<name>/
rules.py: RULES`), and its file is the one they start from. A rule that has
a setting (`Rule.env`) is set by it where it is set: the environment, then
the project file, then the file.

A run reads with the rules of its profile (`use`; `current` takes the
ambient profile's where no run said which). Nothing here decides whether a
harvest is current: a pass names the sha256 of its rules in its entry of the
stamp for a reader, as it names its prompts and its flow (owner decision
2026-09-10: a stamp rests on the questions of the spec alone).

Author: Felix Vossel
"""
from __future__ import annotations

import difflib
import hashlib
import json
import os
import threading
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

FILE = "rules.json"
DEFAULT_NAME = "default"
DEFAULT = Path(__file__).resolve().parent / "builtin" / DEFAULT_NAME / FILE

# The tabs of `docpipe edit` a rule stands in.
TABS = ("spec", "prompts", "flow", "sources", "graph")
# What a rule's value is.
KINDS = ("whole", "number", "switch", "choice", "text", "chars", "texts",
         "map", "table", "range")


class RuleError(ValueError):
    """A rules file or a value a run cannot read. It names the file or the
    rule."""


@dataclass(frozen=True)
class Rule:
    """One rule a run follows: what the code knows of it."""
    name: str
    tab: str
    group: str
    kind: str
    help: str
    least: Optional[float] = None
    most: Optional[float] = None
    choices: tuple = ()
    columns: tuple = ()             # a table's columns
    of: str = "text"                # a map's values: text, texts or whole
    empty: bool = False             # an empty text, list or map; no range
    env: Optional[str] = None       # the setting that wins over the file
    env_flag: tuple = ()            # (the value where that setting is off,
                                    # where it is on): a setting that is a
                                    # flag and stands for one of two values
    decided: str = ""               # the owner's decisions that set it
    where: str = ""                 # where the code applies it


def rule(name, tab, group, kind, help, **more) -> Rule:
    return Rule(name, tab, group, kind, help, **more)


_r = rule

# Every rule of the core, in the order a file writes them and a tab shows
# them. What each is stands in the default profile's file.
RULES = (
    # -- spec: what backs a value -----------------------------------------------
    _r("quote_min_chars", "spec", "What backs a value", "whole",
       "Characters a quote has at least, so that it names a place; a "
       "shorter quote is widened with the lines around it where the reading "
       "shows them, and refused where it stays shorter.", least=1,
       where="verify.py, units.py (short_quote)"),
    _r("word_joiners", "spec", "What backs a value", "chars",
       "Characters that join a name or a number to more of itself: a "
       "wording beside a letter or a digit, or beside one of these and then "
       "a letter or a digit, is part of a longer name (\"OECD\" does not "
       "stand in \"non-OECD\").", empty=True, where="verify.py (_alone)"),
    _r("minus_signs", "spec", "What backs a value", "chars",
       "The signs of a negative number as a document prints them and a "
       "model retypes them; a printed sign is part of the number (\"-1.155\" "
       "backs -1155, \"1.155\" does not).", decided="2026-11-01",
       where="verify.py (numbers_in, canonical_number)"),
    _r("dotted_date_year", "spec", "What backs a value", "switch",
       "Whether the year at the end of a dotted date (\"Stand 09.12.2025\") "
       "stands in a quote as the year it prints.",
       where="verify.py (numbers_in)"),
    _r("same_characters", "spec", "What backs a value", "map",
       "Characters a quote and its source are compared as: quotation marks "
       "and dashes a PDF prints and a model retypes, the thin spaces, the "
       "soft hyphen (to nothing). Both sides are brought into this one "
       "shape before the check runs; it is not a check.", empty=True,
       where="verify.py (flat)"),
    # -- spec: numbers and years -------------------------------------------------
    _r("decimal_mark", "spec", "Numbers and years", "choice",
       "How the documents write the decimal. It decides only what the digits "
       "leave open: \"3,251\" is 3.251 with the comma and 3251 with the "
       "point.", choices=(",", "."), where="verify.py (decimal_mark)"),
    _r("year_range", "spec", "Numbers and years", "range",
       "The years a year of a value can be; a number outside is no year "
       "(a zone number like 169002). Empty: every number.", empty=True,
       decided="2026-11-01", where="pipeline.py (year rules)"),
    _r("year_words", "spec", "Numbers and years", "range",
       "The years a text is searched for where it names a year in words or "
       "a span (\"bis 2045\").", decided="2026-11-07",
       where="addressed.py (years_in)"),
    _r("unit_factor_places", "spec", "Numbers and years", "whole",
       "Decimal places a value keeps when it is converted into its field's "
       "unit.", least=0, where="verify.py (_check_value)"),
    _r("year_by_plan_word", "spec", "Numbers and years", "switch",
       "Whether a year the quote does not print is read where it is one of "
       "the plan's base or target years and the quote carries the plan's "
       "word for that state (\"Basisjahr\", \"Zieljahr\").",
       decided="2026-09-22, 2026-10-06", where="pipeline.py (named_year)"),
    # -- spec: lists and wordings ------------------------------------------------
    _r("wording_most_chars", "spec", "Lists and wordings", "whole",
       "Characters a wording that differs from its chosen entry keeps at "
       "most; it is kept in whole words and counted.", least=1,
       where="pipeline.py (_raw_foreign)"),
    # -- spec: spans and groups --------------------------------------------------
    _r("span_words", "spec", "Spans and groups", "texts",
       "Words that make a span of years with a later year (\"bis 2045\"): "
       "the value is read for every year of the span.", empty=True,
       decided="2026-11-07", where="addressed.py (span)"),
    _r("span_dashes", "spec", "Spans and groups", "chars",
       "Dashes that make a span of years between two years (\"2030-2045\").",
       empty=True, decided="2026-11-07", where="addressed.py (span)"),
    _r("span_marks", "spec", "Spans and groups", "map",
       "What every row of a value for a span of years is marked with, "
       "coordinate -> entry.", empty=True, decided="2026-11-07",
       where="runner.py (span rows)"),
    # -- spec: where the spec is silent -----------------------------------------
    _r("default_takes_group", "spec", "Where the spec is silent", "switch",
       "Whether words for several entries (\"all scenarios\") become one row "
       "per member where the field does not say.", decided="2026-11-08",
       where="spec.py (Parameter), addressed.py"),
    _r("description_least_words", "spec", "Where the spec is silent",
       "whole", "Words a field's description has at least.", least=0,
       where="spec.py (load)"),
    _r("example_least_words", "spec", "Where the spec is silent", "whole",
       "Words the passage of a field's example has at least.", least=0,
       where="spec.py (load)"),
    # -- prompts: how a place is shown ------------------------------------------
    _r("lines_around", "prompts", "How a place is shown", "whole",
       "Lines a request shows before and after the line of a value in text; "
       "a table shows the value's own row under its head.", least=0,
       decided="2026-11-08", where="addressed.py (show_value)"),
    _r("letter_title_page", "prompts", "How a place is shown", "text",
       "The letter the title page is shown under.", decided="2026-11-08",
       where="units.py"),
    _r("letter_headings", "prompts", "How a place is shown", "text",
       "The letter the headings are shown under.", decided="2026-11-08",
       where="units.py"),
    _r("letter_settings", "prompts", "How a place is shown", "text",
       "The letter what the document settles is shown under.",
       decided="2026-11-08", where="units.py"),
    _r("letters_others", "prompts", "How a place is shown", "chars",
       "The letters other pieces are shown under, in order; the three "
       "letters above are left out.", decided="2026-11-08",
       where="units.py"),
    _r("head_joiner", "prompts", "How a place is shown", "text",
       "What joins the words of a table's head over one cell.",
       where="units.py (head_of)"),
    # -- prompts: examples -------------------------------------------------------
    _r("example_words", "prompts", "Examples", "text",
       "What an example answer writes as its words.",
       decided="2026-11-06, 2026-11-07", where="fields.py"),
    _r("example_year", "prompts", "Examples", "text",
       "What an example answer writes as a year.", decided="2026-11-06",
       where="fields.py"),
    _r("example_cell", "prompts", "Examples", "whole",
       "The cell of a table row an example answer names.", least=1,
       decided="2026-11-09", where="addressed.py (first_address)"),
    # -- prompts: where the prompt says nothing ---------------------------------
    _r("temperature", "prompts", "Where the prompt says nothing", "number",
       "The temperature of a request whose prompt names none.", least=0,
       most=2, where="runner.py"),
    _r("max_tokens", "prompts", "Where the prompt says nothing", "whole",
       "The answer length of a request whose prompt names none.", least=1,
       where="runner.py"),
    _r("max_tokens_phrase", "prompts", "Where the prompt says nothing",
       "whole", "The answer length of a search sentence whose prompt names "
       "none.", least=1, where="runner.py (phrase)"),
    _r("max_tokens_review", "prompts", "Where the prompt says nothing",
       "whole", "The answer length of a second reading whose prompt names "
       "none.", least=1, where="runner.py (review)"),
    _r("max_tokens_compute", "prompts", "Where the prompt says nothing",
       "whole", "The answer length of a calculation whose prompt names "
       "none.", least=1, where="runner.py (compute)"),
    _r("retry_temperature_step", "prompts", "Where the prompt says nothing",
       "number", "How much each reply that could not be read raises the "
       "temperature of the next attempt.", least=0,
       env="EXTRACT_RETRY_TEMPERATURE_STEP", where="runner.py"),
    _r("retry_temperature_most", "prompts", "Where the prompt says nothing",
       "number", "The highest temperature an attempt is raised to.",
       least=0, most=2, where="runner.py"),
    _r("image_max_side", "prompts", "Where the prompt says nothing", "whole",
       "Pixels the longer side of a figure's image is sent with at most.",
       least=28, env="EXTRACT_IMAGE_MAX_SIDE", decided="2026-11-08",
       where="runner.py"),
    _r("heading_in_front_chars", "prompts", "Where the prompt says nothing",
       "whole", "A source's heading is put in front of its text unless it "
       "stands in its first this many characters.", least=0,
       where="runner.py"),
    # -- flow: pieces ------------------------------------------------------------
    _r("sentence_marks", "flow", "Pieces", "chars",
       "Marks that end a sentence where a capital or a digit follows.",
       decided="2026-11-08", where="units.py"),
    _r("abbreviations", "flow", "Pieces", "texts",
       "Abbreviations whose point ends no sentence, as the documents print "
       "them.", empty=True, decided="2026-11-08", where="units.py"),
    _r("title_page_also", "flow", "Pieces", "whole",
       "The page whose first lines are the title page where the first page "
       "has none.", least=1, decided="2026-11-08", where="units.py"),
    # -- flow: search ------------------------------------------------------------
    _r("rerank", "flow", "Search", "switch",
       "Whether the reranker orders the pieces of a search once, with the "
       "search sentence; without it they stay in the document's order.",
       decided="2026-11-06, 2026-11-08", where="addressed.py"),
    _r("fetches", "flow", "Search", "texts",
       "What a reply may fetch itself beside the pieces shown: the next or "
       "the previous piece, a table or figure it names, a search for a "
       "pattern, the pieces like one shown. Fetched pieces do not count "
       "against the search's pieces.",
       choices=("next", "previous", "item", "search", "similar"), empty=True,
       decided="2026-11-07, 2026-11-09", where="addressed.py"),
    _r("question_as_sentence", "flow", "Search", "switch",
       "Whether a search sentence that is a question is taken (and "
       "counted), or the search runs with the field's own sentence "
       "instead.", decided="2026-11-08", where="addressed.py"),
    # -- flow: asking again and giving up ---------------------------------------
    _r("retry_wait_s", "flow", "Asking again and giving up", "number",
       "Seconds per attempt waited after a reply that could not be read.",
       least=0, env="EXTRACT_RETRY_WAIT", where="runner.py"),
    _r("retry_wait_most_s", "flow", "Asking again and giving up", "number",
       "Seconds waited at most after a reply that could not be read.",
       least=0, env="EXTRACT_RETRY_WAIT_MAX", where="runner.py"),
    _r("transport_wait_s", "flow", "Asking again and giving up", "number",
       "Seconds waited after the first failure to reach the server, doubled "
       "each time.", least=0, env="EXTRACT_TRANSPORT_WAIT",
       where="runner.py"),
    _r("transport_wait_most_s", "flow", "Asking again and giving up",
       "number", "Seconds waited at most between two attempts to reach the "
       "server.", least=0, env="EXTRACT_TRANSPORT_WAIT_MAX",
       where="runner.py"),
    _r("repeat_timeout_s", "flow", "Asking again and giving up", "number",
       "Seconds a repeated request waits for its answer.", least=1,
       env="EXTRACT_RETRY_TIMEOUT", where="runner.py"),
    _r("server_dead_after_s", "flow", "Asking again and giving up",
       "number", "Seconds without an answer from the server after which the "
       "run halts.", least=1, env="EXTRACT_SERVER_DEAD_AFTER",
       where="runner.py"),
    _r("server_probe_every_s", "flow", "Asking again and giving up",
       "number", "Seconds between two probes of a server that does not "
       "answer.", least=1, where="runner.py"),
    _r("unreachable_share", "flow", "Asking again and giving up", "number",
       "Share of a document's sources that never reached the server above "
       "which the document counts as not read.", least=0, most=1,
       where="runner.py"),
    _r("least_answer_tokens", "flow", "Asking again and giving up", "whole",
       "Tokens a request must leave its answer at least, or it is not sent.",
       least=1, where="runner.py"),
    # -- flow: reading again -----------------------------------------------------
    _r("question_keys", "flow", "Reading again", "texts",
       "The keys of a stamp that decide whether a document is read again: "
       "a changed question of the spec under one of them. Model, prompts, "
       "flow and rules are never compared.", decided="2026-09-10",
       where="runner.py (stale)"),
    # -- flow: calculation -------------------------------------------------------
    _r("code_rounds", "flow", "Calculation", "whole",
       "Runs of code a calculation question gets at most.", least=1,
       env="EXTRACT_CODE_ROUNDS", decided="2026-11-03", where="runner.py"),
    _r("code_output_chars", "flow", "Calculation", "whole",
       "Characters of a code run's output the model is shown.", least=1,
       where="runner.py"),
    _r("compute_shown", "flow", "Calculation", "map",
       "How many of each kind the gathering tools of a calculation show: "
       "sections, tables, figures.", of="whole", decided="2026-11-04",
       where="reading.py"),
    # -- flow: documents ---------------------------------------------------------
    _r("largest_first", "flow", "Documents", "switch",
       "Whether the documents of a run are read largest first; otherwise in "
       "the order of their names.", where="runner.py"),
    _r("same_request_once", "flow", "Documents", "switch",
       "Whether a request a document has already sent word for word is "
       "answered from the first.", decided="2026-11-07",
       where="scheduler.py"),
)
BY_NAME = {one.name: one for one in RULES}
if len(BY_NAME) != len(RULES):
    raise AssertionError("rules.RULES names a rule twice")
for _one in RULES:
    if _one.tab not in TABS or _one.kind not in KINDS:
        raise AssertionError(f"rules.RULES: {_one.name} has no tab or kind "
                             f"of this module")


@dataclass(frozen=True)
class Rules:
    """The rules one run reads with, and where each comes from."""
    values: dict                    # name -> value, in the order of RULES
    owners: dict                    # name -> "rules.json of <profile>" or
                                    #         what set its setting
    files: tuple = ()               # ((profile name, path)), farthest first
    sha256: str = ""                # of the files' rules, settings left out
    state: str = ""                 # of the values in effect, settings in

    def __getitem__(self, name: str):
        try:
            return self.values[name]
        except KeyError:
            raise RuleError(f"{name!r} is no rule"
                            f"{_nearest(name, self.values)}") from None

    def get(self, name: str, default=None):
        return self.values.get(name, default)


# -- one value -------------------------------------------------------------------

def _nearest(name, known) -> str:
    close = difflib.get_close_matches(str(name), list(known), n=3, cutoff=0.6)
    return f" (did you mean {', '.join(close)}?)" if close else ""


def problem(name: str, value, known: Optional[dict] = None) -> Optional[str]:
    """Why *value* is not the rule *name*, None where it is. *known* are
    the rules the profile's line knows (`registry`), the core's where not
    given."""
    known = BY_NAME if known is None else known
    one = known.get(name)
    if one is None:
        return f"{name!r} is no rule{_nearest(name, known)}"
    kind = one.kind

    def bounded(number) -> Optional[str]:
        if one.least is not None and number < one.least:
            return f"{name} must be at least {one.least:g}, not {number}"
        if one.most is not None and number > one.most:
            return f"{name} must be at most {one.most:g}, not {number}"
        return None
    if kind == "whole":
        if isinstance(value, bool) or not isinstance(value, int):
            return f"{name} must be a whole number, not {value!r}"
        return bounded(value)
    if kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return f"{name} must be a number, not {value!r}"
        return bounded(value)
    if kind == "switch":
        if not isinstance(value, bool):
            return f"{name} must be true or false, not {value!r}"
        return None
    if kind == "choice":
        if value not in one.choices:
            return (f"{name} must be one of "
                    f"{', '.join(repr(c) for c in one.choices)}, not "
                    f"{value!r}")
        return None
    if kind in ("text", "chars"):
        if not isinstance(value, str):
            return f"{name} must be a text, not {value!r}"
        if not value and not one.empty:
            return f"{name} must not be empty"
        if kind == "chars" and len(set(value)) != len(value):
            return f"{name} names a character twice: {value!r}"
        return None
    if kind == "texts":
        if not isinstance(value, list) \
                or not all(isinstance(part, str) and part for part in value):
            return f"{name} must be a list of texts, none of them empty"
        if not value and not one.empty:
            return f"{name} must not be empty"
        if len(set(value)) != len(value):
            return f"{name} names an entry twice"
        stray = [part for part in value
                 if one.choices and part not in one.choices]
        if stray:
            return (f"{name}: {', '.join(stray)} is none of "
                    f"{', '.join(one.choices)}")
        return None
    if kind == "map":
        if not isinstance(value, dict) or not all(
                isinstance(key, str) and key for key in value):
            return f"{name} must be an object of named entries"
        if not value and not one.empty:
            return f"{name} must not be empty"
        for key, part in value.items():
            if one.of == "texts":
                good = isinstance(part, list) and all(
                    isinstance(word, str) and word for word in part)
                said = "a list of texts"
            elif one.of == "whole":
                good = isinstance(part, int) and not isinstance(part, bool) \
                    and part >= 0
                said = "a whole number of at least 0"
            else:
                good = isinstance(part, str)
                said = "a text"
            if not good:
                return f"{name}: {key!r} must be {said}, not {part!r}"
        return None
    if kind == "table":
        if not isinstance(value, list):
            return f"{name} must be a list of rows"
        for row in value:
            if not isinstance(row, dict) or set(row) != set(one.columns) \
                    or not all(isinstance(cell, str) for cell in row.values()):
                return (f"{name}: every row has the texts "
                        f"{', '.join(one.columns)}, not {row!r}")
        if not value and not one.empty:
            return f"{name} must not be empty"
        return None
    if kind == "range":
        if value is None:
            return None if one.empty else f"{name} must be two numbers"
        if not (isinstance(value, list) and len(value) == 2
                and all(isinstance(part, int) and not isinstance(part, bool)
                        for part in value)):
            return f"{name} must be two whole numbers or empty, not {value!r}"
        if value[0] > value[1]:
            return f"{name}: {value[0]} is after {value[1]}"
        return None
    return f"{name} is of no kind this module reads"


def checked(where, name: str, value, known: Optional[dict] = None):
    said = problem(name, value, known)
    if said is not None:
        raise RuleError(f"{where}: {said}")
    return value


# How a setting that is a flag says "off"; any other spelling is "on".
OFF = ("0", "false", "no", "off", "")


def _setting(one: Rule, raw: str):
    """The value of a rule as its setting spells it: a number, a text, one of
    its choices, or, for a setting that is a flag (`env_flag`), the value
    the flag stands for."""
    if one.env_flag:
        value = one.env_flag[raw.strip().lower() not in OFF]
    elif one.kind in ("text", "choice"):
        value = raw.strip()
    else:
        try:
            value = int(raw.strip()) if one.kind == "whole" else float(raw)
        except ValueError:
            raise RuleError(f"{one.env} must be a number, not {raw!r}") \
                from None
    said = problem(one.name, value, {one.name: one})
    if said is not None:
        raise RuleError(f"{one.env}: {said}")
    return value


# -- the files ---------------------------------------------------------------------

def declared(profile) -> list:
    """[(profile name, its own rules, the file beside them)] of *profile*'s
    line, farthest first: the rules a profile declares for its own code
    (`profiles/<name>/rules.py: RULES`), which the core does not know, and
    the rules.json beside that module, which they start from."""
    if profile is None or not callable(getattr(profile, "lineage", None)):
        return []
    out = []
    for one in reversed(profile.lineage()):
        own = one.own("rules", "RULES") if hasattr(one, "own") else None
        if own:
            import importlib
            module = importlib.import_module(
                f"profiles.{one.name}.rules")
            beside = Path(module.__file__).resolve().parent / FILE
            out.append((one.name, tuple(own), beside))
    return out


def registry(profile=None) -> dict:
    """{name: Rule} of every rule a run of *profile* reads: the core's and
    those its line declares, in the order a file writes them."""
    known = dict(BY_NAME)
    for owner, own, _beside in declared(profile):
        for one in own:
            if not isinstance(one, Rule):
                raise RuleError(f"profile {owner!r} declares {one!r}, which "
                                f"is no Rule")
            if one.name in known:
                raise RuleError(f"profile {owner!r} declares the rule "
                                f"{one.name!r} again")
            if one.tab not in TABS or one.kind not in KINDS:
                raise RuleError(f"profile {owner!r}: {one.name} has no tab "
                                f"or kind this module reads")
            known[one.name] = one
    return known


def parse(raw: str, where, known: Optional[dict] = None,
          needed: tuple = ()) -> dict:
    """{name: value} of the text *raw*, read strictly against the rules
    *known* (the core's where not given). *needed* are the rules the file
    has to name: those it is the first file of."""
    known = BY_NAME if known is None else known

    def once(pairs: list) -> dict:
        out: dict = {}
        for key, value in pairs:
            if key in out:
                raise RuleError(f"{where}: {key!r} stands twice")
            out[key] = value
        return out
    try:
        data = json.loads(raw, object_pairs_hook=once)
    except RuleError:
        raise
    except ValueError as exc:
        raise RuleError(f"{where}: {exc}") from exc
    if not isinstance(data, dict) or set(data) - {"rules"}:
        raise RuleError(f"{where}: a rules file is one JSON object with "
                        f"\"rules\", the name of a rule -> its value")
    rules = data.get("rules", {})
    if not isinstance(rules, dict):
        raise RuleError(f"{where}: rules must be an object, the name of a "
                        f"rule -> its value")
    read = {name: checked(where, name, value, known)
            for name, value in rules.items()}
    missing = [name for name in needed if name not in read]
    if missing:
        raise RuleError(f"{where}: names no {', '.join(missing)}; this is "
                        f"the file these rules start from")
    return read


def dump(rules: dict, newline: str = "\n", known: Optional[dict] = None) \
        -> str:
    """A rules file's text in the one form it is written in: the rules in
    the order of the registry."""
    known = BY_NAME if known is None else known
    ordered = {name: rules[name] for name in known if name in rules}
    ordered.update({name: value for name, value in rules.items()
                    if name not in ordered})
    text = json.dumps({"rules": ordered}, ensure_ascii=False, indent=2) + "\n"
    # A character nobody sees (a thin space, the soft hyphen) is written as
    # its code, so that the file says which it is.
    text = "".join(f"\\u{ord(ch):04x}" if ch != " " and
                   unicodedata.category(ch) in ("Zs", "Cf", "Zl", "Zp")
                   else ch for ch in text)
    return text if newline == "\n" else text.replace("\n", newline)


def path_of(profile) -> Path:
    return Path(profile.package_dir) / FILE


def line(profile) -> list:
    """[(profile name, path)] of the files a profile's rules can stand in,
    nearest first, the default's last."""
    if profile is None or getattr(profile, "package_dir", None) is None:
        return [(DEFAULT_NAME, DEFAULT)]
    lineage = getattr(profile, "lineage", None)
    profiles = lineage() if callable(lineage) else [profile]
    out = [(one.name, path_of(one)) for one in profiles]
    if not any(Path(path) == DEFAULT for _, path in out):
        out.append((DEFAULT_NAME, DEFAULT))
    return out


_loaded: dict = {}
_LOADED_KEPT = 16


def _merged(profile, skip_own: bool = False) -> tuple:
    """(values, owners, files, sha256) of *profile*'s rules files: the
    default's names every rule of the core, the file beside the rules a
    profile declares names every one of them, and every file of the
    profile's line is laid over the farther ones rule by rule. *skip_own*
    leaves the profile's own file and its own rules out: what it has where
    its own file says nothing."""
    known = registry(profile)
    places = line(profile)
    mine = places[0][0]
    starts = declared(profile)
    if skip_own:
        places = places[1:]
        for owner, own, _beside in starts:
            if owner == mine:
                for one in own:
                    known.pop(one.name, None)
        starts = [start for start in starts if start[0] != mine]
    order: list = [(DEFAULT_NAME, DEFAULT, tuple(BY_NAME))]
    placed = {Path(path).resolve() for _, path in places
              if Path(path).is_file()}
    for owner, own, beside in starts:
        if beside.resolve() not in placed:
            order.append((owner, beside, tuple(one.name for one in own)))
    first_of = {owner: tuple(one.name for one in own)
                for owner, own, beside in starts
                if beside.resolve() in placed}
    for name, path in reversed(places):
        if Path(path) == DEFAULT:
            continue
        order.append((name, Path(path), first_of.get(name, ())))
    present = [(name, Path(path), needed) for name, path, needed in order
               if Path(path).is_file()]
    key = (skip_own, tuple(known), tuple(
        (str(path), path.stat().st_mtime_ns, path.stat().st_size)
        for _, path, _needed in present))
    if key in _loaded:
        return _loaded[key]
    if not present or present[0][1] != DEFAULT:
        raise RuleError(f"{DEFAULT} is missing: the rules start from it")
    values: dict = {}
    owners: dict = {}
    for name, path, needed in present:
        for one, value in parse(path.read_text(encoding="utf-8"), path,
                                known, needed).items():
            values[one], owners[one] = value, name
    lost = [name for name in known if name not in values]
    if lost:
        raise RuleError(f"no rules file names {', '.join(lost)}: the file "
                        f"beside the rules a profile declares is the one they "
                        f"start from")
    values = {name: values[name] for name in known}
    sha = hashlib.sha256(json.dumps(values, ensure_ascii=False,
                                    sort_keys=True).encode("utf-8")
                         ).hexdigest()
    made = (values, owners, tuple((name, path) for name, path, _ in present),
            sha)
    while len(_loaded) >= _LOADED_KEPT:
        _loaded.pop(next(iter(_loaded)))
    _loaded[key] = made
    return made


def load(profile=None, environ=None) -> Rules:
    """The rules of *profile* (the default's where None): its files laid
    over each other, and over them the settings that are set (*environ*,
    the environment where not given)."""
    values, owners, files, sha = _merged(profile)
    values = dict(values)
    owners = {name: f"{FILE} of {owner}" for name, owner in owners.items()}
    own = environ is None
    environ = os.environ if own else environ
    for one in registry(profile).values():
        raw = environ.get(one.env) if one.env else None
        if raw is not None:
            values[one.name] = _setting(one, raw)
            if own:
                from . import settings
                owners[one.name] = settings.origin(one.env)
            else:
                owners[one.name] = "environment"
    return Rules(values, owners, files, sha, _state(values))


def _state(values: dict) -> str:
    return hashlib.sha256(json.dumps(values, ensure_ascii=False,
                                     sort_keys=True).encode("utf-8")
                          ).hexdigest()


def inherited(profile) -> Optional[Rules]:
    """The rules *profile* has where its own file says nothing, no setting
    applied: those of the files of the profiles it extends. None for the
    default profile."""
    if profile is None or len(line(profile)) < 2:
        return None
    values, owners, files, sha = _merged(profile, skip_own=True)
    return Rules(dict(values), {name: f"{FILE} of {owner}"
                                for name, owner in owners.items()},
                 files, sha, _state(values))


def default() -> Rules:
    """The default profile's rules, no setting applied."""
    return load(None, environ={})


# -- the rules a run reads with ---------------------------------------------------

_lock = threading.Lock()
# What a run took (`use`): (ambient profile name, Rules).
_taken: Optional[tuple] = None
# The ambient profile's rules, by (its name, the settings that win).
_ambient: dict = {}
_derived: dict = {}
ENVS = tuple(one.env for one in RULES if one.env)


def use(profile=None, environ=None) -> Rules:
    """Read with the rules of *profile* from here on, while it is the
    ambient profile (`DOCPIPE_PROFILE` names it); returned."""
    global _taken
    made = load(profile, environ)
    with _lock:
        _taken = (getattr(profile, "name", None) or "", made)
        _derived.clear()
    return made


def reset() -> None:
    """Forget the rules taken and read, so that the next read takes the
    files as they are now (for tests, and after a rules file was written)."""
    global _taken
    with _lock:
        _taken = None
        _ambient.clear()
        _derived.clear()
        _loaded.clear()
        _owned.clear()


def current() -> Rules:
    """The rules a run reads with: those a run took (`use`) for the
    ambient profile, else the ambient profile's (`DOCPIPE_PROFILE`), else
    the default's."""
    ambient = os.environ.get("DOCPIPE_PROFILE") or ""
    taken = _taken
    if taken is not None and taken[0] == ambient:
        return taken[1]
    key = (ambient, tuple(os.environ.get(env) for env in ENVS))
    made = _ambient.get(key)
    if made is None:
        from .profile import active_profile
        made = load(active_profile())
        with _lock:
            if len(_ambient) > 32:
                _ambient.clear()
            _ambient[key] = made
    return made


_owned: dict = {}


def get(name: str, owner: Optional[str] = None):
    """The value of the rule *name* in the rules a run reads with. A
    profile's own code names itself as *owner*: where the ambient profile's
    line does not declare the rule, it is *owner*'s (a test of the scenario
    profile's regions run under another ambient profile)."""
    rules = current()
    if owner is None or name in rules.values:
        return rules[name]
    key = (owner, tuple(os.environ.get(env) for env in ENVS))
    made = _owned.get(key)
    if made is None:
        from .profile import load_profile
        made = load(load_profile(owner))
        with _lock:
            _owned[key] = made
    return made[name]


def derived(key: str, build: Callable):
    """What *build* makes of the rules in effect, made once per state of
    the rules: a pattern compiled from a list of words."""
    slot = (key, current().state)
    made = _derived.get(slot)
    if made is None:
        made = build()
        with _lock:
            if len(_derived) > 512:
                _derived.clear()
            _derived[slot] = made
    return made


def of_tab(tab: str, profile=None) -> list:
    """The rules of *tab* a run of *profile* reads, in their order."""
    return [one for one in registry(profile).values() if one.tab == tab]


class overlaid:
    """The rules a run reads with, with *values* laid over them, while the
    block runs: for a test that wants one rule set otherwise.

        with rules.overlaid(year_range=None):
            ...
    """

    def __init__(self, **values):
        self.values = values

    def __enter__(self) -> Rules:
        global _taken
        base = current()
        for name, value in self.values.items():
            if name in BY_NAME:
                checked("overlaid", name, value)
        values = {**base.values, **self.values}
        made = Rules(values, {**base.owners,
                              **{name: "overlaid" for name in self.values}},
                     base.files, base.sha256, _state(values))
        with _lock:
            self._before = _taken
            _taken = (os.environ.get("DOCPIPE_PROFILE") or "", made)
            _derived.clear()
        return made

    def __exit__(self, *exc) -> None:
        global _taken
        with _lock:
            _taken = self._before
            _derived.clear()
