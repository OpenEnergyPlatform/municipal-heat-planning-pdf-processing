"""
runner.py – Wiring the harvest loop to the live stack.

pipeline.py owns the loop and is pure; this module supplies its three
callables from the real world — FAISS retrieval with owner exclusion, the
harvesting LLM call, and locating a quote on its page in the source PDF —
plus resume stamps and the CLI. Heavy imports (faiss, torch-backed embedders, fitz)
happen inside functions: importing this module must stay cheap, or every
test that touches the package pays for a GPU stack it never uses.

Probes are embedded directly, without the QA path's HyDE anchor call: the
spec-generated queries are already precise, skipping the anchor saves one
LLM call per probe, and a stable probe string means the query-embedding
cache hits across all documents.

Author: Felix Vossel
"""
from __future__ import annotations

import argparse
import functools
import json
import logging
import os
import re
import sqlite3
import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import Callable, Optional

from docpipe import prompts
from docpipe.llm_preflight import assert_serving
from docpipe.profile import add_profile_argument, resolve_profile

from .pipeline import (Source, WorkItem, build_chains, fold_batch,
                       group_items, harvest_document, plan_document, run_chain,
                       write_report)
from .queries import expand as expand_queries
from .spec import Spec, load as load_spec

log = logging.getLogger(__name__)

LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "http://localhost:8000/v1")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "EMPTY")
LLM_MODEL = os.environ.get("LLM_MODEL", "Qwen/Qwen3.5-122B-A10B-FP8")
LLM_TIMEOUT = int(os.environ.get("LLM_TIMEOUT", "180"))
TOP_K = int(os.environ.get("EXTRACT_TOP_K", "8"))
MAX_ROUNDS = int(os.environ.get("EXTRACT_MAX_ROUNDS", "4"))
MAX_RETRIES = 3
# Requests in flight against the server, for the whole run — not per document.
# vLLM batches continuously: what it can schedule is what it is given, and a
# handful of requests leaves four H100s idle between tokens. The first pilot
# ran eight at a time and did 0.14 requests a second.
LLM_PARALLEL = int(os.environ.get("EXTRACT_LLM_PARALLEL", "128"))
# Sandbox rounds per harvest. A computed value carries its code and the code's
# output as evidence; without the sandbox the model would have to work the
# number out itself, and that number would have no evidence at all.
CODE_ROUNDS = int(os.environ.get("EXTRACT_CODE_ROUNDS", "2"))
# How many sources share one request, and how much text they may bring. The
# ceiling is the model's window minus the parameter payload, which
# context_budget measures: at 17.5k tokens of spec for kwp, six sources of
# 14k characters together leave the answer room to be written.
BATCH_SOURCES = int(os.environ.get("EXTRACT_BATCH_SOURCES", "6"))
BATCH_CHARS = int(os.environ.get("EXTRACT_BATCH_CHARS", "14000"))
# What the model is told it already has, so it does not hand back the same
# value from a neighbouring passage.
PRIOR_MAX = int(os.environ.get("EXTRACT_PRIOR_MAX", "40"))
# How often a chain may answer "there is more here, look for this" and get
# fresh passages for it. Bounded: the model can always ask again.
FOLLOWUP_ROUNDS = int(os.environ.get("EXTRACT_FOLLOWUP_ROUNDS", "1"))
# Threads for the two cheap halves: retrieval planning (FAISS + SQL) and
# verification (PyMuPDF quote location). Neither talks to the LLM server.
PLAN_PARALLEL = int(os.environ.get("EXTRACT_PLAN_PARALLEL", "8"))
# The longest stretch of source text one request may carry. A section over
# this is split into windows and each window asked separately: truncating
# would drop values silently, which is the one thing this stage may not do.
MAX_SOURCE_CHARS = int(os.environ.get("EXTRACT_MAX_SOURCE_CHARS", "16000"))
SOURCE_OVERLAP_CHARS = 400
# Tables and figures go to the model as pictures as well as text: the
# transcription IS a reading of that picture, and a model that can see both
# can notice when they disagree.
ATTACH_IMAGES = os.environ.get("EXTRACT_ATTACH_IMAGES", "1") != "0"
IMAGE_MAX_SIDE = int(os.environ.get("EXTRACT_IMAGE_MAX_SIDE", "1280"))
# A section can run over a page break; how many of its pages to try before
# giving up on placing the quote.
LOCATE_MAX_PAGES = int(os.environ.get("EXTRACT_LOCATE_MAX_PAGES", "3"))

HARVEST_PROMPT_ID = "extraction/harvest"
QUERIES_PROMPT_ID = "extraction/queries"
ANCHORS_PROMPT_ID = "extraction/anchors"
PROMPT_IDS = (HARVEST_PROMPT_ID, QUERIES_PROMPT_ID, ANCHORS_PROMPT_ID)

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
_FENCE_OPEN = re.compile(r"^```(?:json)?\s*")
_FENCE_CLOSE = re.compile(r"\s*```$")


# ---------------------------------------------------------------------------
# Retrieval: probe text -> ranked unseen owners of one document
# ---------------------------------------------------------------------------

_EMBEDDER = None
_EMBEDDER_LOCK = threading.Lock()


def embedder():
    """The one resident embedding model this run uses.

    `get_embedder()` CONSTRUCTS a backend, it does not return a shared one, and
    this call used to sit inside the per-probe `embed()`. With
    EXTRACT_PLAN_PARALLEL threads each asking for its own probes, every probe
    loaded another copy of the 8B model onto the same card: five fit into 80 GB,
    the sixth died of CUDA OOM, and with it all sixteen documents.

    The double check is not decoration — eight threads reach this together on
    the first probe, and without the lock they would each build one.
    """
    global _EMBEDDER
    if _EMBEDDER is None:
        with _EMBEDDER_LOCK:
            if _EMBEDDER is None:
                from docpipe.embedding import get_embedder
                _EMBEDDER = get_embedder()
    return _EMBEDDER


def _source_of(hit: dict, via: Optional[str] = None) -> Source:
    provenance = {"document_id": hit.get("document_id"),
                  "page": hit.get("page_number"),
                  "section_number": hit.get("section_number"),
                  "section_title": hit.get("section_title"),
                  "title": hit.get("title")}
    if via:
        provenance["via"] = via
    return Source(owner_kind=hit["owner_kind"], owner_id=hit["owner_id"],
                  text=hit.get("text") or "", provenance=provenance,
                  image_path=hit.get("image_path"))


