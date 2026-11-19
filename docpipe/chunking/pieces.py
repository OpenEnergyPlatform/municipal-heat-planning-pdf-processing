"""
pieces.py: The entries of the index are the pieces the harvest reads (owner
decisions 2026-11-17: "Die Einträge im Index sind die Stücke der Ernte";
"**Nichts** kürzen, einfach ggf. clever aufteilen und darauf achten, dass
die Zuordnung zu Sektion und Seite etc. nicht verlieren gehen").

A section, a table and a figure become a passage of numbered lines as the
harvest makes it: the text as the harvest is given it (`runner._source_of`:
the heading, or the caption, in front where the text does not open with it;
a placeholder in a section named by its caption, as `inference.db` shows
it), cut into lines by `extraction.units.passage_of` and into pieces of the
flow's `piece_lines` lines by `units.chunks_of`. One entry is one piece:

- of a section: its heading and its own lines, eight sentences;
- of a table: its title, head and the lines under it, the rows its own
  rows stand under (indented under, or grouped by a group row), and its
  own rows;
- of a figure: its caption and the lines of its description;

and a table's or figure's entries begin with its context sentence, where
the rule `context_sentence` gave one (the sentence of the part of the table
the piece's rows stand in, `context.lead_of`).

Each entry knows which piece it is (as the harvest counts them), its own
first and last line, and its page: a table's or figure's own page, a
section piece's the page its first own line stands on in the section's
segments, the text as the PDF gave it page by page (`line_pages`).

An entry that does not fit the embedder's window is split into parts
(`IndexPiece.parts`, `docpipe.window.split`): each part shows every line its
piece carries, and its own lines as many as fit; nothing is cut.

Author: Felix Vossel
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Optional

from docpipe import rules
from docpipe.captions import resolve_title
from docpipe.extraction import units
from docpipe.extraction.pipeline import Source
from docpipe.window import Part, split

_PLACEHOLDER = re.compile(r"\[(p\d+_(?:tbl|img)\d+)")
_NOT_WORD = re.compile(r"[\W_]+", re.UNICODE)


def piece_lines() -> int:
    """How many lines a piece holds: the number `piece_lines` of the flow of
    the profile in force, as the harvest reads it."""
    from docpipe.extraction import flow as flow_map
    from docpipe.profile import active_profile
    return int(flow_map.load(active_profile()).numbers["piece_lines"])


def section_content(section: dict) -> str:
    content = section.get("content", "") or ""
    if isinstance(content, list):
        content = "\n".join(str(c) for c in content)
    return content


def captions_of(section: dict, resolve: Optional[Callable] = None) -> dict:
    """{block id: caption} of the tables and figures of a merged section,
    each as the database holds it: the item's caption resolved by *resolve*
    (caption, section text, block id), `captions.resolve_title` where none
    is given, as the database step resolves it."""
    resolve = resolve_title if resolve is None else resolve
    content = section_content(section)
    out: dict = {}
    for item in (section.get("tables") or []) + (section.get("figures") or []):
        block = item.get("id")
        if block:
            out[block] = (resolve(item.get("caption"), content, block)
                          or "").strip()
    return out


def as_held(caption, content, block):
    """A caption as it stands: one the database already holds, resolved
    once before (`captions_of`)."""
    return caption


def _with_heading(heading: str, body: str) -> str:
    """The text the harvest reads: *heading* in front where *body* does not
    open with it (`runner._source_of`)."""
    heading = (heading or "").strip()
    if heading and heading not in body[:rules.get("heading_in_front_chars")]:
        return f"{heading}\n{body}"
    return body


def section_source(section: dict, captions: dict) -> Source:
    from docpipe.inference.db import annotate_placeholders
    title = (section.get("title") or "").strip()
    body = annotate_placeholders(section_content(section), captions)
    return Source("section", 0, _with_heading(title, body),
                  {"section_title": title,
                   "page": section.get("page_number")})


def item_source(kind: str, section: dict, item: dict, captions: dict
                ) -> Source:
    title = captions.get(item.get("id")) or (item.get("caption") or "").strip()
    body = (item.get("markdown") if kind == "table"
            else item.get("description")) or ""
    return Source(kind, 0, _with_heading(title, body),
                  {"title": title, "section_title": section.get("title"),
                   "page": item.get("page_number"),
                   "block_id": item.get("id")})


def _compact(text: str) -> str:
    """Letters and digits only, lower case: how a line and the PDF's text of
    it are compared, so that a word the refinement joined across a line
    break ("Wärme-\\nbedarf") is still found."""
    return _NOT_WORD.sub("", (text or "").lower())


def line_pages(texts: list, section: dict) -> list:
    """The page each of a section's lines *texts* stands on: the page of
    the segment (the PDF's text of the section, page by page) where its
    words are found, searched from where the line before was found; a
    placeholder line on its table's or figure's page; a line not found on
    the page of the line before it, the first on the section's page."""
    segments = [s for s in section.get("segments") or []
                if isinstance(s, dict) and s.get("page") is not None]
    first = section.get("page_number")
    if first is None and segments:
        first = segments[0].get("page")
    flat: list = []
    starts: list = []
    pages: list = []
    by_ref: dict = {}
    at = 0
    for segment in segments:
        if segment.get("kind") in ("table", "figure") and segment.get("ref"):
            by_ref.setdefault(segment["ref"], segment["page"])
            continue
        if segment.get("kind") != "text":
            continue
        compact = _compact(segment.get("text"))
        if not compact:
            continue
        flat.append(compact)
        starts.append(at)
        pages.append(segment["page"])
        at += len(compact)
    whole = "".join(flat)

    def page_at(offset: int):
        page = pages[0] if pages else first
        for start, one in zip(starts, pages):
            if start > offset:
                break
            page = one
        return page

    out: list = []
    cursor = 0
    before = first
    probes = _probes()
    for text in texts:
        found = None
        ref = _PLACEHOLDER.match((text or "").strip())
        if ref and ref.group(1) in by_ref:
            found = by_ref[ref.group(1)]
        else:
            key = _compact(text)
            # How much of a line's beginning is looked for, longest first: a
            # line the refinement changed a word of further on is still
            # found by its first words. A line of fewer letters than the
            # shortest says too little to be placed, and stands where the
            # line before it stands.
            for size in probes:
                probe = key[:size]
                if len(probe) < probes[-1]:
                    break
                hit = whole.find(probe, cursor)
                if hit >= 0:
                    found = page_at(hit)
                    cursor = hit
                    break
        if found is None:
            found = before
        out.append(found)
        before = found
    return out


# The lengths, in letters and digits, of the beginnings of a line looked for
# in the PDF's text of its section (`line_pages`): where a line is found, not
# what any request shows. The rule page_locate_probe_chars: long, medium and
# short, tried longest first.
def _probes() -> tuple:
    return tuple(sorted(
        (int(n) for n in rules.get("page_locate_probe_chars").values()),
        reverse=True))


@dataclass
class IndexPiece:
    """One piece of a passage as an entry of the index: its *chunk*
    (`units.Chunk`), the *lead* in front of it (a context sentence and its
    line break, or ""), the *heading* a section piece shows where its own
    lines do not hold it, and the page each of its passage's lines stands
    on (*pages*, by line number)."""
    chunk: units.Chunk
    lead: str = ""
    heading: str = ""
    pages: Optional[dict] = None

    @property
    def index(self) -> int:
        return self.chunk.index

    @property
    def passage(self) -> units.Passage:
        return self.chunk.passage

    def _shown(self, numbers) -> list:
        passage = self.passage
        carried = passage.fixed if self.chunk.carried is None \
            else self.chunk.carried
        return sorted(set(carried) | set(numbers)
                      | passage.parents_of(numbers))

    def render(self, numbers=None, replaced: Optional[dict] = None) -> str:
        """The entry's text: the lead, the heading where the lines shown do
        not hold it, the lines shown of the own lines *numbers* (all where
        None), a line in *replaced* as the text given there."""
        numbers = self.chunk.numbers if numbers is None else numbers
        replaced = replaced or {}
        shown = self._shown(numbers)
        lines = [replaced.get(n, self.passage.line(n).text) for n in shown]
        # A section's first line is its heading, or the opening that holds
        # it (`_with_heading`); every other piece shows it in front.
        if self.heading and 1 not in shown:
            lines = [self.heading] + lines
        return self.lead + "\n".join(lines)

    def text(self) -> str:
        return self.render()

    def page_of(self, numbers=None):
        """The page the first of the own lines *numbers* stands on, else
        the passage's."""
        numbers = self.chunk.numbers if numbers is None else numbers
        if self.pages and numbers:
            page = self.pages.get(min(numbers))
            if page is not None:
                return page
        return self.passage.page

    def first_last(self, numbers=None) -> tuple:
        numbers = self.chunk.numbers if numbers is None else numbers
        return (min(numbers), max(numbers)) if numbers else (None, None)

    def parts(self, fits: Callable[[str], bool], name: str = "") -> list:
        """[window.Part] of this entry, each of which *fits*: the whole
        where it fits, else its own lines as many as fit with every line
        it carries, a line that does not fit alone at its sentences, then
        its words (`window.split`). A piece of carried lines alone is one
        part, or `window.TooLong`."""
        numbers = list(self.chunk.numbers)
        if not numbers:
            text = self.render(())
            if fits(text):
                return [Part((), {}, text)]
            from docpipe.window import TooLong
            raise TooLong(f"{name or 'a piece'}: the lines every part of it "
                          f"shows do not fit the window")
        return split(numbers, lambda own, replaced: self.render(own, replaced),
                     lambda n: self.passage.line(n).text, fits,
                     units.sentences_of, name)


def section_pieces(section: dict, captions: dict, size: int) -> list:
    """[IndexPiece] of a merged section's text, in order. A section whose
    text is nothing but its heading has none (its title has a vector of its
    own)."""
    source = section_source(section, captions)
    passage = units.passage_of(source)
    title = (section.get("title") or "").strip()
    if not passage.lines or all(line.text.strip() == title
                                for line in passage.lines):
        return []
    pages = line_pages([line.text for line in passage.lines], section)
    by_line = {line.number: page for line, page in zip(passage.lines, pages)}
    return [IndexPiece(chunk, "", title, by_line)
            for chunk in units.chunks_of(passage, size)]


def item_pieces(kind: str, section: dict, item: dict, captions: dict,
                size: int, lead_of: Callable) -> list:
    """[IndexPiece] of a merged table or figure, in order, each with the
    lead *lead_of(item, first line, last line)* gives it."""
    source = item_source(kind, section, item, captions)
    if not (source.text or "").strip():
        return []
    passage = units.passage_of(source)
    out: list = []
    for chunk in units.chunks_of(passage, size):
        first, last = ((min(chunk.numbers), max(chunk.numbers))
                       if chunk.numbers else (None, None))
        out.append(IndexPiece(chunk, lead_of(item, first, last)))
    return out
