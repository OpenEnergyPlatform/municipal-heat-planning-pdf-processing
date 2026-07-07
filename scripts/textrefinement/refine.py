"""
refine.py – LLM-based section refinement via vLLM (text-refinement module).

After preprocessing (Stages 1-3) has produced a deterministic section
assembly, this module uses a local LLM (served by vLLM, reached through its
OpenAI-compatible API) to:

  1. Clean extraction artefacts (broken words, orphaned fragments, OCR noise,
     garbled Unicode, misplaced line breaks, etc.).
  2. Clean section titles and captions by removing numbering prefixes
     (e.g. "4.1", "Abbildung 2:", "Tabelle 3:", "Anhang A:", etc.).
  3. Remove sections that consist solely of structural directory pages.
  4. Convert bibliography entries into a dedicated [LITERATURE] section whose
     content is a JSON array of BibTeX strings.
  5. Merge sections that clearly belong together.
  6. Split sections that contain embedded sub-headings into separate sections.

Processing strategy:
  - Uses Qwen3.5-122B-A10B-FP8 served by a single vLLM server (config.LLM_BASE_URL).
  - response_format=json_object plus the system prompt constrain output to
    valid JSON.
  - Section windows are dispatched concurrently, up to LLM_NUM_PARALLEL
    in-flight requests; vLLM batches them server-side (continuous batching).
  - Results are collected in original order and assembled sequentially
    (merge/split actions require ordering).
  - Empty sections are removed as a post-processing step.

Author: Felix Vossel
"""
from __future__ import annotations

import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

