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

from .pipeline import (Source, WorkItem, fold_claims, harvest_document,
                       plan_document, write_report)
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
PROMPT_IDS = (HARVEST_PROMPT_ID, QUERIES_PROMPT_ID)

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

    def retrieve(probes: list, document_id: int, exclude: set) -> list:
        answers = faiss_store.retrieve_many(
            conn, index, id_to_pos, document_id, all_types,
            [embed(p) for p in probes], TOP_K,
            content_fetcher=content_fetcher, exclude=exclude)
        return [[_source_of(hit) for hit in hits] for hits in answers]

    return retrieve


def probe_texts(spec: Spec, templates: list) -> list:
    """Every retrieval probe the run will ever send, once, order-stable."""
    seen: set = set()
    probes: list = []
    for parameter in spec.parameters:
        for probe in expand_queries(templates, parameter):
            if probe not in seen:
                seen.add(probe)
                probes.append(probe)
    return probes


def prime_probe_cache(cache_conn, spec: Spec, templates: list) -> int:
    """Embed every probe of every parameter in one batch, before any planning.

    The probes come from the spec, not from a document, so the whole corpus
    asks the same few dozen questions. Embedded from inside the sweep they
    cost one GPU round trip per miss and put every planning thread behind the
    same lock; embedded here they cost one call, and retrieval afterwards
    reads nothing but the cache.
    """
    from docpipe.inference import query_cache

    probes = probe_texts(spec, templates)
    keys = {p: query_cache.make_key("text", text=p, image_bytes=None)
            for p in probes}
    missing = [p for p in probes if query_cache.get(cache_conn, keys[p]) is None]
    if missing:
        vectors = embedder().embed([{"text": p} for p in missing])
        for probe, vector in zip(missing, vectors):
            query_cache.put(cache_conn, keys[probe], vector)
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
        elif axis.type == "int":
            axes[name] = {"type": "int"}
        else:
            axes[name] = {"enum": list(axis.enum or ())}
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


def make_harvester(image_root: Optional[Path] = None) -> Callable:
    from openai import OpenAI
    prompt = prompts.load(HARVEST_PROMPT_ID)
    client = OpenAI(base_url=LLM_BASE_URL, api_key=LLM_API_KEY,
                    timeout=LLM_TIMEOUT, max_retries=0)
    temperature = float(prompt.meta.get("temperature", 0.1))
    max_tokens = int(prompt.meta.get("max_tokens", 4096))

    def harvest(source: Source, parameter) -> list:
        payload = json.dumps(
            {"parameter": _parameter_payload(parameter),
             "source": {"kind": source.owner_kind,
                        "title": source.provenance.get("title"),
                        "section": source.provenance.get("section_title"),
                        "text": source.text}},
            ensure_ascii=False, indent=2)
        # The crop rides along for tables and figures: the transcription is a
        # reading of that picture, and the model should be able to check it
        # against the picture rather than trust it.
        content: object = payload
        if source.image_path and ATTACH_IMAGES:
            part = _image_part(str(image_root / source.image_path)
                               if image_root else source.image_path)
            if part is not None:
                content = [{"type": "text", "text": payload}, part]
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = client.chat.completions.create(
                    model=LLM_MODEL, temperature=temperature,
                    max_tokens=max_tokens,
                    messages=[{"role": "system", "content": prompt.text},
                              {"role": "user", "content": content}])
                tuples = _parse_tuples(response.choices[0].message.content)
                if tuples is not None:
                    return tuples
                log.warning("   harvest %s/%s attempt %d: reply carried no "
                            "'tuples' list", source.owner_kind,
                            source.owner_id, attempt)
            except Exception as exc:
                log.warning("   harvest %s/%s attempt %d failed: %s",
                            source.owner_kind, source.owner_id, attempt, exc)
                status = getattr(exc, "status_code", None)
                if isinstance(status, int) and 400 <= status < 500 and status != 429:
                    # A request the server refuses is refused every time. The
                    # last run spent three tries and eight seconds of sleep on
                    # each over-long section before writing the same sentinel.
                    break
            if attempt < MAX_RETRIES:
                time.sleep(min(2 * attempt, 6))
        # A source the model never answered for is a hole in the harvest, and
        # holes must be visible: the caller counts these via the sentinel.
        return [{"_harvest_failed": True}]

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


