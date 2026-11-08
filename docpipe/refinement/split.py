"""
split.py: Cuts a section too long to be one retrieval chunk into
several, each a self-contained citation unit.

A section is one chunk and one vector. Past a certain length that
vector stops meaning anything in particular, and past the embedding
model's token limit the tail is not indexed at all, so an oversized
section has to become several.

The model is asked only where it would cut and what to call the
parts, never to reproduce the text. The cut itself happens
mechanically at segment boundaries, which is what makes it safe:
nothing is rephrased, dropped or invented, and each part keeps
exactly the pages, tables and figures that belong to its own text.
Asking only for an outline also keeps the call small, since a section
long enough to need splitting is by definition too long to echo.
When no cut is asked for, or the model's cuts could not be read (a
hole, with its cause), a mechanical fallback cuts at even word-count
intervals instead, dropping a cut that would leave a sliver under
about 100 words; the section is named in the refinement report with
the cause. A request whose reply was cut off is asked again for half
of the outline, since the outline has one line per segment.

A part still over the configured word limit after this pass is cut
again against a lower target; a single segment carrying the whole
overflow is first divided into smaller ones so that a boundary exists
to cut at. A section whose segments no longer reproduce its own
content, because refinement rewrote it, is left oversized rather than
cut at a guessed position.

Author: Felix Vossel
"""
from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Optional

from docpipe import prompts
from docpipe.profile import profile_value
from docpipe.reading import Hole

from .config import (
    LLM_NUM_PARALLEL,
    SECTION_MAX_WORDS,
    SECTION_OUTLINE_WORDS,
    SECTION_SPLIT_ENABLE,
    SECTION_TARGET_WORDS,
)

log = logging.getLogger(__name__)

# "nobody has asked the model yet", as against a call that came back with
# nothing. Only the first may still place a call.
_UNASKED = object()


class NotServed(Exception):
    """The request for the cuts got no answer from the server.

    Not a reason to cut mechanically: asked again another time, the model
    places the cuts. An answer that is unusable is, and so is a request the
    server refused.
    """

@prompts.per_profile
def split_prompt():
    return prompts.load("refinement/split")


def split_temperature() -> float:
    return float(split_prompt().meta.get("temperature", 0.1))


def split_max_tokens() -> int:
    return int(split_prompt().meta.get("max_tokens", 1024))


PROMPT_IDS = ("refinement/split",)


def word_count(text: str) -> int:
    return len((text or "").split())


def _segment_text(seg: dict) -> str:
    """What this segment contributes to the section's content string."""
    if seg.get("kind") == "text":
        return seg.get("text") or ""
    ref = seg.get("ref")
    return f"[{ref}]" if ref else ""


def content_from_segments(segments: list) -> str:
    """
    Rebuild a section's content from its segments — the inverse of how Stage 3
    assembled it (text run by text run, a [block_id] marker where a table or
    figure sits).
    """
    return " ".join(t for t in (_segment_text(s) for s in segments) if t)


def _rebuild_matches(section: dict) -> bool:
    """
    Is this section's content exactly what its segments say it is?

    Only then can it be cut along them. Refinement may have rewritten the
    content, and a section whose provenance no longer lines up must be left
    alone rather than cut at a guessed position.
    """
    def norm(s: str) -> str:
        return re.sub(r"\s+", " ", s or "").strip()
    return norm(content_from_segments(section.get("segments") or [])) \
        == norm(section.get("content") or "")


def needs_split(section: dict, max_words: int = SECTION_MAX_WORDS) -> bool:
    content = section.get("content")
    if not isinstance(content, str):        # [LITERATURE] sections hold a list
        return False
    return word_count(content) > max_words


def outline(section: dict, sample_words: int = SECTION_OUTLINE_WORDS, *,
            start: int = 0, stop: Optional[int] = None) -> str:
    """One numbered line per segment: its size and how it starts.

    The segments *start* to *stop* (the whole section by default), each with
    its number in the section: the cuts the model names are those numbers."""
    lines = []
    segments = section.get("segments") or []
    for i in range(start, len(segments) if stop is None else stop):
        seg = segments[i]
        if seg.get("kind") == "text":
            words = (seg.get("text") or "").split()
            head = " ".join(words[:sample_words])
            if len(words) > sample_words:
                head += " …"
            lines.append(f"{i:4d} [{len(words)} words] {head}")
        else:
            kind = "TABLE" if seg.get("kind") == "table" else "FIGURE"
            lines.append(f"{i:4d} [{kind}] {seg.get('ref') or ''}")
    return "\n".join(lines)


