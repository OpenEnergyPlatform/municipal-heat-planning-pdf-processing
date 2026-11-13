"""
continuation.py: A table the layout cut in parts, and its parts joined to
their start (owner decision 2026-11-06).

A table that runs over a page break, or that the layout cut within a page,
came out of the transcription as parts, each with a caption and a head of its
own, invented where the part prints none: the parts of a table of municipal
buildings on three pages got a column "Kosten" and a unit no page prints. Now
the transcription of a table that may continue the table before it is shown
that table's caption and head and what stands between the two; the model says
whether it continues that table and, where it does, writes its rows under
that head and gives no caption. The merge before the database joins each such
part to the table it continues: one table, its parts' pages, crops and frames
kept beside it.

A table may continue the table right before it in reading order when that
table stands on its page or the page before and has a transcribed head.
Whatever stands between them (a heading, a page footer, a caption, a
paragraph, a figure) is shown to the model, which decides (owner decision
2026-11-07: also after a heading). The reading picks the same
tables by the same rule (`docpipe.extraction.lookup.continued`).

Author: Felix Vossel
"""
from __future__ import annotations

from typing import Callable, Iterator, Optional

# What stands between two tables is shown up to this many characters, its
# start and its end, as the section's text beside a table is cut.
BETWEEN_CHARS = 800

# What a joined part keeps beside its start's rows: where it stood and what
# the transcription measured of it.
PART_KEYS = ("id", "page_number", "path", "bbox", "qa")


def is_rule(line: str) -> bool:
    """Is *line* the rule under a Markdown table's head ("| --- | --- |")?
    The test `docpipe.extraction.lookup.head_of` closes a head with."""
    line = line.strip()
    return line.count("|") >= 2 and "-" in line and set(line) <= set("|:- \t")


def head_lines(markdown: Optional[str]) -> str:
    """A transcribed table's head: its lines down to the rule, the rule
    included, where a row of cells stands above the rule; "" where it has
    none. A head as `docpipe.extraction.lookup.head_of` takes one."""
    lines = (markdown or "").splitlines()
    for at, line in enumerate(lines):
        if is_rule(line):
            if not any(one.count("|") >= 2 for one in lines[:at]):
                return ""
            return "\n".join(lines[:at + 1]).strip()
    return ""


def body_rows(markdown: Optional[str]) -> list:
    """The rows of a transcribed table under its head: its lines after the
    rule, else all of them."""
    lines = [line for line in (markdown or "").splitlines() if line.strip()]
    for at, line in enumerate(lines):
        if is_rule(line):
            return lines[at + 1:]
    return lines


def _stream(sections: list) -> Iterator[tuple]:
    """(kind, page, item) of a document in reading order: each section's
    start ("section", the section), then its pieces as its segments order
    them ("text" with its text, "table" and "figure" with the item); a table
    no segment names comes at the end of its section."""
    for section in sections:
        yield "section", section.get("page_number"), section
        tables = {t.get("id"): t for t in section.get("tables") or []}
        figures = {f.get("id"): f for f in section.get("figures") or []}
        seen: set = set()
        for seg in section.get("segments") or []:
            if not isinstance(seg, dict):
                continue
            kind, page, ref = seg.get("kind"), seg.get("page"), seg.get("ref")
            if kind == "table" and ref in tables and ref not in seen:
                seen.add(ref)
                table = tables[ref]
                yield "table", (page if page is not None
                                else table.get("page_number")), table
            elif kind == "figure":
                yield "figure", page, figures.get(ref) or {}
            elif kind == "text":
                yield "text", page, seg.get("text") or ""
        for table in section.get("tables") or []:
            if table.get("id") not in seen:
                yield "table", table.get("page_number"), table


def _said(kind: str, item) -> str:
    """What a piece between two tables shows of itself."""
    if kind == "text":
        return str(item).strip()
    if kind == "figure":
        caption = (item.get("caption") or "").strip()
        return f"[Figure: {caption}]" if caption else "[Figure]"
    title = (item.get("title") or "").strip()
    return f"# {title}" if title else ""


def _shortened(text: str, limit: int = BETWEEN_CHARS) -> str:
    """*text*, its start and its end where it is longer than *limit*."""
    if len(text) <= limit:
        return text
    half = (limit - 5) // 2
    return text[:half].rstrip() + " ... " + text[-half:].lstrip()


