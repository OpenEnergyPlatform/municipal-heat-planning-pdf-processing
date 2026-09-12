"""
runner.py: Wires the pure harvest loop of `pipeline.py` to the live stack.

This module supplies the loop's expensive dependencies from the real world:
FAISS retrieval with owner exclusion, the harvesting LLM call, and locating a
quote on its page in the source PDF, plus resume stamps and the CLI. Heavy
imports (faiss, torch-backed embedders, fitz) happen inside functions, so
importing this module stays cheap and a test that only touches the package pays
for no GPU stack it does not use.

`make_retrieve` fuses every probe handed to it into one FAISS search per
document and ranks each owner by the best score any probe gave it; measured
over 65 documents and 15,082 values, the fused ranking put the source a value
was really read from at median rank 26, against 77 for the old per-probe
concatenation. `make_candidates` is a deterministic floor under that ranking,
matched by LIKE over the corpus's own vocabulary tokens. A probe is either one
of the spec's query templates (`queries.expand`), stable across the whole
corpus so `prime_probe_cache`'s embeddings hit for every document, or a
HyDE-style anchor sentence a model writes: `make_anchors` writes one set per
question the field sweep asks, cached under `anchors.json` and reusable across
documents, and `document_anchor` writes the one short sentence per parameter
the document being planned is searched with, which is a cache miss by
construction.

`make_harvester` and `make_fieldwise_harvester` build the request to the model
and parse its reply strictly: one JSON object and nothing else. A reply that is
not that is asked again with the cause named (`_reply_fault`), and one cut off
at the token ceiling is asked again over half the passages (`_split_harvest`)
rather than half-read. `make_sweeper` drives the field-wise
sweep: a coordinate the value's own passage does not answer is asked for again
over short overlapping windows of the rest of the document (`window_sources`),
bounded per axis. `find_frame` and `make_frame_asker` read a document's frame,
its scenario and year pairs, once before any value, so a value request states
the pair rather than deciding it. `harvest_batches` runs every batch of a whole
run in flight at once, not as ordered per-document chains.

`make_locate` finds where a quote sits on its page in the source PDF, through
the same alignment the app highlights with. Resume stamps (`_stamp_current`,
`stale`) record a fingerprint per question a spec asks (`spec.fingerprints`),
so an ontology edit restales only the documents asked through the coordinate it
touched, not the whole corpus. `main` is the CLI: a normal harvest, and the
`--recheck`, `--remap`, `--serialize`, `--review` and `--top-up` maintenance
passes over a harvest already written.

Author: Felix Vossel
"""
from __future__ import annotations

import argparse
import functools
import hashlib
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
from docpipe.llm_preflight import assert_serving, request_extras
from docpipe.profile import add_profile_argument, resolve_profile

from . import fields
from . import trace
from .pipeline import (Source, WorkItem, apply_frame, batch_uri,
                       build_sweeps, cell_index as pipeline_cell_index,
                       fold_batch, follow_up, group_items, harvest_document,
                       merge_field, mark_unanswered, open_rows, plan_document,
                       names_no_pair_at_all, names_pair, refused_upstream, route_claims,
                       rows_from_reply, sweep_key, window_sources,
                       write_report)
from .fields import EXHAUSTED
from .queries import expand as expand_queries
from .trust import document_summary, parameter_states
from .spec import Spec, fingerprints, load as load_spec

log = logging.getLogger(__name__)

LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "http://localhost:8000/v1")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "EMPTY")
LLM_MODEL = os.environ.get("LLM_MODEL", "Qwen/Qwen3.8-Flash-Next-FP8")
LLM_TIMEOUT = int(os.environ.get("LLM_TIMEOUT", "180"))
TOP_K = int(os.environ.get("EXTRACT_TOP_K", "8"))
MAX_ROUNDS = int(os.environ.get("EXTRACT_MAX_ROUNDS", "4"))
MAX_RETRIES = 3
# How long to wait before asking again, and it is two curves because the two
# failures are not alike. A reply the model got wrong comes back the moment it
# is asked again; a server that is not there needs time to come back. The
# corpus_m5 run had neither: `attempt < MAX_RETRIES` stops one short of the
# loop it guards, so attempts 3, 4 and 5 of every harvest waited not at all,
# and 256 requests spent their whole budget inside a few seconds of one
# outage — 1,152 of that run's 1,156 connection errors fell in its last hour.
# How often a request may be halved before it is simply refused. Without a
# floor the recursion is bounded only by the number of rows, and one stuck
# table of 64 line items becomes a tree of 127 requests that the field
# sweep's window budget cannot see: it counts the one call it made. Three
# halvings are eight parts, which is the largest table the corpus has needed.
SPLIT_DEPTH = int(os.environ.get("EXTRACT_SPLIT_DEPTH", "3"))
RETRY_WAIT = float(os.environ.get("EXTRACT_RETRY_WAIT", "2"))
RETRY_WAIT_MAX = float(os.environ.get("EXTRACT_RETRY_WAIT_MAX", "6"))
TRANSPORT_WAIT = float(os.environ.get("EXTRACT_TRANSPORT_WAIT", "15"))
TRANSPORT_WAIT_MAX = float(os.environ.get("EXTRACT_TRANSPORT_WAIT_MAX", "120"))


def retry_wait(attempt: int, transport: bool = False) -> float:
    """Seconds to wait before attempt *attempt* + 1.

    *transport* is the request that never reached the server: no HTTP status,
    no refusal, nothing to read. Doubling from 15 seconds gives a restarting
    vLLM 225 seconds over five attempts, which is what a model server needs
    to come back; the model's own mistakes keep the short curve, because
    waiting longer for those buys nothing.
    """
    if transport:
        return min(TRANSPORT_WAIT * (2 ** max(0, attempt - 1)),
                   TRANSPORT_WAIT_MAX)
    return min(RETRY_WAIT * attempt, RETRY_WAIT_MAX)
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
PRIOR_MAX = int(os.environ.get("EXTRACT_PRIOR_MAX", "24"))
# What one prior entry actually costs, measured on real tuples from the pilot
# corpus: 40 entries came to 11071 characters, about 110 tokens each. The
# placeholder here was 60, which is the one direction a budget must not err in.
PRIOR_TOKENS = 110
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
# The field-wise pair that replaces the single whole-tuple request: one call
# finds the values, one call per coordinate fills them in.
ROWS_PROMPT_ID = "extraction/rows"
FIELD_PROMPT_ID = "extraction/field"
# The one sentence a document is searched with, written for THAT document.
PHRASE_PROMPT_ID = "extraction/phrase"
# Which scenarios and which years the document really carries. Asked once per
# document, before any value: the pair is the frame every value hangs in, and
# a frame the run discovers first is one the value request cannot get wrong.
FRAME_PROMPT_ID = "extraction/frame"
PROMPT_IDS = (HARVEST_PROMPT_ID, QUERIES_PROMPT_ID, ANCHORS_PROMPT_ID,
              ROWS_PROMPT_ID, FIELD_PROMPT_ID, PHRASE_PROMPT_ID,
              FRAME_PROMPT_ID)
# The second reading of one value, under a window narrowed to the two passages
# the row may legally quote from. Not in PROMPT_IDS, which are the harvest's
# own prompts: what the review writes into a stamp goes under `review/`.
REVIEW_PROMPT_ID = "extraction/review"

# One request per field, or one request per tuple. The old way is kept
# reachable because it is what every measured number so far was taken with,
# and a comparison needs both.
FIELDWISE = os.environ.get("EXTRACT_FIELDWISE", "1") != "0"
# The anchors.json key of the "which quantity is this" question. It belongs to
# no single parameter, so it cannot be keyed by one.
PARAMETER_ANCHOR = "#parameter"
# How many prose sections a document is planned from. Tables and figures are
# not capped. Measured over 65 documents: 66% of all values sit in the first
# 50 ranks of an anchor-only ranking, 80% of them are in a table or a figure
# and are taken whole regardless of rank.
PROSE_TOP = int(os.environ.get("EXTRACT_PROSE_TOP", "200"))
# The pool: how far down EACH probe's own ranking an owner still counts as
# found. An owner is planned when it is in the top of at least one probe, so
# a section only the year anchor likes is read, instead of sitting at rank 200
# of the fused list because two hundred owners have a higher best score.
# PROSE_TOP is then a ceiling against a pathological document, not the
# selector: a plan has about 132 sections, so the pool cannot exceed that.
POOL_TOP = int(os.environ.get("EXTRACT_POOL_TOP", "50"))
# How many owners the document plan takes, tables figures and prose together,
# in the order the ranking put them. This is the cut that replaces the
# structural floor: whether something is a table decides nothing here, only
# how well it answers the one sentence this document was asked. The floor
# stays wired as the COUNTER -- how many tables and figures a bare ranking
# leaves outside is the number that says whether it has to come back, and it
# can only be taken while the floor is still there to ask. 100 since corpus_m5:
# at 50 the plans held 40 percent of a document's tables and 15 percent of its
# figures.
PLAN_TOP = int(os.environ.get("EXTRACT_PLAN_TOP", "100"))
# How many rounds the frame search may ask for more passages before it says
# what it has. Bounded, because it decides the whole harvest: every value is
# asked for one of its pairs, so a frame that never finished would be a
# document that never got read.
FRAME_ROUNDS = int(os.environ.get("EXTRACT_FRAME_ROUNDS", "3"))
# How many passages one frame request reads. More than a field window, fewer
# than the plan: a scenario stands in a heading and a year in a column header,
# and neither is found by looking at two passages at a time.
FRAME_SOURCES = int(os.environ.get("EXTRACT_FRAME_SOURCES", "12"))
# And how many characters of passage. The same budget one value request gets,
# because the frame reads the whole plan in as many requests as that takes:
# the window of the run this was measured on was 32,047 tokens and the plan is
# fifty passages, so a frame that read them in one request would not fit and a
# frame that read the first twelve would miss the rest.
FRAME_CHARS = int(os.environ.get("EXTRACT_FRAME_CHARS", str(BATCH_CHARS)))
# What counts as a calendar year for the deterministic cross-check. Not a
# reading and never one: it only says how many year-shaped numbers stand in
# the very passages the model was shown and did not name. A plan writes 2045
# as a target and 2045 as a megawatt-hour, so this reports and decides
# nothing.
FRAME_YEAR_MIN = int(os.environ.get("EXTRACT_FRAME_YEAR_MIN", "1990"))
FRAME_YEAR_MAX = int(os.environ.get("EXTRACT_FRAME_YEAR_MAX", "2100"))
_YEAR_RE = re.compile(r"(?<![0-9])([0-9]{4})(?![0-9])")
# Where the run's concurrency actually lives once the values are found. A
# batch is one row request and then one sweep per axis, and the sweeps are
# independent, so 128 batches of seven axes are nine hundred sweeps that can
# all be in flight. Within ONE sweep the windows stay strictly sequential —
# it exists to stop as soon as the coordinate is read, and asking the next
# three windows speculatively would buy parallelism with wasted requests.
#
# 64 was the bottleneck it looks like: 128 batch threads waiting on a pool of
# 64 held the server at a quarter of what it schedules.
FIELD_PARALLEL = int(os.environ.get("EXTRACT_FIELD_PARALLEL", "192"))
# Short windows, many requests. Two sources per window with one shared is the
# unit the sweep walks the document in once a coordinate was not in the
# value's own passage; the rounds bound it, because a stop heuristic without a
# bound is an outage.
FIELD_WINDOW = int(os.environ.get("EXTRACT_FIELD_WINDOW", "2"))
FIELD_OVERLAP = int(os.environ.get("EXTRACT_FIELD_OVERLAP", "1"))
FIELD_ROUNDS = int(os.environ.get("EXTRACT_FIELD_ROUNDS", "4"))
# How many sections at each end of a document count as its covers. Only ever
# used for a parameter without axes, which asks for something that stands once
# and at a known place — the title page in front, the Impressum at the back.
EDGE_SECTIONS = int(os.environ.get("EXTRACT_EDGE_SECTIONS", "3"))
# The most windows one coordinate may cost before the sweep stops. A plan of
# 249 sections combed two at a time for seven axes would be nine hundred
# requests for one batch, so there is a ceiling — and a row that hits it is
# marked exhausted, never "not stated".
FIELD_MAX_WINDOWS = int(os.environ.get("EXTRACT_FIELD_MAX_WINDOWS", "24"))
# How often one window is asked when the answers came back unbackable. The
# retry carries the reason per row, so it is a correction and not a repeat.
FIELD_ATTEMPTS = int(os.environ.get("EXTRACT_FIELD_ATTEMPTS", "3"))
# What the last stage may spend. Its own number rather than a share of the
# one above: reading the rest of a plan is a different search from ranking
# passages out of it, and the two sharing a budget is what left the stage
# unreachable for every sweep that needed it.
REST_MAX_WINDOWS = int(os.environ.get("EXTRACT_REST_MAX_WINDOWS", "12"))


def window_budget() -> dict:
    """{stage: windows} for one coordinate's sweep, own then retrieval then
    rest. Read at call time so a test that moves one constant moves this.

    The sum is FIELD_MAX_WINDOWS + REST_MAX_WINDOWS. `own` can never bind --
    one window, and the attempt loop already stops at FIELD_ATTEMPTS -- and
    is written here so the three numbers add up in one place instead of two.
    """
    return {"own": FIELD_ATTEMPTS,
            "retrieval": max(0, FIELD_MAX_WINDOWS - FIELD_ATTEMPTS),
            "rest": REST_MAX_WINDOWS}