def make_content_fetcher() -> Callable:
    """fetch_owner_content, but each owner is read from SQLite once.

    A sweep meets the same section again in the next round, and again for the
    next parameter: four parameters times four rounds is the same row read up
    to sixteen times over NFS. One planning thread owns one of these, so it
    needs no lock.
    """
    from docpipe.inference import db as inference_db

    seen: dict = {}

    def fetch(conn, owner_kind: str, owner_id: int):
        key = (owner_kind, owner_id)
        if key not in seen:
            seen[key] = inference_db.fetch_owner_content(conn, owner_kind, owner_id)
        return seen[key]

    return fetch


def make_retrieve(conn: sqlite3.Connection, index, id_to_pos: dict,
                  cache_conn, content_fetcher: Optional[Callable] = None) -> Callable:
    """(probes, document_id, exclude) -> one Source list per probe.

    Takes every probe of a sweep round at once. One sub-index for the document
    instead of one per probe, and one FAISS search over a query matrix instead
    of sixty-four searches.
    """
    from docpipe.inference import db as inference_db
    from docpipe.inference import faiss_store, query_cache

    all_types = sorted(inference_db.SECTION_EMBEDDING_TYPES
                       | inference_db.TABLE_EMBEDDING_TYPES
                       | inference_db.FIGURE_EMBEDDING_TYPES)

    def embed(probe: str):
        key = query_cache.make_key("text", text=probe, image_bytes=None)
        cached = query_cache.get(cache_conn, key)
        if cached is not None:
            return cached
        vec = embedder().embed_one({"text": probe})
        query_cache.put(cache_conn, key, vec)
        return vec

    # A sweep calls this once per parameter and per round with the same probe
    # list, and only `exclude` differs between rounds. Without these two the
    # document's sub-index is rebuilt and the identical score matrix recomputed
    # sixteen times over — four parameters by four rounds.
    document: list = [None, None]         # document_id, prepared
    search: list = [None, None]           # probe key, (scores, positions)

    def retrieve(probes: list, document_id: int, exclude: set) -> list:
        if document[0] != document_id:
            document[:] = [document_id, faiss_store.prepare_document(
                conn, index, id_to_pos, document_id, all_types)]
            search[:] = [None, None]
        key = (document_id, tuple(probes))
        if search[0] != key:
            search[:] = [key, faiss_store.search_prepared(
                document[1], [embed(p) for p in probes])]
        scores, positions = search[1]
        answers = faiss_store.rank_prepared(
            conn, document[1], scores, positions, TOP_K,
            content_fetcher=content_fetcher, exclude=exclude)
        return [[_source_of(hit) for hit in hits] for hits in answers]

    return retrieve


def make_more_sources(db_path: Path, index, id_to_pos: dict,
                      cache_path: Path) -> Callable:
    """(document_id, queries, exclude) -> the passages the model asked for.

    Retrieval a second time, but from a query the MODEL wrote rather than one
    the spec generated. It runs during the harvest, not the plan, so it opens
    its own connections per thread: the harvest pool is a hundred threads
    wide and SQLite handles are not shared across them.

    Queries the model invents are one-offs, so they miss the primed cache and
    are embedded on the spot. That is the whole cost of the round trip, and
    it only happens when the model says the passages it was given are not
    enough.
    """
    from docpipe.inference import query_cache

    local = threading.local()

    def connections():
        if getattr(local, "conn", None) is None:
            local.conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            local.conn.row_factory = sqlite3.Row
            local.cache = query_cache.connect(cache_path, create=False)
            local.fetch = make_content_fetcher()
        return local.conn, local.cache, local.fetch

    def more_sources(document_id: int, queries: list, exclude: set) -> list:
        conn, cache, fetch = connections()
        retrieve = make_retrieve(conn, index, id_to_pos, cache, fetch)
        found: list = []
        taken = set(exclude)
        try:
            for sources in retrieve(list(queries)[:4], document_id, taken):
                for source in sources:
                    key = (source.owner_kind, source.owner_id)
                    if key in taken:
                        continue
                    taken.add(key)
                    found.append(source)
        except Exception as exc:
            log.warning("   more-passages for document %s failed: %s",
                        document_id, exc)
            return []
        return found

    return more_sources


def fill_dynamic_axes(spec: Spec, vocabularies: Optional[dict]) -> Spec:
    """A copy of *spec* whose dynamic axes carry THIS document's list.

    The AR6 scenario names are run identifiers — EN_INDCi2030_300f — and two
    of 328 of them occur verbatim in the text they were extracted from. The
    document says "the Current Policies scenario". Nothing but the model can
    bridge that, and it can only do so if it is shown the list it may choose
    from; the mapping then arrives flagged, like every other judgement call
    the harvest records.
    """
    if not vocabularies:
        return spec
    parameters = []
    changed = False
    for parameter in spec.parameters:
        axes = dict(parameter.axes)
        for name, axis in parameter.axes.items():
            if axis.dynamic and vocabularies.get(name):
                axes[name] = replace(axis, vocabulary=vocabularies[name])
                changed = True
        # A category parameter whose VALUE is the choice takes the list named
        # after the parameter itself.
        values = vocabularies.get(parameter.uri)
        if parameter.vocabulary_dynamic and values:
            parameters.append(replace(parameter, axes=axes, vocabulary=values))
            changed = True
        else:
            parameters.append(replace(parameter, axes=axes))
    return Spec(parameters=parameters) if changed else spec


def make_anchors(spec: Spec, client=None) -> dict:
    """parameter uri -> search anchors the model wrote from its definition.

    The QA app turns a question into a HyDE anchor before it searches: a
    sentence written as it would READ in the document, because that is what a
    similarity search matches against. This stage searched with the spec's
    templates alone, which name the thing rather than say it.

    Once per run and per parameter, not per document: the anchor depends on the
    definition, not on the plan, and a stable probe string is what makes the
    query-embedding cache hit across the whole corpus.
    """
    prompt = prompts.load(ANCHORS_PROMPT_ID)
    client = client or _client()
    out: dict = {}

    def one(parameter):
        payload = json.dumps({"label": parameter.label,
                              "description": parameter.description},
                             ensure_ascii=False, indent=2)
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                reply = client.chat.completions.create(
                    model=LLM_MODEL,
                    temperature=float(prompt.meta.get("temperature", 0.4)),
                    max_tokens=int(prompt.meta.get("max_tokens", 800)),
                    messages=[{"role": "system", "content": prompt.text},
                              {"role": "user", "content": payload}],
                    extra_body={"chat_template_kwargs": {"enable_thinking": False}},
                ).choices[0].message.content
                parsed = _loads_object(reply)
                anchors = [a.strip() for a in (parsed or {}).get("anchors", ())
                           if isinstance(a, str) and len(a.strip()) > 20]
                if anchors:
                    return parameter.uri, anchors
            except Exception as exc:
                log.warning("anchors %s attempt %d failed: %s",
                            parameter.uri, attempt, exc)
            if attempt < MAX_RETRIES:
                time.sleep(min(2 * attempt, 6))
        # No anchors is not fatal: the templates alone are what this stage
        # searched with until now.
        log.warning("anchors %s: none generated, templates only", parameter.uri)
        return parameter.uri, []

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=min(8, len(spec.parameters) or 1)) as pool:
        for uri, anchors in pool.map(one, spec.parameters):
            out[uri] = anchors
    log.info("extraction: %d anchor(s) over %d parameter(s)",
             sum(len(v) for v in out.values()), len(out))
    for uri, anchors in out.items():
        for anchor in anchors:
            log.info("   anchor %s: %s", uri, anchor)
    return out