def _even_cuts(section: dict, target: int = SECTION_TARGET_WORDS) -> list:
    """Fallback: cut at the segment boundary nearest each target multiple."""
    cuts, running = [], 0
    for i, seg in enumerate(section.get("segments") or []):
        if i and running >= target:
            cuts.append({"at": i, "title": None})
            running = 0
        running += word_count(_segment_text(seg))
    return cuts


def _sanitize(cuts, n_segments: int, section: dict) -> list:
    """Keep only cuts that name a real segment boundary, in order, no duplicates."""
    clean, seen = [], set()
    for c in cuts or []:
        try:
            at = int(c.get("at"))
        except (AttributeError, TypeError, ValueError, OverflowError):
            # No reply is repaired, and nothing broad catches around this any
            # more: a position that is no number (an infinity too, which a
            # strict JSON read lets through) names no boundary and is dropped.
            continue
        if not (0 < at < n_segments) or at in seen:
            continue
        seen.add(at)
        title = c.get("title")
        title = (title.strip() or None) if isinstance(title, str) else None
        clean.append({"at": at, "title": title})
    clean.sort(key=lambda c: c["at"])
    # Drop a cut that would leave a sliver: below ~100 words a part is not a
    # chunk, it is debris.
    segments = section.get("segments") or []
    kept, previous = [], 0
    for c in clean:
        if sum(word_count(_segment_text(s)) for s in segments[previous:c["at"]]) < 100:
            continue
        kept.append(c)
        previous = c["at"]
    if kept and sum(word_count(_segment_text(s)) for s in segments[kept[-1]["at"]:]) < 100:
        kept.pop()
    return kept


def apply_cuts(section: dict, cuts: list, first_title: Optional[str] = None) -> list:
    """
    Cut *section* at the given segment indices. Returns the parts in order; the
    original is returned untouched (as a single-element list) when there is
    nothing to cut.
    """
    segments = section.get("segments") or []
    if not cuts:
        return [section]

    bounds = [0] + [c["at"] for c in cuts] + [len(segments)]
    titles = [first_title or section.get("title") or ""] + [c["title"] for c in cuts]
    media = {**{t["id"]: ("tables", t) for t in section.get("tables") or []},
             **{f["id"]: ("figures", f) for f in section.get("figures") or []}}

    parts = []
    for k in range(len(bounds) - 1):
        chunk = segments[bounds[k]:bounds[k + 1]]
        if not chunk:
            continue
        part = dict(section)
        part["segments"] = chunk
        part["content"] = content_from_segments(chunk)
        part["title"] = (titles[k] or section.get("title") or "").strip() \
            or (f"{section.get('title') or profile_value('preprocessing', 'PART_TITLE')}"
                f" ({k + 1})")
        # Each part keeps only the media its own text refers to.
        refs = [s.get("ref") for s in chunk if s.get("kind") in ("table", "figure")]
        part["tables"] = [media[r][1] for r in refs if r in media and media[r][0] == "tables"]
        part["figures"] = [media[r][1] for r in refs if r in media and media[r][0] == "figures"]
        pages = sorted({s["page"] for s in chunk if s.get("page") is not None})
        part["pages"] = pages
        part["page_number"] = pages[0] if pages else section.get("page_number")
        parts.append(part)
    return parts or [section]


def _ask_cuts(section: dict, ask: Callable) -> dict | Hole:
    """Where the model would cut *section*: the one object it answered with
    (`cuts`, and maybe `first_title`), or a Hole that says why it did not.

    The whole blocking part of a split, and it depends on nothing but this one
    section, which is what lets split_oversized run them together. A request
    the server did not serve raises NotServed.

    A reply that was cut off is not asked again as it stands. The outline has
    one line per segment, so the section is asked about its first half and
    its second half, the second keeping the segment numbers it has in the
    section, and the cuts are joined with the cut between the halves. An
    outline of one segment has no halves and gets more room, once (the room
    is what *ask* gives a request marked *again*), or is a hole where the
    served window leaves it none.
    """
    return _ask_range(section, ask, 0, len(section.get("segments") or []))


