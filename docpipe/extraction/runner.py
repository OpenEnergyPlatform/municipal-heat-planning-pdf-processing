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

from . import fields
from . import trace
from .pipeline import (Source, WorkItem, batch_uri, build_sweeps,
                       cell_index as pipeline_cell_index, fold_batch,
                       follow_up, group_items, harvest_document, merge_field,
                       mark_unanswered, open_rows, plan_document, route_claims,
                       rows_from_reply, window_sources, write_report)
from .fields import EXHAUSTED
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
PROMPT_IDS = (HARVEST_PROMPT_ID, QUERIES_PROMPT_ID, ANCHORS_PROMPT_ID,
              ROWS_PROMPT_ID, FIELD_PROMPT_ID)

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


def make_rest_of_document(db_path: Path) -> Callable:
    """(document_id, exclude) -> every remaining section, in document order.

    The floor under the field sweep, and the reason "not stated" can mean it.
    Retrieval answers "which passages look like this question", and for a
    coordinate that is stated once in a caption twelve pages away the answer
    is often none of them — an embedding does not rank a table caption under
    "which reference year does this figure belong to".

    So when the probes stop bringing anything new, the sweep stops asking and
    starts reading: the document's own sections, in their own order, until the
    coordinate is found or the document is finished. Finite by construction,
    which is what lets a sweep end in an answer rather than in a budget.
    """
    local = threading.local()

    def connections():
        if getattr(local, "conn", None) is None:
            local.conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            local.conn.row_factory = sqlite3.Row
            local.fetch = make_content_fetcher()
        return local.conn, local.fetch

    def rest_of_document(document_id: int, exclude: set) -> list:
        conn, fetch = connections()
        try:
            ids = [int(r[0]) for r in conn.execute(
                "SELECT id FROM Sections WHERE document = ? "
                "ORDER BY COALESCE(section_number, id)", (document_id,))]
        except Exception as exc:
            log.warning("   sections of document %s unreadable: %s",
                        document_id, exc)
            return []
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