def probe_texts(spec: Spec, templates: list, anchors: Optional[dict] = None) -> list:
    """Every retrieval probe the run will ever send, once, order-stable."""
    seen: set = set()
    probes: list = []
    for parameter in spec.parameters:
        for probe in list(expand_queries(templates, parameter)) + list(
                (anchors or {}).get(parameter.uri, ())):
            if probe not in seen:
                seen.add(probe)
                probes.append(probe)
    return probes


def prime_probe_cache(cache_conn, spec: Spec, templates: list,
                      anchors: Optional[dict] = None) -> int:
    """Embed every probe of every parameter in one batch, before any planning.

    The probes come from the spec, not from a document, so the whole corpus
    asks the same few dozen questions. Embedded from inside the sweep they
    cost one GPU round trip per miss and put every planning thread behind the
    same lock; embedded here they cost one call, and retrieval afterwards
    reads nothing but the cache.
    """
    from docpipe.inference import query_cache

    probes = probe_texts(spec, templates, anchors)
    keys = {p: query_cache.make_key("text", text=p, image_bytes=None)
            for p in probes}
    missing = [p for p in probes if query_cache.get(cache_conn, keys[p]) is None]
    if missing:
        vectors = embedder().embed([{"text": p} for p in missing])
        query_cache.put_many(cache_conn,
                             [(keys[p], v) for p, v in zip(missing, vectors)])
    log.info("extraction: %d probe(s), %d embedded in one batch, %d cached",
             len(probes), len(missing), len(probes) - len(missing))
    return len(probes)


# ---------------------------------------------------------------------------
# Fallback: the deterministic candidate floor under the retrieval sweep
# ---------------------------------------------------------------------------

def _candidate_tokens(parameter) -> list:
    """Everything a value-bearing source could literally contain."""
    tokens = set(parameter.units_accepted)
    tokens.add(parameter.label)
    for axis in parameter.axes.values():
        if axis.dynamic:
            # A per-document list is not corpus vocabulary: adding 146 scenario
            # identifiers here would put 146 LIKE patterns in front of every
            # candidate query for words that occur in no document.
            continue
        for labels in (axis.vocabulary or {}).values():
            tokens.update(labels)
    return sorted(t for t in tokens if len(t) >= 2)


_TOKENS: dict = {}
_TOKENS_LOCK = threading.Lock()


def make_candidates(conn: sqlite3.Connection,
                    content_fetcher: Optional[Callable] = None) -> Callable:
    """Token-filtered owners of one document, straight from SQL.

    LIKE over the stored text is deliberately dumb: it is the *floor*, not
    the harvest. Retrieval finds what wording variance hides from tokens;
    this finds what ranking hides from retrieval.

    Bound to the caller's connection. It used to open its own for every call,
    which on an NFS-backed database is a file open, a header read and a schema
    parse per document and parameter.
    """
    from docpipe.inference import db as inference_db

    fetch = content_fetcher or inference_db.fetch_owner_content

    def candidates(document_id: int, parameter) -> list:
        with _TOKENS_LOCK:
            tokens = _TOKENS.get(parameter.uri)
            if tokens is None:
                tokens = _TOKENS[parameter.uri] = _candidate_tokens(parameter)
        like = lambda column: " OR ".join([f"{column} LIKE ?"] * len(tokens))
        params = [f"%{t}%" for t in tokens]
        owners: list = []
        owners += [("table", int(r[0])) for r in conn.execute(
            f"SELECT t.id FROM Tables t JOIN Sections s ON t.section = s.id "
            f"WHERE s.document = ? AND ({like('t.markdown')} OR {like('t.caption')})",
            [document_id, *params, *params])]
        owners += [("section", int(r[0])) for r in conn.execute(
            f"SELECT id FROM Sections WHERE document = ? AND ({like('content')})",
            [document_id, *params])]
        owners += [("figure", int(r[0])) for r in conn.execute(
            f"SELECT i.id FROM Images i JOIN Sections s ON i.section = s.id "
            f"WHERE s.document = ? AND ({like('i.description')})",
            [document_id, *params])]
        sources = []
        for owner_kind, owner_id in owners:
            hit = fetch(conn, owner_kind, owner_id)
            if hit is None:
                continue
            sources.append(_source_of({**hit, "owner_kind": owner_kind,
                                       "owner_id": owner_id}, via="fallback"))
        return sources

    return candidates


# ---------------------------------------------------------------------------
# Harvest: one source + one parameter -> the model's claimed tuples
# ---------------------------------------------------------------------------

def _client():
    """The one OpenAI-compatible client shape this stage uses."""
    from openai import OpenAI
    return OpenAI(base_url=LLM_BASE_URL, api_key=LLM_API_KEY,
                  timeout=LLM_TIMEOUT, max_retries=0)


def _loads_object(raw_text: str) -> Optional[dict]:
    """The JSON object in a reply, whatever it is wrapped in."""
    text = _THINK_RE.sub("", raw_text or "").strip()
    text = _FENCE_CLOSE.sub("", _FENCE_OPEN.sub("", text)).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return data if isinstance(data, dict) else None


def _parse_tuples(raw_text: str) -> Optional[list]:
    text = _THINK_RE.sub("", raw_text or "").strip()
    text = _FENCE_CLOSE.sub("", _FENCE_OPEN.sub("", text)).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    tuples = data.get("tuples") if isinstance(data, dict) else None
    return tuples if isinstance(tuples, list) else None


