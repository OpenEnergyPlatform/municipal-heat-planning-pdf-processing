"""
refine.py – LLM-based section refinement (Stage 4).

Cleans extraction artefacts and titles, drops directory pages, converts
bibliographies to BibTeX, and merges/splits sections via an LLM.

Author: Felix Vossel
"""
from __future__ import annotations

import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Optional

from .corrections import apply_corrections
from .split import SPLIT_MAX_TOKENS, SPLIT_TEMPERATURE, split_oversized
from .config import (
    REFINEMENT_REPORT_JSON,
    SECTIONS_JSON,
    SECTIONS_REFINED_JSON,
    LLM_MODEL,
    LLM_BASE_URL,
    LLM_API_KEY,
    LLM_TIMEOUT,
    LLM_NUM_PARALLEL,
    LLM_TEMPERATURE,
    LLM_MAX_TOKENS,
    REFINE_RETURN_CORRECTIONS,
    reply_tokens,
    MAX_RETRIES,
    WINDOW_SIZE,
    SYSTEM_PROMPT,
    TITLE_CLEANUP_ENABLE,
    clean_data,
    dump_json_atomic,
)

log = logging.getLogger(__name__)


def _loads_json_object(text: str) -> dict:
    """
    Parse a JSON object from model output, tolerating a non-JSON wrapper.

    Falls back to the outermost {...} block; raises json.JSONDecodeError if
    nothing parses.
    """
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            return json.loads(m.group(0))
        raise



# ---------------------------------------------------------------------------
# LLM API wrapper
# ---------------------------------------------------------------------------


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


# A repair turn has to tell the model that its answer was unusable — it does not
# have to hand the whole answer back. Echoing it verbatim adds up to
# LLM_MAX_TOKENS on top of a window that is already ~18k tokens, which is how a
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


def _call_llm(
    sections_window: list[dict],
    client,
    prev_context: Optional[dict] = None,
) -> Optional[list[dict]]:
    """
    Sends a window of sections to the LLM and parses the JSON response.

    *prev_context* (the previous window's last section) is passed read-only so
    the model can judge whether the first section is a continuation that should
    be merged across the window boundary. Retries up to MAX_RETRIES times —
    except on a 4xx, where the window is abandoned at once: the server refused
    the request itself, so a retry of it is refused too.

    Returns:
        Parsed list of section dicts with "_action" fields, or None on failure.
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
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
    messages = list(base_messages)

    for attempt in range(1, MAX_RETRIES + 1):
        raw_text = ""
        try:
            response = client.chat.completions.create(
                model=LLM_MODEL,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=LLM_TEMPERATURE,
                # Sized to THIS window, not a flat cap: the reply is the
                # window handed back refined, so a big window needs a big
                # answer. The flat 8192 cut the JSON mid-string.
                max_tokens=reply_tokens(len(user_content.split())),
                # Reasoning models must not spend the token budget on a <think>
                # block; that truncates the JSON answer.
                extra_body={"chat_template_kwargs": {"enable_thinking": False}},
            )

            raw_text = response.choices[0].message.content or ""

            # Strip any leaked <think> block and stray markdown fences before
            # parsing.
            raw_text = re.sub(
                r"<think>.*?</think>", "", raw_text, flags=re.DOTALL
            ).strip()
            raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text)
            raw_text = re.sub(r"\s*```$", "", raw_text).strip()

            if not raw_text:
                log.warning(f"   Attempt {attempt}/{MAX_RETRIES}: empty response")
                messages = base_messages + [
                    {"role": "assistant", "content": ""},
                    {"role": "user", "content":
                        "Your response was empty. Please process the sections "
                        "and respond with valid JSON containing a 'sections' array."},
                ]
                _backoff(attempt)
                continue

            parsed = _loads_json_object(raw_text)

            if "sections" not in parsed:
                log.warning(
                    f"   Attempt {attempt}/{MAX_RETRIES}: response missing "
                    f"'sections' key"
                )
                messages = base_messages + [
                    {"role": "assistant", "content": _echo(raw_text)},
                    {"role": "user", "content":
                        "Your JSON is valid but missing the required 'sections' "
                        "key. Please respond with a JSON object that has a "
                        "'sections' array at the top level."},
                ]
                _backoff(attempt)
                continue

            if REFINE_RETURN_CORRECTIONS:
                return _materialise_corrections(parsed["sections"], sections_window)
            return parsed["sections"]

        except json.JSONDecodeError as e:
            log.warning(
                f"   Attempt {attempt}/{MAX_RETRIES}: JSON parse error: {e}"
            )
            messages = base_messages + [
                {"role": "assistant", "content": _echo(raw_text)},
                {"role": "user", "content":
                    f"Your response was not valid JSON. The parse error was: {e}\n"
                    f"Please fix and respond with only valid JSON."},
            ]
            _backoff(attempt)
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
                return None
            # Covers connection errors and the request timeout.
            log.error(
                f"   Attempt {attempt}/{MAX_RETRIES}: LLM request failed: {e}"
            )
            messages = list(base_messages)
            _backoff(attempt)

    return None


# ---------------------------------------------------------------------------
# Post-processing: apply LLM actions (sequential, order-dependent)
# ---------------------------------------------------------------------------


def _coerce_section(sec: dict) -> dict:
    """
    Normalise an LLM-returned section to the expected shape: title str,
    content str|list, tables/figures lists. JSON mode guarantees valid JSON
    but not a schema.
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


