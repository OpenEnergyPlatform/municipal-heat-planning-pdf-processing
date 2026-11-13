"""
front.py: What a publication says of itself, and which reading of it goes
first (owner decisions 2026-11-05).

A publication prints its own title, authors, date and DOI on its first page
or on its title page. A chapter that presents other studies prints theirs,
and a reference list prints the DOIs it cites, so a value read anywhere else
may belong to another work. For these fields a reading on a front page goes
first; where there is none, the record the catalogue holds for the
publication (`completion.py`); only then a reading anywhere else. The
completion looks a field up wherever no front page gave it, and the graph
takes its value in this order (`kg.py`). The fields, which pages are front
pages and the order are graph rules (`front_first_fields`,
`front_pages_rule`, `front_pages_extra`, `front_order`), read when a
reading is placed.

Author: Felix Vossel
"""
from __future__ import annotations

from typing import Optional

from docpipe import graphfile
from docpipe.extraction import readings


def front_fields() -> tuple:
    """The fields a publication states about itself on its front pages: the
    rule `front_first_fields` of graph.json beside this file, as it stands
    now."""
    return tuple(graphfile.get("front_first_fields", "scenarios"))


def __getattr__(name: str):
    """`FRONT_FIELDS`, which this module had as a constant, as the rule says
    it now."""
    if name == "FRONT_FIELDS":
        return front_fields()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def page_of(row: dict) -> Optional[int]:
    """The page a row was read on, None where it names none."""
    return readings.page_of(row)


def front_pages(titles: list) -> set:
    """The front pages, as the graph rules `front_pages_rule` and
    `front_pages_extra` say (`readings.front_pages`)."""
    return readings.front_pages(
        titles, which=graphfile.get("front_pages_rule", "scenarios"),
        extra=graphfile.get("front_pages_extra", "scenarios"))


def looked_up(row: dict) -> bool:
    """Whether *row* holds a value looked up outside the document."""
    return readings.looked_up(row)


def read_in_front(rows: list, front: set) -> list:
    """The rows of *rows* read on one of the *front* pages."""
    return readings.read_in_front(rows, front)


def in_order(rows: list, front: set) -> list:
    """The readings of a front field that count, in the order the graph
    rule `front_order` says (`readings.in_order`)."""
    return readings.in_order(
        rows, front, graphfile.get("front_order", "scenarios"))