def _ask_range(section: dict, ask: Callable, start: int, stop: int,
               again: bool = False) -> dict | Hole:
    got = ask(prompts.text("refinement/split", target=SECTION_TARGET_WORDS),
              f"TITLE: {section.get('title') or ''}\n\nOUTLINE:\n"
              f"{outline(section, start=start, stop=stop)}", again)
    if not (isinstance(got, Hole) and got.cause == "cut_off"):
        return got
    if stop - start > 1:
        mid = start + (stop - start) // 2
        log.warning("Split reply for %r cut off: asked again for segments "
                    "%d to %d and %d to %d", section.get("title"), start,
                    mid - 1, mid, stop - 1)
        first = _ask_range(section, ask, start, mid)
        second = _ask_range(section, ask, mid, stop)
        for half in (first, second):
            if isinstance(half, Hole):
                # A half that is a hole leaves a stretch nobody placed cuts in.
                return half
        title = second.get("first_title")
        return {"first_title": first.get("first_title"),
                "cuts": [*first["cuts"],
                         {"at": mid, "title": title if isinstance(title, str)
                          else None},
                         *second["cuts"]]}
    if not again:
        log.warning("Split reply for %r cut off, one segment: no halves to "
                    "ask for", section.get("title"))
        return _ask_range(section, ask, start, stop, again=True)
    return got


def split_section(section: dict, ask: Optional[Callable] = None,
                  reply=_UNASKED, holes: Optional[list] = None) -> list:
    """
    Split one oversized section. *ask* takes the rendered prompt and returns the
    model's answer (see `_ask_cuts`); without it, or when the answer is a Hole,
    the section is cut mechanically at even intervals, and when *holes* is
    given a Hole adds {"title", "why"} to it: the report names the section
    and the cause. *reply* hands in an answer fetched earlier (see
    split_oversized); then *ask* is not called at all.

    An answer of no cuts at all is an answer: the prompt allows it, and it is
    no hole.
    """
    if not _rebuild_matches(section):
        log.warning(
            "Section %r is %d words but its segments do not reproduce its "
            "content — not cutting it.",
            section.get("title"), word_count(section.get("content")),
        )
        return [section]

    n = len(section.get("segments") or [])
    cuts, first_title = [], None
    if reply is _UNASKED:
        reply = _ask_cuts(section, ask) if ask is not None else None
    if isinstance(reply, Hole):
        log.warning("Split reply for %r could not be read (%s): cutting it "
                    "mechanically", section.get("title"), reply.cause)
        if holes is not None:
            holes.append({"title": str(section.get("title") or ""),
                          "why": reply.cause})
    elif reply is not None:
        cuts = _sanitize(reply.get("cuts"), n, section)
        title = reply.get("first_title")
        first_title = ((title.strip() or None) if isinstance(title, str)
                       else None)

    if not cuts:
        cuts = _sanitize(_even_cuts(section), n, section)
        if cuts:
            log.info("Section %r cut mechanically into %d parts",
                     section.get("title"), len(cuts) + 1)
    if not cuts:
        return [section]
    parts = apply_cuts(section, cuts, first_title)
    log.info("Section %r (%d words) → %d parts (%s words)",
             section.get("title"), word_count(section.get("content")), len(parts),
             ", ".join(str(word_count(p["content"])) for p in parts))
    return parts


def _subdivide_segments(section: dict, target: int) -> bool:
    """Cut text segments longer than *target* into smaller ones, in place.

    Sections are cut at segment boundaries, so a section whose text sits in one
    long segment has nowhere to be cut and stays oversized however often it is
    asked — 51 sections in one scenarios run, up to 1409 words against a 1000 limit,
    and three of those in a window is what the model then had to hand back.

    A text segment's page and kind are unchanged by the cut, so provenance is
    not lost here; it only gets finer. Placeholders (a table or figure ref)
    have no text to divide and are left alone.
    """
    segments = section.get("segments") or []
    if not segments:
        return False
    out, changed = [], False
    for seg in segments:
        words = (seg.get("text") or "").split() if seg.get("kind") == "text" else []
        if len(words) <= target:
            out.append(seg)
            continue
        for i in range(0, len(words), target):
            piece = dict(seg)
            piece["text"] = " ".join(words[i:i + target])
            out.append(piece)
        changed = True
    if changed:
        section["segments"] = out
    return changed