def _parse_reply(raw_text: str) -> Optional[dict]:
    """The whole answer object, not just its tuples.

    A batch reply says three things: what it found, whether these passages
    are exhausted for the parameter, and — when they are not — what sentence
    to search for next. Only `tuples` decides whether the reply was
    understood at all; the other two default to the conservative reading,
    which is "there may be more, but I cannot say where".
    """
    tuples = _parse_tuples(raw_text)
    if tuples is None:
        return None
    data = _loads_object(raw_text) or {}
    status = data.get("status")
    need = data.get("need_more")
    return {"tuples": tuples,
            "status": status if status in ("complete", "partial") else "partial",
            "need_more": [q for q in (need or []) if isinstance(q, str) and q.strip()]}


_UNPARSABLE_SHOWN = 0
_UNPARSABLE_LIMIT = int(os.environ.get("EXTRACT_SHOW_UNPARSABLE", "20"))


def _unparsable(reply) -> str:
    """Why a reply could not be read, for the first few that happen.

    A pilot lost 1093 of 16102 harvests to "reply carried no 'tuples' list"
    and the log could not say whether the model answered something else, was
    cut off mid-reasoning, or returned nothing at all. Bounded: the point is a
    handful of examples, not a second copy of the run in the log.
    """
    global _UNPARSABLE_SHOWN
    if _UNPARSABLE_SHOWN >= _UNPARSABLE_LIMIT:
        return ""
    _UNPARSABLE_SHOWN += 1
    message = getattr(reply, "message", None)
    content = (getattr(message, "content", None) or "")
    reasoning = (getattr(message, "reasoning_content", None) or "")
    return (f" [finish={getattr(reply, 'finish_reason', '?')} "
            f"content={len(content)}ch {content[:160]!r} "
            f"reasoning={len(reasoning)}ch {reasoning[-160:]!r}]")


def _parse_action(text) -> Optional[str]:
    """The python the model wants run, or None if it answered instead."""
    if not isinstance(text, str) or '"action"' not in text:
        return None
    try:
        start, end = text.index("{"), text.rindex("}") + 1
        obj = json.loads(text[start:end])
    except (ValueError, json.JSONDecodeError):
        return None
    if not isinstance(obj, dict) or obj.get("action") != "python":
        return None
    code = obj.get("code")
    return code if isinstance(code, str) and code.strip() else None


def _compute_reply(run: dict) -> str:
    """What the model gets back after a sandbox round."""
    if not run.get("ok"):
        return (f"Der Code lief nicht: {run.get('error') or 'unbekannt'}. "
                f"Antworte jetzt ohne Berechnung, oder korrigiere den Code.")
    out = (run.get("stdout") or "").strip()
    if not out:
        return ("Der Code lief, hat aber nichts ausgegeben. Gib jedes Ergebnis "
                "mit print() aus, oder antworte ohne Berechnung.")
    return (f"Ausgabe des Codes:\n{out}\n\nAntworte jetzt mit dem "
            f'Tupel-Objekt. Berechnete Werte tragen "computed": true.')


def _parameter_payload(parameter) -> dict:
    """What the model needs to know about the target — straight from the spec."""
    axes = {}
    for name, axis in parameter.axes.items():
        if axis.vocabulary is not None:
            # Grouped by class, not a flat label list: the model has to pick
            # ONE of these classes for the wording it read, so it needs to
            # see which spellings already belong together. The first label
            # is the class name it answers with; the rest are what the
            # corpus has been seen to call it.
            axes[name] = {"classes": {labels[0]: list(labels[1:])
                                      for labels in axis.vocabulary.values()}}
        elif axis.enum:
            axes[name] = {"enum": list(axis.enum)}
        else:
            # A wording axis, or a dynamic one the profile had no list for.
            # It used to render as {"enum": []}, which reads as "no value is
            # allowed here" — the opposite of what it means.
            axes[name] = {"type": axis.type or "text"}
    payload = {"uri": parameter.uri, "label": parameter.label,
               "description": parameter.description,
               "value_type": parameter.value_type,
               "axes": axes, "example": parameter.example}
    # Only what applies to this kind of value: a unit list in front of a
    # category would invite the model to invent one.
    if parameter.is_numeric:
        payload["units_accepted"] = sorted(parameter.units_accepted)
    elif parameter.vocabulary:
        payload["value_classes"] = {labels[0]: list(labels[1:])
                                    for labels in parameter.vocabulary.values()}
    return payload


@functools.lru_cache(maxsize=192)
def _image_data_url(path: str) -> Optional[str]:
    """The crop, read, downscaled and base64'd — once per file per run.

    Every parameter asks the same table again, so the same PNG used to be
    reopened, resampled and re-encoded once per parameter. Bounded because a
    corpus run meets thousands of crops and each one is a megabyte of base64.

    PNG, not JPEG: these crops are synthetic graphics with thin rules and
    small axis labels, exactly what JPEG artefacts blur first — and a blurred
    digit is the failure this whole stage exists to avoid. Deliberately not
    imported from llm_client, which binds the QA prompts at import time.
    """
    import base64
    import io
    try:
        from PIL import Image
        img = Image.open(path)
        if max(img.size) > IMAGE_MAX_SIDE:
            img.thumbnail((IMAGE_MAX_SIDE, IMAGE_MAX_SIDE))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
    except Exception as exc:
        log.warning("   crop not attachable (%s): %s", path, exc)
        return None
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _image_part(path: str) -> Optional[dict]:
    """A table or figure crop as a chat message part, or None if unreadable."""
    url = _image_data_url(str(path))
    return None if url is None else {"type": "image_url", "image_url": {"url": url}}


def _prior_payload(prior: list) -> list:
    """What the model is told it already has, small enough to send every time.

    Coordinates and the value, not the whole verified row: the point is that
    the model recognises a repeat, and provenance, flags and tier say nothing
    about that. The newest entries are the ones a neighbouring passage is
    likely to duplicate, so the tail is what survives the cap.
    """
    out: list = []
    for row in prior[-PRIOR_MAX:]:
        item = {k: v for k, v in row.items()
                if k not in ("provenance", "flags", "tier", "compute", "quote")
                and not k.endswith("_raw") and v is not None}
        quote = row.get("quote")
        if isinstance(quote, str):
            item["quote"] = quote[:80]
        out.append(item)
    return out


def _batch_payload(batch, prior: list) -> dict:
    """The request body: one parameter, several labelled sources, what we have."""
    sources = []
    for index, item in enumerate(batch.items):
        source = item.source
        sources.append({"id": batch.label(index), "kind": source.owner_kind,
                        "title": source.provenance.get("title"),
                        "section": source.provenance.get("section_title"),
                        "text": source.text})
    payload = {"parameter": _parameter_payload(batch.parameter),
               "sources": sources}
    if prior:
        payload["prior"] = _prior_payload(prior)
    return payload


