"""
survey.py: What a stored order of a plan says each field was read in.

The order of a plan's pieces for each field is made and kept by
`addressed.Orders` (`survey/<document>[.<scope>].json`, owner decisions
2026-11-08). The passes over a stored harvest read from these files which
passages each field was read in (`surveyed.surveyed_owners`), the files of
older harvests included, which also kept what their survey said of a
passage's frame.

Author: Felix Vossel
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Answer:
    """The fields one passage is read for. *tuples* and *dropped* are what a
    stored survey of an older flow said of the passage's frame, read back by
    the passes over its harvest."""
    owner: tuple
    parameters: list
    tuples: dict = field(default_factory=dict)     # group -> [tuple]
    dropped: list = field(default_factory=list)


@dataclass
class Found:
    """The passages of one document each field is read in."""
    complete: bool
    answers: dict = field(default_factory=dict)    # owner -> Answer
    unanswered: list = field(default_factory=list)
    # field uri -> its owners best first; a field without one is read in
    # the plan's order.
    order: dict = field(default_factory=dict)

    def passages_of(self, parameter: str) -> list:
        """The owners *parameter* is read in: best first where they were
        ranked, else in document order."""
        named = [owner for owner, answer in self.answers.items()
                 if parameter in answer.parameters]
        ranked = self.order.get(parameter)
        if not ranked:
            return named
        held = set(named)
        first = [tuple(owner) for owner in ranked if tuple(owner) in held]
        rest = [owner for owner in named if owner not in set(first)]
        return first + rest
