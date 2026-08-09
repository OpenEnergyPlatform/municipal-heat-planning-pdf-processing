"""
chunker.py – Pack ranked retrieval hits into token-budgeted chunks, each fed to
the LLM as one QA attempt.

Author: Felix Vossel
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from .config import LLM_TOKENIZER_ID

log = logging.getLogger(__name__)

_TOKENIZER = None
_TOKENIZER_TRIED = False


@dataclass
class Chunk:
    """One LLM QA attempt: a list of source-tagged content items."""
    items: list[dict] = field(default_factory=list)


def get_tokenizer(tokenizer_id: str = LLM_TOKENIZER_ID):
    """
    Lazily load the LLM tokenizer, cached across calls. None if it cannot be
    loaded (offline, gated repo, missing dependency) → char/4 heuristic.
    """
    global _TOKENIZER, _TOKENIZER_TRIED
    if _TOKENIZER_TRIED:
        return _TOKENIZER
    _TOKENIZER_TRIED = True
    try:
        from transformers import AutoTokenizer
        _TOKENIZER = AutoTokenizer.from_pretrained(tokenizer_id)
    except Exception as e:
        log.warning("Tokenizer '%s' unavailable, using char/4 heuristic: %s", tokenizer_id, e)
        _TOKENIZER = None
    return _TOKENIZER


def count_tokens(text: str, tokenizer=None) -> int:
    """Token count via the tokenizer if given, else a char/4 estimate."""
    if tokenizer is not None:
        return len(tokenizer.encode(text, add_special_tokens=False))
    return max(1, len(text) // 4)


def citation_label(hit: dict) -> str:
    """Human-readable source label for a retrieval hit."""
    lq, rq = '„', '“'
    page = hit.get("page_number")
    page_str = f'Seite {page}' if page is not None else 'Seite unbekannt'
    sec_title = hit.get("section_title")
    kind = hit.get("owner_kind")

    if kind == "section":
        name = sec_title or "Abschnitt"
        return f'Abschnitt {lq}{name}{rq}, {page_str}'
    if kind == "table":
        cap = hit.get("title") or "Tabelle"
        in_sec = f' (Abschnitt {lq}{sec_title}{rq})' if sec_title else ''
        return f'Tabelle {lq}{cap}{rq}{in_sec}, {page_str}'
    if kind == "figure":
        cap = hit.get("title") or "Abbildung"
        in_sec = f' (Abschnitt {lq}{sec_title}{rq})' if sec_title else ''
        return f'Abbildung {lq}{cap}{rq}{in_sec}, {page_str}'
    return page_str


def format_hit(index: int, hit: dict) -> dict:
    """Build the per-item dict embedded in a chunk (with source + text)."""
    title = hit.get("title")
    body = hit.get("text") or ""
    text = f"{title}\n{body}" if title else body
    return {
        "index": index,
        "source": citation_label(hit),
        "text": text.strip(),
    }


def pack_chunks(hits: list[dict], token_budget: int, tokenizer=None) -> list[Chunk]:
    """
    Greedily pack score-ranked hits into chunks under `token_budget` each.

    A single hit larger than the whole budget gets its own OVERSIZED chunk —
    content is never truncated, so a chunk can exceed the budget.
    """
    chunks: list[Chunk] = []
    current: list[dict] = []
    current_tokens = 0

    for i, hit in enumerate(hits):
        item = format_hit(i, hit)
        t = count_tokens(item["text"], tokenizer)
        if current and current_tokens + t > token_budget:
            chunks.append(Chunk(items=current))
            current, current_tokens = [], 0
        current.append(item)
        current_tokens += t

    if current:
        chunks.append(Chunk(items=current))
    return chunks