def make_harvester(image_root: Optional[Path] = None) -> Callable:
    prompt = prompts.load(HARVEST_PROMPT_ID)
    client = _client()
    temperature = float(prompt.meta.get("temperature", 0.1))
    max_tokens = int(prompt.meta.get("max_tokens", 4096))

    # Deferred: docpipe.inference's package __init__ pulls in the whole answer
    # loop, which demands a profile at import time.
    from docpipe.inference import code_exec

    def harvest(batch, prior: Optional[list] = None) -> dict:
        payload = json.dumps(_batch_payload(batch, prior or []),
                             ensure_ascii=False, indent=2)
        compute: list = []
        # The crops ride along for tables and figures: the transcription is a
        # reading of that picture, and the model should be able to check it
        # against the picture rather than trust it. One part per source that
        # has one, in the batch's own order, so a crop stays next to the
        # label its text was given.
        content: object = payload
        parts = [{"type": "text", "text": payload}]
        for index, item in enumerate(batch.items):
            path = item.source.image_path
            if not (path and ATTACH_IMAGES):
                continue
            part = _image_part(str(image_root / path) if image_root else path)
            if part is not None:
                parts.append({"type": "text",
                              "text": f"Bild zu {batch.label(index)}:"})
                parts.append(part)
        if len(parts) > 1:
            content = parts
        first = batch.items[0].source
        conversation: list = [{"role": "user", "content": content}]
        # A compute round is a turn of the same conversation, not a retry, so
        # the attempt budget grows with the rounds actually used.
        for attempt in range(1, MAX_RETRIES + CODE_ROUNDS + 1):
            try:
                response = client.chat.completions.create(
                    model=LLM_MODEL, temperature=temperature,
                    max_tokens=max_tokens,
                    messages=[{"role": "system", "content": prompt.text},
                              *conversation],
                    # Refinement and the vision path have said this for
                    # longer than this stage has existed: a reasoning model
                    # must not spend the token budget on a think block,
                    # because that truncates the JSON answer. Extraction was
                    # the one stage that did not say it, and the pilot lost
                    # 1093 of 16102 harvests to replies with no 'tuples' in
                    # them, HTTP 200 every one.
                    extra_body={"chat_template_kwargs": {"enable_thinking": False}},
                )
                reply = response.choices[0]
                # An action object instead of an answer: the model wants the
                # sandbox. A value it works out itself would be a number with
                # no evidence; a value the sandbox works out carries the code
                # and the code's output, which is checkable without rerunning
                # anything. Bounded, and only while a round is left.
                action = _parse_action(reply.message.content)
                if action and len(compute) < CODE_ROUNDS:
                    out = code_exec.run_code(
                        action, context={
                            "sources": {batch.label(i): it.source.text
                                        for i, it in enumerate(batch.items)},
                            "title": first.provenance.get("title")})
                    compute.append({"code": action,
                                    "stdout": (out.get("stdout") or "")[:2000],
                                    "ok": bool(out.get("ok")),
                                    "error": out.get("error")})
                    conversation.append({"role": "assistant",
                                         "content": reply.message.content or ""})
                    conversation.append({"role": "user",
                                         "content": _compute_reply(compute[-1])})
                    continue
                answer = _parse_reply(reply.message.content)
                if answer is None:
                    # A reasoning parser puts the chain in reasoning_content
                    # and leaves content empty when the generation stopped
                    # inside it. The answer, if there is one, is in there.
                    answer = _parse_reply(
                        getattr(reply.message, "reasoning_content", None))
                if answer is not None:
                    if compute:
                        for t in answer["tuples"]:
                            if isinstance(t, dict):
                                t.setdefault("compute", compute)
                    return answer
                log.warning("   harvest %s/%s+%d attempt %d: reply carried no "
                            "'tuples' list%s", first.owner_kind,
                            first.owner_id, len(batch.items) - 1, attempt,
                            _unparsable(reply))
            except Exception as exc:
                log.warning("   harvest %s/%s+%d attempt %d failed: %s",
                            first.owner_kind, first.owner_id,
                            len(batch.items) - 1, attempt, exc)
                status = getattr(exc, "status_code", None)
                if isinstance(status, int) and 400 <= status < 500 and status != 429:
                    # A request the server refuses is refused every time. The
                    # last run spent three tries and eight seconds of sleep on
                    # each over-long section before writing the same sentinel.
                    break
            if attempt < MAX_RETRIES:
                time.sleep(min(2 * attempt, 6))
        # Sources the model never answered for are a hole in the harvest, and
        # holes must be visible: the caller counts these via the sentinel.
        # One per source, so a batch of six that died is six holes, not one.
        return {"tuples": [{"_harvest_failed": True,
                            "source": batch.label(i)}
                           for i in range(len(batch.items))],
                "status": "failed", "need_more": []}

    return harvest


def split_long_sources(items: list, max_chars: int = MAX_SOURCE_CHARS) -> list:
    """Work items whose source text fits one request.

    A section longer than the window used to be sent whole, rejected by the
    server with a 400, retried twice and written off — the values in it were
    lost without ever being read. Windows overlap so a number is never cut in
    half at the seam; both windows carry the same owner, so the provenance and
    the dedup that hang off it do not notice the split.
    """
    out: list = []
    for item in items:
        text = item.source.text or ""
        if len(text) <= max_chars:
            out.append(item)
            continue
        step = max(max_chars - SOURCE_OVERLAP_CHARS, 1)
        for start in range(0, len(text), step):
            window = text[start:start + max_chars]
            if not window.strip():
                continue
            part = replace(item.source, text=window)
            out.append(WorkItem(item.document_id, item.parameter, part))
            if start + max_chars >= len(text):
                break
    if len(out) != len(items):
        log.info("extraction: %d source(s) split into %d window(s) at %d chars",
                 len(items), len(out), max_chars)
    return out


