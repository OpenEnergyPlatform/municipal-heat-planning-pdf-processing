"""
answer.py – One retrieval-and-answer turn, with no user interface attached.

The chat app and the batch runner ask the same question of the same corpus;
only what they do with the progress and the result differs. So everything the
turn needs from the outside — the open corpus, how to embed a query, where an
image lives, and an optional progress reporter — is passed in.

Author: Felix Vossel
"""
from __future__ import annotations

import hashlib
import logging
import os
import sqlite3
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from . import chunker, code_exec, config, db, llm_client, request_log
from . import faiss_store, wording

log = logging.getLogger(__name__)


@contextmanager
def _silent(_label: str):
    yield


@dataclass
class Corpus:
    """The open resources one turn works on."""
    conn: sqlite3.Connection
    index: Any
    id_to_pos: dict
    # query item -> (vector, came_from_cache)
    embed: Callable[[dict], tuple]
    # stored image path -> a readable path, or None
    resolve_image: Callable[[Optional[str]], Optional[Path]] = lambda p: None
    log_conn: Optional[sqlite3.Connection] = None


def scopes_are_visual(scopes: list) -> bool:
    """True if the query targets ONLY figure/table scopes → caption-style anchor."""
    return bool(scopes) and all(s in config.VISUAL_SCOPES for s in scopes)


def _write_temp_image(image_bytes: bytes) -> str:
    fd, path = tempfile.mkstemp(suffix=".png")
    with os.fdopen(fd, "wb") as fh:
        fh.write(image_bytes)
    return path


def _code_context(items: list, top_hits: list) -> dict:
    """Table markdown of the sources in this batch, for the code sandbox.

    A retrieved table carries its markdown in `text` — fetch_owner_content has
    no `markdown` key, and reading one silently handed the sandbox an empty
    context on every turn.
    """
    out = {}
    for it in items:
        hit = top_hits[it["index"]]
        if hit.get("owner_kind") == "table" and hit.get("text"):
            out[str(it["index"])] = hit["text"]
    return out


def _image_requester(corpus: Corpus, document_id: int):
    """Resolve a [p17_img1] the model asked for into an item with a readable crop.

    Returns None when the id is unknown or its file is missing — the caller then
    tells the model the picture is unavailable instead of leaving it waiting.
    """
    def _request(block_id: str) -> Optional[dict]:
        item = db.request_item(corpus.conn, document_id, block_id)
        if item is None:
            log.info("Model asked for unknown block id %r", block_id)
            return None
        path = corpus.resolve_image(item.get("image_path"))
        item["image_path"] = str(path) if path is not None else None
        return item

    return _request


