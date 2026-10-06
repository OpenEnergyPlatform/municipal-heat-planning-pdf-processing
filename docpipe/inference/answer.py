"""
answer.py: Runs one retrieval and answer turn, with no user interface
attached.

The chat app and the batch runner ask the same question of the same
corpus. Only what they do with the progress and the result differs,
so everything the turn needs from outside is passed in: the open
corpus, how to embed a query, where an image lives, and an optional
progress reporter.

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
from . import hybrid, replies, statements, wording

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
    # The word index beside the vectors (`lexical.py`), or None: the search
    # is then by meaning alone.
    lexical: Optional[sqlite3.Connection] = None
    # document id -> what a reader calls the document. Asked only when the
    # whole corpus is searched, where a source has to say whose it is.
    # Where it says nothing, the document's file name does (`_whose`).
    document_label: Callable[[Optional[int]], Optional[str]] = lambda i: None


def _whose(corpus: Corpus, document_id) -> Optional[str]:
    """What a source of a corpus-wide answer calls its document: what the
    caller's `document_label` says, else the name of its file."""
    label = corpus.document_label(document_id)
    if label:
        return label
    name = db.document_filename(corpus.conn, document_id) \
        if corpus.conn is not None else None
    return Path(name).stem if name else None


def scopes_are_visual(scopes: list) -> bool:
    """True if the query targets ONLY figure/table scopes → caption-style anchor."""
    return bool(scopes) and all(s in config.VISUAL_SCOPES for s in scopes)


def _write_temp_image(image_bytes: bytes) -> str:
    fd, path = tempfile.mkstemp(suffix=".png")
    with os.fdopen(fd, "wb") as fh:
        fh.write(image_bytes)
    return path


def _code_context(items: list, top_hits: list) -> dict:
    """The tables among this batch's sources, as the variable the compute
    prompt promises: `tables`, a list of {"caption", "markdown"}.

    A retrieved table carries its markdown in `text` — fetch_owner_content has
    no `markdown` key, and reading one silently handed the sandbox an empty
    context on every turn. The sandbox turns each key into a variable, so a
    key that is no identifier (the source's index) never arrived either.
    """
    tables = []
    for it in items:
        hit = top_hits[it["index"]]
        if hit.get("owner_kind") == "table" and hit.get("text"):
            tables.append({"caption": hit.get("title") or "",
                           "markdown": hit["text"]})
    return {"tables": tables}


def _image_requester(corpus: Corpus, document_id: Optional[int],
                     shown: tuple = ()):
    """Resolve a [p17_img1] the model asked for into an item with a readable crop.

    Returns None when the id is unknown or its file is missing — the caller then
    tells the model the picture is unavailable instead of leaving it waiting.

    A block id is unique within one document only. Over the whole corpus it
    is looked for in the documents whose passages the model was *shown*,
    and taken when exactly one of them has it: two documents with a
    p17_img1 each leave nothing to tell which was meant.
    """
    def _request(block_id: str) -> Optional[dict]:
        if document_id is not None:
            item = db.request_item(corpus.conn, document_id, block_id)
        else:
            found = [item for item in (
                db.request_item(corpus.conn, document, block_id)
                for document in dict.fromkeys(shown) if document is not None)
                if item is not None]
            item = found[0] if len(found) == 1 else None
        if item is None:
            log.info("Model asked for unknown block id %r", block_id)
            return None
        path = corpus.resolve_image(item.get("image_path"))
        item["image_path"] = str(path) if path is not None else None
        return item

    return _request


def search_hits(task: str, phrase: Optional[str], query_vec, corpus: Corpus,
                document_id: Optional[int], scopes: list, *,
                image_only: bool = False, exclude=frozenset()) -> list:
    """The passages a turn searches: the hybrid search over the scopes'
    embedding types, TOP_K of them, best first. One definition for the chat
    and for whoever measures its search, so the two cannot drift apart.

    The word index is asked with the question and its search anchor: the
    question has the names and numbers, the anchor the wording a document
    would use. An image query has no words to ask it with.
    """
    embedding_types = [t for s in scopes
                       for t in config.SCOPE_TO_EMBEDDING_TYPES[s]]
    worded = " ".join(part for part in (task, phrase) if part)
    hits = hybrid.retrieve(
        corpus.conn, corpus.index, corpus.id_to_pos, document_id,
        embedding_types, query_vec, config.TOP_K,
        text=None if image_only else worded,
        lexical_index=corpus.lexical, exclude=exclude)
    if document_id is None:
        for hit in hits:
            hit["document_label"] = _whose(corpus, hit.get("document_id"))
    return hits


