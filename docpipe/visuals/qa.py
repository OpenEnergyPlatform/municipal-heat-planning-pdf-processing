"""
qa.py: Quality checks for vision model table extraction.

Pure helper functions that judge a vision model's Markdown
transcription of a table. Coverage compares it against the PyMuPDF
source text and catches truncation; duplication counts repeated rows
and catches repetition loops. A source text that cannot be read as the
table (see `unreadable`) is no measure, so coverage is then unknown.

Author: Felix Vossel
"""
from __future__ import annotations

import re
from typing import Optional

# Salient content tokens: numbers (incl. German decimals like "45,2") and words
# of at least two letters. Single letters and punctuation are deliberately
# ignored, so formatting differences ("24V" vs "24 V") do not affect coverage.
_TOKEN_RE = re.compile(r"\d+(?:[.,]\d+)*|[^\W\d_]{2,}", re.UNICODE)

# A Markdown table separator row (e.g. "| --- | --- |") uses only these chars.
_SEPARATOR_CHARS = set("|-: ")


def salient_tokens(text: str) -> set[str]:
    """Lowercased numbers and words (>= 2 letters) found in *text*."""
    return {m.group(0).lower() for m in _TOKEN_RE.finditer(text or "")}


# Words, for judging whether a source text can be read at all: letters only and
# at least three, so numbers and stray letter pairs decide nothing.
_WORD_RE = re.compile(r"[^\W\d_]{3,}", re.UNICODE)


def words(text: str) -> set[str]:
    """Lowercased words (>= 3 letters) found in *text*."""
    return {m.group(0).lower() for m in _WORD_RE.finditer(text or "")}


def unreadable(source_text: str, markdown: str, known_words: set[str], *,
               max_shared: float, min_known: float) -> bool:
    """
    Whether the source text cannot be read as the table: less than
    *max_shared* of the transcription's salient tokens stand in it, AND less
    than *min_known* of its words occur in the rest of the document
    (*known_words*).

    Both, because each alone misjudges. A table of names a short paper uses
    nowhere else has few known words, but a sound transcription shares its
    tokens, so a truncated one still fails. A transcription that shares
    nothing with a source of known words is the transcription's fault. A
    scanned book whose OCR layer reads its sideways tables upside down
    ("Ayjiqixayy" for "flexibility") has both.
    """
    md = salient_tokens(markdown)
    found = words(source_text)
    if not md or not found:
        return False
    shared = len(salient_tokens(source_text) & md) / len(md)
    known = len(found & known_words) / len(found)
    return shared < max_shared and known < min_known


def _data_rows(markdown: str) -> list[str]:
    """Markdown table rows carrying content (excludes the |---| separator)."""
    rows: list[str] = []
    for line in (markdown or "").splitlines():
        s = line.strip()
        if s.startswith("|") and (set(s) - _SEPARATOR_CHARS):
            rows.append(s)
    return rows


def coverage(source_text: str, markdown: str,
             min_source_tokens: int = 8) -> Optional[float]:
    """
    Fraction of the source's salient tokens that also appear in the markdown.

    None when the source has fewer than *min_source_tokens* salient tokens
    (e.g. an image-only table with no text layer) — too little reference text
    to judge fairly. Not 1.0: an unmeasurable table is unknown, not perfect,
    and a scanned corpus would otherwise report a flawless QA pass for every
    table nobody ever checked.
    """
    src = salient_tokens(source_text)
    if len(src) < min_source_tokens:
        return None
    md = salient_tokens(markdown)
    return len(src & md) / len(src)


def duplication(markdown: str) -> float:
    """Fraction of duplicate data rows (0..1); 0 when there are fewer than 2."""
    rows = _data_rows(markdown)
    if len(rows) < 2:
        return 0.0
    return 1.0 - (len(set(rows)) / len(rows))


def dedup_consecutive_rows(markdown: str) -> str:
    """Collapse runs of identical consecutive data rows (the stutter pattern)."""
    out: list[str] = []
    prev_row: str | None = None
    for line in (markdown or "").splitlines():
        s = line.strip()
        is_row = s.startswith("|") and bool(set(s) - _SEPARATOR_CHARS)
        if is_row and s == prev_row:
            continue
        out.append(line)
        prev_row = s if is_row else None
    return "\n".join(out)


def assess(
    markdown: str,
    source_text: str = "",
    *,
    min_coverage: float = 0.5,
    max_duplication: float = 0.4,
    min_source_tokens: int = 8,
    known_words: Optional[set[str]] = None,
    max_shared: float = 0.25,
    min_known: float = 0.5,
) -> tuple[bool, dict]:
    """
    Judge a table Markdown transcription. Returns (passed, metrics).

    Fails when there are no data rows, duplication exceeds *max_duplication*,
    or coverage (when assessable) is below *min_coverage*. A coverage below it
    is not assessable where the source text is `unreadable` against
    *known_words*, the words of the rest of the document; without them it is
    taken as readable.
    """
    cov = coverage(source_text, markdown, min_source_tokens)
    source_unreadable = (cov is not None and cov < min_coverage
                         and known_words is not None
                         and unreadable(source_text, markdown, known_words,
                                        max_shared=max_shared,
                                        min_known=min_known))
    if source_unreadable:
        cov = None
    dup = duplication(markdown)
    has_rows = bool(_data_rows(markdown))
    # An unassessable coverage cannot fail the gate — there is nothing to
    # compare against — but it is reported as unknown so a corpus that is
    # never assessable does not read as a corpus that always passed.
    passed = (has_rows and dup <= max_duplication
              and (cov is None or cov >= min_coverage))
    return passed, {
        "coverage": None if cov is None else round(cov, 3),
        "coverage_assessed": cov is not None,
        "duplication": round(dup, 3),
        "has_rows": has_rows,
        "source_unreadable": source_unreadable,
    }