def anchors_key(spec_sha: str, frozen_sha: str = "") -> str:
    """What an anchor set depends on: the spec, the anchor prompt, the model,
    and whatever the profile froze.

    The frozen part belongs in the key because a run reads its own
    anchors.json back. Without it, changing the profile's file would leave
    every output directory that already holds one searching with the old set,
    and no line anywhere would say so.
    """
    import hashlib
    versions = prompts.versions((ANCHORS_PROMPT_ID,))
    raw = (f"{spec_sha}|{versions.get(ANCHORS_PROMPT_ID)}|{LLM_MODEL}"
           f"|{ANCHOR_SCHEMA}|{frozen_sha}")
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


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
    """
    out: list = [(PARAMETER_ANCHOR, "Kennzahl", "", spec.parameter_question)]
    for parameter in spec.parameters:
        out.append((anchor_key(parameter.uri), parameter.label,
                    parameter.description, None))
        # asked_slots, not axis_slots: an anchor is a sentence to search
        # with, and a coordinate the spec derives is never searched for.
        for slot in fields.asked_slots(parameter):
            out.append((anchor_key(parameter.uri, slot.name),
                        f"{parameter.label} / {slot.name}",
                        parameter.description, slot.question))
    return [t for t in out if t[0] != PARAMETER_ANCHOR or t[3]]


def frozen_anchors(profile, spec: Spec) -> tuple:
    """(anchors, sha) the profile froze, or ({}, "") if it freezes none.

    An anchor the model writes is a guess at how the corpus phrases a value.
    These are not guesses: they are sections of an earlier run that really
    produced one, taken verbatim. Measured over 150 documents and 4,785 prose
    values, the kwp profile's frozen set puts 18.0% of them in the top 10
    sections where the written ones put 11.0%, against 7.6% for chance.

    Only the questions the file names are frozen. Everything else, the axis
    questions above all, is still written per run, so a profile can freeze what
    it has measured and leave the rest alone.
    """
    raw_path = profile.component("extraction", "ANCHORS_PATH") if profile else None
    if raw_path is None:
        return {}, ""
    path = Path(raw_path)
    raw = path.read_bytes()
    stored = json.loads(raw.decode("utf-8"))
    anchors = stored.get("anchors") if isinstance(stored, dict) else None
    if not isinstance(anchors, dict) or not anchors:
        raise LookupError(f"{path} names no anchors object")
    # The file outlives the spec it was measured against. A key that is no
    # question of this run would be dropped by every reader without a word,
    # and the run would search with a set nobody had checked.
    targets = {target[0] for target in anchor_targets(spec)}
    unknown = sorted(set(anchors) - targets)
    if unknown:
        raise LookupError(
            f"{path}: {', '.join(unknown)} is no question of this spec, which "
            f"asks {len(targets)}. Either the spec moved or the file did.")
    out, empty = {}, []
    for anchor_id, texts in anchors.items():
        usable = [t.strip() for t in texts
                  if isinstance(t, str) and len(t.strip()) > 20]
        if not usable:
            empty.append(anchor_id)
        out[anchor_id] = usable
    if empty:
        raise LookupError(f"{path}: {', '.join(sorted(empty))} freezes no "
                          f"usable anchor, which is a broken file and not a "
                          f"decision to leave the question to the model")
    import hashlib
    return out, hashlib.sha256(raw).hexdigest()[:16]


def load_anchors(path: Path, key: str) -> dict:
    """The anchors a previous run of this same configuration wrote."""
    try:
        stored = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(stored, dict) or stored.get("key") != key:
        return {}
    anchors = stored.get("anchors")
    return anchors if isinstance(anchors, dict) else {}


def save_anchors(path: Path, key: str, anchors: dict) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(
        json.dumps({"key": key, "model": LLM_MODEL, "anchors": anchors},
                   ensure_ascii=False, indent=2), encoding="utf-8")


def make_anchors(spec: Spec, client=None, *, store: Optional[Path] = None,
                 key: str = "", frozen: Optional[dict] = None) -> dict:
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
    # Frozen, because they decide which passages the whole corpus is harvested
    # from. Two calls in one job shared 0 of 18 strings, so a restart searched
    # a different document set with nothing in any of the 1082 output files
    # saying which set had found it. The file carries the reproducibility;
    # the temperature stays where it is.
    out: dict = dict(load_anchors(store, key)) if store is not None else {}
    # The profile's frozen anchors win over anything a previous run wrote for
    # the same question: those are the model's guess, these are measured.
    frozen = frozen or {}
    if frozen:
        out.update({k: list(v) for k, v in frozen.items()})
        log.info("extraction: %d anchor set(s) frozen in the profile: %s",
                 len(frozen), ", ".join(sorted(frozen)))
    todo = [t for t in anchor_targets(spec) if not out.get(t[0])]
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
                    return anchor_id, anchors
            except Exception as exc:
                log.warning("anchors %s attempt %d failed: %s",
                            anchor_id, attempt, exc)
            if attempt < MAX_RETRIES:
                time.sleep(min(2 * attempt, 6))
        log.warning("anchors %s: none generated", anchor_id)
        return anchor_id, []

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=min(8, len(todo) or 1)) as pool:
        for uri, anchors in pool.map(one, todo):
            out[uri] = anchors
    if store is not None:
        save_anchors(store, key, out)
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


def _close_open_brackets(text: str) -> str:
    """The closers a reply stopped short of, appended. Delimiters only.

    Measured on the first corpus group under the multi-field request: 1,546
    of roughly 8,000 five-field replies ended in `}]}}` where `}]}}}` was
    due. The model closes the last field and forgets the object around them,
    every time with finish=stop, and told to try again it repeated it 62% and
    then 98% of the time. No content is added: a bracket inside a string is
    text, a reply that stops inside a string is left as it is, and a closer
    that does not match what is open is somebody else's shape.
    """
    start = text.find("{")
    if start == -1:
        return text
    stack: list = []
    in_string = escaped = False
    for ch in text[start:]:
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]":
            if not stack or stack[-1] != ch:
                return text
            stack.pop()
    if in_string or not stack:
        return text
    return text + "".join(reversed(stack))


def _loads_object(raw_text: str, close: bool = False) -> Optional[dict]:
    """The JSON object in a reply, whatever it is wrapped in.

    The fallback used to be a greedy {.*} span, which is the one shape that
    cannot work: two objects in a row, or a sentence after the answer that
    happens to end in a brace, and the span covers both and is invalid by
    construction. Replies that looked perfectly well formed in the log were
    dropped that way.

    raw_decode instead — it reads ONE object from the first brace and stops,
    so trailing anything is simply not read. The same decoder rescue_reply
    uses, and for the same reason: quotes are lifted verbatim out of plans and
    braces in them do not balance.
    """
    text = _THINK_RE.sub("", raw_text or "").strip()
    text = _FENCE_CLOSE.sub("", _FENCE_OPEN.sub("", text)).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        if start == -1:
            return None
        try:
            data, _end = _DECODER.raw_decode(text, start)
        except json.JSONDecodeError:
            # *close* is the caller saying the model stopped on its own: a
            # reply cut off at the token ceiling may end after a complete
            # value that is not the whole value, and closed it would pass.
            closed = _close_open_brackets(text) if close else text
            if closed == text:
                return None
            try:
                data, _end = _DECODER.raw_decode(closed, start)
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

_TUPLES_KEY = re.compile(r'"tuples"\s*:\s*\[')
_DEFAULTS_KEY = re.compile(r'"defaults"\s*:\s*\{')
_DECODER = json.JSONDecoder()


def _strip_wrapping(raw_text: str) -> str:
    text = _THINK_RE.sub("", raw_text or "").strip()
    return _FENCE_CLOSE.sub("", _FENCE_OPEN.sub("", text)).strip()


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


def rescue_reply(raw_text: str) -> Optional[dict]:
    """Every complete tuple in an answer the generation cut short.

    A reply that hits the token ceiling stops mid-key, never on a boundary,
    so the JSON is unparsable — but the tuples written before the cut are
    whole, and each of them is quote-checked downstream like any other. The
    walk uses the standard decoder rather than counting braces, because the
    quotes are lifted verbatim from the plans and the plans contain BibTeX:
    15 of 1936 sections in the pilot set are `@misc{...}` dumps, and a
    quote-sized window of those is almost never brace-balanced. Only a real
    JSON scanner knows which brace is structure and which is evidence.
    """
    text = _strip_wrapping(raw_text)
    if not text:
        return None
    defaults = None
    head = _DEFAULTS_KEY.search(text)
    if head is not None:
        try:
            obj, _ = _DECODER.raw_decode(text, head.end() - 1)
            defaults = obj if isinstance(obj, dict) else None
        except ValueError:
            defaults = None
    match = _TUPLES_KEY.search(text)
    if match is None:
        return None
    tuples: list = []
    pos = match.end()
    while True:
        while pos < len(text) and text[pos] in " \t\r\n,":
            pos += 1
        if pos >= len(text) or text[pos] != "{":
            break
        try:
            obj, pos = _DECODER.raw_decode(text, pos)
        except ValueError:
            break                     # the half-written tail, dropped on purpose
        if isinstance(obj, dict):
            tuples.append(obj)
    if not tuples:
        return None
    return {"tuples": expand_defaults(defaults, tuples),
            "status": "truncated", "need_more": []}


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
        return f"{text[:keep]!r} …{len(text) - 2 * keep} weitere… {text[-keep:]!r}"

    return (f" [finish={getattr(reply, 'finish_reason', '?')}"
            f" | content {len(content)}ch: {show(content)}"
            f" | reasoning {len(reasoning)}ch: {show(reasoning)}]")


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


def _holes(batch, rescued: list) -> list:
    """Sentinels for the sources a cut-off reply never got to.

    Without this the rescue would trade a loud hole for a silent one. A dead
    batch writes one sentinel per source, which is exactly how the truncation
    was measurable in the finished pilots at all; a rescued batch that simply
    returned fewer tuples would leave the sources after the cut
    indistinguishable from "read, and there was nothing in them".

    Which sources those are is decided by POSITION, not by the label on the
    tuples. Under the defaults contract `source` is one of the keys the model
    is told to state once for the whole reply, so every rescued tuple carries
    the same label — reading it here would report five of six sources as
    never answered and could never report the one the block names. The model
    writes in source order, so the last label it actually reached is the
    frontier and everything past it is the loss.
    """
    labels = {batch.label(i): i for i in range(len(batch.items))}
    reached = [labels[claim["source"]] for claim in rescued
               if isinstance(claim, dict)
               and isinstance(claim.get("source"), str)
               and claim["source"] in labels]
    frontier = max(reached) if reached else 0
    return [{"_harvest_failed": True, "source": batch.label(i),
             "_cut_off": True}
            for i in range(frontier + 1, len(batch.items))]


def make_harvester(image_root: Optional[Path] = None,
                   prompt_id: str = HARVEST_PROMPT_ID,
                   spec=None) -> Callable:
    """The request loop, for either contract.

    The whole-tuple prompt and the field-wise value prompt differ in what they
    ask for and in nothing else: same sources, same crops, same sandbox, same
    rescue of a reply cut off at the token ceiling. So the prompt is the
    argument and the loop is shared.
    """
    prompt = prompts.load(prompt_id)
    client = _client()
    temperature = float(prompt.meta.get("temperature", 0.1))
    max_tokens = int(prompt.meta.get("max_tokens", 4096))

    # Deferred: docpipe.inference's package __init__ pulls in the whole answer
    # loop, which demands a profile at import time.
    from docpipe.inference import code_exec

    def harvest(batch, prior: Optional[list] = None) -> dict:
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
                if answer is None:
                    # A reasoning parser puts the chain in reasoning_content
                    # and leaves content empty when the generation stopped
                    # inside it. The answer, if there is one, is in there.
                    answer = _parse_reply(
                        getattr(reply.message, "reasoning_content", None))
                if (answer is None
                        and getattr(reply, "finish_reason", None) == "length"):
                    # The generation hit the token ceiling. Retrying is
                    # pointless — measured 31 times over one pilot, five
                    # attempts each, zero recoveries — and the tuples written
                    # before the cut are whole. Take them and stop.
                    answer = rescue_reply(reply.message.content)
                    if answer is not None:
                        answer["tuples"].extend(_holes(batch, answer["tuples"]))
                        log.warning(
                            "   harvest %s/%s+%d cut off at the token ceiling: "
                            "%d tuple(s) rescued", first.owner_kind,
                            first.owner_id, len(batch.items) - 1,
                            len(answer["tuples"]))
                    else:
                        log.warning(
                            "   harvest %s/%s+%d cut off at the token ceiling "
                            "before the first tuple%s", first.owner_kind,
                            first.owner_id, len(batch.items) - 1,
                            _unparsable(reply))
                        break
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
                log.warning("   harvest %s/%s+%d attempt %d: reply carried no "
                            "'tuples' list%s", first.owner_kind,
                            first.owner_id, len(batch.items) - 1, attempt,
                            _unparsable(reply))
                trace.event("error", batch.document_id, where=prompt_id,
                            kind="no_tuples", attempt=attempt,
                            owner=[first.owner_kind, first.owner_id],
                            finish=getattr(reply, "finish_reason", None))
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
                   corrections: Optional[list] = None) -> dict:
    """The request body of one field request, over the window shown.

    Several fields at once. One request per field was one round trip per
    coordinate: measured over 60 documents, 2,108 field requests each, which
    is what made a corpus run 82 hours. The evidence rule does not change —
    every field still answers for itself and quotes for itself — only the
    number of round trips does.

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
        if source.provenance.get("via") == "parent":
            entry["holds"] = "der Abschnitt, in dem die Tabelle steht"
        sources.append(entry)
    listed = []
    for row in rows:
        entry = {"id": row.label,
                 "value": row.claim.get("value"),
                 "quote": row.claim.get("quote")}
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

    No sandbox and no rescue of a truncated reply. A field answer is a choice
    and a quote, never arithmetic, and a reply cut off in the middle fills
    fewer rows than it could — which is a gap the harvest can see, because the
    coordinate is simply empty and counted as empty. That is the difference
    the whole change is about: what is missing is missing on the record.
    """
    prompt = prompts.load(FIELD_PROMPT_ID)
    client = _client()
    temperature = float(prompt.meta.get("temperature", 0.1))
    max_tokens = int(prompt.meta.get("max_tokens", 4096))

    def ask(shown: list, rows: list, slots,
            corrections: Optional[list] = None,
            document_id: Optional[int] = None,
            usage_out: Optional[dict] = None) -> Optional[dict]:
        slots = list(slots) if isinstance(slots, (list, tuple)) else [slots]
        name = "+".join(s.name for s in slots)
        payload = json.dumps(_field_payload(shown, rows, slots, corrections),
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
        conversation: list = [{"role": "user", "content": content}]
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = client.chat.completions.create(
                    model=LLM_MODEL, temperature=temperature,
                    max_tokens=max_tokens,
                    messages=[{"role": "system", "content": prompt.text},
                              *conversation],
                    extra_body={"chat_template_kwargs": {"enable_thinking": False}},
                )
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
                closed = False
                if answer is None and reply.finish_reason == "stop":
                    answer = _loads_object(reply.message.content, close=True)
                    closed = answer is not None
                if answer is None:
                    answer = _loads_object(
                        getattr(reply.message, "reasoning_content", None))
                if isinstance(answer, dict):
                    if closed:
                        # Counted, not hidden: the trace says how often the
                        # reply had to be closed for it.
                        trace.event("error", document_id, where="field",
                                    kind="closed", slot=name, attempt=attempt)
                    return answer
                log.warning("   field %s attempt %d: unreadable reply%s",
                            name, attempt, _unparsable(reply))
                trace.event("error", document_id, where="field",
                            kind="unparsable", slot=name, attempt=attempt,
                            finish=getattr(reply, "finish_reason", None))
                conversation.append({"role": "assistant",
                                     "content": reply.message.content or ""})
                conversation.append({"role": "user", "content": (
                    "Deine Antwort war kein lesbares JSON-Objekt. Gib NUR das "
                    "Objekt aus, in EINER Zeile, ohne Text davor oder danach "
                    "und ohne ein zweites Objekt. Anführungszeichen INNERHALB "
                    "eines Zitats müssen als \\\" escaped sein — ist das "
                    "mühsam, kürz das Zitat auf eine Stelle ohne "
                    "Anführungszeichen.")})
            except Exception as exc:
                log.warning("   field %s attempt %d failed: %s",
                            name, attempt, exc)
                status = getattr(exc, "status_code", None)
                trace.event("error", document_id, where="field",
                            kind="exception", slot=name, attempt=attempt,
                            status=status, detail=str(exc)[:300])
                if isinstance(status, int) and 400 <= status < 500 and status != 429:
                    break
            if attempt < MAX_RETRIES:
                time.sleep(min(2 * attempt, 6))
        return None

    return ask


def make_fieldwise_harvester(image_root: Optional[Path] = None,
                             more_sources: Optional[Callable] = None,
                             rest_of_document: Optional[Callable] = None,
                             spec=None, anchors: Optional[dict] = None,
                             slice_gate: Optional[dict] = None,
                             parents: Optional[Callable] = None
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
        # Which source each row came from. The evidence rule is about the
        # distance between a passage and the row it is offered for, and that
        # distance cannot be measured from the reply alone.
        owner_of = {row.label: batch.items[row.item_index].source
                    for row in rows
                    if 0 <= row.item_index < len(batch.items)}
        totals = {"filled": 0, "unquoted": 0, "unbacked": 0, "unstated": 0,
                  "raw_missing": 0, "retried": 0}
        seen = {(i.source.owner_kind, i.source.owner_id) for i in batch.items}
        state = {"asked": 0, "answer": None, "stage": "own"}

        def still_open(pool: list) -> list:
            """Rows with at least one of these fields still unread."""
            wanted = {row.label for slot in slots
                      for row in open_rows(pool, slot)}
            return [row for row in pool if row.label in wanted]

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
            for shown in windows:
                todo = still_open(rows)
                if not todo:
                    return True
                corrections = None
                for attempt in range(FIELD_ATTEMPTS):
                    if state["asked"] >= FIELD_MAX_WINDOWS:
                        return False
                    state["asked"] += 1
                    started = time.time()
                    usage: dict = {}
                    state["answer"] = ask(shown, todo, slots, corrections,
                                          batch.document_id, usage)
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
                              "unstated": 0, "raw_missing": 0, "failed": []}
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
                                                  state["asked"]),
                                          owner_of=owner_of)
                        for key in ("filled", "unquoted", "unbacked",
                                    "unstated", "raw_missing"):
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
                                "raw_missing"):
                        totals[key] += counts[key]
                    totals["retried"] += 1 if attempt else 0
                    # The window this coordinate was asked in, what was shown,
                    # and what came back. Every knob this stage has cuts
                    # through this distribution, and none of them could be set
                    # from a log line that only counted the failures.
                    trace.event("field", batch.document_id, slot=name,
                                anchor=anchor_id, window=state["asked"],
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
                                    "unstated", "raw_missing")})
                    for bad in counts["failed"]:
                        trace.event("drop", batch.document_id, slot=name,
                                    field=bad.get("field"),
                                    window=state["asked"], attempt=attempt,
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
            combed = run(window_sources(fresh, FIELD_WINDOW, FIELD_OVERLAP))

        if combed and still_open(rows) and rest_of_document is not None:
            # Retrieval has nothing left to offer and the coordinate is still
            # open. Read the rest of the plan rather than call it unstated on
            # the strength of what a ranking happened to surface.
            rest = rest_of_document(batch.document_id, set(seen)) or []
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
        totals["asked"] = state["asked"]
        totals["exhausted"] = stranded
        trace.event("sweep", batch.document_id, slot=name,
                    anchor=anchor_id, windows=state["asked"],
                    rows=len(rows), combed=combed, **totals)
        return totals

    def harvest(batch, prior: Optional[list] = None) -> dict:
        reply = find_rows(batch, prior)
        rows, orphans = rows_from_reply(batch, reply)
        if not rows:
            # Either nothing is in these passages or the value request died.
            # Both are already stated in the reply the row request returned,
            # sentinels included, so it is passed through untouched.
            return reply
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
        sweep = sweeps[(batch.document_id, batch_uri(batch))]
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

def _stamp_current(spec_sha: str, anchors_sha: str = "") -> dict:
    # The model is part of the stamp: tuples harvested by another model are
    # not "current" any more than tuples harvested with another prompt.
    #
    # So are the anchors. They are the only probes the plan searches with, so
    # they decide WHICH passages a document was read from, and a document
    # harvested under one set is not the same result as one harvested under
    # another. Without this the documents an interrupted run had already
    # stamped come back "current", stay the only ones on the old set, and
    # nothing in the corpus says which document was read with what.
    return {"spec": spec_sha, "model": LLM_MODEL, "anchors": anchors_sha,
            **prompts.versions(PROMPT_IDS)}


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
                 force: bool = False, force_stale: bool = False,
                 anchors_sha: str = "") -> bool:
    if already_done(name, out_dir, spec_sha, force=force,
                    force_stale=force_stale, anchors_sha=anchors_sha):
        return True
    report = harvest_document(document_id, spec, templates,
                              retrieve=deps["retrieve"],
                              harvest=deps["harvest"],
                              locate=deps.get("locate"),
                              structure=deps.get("structure"),
                              more_sources=deps.get("more_sources"),
                              extra_probes=deps.get("anchors"),
                              prose_top=PROSE_TOP)
    finish_document(report, name, out_dir, spec_sha, anchors_sha)
    return True


def already_done(name: str, out_dir: Path, spec_sha: str, *,
                 force: bool = False, force_stale: bool = False,
                 anchors_sha: str = "") -> bool:
    """True when this document needs no work: harvested under the current
    spec, prompts, model and anchors — or stale with nobody asking for the
    redo."""
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
    changed = stale(stamp_path, _stamp_current(spec_sha, anchors_sha))
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
                    anchors_sha: str = "", answered: Optional[int] = None) -> None:
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
    write_report(report, out_dir / f"{name}.jsonl")
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
        json.dumps(_stamp_current(spec_sha, anchors_sha), indent=2),
        encoding="utf-8")


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
# p90 is what rescue_reply is for.
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
                        help="No harvest and no model: apply the current "
                             "evidence rule to the JSONL already in OUT, drop "
                             "every coordinate whose quote does not carry it, "
                             "and clear the stamps so the next run redoes them")
    parser.add_argument("--keep-stamps", action="store_true",
                        help="--recheck only: leave the resume stamps in place")
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
    import hashlib
    spec_sha = hashlib.sha256(spec_path.read_bytes()).hexdigest()
    # Read here rather than beside make_anchors, because the resume stamps are
    # checked before the anchors are ever built and a stamp that does not know
    # which anchors produced a document cannot tell it from one produced under
    # another set. A broken anchors file raises here, before the model loads.
    frozen, frozen_sha = frozen_anchors(profile, spec)
    # Which coordinates decide whether a value belongs in the graph at all.
    # The profile's business: "scenario == target" is what the kwp target
    # slice holds and says nothing about any other corpus.
    slice_gate = profile.component("extraction", "SLICE") or {}
    if slice_gate:
        log.info("extraction: slice gate on %s — a row that falls out here "
                 "is not asked for its other coordinates",
                 ", ".join(sorted(slice_gate)))
    anchors_sha = anchors_key(spec_sha, frozen_sha)
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
        log.info("extraction: one request per field, swept in windows of %d "
                 "(overlap %d) until read; %d batch thread(s), %d field "
                 "thread(s), at most %d window(s) per coordinate",
                 FIELD_WINDOW, FIELD_OVERLAP, LLM_PARALLEL, FIELD_PARALLEL,
                 FIELD_MAX_WINDOWS)
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

    documents = [(did, fn) for did, fn in documents
                 if not already_done(Path(fn).stem, args.out, spec_sha,
                                     force=args.force,
                                     force_stale=args.force_stale,
                                     anchors_sha=anchors_sha)]
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
               else make_anchors(spec, store=args.out / "anchors.json",
                                 key=anchors_sha, frozen=frozen))

    cache_path = args.out / "query_cache.db"
    primer = query_cache.connect(cache_path)
    prime_probe_cache(primer, spec, templates, anchors)
    primer.close()
    more_sources = make_more_sources(args.db, index, id_to_pos, cache_path)

    # After more_sources, because the field sweep uses it: a coordinate that
    # is not in the value's own passage is looked for further out in the same
    # document. OpenAI client is thread-safe.
    harvest = (make_fieldwise_harvester(args.image_root, more_sources,
                                        make_rest_of_document(args.db),
                                        spec=spec, anchors=anchors,
                                        slice_gate=slice_gate,
                                        parents=make_parents(args.db))
               if FIELDWISE else make_harvester(args.image_root, spec=spec))

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
                retrieve=make_retrieve(conn, index, id_to_pos, cache_conn,
                                       fetch, per_probe_top=POOL_TOP),
                structure=make_structure(conn, fetch), prose_top=PROSE_TOP)
            for item in items:
                trace.event("plan", document_id, rank=item.rank,
                            origin=item.origin, kind=item.source.owner_kind,
                            owner=item.source.owner_id,
                            chars=len(item.source.text or ""),
                            image=bool(item.source.image_path))
            return Path(filename).stem, split_long_sources(items), report
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

        routed, _orphans = route_claims(batch, reply.get("tuples"))
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
                        answered=replies)
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
        # Every batch of every document goes into one pool. A batch belongs
        # to exactly one document, so the replies come back where they can be
        # folded; nothing about the scheduling depends on that.
        batches: list = []
        owner_of: dict = {}
        for name, items, report in plans:
            for batch in group_items(items, max_sources=BATCH_SOURCES,
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