# How many already-read passages ride along at the front of a window. Where
# one coordinate of a row was read, the next one is usually a few lines away
# — and today that passage went into `seen` after the window that showed it
# and was never shown again, so the sweep leaves the one place it knows
# something is and never comes back. Three, because the window itself is two:
# the re-entry may not become the window.
FIELD_RE_ENTRY = int(os.environ.get("EXTRACT_FIELD_RE_ENTRY", "3"))

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
                  "title": hit.get("title"),
                  # The section a table or figure stands in, and its
                  # placeholder in that section. Both are how the own window
                  # is built, and neither can be worked out afterwards.
                  "parent_section": hit.get("section_id"),
                  "block_id": hit.get("block_id")}
    if via:
        provenance["via"] = via
    body = hit.get("text") or ""
    # The heading joins the text the quote is checked against. The model was
    # always shown it; the verifier only ever saw the transcription, so a unit
    # or a year printed only in a caption was visible and not quotable.
    heading = (hit.get("title") or hit.get("section_title") or "").strip()
    text = body
    if heading and heading not in body[:200]:
        text = f"{heading}\n{body}"
    return Source(owner_kind=hit["owner_kind"], owner_id=hit["owner_id"],
                  text=text, provenance=provenance,
                  image_path=hit.get("image_path"),
                  body=body if text is not body else None)


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
                  cache_conn, content_fetcher: Optional[Callable] = None,
                  limit: int = 0, per_probe_top: int = 0) -> Callable:
    """(probes, document_id, exclude) -> ONE ranked Source list.

    Takes every probe at once. One sub-index for the document instead of one
    per probe, one FAISS search over a query matrix, and one ranking out of
    it: the best score any probe gave an owner decides where it sits.

    It used to return a list per probe, which the plan then concatenated. That
    is not a ranking, it is a concatenation of rankings, and it put probe 17's
    best match behind everything probes 1 to 16 had surfaced. Measured over 65
    documents and 15,082 values: median rank 77 that way, 26 this way.
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
        hits = faiss_store.fuse_prepared(
            conn, document[1], scores, positions, limit,
            content_fetcher=content_fetcher, exclude=exclude, probes=probes,
            per_probe_top=per_probe_top)
        return [_source_of(hit) for hit in hits]

    return retrieve


def make_structure(conn: sqlite3.Connection,
                   content_fetcher: Optional[Callable] = None) -> Callable:
    """(document_id) -> every table and every figure of the document.

    The floor of the plan, and it is structural rather than lexical on
    purpose. The old floor searched the stored text with LIKE for the
    vocabulary's own words, which is a worse version of the retrieval above
    it — measured over the corpus it never had anything left to add, because
    the sweep above had already walked the whole document.

    This one adds what retrieval is bad at and structure is certain about:
    12,094 of 15,082 values came from a table or a figure, and whether
    something is a table is not a question a similarity search should be
    asked. There are about 110 per document, which is affordable exactly
    because the plan is no longer built once per parameter.
    """
    from docpipe.inference import db as inference_db

    fetch = content_fetcher or inference_db.fetch_owner_content

    def structure(document_id: int) -> list:
        out: list = []
        for kind, sql in (
                ("table", "SELECT t.id FROM \"Tables\" t "
                          "JOIN Sections s ON s.id = t.section "
                          "WHERE s.document = ? ORDER BY t.id"),
                ("figure", "SELECT i.id FROM Images i "
                           "JOIN Sections s ON s.id = i.section "
                           "WHERE s.document = ? ORDER BY i.id")):
            try:
                ids = [int(r[0]) for r in conn.execute(sql, (document_id,))]
            except Exception as exc:
                log.warning("   %ss of document %s unreadable: %s", kind,
                            document_id, exc)
                continue
            for owner_id in ids:
                content = fetch(conn, kind, owner_id)
                if content is None:
                    continue
                out.append(_source_of({"score": None, **content}))
        return out

    return structure


# How much of a parent section rides along with its table. Kassel's median
# section is 894 characters and its longest is 6,038, so most fit whole and
# the rest are cut around the table's own placeholder rather than dropped:
# the sentence that dates a table stands next to its placeholder and nowhere
# else.
PARENT_CHARS = int(os.environ.get("EXTRACT_PARENT_CHARS", "4000"))


def _around(text: str, needle: str, budget: int) -> str:
    """A window of *budget* characters centred on *needle*."""
    at = text.find(needle) if needle else -1
    if at == -1:
        return text[:budget]
    start = max(0, at - budget // 2)
    return text[start:start + budget]


def make_parents(db_path: Path) -> Callable:
    """(sources) -> the section each table or figure stands in, once each.

    The own window used to be the batch's tables and nothing else, and the
    coordinates a table does not carry live in the section around it: the
    sentence that dates it ("Für das Jahr 2040 ergeben sich ..."), the
    heading that names the scenario, the caption Stage 2 failed to link.
    Measured on Kassel, section 349525 was in 0 of 1,043 field windows while
    its three tables were asked for their year 39 times, and 69 tuples from
    inventory tables came back as target-scenario values because no window
    ever showed the word for what they are.

    Once each: two tables of one section share one parent, and showing it
    twice is the same passage paying twice.

    Its own connection per thread, like more_sources: this runs inside the
    harvest pool, and SQLite handles are not shared across a hundred threads.
    """
    local = threading.local()

    def fetcher():
        if getattr(local, "conn", None) is None:
            local.conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            local.conn.row_factory = sqlite3.Row
            local.fetch = make_content_fetcher()
        return local.conn, local.fetch

    def parents(sources: list) -> list:
        conn, fetch = fetcher()
        seen = {(s.owner_kind, s.owner_id) for s in sources}
        out: list = []
        for source in sources:
            provenance = source.provenance or {}
            section_id = provenance.get("parent_section")
            if section_id is None or ("section", section_id) in seen:
                continue
            seen.add(("section", section_id))
            try:
                content = fetch(conn, "section", section_id)
            except Exception as exc:            # pragma: no cover - defensive
                log.warning("   parent section %s unreadable: %s",
                            section_id, exc)
                continue
            if content is None:
                continue
            parent = _source_of({"score": None, **content}, via="parent")
            if len(parent.text or "") > PARENT_CHARS:
                block = provenance.get("block_id") or ""
                parent = Source(owner_kind=parent.owner_kind,
                                owner_id=parent.owner_id,
                                text=_around(parent.text, f"[{block}",
                                             PARENT_CHARS),
                                provenance=parent.provenance,
                                image_path=parent.image_path)
            out.append(parent)
        return out

    return parents


def make_owner_sources(db_path: Path) -> Callable:
    """(owners) -> {(kind, id): Source} for passages a harvest already named.

    The harvest stores the address of a passage and not its text, so a pass
    that reads one coordinate again has to fetch it back. Through the same
    two functions the harvest used -- the cached fetcher and `_source_of` --
    so the heading is prefixed the same way and a quote that was checkable
    during the harvest stays checkable.

    Its own connection per thread, read-only, and memoised across calls: one
    section is the parent of several rows and would otherwise be read once
    per row.
    """
    local = threading.local()

    def _connections():
        if getattr(local, "conn", None) is None:
            local.conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            local.conn.row_factory = sqlite3.Row
            local.fetch = make_content_fetcher()
        return local.conn, local.fetch

    def owner_sources(owners) -> dict:
        conn, fetch = _connections()
        out: dict = {}
        for kind, owner in owners or ():
            if not kind or owner is None or (kind, owner) in out:
                continue
            try:
                content = fetch(conn, kind, int(owner))
            except Exception as exc:          # pragma: no cover - defensive
                log.warning("   %s %s unreadable: %s", kind, owner, exc)
                continue
            if content is None:
                continue
            out[(kind, owner)] = _source_of(
                {"score": None, **content, "owner_kind": kind,
                 "owner_id": int(owner)})
        return out

    return owner_sources


def make_review_sources(db_path: Path) -> Callable:
    """(row) -> the passages one stored tuple may legally quote from.

    Exactly two, in this order: the row's own source, and the section that
    source stands in. That pair is where a row's labels, header and caption
    stand, and it is a strict SUBSET of the window the sweep already walked --
    which is what makes the second reading a check on the first and not an
    independent one.

    The parent goes through `make_parents` rather than being fetched from
    `parent_section` directly, so a section too long for the window arrives
    cut around this row's own placeholder instead of from its first character.

    Its own connection per thread, like `make_parents`: read-only, and SQLite
    handles are not shared.
    """
    local = threading.local()
    parents = make_parents(db_path)

    def _connections():
        if getattr(local, "conn", None) is None:
            local.conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            local.conn.row_factory = sqlite3.Row
            local.fetch = make_content_fetcher()
        return local.conn, local.fetch

    def sources_for(row: dict) -> list:
        conn, fetch = _connections()
        provenance = row.get("provenance") or {}
        kind, owner = provenance.get("owner_kind"), provenance.get("owner_id")
        if not kind or owner is None:
            return []
        try:
            content = fetch(conn, kind, int(owner))
        except Exception as exc:              # pragma: no cover - defensive
            log.warning("   review: %s %s unreadable: %s", kind, owner, exc)
            return []
        if content is None:
            return []
        own = _source_of({"score": None, **content, "owner_kind": kind,
                          "owner_id": int(owner)})
        # A row whose own source IS a section has one passage, not two:
        # `make_parents` skips a parent that is already shown.
        return [own] + list(parents([own]))

    return sources_for


def own_section_number(sources) -> Optional[int]:
    """The earliest section any of these passages stands in, or None.

    The rest stage reads in the document's own order, and that order starts at
    section 1 -- the title page of a 249-section plan, for a row that stands on
    page 180. Earliest and not nearest, because one sweep asks for several rows
    at once and only a start before all of them is close to every one.
    """
    numbers = [n for n in ((s.provenance or {}).get("section_number")
                           for s in sources or ())
               if isinstance(n, int)]
    return min(numbers) if numbers else None


def make_rest_of_document(db_path: Path) -> Callable:
    """(document_id, exclude, start) -> every remaining section, in document order.

    The floor under the field sweep, and the reason "not stated" can mean it.
    Retrieval answers "which passages look like this question", and for a
    coordinate that is stated once in a caption twelve pages away the answer
    is often none of them — an embedding does not rank a table caption under
    "which reference year does this figure belong to".

    So when the probes stop bringing anything new, the sweep stops asking and
    starts reading: the document's own sections, in their own order, until the
    coordinate is found or the document is finished. Finite by construction,
    which is what lets a sweep end in an answer rather than in a budget.

    Where it starts reading is `start`, the section the open rows stand in. The
    order is ROTATED there and never cut: what this floor promises is that "not
    stated" means the whole document was read, and dropping the sections before
    the row would make that a lie about the part a title page stands in. A
    coordinate is far more often a few sections from its own row than on page
    one, and the budget runs out long before the wrap comes round.
    """
    local = threading.local()

    def connections():
        if getattr(local, "conn", None) is None:
            local.conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            local.conn.row_factory = sqlite3.Row
            local.fetch = make_content_fetcher()
        return local.conn, local.fetch

    def rest_of_document(document_id: int, exclude: set,
                         start: Optional[int] = None) -> list:
        conn, fetch = connections()
        try:
            order = [(int(r[0]), r[1]) for r in conn.execute(
                "SELECT id, section_number FROM Sections WHERE document = ? "
                "ORDER BY COALESCE(section_number, id)", (document_id,))]
        except Exception as exc:
            log.warning("   sections of document %s unreadable: %s",
                        document_id, exc)
            return []
        if start is not None:
            at = next((i for i, (_id, number) in enumerate(order)
                       if number is not None and number >= start), 0)
            order = order[at:] + order[:at]
        ids = [section_id for section_id, _number in order]
        out: list = []
        for section_id in ids:
            if ("section", section_id) in exclude:
                continue
            hit = fetch(conn, "section", section_id)
            if hit is None:
                continue
            out.append(_source_of({**hit, "owner_kind": "section",
                                   "owner_id": section_id}, via="comb"))
        return out

    return rest_of_document


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
            for source in retrieve(list(queries)[:4], document_id, taken):
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


# Bumped when the SET of anchor targets changes, not just their wording: an
# anchors.json written for three parameters must not be read back as if it
# also held the twenty-two question anchors this version asks for.
ANCHOR_SCHEMA = "per-question-1"


def _key16(raw: str) -> str:
    """Sixteen hex characters. Long enough that two configurations do not
    collide, short enough to read in a stamp beside twenty-nine other keys."""
    import hashlib
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def anchor_question_key(target) -> str:
    """The one question a stored anchor set was written for.

    An anchor is a sentence written from a label, a description and a
    wording. Those three and the anchor's own id are the target tuple, so the
    tuple IS the question, and a set is reusable exactly while its tuple has
    not moved.
    """
    return _key16(json.dumps(list(target), ensure_ascii=False,
                             sort_keys=True, separators=(",", ":")))


def anchors_key() -> str:
    """Everything an anchor set depends on that is NOT one question: the
    anchor prompt, the model and the version of the target SET. The cache is
    stored under it and the stamp records it.

    Not the questions, though it used to hash them. Everything a target tuple
    carries is already a stamp key of its own -- a parameter's label and
    description in `parameter/<uri>`, an axis' question in
    `axis/<uri>/<name>`, the spec's own question and the parameter list in
    `slot/parameter` -- and the anchor prompt and the model are stamp keys too
    (`extraction/anchors`, `model`). Hashing the targets in here as well made
    every document in the corpus stale over ONE changed question, which is
    exactly what the per-question keys were written to stop.

    The empty last field held the sha of a file of anchors a profile could
    freeze. That file is gone, and the field stays empty rather than going,
    so a harvest that never had one keeps its key.
    """
    versions = prompts.versions((ANCHORS_PROMPT_ID,))
    return _key16(f"{versions.get(ANCHORS_PROMPT_ID)}|{LLM_MODEL}"
                  f"|{ANCHOR_SCHEMA}|")


def anchor_key(parameter_uri: str, slot_name: Optional[str] = None) -> str:
    """The anchors.json key of one question: the value's, or one axis's."""
    return parameter_uri if not slot_name else f"{parameter_uri}#{slot_name}"


def anchor_targets(spec: Spec) -> list:
    """(key, label, description, question) for every question the run asks.

    One anchor set per QUESTION, not per parameter. An anchor is a sentence as
    the document would write it, and the sentence that states a value and the
    sentence that states its reference year are not the same sentence. Six
    anchors written from "Endenergieverbrauch" find tables of consumption and
    say nothing about where a bilanz year is printed, which is why the field
    sweep searched with the raw question and found captions by accident.

    The value itself has no set here. The plan searches with the one short
    sentence `document_anchor` writes for the document it plans, and a set
    written once for the whole corpus was never searched with.
    """
    out: list = [(PARAMETER_ANCHOR, "Kennzahl", "", spec.parameter_question)]
    for parameter in spec.parameters:
        # asked_slots, not axis_slots: an anchor is a sentence to search
        # with, and a coordinate the spec derives is never searched for.
        for slot in fields.asked_slots(parameter):
            out.append((anchor_key(parameter.uri, slot.name),
                        f"{parameter.label} / {slot.name}",
                        parameter.description, slot.question))
    return [t for t in out if t[0] != PARAMETER_ANCHOR or t[3]]


def document_anchor(spec: Spec, context: Optional[dict] = None,
                    client=None, prompt=None,
                    frame: Optional[dict] = None) -> dict:
    """{parameter uri: [one sentence]} — the probe THIS document is searched with.

    The QA app turns a question into one short statement before it searches,
    because a similarity search matches sentences and a question is the one
    sentence that never stands in a document. This stage searched with 24
    frozen 600-character passages instead, and a 600-character passage is not
    an anchor: it is half a hit put back into the query.

    Per document, not per corpus, and that is the whole point. The sentence is
    written from the ontology annotation the spec inlines -- `label` and
    `description` -- AND from what the document itself has already said: its
    name, and the caption of what a first search in it returned. So the anchor
    grows with the document instead of asking all 1,082 plans the same
    sentence.

    The price, stated: the corpus-wide query-embedding cache stops hitting.
    A per-document sentence is a miss by construction, so the plan pays one
    embed per parameter per document instead of one per corpus.

    A parameter whose sentence could not be written is left out rather than
    filled with the label. `plan_document` says out loud when it plans without
    anchors, and a probe that is a bare label is the "silently worse
    retrieval" this whole stage exists to end.
    """
    prompt = prompt if prompt is not None else prompts.load(PHRASE_PROMPT_ID)
    client = client or _client()
    context = {k: v for k, v in (context or {}).items()
               if isinstance(v, str) and v.strip()}

    def one(parameter):
        body = {"label": parameter.label,
                "description": parameter.description}
        if context:
            body["document"] = context
        if frame:
            # The pair this sentence searches for, in the document's own
            # wording where the frame read one. "Nutzwaermebedarf 2040 im
            # Zielszenario" finds the table for 2040; the parameter alone
            # finds the first table of the chapter, whatever its year.
            body["frame"] = {k: frame.get(f"{k}_raw") or v
                             for k, v in frame.items()
                             if not k.endswith(("_raw", "_quote", "_source"))}
        payload = json.dumps(body, ensure_ascii=False, indent=2)
        transport = False
        conversation: list = [{"role": "user", "content": payload}]
        limit = int(prompt.meta.get("max_tokens", 300))
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                reply = client.chat.completions.create(
                    model=LLM_MODEL,
                    temperature=float(prompt.meta.get("temperature", 0)),
                    max_tokens=limit,
                    messages=[{"role": "system", "content": prompt.text},
                              *conversation],
                    extra_body=request_extras(),
                ).choices[0]
                phrase = ((_loads_object(reply.message.content) or {})
                          .get("phrase") or "")
                phrase = phrase.strip() if isinstance(phrase, str) else ""
                if phrase:
                    return parameter.uri, [phrase]
                # The same retry rule as everywhere else: a reply that could
                # not be read is asked again WITH the reason. Three silent
                # tries were three copies of the same reply.
                cause, correction = _reply_fault(reply, limit)
                log.warning("phrase %s attempt %d: %s reply",
                            parameter.uri, attempt, cause)
                conversation.append({"role": "assistant",
                                     "content": reply.message.content or ""})
                conversation.append({"role": "user", "content": correction})
            except Exception as exc:
                log.warning("phrase %s attempt %d failed: %s",
                            parameter.uri, attempt, exc)
                transport = not isinstance(
                    getattr(exc, "status_code", None), int)
            if attempt < MAX_RETRIES:
                time.sleep(retry_wait(attempt, transport))
        log.warning("phrase %s: no anchor written for this document",
                    parameter.uri)
        return parameter.uri, []

    out: dict = {}
    for uri, phrase in map(one, spec.parameters):
        if phrase:
            out[uri] = phrase
    return out


def years_in_sources(sources, low: int = 0, high: int = 0) -> set:
    """Every year-shaped number in these passages. A count, not a reading.

    The frame carries the whole harvest: every value is asked for one of its
    pairs, so a year the frame missed loses all of that year's values at once
    and loses them silently -- which is the one failure this design has that
    the old one did not. So the same passages the model was shown are scanned
    without a model, and what it did not name is reported.

    Reported, never added. "2045 MWh/a" is a year-shaped number and is not a
    year, and a cross-check that decided would put it in the frame and ask
    every table for a year the plan does not have.
    """
    low = low or FRAME_YEAR_MIN
    high = high or FRAME_YEAR_MAX
    found = set()
    for source in sources or ():
        for part in (source.text or "", (source.provenance or {}).get("title") or ""):
            for match in _YEAR_RE.finditer(part):
                year = int(match.group(1))
                if low <= year <= high:
                    found.add(year)
    return found


def _frame_payload(sources: list, slots: list, known: Optional[list] = None,
                   candidates: Optional[list] = None,
                   corrections: Optional[list] = None) -> dict:
    """The request body of one frame request.

    Sources first, then the answer space of every frame coordinate that has
    one. A closed list is offered as a list -- the model chooses rather than
    generates -- and an open one (the year is an int) is left open, because
    there is no list of years to choose from.
    """
    listed = []
    for index, source in enumerate(sources):
        provenance = source.provenance or {}
        entry = {"id": f"Q{index + 1}", "kind": source.owner_kind,
                 "title": provenance.get("title"),
                 "section": provenance.get("section_title"),
                 "text": source.text}
        for key in ("page", "block_id"):
            if provenance.get(key):
                entry[key] = provenance[key]
        listed.append(entry)
    payload: dict = {"sources": listed}
    for slot in slots:
        options = slot.answerable() if slot.kind == fields.CHOICE else None
        if options:
            payload.setdefault("scenarios", {}).update(
                {k: v for k, v in options.items()
                 if not str(k).startswith("out:")})
    if known:
        payload["known"] = [{s.name: pair.get(s.name) for s in slots}
                            for pair in known]
    if candidates:
        # The second pass. These numbers really stand in the passages above
        # and the first round did not name them, which is either a year it
        # missed or a number that only looks like one. The model decides
        # which, and its answer is checked like every other: the quote stands
        # in a shown passage and carries the year -- so a candidate that is a
        # megawatt-hour simply comes back unquotable.
        payload["candidates"] = list(candidates)
    if corrections:
        # What was wrong with the last answer over these same passages. A
        # pair that failed its evidence, or named a scenario that is not on
        # the list, used to disappear without a word -- the model was never
        # told, and the next window was asked in exactly the same way.
        payload["corrections"] = [c.get("reason") for c in corrections
                                  if isinstance(c, dict) and c.get("reason")]
    return payload


# How vLLM words a request whose prompt and completion together do not fit
# the model's window: "maximum context length is 32768 tokens. However, you
# requested 6144 output tokens and your prompt contains at least 26625 input
# tokens".
_OVERFLOW = re.compile(r"maximum context length is (\d+) tokens.*?"
                       r"(\d+) input tokens", re.S)
# What an answer needs at the very least. Less room than this and the request
# is refused for good, as it was before.
MIN_ANSWER_TOKENS = 256


def fitted_max_tokens(exc, asked: int, where: str = "") -> Optional[int]:
    """A completion budget that fits the window this request overflowed, or
    None when the error is another one or no answer fits.

    The server names both numbers when it refuses. Measured on Kassel: one
    field request of 26,625 prompt tokens asked for 6,144 more, was refused
    for one token over 32,768, and the break on a 4xx wrote its coordinates
    off. The prompt is what it is, so the room for the answer is what gives.
    """
    match = _OVERFLOW.search(str(exc))
    if not match:
        return None
    room = int(match.group(1)) - int(match.group(2)) - 32
    if room < MIN_ANSWER_TOKENS or room >= asked:
        return None
    log.warning("   %s: %d output token(s) do not fit next to the prompt, "
                "asked again with %d", where or "request", asked, room)
    return room


def make_frame_asker(image_root: Optional[Path] = None) -> Callable:
    """ask(sources, slots, document_id, known, usage_out) -> reply or None.

    One request, and the answer is a list of pairs with two quotes each. Two,
    because a column header carries the years and a section heading carries
    the scenario: one passage can back both halves only when it prints both,
    and every coordinate is checked against its OWN quote exactly as a field
    answer is.
    """
    prompt = prompts.load(FRAME_PROMPT_ID)
    client = _client()
    temperature = float(prompt.meta.get("temperature", 0))
    max_tokens = int(prompt.meta.get("max_tokens", 4096))

    def ask(sources: list, slots: list, document_id: Optional[int] = None,
            known: Optional[list] = None,
            usage_out: Optional[dict] = None,
            candidates: Optional[list] = None,
            corrections: Optional[list] = None, *,
            depth: int = 0) -> Optional[dict]:
        payload = json.dumps(
            _frame_payload(sources, slots, known, candidates, corrections),
            ensure_ascii=False, indent=2)
        # The crops ride along, as they do for every other request: a year
        # in a column header and a scenario in a figure caption are often
        # clearer in the picture than in the transcription of it.
        content: object = payload
        parts = [{"type": "text", "text": payload}]
        for index, source in enumerate(sources):
            path = source.image_path
            if not (path and ATTACH_IMAGES):
                continue
            part = _image_part(str(image_root / path) if image_root else path)
            if part is not None:
                parts.append({"type": "text", "text": f"Bild zu Q{index + 1}:"})
                parts.append(part)
        if len(parts) > 1:
            content = parts
        transport = False
        conversation: list = [{"role": "user", "content": content}]
        limit = max_tokens
        for attempt in range(1, MAX_RETRIES + 1):
            started = time.time()
            try:
                completion = client.chat.completions.create(
                    model=LLM_MODEL, temperature=temperature,
                    max_tokens=limit,
                    messages=[{"role": "system", "content": prompt.text},
                              *conversation],
                    extra_body=request_extras(),
                )
                transport = False
                _observe_usage(getattr(completion, "usage", None))
                if usage_out is not None:
                    usage = getattr(completion, "usage", None)
                    usage_out["prompt_tokens"] = getattr(
                        usage, "prompt_tokens", None)
                    usage_out["completion_tokens"] = getattr(
                        usage, "completion_tokens", None)
                    usage_out["ms"] = int((time.time() - started) * 1000)
                    usage_out["attempt"] = attempt
                reply = completion.choices[0]
                parsed = _loads_object(reply.message.content or "")
                # WITH its list: a dict that carries no `pairs` is a reply
                # that answered something else, and returning it made the
                # window look answered and the plan pairless.
                if isinstance(parsed, dict) and isinstance(
                        parsed.get("pairs"), list):
                    return parsed
                cause, correction = _reply_fault(
                    reply, limit, key="pairs",
                    shorter="Antworte mit weniger Paaren und zitiere nur die "
                            "kurze Stelle, an der das Szenario oder das Jahr "
                            "steht.")
                log.warning("frame %s attempt %d: %s reply%s",
                            document_id, attempt, cause, _unparsable(reply))
                trace.event("error", document_id, where="frame",
                            kind="unreadable", cause=cause, attempt=attempt,
                            finish=getattr(reply, "finish_reason", None))
                if cause == "cut_off" and len(sources) > 1 \
                        and depth < SPLIT_DEPTH:
                    # Fewer passages per request. A pair the frame does not
                    # have loses every value of that pair, so the half of the
                    # window that was never answered for is asked rather than
                    # written off.
                    cut = len(sources) // 2
                    merged: dict = {"pairs": [], "status": "complete",
                                    "need_more": []}
                    for offset, part in ((0, sources[:cut]),
                                         (cut, sources[cut:])):
                        got = ask(part, slots, document_id, known, usage_out,
                                  candidates, corrections, depth=depth + 1)
                        if not isinstance(got, dict):
                            merged["status"] = "incomplete"
                            continue
                        merged["pairs"].extend(_relabel_sources(
                            [p for p in (got.get("pairs") or ())
                             if isinstance(p, dict)], offset))
                        if str(got.get("status") or "") != "complete":
                            merged["status"] = "incomplete"
                        merged["need_more"].extend(
                            q for q in (got.get("need_more") or ())
                            if isinstance(q, str))
                    trace.event("error", document_id, where="frame",
                                kind="split", attempt=attempt)
                    return merged
                conversation.append({"role": "assistant",
                                     "content": reply.message.content or ""})
                conversation.append({"role": "user", "content": correction})
            except Exception as exc:
                log.warning("frame %s attempt %d failed: %s",
                            document_id, attempt, exc)
                transport = not isinstance(
                    getattr(exc, "status_code", None), int)
                trace.event("error", document_id, where="frame",
                            kind="exception", attempt=attempt,
                            detail=str(exc)[:200])
                fitted = fitted_max_tokens(exc, limit, "frame")
                if fitted is not None:
                    limit = fitted
                    continue
            if attempt < MAX_RETRIES:
                time.sleep(retry_wait(attempt, transport))
        return None

    return ask


def frame_pairs(reply: Optional[dict], slots: list, sources: list,
                rejected: Optional[list] = None) -> list:
    """The pairs of a reply that carry their own evidence, in order.

    Every coordinate is held to what a field answer is held to: its quote sits
    verbatim in one of the passages that were SHOWN, the quote contains the
    answer, and a scenario is one of the keys the request listed. Nothing else
    is checked. A frame reading is document-level by construction -- it is
    read once, from a caption or a heading, and every row of the document
    inherits it -- so "is this passage near this row" is not a question about
    it, and no reading anywhere in the harvest is asked it.

    *rejected* collects one sentence per pair that did not get through, for
    `find_frame` to put back in front of the model. Silently dropping them is
    how a plan ended up with a scenario the ontology has no class for: the
    pair was refused, nobody said so, and the next window was asked the same
    question in the same way.
    """
    from .pipeline import answer_in_quote, option_named
    from .verify import quote_in

    where = {f"Q{i + 1}": s for i, s in enumerate(sources)}
    out: list = []
    seen: set = set()

    def refuse(reason: str) -> None:
        # Bounded: the corrections ride in the next prompt, and a reply whose
        # every pair failed would otherwise pay for itself twice.
        if rejected is not None and len(rejected) < 6:
            rejected.append({"reason": reason})

    for entry in (reply or {}).get("pairs") or ():
        if not isinstance(entry, dict):
            continue
        pair: dict = {}
        for slot in slots:
            given = entry.get(slot.name)
            if isinstance(given, str):
                given = given.strip()
            if given is None or given == "":
                refuse(f'In einem Paar fehlte "{slot.name}".')
                break
            quote = entry.get(f"{slot.name}_quote")
            if not isinstance(quote, str) or not quote.strip():
                refuse(f'Zu {slot.name}={given!r} fehlte "{slot.name}_quote".')
                break
            named = entry.get(f"{slot.name}_source")
            found = where.get(str(named))
            if found is None or not quote_in(found.text or "", quote):
                found = next((s for s in sources
                              if quote_in(s.text or "", quote)), None)
            if found is None:
                refuse(f"Das Zitat zu {slot.name}={given!r} steht in keiner "
                       f"der gezeigten Passagen: {quote.strip()[:80]!r}. "
                       f"Kopiere es Zeichen f\u00fcr Zeichen aus \"sources\".")
                break
            wording = entry.get(f"{slot.name}_raw")
            wording = wording.strip() if isinstance(wording, str) else None
            if not answer_in_quote(slot, given, wording, quote):
                refuse(f"{slot.name}={given!r} steht nicht in seinem Zitat "
                       f"{quote.strip()[:80]!r}. Schreib die Formulierung des "
                       f"Plans in \"{slot.name}_raw\".")
                break
            if slot.kind == fields.CHOICE and slot.options \
                    and option_named(slot, given) is None:
                # An answer that is not on the closed list. It used to be
                # taken as long as its wording stood in the quote, and the
                # class lookup behind it then came back empty -- 8,944 of
                # ar6's tuples carry an unmapped scenario label for exactly
                # this reason. Asked again instead, and told which list.
                refuse(f"{given!r} ist keiner der Schl\u00fcssel aus "
                       f'"scenarios". W\u00e4hle genau einen daraus, Zeichen '
                       f"f\u00fcr Zeichen abgeschrieben, und schreib das Wort "
                       f'des Plans in "{slot.name}_raw".')
                break
            if slot.kind == fields.NUMBER:
                try:
                    given = int(str(given).strip())
                except (TypeError, ValueError):
                    refuse(f"{slot.name}={given!r} ist keine ganze "
                           f"Jahreszahl. Gib das Jahr vierstellig an.")
                    break
            pair[slot.name] = given
            pair[f"{slot.name}_raw"] = wording
            pair[f"{slot.name}_quote"] = quote.strip()
            pair[f"{slot.name}_source"] = [found.owner_kind, found.owner_id]
        else:
            key = tuple(pair.get(slot.name) for slot in slots)
            if key not in seen:
                seen.add(key)
                out.append(pair)
    return out



def frame_windows(sources: list, max_sources: int = 0,
                  max_chars: int = 0) -> list:
    """The plan's passages in windows one frame request can hold.

    All of them, not a prefix. A pair may only be quoted from a passage that
    was shown (`frame_pairs`), so a year printed past the cut cannot enter the
    frame at all, and a pair the frame does not have loses every value of that
    pair. Measured on Kassel: a frame over the first 12 of 50 passages found
    2 pairs, 2040 and 2024, and 174 of the 234 table tuples the hand reading
    covers were then stamped with a year printed on another table.
    """
    max_sources = max_sources or FRAME_SOURCES
    max_chars = max_chars or FRAME_CHARS
    windows: list = []
    current: list = []
    chars = 0
    for source in sources or ():
        size = len(source.text or "")
        if current and (len(current) >= max_sources
                        or chars + size > max_chars):
            windows.append(current)
            current, chars = [], 0
        current.append(source)
        chars += size
    if current:
        windows.append(current)
    return windows


def find_frame(sources: list, slots: list, document_id: int, ask: Callable,
               more_sources: Optional[Callable] = None,
               probes: Optional[list] = None) -> tuple:
    """(pairs, status, missed) - which scenarios and years this document has.

    Asked once per document and over every window of the plan, before any
    value. Every value question is then one of these pairs, which is what
    takes the coordinate out of the model's hands: it is not asked which year
    a number belongs to, it is asked what the number for THIS year is.

    `missed` is the deterministic cross-check: the year-shaped numbers in the
    passages that no pair names. It is a finding for the second pass, never an
    addition to the frame, and the second pass shows the window that CARRIES
    the missed year instead of the first window again.
    """
    if not slots:
        return [], "complete", []
    number = [s for s in slots if s.kind == fields.NUMBER]
    windows = frame_windows(sources)
    pairs: list = []
    finished = True

    def take(found) -> None:
        known = {tuple(p.get(s.name) for s in slots) for p in pairs}
        pairs.extend(p for p in found
                     if tuple(p.get(s.name) for s in slots) not in known)

    def one(shown: list, attempt: int, recheck: Optional[list] = None) -> str:
        said = "complete"
        corrections: Optional[list] = None
        # Two rounds at most over one window: the ask, and one that says what
        # was wrong with it. The second round is only sent when a pair was
        # actually refused, so a clean window still costs one request.
        for extra in range(2):
            usage: dict = {}
            rejected: list = []
            reply = ask(shown, slots, document_id, pairs, usage, recheck,
                        corrections)
            take(frame_pairs(reply, slots, shown, rejected))
            # The conservative reading wins across the rounds: a window whose
            # first answer said "incomplete" is not finished because the
            # second one, asked about what was refused, says it is.
            if str((reply or {}).get("status") or "").strip() != "complete":
                said = "exhausted"
            trace.event("frame", document_id, pairs=len(pairs),
                        scenarios=sorted({str(p.get(slots[0].name))
                                          for p in pairs}),
                        years=sorted({p[s.name] for p in pairs for s in number
                                      if isinstance(p.get(s.name), int)}),
                        missed=list(recheck or []),
                        sources=[[s.owner_kind, s.owner_id] for s in shown],
                        status="complete" if said == "complete" else "exhausted",
                        attempt=attempt + extra,
                        rejected=len(rejected),
                        prompt_tokens=usage.get("prompt_tokens"),
                        completion_tokens=usage.get("completion_tokens"),
                        ms=usage.get("ms", 0))
            if not rejected:
                break
            corrections = rejected
        return said

    for index, shown in enumerate(windows):
        if one(shown, index + 1) != "complete":
            finished = False

    def _not_named() -> list:
        if not number:
            return []
        named = {p[s.name] for p in pairs for s in number
                 if isinstance(p.get(s.name), int)}
        return sorted(years_in_sources(sources) - named)

    missed = _not_named()
    for index, shown in enumerate(windows):
        if not missed:
            break
        here = sorted(years_in_sources(shown) & set(missed))
        if not here:
            continue
        # The second pass, and it is the whole reason the deterministic scan
        # exists. What the scan found and the model did not name is put back
        # in front of it once, by name, together with the passages it stands
        # in.
        one(shown, index + 1, here)
        missed = _not_named()

    # Nothing in the whole plan carries a pair. Only then is it worth looking
    # past the plan, and the passages that come back are read like any other
    # window.
    for round_index in range(1, max(1, FRAME_ROUNDS)):
        if pairs or more_sources is None or not probes:
            break
        seen = {(s.owner_kind, s.owner_id) for s in sources or ()}
        fresh = more_sources(document_id, list(probes), seen) or []
        if not fresh:
            break
        for shown in frame_windows(fresh):
            one(shown, round_index, None)
        missed = _not_named()

    status = "complete" if finished and pairs else "exhausted"
    trace.event("frame", document_id, pairs=len(pairs),
                scenarios=sorted({str(p.get(slots[0].name)) for p in pairs}),
                years=sorted({p[s.name] for p in pairs for s in number
                              if isinstance(p.get(s.name), int)}),
                missed=missed,
                sources=[[s.owner_kind, s.owner_id] for s in sources],
                status=status, attempt=0, prompt_tokens=None,
                completion_tokens=None, ms=0)
    return pairs, status, missed


def load_anchors(path: Path, key: str, targets: list) -> dict:
    """The anchor sets a previous run wrote that are still the answer to the
    same question.

    Per question, not per file. One changed question used to miss the whole
    cache and have the model rewrite all nineteen sets, and those sets decide
    which passages a document is read from -- so an edit to the year question
    changed the retrieval of the carrier coordinate, which nothing had asked
    for and no line anywhere reported.

    A file written before the per-question map existed carries none of it and
    is therefore reused for nothing: it cannot say which of its sets still
    answer, and guessing is how a run comes to search with a set nobody
    checked.
    """
    try:
        stored = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(stored, dict) or stored.get("key") != key:
        return {}
    anchors = stored.get("anchors")
    if not isinstance(anchors, dict):
        return {}
    questions = stored.get("questions")
    if not isinstance(questions, dict):
        # Absent, or something other than a map. Either way the file cannot
        # say which of its sets still answer, so none of them is taken.
        questions = {}
    want = {target[0]: anchor_question_key(target) for target in targets}
    return {anchor_id: texts for anchor_id, texts in anchors.items()
            if anchor_id in want and questions.get(anchor_id) == want[anchor_id]}


def save_anchors(path: Path, key: str, anchors: dict,
                 targets: Optional[list] = None) -> None:
    """Write the sets and, beside each, the question it answers."""
    questions = {target[0]: anchor_question_key(target)
                 for target in (targets or [])}
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(
        json.dumps({"key": key, "model": LLM_MODEL, "anchors": anchors,
                    "questions": {k: v for k, v in questions.items()
                                  if k in anchors}},
                   ensure_ascii=False, indent=2), encoding="utf-8")


def make_anchors(spec: Spec, client=None, *, store: Optional[Path] = None,
                 key: str = "") -> dict:
    """anchor id -> search anchors the model wrote for one question.

    The QA app turns a question into a HyDE anchor before it searches: a
    sentence written as it would READ in the document, because that is what a
    similarity search matches against. This stage searched with the spec's
    templates alone, which name the thing rather than say it.

    Once per run and per question, not per document: the anchor depends on
    the question, not on the plan, and a stable probe string is what makes the
    query-embedding cache hit across the whole corpus.
    """
    prompt = prompts.load(ANCHORS_PROMPT_ID)
    # Stored, because they decide which passages the whole corpus is harvested
    # from. Two calls in one job shared 0 of 18 strings, so a restart searched
    # a different document set with nothing in any of the 1082 output files
    # saying which set had found it. The file carries the reproducibility;
    # the temperature stays where it is.
    targets = anchor_targets(spec)
    out: dict = (dict(load_anchors(store, key, targets))
                 if store is not None else {})
    todo = [t for t in targets if not out.get(t[0])]
    if store is not None and out:
        log.info("extraction: %d anchor set(s) reused from %s, %d to write",
                 len(out), store, len(todo))
    if not todo:
        return out
    client = client or _client()

    def one(target):
        anchor_id, label, description, question = target
        body = {"label": label, "description": description}
        if question:
            # The anchors must read like the ANSWER to this question, not like
            # the topic it belongs to. Without it every axis of a parameter
            # would get the same six sentences about the parameter.
            body["question"] = question
        payload = json.dumps(body, ensure_ascii=False, indent=2)
        transport = False
        conversation: list = [{"role": "user", "content": payload}]
        limit = int(prompt.meta.get("max_tokens", 800))
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                reply = client.chat.completions.create(
                    model=LLM_MODEL,
                    temperature=float(prompt.meta.get("temperature", 0.4)),
                    max_tokens=limit,
                    messages=[{"role": "system", "content": prompt.text},
                              *conversation],
                    extra_body=request_extras(),
                ).choices[0]
                parsed = _loads_object(reply.message.content)
                anchors = [a.strip() for a in (parsed or {}).get("anchors", ())
                           if isinstance(a, str) and a.strip()]
                if anchors:
                    return anchor_id, anchors
                cause, correction = _reply_fault(reply, limit, key="anchors")
                log.warning("anchors %s attempt %d: %s reply",
                            anchor_id, attempt, cause)
                conversation.append({"role": "assistant",
                                     "content": reply.message.content or ""})
                conversation.append({"role": "user", "content": correction})
            except Exception as exc:
                log.warning("anchors %s attempt %d failed: %s",
                            anchor_id, attempt, exc)
                transport = not isinstance(
                    getattr(exc, "status_code", None), int)
            if attempt < MAX_RETRIES:
                time.sleep(retry_wait(attempt, transport))
        log.warning("anchors %s: none generated", anchor_id)
        return anchor_id, []

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=min(8, len(todo) or 1)) as pool:
        for uri, anchors in pool.map(one, todo):
            out[uri] = anchors
    if store is not None:
        save_anchors(store, key, out, targets)
    log.info("extraction: %d anchor(s) over %d question(s)",
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

    def edges(document_id: int) -> list:
        """The document's first and last sections — its covers.

        A parameter without axes asks for something that stands once in the
        document and at a known place, and that place is an edge: the title
        page in front, the Impressum at the back. It is not a similarity
        question, and treating it as one fails in a way retrieval cannot fix,
        because a cover page carries almost no text to embed.

        The token floor above cannot reach these either: its words come from
        units_accepted and the axis vocabularies, and a parameter without axes
        has neither. What is left is its label, so `planning_organisation`
        searched German full text for the phrase "Beauftragtes Planungsbüro".

        Both edges, not just the front. The scenarios side measured 59 of 60
        missing front pages in section 1 and proposed the first; measured on
        the 58 KWP plans that named no planning office, section 1 holds it for
        15, sections 2-3 for another 17, and the last three sections for 17
        more. A Wärmeplan puts its Impressum at the back.
        """
        first = [int(r[0]) for r in conn.execute(
            "SELECT id FROM Sections WHERE document = ? "
            "ORDER BY COALESCE(section_number, id) LIMIT ?",
            (document_id, EDGE_SECTIONS))]
        last = [int(r[0]) for r in conn.execute(
            "SELECT id FROM Sections WHERE document = ? "
            "ORDER BY COALESCE(section_number, id) DESC LIMIT ?",
            (document_id, EDGE_SECTIONS))]
        return first + last

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
        if not parameter.axes:
            seen = {o for o in owners}
            owners += [("section", sid) for sid in edges(document_id)
                       if ("section", sid) not in seen]
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


def _loads_object(raw_text) -> Optional[dict]:
    """The one JSON object a reply was asked for, or None.

    Strict, and that is the point of it. Every softener this used to carry --
    closing the brackets a reply stopped short of, reading one object out of
    a longer text, stripping fences and think blocks -- turned a defective
    answer into a value that then stood in the harvest saying "read" with
    nothing under it. A reply that is not exactly the object that was asked
    for is asked again, and the retry says what was wrong with it
    (`_reply_fault`).
    """
    text = (raw_text or "").strip()
    if not text:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


# What a `defaults` block may NOT carry. Stated as the exclusion, not as a
# list of axis names: the axes are the profile's business and the core has no
# opinion on them. These two are different in kind — they are the evidence
# pair, one number and the words it was read from, and a shared one would
# hand every tuple in the reply the same evidence, which is the one thing
# this stage exists to prevent. Underscore keys are ours, not the model's.
NOT_DEFAULTABLE = frozenset({
    "value", "quote", "value_raw",
    # Not a coordinate at all but a switch: `computed` decides WHICH evidence
    # check applies, letting the value be absent from its own quote as long
    # as the sandbox printed it. Shared across a reply it would open that
    # door for every tuple in it, and a table whose rows are all computed is
    # exactly the case the defaults block was written for.
    "computed", "compute",
})

_DECODER = json.JSONDecoder()


def expand_defaults(defaults: Optional[dict], tuples: list) -> list:
    """Fold the reply's shared coordinates into every tuple that omits them.

    Measured on the one table that truncated in three consecutive pilots: of
    the sixteen keys a tuple carries, ten are identical across all 39 of its
    tuples, and rewriting them costs 52% of the whole answer. So the model
    writes them once. A tuple's own key always wins, and a key in
    NOT_DEFAULTABLE is dropped however the model labelled it.
    """
    if not isinstance(defaults, dict) or not defaults:
        return tuples
    shared = {k: v for k, v in defaults.items()
              if isinstance(k, str) and k not in NOT_DEFAULTABLE
              and not k.startswith("_")}
    if not shared:
        return tuples
    out = []
    for claim in tuples:
        if not isinstance(claim, dict):
            out.append(claim)
            continue
        merged = dict(shared)
        merged.update(claim)          # what the tuple says about itself wins
        out.append(merged)
    return out


def _parse_reply(raw_text) -> Optional[dict]:
    """The whole answer object, not just its tuples.

    A batch reply says three things: what it found, whether these passages
    are exhausted for the parameter, and -- when they are not -- what
    sentence to search for next. Only `tuples` decides whether the reply was
    understood at all; the other two default to the conservative reading,
    which is "there may be more, but I cannot say where".
    """
    data = _loads_object(raw_text)
    if data is None:
        return None
    tuples = data.get("tuples")
    if not isinstance(tuples, list):
        return None
    status = data.get("status")
    need = data.get("need_more")
    return {"tuples": expand_defaults(data.get("defaults"), tuples),
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

    def show(text: str, keep: int = 400) -> str:
        """Head and tail, with the cut marked.

        Marked, because an unmarked cut is worse than no excerpt: this line
        used to end a JSON string mid-word with no sign of why, and a reply
        that was merely long read as a reply that was broken. And the TAIL is
        the half that matters — a malformed reply is malformed at its end, and
        the head was all this printed.
        """
        if len(text) <= 2 * keep:
            return repr(text)
        return f"{text[:keep]!r} …{len(text) - 2 * keep} more… {text[-keep:]!r}"

    return (f" [finish={getattr(reply, 'finish_reason', '?')}"
            f" | content {len(content)}ch: {show(content)}"
            f" | reasoning {len(reasoning)}ch: {show(reasoning)}]")


# What has to be said back whatever went wrong: the shape that was asked for.
_SHAPE_RULE = (" Gib NUR das JSON-Objekt aus, in EINER Zeile, ohne Text davor "
               "oder danach, ohne Codefence, ohne <think>-Block und ohne ein "
               "zweites Objekt. Anführungszeichen INNERHALB eines Zitats "
               "müssen als \\\" escaped sein — ist das mühsam, kürz das "
               "Zitat auf eine Stelle ohne Anführungszeichen.")


def _reply_fault(reply, limit: int, *, key: str = "",
                 shorter: str = "") -> tuple:
    """(cause, what to tell the model) for a reply that could not be read.

    The retry used to say the same sentence whatever had gone wrong, and a
    model told nothing specific answers the same way again. The causes need
    different things: a reply cut off at the ceiling has to be shorter, one
    wrapped in prose has to drop the prose, one with broken syntax has to see
    where it broke, one that spent its turn thinking has to stop thinking,
    and one missing its list has to be told which list.

    The cause goes into the trace too, so a run can say what its retries were
    spent on instead of counting all of them as "unparsable".
    """
    def cut_off() -> tuple:
        return "cut_off", (
            f"Deine Antwort wurde nach {limit} Tokens abgeschnitten und ist "
            "deshalb kein vollständiges JSON-Objekt. "
            + (shorter or "Antworte kürzer: zitiere nur die kurze Stelle, an "
                          "der die Angabe steht."))

    ran_out = getattr(reply, "finish_reason", None) == "length"
    message = getattr(reply, "message", None)
    content = getattr(message, "content", None)
    text = content.strip() if isinstance(content, str) else ""
    thought = getattr(message, "reasoning_content", None)
    thought = thought.strip() if isinstance(thought, str) else ""
    if not text and thought:
        # The answer went into the think block and the reply itself stayed
        # empty. Reading it back out of there was a fallback and is gone, so
        # the model is told instead — and this is also the one reply that
        # says the server's thinking switch did not take, which is worth
        # seeing in the trace rather than hiding behind "empty".
        return "reasoning_only", (
            "Du hast nur nachgedacht und nichts geantwortet: dein Beitrag "
            "war leer. Denk nicht vor, sondern gib direkt das Ergebnis aus."
            + _SHAPE_RULE)
    if not text:
        return cut_off() if ran_out else (
            "empty", "Deine Antwort war leer." + _SHAPE_RULE)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        # Only here. A reply that ran into the ceiling is unreadable BECAUSE
        # it was cut, so its syntax error is the consequence and not the
        # cause — but a reply that parses and merely has the wrong shape is
        # not made right by being told it was too long, whatever its
        # finish_reason says.
        if ran_out:
            return cut_off()
        start = text.find("{")
        if start == -1:
            return "no_object", ("Deine Antwort enthielt gar kein "
                                 "JSON-Objekt." + _SHAPE_RULE)
        try:
            _obj, end = _DECODER.raw_decode(text, start)
        except json.JSONDecodeError:
            around = text[max(start, exc.pos - 60):exc.pos + 20]
            return "syntax", (
                f"Dein JSON bricht bei Zeichen {exc.pos - start} ab "
                f"({exc.msg}), an dieser Stelle: {around!r}." + _SHAPE_RULE)
        extra = (text[:start] + text[end:]).strip()
        return "outside_text", (
            f"Neben dem JSON-Objekt stand noch Text: {extra[:200]!r}."
            + _SHAPE_RULE)
    if not isinstance(data, dict):
        return "not_an_object", (
            f"Deine Antwort war eine {type(data).__name__}-Struktur und kein "
            "JSON-Objekt." + _SHAPE_RULE)
    if key and not isinstance(data.get(key), list):
        had = "fehlte" if key not in data else "war keine Liste"
        return "missing_key", (
            f'In deiner Antwort {had} "{key}".' + _SHAPE_RULE)
    return "wrong_shape", ("Deine Antwort hatte nicht die Form, die verlangt "
                           "war." + _SHAPE_RULE)


def _relabel_sources(entries, offset: int, suffix: str = "source"):
    """A part's Q labels shifted back onto the whole request's numbering.

    A request asked again in halves numbers its passages from Q1, and the
    second half's Q1 is the whole request's Q4. Unshifted, every answer of
    that half would be checked against the wrong passage -- which is the one
    way splitting could corrupt what a truncation merely lost.
    """
    if not offset:
        return entries
    for entry in entries or ():
        if not isinstance(entry, dict):
            continue
        for key in [k for k in entry
                    if k == suffix or k.endswith("_" + suffix)]:
            name = entry.get(key)
            if isinstance(name, str) and name.startswith("Q") \
                    and name[1:].strip().isdigit():
                entry[key] = f"Q{int(name[1:].strip()) + offset}"
    return entries


def _split_harvest(batch, prior, harvest: Callable, limit: int,
                   ceiling: int, first, depth: int = 0) -> Optional[dict]:
    """A cut-off batch asked again in pieces, or None when it cannot be.

    Two ways to make an answer fit: fewer passages per request, and -- when a
    single passage already IS the request -- more room for the answer. The
    reply that was cut off is not used at all. It was, once: the tuples
    written before the cut were kept and the passages after it became holes,
    which put a half-read request into the harvest as if it had been read.
    """
    items = list(batch.items)
    if len(items) > 1 and depth < SPLIT_DEPTH:
        cut = len(items) // 2
        log.warning("   harvest %s/%s+%d cut off at %d tokens: asked again "
                    "as %d and %d passage(s)", first.owner_kind,
                    first.owner_id, len(items) - 1, limit, cut,
                    len(items) - cut)
        merged: dict = {"tuples": [], "status": "complete", "need_more": []}
        for offset, part in ((0, items[:cut]), (cut, items[cut:])):
            got = harvest(replace(batch, items=list(part)), prior,
                          depth=depth + 1)
            if not isinstance(got, dict):
                merged["status"] = "partial"
                continue
            merged["tuples"].extend(_relabel_sources(
                [t for t in (got.get("tuples") or ()) if isinstance(t, dict)],
                offset))
            if got.get("status") != "complete":
                merged["status"] = str(got.get("status") or "partial")
            merged["need_more"].extend(
                q for q in (got.get("need_more") or ()) if isinstance(q, str))
        return merged
    if limit < ceiling * 4:
        log.warning("   harvest %s/%s cut off at %d tokens: %s, asked again "
                    "with %d", first.owner_kind, first.owner_id, limit,
                    "one passage" if len(items) == 1 else "no room to split",
                    limit * 2)
        return harvest(batch, prior, ceiling=limit * 2, depth=depth)
    return None


def _parse_action(text) -> Optional[str]:
    """The python the model wants run, or None if it answered instead."""
    obj = _loads_object(text)
    if obj is None or obj.get("action") != "python":
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


# The evidence a row keeps next to each coordinate: what makes it re-checkable,
# and nothing that tells a repeat from a new value.
_EVIDENCE = ("_raw", "_raw_foreign", "_quote", "_source", "_window", "_state",
             "_seen")


def _prior_payload(prior: list) -> list:
    """What the model is told it already has, small enough to send every time.

    Coordinates and the value, not the whole verified row: the point is that
    the model recognises a repeat, and provenance, flags, tier and the
    evidence beside each coordinate say nothing about that. The evidence went
    along until corpus_m5 measured it: 74 percent of a 24-row block, 13k
    tokens at the median and past the window at the top, where rows requests
    came back as 400. The newest entries are the ones a neighbouring passage
    is likely to duplicate, so the tail is what survives the cap.
    """
    out: list = []
    for row in prior[-PRIOR_MAX:]:
        item = {k: v for k, v in row.items()
                if k not in ("provenance", "flags", "tier", "compute", "quote")
                and not k.endswith(_EVIDENCE) and v is not None}
        quote = row.get("quote")
        if isinstance(quote, str):
            item["quote"] = quote[:80]
        out.append(item)
    return out


def _quantities_payload(spec) -> list:
    """What counts as a value, for a batch that was not planned per parameter.

    The definitions and the accepted units, and no axes: this request finds
    numbers and says where it read them. Which quantity each number is, is a
    coordinate and is asked for on its own, with its own quote.
    """
    out = []
    for parameter in spec.parameters:
        entry = {"uri": parameter.uri, "label": parameter.label,
                 "description": parameter.description,
                 "value_type": parameter.value_type}
        if parameter.is_numeric:
            entry["units_accepted"] = sorted(parameter.units_accepted)
        elif parameter.vocabulary:
            entry["value_classes"] = {labels[0]: list(labels[1:])
                                      for labels in parameter.vocabulary.values()}
        out.append(entry)
    return out


def _batch_payload(batch, prior: list, spec=None) -> dict:
    """The request body: labelled sources, the target, and what we have.

    The target is one parameter when the plan fixed one, and the list of
    quantities when it did not. The second is the document-level plan: a
    passage is read once and every value in it is found in that one reading,
    instead of once per parameter with two thirds of the answers empty.
    """
    sources = []
    for index, item in enumerate(batch.items):
        source = item.source
        sources.append({"id": batch.label(index), "kind": source.owner_kind,
                        "title": source.provenance.get("title"),
                        "section": source.provenance.get("section_title"),
                        "text": source.text})
    payload: dict = {"sources": sources}
    if batch.frame:
        # The pair this request is for. It was read once for the document and
        # it is not a question here: the request asks what the value IS for
        # this scenario and this year, which is the whole point of finding the
        # frame first.
        payload = {"frame": {k: v for k, v in batch.frame.items()
                             if not k.endswith(("_raw", "_quote", "_source"))},
                   **payload}
    if getattr(batch, "anchors", ()):
        payload = {"anchors": list(batch.anchors), **payload}
    if batch.parameter is not None:
        payload = {"parameter": _parameter_payload(batch.parameter), **payload}
    elif spec is not None:
        payload = {"quantities": _quantities_payload(spec), **payload}
    if prior:
        payload["prior"] = _prior_payload(prior)
    return payload


_USAGE = {"n": 0, "prompt_max": 0, "prompt_sum": 0, "completion_max": 0}
_USAGE_LOCK = threading.Lock()


def _observe_usage(usage) -> None:
    """What a request really cost, from the server's own count.

    context_budget is a formula with estimated constants, and it feeds
    --max-model-len. Nobody had ever checked it against reality: it claimed
    22900 prompt tokens where the measured mean was 10081, and its `prior`
    term was low by 40%. The server reports the true number on every reply,
    so from now on the run says what it actually used and the next budget can
    be calibrated instead of guessed.
    """
    prompt = getattr(usage, "prompt_tokens", None)
    completion = getattr(usage, "completion_tokens", None)
    if not isinstance(prompt, int):
        return
    with _USAGE_LOCK:
        _USAGE["n"] += 1
        _USAGE["prompt_sum"] += prompt
        _USAGE["prompt_max"] = max(_USAGE["prompt_max"], prompt)
        if isinstance(completion, int):
            _USAGE["completion_max"] = max(_USAGE["completion_max"], completion)


def log_usage(budget: Optional[int] = None) -> None:
    """One line at the end of a run: what the window was really asked for."""
    with _USAGE_LOCK:
        seen = dict(_USAGE)
    if not seen["n"]:
        return
    log.info("harvest tokens: %d request(s), prompt mean %d / max %d, "
             "completion max %d, budget said %s",
             seen["n"], seen["prompt_sum"] // seen["n"], seen["prompt_max"],
             seen["completion_max"], budget if budget is not None else "-")


def make_harvester(image_root: Optional[Path] = None,
                   prompt_id: str = HARVEST_PROMPT_ID,
                   spec=None) -> Callable:
    """The request loop, for either contract.

    The whole-tuple prompt and the field-wise value prompt differ in what they
    ask for and in nothing else: same sources, same crops, same sandbox, same
    splitting of a request whose answer did not fit. So the prompt is the
    argument and the loop is shared.
    """
    prompt = prompts.load(prompt_id)
    client = _client()
    temperature = float(prompt.meta.get("temperature", 0.1))
    max_tokens = int(prompt.meta.get("max_tokens", 4096))

    # Deferred: docpipe.inference's package __init__ pulls in the whole answer
    # loop, which demands a profile at import time.
    from docpipe.inference import code_exec

    def harvest(batch, prior: Optional[list] = None, *,
                ceiling: Optional[int] = None, depth: int = 0) -> dict:
        started = time.time()
        payload = json.dumps(_batch_payload(batch, prior or [], spec),
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
        why = ["no_answer"]
        conversation: list = [{"role": "user", "content": content}]
        transport = False
        # The wait follows the FAILURES, not the turns of the conversation: a
        # sandbox round is a turn and not a failure, and counting it escalated
        # the backoff of the next real one.
        failures = 0
        # More room than the prompt asks for only when a single passage came
        # back cut off and there is nothing left to split.
        limit = ceiling or max_tokens
        # A compute round is a turn of the same conversation, not a retry, so
        # the attempt budget grows with the rounds actually used.
        for attempt in range(1, MAX_RETRIES + CODE_ROUNDS + 1):
            try:
                response = client.chat.completions.create(
                    model=LLM_MODEL, temperature=temperature,
                    max_tokens=limit,
                    messages=[{"role": "system", "content": prompt.text},
                              *conversation],
                    # Refinement and the vision path have said this for
                    # longer than this stage has existed: a reasoning model
                    # must not spend the token budget on a think block,
                    # because that truncates the JSON answer. Extraction was
                    # the one stage that did not say it, and the pilot lost
                    # 1093 of 16102 harvests to replies with no 'tuples' in
                    # them, HTTP 200 every one.
                    extra_body=request_extras(),
                )
                transport = False
                reply = response.choices[0]
                _observe_usage(getattr(response, "usage", None))
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
                if answer is not None:
                    if compute:
                        for t in answer["tuples"]:
                            if isinstance(t, dict):
                                t.setdefault("compute", compute)
                    usage = getattr(response, "usage", None)
                    trace.event("rows", batch.document_id, prompt=prompt_id,
                                attempt=attempt, rows=len(answer["tuples"]),
                                status=answer.get("status"),
                                sources=[[it.source.owner_kind,
                                          it.source.owner_id]
                                         for it in batch.items],
                                ranks=[it.rank for it in batch.items],
                                origins=[it.origin for it in batch.items],
                                prompt_tokens=getattr(usage, "prompt_tokens",
                                                      None),
                                completion_tokens=getattr(
                                    usage, "completion_tokens", None),
                                ms=int((time.time() - started) * 1000))
                    return answer
                cause, correction = _reply_fault(
                    reply, limit, key="tuples",
                    shorter="Antworte mit weniger Tupeln und zitiere nur die "
                            "kurze Stelle, an der die Zahl steht.")
                log.warning("   harvest %s/%s+%d attempt %d: %s reply%s",
                            first.owner_kind, first.owner_id,
                            len(batch.items) - 1, attempt, cause,
                            _unparsable(reply))
                trace.event("error", batch.document_id, where=prompt_id,
                            kind="unreadable", cause=cause, attempt=attempt,
                            owner=[first.owner_kind, first.owner_id],
                            finish=getattr(reply, "finish_reason", None))
                if cause == "cut_off":
                    smaller = _split_harvest(batch, prior, harvest, limit,
                                             max_tokens, first, depth)
                    if smaller is not None:
                        trace.event("error", batch.document_id,
                                    where=prompt_id, kind="split",
                                    attempt=attempt,
                                    owner=[first.owner_kind, first.owner_id])
                        return smaller
                    # One passage, and the ceiling raised as far as it goes.
                    # Nothing to split and nothing to shorten, so the request
                    # is a hole -- named as one, not filled with the half of
                    # it that arrived.
                    why[0] = "cut_off"
                    break
                conversation.append({"role": "assistant",
                                     "content": reply.message.content or ""})
                conversation.append({"role": "user", "content": correction})
            except Exception as exc:
                log.warning("   harvest %s/%s+%d attempt %d failed: %s",
                            first.owner_kind, first.owner_id,
                            len(batch.items) - 1, attempt, exc)
                status = getattr(exc, "status_code", None)
                trace.event("error", batch.document_id, where=prompt_id,
                            kind="exception", attempt=attempt,
                            status=status, detail=str(exc)[:300],
                            owner=[first.owner_kind, first.owner_id])
                # No HTTP status at all is a transport failure: the server is
                # not there. That is the case a resume must never mistake for
                # a harvested document.
                why[0] = "no_answer" if isinstance(status, int) else "unreachable"
                transport = not isinstance(status, int)
                if isinstance(status, int) and 400 <= status < 500 and status != 429:
                    fitted = fitted_max_tokens(exc, limit, prompt_id)
                    if fitted is not None:
                        limit = fitted
                        continue
                    # A request the server refuses is refused every time. The
                    # last run spent three tries and eight seconds of sleep on
                    # each over-long section before writing the same sentinel.
                    break
            # Every attempt but the last, and the loop runs to
            # MAX_RETRIES + CODE_ROUNDS: the old bound stopped two short of it.
            failures += 1
            if attempt < MAX_RETRIES + CODE_ROUNDS:
                time.sleep(retry_wait(failures, transport))
        # Sources the model never answered for are a hole in the harvest, and
        # holes must be visible: the caller counts these via the sentinel.
        # One per source, so a batch of six that died is six holes, not one.
        # The cause rides along, because a server that is gone and a model
        # that answered nothing are the same row in the output and must not
        # be the same thing to the resume: an unreachable server would
        # otherwise stamp every remaining document as harvested.
        trace.event("error", batch.document_id, where=prompt_id,
                    kind="gave_up", why=why[0],
                    sources=[[it.source.owner_kind, it.source.owner_id]
                             for it in batch.items],
                    ms=int((time.time() - started) * 1000))
        return {"tuples": [{"_harvest_failed": True, "_why": why[0],
                            "source": batch.label(i)}
                           for i in range(len(batch.items))],
                "status": "failed", "need_more": []}

    return harvest


def _field_payload(shown: list, rows: list, slots,
                   corrections: Optional[list] = None,
                   owner_of: Optional[dict] = None) -> dict:
    """The request body of one field request, over the window shown.

    Several fields at once. One request per field was one round trip per
    coordinate: measured over 60 documents, 2,108 field requests each, which
    is what made a corpus run 82 hours. Every field still answers for itself
    and quotes for itself; only the number of round trips changes.

    Sources first, rows second, the field last. Consecutive windows then share
    the part of the prefix that did not move, which is what makes asking many
    short questions cheaper than asking one long one.
    """
    sources = []
    for index, source in enumerate(shown):
        entry = {"id": f"Q{index + 1}", "kind": source.owner_kind,
                 "title": source.provenance.get("title"),
                 "section": source.provenance.get("section_title"),
                 "text": source.text}
        # Where this source stands, so "the section this table is in" is a
        # fact the request carries rather than one the model has to infer
        # from the order the sources happen to be in.
        for key in ("page", "block_id"):
            if source.provenance.get(key):
                entry[key] = source.provenance[key]
        sources.append(entry)
    # Which shown source is which, so a row can name its own by id rather
    # than by the model recognising its own quote among five passages.
    where = {(s.owner_kind, s.owner_id): f"Q{i + 1}"
             for i, s in enumerate(shown)}
    listed = []
    for row in rows:
        entry = {"id": row.label,
                 "value": row.claim.get("value"),
                 "quote": row.claim.get("quote")}
        own = (owner_of or {}).get(row.label)
        here = (where.get((own.owner_kind, own.owner_id))
                if own is not None else None)
        if here:
            entry["source"] = here
        unit = row.claim.get("unit_raw") or row.claim.get("unit")
        if unit:
            entry["unit"] = unit
        # Which cell of the quoted table row this number sits in. Three
        # numbers under three year columns share one quote, and the column is
        # what tells them apart — a fact already in hand here, so it is handed
        # over rather than left to be counted.
        cell = pipeline_cell_index(entry["quote"], entry["value"])
        if cell is not None:
            entry["column"], entry["columns"] = cell
        listed.append(entry)
    asked = []
    for slot in ([slots] if not isinstance(slots, (list, tuple)) else slots):
        field = {"name": slot.name, "question": slot.question}
        if slot.options:
            field["options"] = slot.answerable()
        asked.append(field)
    out = {"sources": sources, "rows": listed, "fields": asked}
    if corrections:
        # What was wrong with the last answer, per row. A verification failure
        # is information the model can act on, and withholding it turns three
        # attempts into the same wrong answer three times. Only the row and
        # the sentence go over the wire: the rest of the entry is for the
        # trace, and the model pays for every token it is shown.
        out["corrections"] = [{"row": c.get("row"), "reason": c.get("reason")}
                              for c in corrections]
    return out


def keeps_row(slot, answer, allowed) -> bool:
    """Does this gate answer keep the row in the slice this run serializes?

    The answer is the option's LABEL, because that is what a field reply
    carries and what merge_field writes: "Potenzial", not "out:potential". The
    profile names classes, so the label is resolved here — reading the profile
    as if it held German spellings would have kept every potential and thrown
    away every target scenario, which is exactly what it did.

    Undecided keeps the row. A coordinate that came back empty or "not stated"
    is a finding about the passages, not a licence to throw the value away,
    and dropping on it would silently shrink the harvest by whatever the sweep
    happened to miss.

    *allowed* None means every class the graph takes, which is every entry
    that does not ride the out: convention. A tuple names the answers.
    """
    text = str(answer or "").strip()
    if not text or text == fields.UNSTATED:
        return True
    uri = {option.label: option.uri
           for option in (getattr(slot, "options", None) or ())}.get(text, text)
    if allowed is None:
        return not str(uri).startswith("out:")
    return uri in allowed


def make_field_asker(image_root: Optional[Path] = None) -> Callable:
    """ask(batch, rows, slot) -> reply, or None when the field stays unasked.

    No sandbox: a field answer is a choice and a quote, never arithmetic. A
    reply that did not fit its token ceiling is not patched up either — the
    rows are halved and asked again, so every row is answered under the same
    evidence rules, and what is still missing is missing on the record.
    """
    prompt = prompts.load(FIELD_PROMPT_ID)
    client = _client()
    temperature = float(prompt.meta.get("temperature", 0.1))
    max_tokens = int(prompt.meta.get("max_tokens", 4096))

    def ask(shown: list, rows: list, slots,
            corrections: Optional[list] = None,
            document_id: Optional[int] = None,
            usage_out: Optional[dict] = None,
            owner_of: Optional[dict] = None, *,
            depth: int = 0) -> Optional[dict]:
        slots = list(slots) if isinstance(slots, (list, tuple)) else [slots]
        name = "+".join(s.name for s in slots)
        payload = json.dumps(_field_payload(shown, rows, slots, corrections,
                                            owner_of),
                             ensure_ascii=False, indent=2)
        # The crops ride along, as they do for the value request. A table's
        # transcription is a model's reading of a picture, and the coordinate
        # this asks for — the year in the header, the carrier in the row label
        # — is often clearer in the picture than in the transcription. The
        # field request was sending JSON text and nothing else.
        content: object = payload
        parts = [{"type": "text", "text": payload}]
        for index, source in enumerate(shown):
            path = source.image_path
            if not (path and ATTACH_IMAGES):
                continue
            part = _image_part(str(image_root / path) if image_root else path)
            if part is not None:
                parts.append({"type": "text", "text": f"Bild zu Q{index + 1}:"})
                parts.append(part)
        if len(parts) > 1:
            content = parts
        # A model error is told to the model, the same way a verification
        # failure is. Retrying a malformed reply without saying what was
        # malformed is one attempt three times.
        transport = False
        conversation: list = [{"role": "user", "content": content}]
        limit = max_tokens
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = client.chat.completions.create(
                    model=LLM_MODEL, temperature=temperature,
                    max_tokens=limit,
                    messages=[{"role": "system", "content": prompt.text},
                              *conversation],
                    extra_body=request_extras(),
                )
                transport = False
                reply = response.choices[0]
                usage = getattr(response, "usage", None)
                _observe_usage(usage)
                if usage_out is not None:
                    # Per request, not only in the run's total. The field
                    # requests are the bulk of a document and nothing said how
                    # much any single one cost, so no ceiling could be set
                    # from the trace.
                    usage_out["prompt_tokens"] = getattr(
                        usage, "prompt_tokens", None)
                    usage_out["completion_tokens"] = getattr(
                        usage, "completion_tokens", None)
                answer = _loads_object(reply.message.content)
                if isinstance(answer, dict):
                    return answer
                cause, correction = _reply_fault(
                    reply, limit,
                    shorter="Fasse Zeilen mit derselben Antwort in \"groups\" "
                            "zusammen und zitiere nur die kurze Stelle, an "
                            "der die Angabe steht.")
                log.warning("   field %s attempt %d: %s reply%s",
                            name, attempt, cause, _unparsable(reply))
                trace.event("error", document_id, where="field",
                            kind="unreadable", cause=cause, slot=name,
                            attempt=attempt,
                            finish=getattr(reply, "finish_reason", None))
                if cause == "cut_off" and len(rows) > 1 \
                        and depth < SPLIT_DEPTH:
                    # Half the rows per request, not half an answer. The reply
                    # used to be closed with the brackets it was missing, and
                    # every row past the cut then took whatever the last
                    # complete field in it happened to say.
                    cut = len(rows) // 2
                    merged: dict = {"answers": {}, "groups": []}
                    for part in (rows[:cut], rows[cut:]):
                        here = {r.label for r in part}
                        got = ask(shown, part, slots,
                                  [c for c in (corrections or ())
                                   if c.get("row") in here],
                                  document_id, usage_out, owner_of,
                                  depth=depth + 1)
                        if not isinstance(got, dict):
                            continue
                        if isinstance(got.get("answers"), dict):
                            merged["answers"].update(got["answers"])
                        merged["groups"].extend(
                            g for g in (got.get("groups") or ())
                            if isinstance(g, dict))
                    trace.event("error", document_id, where="field",
                                kind="split", slot=name, attempt=attempt)
                    return merged if (merged["answers"]
                                      or merged["groups"]) else None
                conversation.append({"role": "assistant",
                                     "content": reply.message.content or ""})
                conversation.append({"role": "user", "content": correction})
            except Exception as exc:
                log.warning("   field %s attempt %d failed: %s",
                            name, attempt, exc)
                status = getattr(exc, "status_code", None)
                trace.event("error", document_id, where="field",
                            kind="exception", slot=name, attempt=attempt,
                            status=status, detail=str(exc)[:300])
                transport = not isinstance(status, int)
                if isinstance(status, int) and 400 <= status < 500 and status != 429:
                    fitted = fitted_max_tokens(exc, limit, f"field {name}")
                    if fitted is not None:
                        limit = fitted
                        continue
                    break
            if attempt < MAX_RETRIES:
                time.sleep(retry_wait(attempt, transport))
        return None

    return ask


def _review_payload(row: dict, shown: list, parameter, slots) -> dict:
    """The request body of one review request: one row, its two passages.

    Its own body and not `_field_payload`'s: that one exists to amortise many
    rows over one caption and carries the ids, groups and corrections that go
    with it. Reusing it would bind this prompt to the whole field contract,
    and the review asks a different question of one row.
    """
    sources = []
    for index, source in enumerate(shown):
        entry = {"id": f"Q{index + 1}", "kind": source.owner_kind,
                 "title": source.provenance.get("title"),
                 "section": source.provenance.get("section_title"),
                 "text": source.text}
        for key in ("page", "block_id"):
            if source.provenance.get(key):
                entry[key] = source.provenance[key]
        # A machine token, not prose: which passage is the section the other
        # one stands in. The wording of that belongs in each profile's own
        # prompt, in the language that profile's corpus is written in.
        if source.provenance.get("via") == "parent":
            entry["via"] = "parent"
        sources.append(entry)
    where = {(s.owner_kind, s.owner_id): f"Q{i + 1}"
             for i, s in enumerate(shown)}
    provenance = row.get("provenance") or {}
    listed = {"value": row.get("value"), "quote": row.get("quote")}
    here = where.get((provenance.get("owner_kind"),
                      provenance.get("owner_id")))
    if here:
        listed["source"] = here
    there = where.get(("section", provenance.get("parent_section")))
    if there:
        listed["section"] = there
    unit = row.get("unit_raw") or row.get("unit")
    if unit:
        listed["unit"] = unit
    # Which cell of the quoted table row the number sits in. Three numbers
    # under three year columns share one quote, and the column is what tells
    # them apart.
    cell = pipeline_cell_index(listed.get("quote"), listed.get("value"))
    if cell is not None:
        listed["column"], listed["columns"] = cell
    asked = []
    for slot in slots:
        field = {"name": slot.name, "question": slot.question}
        if slot.options:
            field["options"] = slot.answerable()
        asked.append(field)
    return {"sources": sources, "row": listed, "fields": asked}


def make_review_asker(image_root: Optional[Path] = None) -> Callable:
    """ask(row, shown, parameter, slots) -> reply, or None.

    One stored value, read again over the two passages it may quote from. The
    same model and a narrower window, so what it can find is a reading that
    contradicts itself -- not a reading that is wrong about the picture in the
    same way twice.
    """
    prompt = prompts.load(REVIEW_PROMPT_ID)
    client = _client()
    temperature = float(prompt.meta.get("temperature", 0.0))
    max_tokens = int(prompt.meta.get("max_tokens", 1024))

    def ask(row: dict, shown: list, parameter, slots) -> Optional[dict]:
        payload = json.dumps(_review_payload(row, shown, parameter, slots),
                             ensure_ascii=False, indent=2)
        # The crops ride along exactly as they do for a field request: a
        # transcription is a model's reading of a picture, and a review of a
        # transcription alone would be a review of that first reading.
        content: object = payload
        parts = [{"type": "text", "text": payload}]
        for index, source in enumerate(shown):
            path = source.image_path
            if not (path and ATTACH_IMAGES):
                continue
            part = _image_part(str(image_root / path) if image_root else path)
            if part is not None:
                parts.append({"type": "text", "text": f"Bild zu Q{index + 1}:"})
                parts.append(part)
        if len(parts) > 1:
            content = parts
        transport = False
        conversation: list = [{"role": "user", "content": content}]
        limit = max_tokens
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = client.chat.completions.create(
                    model=LLM_MODEL, temperature=temperature,
                    max_tokens=limit,
                    messages=[{"role": "system", "content": prompt.text},
                              *conversation],
                    extra_body=request_extras(),
                )
                transport = False
                reply = response.choices[0]
                _observe_usage(getattr(response, "usage", None))
                answer = _loads_object(reply.message.content)
                if isinstance(answer, dict):
                    return answer
                # One row and two passages: there is nothing here to split, so
                # a reply that did not fit is told to quote less rather than
                # to answer for fewer rows.
                cause, correction = _reply_fault(
                    reply, limit,
                    shorter="Zitiere nur die kurze Stelle, an der die Angabe "
                            "steht, und lass jedes Feld weg, das die zwei "
                            "Passagen nicht tragen.")
                log.warning("   review attempt %d: %s reply%s",
                            attempt, cause, _unparsable(reply))
                conversation.append({"role": "assistant",
                                     "content": reply.message.content or ""})
                conversation.append({"role": "user", "content": correction})
            except Exception as exc:
                log.warning("   review attempt %d failed: %s", attempt, exc)
                status = getattr(exc, "status_code", None)
                transport = not isinstance(status, int)
                if isinstance(status, int) and 400 <= status < 500 and status != 429:
                    fitted = fitted_max_tokens(exc, limit, "review")
                    if fitted is not None:
                        limit = fitted
                        continue
                    break
            if attempt < MAX_RETRIES:
                time.sleep(retry_wait(attempt, transport))
        return None

    return ask


def make_sweeper(ask: Callable, *,
                 more_sources: Optional[Callable] = None,
                 rest_of_document: Optional[Callable] = None,
                 parents: Optional[Callable] = None,
                 anchors: Optional[dict] = None) -> Callable:
    """sweep_field(batch, rows, slots, anchor_id) -> what the sweep came to.

    Lifted out of the harvester so a pass that re-reads ONE coordinate of an
    already harvested document walks the same three stages, in the same
    order, under the same allowances. A second copy of this would be a second
    set of numbers, and every measurement the sweep has ever produced is
    about this one.

    Its five dependencies are exactly what it closed over inside the
    harvester: the asker, and the three ways of finding more passages plus
    the anchor sets that seed them.
    """
    anchors = anchors or {}

    def sweep_field(batch, rows: list, slots, anchor_id: str = "") -> dict:
        """Short windows over the document until these coordinates are read.

        Several fields in one request. One field per request was one round
        trip per coordinate: 2,108 of them per document, which is what made a
        corpus run 82 hours. Each field still answers for itself and quotes
        for itself, and each is folded on its own, so nothing about the
        evidence changes.

        The value's own passages first, because a carrier usually is in the
        table row it labels. What is still open after that is looked for
        further out, one short window at a time with an overlap, because the
        year of a table is in its caption and the scenario is in the section
        heading — neither of which the value's passage contains.

        Short windows and many requests, not one wide one. A window that holds
        the answer holds it whether or not ninety other passages ride along,
        and the ninety cost the attention that would have found it.

        One window saying "not in here" ends nothing. It is a statement about
        two passages, and the next window shows two others: a row stays open
        through out:unstated and closes only on a reading. What ends the sweep
        is running out of document — retrieval first, then the sections in
        their own order — or running out of budget, and those two are written
        down differently, because "the plan does not say" and "we stopped
        looking" are the pair this whole stage exists to keep apart.
        """
        slots = list(slots) if isinstance(slots, (list, tuple)) else [slots]
        name = "+".join(slot.name for slot in slots)
        # Which source each row came from: the request names it for the
        # row, and a later window shows it and its section again
        # (`re_entry`).
        owner_of = {row.label: batch.items[row.item_index].source
                    for row in rows
                    if 0 <= row.item_index < len(batch.items)}
        totals = {"filled": 0, "unquoted": 0, "unbacked": 0, "unstated": 0,
                  "raw_missing": 0, "raw_foreign": 0, "retried": 0}
        seen = {(i.source.owner_kind, i.source.owner_id) for i in batch.items}
        # Every passage this sweep has already materialised, by key. `seen`
        # answers what must not be FETCHED again; this answers what may be
        # SHOWN again, which is the opposite question and needs the passage
        # itself rather than its key.
        held = {(i.source.owner_kind, i.source.owner_id): i.source
                for i in batch.items}
        # One allowance per stage, not one for the sweep. Own, retrieval
        # and rest are three different searches, and a stage that ran out must
        # not be the reason the next one never ran. Two ways it was:
        #
        #   * own's retries were charged to retrieval. Measured on a stubbed
        #     sweep: retrieval got 21 windows when own retried three times and
        #     23 when it answered once, for the same document.
        #   * rest took its allowance by ASSIGNING the shared counter,
        #     `max(0, FIELD_MAX_WINDOWS - REST_MAX_WINDOWS)`, which is
        #     REST_MAX_WINDOWS only while that number is the smaller one. Set
        #     the rest allowance above the field one and it becomes 0, and the
        #     stage silently gets the whole budget.
        #
        budget = window_budget()
        spent = {stage: 0 for stage in budget}
        state = {"answer": None, "stage": "own"}

        def still_open(pool: list) -> list:
            """Rows with at least one of these fields still unread."""
            wanted = {row.label for slot in slots
                      for row in open_rows(pool, slot)}
            return [row for row in pool if row.label in wanted]

        def re_entry(todo: list, already: set) -> list:
            """The passages these rows were last read in, to ride along.

            The sweep asks five coordinates of the same row and moves on after
            each window. Where the sector was read, the aggregation is a
            column further right — so the search starts again where it last
            found something instead of striking that passage off for good.

            Three places, in this order, and only the ones the window does not
            already show:

            - the passage a coordinate of this row was READ in. It is the one
              of the three that `seen` makes unreachable forever, and it is
              the one that has already proved it carries this row's answers.
            - the section the row's own passage stands in. It is also the only
              one of the three that is in no checked pool from the second
              window on, so an answer quoting the caption of its own table
              came back unbacked: its quote stood in no passage the check was
              given.
            - the row's own passage last, because `merge_field` checks against
              `batch.sources` in every window anyway and the row carries its
              own quote in the request, so it is the one that is not lost when
              the budget cuts the list off.
            """
            found, sections, owns = [], [], []
            picked = set()

            def take(bucket, key):
                source = held.get(key)
                if source is None or key in picked or key in already:
                    return
                picked.add(key)
                bucket.append(source)

            for row in todo:
                for slot in slots:
                    where = row.claim.get(f"{slot.name}_source")
                    if isinstance(where, (list, tuple)) and len(where) == 2:
                        take(found, (where[0], where[1]))
            for row in todo:
                own = owner_of.get(row.label)
                parent = (own.provenance or {}).get("parent_section") \
                    if own is not None else None
                if parent is not None:
                    take(sections, ("section", parent))
            for row in todo:
                own = owner_of.get(row.label)
                if own is not None:
                    take(owns, (own.owner_kind, own.owner_id))
            return (found + sections + owns)[:FIELD_RE_ENTRY]

        def run(windows) -> bool:
            """Ask over these windows. False when the budget ran out.

            A window is asked again when its answers came back unbackable, and
            the retry carries what was wrong with each row. A model told "R7:
            your quote is in none of the sources" can fix R7; a model told
            nothing gives the same answer again, which is why three attempts
            without the reason are one attempt three times. Every attempt
            counts against the window budget, so a stubborn coordinate cannot
            eat the document.
            """
            for window in windows:
                todo = still_open(rows)
                if not todo:
                    return True
                # The re-entry rides in FRONT of the window and is not part
                # of it: the window generator is untouched, so the frontier
                # still advances by exactly one window per request and a
                # re-shown passage can never stand in for a fresh one.
                shown = re_entry(todo, {(s.owner_kind, s.owner_id)
                                        for s in window}) + list(window)
                corrections = None
                # Only where a retry pays. Measured on the M3 run: a retry of
                # the OWN window fills 4.88 rows, a third of what a fresh own
                # window fills; a retry further out fills 0.10, a seventh of
                # the fresh window it displaces. 145 of 149 third attempts
                # filled nothing at all, and 263 of 334 retries came back with
                # exactly the same failures as the attempt before them.
                attempts = FIELD_ATTEMPTS if state["stage"] == "own" else 1
                for attempt in range(attempts):
                    if spent[state["stage"]] >= budget[state["stage"]]:
                        return False
                    spent[state["stage"]] += 1
                    started = time.time()
                    usage: dict = {}
                    state["answer"] = ask(shown, todo, slots, corrections,
                                          batch.document_id, usage, owner_of)
                    # Checked against the window AND the passages the rows
                    # carry. A row's own quote is shown to the model in the
                    # rows list, so citing it is legitimate — and from the
                    # second window on it is no longer among `shown`, which
                    # threw away correct readings by the hundred: one batch
                    # logged 520 dropped against 31 read.
                    # One reply, folded field by field. A field that is
                    # missing from it is simply not folded, which leaves its
                    # rows open for the next window — the same outcome as an
                    # empty answer, and the same as before.
                    answered = (state["answer"] or {}).get("fields")
                    if not isinstance(answered, dict):
                        answered = {}
                    counts = {"filled": 0, "unquoted": 0, "unbacked": 0,
                              "unstated": 0, "raw_missing": 0,
                              "raw_foreign": 0, "failed": []}
                    # Which FIELD filled and which failed, not only how many.
                    # Five fields answer in one reply, and a run that logs
                    # "aggregation+carrier+sector+year+spatial_scope: 3 of 5"
                    # cannot say which two were dropped: 7,738 unbacked and
                    # 3,110 unquoted answers of one corpus group were not
                    # attributable to a coordinate.
                    filled_by: dict = {}
                    unbacked_by: dict = {}
                    for slot in slots:
                        got = merge_field(rows, list(shown) + batch.sources,
                                          slot, answered.get(slot.name),
                                          window=(state["stage"],
                                                  sum(spent.values())))
                        for key in ("filled", "unquoted", "unbacked",
                                    "unstated", "raw_missing",
                                    "raw_foreign"):
                            counts[key] += got[key]
                        if got["filled"]:
                            filled_by[slot.name] = got["filled"]
                        if got["unquoted"] or got["unbacked"]:
                            unbacked_by[slot.name] = (got["unquoted"]
                                                      + got["unbacked"])
                        for bad in got["failed"]:
                            counts["failed"].append(dict(bad,
                                                         field=slot.name))
                    for key in ("filled", "unquoted", "unbacked", "unstated",
                                "raw_missing", "raw_foreign"):
                        totals[key] += counts[key]
                    totals["retried"] += 1 if attempt else 0
                    # The window this coordinate was asked in, what was shown,
                    # and what came back. Every knob this stage has cuts
                    # through this distribution, and none of them could be set
                    # from a log line that only counted the failures.
                    trace.event("field", batch.document_id, slot=name,
                                anchor=anchor_id,
                                window=sum(spent.values()),
                                stage=state["stage"], attempt=attempt,
                                parameter=(batch.parameter.uri
                                           if batch.parameter else None),
                                open=len(todo), reply=state["answer"] is not None,
                                shown=[[x.owner_kind, x.owner_id]
                                       for x in shown],
                                ms=int((time.time() - started) * 1000),
                                filled_by=filled_by, unbacked_by=unbacked_by,
                                prompt_tokens=usage.get("prompt_tokens"),
                                completion_tokens=usage.get(
                                    "completion_tokens"),
                                **{k: counts[k] for k in
                                   ("filled", "unquoted", "unbacked",
                                    "unstated", "raw_missing",
                                    "raw_foreign")})
                    for bad in counts["failed"]:
                        trace.event("drop", batch.document_id, slot=name,
                                    field=bad.get("field"),
                                    window=sum(spent.values()),
                                    attempt=attempt,
                                    row=bad.get("row"),
                                    why=bad.get("why") or "unbacked")
                    corrections = counts["failed"]
                    if not corrections:
                        break
                    named = {c["row"] for c in corrections}
                    todo = [r for r in still_open(rows) if r.label in named]
                    if not todo:
                        break
            return True

        # The value's own passages AND the sections they stand in. A table
        # carries its numbers and its row labels; the year, the scenario and
        # the caption live one level up, and the own window never showed it.
        own = list(batch.sources)
        for parent in (parents(batch.sources) if parents else ()):
            own.append(parent)
            seen.add((parent.owner_kind, parent.owner_id))
            held[(parent.owner_kind, parent.owner_id)] = parent
        combed = run([own])
        state["stage"] = "retrieval"
        for _ in range(FIELD_ROUNDS):
            if not combed or not still_open(rows) or more_sources is None:
                break
            # Still open, so look further out. The probes are the anchors
            # written for THIS question: sentences as a plan would print the
            # answer. The question itself was what this searched with before,
            # and a question is the one sentence that never stands in a
            # document.
            probes = list(anchors.get(anchor_id) or ())
            if not probes:
                probes = [slot.question for slot in slots if slot.question]
            probes += [q for q in (state["answer"] or {}).get("need_more") or []
                       if isinstance(q, str) and len(q) > 20]
            fresh = more_sources(batch.document_id, probes, set(seen)) or []
            if not fresh:
                break
            for source in fresh:
                seen.add((source.owner_kind, source.owner_id))
                held[(source.owner_kind, source.owner_id)] = source
            combed = run(window_sources(fresh, FIELD_WINDOW, FIELD_OVERLAP))

        open_now = still_open(rows)
        if open_now and rest_of_document is not None:
            # Retrieval has nothing left to offer and the coordinate is still
            # open. Read the rest of the plan rather than call it unstated on
            # the strength of what a ranking happened to surface.
            #
            # Not `combed and ...`: `run` returns False exactly when the
            # budget ran out, and a sweep with budget left has no open rows.
            # So the old condition was never both true at once -- 0 of the 70
            # sweeps of the M3 run entered this stage, and 32 of the 33 that
            # hit the cap had had exactly one retrieval round out of four.
            # The stage that exists to keep "we stopped looking" apart from
            # "the plan does not say it" was unreachable, and the harvest
            # shows it: 789 exhausted and 0 unstated.
            #
            # Its own allowance, and now its own counter rather than a
            # number written into the shared one. Bounded, because 33 sweeps of
            # that run hit the cap and an unbounded second pass would put the
            # requests per document over the 1161 the acceptance allows.
            rest = rest_of_document(
                batch.document_id, set(seen),
                own_section_number([owner_of[row.label] for row in open_now
                                    if row.label in owner_of])) or []
            for source in rest:
                held[(source.owner_kind, source.owner_id)] = source
            state["stage"] = "rest"
            combed = run(window_sources(rest, FIELD_WINDOW, FIELD_OVERLAP))

        stranded = 0
        if not combed:
            for slot in slots:
                for row in open_rows(rows, slot):
                    # Still open with the document unread to the end. Not the
                    # same finding as a document that does not say it, and not
                    # recorded as one.
                    row.claim[f"{slot.name}_state"] = EXHAUSTED
                    stranded += 1
        totals["asked"] = sum(spent.values())
        totals["exhausted"] = stranded
        trace.event("sweep", batch.document_id, slot=name,
                    anchor=anchor_id, windows=sum(spent.values()),
                    rows=len(rows), combed=combed, **totals)
        return totals

    return sweep_field


def make_fieldwise_harvester(image_root: Optional[Path] = None,
                             more_sources: Optional[Callable] = None,
                             rest_of_document: Optional[Callable] = None,
                             spec=None, anchors: Optional[dict] = None,
                             slice_gate: Optional[dict] = None,
                             parents: Optional[Callable] = None,
                             frame_axes: Optional[list] = None
                             ) -> Callable:
    """A harvest(batch, prior) that asks per field and answers like the old one.

    Same signature as make_harvester's, so the scheduler above it does not
    change: the batch is still the unit in flight, and the sweep over the
    fields happens inside one batch's turn.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    find_rows = make_harvester(image_root, prompt_id=ROWS_PROMPT_ID, spec=spec)
    ask = make_field_asker(image_root)
    anchors = anchors or {}
    pool = ThreadPoolExecutor(max_workers=FIELD_PARALLEL,
                              thread_name_prefix="field")

    sweep_field = make_sweeper(ask, more_sources=more_sources,
                               rest_of_document=rest_of_document,
                               parents=parents, anchors=anchors)

    def harvest(batch, prior: Optional[list] = None) -> dict:
        reply = find_rows(batch, prior)
        rows, orphans = rows_from_reply(batch, reply, frame_axes)

        def project(group: list, axes: list) -> None:
            """The pair onto these rows, as far as their parameter has its axes.

            Before anything is asked. The sweep only offers a coordinate that
            is still open, so projecting here is what makes the year sweeper
            fall away rather than run and find nothing: measured on M3, the
            year axis produced 1,849 refusals against 0 readings, because
            every later window excluded the row's own source and only that one
            could carry the year.

            Only the frame coordinates the row's parameter has. The pair spans
            the document, but the planning organisation has no scenario and no
            year, and 11 of its rows on corpus_m5 carried both, which the
            schema refuses.
            """
            own = {axis.name: axis for axis in axes}
            slots = [own[slot.name] for slot in frame_axes or ()
                     if slot.name in own]
            if not group or not slots:
                return
            if batch.frame:
                written = apply_frame(group, batch.frame, batch.frame_index,
                                      slots, batch.sources)
                if written:
                    log.debug("   frame %s: %d coordinate(s) on %d row(s)",
                              batch.document_id, written, len(group))
            elif batch.frame_default:
                # A passage that names no pair at all, read like the rest and
                # written under the document's default pair, cited on the
                # passage the frame read it in.
                written = apply_frame(group, batch.frame_default,
                                      batch.frame_default_index, slots,
                                      batch.sources)
                if written:
                    log.debug("   default pair %s: %d coordinate(s) on %d "
                              "row(s)", batch.document_id, written, len(group))

        if not rows:
            # Nothing to sweep: no value in these passages, a value request
            # that died, or every claim refused above. What goes back is what
            # `rows_from_reply` made of the claims, sentinels and reasons
            # included. The raw claims went back until now, and verified a
            # second time they came out as "claim names no parameter of the
            # spec": 598 of Kassel's refusals.
            return {**(reply if isinstance(reply, dict) else {}),
                    "tuples": orphans}
        counts: dict = {}
        jobs: list = []          # (rows, slot, anchor id)
        slots_of: dict = {}      # row label -> the slots that apply to it

        if batch.parameter is None:
            # Which quantity each value is comes first, because it decides
            # which coordinates the row even has. One request, one quote, and
            # a row it cannot answer for gets no axes rather than the axes of
            # a guess.
            #
            # Asked only where the unit leaves it open. The spec says it
            # itself — "the unit separates the two parameters" — and over the
            # kwp spec the nine energy units and the forty-two emission units
            # share not one spelling. Asking anyway cost 322 of 1,043 field
            # windows on Kassel, 30.9 percent, for a coordinate not one of
            # 559 accepted tuples contradicted.
            slot = fields.parameter_slot(spec)
            undecided = []
            for row in rows:
                parameter = fields.derive_parameter(spec, row.claim)
                if parameter is None:
                    if fields.parameter_undecidable(spec, row.claim):
                        # No parameter of the spec can hold this row, so the
                        # sweep has no answer to find: whatever it returned,
                        # `verify` refuses it on the same unit lookup. The row
                        # still goes on to be refused with the unit as the
                        # reason -- it is just not asked about first.
                        row.claim["parameter_state"] = fields.OUT_OF_SLICE
                        continue
                    undecided.append(row)
                    continue
                row.claim["parameter"] = parameter.label
                row.claim["parameter_state"] = fields.DERIVED
                wording = row.claim.get("unit_raw") or row.claim.get("unit")
                if wording:
                    row.claim["parameter_raw"] = wording
                if row.claim.get("quote"):
                    row.claim["parameter_quote"] = row.claim["quote"]
            if undecided:
                counts[slot.name] = sweep_field(batch, undecided, slot,
                                                PARAMETER_ANCHOR)
            uri_of = {opt.label: opt.uri for opt in slot.options}
            grouped: dict = {}
            for row in rows:
                uri = uri_of.get(str(row.claim.get("parameter") or "").strip())
                if uri is None:
                    slots_of[row.label] = [slot]
                    continue
                row.claim["parameter"] = uri
                grouped.setdefault(uri, []).append(row)
            for uri, group in grouped.items():
                axes = fields.axis_slots(spec.by_uri[uri])
                for row in group:
                    slots_of[row.label] = [slot] + axes
                project(group, axes)
                # What the spec decides is written before anything is asked,
                # and before the gate: a row that leaves at the gate still
                # carries the coordinates that never needed a request, so
                # `out_of_slice` says "never asked" about the axes that
                # really were not asked and about no others.
                for axis in axes:
                    fields.apply_derived(group, axis)
                axes = [axis for axis in axes if not axis.derive]
                by_name = {axis.name: axis for axis in axes}
                gate = [by_name[name] for name in (slice_gate or {})
                        if name in by_name]
                gated = {axis.name for axis in gate}
                # Sequential and first. Each of these can close a row, and a
                # closed row must not pay for the axes behind it: measured on
                # 20 plans, 4,064 of 6,763 harvested tuples were dropped by
                # the serializer for exactly these two coordinates, after the
                # run had paid for all seven axes of every one of them.
                inside = group
                if gate:
                    got = sweep_field(batch, inside, gate,
                                      anchor_key(uri, gate[0].name))
                    counts["+".join(a.name for a in gate)] = got
                    for axis in gate:
                        allowed = (slice_gate or {}).get(axis.name)
                        inside = [row for row in inside
                                  if keeps_row(axis, row.claim.get(axis.name),
                                               allowed)]
                staying = {row.label for row in inside}
                for row in group:
                    if row.label in staying:
                        continue
                    # Never asked, and said so. An empty cell here would be
                    # indistinguishable from a coordinate the model dropped.
                    for axis in axes:
                        if axis.name not in gated:
                            row.claim.setdefault(f"{axis.name}_state",
                                                 fields.OUT_OF_SLICE)
                rest = [axis for axis in axes if axis.name not in gated]
                if inside and rest:
                    jobs.append((inside, rest, anchor_key(uri, rest[0].name)))
        else:
            axes = fields.axis_slots(batch.parameter)
            for row in rows:
                slots_of[row.label] = axes
            project(rows, axes)
            for axis in axes:
                fields.apply_derived(rows, axis)
            axes = [axis for axis in axes if not axis.derive]
            if axes:
                jobs.append((rows, axes,
                             anchor_key(batch.parameter.uri, axes[0].name)))

        futures = {pool.submit(sweep_field, batch, group, group_slots, anchor):
                   "+".join(a.name for a in group_slots)
                   for group, group_slots, anchor in jobs}
        for future in as_completed(futures):
            label = futures[future]
            try:
                got = future.result()
            except Exception as exc:            # pragma: no cover - defensive
                log.warning("   field %s raised: %s", label, exc)
                continue
            into = counts.setdefault(label, dict(got))
            if into is not got:
                for key, value in got.items():
                    into[key] = into.get(key, 0) + value
        blank = 0
        for row in rows:
            blank += mark_unanswered([row], slots_of.get(row.label, []))
        tally = {k: sum(c.get(k, 0) for c in counts.values())
                 for k in ("filled", "unstated", "unquoted", "unbacked",
                           "asked", "retried")}
        if tally["unquoted"] or tally["unbacked"] or blank:
            log.info("   fields: %d read, %d not stated, %d unanswered, "
                     "dropped %d (quote not in source) + %d (answer not in quote)",
                     tally["filled"], tally["unstated"], blank,
                     tally["unquoted"], tally["unbacked"])
        # The label goes back on so the fold routes each claim to the source
        # the value request already settled on, instead of deciding a second
        # time from the quote alone.
        for row in rows:
            row.claim["source"] = batch.label(row.item_index)
        return {"tuples": [row.claim for row in rows] + orphans,
                "status": reply.get("status", "complete"),
                "need_more": reply.get("need_more") or [],
                "_fieldwise": tally}

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