def _enforce_max(part: dict, max_words: int) -> list:
    """Cut *part* down until every piece fits *max_words*.

    The model is asked for readable boundaries, not for a bound, and it does
    return parts over the limit — an 11596-word section came back as 10 parts
    with one of 2392. Without this, max_words is a suggestion, and any context
    budget resting on it (config.max_request_tokens) is fiction.
    """
    # Aim below the limit, not at it: a cut lands on a segment boundary, so the
    # piece is the target plus whatever the straddling segment adds.
    target = min(SECTION_TARGET_WORDS, max(1, max_words // 2))
    out, queue = [], [part]
    while queue:
        piece = queue.pop(0)
        if not needs_split(piece, max_words):
            out.append(piece)
            continue
        rebuildable = _rebuild_matches(piece)
        cuts = (_sanitize(_even_cuts(piece, target=target),
                          len(piece.get("segments") or []), piece)
                if rebuildable else [])
        if not cuts and rebuildable and _subdivide_segments(piece, target):
            # No boundary to cut on because one segment carries the overflow.
            # Give it boundaries, then ask again.
            cuts = _sanitize(_even_cuts(piece, target=target),
                             len(piece.get("segments") or []), piece)
        if not cuts:
            # Left only when the segments no longer rebuild the content —
            # refinement rewrote it, and cutting at a guessed position would
            # attach text to the wrong page.
            log.warning(
                "Section %r stays at %d words (limit %d): its segments no "
                "longer rebuild its content, so there is no safe cut.",
                piece.get("title"), word_count(piece.get("content")), max_words)
            out.append(piece)
            continue
        queue.extend(apply_cuts(piece, cuts))
    return out


def _ask_all_cuts(sections: list, ask: Optional[Callable],
                  max_words: int) -> dict:
    """Every split call the document needs, at once; replies by section index.

    Asked serially this phase held exactly one request in flight per document,
    and it runs to completion before the windows are dispatched. A section that
    cannot be cut along its segments is skipped rather than asked about.
    """
    if ask is None:
        return {}
    todo = [i for i, s in enumerate(sections)
            if needs_split(s, max_words) and _rebuild_matches(s)]
    if not todo:
        return {}
    with ThreadPoolExecutor(max_workers=min(LLM_NUM_PARALLEL, len(todo))) as pool:
        return dict(zip(todo, pool.map(lambda i: _ask_cuts(sections[i], ask), todo)))


_LINE_END = re.compile(r"\n\s*")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_WORD = re.compile(r"\S+")


def _units(text: str, start: int, end: int, target: int) -> list:
    """(start, end) character spans of *text*[start:end] that cut it only where
    a line or, below that, a sentence ends; a span still longer than *target*
    words is cut after every *target* words."""
    spans = []
    for finer in (_LINE_END, _SENTENCE_END):
        if len(text[start:end].split()) <= target:
            break
        cuts = [m.end() for m in finer.finditer(text, start, end)
                if start < m.start() and m.end() < end]
        if cuts:
            bounds = [start, *cuts, end]
            for a, b in zip(bounds, bounds[1:]):
                spans.extend(_units(text, a, b, target) if finer is _LINE_END
                             else _words(text, a, b, target))
            return spans
    return _words(text, start, end, target)


def _words(text: str, start: int, end: int, target: int) -> list:
    """*text*[start:end] in runs of at most *target* words."""
    words = list(_WORD.finditer(text, start, end))
    if len(words) <= target:
        return [(start, end)]
    heads = [words[i].start() for i in range(target, len(words), target)]
    bounds = [start, *heads, end]
    return list(zip(bounds, bounds[1:]))


def _group(sizes: list, target: int, max_words: int) -> list:
    """Start indices of the parts *sizes* (words per unit) are grouped into:
    a part closes once it reaches *target*, and a last part under ~100 words
    joins the one before where both fit *max_words* (`_sanitize`'s rule)."""
    starts, running = [0], 0
    for i, size in enumerate(sizes):
        if i and running >= target:
            starts.append(i)
            running = 0
        running += size
    if len(starts) > 1 and sum(sizes[starts[-1]:]) < 100 \
            and sum(sizes[starts[-2]:]) <= max_words:
        starts.pop()
    return starts


def cut_to_limit(section: dict, max_words: int = SECTION_MAX_WORDS) -> list:
    """*section* as refinement left it, in parts of at most *max_words* each.

    The cut before refinement (`split_oversized`) holds the limit only on what
    goes into the model: a section the model merges back together, or a
    literature list it rewrites as BibTeX, which names every field, comes out
    longer, and the embedding then drops its tail. This cuts the refined text
    itself, with no model: a literature list after whole entries, any other
    text where a line ends, else where a sentence ends, else after a run of
    words, so that no word is changed or lost. Each part keeps the title and
    the tables and figures whose marker its text carries; one whose marker is
    in no part stays with the first. The segments follow the text
    (`_spread_segments`), so a part's pages are those of its own text.
    """
    content = section.get("content")
    target = min(SECTION_TARGET_WORDS, max(1, max_words // 2))
    if isinstance(content, list):
        if sum(word_count(str(e)) for e in content) <= max_words:
            return [section]
        sizes = [word_count(str(e)) for e in content]
        starts = _group(sizes, target, max_words)
        pieces = [content[a:b] for a, b in zip(starts, starts[1:] + [len(content)])]
        heads = [sum(sizes[:i]) for i in starts]
    elif isinstance(content, str) and word_count(content) > max_words:
        spans = _units(content, 0, len(content), target)
        sizes = [word_count(content[a:b]) for a, b in spans]
        starts = _group(sizes, target, max_words)
        ends = [spans[i][0] for i in starts] + [len(content)]
        pieces = [content[a:b].strip() for a, b in zip(ends, ends[1:])]
        heads = [sum(sizes[:i]) for i in starts]
    else:
        return [section]
    if len(pieces) < 2:
        return [section]
    parts = []
    for piece in pieces:
        part = dict(section)
        part["content"] = piece
        marked = set(_MARKER.findall(piece if isinstance(piece, str)
                                     else "\n".join(map(str, piece))))
        for key in ("tables", "figures"):
            part[key] = [item for item in section.get(key) or []
                         if isinstance(item, dict) and item.get("id") in marked]
        parts.append(part)
    for key in ("tables", "figures"):
        placed = {item.get("id") for part in parts for item in part[key]}
        parts[0][key] = parts[0][key] + [
            item for item in section.get(key) or []
            if not (isinstance(item, dict) and item.get("id") in placed)]
    for part, segments in zip(parts, _spread_segments(
            section.get("segments") or [], heads, sum(sizes), parts)):
        part["segments"] = segments
    return parts


def _spread_segments(segments: list, heads: list, total: int,
                     parts: list) -> list:
    """The segments of each of *parts*, which start at the words *heads* of a
    text *total* words long.

    Refinement rewrote the text a little, so its segments no longer rebuild
    it word for word (`_rebuild_matches`), but they still follow it in order
    and at nearly its length. A part therefore holds the source words at its
    own share of the way through: a text segment across a cut is cut there as
    well, each piece keeping its page and kind, as `_subdivide_segments` does.
    A table or figure goes with the part that marks it, else with the part
    its place in the order falls in.
    """
    out = [[] for _ in parts]
    source = sum(word_count(s.get("text")) for s in segments
                 if isinstance(s, dict) and s.get("kind") == "text")
    scale = source / total if total else 0.0
    cuts = [round(h * scale) for h in heads] + [source]
    marks = [set(_MARKER.findall(p["content"] if isinstance(p["content"], str)
                                 else "\n".join(map(str, p["content"]))))
             for p in parts]
    position = 0

    def part_at(word: int) -> int:
        return max(j for j in range(len(parts)) if cuts[j] <= word or j == 0)

    for seg in segments:
        if not isinstance(seg, dict):
            continue
        if seg.get("kind") != "text":
            owner = next((j for j, m in enumerate(marks) if seg.get("ref") in m),
                         part_at(position))
            out[owner].append(seg)
            continue
        seg_words = (seg.get("text") or "").split()
        start, end = position, position + len(seg_words)
        for j in range(len(parts)):
            a, b = max(start, cuts[j]), min(end, cuts[j + 1])
            if a < b or (not seg_words and j == part_at(start)):
                piece = dict(seg)
                if a < b and (a, b) != (start, end):
                    piece["text"] = " ".join(seg_words[a - start:b - start])
                out[j].append(piece)
        position = end
    return out


_MARKER = re.compile(r"\[([A-Za-z0-9_]+)\]")


def split_oversized(sections: list, ask: Optional[Callable] = None,
                    max_words: int = SECTION_MAX_WORDS,
                    holes: Optional[list] = None) -> list:
    """Split every section longer than *max_words*; returns the new list.

    *holes*, when given, gets {"title", "why"} for every section whose cut the
    model did not place and that was cut mechanically instead."""
    if not SECTION_SPLIT_ENABLE:
        return sections
    replies = _ask_all_cuts(sections, ask, max_words)
    out, n_split, n_recut = [], 0, 0
    for i, section in enumerate(sections):
        if needs_split(section, max_words):
            # The cuts are applied in the original order, so the outcome is the
            # one the serial version produced.
            parts = split_section(section, ask, reply=replies.get(i, _UNASKED),
                                  holes=holes)
            n_split += len(parts) > 1
            bounded = []
            for part in parts:
                pieces = _enforce_max(part, max_words)
                n_recut += len(pieces) > 1
                bounded.extend(pieces)
            out.extend(bounded)
        else:
            out.append(section)
    if n_split:
        log.info("Stage 4: split %d oversized section(s) → %d sections",
                 n_split, len(out))
    if n_recut:
        log.info("Stage 4: re-cut %d part(s) the model left over the limit",
                 n_recut)
    return out