from .config import (
    STRUCTURED_OUTPUT_JSON,
    FINAL_OUTPUT_JSON,
    LLM_MODEL,
    LLM_BASE_URL,
    LLM_API_KEY,
    LLM_TIMEOUT,
    LLM_NUM_PARALLEL,
    LLM_TEMPERATURE,
    LLM_MAX_TOKENS,
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

    Tries a direct parse first; on failure falls back to the outermost
    {...} block. Raises json.JSONDecodeError if nothing parses, so the
    caller's retry / self-correction path still triggers.
    """
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            return json.loads(m.group(0))
        raise



# ---------------------------------------------------------------------------
# vLLM (OpenAI-compatible) API wrapper
# ---------------------------------------------------------------------------


def _backoff(attempt: int) -> None:
    """Sleep between retries (skipped after the final attempt)."""
    if attempt < MAX_RETRIES:
        time.sleep(min(2 * attempt, 10))


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


def _call_llm(
    sections_window: list[dict],
    client,
    prev_context: Optional[dict] = None,
) -> Optional[list[dict]]:
    """
    Sends a window of sections to the vLLM chat-completions API and parses the
    JSON response.

    response_format=json_object plus the system prompt constrain the model to a
    valid JSON object. On a content failure (empty / missing "sections" / unparseable),
    the failed turn is fed back so the model can self-correct on the next
    attempt; the conversation is rebuilt from the original two messages each
    time so it cannot grow unboundedly. Transport errors and timeouts reset
    the conversation and back off. The wall-clock bound per request is the
    httpx client timeout configured on *client*.

    *prev_context* (the previous window's last section) is included read-only
    so the model can judge whether the first section is a continuation that
    should be merged across the window boundary.

    Retries up to MAX_RETRIES times.

    Returns:
        Parsed list of section dicts with "_action" fields, or None on failure.
    """
    # Strip page-provenance fields (segments/pages) from the LLM payload; the
    # model must not see or rewrite them. They are reattached to the cleaned
    # output afterwards (see _thread_provenance).
    stripped = [
        {k: v for k, v in s.items() if k not in ("segments", "pages")}
        for s in sections_window
    ]
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
                max_tokens=LLM_MAX_TOKENS,
                # Qwen3.5 is a reasoning model; disable thinking so the full
                # token budget goes to the JSON answer (not a <think> block that
                # truncates/empties content → JSON parse failures).
                extra_body={"chat_template_kwargs": {"enable_thinking": False}},
            )

            raw_text = response.choices[0].message.content or ""

            # Belt-and-suspenders: enable_thinking=False above should prevent a
            # <think> block, but strip one (plus stray markdown fences) anyway
            # before parsing. Without this, leaked reasoning makes json.loads
            # fail, burns the retry budget, and the whole window silently
            # falls back to the unrefined originals.
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
                    {"role": "assistant", "content": raw_text},
                    {"role": "user", "content":
                        "Your JSON is valid but missing the required 'sections' "
                        "key. Please respond with a JSON object that has a "
                        "'sections' array at the top level."},
                ]
                _backoff(attempt)
                continue

            return parsed["sections"]

        except json.JSONDecodeError as e:
            log.warning(
                f"   Attempt {attempt}/{MAX_RETRIES}: JSON parse error: {e}"
            )
            messages = base_messages + [
                {"role": "assistant", "content": raw_text},
                {"role": "user", "content":
                    f"Your response was not valid JSON. The parse error was: {e}\n"
                    f"Please fix and respond with only valid JSON."},
            ]
            _backoff(attempt)
        except Exception as e:
            # Covers connection errors and the httpx request timeout. Reset the
            # conversation (drop the failed turn) and back off before retrying.
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
    Defensively normalise an LLM-returned section to the expected shape.

    format="json" guarantees valid JSON but not a schema, so a misbehaving
    model could return wrong types (content as a dict, tables missing, …)
    that crash downstream consumers. This coerces title to str, content to
    str|list, and tables/figures to lists, dropping nothing that is usable.
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
# "[p5_tbl0]" / "[p3_img2]". They are the exact anchor between an input
# segment and the output section that ends up owning it.
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
    """Fraction of a text segment's tokens present in an output's content.
    Robust to the LLM's cleaning (de-hyphenation, whitespace) because cleaning
    preserves most tokens; used only to pick the best-matching child."""
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
    segment's own page (keeps same-page content together), then reading order.
    Guards against shared German boilerplate routing a page onto the wrong
    child."""
    if page is not None:
        same_page = [c for c in cands if page in out_pages[c]]
        if same_page:
            return _pick_monotone(same_page, cursor)
    return _pick_monotone(cands, cursor)


def _positional_consistent(inputs: list[dict], outputs: list[dict]) -> bool:
    """A 1:1 positional reattach is trustworthy only if no block marker moved
    across positions, i.e. each output's block ids are a subset of its
    positional input's. This guards the fast path against a same-length window
    that nonetheless rearranged content (e.g. a split paired with a drop)."""
    for inp, out in zip(inputs, outputs):
        if not _block_ids_of_output(out).issubset(_block_ids_of_input(inp)):
            return False
    return True


def _redistribute_segments(
    inputs: list[dict], outputs: list[dict], *, shrink: bool
) -> None:
    """
    Re-home every input segment onto the output section that actually contains
    it. Used when the section count changed (a split, or — defensively — an LLM
    that dropped a section by omission instead of marking it _action:"remove").

      * table/figure segments → matched exactly by their globally-unique block
        id (the LLM distributes the placeholders into the children verbatim);
      * text segments → the child with the highest token containment, ties
        broken toward the child that already holds the segment's own page, then
        reading order.

    Anchorless orphans are NOT force-attached to an arbitrary survivor: doing so
    would phantom-cite a page the child does not hold (e.g. a removed directory
    section leaking its page onto a neighbour). A text run that matches no child
    is dropped from provenance; a table/figure whose marker the LLM dropped keeps
    a best-effort home only on a split (never on a shrink, where the owning
    section was removed). Because Stage-3 text segments never span a page
    boundary, a split that changes page attribution falls between segments, so
    per-child pages stay correct; only total token annihilation of a run (rare —
    the prompt forbids paraphrase) costs a page, and dropping it beats a
    confident mis-citation.
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
            # No anchor / no overlap. Keep a real media page on a split (the LLM
            # merely dropped the marker), but never force anchorless text — or
            # anything on a shrink — onto an arbitrary survivor; drop it instead.
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
    Reattach fine-grained page provenance (segments → pages) from the input
    window onto the LLM's cleaned output sections.

    The LLM never sees segments/pages (they are stripped from its payload) and
    it preserves the [block_id] placeholders verbatim while keeping reading
    order. We exploit that:

      * keep / remove / merge preserve the section count → exact 1:1 positional
        reattach (guarded by `_positional_consistent`);
      * a split emits more sections than it received → `_redistribute_segments`
        re-homes each input segment onto the child that actually contains it,
        so every split child ends up with precisely its own pages.

    Pages are finalised per output afterwards, so the result is always
    self-consistent regardless of which path ran.
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
    keyed on the globally-unique block id.

    Segments carry their bbox for free (``_thread_provenance`` copies whole
    segment dicts), but tables/figures are re-emitted by the LLM, which may drop
    or mangle a numeric array it was shown. So the authoritative geometry is
    reattached deterministically here — the same philosophy as segment
    provenance — and it survives regardless of what the model echoed.
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
    """Recompute a section's `pages` (and page_number) from its segments and
    its tables'/figures' page numbers, keeping them self-consistent after
    merges/splits. Falls back to the section's own page_number for a within-page
    split child that carries no page-bearing segments or media."""
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
    Best-effort: a kept, content-bearing section that finalised with no pages
    (e.g. a within-page split child that won no segment and whose page_number
    the LLM omitted) inherits a page from its nearest neighbour, so it ingests
    as a citable chunk instead of an un-citable NULL-page row. A neighbour page
    is an approximation, but strictly better than no citation.
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


# Leading numbering prefix: hierarchical (3.3.3 / 4-1), short single number
# (6, 11, with optional trailing . or )), appendix letter (A. / B)), or roman
# numeral (IV.). A 1–2 digit bare number is stripped; 4-digit years are not.
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
    Deterministic guarantee on top of the LLM's title cleaning: strip leading
    numbering prefixes and de-shout ALL-CAPS titles (preserving short acronyms
    like KWP / CO2). The "[LITERATURE]" sentinel is left untouched.
    """
    if not isinstance(title, str):
        return title
    t = title.strip()
    if not t or t == "[LITERATURE]":
        return title
    # Strip possibly-stacked numbering prefixes ("Anhang 6.1" → handled by LLM;
    # "6.1 Foo" → "Foo").
    prev = None
    while prev != t:
        prev = t
        t = _TITLE_NUM_PREFIX_RE.sub("", t).strip()
    # De-shout an ALL-CAPS title word-by-word, keeping short acronyms intact.
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


def refine_sections(sections: list[dict]) -> list[dict]:
    """
    Processes all sections through the LLM in windows of WINDOW_SIZE.

    Windows are dispatched in parallel (up to LLM_NUM_PARALLEL concurrent
    requests to the vLLM server, which batches them). Results are collected in
    order and assembled sequentially to preserve merge/split semantics.

    Returns:
        Refined list of section dicts.
    """
    if not sections:
        return sections

    # source_text is a QA reference for the downstream image processing, not
    # something the refinement LLM should see or echo back — drop it from the
    # payload (it stays in structured_output.json, which imageprocessing reads).
    _strip_table_source_text(sections)

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

    # ── One shared OpenAI client pointed at the vLLM server, reused across all
    #    windows (thread-safe, so LLM_NUM_PARALLEL workers can share it; vLLM
    #    batches the concurrent requests server-side). max_retries=0 leaves
    #    retry control to our own loop. ─────────────────────────────────────
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

    # ── Parallel dispatch ────────────────────────────────────────────────
    ordered_results: dict[int, tuple[Optional[list[dict]], list[dict]]] = {}

    with ThreadPoolExecutor(max_workers=LLM_NUM_PARALLEL) as executor:
        futures = {}
        for win_idx, window in enumerate(windows):
            # Give each window (except the first) the previous window's last
            # original section as read-only context for boundary merges.
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

    for win_idx in range(total_windows):
        llm_result, window = ordered_results[win_idx]

        if llm_result is None:
            log.warning(
                f"  Stage 4: window {win_idx + 1}/{total_windows} failed, "
                f"keeping originals"
            )
            for sec in window:
                sec.pop("_action", None)
            refined.extend(window)
            previous_kept = window[-1] if window else previous_kept
        else:
            # Defensive: the LLM very occasionally emits a bare string where a
            # section object belongs. Drop those before provenance threading
            # (_block_ids_of_output would call .get() on the string and crash the
            # whole document); if nothing usable remains, keep the originals.
            llm_result = [s for s in llm_result if isinstance(s, dict)]
            if not llm_result:
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

    # Reattach authoritative table/figure geometry from the Stage-3 input (the
    # LLM re-emits media items and may drop the bbox it was shown).
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
    # Rescue any kept content-bearing section left without a page citation.
    _backfill_empty_pages(refined)

    # Deterministic title-cleanup guarantee (numbering prefixes + ALL-CAPS) on
    # top of the LLM's semantic pass.
    if TITLE_CLEANUP_ENABLE:
        for s in refined:
            s["title"] = _normalize_title(s.get("title", ""))

    log.info(f"Stage 4: {len(refined)} sections final")
    return refined


# ---------------------------------------------------------------------------
# File-level entry point
# ---------------------------------------------------------------------------


def run_refine(output_dir: Path, data: Optional[dict] = None) -> Optional[dict]:
    """
    Refines the Stage-3 sections via the LLM and writes
    structured_output_final.json.

    If structured_output_final.json already exists, it is loaded from cache
    and returned without re-running the LLM.

    Args:
        output_dir: The output directory; the final output is written here.
        data:       The Stage 3 result dict to refine. When None (e.g. a
                    standalone Stage 4 run), structured_output.json is read
                    from output_dir instead. Passing it in keeps a single
                    source of truth between Stage 3 and Stage 4.

    Returns:
        The refined output dict, or None on failure.
    """
    final_path = output_dir / FINAL_OUTPUT_JSON

    # ── Cache check: skip LLM if final output already exists ─────────────
    if final_path.exists():
        log.info(f"Stage 4: cache hit → {final_path}")
        with open(final_path, encoding="utf-8") as f:
            return json.load(f)

    # ── Resolve Stage 3 input (passed in, or read from disk) ─────────────
    if data is None:
        input_path = output_dir / STRUCTURED_OUTPUT_JSON
        if not input_path.exists():
            log.error(f"Stage 4: {input_path} not found")
            return None
        log.info(f"Stage 4: loading {input_path}")
        with open(input_path, encoding="utf-8") as f:
            data = json.load(f)

    sections = data.get("sections", [])
    log.info(f"Stage 4: {len(sections)} sections loaded")

    refined = refine_sections(sections)

    result = {"sections": refined}
    result = clean_data(result)

    # Write refined output (atomic: temp file + os.replace)
    dump_json_atomic(result, final_path)
    log.info(f"Stage 4: refined output written → {final_path}")

    return result