def answer_question(task: str, corpus: Corpus, document_id: int, scopes: list, *,
                    image_bytes: Optional[bytes] = None, image_only: bool = False,
                    as_json: bool = False, history: Optional[list] = None,
                    progress: Callable = _silent) -> dict:
    """
    Execute one full retrieval + answer turn. Returns a dict with:
    answer (str|None), answer_text (str|None), citations (list[dict]),
    n_findings (int), cache_hit (bool), n_hits (int), phrase (str|None),
    as_json (bool), n_batches (int), compute (list), examined, recheck,
    n_excluded.

    answer is None when nothing was retrieved or nothing could be grounded.
    """
    result = {"answer": None, "answer_text": None, "citations": [], "n_findings": 0,
              "cache_hit": False, "n_hits": 0, "phrase": None, "as_json": as_json,
              "n_batches": 0, "compute": [], "examined": [], "recheck": False,
              "n_excluded": 0, "requested": []}

    start_time = time.time()

    # --- 1) build the query item, per mode ---
    tmp_path = None
    recheck = False
    if image_bytes is not None and image_only:
        mode = "image"
        tmp_path = _write_temp_image(image_bytes)
        item = {"image": tmp_path}
        phrase = None
    elif image_bytes is not None:
        mode = "image+text"
        with progress("🔎 Search anchor (image+text)"):
            phrase, recheck = llm_client.make_search_phrase(task, visual=True,
                                                            history=history)
        tmp_path = _write_temp_image(image_bytes)
        item = {"text": phrase, "image": tmp_path}
    else:
        mode = "text"
        with progress("🔎 Search anchor"):
            phrase, recheck = llm_client.make_search_phrase(
                task, visual=scopes_are_visual(scopes), history=history)
        item = {"text": phrase}
    result["phrase"] = phrase
    result["recheck"] = recheck

    # A re-check ("schau noch einmal nach") searches PAST the sources earlier
    # attempts already examined — otherwise it re-reads the same top sources and
    # can only repeat itself. Walk back through the whole re-check chain to the
    # original question, or the second re-check resurfaces the first turn's
    # sources.
    exclude = set()
    if recheck:
        for turn in reversed(history or []):
            exclude.update((k, i) for k, i in turn.get("examined", []))
            if not turn.get("recheck"):
                break
    result["n_excluded"] = len(exclude)

    # --- 2) embed ---
    with progress("🧮 Embedding"):
        query_vec, cache_hit = corpus.embed(item)
    result["cache_hit"] = cache_hit
    if tmp_path:
        try:
            Path(tmp_path).unlink()
        except OSError:
            pass

    # --- 3) scoped retrieval ---
    with progress("📚 Retrieval"):
        embedding_types = [t for s in scopes for t in config.SCOPE_TO_EMBEDDING_TYPES[s]]
        hits = faiss_store.retrieve(
            corpus.conn, corpus.index, corpus.id_to_pos, document_id, embedding_types,
            query_vec, config.TOP_K, exclude=exclude,
        )
    result["n_hits"] = len(hits)
    if not hits:
        _log(corpus, document_id, task or phrase or "", mode, scopes, start_time,
             n_hits=0, error_message="No hits")
        return result

    # --- 4) answer across the top sources in context-safe batches; a further
    #        batch runs only while the answer is still incomplete ---
    top_hits = hits[: config.MAX_CHUNK_ATTEMPTS]
    # The real tokenizer, not the char/4 heuristic: German prose runs ~3.0-3.5
    # chars per token and table markdown lower still, so a batch packed as
    # 10k "tokens" was really 12-14k and overran the context it was sized for.
    # get_tokenizer() falls back to the heuristic on its own when offline.
    batches = chunker.pack_chunks(top_hits, config.ANSWER_CONTEXT_TOKENS,
                                  tokenizer=chunker.get_tokenizer())
    citations, seen = [], set()
    prior_text = None
    off_envelope = False
    examined = set()
    requested_items: list[dict] = []
    with progress("🔍 Answer from the sources"):
        for bi, chunk in enumerate(batches, start=1):
            items = chunk.items
            # Sources the LLM actually reads this turn; a later re-check of the
            # same question searches past exactly these.
            examined.update((top_hits[it["index"]]["owner_kind"],
                             top_hits[it["index"]]["owner_id"]) for it in items)
            # Attach the table/figure crops so values that exist only in a chart
            # can be read off the image (capped; downscaled in llm_client).
            images = {}
            for it in items:
                if len(images) >= config.ANSWER_MAX_IMAGES:
                    break
                img = corpus.resolve_image(top_hits[it["index"]].get("image_path"))
                if img is not None:
                    images[it["index"]] = str(img)
            # Text answer during batching; JSON formatting happens once at the end.
            code_ctx = _code_context(items, top_hits) if code_exec.is_enabled() else None
            out = llm_client.answer_from_sources(
                task, items, prior=prior_text, as_json=False,
                code_runner=(code_exec.run_code if code_exec.is_enabled() else None),
                code_context=code_ctx, max_compute=config.CODE_EXEC_MAX_ROUNDS,
                history=history, images=images or None,
                image_requester=_image_requester(corpus, document_id),
                max_image_requests=config.REQUEST_IMAGE_MAX)
            for req in out.get("requested") or []:
                if req.get("delivered") and req.get("owner_kind"):
                    requested_items.append(req)
                    examined.add((req["owner_kind"], req["owner_id"]))
            result["compute"].extend(out.get("compute") or [])
            off_envelope = off_envelope or bool(out.get("off_envelope"))
            attached = set(out.get("attached_images") or [])
            item_by_index = {it["index"]: it for it in items}
            for s in out.get("supports", []):
                try:
                    idx = int(s.get("index"))
                except (TypeError, ValueError):
                    continue
                it = item_by_index.get(idx)
                if it is None or not (0 <= idx < len(top_hits)):
                    continue
                if s.get("image"):
                    # Read off an attached crop: no verbatim quote can exist, the
                    # validated substitute is the reading + the flagged rendering.
                    quote = llm_client.visual_reading(s, attached)
                    visual = True
                else:
                    quote = llm_client.grounded_quote(s.get("quote", ""), it)
                    visual = False
                if quote is None:
                    continue
                hit = top_hits[idx]
                key = (hit["owner_kind"], hit["owner_id"])
                if key in seen:
                    continue
                seen.add(key)
                citations.append({**hit, "quote": quote, "visual": visual})
            if out.get("found"):
                prior_text = out.get("answer")
            result["n_batches"] = bi
            if out.get("complete") and citations:
                break     # fully answered → don't scan the remaining batches
    result["examined"] = sorted(examined)

    # A crop the model asked for cannot be cited through `supports`: it carries no
    # index in the batch it was handed to. Without a citation of its own the whole
    # answer would count as ungrounded and be discarded below — so the request
    # itself is the citation, and it is marked visual, which sends it through the
    # focused read-off that turns a caption into an actual value.
    for req in requested_items:
        key = (req["owner_kind"], req["owner_id"])
        if key in seen:
            continue
        hit = db.fetch_owner_content(corpus.conn, req["owner_kind"], req["owner_id"])
        if hit is None:
            continue
        seen.add(key)
        citations.append({**hit, "quote": (hit.get("title") or "").strip()
                                  or (hit.get("text") or "")[:160],
                          "visual": True, "requested": True})
    result["requested"] = [r["block_id"] for r in requested_items]

    # Re-read every image-derived value in a focused single-image call and fold
    # the results into the answer. The big call above only IDENTIFIES which
    # figure carries the answer; with ten sources and several charts in one
    # prompt it misreads (returned a stack's total height as one segment).
    visual_cits = [c for c in citations if c.get("visual")]
    if visual_cits and prior_text:
        readings = []
        with progress("🔬 Refine the read-off"):
            for cit in visual_cits[: config.READOFF_MAX_CALLS]:
                img = corpus.resolve_image(cit.get("image_path"))
                if img is None:
                    continue
                ro = llm_client.read_off_image(task, str(img), cit["quote"])
                if ro:
                    cit["quote"] = ro["reading"]
                    readings.append(f"{chunker.citation_label(cit)}: {ro['reading']}")
            if readings:
                prior_text = llm_client.revise_with_readings(task, prior_text, readings)

    # Deterministic marking of read-off values: the prompt asks for the phrase,
    # but only this guarantees it. In JSON output the schema may leave no room
    # for it — there the flagged citation below the answer is the channel.
    # Marker and note are the profile's: with the wrong language the marker
    # never matches and the note is stapled to every figure-backed answer.
    readoff_marker, readoff_note = wording.readoff()
    if prior_text and any(c.get("visual") for c in citations) \
            and readoff_marker.casefold() not in prior_text.casefold():
        prior_text = prior_text.rstrip() + "\n\n" + readoff_note
    if not citations or not prior_text:      # nothing grounded → refuse (anti-hallucination)
        # An off-envelope reply is a model failure, not an absent fact — logging
        # both as "no citations" makes the two indistinguishable after the fact.
        _log(corpus, document_id, task or phrase or "", mode, scopes, start_time,
             n_hits=result["n_hits"],
             error_message=("Answer ignored the response envelope" if off_envelope
                            else "No grounded citations"))
        return result

    # --- 5) final answer (format to JSON once at the end, if requested) ---
    result["answer_text"] = prior_text          # prose answer, for follow-up context
    if as_json:
        with progress("🧩 As JSON"):
            result["answer"] = llm_client.format_as_json(task, prior_text)
    else:
        result["answer"] = prior_text
    result["citations"] = citations
    result["n_findings"] = len(citations)

    answer_hash = hashlib.sha256((result["answer"] or "").encode()).hexdigest()[:12]
    _log(corpus, document_id, task or phrase or "", mode, scopes, start_time,
         n_hits=result["n_hits"], n_citations=result["n_findings"],
         answer_hash=answer_hash)
    return result


def _log(corpus: Corpus, document_id, question, mode, scopes, start_time, **kw) -> None:
    if corpus.log_conn is None:
        return
    request_log.log_request(corpus.log_conn, document_id, question, mode, scopes,
                            latency_ms=(time.time() - start_time) * 1000,
                            cache_hit=False, **kw)