def answer_question(task: str, corpus: Corpus, document_id: Optional[int],
                    scopes: list, *,
                    image_bytes: Optional[bytes] = None, image_only: bool = False,
                    as_json: bool = False, history: Optional[list] = None,
                    progress: Callable = _silent) -> dict:
    """
    Execute one full retrieval + answer turn. *document_id* None asks the
    whole corpus: every source then names its document. Returns a dict with:
    answer (str|None), answer_text (str|None), citations (list[dict]),
    n_findings (int), cache_hit (bool), n_hits (int), phrase (str|None),
    as_json (bool), n_batches (int), compute (list), examined, recheck,
    n_excluded, requested (block ids), statements (list[dict]),
    statements_made / statements_shown / statements_dropped (int, counting
    statements), faults (list of {"request", "cause"}).

    The answer is made of the statements the model wrote whose evidence
    stood in the source they cite (`statements.back`); the rest are counted
    in `statements_dropped`, never shown. Each batch is told the statements
    already checked and writes only new ones, so what was checked is carried
    forward as it was and the model cannot rewrite it. `answer_text` is the
    same statements without list marks and citation numbers, which is what a
    follow-up and a comparison read.

    answer is None when nothing was retrieved or no statement was backed.
    `faults` says which requests of the turn stayed unreadable: with no
    statement made and a fault on the answer, the sources were not read, and
    that is not "nothing found in them". `as_json` is True only when the
    answer was reshaped as JSON; where that did not happen the answer is the
    prose and `faults` says why.
    """
    with llm_client.collecting() as faults:
        result = _turn(task, corpus, document_id, scopes, faults,
                       image_bytes=image_bytes, image_only=image_only,
                       as_json=as_json, history=history, progress=progress)
    result["faults"] = list(faults)
    return result