def links(sections: list) -> dict:
    """{table id: {"after": the id of the table before it, "between": the
    text between them}} for each table whose page lets it continue the table
    right before it (see the module; whether that table has a head is known
    once it is transcribed, `transcribe_run`); "" where nothing stands
    between them."""
    out: dict = {}
    previous: Optional[tuple] = None     # (page, table)
    between: list = []                   # (kind, item)
    for kind, page, item in _stream(sections):
        if kind != "table":
            if previous is not None:
                between.append((kind, item))
            continue
        if (previous is not None and page is not None
                and previous[0] is not None
                and page in (previous[0], previous[0] + 1)):
            said = [_said(other, one) for other, one in between]
            out[item.get("id")] = {
                "after": previous[1].get("id"),
                "between": _shortened("\n".join(s for s in said if s))}
        previous, between = (page, item), []
    return out


def runs(sections: list, found: dict) -> list:
    """The tables of a document in reading order, in runs: a table that may
    continue the one before it (*found*, `links`) is in that table's run.
    Each run as [(section index, table index)], for a stage that asks a
    run's tables in their order."""
    where = {t.get("id"): (si, ti) for si, section in enumerate(sections)
             for ti, t in enumerate(section.get("tables") or [])}
    out: list = []
    for kind, _page, item in _stream(sections):
        place = where.get(item.get("id")) if kind == "table" else None
        if place is None:
            continue
        if out and item.get("id") in found:
            out[-1].append(place)
        else:
            out.append([place])
    return out


def before_of(start: dict, link: dict) -> dict:
    """What the request of a table that may continue *start* is shown of it:
    the id of the table right before it (*link*), *start*'s caption and head,
    and what stands between them."""
    return {"after": link["after"], "caption": (start.get("caption") or ""),
            "head": head_lines(start.get("markdown")),
            "between": link.get("between") or ""}


def transcribe_run(items: list, found: dict, cached: dict,
                   transcribe: Callable) -> list:
    """The tables of one run (`runs`) in their order, each transcribed or
    taken from *cached* (by id): [result].

    *transcribe(item, before)* is one request; *before* is what it is shown
    of the table the item may continue (`before_of`), None for a table asked
    on its own. The table a run starts with is shown to each later one until
    one of them does not continue it, which is then shown to those after it;
    one without a transcribed head (`head_lines`) is shown to none. A cached
    table stands, unless it may continue a table that has a transcribed head
    and was not asked against the table right before it (a transcription
    from before this was asked, or of another table)."""
    out: list = []
    start: Optional[dict] = None
    for item in items:
        link = found.get(item.get("id"))
        shown = (start if link is not None and start is not None
                 and head_lines(start.get("markdown")) else None)
        kept = cached.get(item.get("id"))
        if kept is not None and (shown is None
                                 or kept.get("after") == link["after"]):
            result = kept
        else:
            result = transcribe(item, before_of(shown, link)
                                if shown is not None else None)
        out.append(result)
        if not (shown is not None and result.get("continues") is True):
            start = result
    return out


def join(sections: list) -> int:
    """Each table the transcription found to continue the table before it
    ("continues", "after"), joined in place to the table its run started
    with: its rows under that table's rows, and its id, page, crop, frame and
    check in that table's "parts"; it leaves its section. A part whose start
    has no transcription, or that has none itself, stays a table of its own.
    Returns how many parts were joined."""
    tables = {t.get("id"): t for section in sections
              for t in section.get("tables") or []}
    start_of: dict = {}
    joined: set = set()
    for kind, _page, table in _stream(sections):
        if kind != "table" or table.get("continues") is not True:
            continue
        before = tables.get(table.get("after"))
        start = start_of.get(table.get("after"), before)
        if not start or not start.get("markdown") \
                or not table.get("markdown"):
            continue
        rows = body_rows(table["markdown"])
        start["markdown"] = "\n".join([start["markdown"].rstrip("\n"), *rows])
        start.setdefault("parts", []).append(
            {key: table[key] for key in PART_KEYS if key in table})
        start_of[table.get("id")] = start
        joined.add(table.get("id"))
    for section in sections:
        section["tables"] = [t for t in section.get("tables") or []
                             if t.get("id") not in joined]
    return len(joined)
