"""
qa.py – Quality checks for VLM table extraction.

Pure, dependency-free helpers used to judge a vision model's Markdown
transcription of a table:

- coverage:   fraction of the table's source text (PyMuPDF) recovered in the
              Markdown — catches truncation / under-extraction.
- duplication: fraction of repeated data rows — catches the "stutter" loop
              where a sequence model regenerates the same row repeatedly.
- dedup_consecutive_rows: cleanup that collapses runs of identical rows.

Author: Felix Vossel
"""
from __future__ import annotations

import re

# Salient content tokens: numbers (incl. German decimals like "45,2") and
# words of at least two letters. Single letters / punctuation are ignored so
# that minor formatting differences ("24V" vs "24 V") do not affect coverage.
_TOKEN_RE = re.compile(r"\d+(?:[.,]\d+)*|[^\W\d_]{2,}", re.UNICODE)

# A Markdown table separator row (e.g. "| --- | --- |") uses only these chars.
_SEPARATOR_CHARS = set("|-: ")


def salient_tokens(text: str) -> set[str]:
    """Lowercased numbers and words (>= 2 letters) found in *text*."""
    return {m.group(0).lower() for m in _TOKEN_RE.finditer(text or "")}


def _data_rows(markdown: str) -> list[str]:
    """Markdown table rows carrying content (excludes the |---| separator)."""
    rows: list[str] = []
    for line in (markdown or "").splitlines():
        s = line.strip()
        if s.startswith("|") and (set(s) - _SEPARATOR_CHARS):
            rows.append(s)
    return rows


def coverage(source_text: str, markdown: str, min_source_tokens: int = 8) -> float:
    """
    Fraction of the source's salient tokens that also appear in the markdown.

    Returns 1.0 when the source has fewer than *min_source_tokens* salient
    tokens (e.g. an image-only table with no text layer) — too little
    reference text to judge fairly.
    """
    src = salient_tokens(source_text)
    if len(src) < min_source_tokens:
        return 1.0
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
) -> tuple[bool, dict]:
    """
    Judge a table Markdown transcription. Returns (passed, metrics).

    Fails when there are no data rows, duplication exceeds *max_duplication*,
    or coverage (when assessable) is below *min_coverage*.
    """
    cov = coverage(source_text, markdown, min_source_tokens)
    dup = duplication(markdown)
    has_rows = bool(_data_rows(markdown))
    passed = has_rows and dup <= max_duplication and cov >= min_coverage
    return passed, {
        "coverage": round(cov, 3),
        "duplication": round(dup, 3),
        "has_rows": has_rows,
    }
