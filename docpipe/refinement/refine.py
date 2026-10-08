"""
refine.py: Runs Stage 4, the LLM-based refinement of Stage 3
sections.

The LLM is asked, per window of sections, to clean extraction
artefacts and titles, drop directory sections, convert bibliographies
to BibTeX, and merge or split sections; each returned action is
applied by refine_sections. A section longer than the split threshold
is cut before windowing (see split.py), since a window has to echo
every section it carries, and an oversized section could never be
echoed.

Windows are dispatched in parallel, up to LLM_NUM_PARALLEL requests
at once, then assembled in the original order, since merging and
splitting are positional. Every request sends its reply schema as the
grammar, and a reply is read as exactly one JSON object (see
docpipe/reading.py): nothing is stripped, cut out or closed. A reply
that is not that object is asked again with its cause named, up to
MAX_RETRIES times, except on a 4xx response, which is not retried
because the server has refused the request itself. A reply that was
cut off at its token limit is never asked again as it stands: the
window is asked in halves by sections, and a lone section gets more
room once (twice what it asked, or as much as the window the server
reported leaves, whichever is smaller; a window that leaves none makes
it a hole at once). What is still unread is a hole with its cause: the
window keeps its original, unrefined text and is recorded in the
refinement report written next to the output, and the next plain run
asks exactly those windows again.

Page provenance travels with the rewritten text: an unchanged window
reattaches its segments one to one, and a window that split, merged
or dropped sections is redistributed by which output section's
tokens a segment's text is found in, or by which output claims a
table's or figure's block id. A "remove" action is refused when the
section still carries a table or figure, since those are Stage 2
artefacts with their own transcriptions and not the model's to
discard; a section made of nothing but reference markers can
otherwise look empty to a reader of the text alone.

Author: Felix Vossel
"""
from __future__ import annotations

import copy
import hashlib
import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Optional

from docpipe import prompts, providers, reading, usage
from docpipe.llm_preflight import request_extras, served_window
from docpipe.reading import Hole

from . import replies
from .corrections import apply_corrections
from .split import (NotServed, split_max_tokens, split_oversized,
                    split_temperature)