def harvest_batch(items: list, harvest: Callable,
                  workers: int = LLM_PARALLEL) -> list:
    """Every harvest request of the whole run, in flight at once.

    Returns one claim list per item, in the order given: the caller folds
    them back into the document they belong to. Ordering is by index, not by
    completion — the server answers a 40-token table long before a 6000-token
    section, and the report must not depend on that.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    results: list = [None] * len(items)
    if not items:
        return results
    started = time.time()
    step = max(len(items) // 20, 50)
    done = 0
    with ThreadPoolExecutor(max_workers=max(workers, 1)) as pool:
        futures = {pool.submit(harvest, it.source, it.parameter): i
                   for i, it in enumerate(items)}
        for future in as_completed(futures):
            index = futures[future]
            try:
                results[index] = future.result()
            except Exception as exc:                        # pragma: no cover
                source = items[index].source
                log.warning("   harvest %s/%s raised: %s",
                            source.owner_kind, source.owner_id, exc)
                results[index] = [{"_harvest_failed": True}]
            done += 1
            if done % step == 0 or done == len(items):
                elapsed = max(time.time() - started, 1e-6)
                rate = done / elapsed
                log.info("harvest: %d/%d requests (%.1f/s, %.0f s left)",
                         done, len(items), rate,
                         (len(items) - done) / max(rate, 1e-6))
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
                try:
                    pages = [int(r[0]) for r in conn.execute(
                        "SELECT page_number FROM SectionPages WHERE section = ? "
                        "ORDER BY page_number", (owner_id,))]
                except sqlite3.OperationalError:
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


def context_budget(prompt) -> int:
    """Tokens one harvest request needs at worst — a floor for the server.

    Counted, not guessed: system prompt, parameter payload and JSON envelope,
    a source window at its ceiling, the crop that rides along, and the reply.
    The estimate this replaces allowed 6000 tokens for "largest source,
    generous" and no image at all, and the job script served that number as
    --max-model-len; every section over it came back as a 400.
    """
    return int(len(prompt.text.split()) * 3
               + MAX_SOURCE_CHARS // 3                      # a bounded window
               + (1200 if ATTACH_IMAGES else 0)             # a 1280 px crop
               + 2000                                       # payload + envelope
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

    required = context_budget(prompts.load(HARVEST_PROMPT_ID))
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

    with sqlite3.connect(f"file:{args.db}?mode=ro", uri=True) as listing:
        documents = _documents(listing)
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

    cache_path = args.out / "query_cache.db"
    primer = query_cache.connect(cache_path)
    prime_probe_cache(primer, spec, templates)
    primer.close()

    def plan(document_id: int, filename: str) -> tuple:
        # Both connections per thread, cache included. Sharing one across the
        # pool would rest on SQLite being built serialized, and the priming
        # above already means every read here is a hit.
        conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        cache_conn = query_cache.connect(cache_path)
        try:
            # One memo per document: retrieval and the fallback floor meet the
            # same section in every round and for every parameter.
            fetch = make_content_fetcher()
            items, report = plan_document(
                document_id, spec, templates,
                retrieve=make_retrieve(conn, index, id_to_pos, cache_conn, fetch),
                candidates=make_candidates(conn, fetch), max_rounds=MAX_ROUNDS)
            return Path(filename).stem, split_long_sources(items), report
        finally:
            conn.close()
            cache_conn.close()

    def verify(entry: tuple) -> None:
        name, items, report, answers = entry
        for item, answer in zip(items, answers):
            fold_claims(item, answer, report, locate=locate)
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
        flat = [item for _, items, _ in plans for item in items]
        log.info("extraction: group %d/%d planned — %d request(s) over %d "
                 "document(s)", offset // group_size + 1,
                 (len(documents) - 1) // group_size + 1, len(flat), len(plans))

        # ---- Harvest: all of them, at once ---------------------------------
        claims = harvest_batch(flat, harvest, LLM_PARALLEL)

        # ---- Verify and write, document by document ------------------------
        cursor = 0
        entries = []
        for name, items, report in plans:
            entries.append((name, items, report, claims[cursor:cursor + len(items)]))
            cursor += len(items)
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