def harvest_batches(batches: list, harvest: Callable, *,
                    more_sources: Optional[Callable] = None,
                    verify: Optional[Callable] = None,
                    on_give_up: Optional[Callable] = None,
                    workers: int = LLM_PARALLEL) -> list:
    """Every batch of the whole run in flight at once.

    The batch is the unit, not the chain. A chain — one document, one
    parameter — has to be read in order only if a later batch must be told
    what an earlier one found, and making that ordering real made it the unit
    of scheduling too: the pilot's canary stage is a single document, which
    is three chains, so three requests faced a server sized for two hundred.
    The same document had taken three minutes when every source was its own
    request; it was killed unfinished after nine.

    So `prior` became a hint that each batch reads at dispatch instead of a
    sequence it waits for. *verify* turns one reply into the rows that
    survived checking, and only those are recorded — the hint must not carry
    claims the verifier threw away, or a value refused once is suppressed
    everywhere else in the document.

    Returns [(batch, reply)] in submission order, follow-up batches appended
    as they are earned. Ordering is by index, not by completion: the server
    answers a 40-token table long before a 6000-token section, and the report
    must not depend on that.

    *on_give_up* is called once when the dead-server cut fires. Cancelling this
    group is not enough on its own: the cut fired sixteen times in one run and
    the loop went on to the next group each time, so a server that died at
    01:44 was still being asked at 05:14. What the caller does with it is the
    caller's business, but it has to be able to know.
    """
    from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

    if not batches:
        return []
    sweeps = build_sweeps(batches, FOLLOWUP_ROUNDS)
    results: list = []
    started = time.time()
    submitted = len(batches)

    def one(batch):
        sweep = sweeps[sweep_key(batch)]
        reply = harvest(batch, sweep.snapshot())
        reply = reply if isinstance(reply, dict) else {}
        if verify is not None:
            try:
                sweep.record(verify(batch, reply))
            except Exception as exc:                        # pragma: no cover
                log.warning("   prior for %s/%s not updated: %s",
                            batch.document_id, batch_uri(batch), exc)
        return batch, reply, sweep

    # A server that goes away turns every request into the same failure, and
    # the pool would work its way through the whole queue to find that out.
    # Measured: 53 minutes of dying on five H100s. Past this many consecutive
    # unreachable replies the rest is cancelled and the run ends with its
    # documents unstamped, which is what makes a resume possible.
    dead_streak = [0]
    give_up = max(64, workers)

    with ThreadPoolExecutor(max_workers=max(workers, 1)) as pool:
        pending = {pool.submit(one, b): b for b in batches}
        step = max(submitted // 20, 25)
        while pending:
            done_now, _ = wait(list(pending), return_when=FIRST_COMPLETED)
            for future in done_now:
                batch = pending.pop(future)
                try:
                    batch, reply, sweep = future.result()
                except Exception as exc:                    # pragma: no cover
                    log.warning("   harvest %s/%s raised: %s",
                                batch.document_id, batch_uri(batch), exc)
                    reply = {"tuples": [{"_harvest_failed": True,
                                         "_why": "unreachable",
                                         "source": batch.label(i)}
                                        for i in range(len(batch.items))],
                             "status": "failed", "need_more": []}
                    sweep = None
                results.append((batch, reply))
                if any(t.get("_why") == "unreachable"
                       for t in reply.get("tuples") or []):
                    dead_streak[0] += 1
                    if dead_streak[0] >= give_up:
                        log.error("harvest: %d requests in a row never reached "
                                  "the server — cancelling the remaining %d",
                                  dead_streak[0], len(pending))
                        for f in list(pending):
                            f.cancel()
                        pending.clear()
                        if on_give_up is not None:
                            on_give_up()
                        break
                else:
                    dead_streak[0] = 0
                if sweep is not None and more_sources is not None:
                    # A follow-up joins the pool rather than blocking its
                    # sweep: the passages it brings are new to the whole run,
                    # so nothing else is waiting on them.
                    for extra in follow_up(batch, reply, sweep, more_sources,
                                           max_sources=BATCH_SOURCES,
                                           max_chars=BATCH_CHARS):
                        submitted += 1
                        pending[pool.submit(one, extra)] = extra
                if len(results) % step == 0 or not pending:
                    elapsed = max(time.time() - started, 1e-6)
                    rate = len(results) / elapsed
                    log.info("harvest: %d/%d batches (%.1f/s, %.0f s left)",
                             len(results), submitted, rate,
                             (submitted - len(results)) / max(rate, 1e-6))
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
    if pdf_root is None or os.environ.get("EXTRACT_LOCATE", "1") == "0":
        # The rectangles are display data: they say WHERE on the page a quote
        # sits, never whether the value is accepted. A run that cannot afford
        # to enter MuPDF at all still produces every value, quote and page.
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
            # Under the lock, because this is where MuPDF is entered. The lock
            # guarded the two dicts and not the library, so eight verification
            # threads opened and laid out PDFs at once; a corpus run died of
            # "stack smashing detected" after 204 documents, taking the rest
            # of its group with it. The lru_cache means most calls here are a
            # dict lookup anyway.
            with lock:
                words = words_of(pdf_path, page)
            rects = rects_from_words(words, quote)
            if rects:
                return rects
        return None

    return locate


# ---------------------------------------------------------------------------
# Resume stamps and the per-document run
# ---------------------------------------------------------------------------

def _stamp_current(spec_sha: str, anchors_sha: str = "",
                   spec: Optional[Spec] = None) -> dict:
    """What a harvest was produced by, key by key.

    The model, the anchors and every prompt are written so a reader can
    place a harvest, and never compared: the owner decided on 2026-09-10
    that a stamp rests on the KG/ontology parameters alone.

    Those are one key per parameter and per coordinate. `spec` is
    the sha of the whole file, which answers "did anything change" and
    nothing else: one new energy carrier moves it, and all 1.082 documents
    become stale together -- about 93 GPU hours to re-read a corpus over a
    word. The ontology this spec is written against keeps moving, so that
    bill would come again and again. With a key per parameter and per axis,
    a run can see that only `axis/energy_consumption/carrier` changed and
    open only that coordinate. `stale` reads it that way and does not compare
    `spec` at all, which is why the fine keys have to be written even for a
    run that never asks for them: a stamp that does not carry the detail
    cannot be asked for it afterwards.

    Without a spec the stamp keeps its old shape. That is for callers that
    have no spec to hand, and it is a coarser stamp, not a wrong one -- and
    with nothing finer to go on `spec` decides again.
    """
    return {"spec": spec_sha, "model": LLM_MODEL, "anchors": anchors_sha,
            **prompts.versions(PROMPT_IDS),
            **(fingerprints(spec) if spec is not None else {})}


# Recorded, and compared only while there is nothing finer to go on: the sha
# of the whole spec file. It moves on a comment, an indent, a reordering, a
# graph annotation -- none of which any question is asked through, and all of
# which the ontology work produces by the dozen. Compared beside the finer
# keys it outvotes them: one added byte and all 991 stamped documents report
# stale together, which is the bill the finer keys exist to avoid. With no
# finer keys in the stamp it is all there is, and then it decides again.
COARSE = ("spec",)

# What a run really asks a document through, one key per question and per
# answer space: the ontology keys, and the only ones `stale` compares. Their
# presence is what licenses ignoring `spec`: with nothing finer in the stamp
# there is nothing else to go on.
QUESTION_KEYS = ("parameter/", "value/", "axis/", "slot/")

# Where a top-up writes its trace: beside the harvest's `trace/`, never into
# it. trace._handle opens "w", so the harvest's own file would be truncated,
# and scripts/harvest_compare.py reads `trace/` alone, so a top-up's requests
# are not counted into the harvest's cost.
TOPUP_TRACE_DIR = "trace-topup"


def recorded_questions(questions: Optional[dict]) -> dict:
    """{key: [sentence]} -> the stamp keys that record what was really asked.

    A question the model writes for THIS document exists nowhere else once the
    run is over: it is not in the spec, not in a prompt and not in the JSONL.
    Without it a harvest cannot be placed at all -- "which sentence found these
    passages" has no answer, and `--force-stale` loses its meaning, because
    nothing says what would be redone differently.

    So it is written down, and never compared: `stale` compares the
    ontology keys alone.
    """
    out: dict = {}
    for key, texts in (questions or {}).items():
        if isinstance(texts, str):
            texts = [texts]
        wording = [t.strip() for t in texts or ()
                   if isinstance(t, str) and t.strip()]
        if wording:
            out[f"question_text/{key}"] = wording
    return out


def stale(stamp_path: Path, current: dict) -> list:
    """Which ontology keys differ from now; everything when unstamped.

    Only the ontology keys are compared (`QUESTION_KEYS`: one per parameter,
    value list, axis and slot), and the whole-file sha `spec` only for a stamp
    that has none of them. The model, the anchors, every prompt and every
    recorded sentence are in the stamp for a reader and decide nothing: the
    owner's rule of 2026-09-10 is that a stamp rests on the KG/ontology
    parameters alone, so a reworded prompt or another model leaves a
    harvested corpus current.

    A key the stored stamp does not have counts as changed, which is what
    makes a stamp from before the per-parameter keys read as stale: it cannot
    vouch for a coordinate it never recorded, and pretending otherwise is how
    a document keeps a harvest nobody can place.

    Both directions: every key is written from what the spec still HAS, so a
    question that is gone is in no current key at all. Dropping an axis moved
    nothing and the document read as current under a spec that no longer asks
    that coordinate -- the whole-file sha used to catch it, and stopped once
    it was no longer compared.
    """
    if not stamp_path.is_file():
        return sorted(current)
    try:
        stored = json.loads(stamp_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return sorted(current)
    detailed = any(k.startswith(QUESTION_KEYS) for k in current)

    def compared(key: str) -> bool:
        return key.startswith(QUESTION_KEYS) or (not detailed and key in COARSE)

    changed = {k for k in current
               if compared(k) and stored.get(k) != current[k]}
    if detailed:
        changed |= {k for k in stored if k not in current and compared(k)}
    return sorted(changed)


def documents_to_harvest(documents, out_dir: Path, spec_sha: str, *,
                         force: bool = False, force_stale: bool = False,
                         anchors_sha: str = "", spec: Optional[Spec] = None,
                         top_up: bool = False) -> list:
    """Which of these documents this run has work for.

    A top-up is the exception and it is not a small one: this filter drops
    exactly the documents whose stamp moved, which is the entire population a
    top-up exists to re-read. Filtered, the flag is a no-op that logs
    "nothing to harvest" unless --force-stale is also given.
    """
    if top_up:
        return list(documents)
    return [(did, fn) for did, fn in documents
            if not already_done(Path(fn).stem, out_dir, spec_sha,
                                force=force, force_stale=force_stale,
                                anchors_sha=anchors_sha, spec=spec)]


def run_document(document_id: int, name: str, out_dir: Path, spec: Spec,
                 spec_sha: str, templates: list, deps: dict, *,
                 force: bool = False, force_stale: bool = False,
                 anchors_sha: str = "") -> bool:
    if already_done(name, out_dir, spec_sha, force=force,
                    force_stale=force_stale, anchors_sha=anchors_sha,
                    spec=spec):
        return True
    report = harvest_document(document_id, spec, templates,
                              retrieve=deps["retrieve"],
                              harvest=deps["harvest"],
                              locate=deps.get("locate"),
                              structure=deps.get("structure"),
                              more_sources=deps.get("more_sources"),
                              extra_probes=deps.get("anchors"),
                              prose_top=PROSE_TOP)
    finish_document(report, name, out_dir, spec_sha, anchors_sha,
                    spec=spec)
    return True


def already_done(name: str, out_dir: Path, spec_sha: str, *,
                 force: bool = False, force_stale: bool = False,
                 anchors_sha: str = "", spec: Optional[Spec] = None) -> bool:
    """True when this document needs no work: harvested under the current
    ontology keys — or stale with nobody asking for the redo."""
    if force or not (out_dir / f"{name}.jsonl").exists():
        return False
    stamp_path = out_dir / f"{name}.stamp.json"
    if not stamp_path.is_file():
        # No record at all, which is not the same as a record of something
        # older and must not be read as one. A file with no stamp is a file
        # nothing vouches for: it may predate the stamps, it may be half
        # written, it may have been rewritten by a rule the run never applied.
        # Treating that as "already done" is how deleting the stamps to force
        # a redo caused every document to be skipped instead.
        log.info("extraction: %s carries no stamp — harvested again", name)
        return False
    changed = stale(stamp_path, _stamp_current(spec_sha, anchors_sha, spec))
    if not changed:
        log.info("extraction: %s is current — skipped", name)
        return True
    if not force_stale:
        log.warning("extraction: %s was harvested with older %s; re-run "
                    "with --force-stale to redo it", name, ", ".join(changed))
        return True
    return False


# A document this many of whose sources died on an unreachable server was not
# harvested, whatever its file says. Half is the line: below it a plan really
# can be mostly holes, above it the server was gone.
UNREACHABLE_LIMIT = 0.5


def finish_document(report, name: str, out_dir: Path, spec_sha: str,
                    anchors_sha: str = "", answered: Optional[int] = None,
                    spec: Optional[Spec] = None,
                    questions: Optional[dict] = None) -> None:
    """Write one document's JSONL and stamp it with what produced it.

    The stamp is what a resume trusts, so it is withheld when the harvest did
    not happen. A dead server answers every request the same way and every
    document comes back all sentinels; stamping those would write up to a
    thousand empty documents down as finished, and the run that resumed would
    skip every one of them without a word.

    `answered` is how many of the document's batches came back at all. None
    means the caller does not track it and the count is not checked. Zero
    against a plan that had sources is the second way a harvest fails to
    happen, and the sentinel arithmetic below cannot see it: with no reply
    there is no tuple and no refusal either, so it reads 0 > n/2, says no, and
    stamps an empty file. That is how a dead server turned 872 planned
    documents into 0-byte results a resume would have skipped.
    """
    failed = [r for r in report.refusals
              if r.get("claim", {}).get("_harvest_failed")]
    if failed:
        log.warning("extraction: %s: %d source(s) never answered", name, len(failed))
    # One line per parameter, whatever it came to. Every other state in the
    # file belongs to a row, so a parameter that produced no row produced no
    # record at all: on Kassel, planning_organisation came back with 0 tuples
    # and nothing anywhere saying whether the plan is silent or the run never
    # asked.
    states = (parameter_states(spec, report.tuples, report.refusals,
                               harvested=report.owners_harvested,
                               answered=answered,
                               sources_of=getattr(report, "sources_of", None))
              if spec is not None else None)
    if spec is not None:
        check_against_schema(report, name, spec, states)
    write_report(report, out_dir / f"{name}.jsonl", states)
    unreachable = sum(1 for r in failed
                      if r.get("claim", {}).get("_why") == "unreachable")
    sources = max(report.owners_harvested, len(failed))
    if sources and unreachable > sources * UNREACHABLE_LIMIT:
        log.error("extraction: %s: %d of %d source(s) never reached the "
                  "server — not stamped, so a resume harvests it again",
                  name, unreachable, sources)
        return
    if sources and answered == 0:
        log.error("extraction: %s: %d source(s) planned and not one reply — "
                  "not stamped, so a resume harvests it again", name, sources)
        return
    (out_dir / f"{name}.stamp.json").write_text(
        json.dumps({**_stamp_current(spec_sha, anchors_sha, spec),
                    **recorded_questions(questions)},
                   ensure_ascii=False, indent=2),
        encoding="utf-8")


def _harvest_validators(spec):
    """One validator per branch of the harvest schema, or None.

    Per branch and not one for the whole file, because the schema is a oneOf
    over the parameters: a row that breaks in one key fails every branch, and
    the only message the outer validator can give is "matches none of them"
    followed by the row itself. Which branch a row belongs to is written on
    the row (its kind, and for a tuple its parameter), so it is looked up
    rather than searched for.

    Built once per process and cached: compiling the schema per document
    would cost more than the check it pays for.
    """
    # Keyed by the profile the spec describes, not cached once for the
    # process: two profiles in one process would otherwise have the second
    # checked against the first one's schema, and every row of it would be
    # reported invalid.
    key = tuple(p.uri for p in spec.parameters)
    cache = getattr(_harvest_validators, "_cached", None)
    if cache is None:
        cache = _harvest_validators._cached = {}
    if key not in cache:
        try:
            import jsonschema

            from .schema import build
            harvest = build(spec)["harvest"]
            defs = harvest["$defs"]
            base = {"$schema": harvest["$schema"], "$defs": defs}
            cache[key] = {
                branch_key: jsonschema.Draft202012Validator(
                    {**base, **defs[branch]})
                for branch_key, branch in
                [(("refusal", None), "refusal"),
                 (("parameter_state", None), "parameter_state"),
                 (("summary", None), "summary")]
                + [(("tuple", p.uri), f"tuple_{p.uri}")
                   for p in spec.parameters]}
        except Exception as exc:              # pragma: no cover - defensive
            log.warning("extraction: no schema check (%s)", exc)
            cache[key] = False
    return cache[key] or None


def check_against_schema(report, name: str, spec,
                         states: Optional[list] = None) -> int:
    """Count the rows this document would write that the schema refuses.

    Counted and traced, never blocking. The harvest is the durable artifact
    and a row the schema does not recognise is still evidence; refusing to
    write it would turn a documentation defect into a data loss. What it must
    not do is pass unnoticed, because the schema is what everyone downstream
    reads instead of this file.
    """
    validators = _harvest_validators(spec)
    if validators is None:
        return 0
    invalid = 0
    # The summary is written by write_report, not carried on the report, so
    # it is built here the same way and checked with everything else. A line
    # the schema refuses is a line downstream cannot read, whoever wrote it.
    summary = document_summary(report.document_id, report.tuples,
                               report.refusals)
    for kind, rows in (("tuple", report.tuples), ("refusal", report.refusals),
                       ("parameter_state",
                        [{"document_id": report.document_id, **r}
                         for r in states or []]),
                       ("summary", [summary])):
        for row in rows:
            key = (kind, row.get("parameter") if kind == "tuple" else None)
            validator = validators.get(key)
            if validator is None:
                # No branch claims it. That is a finding of its own: the row
                # names a parameter this spec does not have.
                invalid += 1
                trace.event("invalid", report.document_id, kind=kind,
                            where="parameter", why="oneOf",
                            detail=f"no branch for {key[1]!r}")
                continue
            errors = list(validator.iter_errors({"kind": kind, **row}))
            if not errors:
                continue
            invalid += 1
            first = min(errors, key=lambda e: (e.validator == "oneOf",
                                               -len(list(e.absolute_path))))
            trace.event("invalid", report.document_id, kind=kind,
                        where="/".join(str(p) for p in first.absolute_path),
                        why=str(first.validator),
                        detail=first.message[:200])
    if invalid:
        log.warning("extraction: %s: %d of %d row(s) do not match the "
                    "published schema", name, invalid,
                    len(report.tuples) + len(report.refusals) + 1)
    return invalid


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
               + PRIOR_MAX * PRIOR_TOKENS                   # what we have already
               + payload                                    # payload + envelope
               + int(prompt.meta.get("max_tokens", 4096)))


# How many tuples one source yields when it yields at all, at the 90th
# percentile — measured over the finished pilots' own output, grouped by
# (owner, parameter). Sizing on the median would truncate half the fat
# tables; sizing on the maximum would make the batch pointless. The tail past
# p90 is what the split is for: the batch is asked again in halves.
TUPLES_PER_SOURCE_P90 = 12
# Characters per output token, from the truncated replies themselves: they
# stopped at exactly max_tokens, so content length over max_tokens is the
# measurement. It came out between 2.62 and 2.82; the low end is conservative.
CHARS_PER_TOKEN = 2.62


def fit_batch_sources(prompt, spec, wanted: int = BATCH_SOURCES) -> int:
    """The largest batch this profile can be ANSWERED for, at most *wanted*.

    The two numbers that killed a pilot lived in different files and nobody
    ever compared them: how many sources one request reads is set here, and
    how much the model may write about them is set in the prompt's
    frontmatter. Six sources of kwp tuples fit in 8192 tokens; six sources of
    ar6 tuples, whose quotes are whole sentences, need 11000 and would be cut
    off — every time, deterministically, on five GPUs.

    So the batch follows the answer budget rather than a hand-picked
    constant, and what one tuple costs comes from the profile's own example,
    which is the very contract the prompt shows the model.
    """
    widest = max((len(json.dumps(t, ensure_ascii=False))
                  for parameter in spec.parameters
                  for t in (parameter.example or {}).get("tuples", ())),
                 default=0)
    if not widest:
        return wanted
    per_source = TUPLES_PER_SOURCE_P90 * widest / CHARS_PER_TOKEN
    allowed = int(int(prompt.meta.get("max_tokens", 4096)) // per_source)
    return max(1, min(wanted, allowed))


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


def pair_batches(items: list, pairs: list, pair_plans: list, frame_axes: list,
                 anchors: list, *, default: Optional[dict] = None,
                 max_sources: int = BATCH_SOURCES,
                 max_chars: int = BATCH_CHARS) -> tuple:
    """(batches, rest, added, assumed) for one document with a frame.

    A pair is read over every passage that prints it, and over no other. Its
    own search and the document's search keep `PLAN_TOP` passages each, cut
    from two rankings. A table the document's search found that prints 2045,
    below the cut of the 2045 search, was in no batch at all: not under the
    pair, whose search had not kept it, and not in the rest, which is what
    prints none of the pairs. So every passage any search of the document
    planned goes to every pair it prints. `added` counts the ones a pair's own
    search had not kept; a pair whose own search failed (`None`) is read over
    those alone.

    A passage a pair's own search kept that does not print the pair is not
    read under it: every value from it is refused as another pair's, and on
    corpus_m5 that was 26,990 refusals, 95 percent of all. It goes where the
    passages of no pair go.

    `rest` is what any search of the document found that prints none of the
    pairs.
    With a `default` (the profile's FRAME_DEFAULT) that exactly one pair of
    the document matches, a passage of the rest that names no pair at all,
    no scenario of any pair and no year, is read under that pair instead: the
    owner's rule for an inventory table that states neither, after Kassel's
    Tabelle 3 left 35 values without a year. `assumed` counts those passages.
    """
    def key(item):
        return (item.source.owner_kind, item.source.owner_id,
                item.source.text or "")

    known: dict = {}
    for item in list(items) + [item for planned in pair_plans
                               for item in planned or ()]:
        known.setdefault(key(item), item)
    batches: list = []
    added = 0
    for pair_index, pair in enumerate(pairs):
        planned = [item for item in (pair_plans[pair_index]
                                     if pair_index < len(pair_plans)
                                     else None) or ()
                   if names_pair(item.source, pair, frame_axes)]
        have = {key(item) for item in planned}
        extra = [item for k, item in known.items()
                 if k not in have and names_pair(item.source, pair, frame_axes)]
        added += len(extra)
        for batch in group_items(planned + extra, max_sources=max_sources,
                                 max_chars=max_chars):
            batch.frame = pair
            batch.frame_index = pair_index
            batch.anchors = tuple(anchors[pair_index]
                                  if pair_index < len(anchors) else ())
            batches.append(batch)
    rest = [item for item in known.values()
            if not any(names_pair(item.source, pair, frame_axes)
                       for pair in pairs)]
    matching = [index for index, pair in enumerate(pairs)
                if default and all(pair.get(k) == v for k, v in default.items())]
    assumed = 0
    if len(matching) == 1:
        index = matching[0]
        bare = [item for item in rest
                if names_no_pair_at_all(item.source, pairs, frame_axes)]
        if bare:
            taken = {id(item) for item in bare}
            rest = [item for item in rest if id(item) not in taken]
            for batch in group_items(bare, max_sources=max_sources,
                                     max_chars=max_chars):
                batch.frame_default = pairs[index]
                batch.frame_default_index = index
                batches.append(batch)
            assumed = len(bare)
    return batches, rest, added, assumed


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
    parser.add_argument("--recheck", action="store_true",
                        help="No harvest and no model: check every "
                             "coordinate of the JSONL already in OUT again, "
                             "drop every one whose quote does not carry its "
                             "answer, and clear the stamps so the next run "
                             "redoes them")
    parser.add_argument("--keep-stamps", action="store_true",
                        help="--recheck only: leave the resume stamps in place")
    parser.add_argument("--top-up", action="store_true",
                        help="re-read only the coordinates the resume stamps "
                             "say moved, over the harvest in --out, instead "
                             "of harvesting those documents again. Needs the "
                             "model and the index; a document whose stamp "
                             "moved in anything but a coordinate is skipped "
                             "whole")
    parser.add_argument("--top-up-key", action="append", metavar="KEY",
                        help="--top-up only: sweep this stamp key and no "
                             "other, e.g. axis/energy_consumption/sector. "
                             "Repeatable")
    parser.add_argument("--review", action="store_true",
                        help="read every value nobody can stand behind a "
                             "second time, over its own passage and the "
                             "section that passage stands in, and record "
                             "what the second reading came to. One request "
                             "per C value: `python scripts/curation_list.py "
                             "OUT --level C` prints that count for free")
    parser.add_argument("--review-limit", type=int, default=0, metavar="N",
                        help="--review only: stop after N values (0 = all)")
    parser.add_argument("--remap", action="store_true",
                        help="map every coordinate's recorded wording onto "
                             "the vocabulary as the spec reads today, over "
                             "the harvest in --out. No model. Carries a "
                             "document's stamp forward for every answer "
                             "space it could fully re-map, so a grown option "
                             "list costs minutes instead of a corpus run")
    add_profile_argument(parser)
    args = parser.parse_args(argv)
    logging.basicConfig(level=args.log_level,
                        format="%(asctime)s [%(levelname)s] %(name)s %(message)s",
                        datefmt="%H:%M:%S")

    profile = resolve_profile(args)
    if args.recheck:
        raw_spec_path = profile.component("extraction", "SPEC_PATH")
        if raw_spec_path is None:
            parser.error(f"profile {profile.name!r} does not configure the "
                         f"extraction stage")
        from .recheck import run as recheck_run
        stats = recheck_run(args.out, load_spec(Path(raw_spec_path)),
                            drop_stamps=not args.keep_stamps)
        total = stats["coordinates"] or 1
        log.info("recheck: %d of %d coordinates survive the rule (%.1f%%), "
                 "over %d tuple(s)", stats["read"], stats["coordinates"],
                 100.0 * stats["read"] / total, stats["tuples"])
        return 0
    if args.remap:
        raw_spec_path = profile.component("extraction", "SPEC_PATH")
        if raw_spec_path is None:
            parser.error(f"profile {profile.name!r} does not configure the "
                         f"extraction stage")
        spec_path = Path(raw_spec_path)
        spec = load_spec(spec_path)
        from .remap import run as remap_run
        stats = remap_run(args.out, spec,
                          _stamp_current(hashlib.sha256(spec_path.read_bytes()).hexdigest(),
                                        "", spec))
        settled = stats["unchanged"] + stats["remapped"] \
            + stats["remapped (required)"] + stats["newly mapped"]
        log.info("remap: %d of %d coordinate(s) map onto the current lists, "
                 "%d document(s) carried their stamp forward", settled,
                 settled + stats["no wording"] + stats["not listed"],
                 stats["stamps carried forward"])
        return 0
    if args.serialize is not None:
        factory = profile.component("kg", "make_serializer")
        if factory is None:
            parser.error(f"profile {profile.name!r} provides no "
                         f"kg.make_serializer (profiles/{profile.name}/kg.py)")
        from .serialize import run as serialize_run
        try:
            counts = serialize_run(args.out, args.serialize, factory(args.db))
        except ValueError as exc:
            log.error("serialize: %s", exc)
            return 1
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
    if args.review:
        # The two guards `main` applies below, applied here as well: this
        # branch returns before either of them is reached, and a review that
        # reads every table without its picture is a review of a
        # transcription.
        if ATTACH_IMAGES and not Path(args.image_root).is_dir():
            parser.error(f"image root {args.image_root} is not a directory — "
                         f"every table and figure crop would be missing. Pass "
                         f"--image-root, or EXTRACT_ATTACH_IMAGES=0 to review "
                         f"from the transcriptions alone")
        review_prompt = prompts.load(REVIEW_PROMPT_ID)
        assert_serving(LLM_BASE_URL, LLM_API_KEY, LLM_MODEL,
                       context_budget(review_prompt, spec),
                       what="extraction review", flag="--max-model-len")
        from .review import run as review_run
        wanted = None
        if args.document:
            # The harvest files are named after the documents, so a
            # restriction is resolved through the same listing the harvest
            # selects from and fails the same way on an id that is not on it.
            listing = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
            try:
                chosen, missing = select_documents(_documents(listing),
                                                   args.document)
            finally:
                listing.close()
            if missing:
                log.error("%d named document(s) not found or not current: %s",
                          len(missing), ", ".join(str(m) for m in missing))
                return 1
            wanted = [Path(fn).stem for _did, fn in chosen]
        stats = review_run(args.out, spec,
                           ask=make_review_asker(args.image_root),
                           sources_for=make_review_sources(args.db),
                           documents=wanted, limit=args.review_limit,
                           prompt_sha=review_prompt.sha256, model=LLM_MODEL)
        log.info("review: %d value(s) read again — %d agreed, %d disagreed, "
                 "%d could not be backed, over %d document(s)",
                 stats["reviewed"], stats["agree"], stats["disagree"],
                 stats["unbacked"], stats["documents"])
        return 0
    spec_sha = hashlib.sha256(spec_path.read_bytes()).hexdigest()
    # Which coordinates decide whether a value belongs in the graph at all.
    # The profile's business: "scenario == target" is what the kwp target
    # slice holds and says nothing about any other corpus.
    slice_gate = profile.component("extraction", "SLICE") or {}
    if slice_gate:
        log.info("extraction: slice gate on %s — a row that falls out here "
                 "is not asked for its other coordinates",
                 ", ".join(sorted(slice_gate)))
    anchors_sha = anchors_key()
    templates = [line for line in
                 prompts.load(QUERIES_PROMPT_ID).text.splitlines()
                 if line.strip() and not line.lstrip().startswith("#")]
    # Optional: (connection, document_id) -> {axis name: {uri: [labels]}} for
    # the axes the spec declares dynamic.
    document_axes = profile.component("extraction", "document_axes")
    # Optional: (connection, document_id) -> {"name": ...}. What the document
    # itself contributes to its own search anchor. The municipality is in the
    # profile's catalog join and in no core query, so the core asks for it
    # rather than growing a second idea of what a document is.
    document_context = profile.component("extraction", "document_context")
    # Which coordinates belong to the DOCUMENT rather than to the row. The
    # profile names them; the core never names a coordinate. Empty means the
    # old shape: every coordinate is asked per row.
    frame_axes = fields.frame_slots(spec, profile.component("extraction",
                                                            "FRAME") or ())
    frame_default = profile.component("extraction", "FRAME_DEFAULT")
    if frame_axes:
        log.info("extraction: the frame is %s — found once per document, then "
                 "one value request per pair",
                 " x ".join(slot.name for slot in frame_axes))
    # Which sentence each document was really asked. Written into that
    # document's stamp for a reader; `stale` compares the ontology keys alone.
    asked: dict = {}

    required = context_budget(prompts.load(HARVEST_PROMPT_ID), spec)
    if args.print_context_budget:
        print(required)
        return 0
    assert_serving(LLM_BASE_URL, LLM_API_KEY, LLM_MODEL, required,
                   what="extraction", flag="--max-model-len")

    from concurrent.futures import ThreadPoolExecutor, as_completed

    from docpipe.inference import faiss_store, query_cache
    # Not `index`. `plan` below closes over this name and reads it when it
    # runs, and the pair loop further down bound an `index` of its own: pairs
    # 8, 9 and 10 of Kassel were planned against an int and the job failed.
    faiss_index, id_to_pos = faiss_store.load_global_index(args.index)
    args.out.mkdir(parents=True, exist_ok=True)
    if ATTACH_IMAGES and not Path(args.image_root).is_dir():
        # Loud here, at second one. The alternative is what happened last
        # time: a warning per crop, buried in half a million log lines, while
        # the harvest read every table without its picture.
        parser.error(f"image root {args.image_root} is not a directory — "
                     f"every table and figure crop would be missing. Pass "
                     f"--image-root, or EXTRACT_ATTACH_IMAGES=0 to harvest "
                     f"from the transcriptions alone")
    # The batch follows what the model is allowed to say about it, not the
    # other way round. Said out loud, because a run that quietly reads three
    # sources where the constant says six is a run whose numbers mean
    # something else than the last one's.
    global BATCH_SOURCES
    fitted = fit_batch_sources(prompts.load(HARVEST_PROMPT_ID), spec)
    if fitted != BATCH_SOURCES:
        log.info("extraction: %d source(s) per request, not %d — that is what "
                 "max_tokens allows this profile to answer for",
                 fitted, BATCH_SOURCES)
        BATCH_SOURCES = fitted

    if FIELDWISE:
        budget = window_budget()
        log.info("extraction: one request per field, swept in windows of %d "
                 "(overlap %d) until read; %d batch thread(s), %d field "
                 "thread(s), at most %d own + %d retrieval + %d rest = %d "
                 "window(s) per coordinate",
                 FIELD_WINDOW, FIELD_OVERLAP, LLM_PARALLEL, FIELD_PARALLEL,
                 budget["own"], budget["retrieval"], budget["rest"],
                 sum(budget.values()))
    else:
        log.info("extraction: one request per tuple (EXTRACT_FIELDWISE=0)")
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

    documents = documents_to_harvest(
        documents, args.out, spec_sha, force=args.force,
        force_stale=args.force_stale, anchors_sha=anchors_sha, spec=spec,
        top_up=args.top_up)
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

    # One call per question the field sweep asks, before anything is
    # planned: the anchors depend on the question, not on the document, and a
    # probe string that is the same for the whole corpus is what makes the
    # query-embedding cache pay.
    anchors = ({} if os.environ.get("EXTRACT_ANCHORS", "1") == "0"
               else make_anchors(spec, store=args.out / "anchors.json",
                                 key=anchors_sha))

    cache_path = args.out / "query_cache.db"
    primer = query_cache.connect(cache_path)
    prime_probe_cache(primer, spec, templates, anchors)
    primer.close()
    more_sources = make_more_sources(args.db, faiss_index, id_to_pos,
                                     cache_path)

    if args.top_up:
        from . import topup
        trace.open_trace(args.out / TOPUP_TRACE_DIR,
                         {did: Path(fn).stem for did, fn in documents}.get)
        frame_names = [slot.name for slot in frame_axes]
        listing = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
        listing.row_factory = sqlite3.Row

        def document_spec(document_id):
            """This document's own spec, or None when its list cannot be
            closed: swept against an empty list a dynamic axis degrades to a
            wording, which is a demotion nothing would report."""
            if document_axes is None:
                return spec
            try:
                filled = document_axes(listing, document_id)
            except Exception as exc:          # pragma: no cover - defensive
                log.warning("   document %s: dynamic axes unreadable: %s",
                            document_id, exc)
                return None
            return fill_dynamic_axes(spec, filled) if filled else None

        try:
            log.info("top-up: this may rewrite %s for every question whose "
                     "wording moved — the anchors key hashes the prompt and "
                     "the model, not the questions",
                     args.out / "anchors.json")
            stats = topup.run(
                args.out, spec,
                _stamp_current(spec_sha, anchors_sha, spec),
                {"sweep": make_sweeper(
                    make_field_asker(args.image_root),
                    more_sources=more_sources,
                    rest_of_document=make_rest_of_document(args.db),
                    parents=make_parents(args.db), anchors=anchors),
                 "owner_sources": make_owner_sources(args.db),
                 "document_spec": document_spec,
                 "frame_names": frame_names,
                 "dynamic_ok": document_axes is not None,
                 "slice_gate": slice_gate,
                 "locate": locate},
                only=args.top_up_key)
        finally:
            listing.close()
        log.info("top-up: %d row(s) re-read over %d document(s), %d stamp(s) "
                 "carried forward, %d blocked",
                 stats["rows"], stats["documents"],
                 stats["stamps carried forward"], stats["blocked"])
        return 0

    # After more_sources, because the field sweep uses it: a coordinate that
    # is not in the value's own passage is looked for further out in the same
    # document. OpenAI client is thread-safe.
    harvest = (make_fieldwise_harvester(args.image_root, more_sources,
                                        make_rest_of_document(args.db),
                                        spec=spec, anchors=anchors,
                                        slice_gate=slice_gate,
                                        parents=make_parents(args.db),
                                        frame_axes=frame_axes)
               if FIELDWISE else make_harvester(args.image_root, spec=spec))
    ask_frame = make_frame_asker(args.image_root) if frame_axes else None

    # The sentences each pair was searched with, by (document, pair index),
    # so the request that reads the pair's passages can say what it asks.
    anchor_texts: dict = {}

    def plan(document_id: int, filename: str, frame: Optional[dict] = None,
             frame_index: int = 0) -> tuple:
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
            retrieve = make_retrieve(conn, faiss_index, id_to_pos,
                                     cache_conn, fetch, limit=PLAN_TOP)
            # The anchor is written for THIS document, so the document has to
            # say something first. One cheap probe out of the spec's own
            # templates, and what comes back carries its caption -- the words
            # this plan uses for the thing, which is what the anchor is for.
            context = dict(document_context(conn, document_id)
                           if document_context is not None else {})
            seed = [q for parameter in doc_spec.parameters
                    for q in list(expand_queries(templates, parameter))[:1]]
            first = retrieve(seed, document_id, set()) if seed else []
            if first:
                context.setdefault(
                    "caption", (first[0].provenance or {}).get("title") or "")
            probes = document_anchor(doc_spec, context, frame=frame)
            name = Path(filename).stem
            for uri, texts in sorted(probes.items()):
                for text in texts:
                    trace.event("anchor", document_id, parameter=uri,
                                text=text,
                                frame=frame_index if frame else None)
            if frame is None:
                asked[name] = dict(probes)
            else:
                # Recorded next to the document's own sentences, under the
                # pair they were written for.
                asked.setdefault(name, {}).update(
                    {f"{uri}#{frame_index}": list(texts)
                     for uri, texts in probes.items()})
                anchor_texts[(name, frame_index)] = [
                    text for texts in probes.values() for text in texts]
            items, report = plan_document(
                document_id, doc_spec, templates, extra_probes=probes,
                retrieve=retrieve,
                structure=make_structure(conn, fetch), top=PLAN_TOP)
            for item in items:
                trace.event("plan", document_id, rank=item.rank,
                            origin=item.origin, kind=item.source.owner_kind,
                            owner=item.source.owner_id,
                            chars=len(item.source.text or ""),
                            image=bool(item.source.image_path),
                            frame=frame_index if frame else None)
            return name, split_long_sources(items), report
        finally:
            conn.close()
            cache_conn.close()

    document_name = {did: Path(fn).stem for did, fn in documents}
    # Every event carries the document it belongs to and lands in that
    # document's own file, so a redone document overwrites its own trace.
    trace.open_trace(args.out / "trace", document_name.get)

    def accepted_rows(batch, reply) -> list:
        """What of one reply survives checking — the next batch's `prior`.

        The same verify_tuple the fold runs, against the same source text, so
        the two cannot drift apart. It skips only `locate`, which turns a
        quote into highlight rectangles and has never decided whether a
        claim is accepted.
        """
        from .verify import Refusal, verify_tuple

        routed, _orphans = route_claims(
            batch, [claim for claim in reply.get("tuples") or ()
                    if not refused_upstream(claim)])
        rows: list = []
        for item, claims in zip(batch.items, routed):
            for claim in claims:
                parameter = item.parameter or spec.by_uri.get(
                    str(claim.get("parameter") or ""))
                if parameter is None:
                    continue
                outcome = verify_tuple(dict(claim), parameter,
                                       item.source.text,
                                       owner_kind=item.source.owner_kind)
                if not isinstance(outcome, Refusal):
                    rows.append(dict(outcome.tuple))
        return rows

    def verify(entry: tuple) -> None:
        name, report, answered = entry
        replies = len(answered)
        for batch, reply in answered:
            fold_batch(batch, reply, report, locate=locate, spec=spec)
        for row in report.tuples:
            prov = row.get("provenance") or {}
            trace.event("coord", report.document_id,
                        parameter=row.get("parameter"), value=row.get("value"),
                        unit=row.get("unit"), tier=row.get("tier"),
                        kind=prov.get("owner_kind"), owner=prov.get("owner_id"),
                        states={k[:-6]: v for k, v in row.items()
                                if k.endswith("_state")})
        for refusal in report.refusals:
            trace.event("refusal", report.document_id,
                        parameter=refusal.get("parameter"),
                        reason=refusal.get("reason"),
                        owner=refusal.get("owner"))
        finish_document(report, name, args.out, spec_sha, anchors_sha,
                        answered=replies, spec=spec,
                        questions=asked.pop(name, None))
        trace.flush(report.document_id)

    started = time.time()
    failures = 0
    # Set by the dead-server cut inside harvest_batches. The group still gets
    # folded and written, because the documents that DID answer are real work,
    # and the ones that did not stay unstamped and are redone on a resume.
    server_gone = [False]

    def give_up() -> None:
        server_gone[0] = True

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
        # ---- Frame: which scenarios and which years, once per document --
        # Before any value. Every value request below asks for ONE of these
        # pairs, so the coordinate is never something the model has to decide
        # while it is reading a number.
        frames: dict = {}
        if ask_frame is not None and plans:
            with ThreadPoolExecutor(max_workers=LLM_PARALLEL) as pool:
                futures = {pool.submit(find_frame,
                                       [item.source for item in items],
                                       frame_axes, report.document_id,
                                       ask_frame, more_sources): name
                           for name, items, report in plans}
                for future in as_completed(futures):
                    name = futures[future]
                    try:
                        pairs, status, missed = future.result()
                    except Exception:
                        failures += 1
                        log.exception("extraction: frame %s failed", name)
                        continue
                    frames[name] = pairs
                    if missed:
                        # A year the deterministic scan found in the very
                        # passages the model was shown and it did not name.
                        # Reported, never added: "2045 MWh/a" is year-shaped
                        # and is not a year.
                        log.info("extract: %s: frame %d pair(s), %s, %d "
                                 "year-shaped number(s) not named: %s",
                                 name, len(pairs), status, len(missed),
                                 ", ".join(str(y) for y in missed[:8]))
                    else:
                        log.info("extract: %s: frame %d pair(s), %s",
                                 name, len(pairs), status)

        # ---- Plan again, once per pair: the pair is a search, not a label
        # "Nutzwaermebedarf 2040 im Zielszenario" is a sentence the plan can
        # print and the value request for 2040 is asked over what THAT
        # sentence finds. Reusing one document plan for every pair made the
        # pair a field in the request and left the search untouched, which is
        # how a plan with four target years ran with two.
        pair_items: dict = {}
        report_of = {name: report for name, _items, report in plans}
        jobs = [(name, pair_index, pair) for name, _items, _report in plans
                for pair_index, pair in enumerate(frames.get(name) or ())]
        if jobs:
            where = {Path(fn).stem: (did, fn) for did, fn in group}
            with ThreadPoolExecutor(max_workers=PLAN_PARALLEL) as pool:
                futures = {pool.submit(plan, *where[name], pair, pair_index):
                           (name, pair_index)
                           for name, pair_index, pair in jobs}
                for future in as_completed(futures):
                    name, pair_index = futures[future]
                    try:
                        _name, items, pair_report = future.result()
                    except Exception:
                        failures += 1
                        log.exception("extraction: planning %s for pair %d "
                                      "failed", name, pair_index)
                        continue
                    pair_items[(name, pair_index)] = items
                    # The pair's own anchors found passages of their own;
                    # they are that parameter's too.
                    for uri, keys in pair_report.sources_of.items():
                        report_of[name].sources_of.setdefault(
                            uri, set()).update(keys)

        # Every batch of every document goes into one pool. A batch belongs
        # to exactly one document, so the replies come back where they can be
        # folded; nothing about the scheduling depends on that.
        batches: list = []
        owner_of: dict = {}
        for name, items, report in plans:
            found = list(frames.get(name) or ())
            framed, rest, added, assumed = pair_batches(
                items, found,
                [pair_items.get((name, i)) for i in range(len(found))],
                frame_axes,
                [anchor_texts.get((name, i), ()) for i in range(len(found))],
                default=frame_default,
                max_sources=BATCH_SOURCES, max_chars=BATCH_CHARS)
            for batch in framed:
                batches.append(batch)
                owner_of[id(batch)] = name
            # The rest: what prints none of the pairs. A value the frame
            # search has no pair for is harvested here without one, and its
            # year is read per row or ends `unstated`, so a year the search
            # missed is a countable gap and not a silent loss.
            if found:
                log.info("extract: %s: %d pair(s), %d passage(s) print none "
                         "of them, %d read under a pair its own search had "
                         "not kept, %d name no pair at all and are read "
                         "under the default pair", name, len(found),
                         len(rest), added, assumed)
            for batch in group_items(rest, max_sources=BATCH_SOURCES,
                                     max_chars=BATCH_CHARS):
                batches.append(batch)
                owner_of[id(batch)] = name
        sources = sum(len(b.items) for b in batches)
        log.info("extraction: group %d/%d planned — %d batch(es) over %d "
                 "source(s) in %d document(s)", offset // group_size + 1,
                 (len(documents) - 1) // group_size + 1, len(batches), sources,
                 len(plans))

        # ---- Harvest: all of them, at once ---------------------------------
        answered = harvest_batches(batches, harvest,
                                   more_sources=more_sources,
                                   verify=accepted_rows, workers=LLM_PARALLEL,
                                   on_give_up=give_up)

        # ---- Verify and write, document by document ------------------------
        by_document: dict = {}
        for batch, reply in answered:
            # A follow-up batch is new since planning, and it belongs to the
            # document its own sweep does.
            name = owner_of.get(id(batch)) or document_name.get(batch.document_id)
            by_document.setdefault(name, []).append((batch, reply))
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
        if server_gone[0]:
            log.error("extraction: the model server stopped answering — the "
                      "run ends here after %d of %d document(s). What was "
                      "harvested is written and stamped, the rest is not, so "
                      "a resume picks up where this stopped.",
                      min(offset + group_size, len(documents)), len(documents))
            failures += 1
            break

    log_usage(context_budget(prompts.load(HARVEST_PROMPT_ID), spec))
    log.info("extraction: done in %.0f s, %d failure(s)",
             time.time() - started, failures)
    return 1 if failures else 0