def _turn(task: str, corpus: Corpus, document_id: Optional[int], scopes: list,
          faults: list, *, image_bytes, image_only, as_json, history,
          progress) -> dict:
    result = {"answer": None, "answer_text": None, "citations": [], "n_findings": 0,
              "cache_hit": False, "n_hits": 0, "phrase": None, "as_json": as_json,
              "n_batches": 0, "compute": [], "examined": [], "recheck": False,
              "n_excluded": 0, "requested": [], "statements": [],
              "statements_made": 0, "statements_shown": 0,
              "statements_dropped": 0, "faults": faults}

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
        hits = search_hits(task, phrase, query_vec, corpus, document_id,
                           scopes, image_only=mode == "image",
                           exclude=exclude)
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
    # The statements that stood their check, in the order they were made.
    # `made` and `dropped` count statements, not batches and not citations.
    shown: list[dict] = []
    made = dropped = 0
    examined = set()
    requested_items: list[dict] = []
    with progress("🔍 Answer from the sources"):
        for bi, chunk in enumerate(batches, start=1):
            items = chunk.items
            # Attach the table/figure crops so values that exist only in a chart
            # can be read off the image (capped; downscaled in llm_client).
            images = {}
            for it in items:
                if len(images) >= config.ANSWER_MAX_IMAGES:
                    break
                img = corpus.resolve_image(top_hits[it["index"]].get("image_path"))
                if img is not None:
                    images[it["index"]] = str(img)
            code_ctx = _code_context(items, top_hits) if code_exec.is_enabled() else None
            # The batch is told what was already said and checked, and writes
            # only what is new: a checked statement is never rewritten.
            out = llm_client.answer_from_sources(
                task, items, prior=statements.texts(shown) or None,
                code_runner=(code_exec.run_code if code_exec.is_enabled() else None),
                code_context=code_ctx, max_compute=config.CODE_EXEC_MAX_ROUNDS,
                history=history, images=images or None,
                image_requester=_image_requester(
                    corpus, document_id,
                    tuple(top_hits[it["index"]].get("document_id")
                          for it in items)),
                max_image_requests=config.REQUEST_IMAGE_MAX)
            # Sources the LLM actually read this turn; a later re-check of the
            # same question searches past exactly these. A batch whose reply
            # stayed unreadable (a half of it, where it was halved) was not
            # read, and a re-check that skipped it would never read it.
            if not out.get("fault"):
                examined.update((top_hits[it["index"]]["owner_kind"],
                                 top_hits[it["index"]]["owner_id"])
                                for it in items)
            wrote = out.get("statements") or []
            wanted = statements.blocks_named(wrote)
            delivered = {}
            for req in out.get("requested") or []:
                if req.get("delivered") and req.get("owner_kind"):
                    requested_items.append(req)
                    examined.add((req["owner_kind"], req["owner_id"]))
                    block = llm_client.crop_id(req["block_id"])
                    if block in wanted:
                        # The passage a crop the model asked for belongs to.
                        hit = db.fetch_owner_content(
                            corpus.conn, req["owner_kind"], req["owner_id"])
                        if hit is not None:
                            if document_id is None:
                                hit["document_label"] = _whose(
                                    corpus, hit.get("document_id"))
                            delivered[block] = {**req, "hit": hit}
            # Code runs are numbered from 1 in each call; a statement names its
            # run in that numbering, and is shown under the turn's.
            offset = len(result["compute"])
            result["compute"].extend(out.get("compute") or [])
            got, lost = statements.back(
                wrote, items={it["index"]: it for it in items}, hits=top_hits,
                attached=set(out.get("attached_images") or []),
                delivered=delivered, runs=out.get("compute") or [],
                run_offset=offset)
            shown += got
            made += len(got) + len(lost)
            dropped += len(lost)
            for row in lost:
                log.info("batch %d: statement dropped (%s): %.80s", bi,
                         row["why"], str(row.get("statement")))
            result["n_batches"] = bi
            if out.get("complete") and shown:
                break     # fully answered → don't scan the remaining batches
    result["examined"] = sorted(examined)
    result["requested"] = [r["block_id"] for r in requested_items]

    # What was asked for and not cited is not shown as evidence: a crop the
    # model asked for is a citation only where a statement stands on it.
    citations = statements.citations_of(shown)

    # Re-read every image-derived value in a focused single-image call. The big
    # call above only IDENTIFIES which figure carries the answer; with ten
    # sources and several charts in one prompt it misreads (returned a stack's
    # total height as one segment). The sentence of the focused call is then
    # the statement itself: the model's first wording of it is not shown.
    visual_cits = [c for c in citations if c["visual"]]
    if visual_cits:
        with progress("🔬 Refine the read-off"):
            for cit in visual_cits[: config.READOFF_MAX_CALLS]:
                img = corpus.resolve_image(cit.get("image_path"))
                if img is None:
                    continue
                ro = llm_client.read_off_image(task, str(img), cit["quote"])
                if ro:
                    cit["quote"] = ro["reading"]
                    for s in shown:
                        if s["citation"] == cit["n"]:
                            s["text"] = s["quote"] = ro["reading"]

    # Deterministic marking of read-off values: the prompt asks for the phrase,
    # but only this guarantees it. Marker and note are the profile's: with the
    # wrong language the marker never matches and the note is stapled to every
    # figure-backed answer.
    readoff_marker, readoff_note = wording.readoff()
    prose, prose_text = statements.assemble(shown, readoff_marker, readoff_note)
    result.update(
        statements=[{k: v for k, v in s.items() if k != "hit"} for s in shown],
        statements_made=made, statements_shown=len(shown),
        statements_dropped=dropped)

    if not shown:      # nothing backed → refuse (anti-hallucination)
        # Three different things end here and are told apart in the log: the
        # model's replies could not be read (the sources were not looked at),
        # statements were made and none stood its check, and the model made
        # none (it found nothing in the sources).
        unread = [f for f in faults if f["request"] == replies.ANSWER]
        said: list = []
        if made:
            why = (f"No statement backed ({dropped} of {made} statements "
                   f"dropped)")
        elif unread:
            why = (f"Reply unreadable: {len(unread)} request(s): "
                   f"{llm_client.describe_faults(unread)}")
            said = unread
        else:
            why = "No statement made"
        # An answer request left unread while others made statements is not
        # said by `why`: it stays among the faults the message adds.
        _log(corpus, document_id, task or phrase or "", mode, scopes, start_time,
             n_hits=result["n_hits"], n_statements=made, n_dropped=dropped,
             error_message=_with_faults(why, faults, said))
        return result

    # --- 5) final answer (format to JSON once at the end, if requested) ---
    result["answer_text"] = prose_text        # prose answer, for follow-up context
    result["answer"] = prose
    result["citations"] = citations
    result["n_findings"] = len(citations)
    if as_json:
        # The shape is the user's, written as prose in the task, so it is made
        # by one more call over the checked text. That call can add or leave
        # out, and nothing checks what it wrote; the citations stand below.
        formatted = None
        with progress("🧩 As JSON"):
            try:
                formatted = llm_client.format_as_json(task, prose_text)
            except llm_client.ReplyError as unread_json:
                log.warning("the answer stays prose: %s", unread_json)
        if formatted is None:
            result["as_json"] = False
        else:
            result["answer"] = formatted
            # The JSON has no marks to refer to, so the citations carry no number.
            for cit in citations:
                cit.pop("n", None)

    answer_hash = hashlib.sha256((result["answer"] or "").encode()).hexdigest()[:12]
    _log(corpus, document_id, task or phrase or "", mode, scopes, start_time,
         n_hits=result["n_hits"], n_citations=result["n_findings"],
         answer_hash=answer_hash, n_statements=made, n_dropped=dropped,
         error_message=_with_faults(None, faults, []))
    return result


def _with_faults(why: Optional[str], faults: list, said: list) -> Optional[str]:
    """The log's error message: why there is no answer, and the requests of the
    turn that stayed unreadable (those already in *why* are not said twice)."""
    rest = [f for f in faults if f not in said]
    parts = [why] if why else []
    if rest:
        parts.append(f"{len(rest)} request(s) unreadable: "
                     f"{llm_client.describe_faults(rest)}")
    return "; ".join(parts) or None


def _log(corpus: Corpus, document_id, question, mode, scopes, start_time, **kw) -> None:
    if corpus.log_conn is None:
        return
    request_log.log_request(corpus.log_conn, document_id, question, mode, scopes,
                            latency_ms=(time.time() - start_time) * 1000,
                            cache_hit=False, **kw)