from .config import (
    further_room,
    PROMPT_IDS,
    REFINEMENT_PARTIAL_JSON,
    REFINEMENT_REPORT_JSON,
    SECTIONS_JSON,
    SECTIONS_REFINED_JSON,
    LLM_MODEL,
    LLM_BASE_URL,
    LLM_API_KEY,
    LLM_TIMEOUT,
    LLM_NUM_PARALLEL,
    llm_temperature,
    REFINE_RETURN_CORRECTIONS,
    reply_tokens,
    MAX_RETRIES,
    WINDOW_SIZE,
    system_prompt,
    TITLE_CLEANUP_ENABLE,
    clean_data,
    dump_json_atomic,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# LLM API wrapper
# ---------------------------------------------------------------------------


class _NotServed:
    """What `_call_llm` returns for a window the server did not serve."""

    def __repr__(self) -> str:
        return "NOT_SERVED"


# Not a Hole: a Hole is a window the model was asked about and gave nothing
# usable for, which keeps its text. This one was never answered at all.
NOT_SERVED = _NotServed()


class Halved:
    """A window that was asked in halves, of which at least one part is a Hole.

    *parts* are (offset of the part in the window, the part's sections, its
    reply: a list of sections or a Hole). A window whose parts were all read
    is not one of these: its replies are laid end to end into one list, and
    the window is assembled like one that was never cut.
    """

    def __init__(self, parts: list):
        self.parts = parts

    def __repr__(self) -> str:
        return f"Halved({[type(r).__name__ for _o, _w, r in self.parts]})"


class Unfinished(Exception):
    """Windows the model server did not serve, so the document is not refined.

    *sections* are the sections the windows were cut from (after the split),
    *done* the usable replies by window index, *lost* the indices that were
    not served. A later run over the same sections asks only for the rest.
    Without *sections* it was the cut of an oversized section that was not
    served, and there is nothing to keep: the next run starts with the cut.
    """

    def __init__(self, sections: list, done: dict, lost: list, total: int,
                 mechanical: Optional[list] = None):
        super().__init__(f"{len(lost)} of {total} window(s) not served")
        self.sections, self.done, self.lost, self.total = (
            sections, done, lost, total)
        # The sections whose cut the model did not place, which the next pass
        # does not cut again and so cannot find out.
        self.mechanical = mechanical or []


def _backoff(attempt: int) -> None:
    """Sleep between retries (skipped after the final attempt)."""
    if attempt < MAX_RETRIES:
        time.sleep(min(2 * attempt, 10))


def _client_error_status(exc: Exception) -> Optional[int]:
    """The 4xx behind an API error, if the server refused the request itself.

    429 and 5xx are the server asking for time; a 4xx is this request being
    wrong, and every identical retry is refused identically.
    """
    status = getattr(exc, "status_code", None)
    if status is None:
        status = getattr(getattr(exc, "response", None), "status_code", None)
    if isinstance(status, int) and 400 <= status < 500 and status != 429:
        return status
    return None


def _strip_table_source_text(sections: list) -> None:
    """Remove the QA-only ``source_text`` field from every table, in place."""
    for sec in sections:
        if isinstance(sec, dict):
            for t in sec.get("tables", []):
                if isinstance(t, dict):
                    t.pop("source_text", None)


def _tail_text(content, n: int) -> str:
    """Returns the last *n* characters of a section's content (str or list)."""
    if isinstance(content, list):
        content = " ".join(str(x) for x in content)
    content = str(content)
    return content[-n:] if len(content) > n else content


# A re-ask has to tell the model that its answer was unusable, it does not
# have to hand the whole answer back. Echoing it verbatim adds up to
# llm_max_tokens() on top of a window that is already ~18k tokens, which is how a
# retry, not the original request, ran into the 32k context limit.
_ECHO_HEAD = 400
_ECHO_TAIL = 200


def _echo(raw_text: str) -> str:
    """The failed answer, bounded: enough to point at the fault, not a resend."""
    if len(raw_text) <= _ECHO_HEAD + _ECHO_TAIL:
        return raw_text
    dropped = len(raw_text) - _ECHO_HEAD - _ECHO_TAIL
    return (raw_text[:_ECHO_HEAD]
            + "\n...[%d characters omitted]...\n" % dropped
            + raw_text[-_ECHO_TAIL:])


def _materialise_corrections(reply: list, window: list) -> list:
    """Rebuild full sections from an edit-mode reply.

    Everything the model was not asked to change is taken from the ORIGINAL,
    not from the reply — that is the whole point of asking for edits. A table's
    id, path and page_number never make the round trip, so they cannot come
    back altered or missing, which is how they used to be lost.

    A section whose edits do not survive apply_corrections keeps whatever could be
    verified; nothing is applied on the model's word alone.
    """
    # Every section of the window starts as itself and every one of them is
    # returned. A reply that mentions two of three sections is the ordinary
    # case, not permission to drop the third: this book lost 123 of its 2697
    # sections that way, and the 27B run 237. What the reply does supply is
    # laid over the originals; what it omits stays as it was.
    built_by_index: dict = {
        i: {**original, "_action": "keep"} for i, original in enumerate(window)
    }
    pending: dict = {}
    for position, sec in enumerate(reply):
        if not isinstance(sec, dict):
            log.warning("   reply %d is not an object, section dropped", position)
            continue
        index = sec.get("index", position)
        if not isinstance(index, int) or not 0 <= index < len(window):
            log.warning("   reply names index %r, outside this window", index)
            continue
        original = window[index]
        action = sec.get("_action", "keep")

        built = dict(original)
        built["_action"] = action
        title = sec.get("title")
        if isinstance(title, str) and title.strip():
            built["title"] = title

        captions = sec.get("captions") if isinstance(sec.get("captions"), dict) else {}
        for key in ("tables", "figures"):
            items = []
            for media in (original.get(key) or []):
                media = dict(media)
                if media.get("id") in captions:
                    media["caption"] = captions[media["id"]]
                items.append(media)
            built[key] = items

        if action == "replace":
            # The one real conversion: text becomes a BibTeX array, so it has
            # to be written out in full.
            built["content"] = sec.get("content", original.get("content"))
        else:
            built["content"] = original.get("content")
            pending.setdefault(index, []).extend(sec.get("corrections") or [])

        built_by_index[index] = built

    # Pass two: apply the corrections gathered per section.
    for index, corrections in pending.items():
        built = built_by_index[index]
        if built.get("_action") == "replace":
            continue
        text, report = apply_corrections(window[index].get("content"), corrections)
        if report.rejected:
            # One line per refusal, WITH the string the model quoted. The
            # previous version logged the reason only, which made refusals
            # countable and undiagnosable at the same time: 1440 of them in
            # one run and no way to ask afterwards what they had quoted.
            for find, reason in report.rejected:
                log.warning("   section %d: refused (%s): %r",
                            index, reason, (find or "")[:100])
            log.warning("   section %d: %d correction(s) applied, %d refused",
                        index, report.applied, len(report.rejected))
        built["content"] = text

    return [built_by_index[i] for i in range(len(window))]


def _further_tokens(asked: int, unit: str) -> Optional[int]:
    """The token limit of the one further attempt at *unit* (as the log names
    it), whose reply was cut off at *asked* tokens, or None where the served
    window leaves no more room than it had. Both are said here."""
    more = further_room(asked)
    if more is None:
        log.warning("   %s cut off at %d tokens: the served window of %d "
                    "tokens leaves no more room, so no second request is "
                    "sent", unit, asked, served_window("llm"))
    else:
        log.warning("   %s cut off at %d tokens: asked again with %d tokens "
                    "(%d tokens before)", unit, asked, more, asked)
    return more


def _call_llm(
    sections_window: list[dict],
    client,
    prev_context: Optional[dict] = None,
    again: bool = False,
) -> list[dict] | Hole | _NotServed:
    """
    Sends a window of sections to the LLM and reads the one JSON object that
    comes back.

    *prev_context* (the previous window's last section) is passed read-only so
    the model can judge whether the first section is a continuation that should
    be merged across the window boundary. The reply schema is the grammar of
    the request. A reply that is not exactly one object with a ``sections``
    list is asked again, up to MAX_RETRIES times, with its cause named in the
    profile's words. A reply cut off at its token limit is not asked again as
    it stands: the caller splits the window (see `_ask_window`). A 4xx ends it
    at once: the server refused the request itself, so a retry of it is
    refused too. *again* is the one further attempt of a window that cannot
    be split any further: its reply's token limit is the room the served
    window leaves (see `further_room`), and where there is none the window is
    a Hole with its cause at once, with no request sent.

    Returns:
        The list of section dicts with "_action" fields. A Hole when the
        request was refused (4xx), the reply was cut off, or the model gave
        nothing readable in its last attempt; the Hole names why.
        NOT_SERVED when the last attempt never got an answer: no connection,
        a timeout, a 429 or a 5xx.
    """
    # segments/pages are stripped from the payload: the model must not see or
    # rewrite them. They are reattached afterwards (see _thread_provenance).
    stripped = [
        {k: v for k, v in s.items() if k not in ("segments", "pages")}
        for s in sections_window
    ]
    if REFINE_RETURN_CORRECTIONS:
        # The reply carries no text, so it needs a handle back to its section.
        # Media keeps only id and caption: the model must not restate a path or
        # a page number it is forbidden to change (and used to drop).
        for i, sec in enumerate(stripped):
            sec["index"] = i
            for key in ("tables", "figures"):
                sec[key] = [{"id": m.get("id"), "caption": m.get("caption")}
                            for m in (sec.get(key) or [])]
    user_payload = json.dumps(
        {"sections": stripped},
        ensure_ascii=False,
        indent=2,
    )

    if prev_context:
        ctx = {
            "title": prev_context.get("title", ""),
            "content_tail": _tail_text(prev_context.get("content", ""), 600),
        }
        user_content = (
            "CONTEXT (read-only — do NOT include this in your output): the "
            "section immediately before the first section below ended as "
            "shown. Use it ONLY to decide whether the first section is a "
            "broken continuation of it (then set that first section's "
            '_action to "merge_into_previous").\n'
            + json.dumps(ctx, ensure_ascii=False, indent=2)
            + "\n\nSECTIONS TO PROCESS:\n"
            + user_payload
        )
    else:
        user_content = user_payload

    base_messages = [
        {"role": "system", "content": system_prompt()},
        {"role": "user", "content": user_content},
    ]
    messages = list(base_messages)
    # What the last attempt came to. The last attempt decides: a 503 and then
    # replies nobody can read is a window the model got and could not do; the
    # other way round it is a window nobody answered.
    outcome: Hole | _NotServed = NOT_SERVED
    # Before the loop and outside its try: a setting that cannot be read is
    # no failed request, and must not pass for a server that did not answer.
    temperature = llm_temperature()
    # Sized to THIS window, not a flat cap: the reply is the window handed
    # back refined, so a big window needs a big answer. The flat 8192 cut the
    # JSON mid-string.
    max_tokens = reply_tokens(len(user_content.split()))
    if again:
        asked = max_tokens
        title = str(sections_window[0].get("title") or "?")[:60]
        max_tokens = _further_tokens(asked,
                                     f"Window of one section ({title!r})")
        if max_tokens is None:
            return Hole("cut_off", f"{asked} tokens")
    shape = providers.grammar(
        "refined_sections",
        replies.CORRECTIONS if REFINE_RETURN_CORRECTIONS
        else replies.window(stripped))

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.chat.completions.create(
                model=LLM_MODEL,
                messages=messages,
                response_format=shape,
                temperature=temperature,
                max_tokens=max_tokens,
                # Reasoning models must not spend the token budget on a
                # <think> block; that truncates the JSON answer.
                extra_body=request_extras(),
            )
        except Exception as e:
            status = _client_error_status(e)
            if status is not None:
                if "maximum context length" in str(e):
                    # The window does not fit and will not start fitting. Said
                    # loudly because the caller keeps such a window as raw text,
                    # which reads exactly like a window that needed no change.
                    log.error(
                        "   Window ABANDONED — it exceeds the model's context "
                        "and stays unrefined. %d section(s): %s | %s",
                        len(sections_window),
                        "; ".join(str(s.get("title") or "?")[:60]
                                  for s in sections_window),
                        e,
                    )
                else:
                    log.error("   LLM rejected the request (HTTP %d): %s", status, e)
                return Hole("refused", f"HTTP {status}")
            # Covers connection errors, the request timeout, 429 and 5xx.
            log.error(
                f"   Attempt {attempt}/{MAX_RETRIES}: LLM request failed: {e}"
            )
            outcome = NOT_SERVED
            messages = list(base_messages)
            _backoff(attempt)
            continue

        # The reply is in. What goes wrong from here is the reply's or ours,
        # never the server's, so it is read outside the request's own try.
        try:
            usage.reply(response, LLM_MODEL)
            choice = reading.first(response)
            found, cause, said = reading.read(choice, key="sections")
            if not cause:
                if REFINE_RETURN_CORRECTIONS:
                    return _materialise_corrections(found["sections"],
                                                    sections_window)
                return found["sections"]
        except Exception as e:
            log.exception("   Window of %d section(s): reading the reply failed "
                          "in the stage itself", len(sections_window))
            return Hole("error", f"{type(e).__name__}: {e}")

        if cause == "cut_off":
            log.warning(
                "   Reply cut off at %d tokens; window of %d section(s): %s",
                max_tokens, len(sections_window),
                "; ".join(str(s.get("title") or "?")[:60]
                          for s in sections_window))
            return Hole("cut_off", f"{max_tokens} tokens")
        log.warning(
            f"   Attempt {attempt}/{MAX_RETRIES}: {cause} reply "
            f"(finish: {getattr(choice, 'finish_reason', None)})"
        )
        outcome = Hole(cause)
        content = getattr(getattr(choice, "message", None), "content", None)
        messages = base_messages + [
            {"role": "assistant",
             "content": _echo(content) if isinstance(content, str) else ""},
            {"role": "user", "content": said},
        ]
        _backoff(attempt)

    return outcome


def _ask_window(window: list[dict], client, prev_context: Optional[dict]):
    """The reply to one window: a list of sections, a Hole, NOT_SERVED, or
    Halved when only some parts of the window were read.

    A reply that was cut off is never asked again as it stands. The window is
    asked as its first half and its second half, by sections; the second half
    sees the last section of the first as its context, exactly what the next
    window would see. A lone section has no halves and gets more room, once
    (`_further_tokens` says how much), or is a hole at once where the served
    window leaves it none. The reply that was cut off is not used.
    """
    got = _call_llm(window, client, prev_context)
    if not (isinstance(got, Hole) and got.cause == "cut_off"):
        return got
    if len(window) == 1:
        return _call_llm(window, client, prev_context, again=True)
    mid = len(window) // 2
    log.warning("   Window of %d section(s) cut off: asked again as %d and %d",
                len(window), mid, len(window) - mid)
    parts = []
    for offset, part, context in ((0, window[:mid], prev_context),
                                  (mid, window[mid:], window[mid - 1])):
        result = _ask_window(part, client, context)
        if result is NOT_SERVED:
            # A resume asks the whole window again.
            return NOT_SERVED
        if isinstance(result, Halved):
            parts.extend((offset + start, sub, reply)
                         for start, sub, reply in result.parts)
        else:
            parts.append((offset, part, result))
    if all(isinstance(reply, list) for _o, _w, reply in parts):
        return [section for _o, _w, reply in parts for section in reply]
    return Halved(parts)


# ---------------------------------------------------------------------------
# Post-processing: apply LLM actions (sequential, order-dependent)
# ---------------------------------------------------------------------------


def _coerce_section(sec: dict) -> dict:
    """
    Normalise an LLM-returned section to the expected shape: title str,
    content str|list, tables/figures lists. The reader checks that the reply
    is one object with a list of sections, not what is in each section.
    """
    if not isinstance(sec, dict):
        return {"title": "", "content": "", "tables": [], "figures": [],
                "_action": "keep"}
    out = dict(sec)
    title = out.get("title", "")
    out["title"] = title if isinstance(title, str) else str(title)
    content = out.get("content", "")
    out["content"] = content if isinstance(content, (str, list)) else ""
    tables = out.get("tables", [])
    out["tables"] = tables if isinstance(tables, list) else []
    figures = out.get("figures", [])
    out["figures"] = figures if isinstance(figures, list) else []
    return out


def _apply_actions(
    processed_sections: list[dict],
    previous_kept: Optional[dict],
) -> tuple[list[dict], Optional[dict]]:
    """
    Applies the _action directives returned by the LLM.

    Returns:
        (result_sections, last_kept_section)
        where last_kept_section is a reference to the last kept/merged section
        so the next window can merge into it if needed.
    """
    result: list[dict] = []

    for sec in processed_sections:
        sec = _coerce_section(sec)
        action = sec.pop("_action", "keep")

        if action == "remove":
            # A removal may not take tables or figures with it. They are Stage-2
            # artefacts with their own transcriptions, not the model's to throw
            # away, and a section whose body is nothing but [pNN_tbl0] markers
            # looks empty to a reader of the text alone. Eleven plans lost this
            # way: no text layer, so every section was markers, "remove" looked
            # right, and 1270 transcribed tables and figures went with them.
            if sec.get("tables") or sec.get("figures"):
                log.warning(
                    "  Refusing to remove '%s': it carries %d table(s) and "
                    "%d figure(s)", sec.get("title", "?"),
                    len(sec.get("tables") or []), len(sec.get("figures") or []))
            else:
                log.debug(f"  Removing section: {sec.get('title', '?')}")
                continue

        if action == "merge_into_previous":
            target = result[-1] if result else previous_kept
            if target is not None:
                merge_content = sec.get("content", "")
                if isinstance(merge_content, list):
                    merge_content = " ".join(merge_content)
                existing = target.get("content", "")
                if isinstance(existing, list):
                    existing = " ".join(existing)
                target["content"] = (existing + " " + merge_content).strip()
                target.setdefault("tables", []).extend(sec.get("tables", []))
                target.setdefault("figures", []).extend(sec.get("figures", []))
                target.setdefault("segments", []).extend(sec.get("segments", []))
                log.debug(
                    f"  Merged '{sec.get('title', '?')}' into "
                    f"'{target.get('title', '?')}'"
                )
                continue
            else:
                log.debug(
                    f"  Cannot merge '{sec.get('title', '?')}' "
                    f"(no previous section) – keeping"
                )

        # "keep" or "replace" → include in output
        result.append(sec)

    last_kept = result[-1] if result else previous_kept
    return result, last_kept


# ---------------------------------------------------------------------------
# Page provenance: carry per-segment page info through the LLM rewrite
# ---------------------------------------------------------------------------

# Placeholder markers the LLM is instructed to preserve verbatim, e.g.
# "[p5_tbl0]" / "[p3_img2]". They are the only anchor between an input segment
# and the output section that ends up owning it.
_REF_RE = re.compile(r"\[([A-Za-z0-9_]+)\]")
_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


def _content_str(section: dict) -> str:
    """Section content as a single string (literature content is a list)."""
    c = section.get("content", "")
    if isinstance(c, list):
        c = " ".join(str(x) for x in c)
    return c or ""


def _tokens(text: str) -> list[str]:
    return [w.lower() for w in _TOKEN_RE.findall(text or "")]


def _block_ids_of_output(section: dict) -> set[str]:
    """Block ids an LLM output section claims: markers in its content plus the
    ids in its (LLM-distributed) tables/figures arrays."""
    if not isinstance(section, dict):
        return set()
    ids = set(_REF_RE.findall(_content_str(section)))
    for item in (section.get("tables") or []) + (section.get("figures") or []):
        if isinstance(item, dict) and item.get("id"):
            ids.add(item["id"])
    return ids


def _block_ids_of_input(section: dict) -> set[str]:
    """Block ids an input section owns (from its segment refs + tables/figures)."""
    ids = set()
    for seg in section.get("segments") or []:
        if isinstance(seg, dict) and seg.get("ref"):
            ids.add(seg["ref"])
    for item in (section.get("tables") or []) + (section.get("figures") or []):
        if isinstance(item, dict) and item.get("id"):
            ids.add(item["id"])
    return ids


def _text_containment(seg_text: str, out_token_set: set[str]) -> float:
    """Fraction of a text segment's tokens present in an output's content."""
    toks = _tokens(seg_text)
    if not toks:
        return 0.0
    return sum(1 for t in toks if t in out_token_set) / len(toks)


def _pick_monotone(cands: list[int], cursor: int) -> int:
    """Pick an output index for a segment, preferring not to move backwards in
    reading order (keeps a split's segments in order)."""
    forward = [c for c in cands if c >= cursor]
    return min(forward) if forward else max(cands)


def _pick_target(cands: list[int], cursor: int, page, out_pages: list[set]) -> int:
    """Among equally-scoring text candidates, prefer one that already holds this
    segment's own page (keeps same-page content together), then reading order."""
    if page is not None:
        same_page = [c for c in cands if page in out_pages[c]]
        if same_page:
            return _pick_monotone(same_page, cursor)
    return _pick_monotone(cands, cursor)


def _positional_consistent(inputs: list[dict], outputs: list[dict]) -> bool:
    """True if a 1:1 positional reattach is trustworthy, i.e. each output's
    block ids are a subset of its positional input's. Guards against a
    same-length window that nonetheless rearranged content."""
    for inp, out in zip(inputs, outputs):
        if not _block_ids_of_output(out).issubset(_block_ids_of_input(inp)):
            return False
    return True


def _redistribute_segments(
    inputs: list[dict], outputs: list[dict], *, shrink: bool
) -> None:
    """
    Re-home every input segment onto the output section that contains it. Used
    when the section count changed (a split, or a section dropped by omission).

      * table/figure segments → matched by their globally-unique block id;
      * text segments → the child with the highest token containment, ties
        broken toward the child that already holds the segment's own page, then
        reading order.

    Relies on the Stage-3 invariant that a text segment never spans a page
    boundary, so a split can never cut one.

    Anchorless orphans are dropped from provenance rather than force-attached to
    an arbitrary survivor, which would phantom-cite a page the child does not
    hold. A table/figure whose marker the LLM dropped keeps a best-effort home
    only on a split, never on a shrink.
    """
    pool = [seg for inp in inputs for seg in (inp.get("segments") or [])
            if isinstance(seg, dict)]
    out_block_ids = [_block_ids_of_output(o) for o in outputs]
    out_tokens = [set(_tokens(_content_str(o))) for o in outputs]
    assigned: list[list[dict]] = [[] for _ in outputs]
    out_pages: list[set] = [set() for _ in outputs]
    cursor = 0

    for seg in pool:
        target: Optional[int] = None
        is_media = seg.get("kind") in ("table", "figure") and bool(seg.get("ref"))
        if is_media:
            cands = [j for j, bids in enumerate(out_block_ids)
                     if seg["ref"] in bids]
            if cands:
                target = _pick_monotone(cands, cursor)
        else:
            scores = [_text_containment(seg.get("text", ""), out_tokens[j])
                      for j in range(len(outputs))]
            best = max(scores) if scores else 0.0
            if best > 0:
                cands = [j for j, s in enumerate(scores) if s == best]
                target = _pick_target(cands, cursor, seg.get("page"), out_pages)

        if target is None:
            # No anchor / no overlap.
            if is_media and not shrink and outputs:
                target = min(cursor, len(outputs) - 1)
            else:
                log.warning(
                    "Stage 4: dropping unanchored %s segment (page %s) from "
                    "provenance — it matched no output section",
                    seg.get("kind"), seg.get("page"),
                )
                continue

        assigned[target].append(seg)
        if seg.get("page") is not None:
            out_pages[target].add(seg["page"])
        cursor = max(cursor, target)

    for out, segs in zip(outputs, assigned):
        out["segments"] = segs


def _thread_provenance(inputs: list[dict], outputs: list[dict]) -> None:
    """
    Reattach page provenance (segments → pages) from the input window onto the
    LLM's cleaned output sections, in place.

    A same-length, positionally-consistent window reattaches 1:1; anything else
    goes through `_redistribute_segments`. Pages are finalised per output
    afterwards either way.
    """
    if not inputs:
        for out in outputs:
            out["segments"] = list(out.get("segments") or [])
            _finalize_pages(out)
        return

    if len(outputs) == len(inputs) and _positional_consistent(inputs, outputs):
        for inp, out in zip(inputs, outputs):
            out["segments"] = list(inp.get("segments") or [])
    else:
        _redistribute_segments(inputs, outputs, shrink=len(outputs) < len(inputs))

    for out in outputs:
        _finalize_pages(out)


def _reattach_media_bbox(inputs: list[dict], outputs: list[dict]) -> None:
    """
    Stamp each output table/figure's layout ``bbox`` from the Stage-3 input,
    keyed on the globally-unique block id. Tables/figures are re-emitted by the
    LLM, which may drop or mangle the bbox it was shown.
    """
    bbox_by_id: dict[str, list] = {}
    for sec in inputs:
        if not isinstance(sec, dict):
            continue
        for item in (sec.get("tables") or []) + (sec.get("figures") or []):
            if isinstance(item, dict) and item.get("id") and item.get("bbox") is not None:
                bbox_by_id[item["id"]] = item["bbox"]
    if not bbox_by_id:
        return
    for sec in outputs:
        if not isinstance(sec, dict):
            continue
        for item in (sec.get("tables") or []) + (sec.get("figures") or []):
            if isinstance(item, dict):
                b = bbox_by_id.get(item.get("id"))
                if b is not None:
                    item["bbox"] = b


def _finalize_pages(section: dict) -> None:
    """Recompute a section's `pages` (and page_number) in place from its
    segments and its tables'/figures' page numbers. Falls back to the section's
    own page_number when nothing else carries one."""
    pages: set[int] = set()
    for seg in section.get("segments") or []:
        if isinstance(seg, dict) and seg.get("page") is not None:
            pages.add(seg["page"])
    for item in (section.get("tables") or []) + (section.get("figures") or []):
        if isinstance(item, dict) and item.get("page_number") is not None:
            pages.add(item["page_number"])
    if not pages and section.get("page_number") is not None:
        pages.add(section["page_number"])
    section["pages"] = sorted(pages)
    if section.get("page_number") is None and section["pages"]:
        section["page_number"] = section["pages"][0]


def _backfill_empty_pages(sections: list[dict]) -> None:
    """
    A kept, content-bearing section that finalised with no pages inherits an
    approximate page from its nearest neighbour, so it stays citable.
    """
    for i, sec in enumerate(sections):
        if sec.get("pages") or _is_empty_section(sec):
            continue
        page = None
        for j in range(i - 1, -1, -1):
            if sections[j].get("pages"):
                page = sections[j]["pages"][-1]
                break
        if page is None:
            for j in range(i + 1, len(sections)):
                if sections[j].get("pages"):
                    page = sections[j]["pages"][0]
                    break
        if page is not None:
            sec["pages"] = [page]
            if sec.get("page_number") is None:
                sec["page_number"] = page
            log.warning(
                "Stage 4: section %r had no page provenance; inherited page %d "
                "from a neighbour", sec.get("title", "?"), page,
            )


# ---------------------------------------------------------------------------
# Rule-based helpers
# ---------------------------------------------------------------------------


def _is_empty_section(sec: dict) -> bool:
    """True if a section carries no content, no tables, and no figures."""
    content = sec.get("content", "")
    if isinstance(content, list):
        content = " ".join(content)
    has_content = bool(content.strip())
    has_tables = bool(sec.get("tables"))
    has_figures = bool(sec.get("figures"))
    return not has_content and not has_tables and not has_figures


# Leading numbering prefix. A 1–2 digit bare number is stripped; 4-digit years
# are not.
_TITLE_NUM_PREFIX_RE = re.compile(
    r"^\s*(?:"
    r"\d+(?:[.\-]\d+)+[.\)]?"   # 3.3.3  / 4-1
    r"|\d{1,2}[.\)]?"           # 6  / 11.  / 7)
    r"|[A-Z][.\)]"             # A.  / B)
    r"|[IVXLCDM]{1,6}[.\)]"     # IV.  / VII)
    r")\s+"
)


def _normalize_title(title: str) -> str:
    """
    Strip leading numbering prefixes and de-shout ALL-CAPS titles (preserving
    short acronyms like KWP / CO2). The "[LITERATURE]" sentinel is left
    untouched.
    """
    if not isinstance(title, str):
        return title
    t = title.strip()
    if not t or t == "[LITERATURE]":
        return title
    # Prefixes can stack ("6.1 Foo").
    prev = None
    while prev != t:
        prev = t
        t = _TITLE_NUM_PREFIX_RE.sub("", t).strip()
    alpha = [c for c in t if c.isalpha()]
    if len(alpha) > 5 and all(c.isupper() for c in alpha):
        def _fix(w: str) -> str:
            core = [c for c in w if c.isalpha()]
            if core and len(core) <= 4 and all(c.isupper() for c in core):
                return w  # acronym (KWP, CO2, …)
            return w[:1] + w[1:].lower()
        t = " ".join(_fix(w) for w in t.split())
    return t or title


# ---------------------------------------------------------------------------
# Core: parallel window processing + sequential assembly
# ---------------------------------------------------------------------------


def reply_shapes() -> dict:
    """{name: schema} of what this stage sends as the grammar of its requests,
    for the preflight to put to the server before the first document.

    The window schema is built per window from the keys it carries, so the
    probe's is built from a section of the shape stage 3 writes: text, a table
    and a figure, one of them with a caption the model may leave null."""
    sample = {"title": "Title", "content": "Text.", "page_number": 1,
              "tables": [{"id": "p1_tbl0", "path": "images/p1_tbl0.png",
                          "page_number": 1, "caption": None}],
              "figures": [{"id": "p1_img0", "path": "images/p1_img0.png",
                           "page_number": 1, "caption": "Caption"}]}
    window = (replies.CORRECTIONS if REFINE_RETURN_CORRECTIONS
              else replies.window([sample]))
    return {"refined_sections": window, "section_cuts": replies.SPLIT}


def _make_splitter(client) -> Callable[..., dict | Hole]:
    """A JSON call for the split prompt: the one object read, or a Hole.

    The reply schema is the grammar of the request. A reply that is not
    exactly one object with a `cuts` list is asked again with its cause named,
    like a window's. One that was cut off is not asked again as it stands: it
    is a Hole("cut_off") that `split._ask_cuts` answers by asking for half of
    the outline, or, when the outline has no halves, with *again*: one
    further attempt with more room (`_further_tokens`), or the Hole at once
    where the served window leaves none. A request the server refused is a
    Hole("refused"). What is a Hole is cut mechanically in split.py, and said
    so in the report: the mechanical cut is less clever, never wrong.

    A request the server did not answer is asked again like a window's, and
    raises NotServed when it stays that way: cut mechanically because of an
    outage, the section would keep those cuts for good.
    """
    def ask(system_prompt: str, user_content: str, again: bool = False):
        temperature = split_temperature()
        max_tokens = split_max_tokens()
        if again:
            asked = max_tokens
            max_tokens = _further_tokens(asked, "Split request")
            if max_tokens is None:
                return Hole("cut_off", f"{asked} tokens")
        base_messages = [{"role": "system", "content": system_prompt},
                         {"role": "user", "content": user_content}]
        messages = list(base_messages)
        outcome: Optional[Hole] = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = client.chat.completions.create(
                    model=LLM_MODEL,
                    messages=messages,
                    response_format=providers.grammar("section_cuts",
                                                      replies.SPLIT),
                    temperature=temperature,
                    max_tokens=max_tokens,
                    extra_body=request_extras(),
                )
            except Exception as e:
                status = _client_error_status(e)
                if status is not None:
                    log.error("   Split request rejected (HTTP %d): %s",
                              status, e)
                    return Hole("refused", f"HTTP {status}")
                log.warning(f"   Split attempt {attempt}/{MAX_RETRIES}: "
                            f"LLM request failed: {e}")
                if attempt == MAX_RETRIES:
                    raise NotServed(str(e)) from e
                messages = list(base_messages)
                _backoff(attempt)
                continue
            try:
                usage.reply(response, LLM_MODEL)
                choice = reading.first(response)
                found, cause, said = reading.read(choice, key="cuts")
                if not cause:
                    return found
            except Exception as e:
                log.exception("   Split reply: reading it failed in the "
                              "stage itself")
                return Hole("error", f"{type(e).__name__}: {e}")
            if cause == "cut_off":
                log.warning("   Split reply cut off at %d tokens", max_tokens)
                return Hole("cut_off", f"{max_tokens} tokens")
            log.warning(f"   Split attempt {attempt}/{MAX_RETRIES}: {cause} "
                        f"reply")
            outcome = Hole(cause)
            content = getattr(getattr(choice, "message", None), "content", None)
            messages = base_messages + [
                {"role": "assistant",
                 "content": _echo(content) if isinstance(content, str) else ""},
                {"role": "user", "content": said},
            ]
            _backoff(attempt)
        return outcome
    return ask


def refine_sections(sections: list[dict],
                    report: Optional[dict] = None,
                    done: Optional[dict] = None,
                    left: Optional[dict] = None) -> list[dict]:
    """
    Processes all sections through the LLM in windows of WINDOW_SIZE, dispatched
    in parallel but assembled in order (merge/split semantics are positional).

    Mutates *sections* in place (source_text is stripped); returns the refined
    list. When *report* is given, it is filled with what this pass could not
    refine: the windows (or the parts of a window) that ended as a hole, each
    with its cause, and the sections whose cut the model did not place. See
    run_refine, which writes it next to the output. A report that already
    holds `mechanical_cuts` (from the pass that cut the sections, on a resume)
    keeps them.

    *done* resumes an unfinished pass: {window index: reply} over *sections*
    as that pass cut them, so they are not cut again and only the other
    windows are asked. Raises Unfinished when the server did not serve a
    window; nothing is assembled then, because a window that was never
    answered would go into the output as text that needed no change.

    *left*, when given, is filled with what the next pass over the same input
    needs to ask only the windows that ended as a hole: the sections as this
    pass cut them, and the reply of every window that was read.
    """
    if not sections:
        return sections

    # source_text is a QA reference for the downstream image processing; it
    # stays in sections.json, which imageprocessing reads separately.
    _strip_table_source_text(sections)

    # One shared client for every call below: it is thread-safe, so the workers
    # can share it. max_retries=0 leaves retry control to our own loop.
    try:
        client = providers.client(
            "llm",
            base_url=LLM_BASE_URL,
            api_key=LLM_API_KEY,
            timeout=LLM_TIMEOUT,
            max_retries=0,
        )
    except ImportError:
        raise ImportError(
            "openai package not installed.\n  pip install openai"
        )

    # Cut oversized sections FIRST. A window has to echo every section it
    # carries, so a section too long to be one chunk is also too long to echo —
    # which is how those sections used to pass through unrefined.
    mechanical = list((report or {}).get("mechanical_cuts") or [])
    if done is None:
        try:
            sections = split_oversized(sections, ask=_make_splitter(client),
                                       holes=mechanical)
        except NotServed as lost_cut:
            raise Unfinished(None, {}, [], 0) from lost_cut
    done = done or {}

    log.info(
        f"Stage 4: {len(sections)} sections, window size {WINDOW_SIZE}, "
        f"parallel slots {LLM_NUM_PARALLEL}"
    )

    # ── Build all windows ────────────────────────────────────────────────
    windows: list[list[dict]] = []
    i = 0
    while i < len(sections):
        windows.append(sections[i : i + WINDOW_SIZE])
        i += WINDOW_SIZE

    total_windows = len(windows)
    log.info(f"Stage 4: {total_windows} windows to process")

    # ── Parallel dispatch ────────────────────────────────────────────────
    ordered_results: dict[int, tuple] = {}

    with ThreadPoolExecutor(max_workers=LLM_NUM_PARALLEL) as executor:
        futures = {}
        for win_idx, window in enumerate(windows):
            if isinstance(done.get(win_idx), list):
                ordered_results[win_idx] = (done[win_idx], window)
                continue
            # Read-only context for merges across the window boundary.
            prev_ctx = windows[win_idx - 1][-1] if win_idx > 0 else None
            future = executor.submit(_ask_window, window, client, prev_ctx)
            futures[future] = (win_idx, window)

        for future in futures:  # iterate in submission order
            win_idx, window = futures[future]
            try:
                llm_result = future.result()
                ordered_results[win_idx] = (llm_result, window)
                status = ("NOT SERVED" if llm_result is NOT_SERVED
                          else f"hole ({llm_result.cause})"
                          if isinstance(llm_result, Hole)
                          else "partly read" if isinstance(llm_result, Halved)
                          else "ok")
                log.info(
                    f"  Stage 4: window {win_idx + 1}/{total_windows} → {status}"
                )
            except Exception as e:
                # An error of the stage's own, not of the server: a hole with
                # that cause, and the traceback in the log.
                log.exception(
                    f"  Stage 4: window {win_idx + 1} exception: {e}"
                )
                ordered_results[win_idx] = (
                    Hole("error", f"{type(e).__name__}: {e}"), window)

    lost = [i for i in range(total_windows)
            if ordered_results[i][0] is NOT_SERVED]
    if lost:
        raise Unfinished(
            sections,
            {i: reply for i, (reply, _window) in ordered_results.items()
             if isinstance(reply, list)},
            lost, total_windows, mechanical)

    # A window that keeps its original text hands those very sections to the
    # next one, which may merge into them. What a next pass starts from is the
    # sections as they were cut, and the replies as they were read: both are
    # copied before anything is threaded or merged, since a merge extends the
    # lists of the reply it merges into, and a resume would merge them twice.
    cut = copy.deepcopy(sections) if left is not None else None
    read = ({i: copy.deepcopy(reply) for i, (reply, _window)
             in ordered_results.items() if isinstance(reply, list)}
            if left is not None else None)

    # ── Sequential assembly (order matters for merge_into_previous) ──────
    refined: list[dict] = []
    previous_kept: Optional[dict] = None
    # A window (or the part of one) that is a hole keeps its original text,
    # which is indistinguishable in the output from a window that needed no
    # change, so the only place this can be recorded is here, while it
    # happens. Without it, "what is still unrefined?" can only be guessed at
    # from the output, and a guess calibrated for one refinement mode reads
    # the other one backwards.
    failed: list[dict] = []

    def _note_failure(win_idx: int, start: int, part: list,
                      cause: str) -> None:
        first = win_idx * WINDOW_SIZE + start
        failed.append({
            "window": win_idx + 1,
            "reason": cause,
            "sections": [first + n for n in range(len(part))],
            "titles": [str(s.get("title") or "")[:80] for s in part],
        })

    for win_idx in range(total_windows):
        llm_result, window = ordered_results[win_idx]
        # A window that was asked in halves and not read in all of them is
        # assembled part by part; every other window is one part.
        parts = (llm_result.parts if isinstance(llm_result, Halved)
                 else [(0, window, llm_result)])

        for start, part, result in parts:
            if isinstance(result, Hole):
                cause = result.cause
            else:
                # The LLM occasionally emits a bare string where a section
                # object belongs; drop those before provenance threading.
                result = [s for s in result if isinstance(s, dict)]
                cause = "" if result else "wrong_shape"

            if cause:
                _note_failure(win_idx, start, part, cause)
                log.warning(
                    f"  Stage 4: window {win_idx + 1}/{total_windows} "
                    f"(section(s) {start + 1} to {start + len(part)} of it): "
                    f"{cause}, keeping originals"
                )
                for sec in part:
                    sec.pop("_action", None)
                refined.extend(part)
                previous_kept = part[-1] if part else previous_kept
            else:
                _thread_provenance(part, result)
                applied, previous_kept = _apply_actions(result, previous_kept)
                refined.extend(applied)

    log.info(f"Stage 4: {len(refined)} sections after LLM refinement")

    _reattach_media_bbox(sections, refined)

    # ── Post-filter: remove empty sections ───────────────────────────────
    before = len(refined)
    refined = [s for s in refined if not _is_empty_section(s)]
    removed = before - len(refined)
    if removed:
        log.info(f"Stage 4: removed {removed} empty section(s)")

    # Keep each section's page span self-consistent after merges/splits.
    for s in refined:
        _finalize_pages(s)
    _backfill_empty_pages(refined)

    if TITLE_CLEANUP_ENABLE:
        for s in refined:
            s["title"] = _normalize_title(s.get("title", ""))

    log.info(f"Stage 4: {len(refined)} sections final")
    _report_dropped_text(sections, refined)
    if report is not None:
        report["total_windows"] = total_windows
        report["failed_windows"] = failed
        report["mechanical_cuts"] = mechanical
    if left is not None:
        # What a window that was read is worth keeping: a hole is asked again,
        # and so is a window whose reply held no section.
        asked_again = {entry["window"] - 1 for entry in failed}
        left["sections"] = cut
        left["total_windows"] = total_windows
        left["windows"] = {i: reply for i, reply in read.items()
                           if i not in asked_again}
    if failed:
        log.warning("Stage 4: %d window(s) of %d (%d section(s)) kept their "
                    "original text; hole(s) by cause: %s",
                    len({e["window"] for e in failed}),
                    total_windows, sum(len(e["sections"]) for e in failed),
                    _count_causes(entry["reason"] for entry in failed))
    if mechanical:
        log.warning("Stage 4: %d section(s) were cut mechanically, the "
                    "model's cuts being unusable; section(s) by cause: %s",
                    len(mechanical),
                    _count_causes(entry["why"] for entry in mechanical))
    return refined


def _tally(causes) -> dict:
    """{cause: how many of the units given are that cause's}."""
    counted: dict = {}
    for cause in causes:
        counted[cause] = counted.get(cause, 0) + 1
    return counted


def _count_causes(causes) -> str:
    """'cut_off 2, wrong_shape 1': the causes of a pass's holes, with how many
    units each is the cause of (the caller says which units)."""
    return ", ".join(f"{cause} {n}" for cause, n
                     in sorted(_tally(causes).items()))


def _hole_entry(output_dir: Path, report: dict) -> dict:
    """What a document left unread, in the units each number counts: the
    windows (and sections of them) that kept their original text, with the
    cause of each hole, and the sections that were cut mechanically."""
    failed = report.get("failed_windows") or []
    return {"document": output_dir.name,
            "windows": len({entry["window"] for entry in failed}),
            "sections": sum(len(entry["sections"]) for entry in failed),
            "holes": _tally(entry["reason"] for entry in failed),
            "mechanical": _tally(entry["why"] for entry
                                 in report.get("mechanical_cuts") or [])}


def _shingles(text: str, width: int = 5) -> set:
    """Hashes of every *width*-word run, so survival can be tested in O(1).

    Substring search would be the obvious way and is unusable here: 3000
    sections times 8 probes against seven megabytes of output is hundreds of
    gigabytes of scanning at the end of a stage that already took an hour.
    """
    words = text.split()
    return {hash(" ".join(words[i:i + width]))
            for i in range(max(0, len(words) - width + 1))}


def _report_dropped_text(before: list, after: list) -> None:
    """Say which sections did not make it into the output, and how big they were.

    Two bugs got through this stage unnoticed because nothing here said what
    came out of it. Both were section loss: one dropped any section a reply
    failed to mention, the other filed corrections under the wrong section.
    Counts alone hid them, because the count legitimately falls — a book's
    index and its list of abbreviations are meant to be removed here.

    So this reports the removals in full instead of judging them. A healthy
    run names its front and back matter, and 'Index', 'A', 'C' in that list
    reads very differently from a chapter title. The judgement is the
    reader's; the facts are no longer missing.
    """
    try:
        kept = set()
        for section in after:
            kept |= _shingles(_text_of(section))
        dropped, words = [], 0
        for section in before:
            body = _text_of(section)
            if len(body.split()) < 6:
                continue
            probes = list(_shingles(body))[:24]
            if probes and not any(p in kept for p in probes):
                dropped.append((len(body.split()), section.get("title") or "?"))
                words += len(body.split())
        total = sum(len(_text_of(s).split()) for s in before)
        log.info("Stage 4: %d words in, %d out (%+.2f%%)", total,
                 sum(len(_text_of(s).split()) for s in after),
                 100 * (sum(len(_text_of(s).split()) for s in after) - total)
                 / max(1, total))
        if not dropped:
            return
        log.info("Stage 4: %d section(s) removed entirely, %d words (%.1f%%); "
                 "largest: %s", len(dropped), words, 100 * words / max(1, total),
                 ", ".join(f"{title!r} ({n} words)"
                           for n, title in sorted(dropped, reverse=True)[:6]))
    except Exception as exc:                      # a report may never break a run
        log.debug("Stage 4: could not report dropped text: %s", exc)


def _text_of(section: dict) -> str:
    content = section.get("content")
    if isinstance(content, list):                 # [LITERATURE] holds BibTeX
        return "\n".join(str(part) for part in content)
    return content if isinstance(content, str) else ""


# ---------------------------------------------------------------------------
# File-level entry point
# ---------------------------------------------------------------------------


def run_refine(output_dir: Path, data: Optional[dict] = None,
               force: bool = False,
               holes: Optional[list] = None) -> Optional[dict]:
    """
    Refines the Stage-3 sections and writes sections_refined.json under
    *output_dir*. An existing final output is returned from cache without
    re-running the LLM; *force* ignores it and runs the LLM again.

    *data* is the Stage-3 result dict; when None, sections.json is read
    from *output_dir* instead.

    Forcing must not delete the old output first. dump_json_atomic replaces it
    in one step at the end, so a run killed part-way — a batch timeout, a job
    hitting its wall clock — leaves the previous refinement rather than nothing
    at all. A document with no refined output is left out by the merge, and
    would vanish from the database.

    A pass the server did not serve every window of writes no refined output.
    What it did get is kept beside it (REFINEMENT_PARTIAL_JSON), and the next
    run, forced or not, asks only for the windows that are missing.

    *holes*, when given, gets one entry (`_hole_entry`) for a document this
    pass wrote with windows that kept their original text, or sections cut
    mechanically: what a caller counts to say what a run left unread.

    A pass that was served every window and could not read some of them (a
    hole, with its cause) writes the refined output with those windows in
    their original text, names them in the report, and keeps the other
    windows' replies in REFINEMENT_PARTIAL_JSON as well: the next plain run
    asks exactly the windows the report lists, and the file goes when none is
    left.

    Returns:
        The refined output dict, or None on failure.
    """
    final_path = output_dir / SECTIONS_REFINED_JSON
    partial_path = output_dir / REFINEMENT_PARTIAL_JSON
    partial = _read_partial(partial_path)

    if final_path.exists() and not force and partial is None:
        log.info(f"Stage 4: cache hit → {final_path}")
        with open(final_path, encoding="utf-8") as f:
            return json.load(f)

    if data is None:
        input_path = output_dir / SECTIONS_JSON
        if not input_path.exists():
            log.error(f"Stage 4: {input_path} not found")
            return None
        log.info(f"Stage 4: loading {input_path}")
        with open(input_path, encoding="utf-8") as f:
            data = json.load(f)

    sections = data.get("sections", [])
    log.info(f"Stage 4: {len(sections)} sections loaded")

    # What the pass strips first, stripped before the key is taken: a caller
    # that hands the same sections in again hashes what was hashed before.
    _strip_table_source_text(sections)
    key = _partial_key(sections)
    done = None
    if partial is not None and partial.get("key") != key:
        log.warning("Stage 4: the unfinished pass in %s is of another input, "
                    "prompt or window size — not resumed", partial_path)
        partial_path.unlink()
        partial = None
        if final_path.exists() and not force:
            log.info(f"Stage 4: cache hit → {final_path}")
            with open(final_path, encoding="utf-8") as f:
                return json.load(f)
    if partial is not None:
        sections = partial["sections"]
        done = {int(index): reply
                for index, reply in partial["windows"].items()}
        log.info("Stage 4: resuming an unfinished pass, %d window(s) kept",
                 len(done))

    report: dict = {}
    if partial is not None:
        # The sections were cut by the pass that wrote this file, which
        # recorded the cuts the model did not place. A file from before that
        # was recorded has no such key, and says: none recorded.
        report["mechanical_cuts"] = list(partial.get("mechanical_cuts") or [])
    left: dict = {}
    try:
        # A third argument only when there is something to resume.
        refined = (refine_sections(sections, report, left=left) if done is None
                   else refine_sections(sections, report, done, left=left))
    except Unfinished as unfinished:
        if unfinished.sections is None:
            log.error("Stage 4: %s: the model server did not serve the cut "
                      "of an oversized section — nothing is written as "
                      "refined. Run the stage again.", output_dir.name)
            return None
        # The report stays as it is: it describes the refined output beside
        # it, and this pass wrote none.
        dump_json_atomic(clean_data(
            {"key": key, "sections": unfinished.sections,
             "total_windows": unfinished.total,
             "unserved_windows": [n + 1 for n in unfinished.lost],
             "mechanical_cuts": unfinished.mechanical,
             "windows": {str(index): reply
                         for index, reply in unfinished.done.items()}}),
            partial_path)
        log.error("Stage 4: %s: the model server did not serve %d of %d "
                  "window(s) — nothing is written as refined. Run the stage "
                  "again and only those are asked.", output_dir.name,
                  len(unfinished.lost), unfinished.total)
        return None

    result = {"sections": refined}
    result = clean_data(result)

    unread = bool(report.get("failed_windows"))
    if unread:
        # Before the output: a run that ends between the two files leaves an
        # output that its next run finishes, not one that reads as done.
        dump_json_atomic(clean_data(
            {"key": key, "sections": left["sections"],
             "total_windows": left["total_windows"],
             "unserved_windows": [],
             "mechanical_cuts": report.get("mechanical_cuts") or [],
             "windows": {str(index): reply
                         for index, reply in left["windows"].items()}}),
            partial_path)
    dump_json_atomic(result, final_path)
    log.info(f"Stage 4: refined output written → {final_path}")
    if partial_path.exists() and not unread:
        partial_path.unlink()
    _write_report(report, output_dir)
    if holes is not None and (report.get("failed_windows")
                              or report.get("mechanical_cuts")):
        holes.append(_hole_entry(output_dir, report))

    return result


def _partial_key(sections: list) -> str:
    """What an unfinished pass must agree with to be resumed: the sections
    it was given, the prompts and the model it asked, the size of its
    windows. Half a document from one model and half from another is not
    one refinement."""
    return hashlib.sha256(json.dumps(
        {"sections": sections, "window": WINDOW_SIZE, "model": LLM_MODEL,
         "prompts": prompts.versions(PROMPT_IDS)},
        ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _read_partial(path: Path) -> Optional[dict]:
    """The unfinished pass beside the output, or None."""
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            partial = json.load(f)
    except (OSError, ValueError):
        return None
    usable = (isinstance(partial, dict)
              and isinstance(partial.get("sections"), list)
              and isinstance(partial.get("windows"), dict))
    return partial if usable else None


def _write_report(report: dict, output_dir: Path) -> None:
    """The stage's own account of what it could not refine.

    Written on every run, failures or none: an empty list means "this pass
    checked and nothing failed", while a missing file means "nobody has
    looked" — a distinction the output files themselves cannot make. Wrapped,
    because a bookkeeping file must never end a refinement run that produced
    its actual output a line earlier.
    """
    try:
        dump_json_atomic(report, output_dir / REFINEMENT_REPORT_JSON)
    except Exception as exc:                       # pragma: no cover - defensive
        log.warning("Stage 4: could not write the refinement report (%s)", exc)