def harvest_chains(chains: list, harvest: Callable,
                   more_sources: Optional[Callable] = None,
                   workers: int = LLM_PARALLEL) -> list:
    """Every chain of the whole run, in flight at once.

    Returns one [(batch, reply)] list per chain, in the order given: the
    caller folds them back into the document they belong to. Ordering is by
    index, not by completion — the server answers a 40-token table long
    before a 6000-token section, and the report must not depend on that.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    results: list = [None] * len(chains)
    if not chains:
        return results
    started = time.time()
    step = max(len(chains) // 20, 10)
    done = 0
    def one(chain: list) -> list:
        return run_chain(chain, harvest, more_sources=more_sources,
                         rounds=FOLLOWUP_ROUNDS, max_sources=BATCH_SOURCES,
                         max_chars=BATCH_CHARS)

    with ThreadPoolExecutor(max_workers=max(workers, 1)) as pool:
        futures = {pool.submit(one, c): i for i, c in enumerate(chains)}
        for future in as_completed(futures):
            index = futures[future]
            try:
                results[index] = future.result()
            except Exception as exc:                        # pragma: no cover
                batch = chains[index][0]
                log.warning("   chain %s/%s raised: %s", batch.document_id,
                            batch.parameter.uri, exc)
                results[index] = [
                    (b, {"tuples": [{"_harvest_failed": True,
                                     "source": b.label(i)}
                                    for i in range(len(b.items))],
                         "status": "failed", "need_more": []})
                    for b in chains[index]]
            done += 1
            if done % step == 0 or done == len(chains):
                elapsed = max(time.time() - started, 1e-6)
                rate = done / elapsed
                log.info("harvest: %d/%d chains (%.1f/s, %.0f s left)",
                         done, len(chains), rate,
                         (len(chains) - done) / max(rate, 1e-6))
    return results


# ---------------------------------------------------------------------------
# Where a quote sits in the source PDF
# ---------------------------------------------------------------------------

def make_locate(db_path: Path, pdf_root: Optional[Path]) -> Optional[Callable]:
    """(Source, quote) -> highlight rects in the source PDF, or None.

    Uses the same alignment the app highlights with, so a value's recorded
    provenance and the box a reader sees are produced by one implementation.
    A section can run over a page break, so the section's other pages are
    tried too - bounded, because this opens the PDF each time.
    """
    if pdf_root is None:
        return None
    from docpipe.inference.pdf_locate import page_words, rects_from_words

    # Both caches exist for the same reason: a document yields several hundred
    # located quotes, and the old path opened the PDF *and* a SQLite connection
    # for every single one of them — a file open, an xref parse and a page
    # layout per quote, over NFS. Bounded, so a corpus run cannot grow into
    # them: a page's words are some tens of kilobytes.
    words_of = functools.lru_cache(maxsize=512)(page_words)
    lock = threading.Lock()
    documents: dict = {}
    section_pages: dict = {}

    def _lookup(document_id: int, owner_kind: str, owner_id: int) -> tuple:
        with lock:
            known = document_id in documents
            filename = documents.get(document_id)
            pages = section_pages.get((owner_kind, owner_id))
        if known and (owner_kind != "section" or pages is not None):
            return filename, pages or []
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            if not known:
                row = conn.execute(
                    "SELECT filename FROM Documents WHERE id = ?",
                    (document_id,)).fetchone()
                filename = row[0] if row else None
            if owner_kind == "section" and pages is None:
                # SectionPages.page is a foreign key to Pages.id, not a page
                # number. The old query asked SectionPages for page_number,
                # raised "no such column" every single time, and the except
                # below booked it as "this schema has no SectionPages" — so a
                # section that runs over a page break only ever had its first
                # page tried.
                try:
                    pages = [int(r[0]) for r in conn.execute(
                        "SELECT pg.page_number FROM SectionPages sp "
                        "JOIN Pages pg ON sp.page = pg.id "
                        "WHERE sp.section = ? ORDER BY pg.page_number",
                        (owner_id,))]
                except sqlite3.OperationalError as exc:
                    log.warning("section pages unavailable (%s)", exc)
                    pages = []
        finally:
            conn.close()
        with lock:
            documents[document_id] = filename
            if owner_kind == "section":
                section_pages[(owner_kind, owner_id)] = pages or []
        return filename, pages or []

    def locate(source: Source, quote: str) -> Optional[list]:
        document_id = source.provenance.get("document_id")
        first_page = source.provenance.get("page")
        if not document_id:
            return None
        filename, pages = _lookup(document_id, source.owner_kind, source.owner_id)
        if filename is None:
            return None
        pdf_path = pdf_root / filename
        if not pdf_path.is_file():
            return None
        candidates = ([int(first_page)] if first_page else []) + \
                     [p for p in pages if p != first_page]
        for page in candidates[:LOCATE_MAX_PAGES]:
            rects = rects_from_words(words_of(pdf_path, page), quote)
            if rects:
                return rects
        return None

    return locate


# ---------------------------------------------------------------------------
# Resume stamps and the per-document run
# ---------------------------------------------------------------------------

def _stamp_current(spec_sha: str) -> dict:
    # The model is part of the stamp: tuples harvested by another model are
    # not "current" any more than tuples harvested with another prompt.
    return {"spec": spec_sha, "model": LLM_MODEL, **prompts.versions(PROMPT_IDS)}


def stale(stamp_path: Path, current: dict) -> list:
    """Which stamped versions differ from now; everything when unstamped."""
    if not stamp_path.is_file():
        return sorted(current)
    try:
        stored = json.loads(stamp_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return sorted(current)
    return sorted(k for k, v in current.items() if stored.get(k) != v)


def run_document(document_id: int, name: str, out_dir: Path, spec: Spec,
                 spec_sha: str, templates: list, deps: dict, *,
                 force: bool = False, force_stale: bool = False) -> bool:
    if already_done(name, out_dir, spec_sha, force=force,
                    force_stale=force_stale):
        return True
    report = harvest_document(document_id, spec, templates,
                              retrieve=deps["retrieve"],
                              harvest=deps["harvest"],
                              locate=deps.get("locate"),
                              candidates=deps.get("candidates"),
                              max_rounds=MAX_ROUNDS)
    finish_document(report, name, out_dir, spec_sha)
    return True


def already_done(name: str, out_dir: Path, spec_sha: str, *,
                 force: bool = False, force_stale: bool = False) -> bool:
    """True when this document needs no work: harvested under the current
    spec, prompts and model — or stale with nobody asking for the redo."""
    if force or not (out_dir / f"{name}.jsonl").exists():
        return False
    changed = stale(out_dir / f"{name}.stamp.json", _stamp_current(spec_sha))
    if not changed:
        log.info("extraction: %s is current — skipped", name)
        return True
    if not force_stale:
        log.warning("extraction: %s was harvested with older %s; re-run "
                    "with --force-stale to redo it", name, ", ".join(changed))
        return True
    return False


def finish_document(report, name: str, out_dir: Path, spec_sha: str) -> None:
    """Write one document's JSONL and stamp it with what produced it."""
    failed = [r for r in report.refusals
              if r.get("claim", {}).get("_harvest_failed")]
    if failed:
        log.warning("extraction: %s: %d source(s) never answered", name, len(failed))
    write_report(report, out_dir / f"{name}.jsonl")
    (out_dir / f"{name}.stamp.json").write_text(
        json.dumps(_stamp_current(spec_sha), indent=2), encoding="utf-8")


