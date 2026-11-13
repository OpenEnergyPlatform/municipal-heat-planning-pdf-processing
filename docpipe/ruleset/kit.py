"""
kit.py: what a rule is, the tabs and kinds of a rule, and the kinds of
steps that read rules.

The modules of the ruleset make their rules with `rule` while rules.py
gathers them, so they import these from here and nothing of docpipe:
whichever of them is imported first, neither waits for the other.
rules.py names them again, as it always did.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# The tabs of `docpipe edit` a rule stands in.
TABS = ("spec", "prompts", "flow", "sources", "graph")
# What a rule's value is.
KINDS = ("whole", "number", "switch", "choice", "text", "chars", "texts",
         "map", "table", "range")


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
    steps: tuple = ()               # the kinds of steps that read it
                                    # (`step_kind`): a value at one of them
                                    # is a value of its own there
    machine: bool = False           # a value of the machine (a server's
                                    # address, a path): never in a file of
                                    # the repo, set at the start or in the
                                    # project file
    secret: bool = False            # a key: set at the start only (.env),
                                    # never shown, never written


def rule(name, tab, group, kind, help, **more) -> Rule:
    return Rule(name, tab, group, kind, help, **more)


# The kinds of steps (`step_kind`) that send a request to the model.
ASKING = ("transcribe", "sentences", "order", "docfield", "works", "find",
          "coord", "quantity", "work_coordinate", "phrase", "search",
          "last_year", "names", "about", "compute", "review", "example",
          "list")
# Those whose request shows lines of the document.
SHOWING = ("sentences", "order", "docfield", "works", "find", "coord",
           "quantity", "work_coordinate", "phrase", "search", "last_year",
           "names", "about", "list")
# The steps of a pass over a stored harvest that take an answer, or hold a
# stored one, to its quote: a dimension taken back and read again, the new
# answer where it is better, the parameters and the passages read for the
# first time, the quotes checked again, the second reading.
PASS_TAKING = ("take_back", "better", "read_parameters", "unread",
               "recheck", "review")
# Those that take an answer and hold it to its quote, and the writing that
# holds every value to it once more.
TAKING = ("docfield", "works", "find", "coord", "quantity",
          "work_coordinate", "search", "last_year", "names", "about",
          "settle", "write", "list") + PASS_TAKING
# The general steps of a flow (owner decision 2026-11-12) and the steps
# whose work each does: it reads the rules they read for that work, so a
# value set at one of them can be set at the general step too. A question
# to the model does the asking of every step whose request shows lines of
# the document; a search and an order by a text do the searching of the
# steps that search, and read the rules of the search only (`SEARCH_GROUP`).
STANDS_FOR = {"ask": SHOWING}
SEARCH_STANDS_FOR = {"retrieve": ("order", "search"),
                     "rerank": ("order", "search")}
# The group of the rules of the search, on the Flow tab.
SEARCH_GROUP = "Search"


def with_general(steps: tuple, searching: bool = False) -> tuple:
    """*steps* and every general step that does the work of one of them:
    the asking (`STANDS_FOR`), and the searching for a rule of the search
    (*searching*, `SEARCH_STANDS_FOR`)."""
    table = {**STANDS_FOR, **(SEARCH_STANDS_FOR if searching else {})}
    more = tuple(general for general, kinds in table.items()
                 if general not in steps and set(kinds) & set(steps))
    return tuple(steps) + more


# The steps that write rows into the harvest: the writing of a run, and the
# steps of a pass that replace the file or append rows to it.
WRITING = ("write", "replace", "read_parameters", "unread")
# Those that grade a row's trust, and the steps that write what they grade.
TRUSTING = ("write", "replace", "review", "summary")
