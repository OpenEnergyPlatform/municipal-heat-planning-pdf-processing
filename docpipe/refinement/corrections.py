"""
edits.py – Apply a model's edit list to a section, and refuse the ones that
do not hold up.

The refinement stage used to have the model hand back the whole section. It is
mostly retyping: over 60 ar6 documents, 28% of sections came back byte-identical
and the median similarity was 99%, while only 166 of 4887 sections were real
conversions. The expensive half of an LLM call is the part it writes, so the
stage paid its worst resource to copy text.

Asking for the changes instead is cheap — and unsafe unless every one of them
is checked against the original first. A find/replace the model half-remembered
would otherwise rewrite a sentence nobody asked it to touch, or match in two
places and change the wrong one. Nothing here is applied on trust:

  * the text to find must be present, exactly once, in the section AS THE MODEL
    RECEIVED IT — the only text it can honestly be quoting;
  * where two corrections cover the same passage, the longer one wins and the
    other is reported as overlapping;
  * an edit may not add, drop or alter a [pN_tblM] / [pN_imgM] placeholder;
  * the edits together may not remove more than MAX_SHRINK of the section.

The first two rules used to be one: each find was looked up in the text left by
its predecessors. That quietly punished the prompt for working. The model is
told to quote whole sentences so that a quote is unique, which makes two fixes
to one sentence overlap by construction — and the second then failed to find an
anchor its predecessor had just rewritten, and was reported as text that was
never in the document. It was; it had been edited away moments earlier. Of 4828
corrections on one book, 1144 were refused that way.

A rejected edit is dropped and reported, never guessed at. If the caller sees
anything in `rejected`, the honest move is to keep the original section — the
model's picture of it evidently did not match.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# A placeholder stands for a table or figure that lives in its own file. Losing
# one silently detaches an image from the text that explains it.
PLACEHOLDER_RE = re.compile(r"\[p\d+_(?:img|tbl)\d+\]")

# An edit list is meant to fix artefacts, not to rewrite the section. Removing
# more than this much of it means the model is doing something other than what
# it was asked, and the section is safer untouched.
MAX_SHRINK = 0.30


@dataclass
class CorrectionReport:
    applied: int = 0
    rejected: list = field(default_factory=list)   # (find, reason)

    @property
    def ok(self) -> bool:
        return not self.rejected


_WS_RE = re.compile(r"\s+")


def _placeholders(text: str) -> list:
    return PLACEHOLDER_RE.findall(text or "")


def _loose_hits(text: str, find: str) -> int:
    """How often *find* occurs when runs of whitespace are treated as equal.

    Purely diagnostic. A model that retypes a quote tends to normalise double
    spaces and line breaks on the way, and a literal lookup then misses a
    passage that is plainly there. Counting those separately is what tells us
    whether the refusals are a quoting habit or an invention.
    """
    return _WS_RE.sub(" ", text).count(_WS_RE.sub(" ", find))


def apply_corrections(original: str, edits) -> tuple:
    """(text, CorrectionReport). *original* is returned unchanged for any edit that
    fails its check — the caller decides what to do about a non-empty report."""
    report = CorrectionReport()
    if not isinstance(original, str):
        report.rejected.append((None, "section content is not text"))
        return original, report
    if not isinstance(edits, list):
        report.rejected.append((None, f"edits is {type(edits).__name__}, not a list"))
        return original, report

    located = []
    for edit in edits:
        if not isinstance(edit, dict):
            report.rejected.append((None, "edit is not an object"))
            continue
        find = edit.get("find")
        replace = edit.get("replace")
        if not isinstance(find, str) or not find:
            report.rejected.append((find, "empty find"))
            continue
        if replace is None:
            replace = ""
        if not isinstance(replace, str):
            report.rejected.append((find, "replace is not text"))
            continue

        hits = original.count(find)
        if hits == 0:
            # The model quoted something the section does not contain. Say WHY,
            # not just that: a miss that a whitespace-insensitive search would
            # have found is a quoting habit and calls for a tolerant match; a
            # miss that stays missing is invention and calls for a better prompt
            # or a better model. Diagnosis only — the loose match is counted,
            # never applied.
            loose = _loose_hits(original, find)
            detail = ("whitespace-only miss" if loose == 1 else
                      f"whitespace-only miss but {loose} loose hits" if loose > 1
                      else "absent even loosely")
            report.rejected.append((find, f"not found in the section, {detail}"))
            continue
        if hits > 1:
            report.rejected.append((find, f"ambiguous, {hits} occurrences"))
            continue

        lost = set(_placeholders(find)) - set(_placeholders(replace))
        gained = set(_placeholders(replace)) - set(_placeholders(find))
        if lost or gained:
            report.rejected.append(
                (find, f"touches placeholders (lost {sorted(lost)}, "
                       f"added {sorted(gained)})"))
            continue

        start = original.index(find)
        located.append((start, start + len(find), find, replace))

    # Longest first, so that when two corrections cover the same sentence the
    # one that quoted more of it survives. Its "replace" is that whole passage
    # as it should read, so it carries the shorter one's fix as well.
    located.sort(key=lambda span: (span[0] - span[1], span[0]))
    taken = []
    for start, end, find, replace in located:
        clash = next(((s, e) for s, e, _ in taken if start < e and s < end), None)
        if clash:
            report.rejected.append(
                (find, f"overlaps a longer correction to the same passage "
                       f"(chars {clash[0]}-{clash[1]})"))
            continue
        taken.append((start, end, replace))

    # Back to front: splicing from the end keeps every remaining offset valid.
    text = original
    for start, end, replace in sorted(taken, reverse=True):
        text = text[:start] + replace + text[end:]
        report.applied += 1

    if _placeholders(text) != _placeholders(original):
        report.rejected.append((None, "placeholder set changed overall"))
        return original, report

    if original and len(text) < len(original) * (1 - MAX_SHRINK):
        report.rejected.append(
            (None, f"section shrank by "
                   f"{100 * (1 - len(text) / len(original)):.0f}%, over the "
                   f"{100 * MAX_SHRINK:.0f}% an edit pass may remove"))
        return original, report

    return text, report