def resolve_image_root(pdf_root: Optional[Path],
                       fallback: Path) -> Path:
    """Where the table and figure crops live, given where the PDFs live.

    The crops sit next to the PDFs they were cut from, so a run that names its
    PDF root has already said where they are. Falling back to the profile's
    processed dir is only right when nothing was named: this deployment passes
    db, index and pdf root explicitly and keeps its data somewhere else
    entirely, and the profile default pointed every crop at a directory that
    does not exist — one warning per table, and a harvest that read every
    picture's transcription without the picture.
    """
    return (Path(pdf_root) / "processed") if pdf_root else Path(fallback)


# A choice list the profile fills per document is not in the spec file, so it
# cannot be measured there. This is its ceiling: the widest such list in this
# corpus is one publication's 146 AR6 scenarios beside the ~250 OEKG study
# regions, and both together stay well inside it.
DYNAMIC_LIST_TOKENS = 4000


def context_budget(prompt, spec=None) -> int:
    """Tokens one harvest request needs at worst — a floor for the server.

    Counted, not guessed: system prompt, parameter payload and JSON envelope,
    a source window at its ceiling, the crop that rides along, and the reply.
    The estimate this replaces allowed 6000 tokens for "largest source,
    generous" and no image at all, and the job script served that number as
    --max-model-len; every section over it came back as a 400.

    The payload term is measured off the spec when there is one: a parameter
    that hands the model a class list to choose from is many times the size of
    one that asks for a wording, and a flat allowance for both underserves the
    first.

    A request carries several sources now, so the text term is the batch's
    ceiling rather than one window's — and one source too long to share a
    request rides alone, which is why the larger of the two is what counts.
    Every source in a batch may bring a crop, and the prior block rides along
    on top.
    """
    payload = 2000
    if spec is not None:
        widest = max((len(json.dumps(_parameter_payload(p), ensure_ascii=False))
                      for p in spec.parameters), default=0)
        dynamic = any(p.vocabulary_dynamic or
                      any(a.dynamic for a in p.axes.values())
                      for p in spec.parameters)
        payload = max(payload, widest // 3 + 600
                      + (DYNAMIC_LIST_TOKENS if dynamic else 0))
    return int(len(prompt.text.split()) * 3
               + max(BATCH_CHARS, MAX_SOURCE_CHARS) // 3    # the batch's text
               + (1200 * BATCH_SOURCES if ATTACH_IMAGES else 0)   # its crops
               + PRIOR_MAX * 60                             # what we have already
               + payload                                    # payload + envelope
               + int(prompt.meta.get("max_tokens", 4096)))


def _documents(conn: sqlite3.Connection) -> list:
    return [(int(r[0]), str(r[1]))
            for r in conn.execute(
                "SELECT id, filename FROM Documents WHERE is_current = 1 "
                "ORDER BY filename")]


