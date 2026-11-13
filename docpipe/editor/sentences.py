"""
sentences.py: A text cut into sentences and the diff of two such texts.

A prompt is compared by sentence, one sentence per line, so that a changed
word shows as one changed line and not as a changed paragraph. The cut only
decides what one line of the diff is; the same rule runs on both sides, so a
wrong cut shows as two lines on each and never hides a change.

Author: Felix Vossel
"""
from __future__ import annotations

import difflib
import re

# The typographic quotes by code point, so that this file stays ASCII: what may
# close a sentence after its stop, and what may open one besides a capital.
_CLOSING = "\"')]" + "".join(chr(code) for code in (0x201C, 0x201D, 0x2019,
                                                     0xAB, 0xBB))
# A stop, the quotes and brackets that close the sentence with it, the space.
_STOP = re.compile(r"[.!?][" + re.escape(_CLOSING) + r"]*(\s+)(?=\S)")
# Besides a capital, what may open a sentence.
_OPENERS = "\"'([{<`" + "".join(chr(code) for code in (0x201E, 0x201C, 0x201A,
                                                       0x2018, 0xAB, 0xBB))


def sentences(line: str) -> list:
    """One line cut where a sentence ends: a stop, a space and a capital or an
    opening quote or bracket. Not after a single letter ("z. B.", "d. h.") and
    not after the number that opens a list item. The cut only decides what one
    line of the diff is. The same rule runs on both sides, so a wrong cut shows
    as two lines on each and never hides a change."""
    out, start = [], 0
    for hit in _STOP.finditer(line):
        words = line[start:hit.start()].split()
        word = words[-1].replace(".", "") if words else ""
        following = line[hit.end()]
        if word.isalpha() and len(word) < 2:
            continue
        if word.isdigit() and line[:hit.start()].strip() == word:
            continue                    # "3." that opens a list item
        if not (following.isupper() or following in _OPENERS):
            continue
        out.append(line[start:hit.start(1)])
        start = hit.end()
    out.append(line[start:])
    return out


def units(text: str) -> list:
    """The lines of a text, each cut into its sentences. A blank line is one
    unit and the end of the text is one, so a change of paragraphs or of the
    last newline is a change in the list."""
    out: list = []
    for line in text.split("\n"):
        out.extend(sentences(line) if line.strip() else [line])
    return out


def _range(start: int, stop: int) -> str:
    length = stop - start
    if length == 1:
        return str(start + 1)
    if not length:
        start -= 1
    return f"{start + 1},{length}"


def unified(before: list, after: list, context: int = 2) -> list:
    """The unified diff of two lists of units. Not `difflib.unified_diff`: its
    matcher treats an item that repeats as junk once a list reaches 200
    items, and blank lines repeat."""
    matcher = difflib.SequenceMatcher(None, before, after, autojunk=False)
    out = []
    for group in matcher.get_grouped_opcodes(context):
        first, last = group[0], group[-1]
        out.append(f"@@ -{_range(first[1], last[2])} "
                   f"+{_range(first[3], last[4])} @@")
        for tag, i1, i2, j1, j2 in group:
            if tag == "equal":
                out += [f" {unit}" for unit in before[i1:i2]]
                continue
            if tag in ("replace", "delete"):
                out += [f"-{unit}" for unit in before[i1:i2]]
            if tag in ("replace", "insert"):
                out += [f"+{unit}" for unit in after[j1:j2]]
    return out