def _make_splitter(client) -> Callable[[str, str], str]:
    """A one-shot JSON call for the split prompt — no retries, no repair.

    A failed or unusable answer is not worth a second call: the mechanical
    fallback in split.py cuts the section anyway, only less cleverly.
    """
    def ask(system_prompt: str, user_content: str) -> str:
        response = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[{"role": "system", "content": system_prompt},
                      {"role": "user", "content": user_content}],
            response_format={"type": "json_object"},
            temperature=SPLIT_TEMPERATURE,
            max_tokens=SPLIT_MAX_TOKENS,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
        raw = response.choices[0].message.content or ""
        raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        return re.sub(r"\s*```$", "", raw).strip()
    return ask


def refine_sections(sections: list[dict],
                    report: Optional[dict] = None) -> list[dict]:
    """
    Processes all sections through the LLM in windows of WINDOW_SIZE, dispatched
    in parallel but assembled in order (merge/split semantics are positional).

    Mutates *sections* in place (source_text is stripped); returns the refined
    list. When *report* is given, it is filled with what this pass could not
    refine — see refine_document, which writes it next to the output.
    """
    if not sections:
        return sections

    # source_text is a QA reference for the downstream image processing; it
    # stays in sections.json, which imageprocessing reads separately.
    _strip_table_source_text(sections)

    # One shared client for every call below: it is thread-safe, so the workers
    # can share it. max_retries=0 leaves retry control to our own loop.
    try:
        from openai import OpenAI
    except ImportError:
        raise ImportError(
            "openai package not installed.\n  pip install openai"
        )
    client = OpenAI(
        base_url=LLM_BASE_URL,
        api_key=LLM_API_KEY,
        timeout=LLM_TIMEOUT,
        max_retries=0,
    )

    # Cut oversized sections FIRST. A window has to echo every section it
    # carries, so a section too long to be one chunk is also too long to echo —
    # which is how those sections used to pass through unrefined.
    sections = split_oversized(sections, ask=_make_splitter(client))

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
    ordered_results: dict[int, tuple[Optional[list[dict]], list[dict]]] = {}

    with ThreadPoolExecutor(max_workers=LLM_NUM_PARALLEL) as executor:
        futures = {}
        for win_idx, window in enumerate(windows):
            # Read-only context for merges across the window boundary.
            prev_ctx = windows[win_idx - 1][-1] if win_idx > 0 else None
            future = executor.submit(_call_llm, window, client, prev_ctx)
            futures[future] = (win_idx, window)

        for future in futures:  # iterate in submission order
            win_idx, window = futures[future]
            try:
                llm_result = future.result()
                ordered_results[win_idx] = (llm_result, window)
                status = "ok" if llm_result is not None else "FAILED"
                log.info(
                    f"  Stage 4: window {win_idx + 1}/{total_windows} → {status}"
                )
            except Exception as e:
                log.error(
                    f"  Stage 4: window {win_idx + 1} exception: {e}"
                )
                ordered_results[win_idx] = (None, window)

    # ── Sequential assembly (order matters for merge_into_previous) ──────
    refined: list[dict] = []
    previous_kept: Optional[dict] = None
    # A failed window keeps its original text, which is indistinguishable in
    # the output from a window that needed no change — so the only place this
    # can be recorded is here, while it happens. Without it, "what is still
    # unrefined?" can only be guessed at from the output, and a guess
    # calibrated for one refinement mode reads the other one backwards.
    failed: list[dict] = []

    def _note_failure(win_idx: int, window: list, reason: str) -> None:
        failed.append({
            "window": win_idx + 1,
            "reason": reason,
            "sections": [win_idx * WINDOW_SIZE + n for n in range(len(window))],
            "titles": [str(s.get("title") or "")[:80] for s in window],
        })

    for win_idx in range(total_windows):
        llm_result, window = ordered_results[win_idx]

        if llm_result is None:
            _note_failure(win_idx, window, "no usable reply")
            log.warning(
                f"  Stage 4: window {win_idx + 1}/{total_windows} failed, "
                f"keeping originals"
            )
            for sec in window:
                sec.pop("_action", None)
            refined.extend(window)
            previous_kept = window[-1] if window else previous_kept
        else:
            # The LLM occasionally emits a bare string where a section object
            # belongs; drop those before provenance threading.
            llm_result = [s for s in llm_result if isinstance(s, dict)]
            if not llm_result:
                _note_failure(win_idx, window, "no usable sections")
                log.warning(
                    f"  Stage 4: window {win_idx + 1}/{total_windows} returned "
                    f"no usable sections, keeping originals"
                )
                for sec in window:
                    sec.pop("_action", None)
                refined.extend(window)
                previous_kept = window[-1] if window else previous_kept
            else:
                _thread_provenance(window, llm_result)
                applied, previous_kept = _apply_actions(llm_result, previous_kept)
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
        if failed:
            log.warning("Stage 4: %d of %d window(s) kept their original text",
                        len(failed), total_windows)
    return refined


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
               force: bool = False) -> Optional[dict]:
    """
    Refines the Stage-3 sections and writes sections_refined.json under
    *output_dir*. An existing final output is returned from cache without
    re-running the LLM; *force* ignores it and runs the LLM again.

    *data* is the Stage-3 result dict; when None, sections.json is read
    from *output_dir* instead.

    Forcing must not delete the old output first. dump_json_atomic replaces it
    in one step at the end, so a run killed part-way — a batch timeout, a job
    hitting its wall clock — leaves the previous refinement rather than nothing
    at all. A document with no refined output is skipped by the merge without
    a word, and would vanish from the database.

    Returns:
        The refined output dict, or None on failure.
    """
    final_path = output_dir / SECTIONS_REFINED_JSON

    if final_path.exists() and not force:
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

    report: dict = {}
    refined = refine_sections(sections, report)

    result = {"sections": refined}
    result = clean_data(result)

    dump_json_atomic(result, final_path)
    log.info(f"Stage 4: refined output written → {final_path}")
    _write_report(report, output_dir)

    return result


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