def select_documents(documents: list, wanted: Optional[list]) -> tuple:
    """(chosen, missing) for a --document restriction; no restriction = all.

    `missing` is what was asked for and is not on offer, which for this corpus
    means superseded rather than absent: `_documents` lists current versions
    only. A pilot has to hear about that instead of quietly being smaller than
    it was meant to be.
    """
    if not wanted:
        return documents, []
    ids = set(wanted)
    chosen = [d for d in documents if d[0] in ids]
    return chosen, sorted(ids - {d[0] for d in chosen})


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m docpipe.extraction",
        description="Ontology-guided value extraction over an indexed corpus")
    parser.add_argument("db", type=Path, help="SQLite corpus database")
    parser.add_argument("index", type=Path, help="FAISS index")
    parser.add_argument("out", type=Path, help="Output directory (JSONL per document)")
    parser.add_argument("--image-root", type=Path, default=None,
                        help="Processed root holding the table/figure crops "
                             "(default: the profile's processed dir)")
    parser.add_argument("--pdf-root", type=Path, default=None,
                        help="PDF directory for the digit-exact native check")
    parser.add_argument("--document", type=int, action="append", default=None,
                        metavar="ID",
                        help="Restrict the run to this document id. Repeatable, "
                             "so a pilot names its set instead of running the "
                             "corpus or paying for the index and the embedder "
                             "once per document")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--force-stale", action="store_true")
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    parser.add_argument("--print-context-budget", action="store_true",
                        help="Print the tokens one harvest request needs and "
                             "exit — job scripts feed this to --max-model-len")
    parser.add_argument("--serialize", type=Path, default=None, metavar="TTL",
                        help="No harvest: hand the JSONL in OUT to the "
                             "profile's kg.make_serializer and write TTL")
    add_profile_argument(parser)
    args = parser.parse_args(argv)
    logging.basicConfig(level=args.log_level,
                        format="%(asctime)s [%(levelname)s] %(name)s %(message)s",
                        datefmt="%H:%M:%S")

    profile = resolve_profile(args)
    if args.serialize is not None:
        factory = profile.component("kg", "make_serializer")
        if factory is None:
            parser.error(f"profile {profile.name!r} provides no "
                         f"kg.make_serializer (profiles/{profile.name}/kg.py)")
        from .serialize import run as serialize_run
        counts = serialize_run(args.out, args.serialize, factory(args.db))
        log.info("serialize: %d tuple(s) from %d document(s) -> %s",
                 sum(counts.values()), len(counts), args.serialize)
        return 0

    if args.image_root is None:
        args.image_root = resolve_image_root(args.pdf_root,
                                             profile.processed_dir)

    # component, not require: extraction is an optional stage. A profile that
    # does not do OBIE (ar6 today) must stay loadable everywhere else and only
    # fail here, when someone actually asks it to extract.
    raw_spec_path = profile.component("extraction", "SPEC_PATH")
    if raw_spec_path is None:
        parser.error(f"profile {profile.name!r} does not configure the "
                     f"extraction stage (profiles/{profile.name}/extraction.py "
                     f"with SPEC_PATH)")
    spec_path = Path(raw_spec_path)
    spec = load_spec(spec_path)
    import hashlib
    spec_sha = hashlib.sha256(spec_path.read_bytes()).hexdigest()
    templates = [line for line in
                 prompts.load(QUERIES_PROMPT_ID).text.splitlines()
                 if line.strip() and not line.lstrip().startswith("#")]
    # Optional: (connection, document_id) -> {axis name: {uri: [labels]}} for
    # the axes the spec declares dynamic.
    document_axes = profile.component("extraction", "document_axes")

    required = context_budget(prompts.load(HARVEST_PROMPT_ID), spec)
    if args.print_context_budget:
        print(required)
        return 0
    assert_serving(LLM_BASE_URL, LLM_API_KEY, LLM_MODEL, required,
                   what="extraction", flag="--max-model-len")

    from concurrent.futures import ThreadPoolExecutor, as_completed

    from docpipe.inference import faiss_store, query_cache
    index, id_to_pos = faiss_store.load_global_index(args.index)
    args.out.mkdir(parents=True, exist_ok=True)
    if ATTACH_IMAGES and not Path(args.image_root).is_dir():
        # Loud here, at second one. The alternative is what happened last
        # time: a warning per crop, buried in half a million log lines, while
        # the harvest read every table without its picture.
        parser.error(f"image root {args.image_root} is not a directory — "
                     f"every table and figure crop would be missing. Pass "
                     f"--image-root, or EXTRACT_ATTACH_IMAGES=0 to harvest "
                     f"from the transcriptions alone")
    harvest = make_harvester(args.image_root)     # OpenAI client is thread-safe
    locate = make_locate(args.db, args.pdf_root)

    listing = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    try:
        # `with` on a connection commits, it does not close.
        documents = _documents(listing)
    finally:
        listing.close()
    documents, missing = select_documents(documents, args.document)
    if missing:
        log.error("%d named document(s) not found or not current: %s",
                  len(missing), ", ".join(str(m) for m in missing))
        return 1

    documents = [(did, fn) for did, fn in documents
                 if not already_done(Path(fn).stem, args.out, spec_sha,
                                     force=args.force,
                                     force_stale=args.force_stale)]
    if not documents:
        log.info("extraction: nothing to harvest")
        return 0

    # Documents are batched in groups only so the plan of a 1000-document run
    # fits in memory: every group is still one flat batch of requests, which
    # is the whole point. A pilot is one group.
    group_size = int(os.environ.get("EXTRACT_BATCH_DOCS", "64"))
    log.info("extraction: %d document(s), %d parameter(s), top_k=%d, "
             "max_rounds=%d, plan_parallel=%d, llm_parallel=%d, group=%d",
             len(documents), len(spec.parameters), TOP_K, MAX_ROUNDS,
             PLAN_PARALLEL, LLM_PARALLEL, group_size)

    # One call per parameter, before anything is planned: the anchors depend on
    # the definition, not on the document, and a probe string that is the same
    # for the whole corpus is what makes the query-embedding cache pay.
    anchors = ({} if os.environ.get("EXTRACT_ANCHORS", "1") == "0"
               else make_anchors(spec))

    cache_path = args.out / "query_cache.db"
    primer = query_cache.connect(cache_path)
    prime_probe_cache(primer, spec, templates, anchors)
    primer.close()
    more_sources = make_more_sources(args.db, index, id_to_pos, cache_path)

    def plan(document_id: int, filename: str) -> tuple:
        # Both connections per thread, cache included. Sharing one across the
        # pool would rest on SQLite being built serialized, and the priming
        # above already means every read here is a hit.
        conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        cache_conn = query_cache.connect(cache_path, create=False)
        try:
            # One memo per document: retrieval and the fallback floor meet the
            # same section in every round and for every parameter.
            fetch = make_content_fetcher()
            # A dynamic axis only becomes a closed list here, where the
            # document is known.
            doc_spec = spec
            if document_axes is not None:
                lists = document_axes(conn, document_id)
                doc_spec = fill_dynamic_axes(spec, lists)
                if lists:
                    # The one line that says whether the model was given a
                    # choice at all: an empty list means it was asked to pick
                    # from nothing and every answer will come back unmapped.
                    log.info("extract: %s: choice lists %s", Path(filename).stem,
                             ", ".join(f"{k}={len(v)}"
                                       for k, v in sorted(lists.items())))
            items, report = plan_document(
                document_id, doc_spec, templates, extra_probes=anchors,
                retrieve=make_retrieve(conn, index, id_to_pos, cache_conn, fetch),
                candidates=make_candidates(conn, fetch), max_rounds=MAX_ROUNDS)
            return Path(filename).stem, split_long_sources(items), report
        finally:
            conn.close()
            cache_conn.close()

    def verify(entry: tuple) -> None:
        name, report, answered = entry
        for batch, reply in answered:
            fold_batch(batch, reply, report, locate=locate)
        finish_document(report, name, args.out, spec_sha)

    started = time.time()
    failures = 0
    for offset in range(0, len(documents), group_size):
        group = documents[offset:offset + group_size]

        # ---- Plan: retrieval and SQL, not one model request ----------------
        plans: list = []
        with ThreadPoolExecutor(max_workers=PLAN_PARALLEL) as pool:
            futures = {pool.submit(plan, did, fn): fn for did, fn in group}
            for future in as_completed(futures):
                try:
                    plans.append(future.result())
                except Exception:
                    failures += 1
                    log.exception("extraction: planning %s failed",
                                  futures[future])
        # A chain belongs to exactly one document, so the chains are built per
        # document and the replies come back where they can be folded.
        chains: list = []
        owners: list = []
        for name, items, report in plans:
            for chain in build_chains(items, max_sources=BATCH_SOURCES,
                                      max_chars=BATCH_CHARS):
                chains.append(chain)
                owners.append(name)
        sources = sum(len(b.items) for c in chains for b in c)
        log.info("extraction: group %d/%d planned — %d chain(s) over %d "
                 "source(s) in %d document(s)", offset // group_size + 1,
                 (len(documents) - 1) // group_size + 1, len(chains), sources,
                 len(plans))

        # ---- Harvest: every chain at once, its batches in order -------------
        answered = harvest_chains(chains, harvest, more_sources, LLM_PARALLEL)

        # ---- Verify and write, document by document ------------------------
        by_document: dict = {}
        for name, pairs in zip(owners, answered):
            by_document.setdefault(name, []).extend(pairs or [])
        entries = [(name, report, by_document.get(name, []))
                   for name, _, report in plans]
        with ThreadPoolExecutor(max_workers=PLAN_PARALLEL) as pool:
            futures = {pool.submit(verify, e): e[0] for e in entries}
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception:
                    failures += 1
                    log.exception("extraction: %s failed", futures[future])

    log.info("extraction: done in %.0f s, %d failure(s)",
             time.time() - started, failures)
    return 1 if failures else 0
