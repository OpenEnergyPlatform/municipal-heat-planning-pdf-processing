"""
jsonl.py: The lines of a JSON Lines file.

One record is one line, and a line ends at a line feed and nowhere else.
`str.splitlines()` also breaks at U+2028, U+2029 and U+0085, and
`json.dumps(ensure_ascii=False)` writes those three as they are. A quote
that carries one would be read as two broken records, and a file that is
read that way and written back would keep them broken.

Author: Felix Vossel
"""
from __future__ import annotations

from pathlib import Path


def lines(text: str) -> list:
    """The lines of *text*, in order and with the empty ones among them."""
    found = text.split("\n")
    if found and found[-1] == "":
        found.pop()             # the feed that ends the last line
    return found


def read(path) -> list:
    """The lines of a file. Reading folds `\\r\\n` into the line feed."""
    return lines(Path(path).read_text(encoding="utf-8"))
