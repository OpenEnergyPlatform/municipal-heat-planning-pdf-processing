"""
runner.py: Wires the pure harvest loop of `pipeline.py` to the live stack.

A run harvests from the survey of each plan (`surveyed_flow`, which stops the
run where the spec names no groups or the profile lacks a prompt of the
survey): survey, reading and combing per document (`surveyed.py`), then the
fold, the compute step and the file with its stamp as below. The passes over a
stored harvest run on the same steps.

This module supplies the loop's expensive dependencies from the real world:
FAISS retrieval with owner exclusion, the model calls, and locating a quote on
its page in the source PDF, plus resume stamps and the CLI. Heavy imports
(faiss, torch-backed embedders, fitz) happen inside functions, so importing
this module stays cheap and a test that only touches the package pays for no
GPU stack it does not use.

`make_retrieve` fuses every probe handed to it into one FAISS search per
document and ranks each owner by the best score any probe gave it; measured
over 65 documents and 15,082 values, the fused ranking put the source a value
was really read from at median rank 26, against 77 for the old per-probe
concatenation. A probe is a HyDE-style sentence a model writes:
`document_anchor` writes the one short sentence per parameter the document is
searched with, which is a cache miss by construction.

The requests parse the reply strictly: one JSON object and nothing else. A
reply that is not that is asked again with the cause named (`_reply_fault`).

`make_locate` finds where a quote sits on its page in the source PDF, through
the same alignment the app highlights with. Resume stamps (`_stamp_current`,
`stale`) record a fingerprint per question a spec asks (`spec.fingerprints`),
so an ontology edit restales only the documents asked through the coordinate it
touched, not the whole corpus. `main` is the CLI: a normal harvest, and the
`--recheck`, `--remap`, `--serialize`, `--review`, `--top-up` and
`--top-up-parameters` maintenance passes over a harvest already written.

Author: Felix Vossel
"""
from __future__ import annotations

import argparse
import functools
import hashlib
import json
import logging
import os
import signal
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Callable, Optional

from docpipe import prompts
from docpipe import providers
from docpipe import usage as token_usage
from docpipe.llm_preflight import assert_serving, request_extras
from docpipe.profile import add_profile_argument, program, require_profile
from docpipe.store.schema import readonly_uri

from . import archive
from . import combing as combing_map
from . import compute as computing
from . import fields
from . import found as found_places
from . import naming as naming_map
from . import reading as reading_map
from . import replies
from . import seeking as seeking_map
from . import settings as settings_map
from . import survey as survey_map
from . import surveyed as surveyed_map
from . import thread as thread_map
from . import years as years_map
from . import scheduler
from . import scratch
from . import trace
from .wording import say
from .pipeline import (YEAR_STATES, DocumentReport, Source,
                       cell_index as pipeline_cell_index, column_head,
                       drop_repeats, fold_batch, fold_claims, named_years,
                       option_named, window_around, write_report)
from .verify import flat as flat_text
from .trust import document_summary, parameter_states
from .spec import Spec, fingerprints, load as load_spec

log = logging.getLogger(__name__)

LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "http://localhost:8000/v1")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "EMPTY")
LLM_MODEL = os.environ.get("LLM_MODEL", "Qwen/Qwen3.5-122B-A10B-FP8")
LLM_TIMEOUT = int(os.environ.get("LLM_TIMEOUT", "180"))
MAX_RETRIES = int(os.environ.get("EXTRACT_MAX_RETRIES", "3"))
# What a retry may take after a request timed out. The first attempt keeps
# LLM_TIMEOUT, which is sized for a slow but working generation; a request the
# server did not answer in that time is unlikely to differ on its repeat, and
# three full timeouts held one field thread for 91 minutes.
RETRY_TIMEOUT = int(os.environ.get("EXTRACT_RETRY_TIMEOUT", "600"))
# A malformed reply asked again at temperature 0 comes back the same, byte for
# byte, correction message or not: on corpus_m5 field retries
# repeated their first attempt exactly and all three were lost. Every reply
# fault raises the temperature of the next attempt by this step.
RETRY_TEMPERATURE_STEP = float(os.environ.get("EXTRACT_RETRY_TEMPERATURE_STEP",
                                              "0.1"))

# Set by SIGTERM (a time-limit trap or a manual kill). The run stops
# taking new work, writes the documents whose every batch came back, and
# exits without waiting for the requests still open.
STOP = threading.Event()


def retry_temperature(base: float, faults: int) -> float:
    """The sampling temperature after `faults` unreadable replies."""
    return min(1.0, base + RETRY_TEMPERATURE_STEP * faults)


STOPPED_EXIT = 143
_hard_exit = os._exit


def install_stop_handler() -> None:
    """SIGTERM sets STOP instead of killing the interpreter mid-group.

    Killed outright, a time-limit stop threw away the whole group in flight,
    up to 64 documents and hours of work, including every batch that had
    already come back. Only the main thread can install a handler, so a call
    from anywhere else leaves the default in place.
    """
    if threading.current_thread() is not threading.main_thread():
        return
    signal.signal(signal.SIGTERM, lambda *_: STOP.set())
RETRY_WAIT = float(os.environ.get("EXTRACT_RETRY_WAIT", "2"))
RETRY_WAIT_MAX = float(os.environ.get("EXTRACT_RETRY_WAIT_MAX", "6"))
TRANSPORT_WAIT = float(os.environ.get("EXTRACT_TRANSPORT_WAIT", "15"))
TRANSPORT_WAIT_MAX = float(os.environ.get("EXTRACT_TRANSPORT_WAIT_MAX", "120"))


def unheld_requests() -> int:
    """1 when this run replayed a cassette and asked something it does not
    hold, else 0: such a harvest is not the recorded run's, and a job that
    compares the two must not take it for one."""
    if not providers.replaying():
        return 0
    from docpipe.providers import cassette
    held = cassette.player()
    log.info("extraction: %d answer(s) taken from %s, %d request(s) it does "
             "not hold", held.replayed, held.path.name, held.missed)
    if not held.missed:
        return 0
    log.error("extraction: this run asked %d request(s) the recorded one did "
              "not. Its harvest is not the recorded run's and says nothing "
              "about it.", held.missed)
    return 1


def retry_wait(attempt: int, transport: bool = False) -> float:
    """Seconds to wait before attempt *attempt* + 1.

    *transport* is the request that never reached the server: no HTTP status,
    no refusal, nothing to read. Doubling from 15 seconds gives a restarting
    vLLM 225 seconds over five attempts, which is what a model server needs
    to come back; the model's own mistakes keep the short curve, because
    waiting longer for those buys nothing.
    """
    if providers.replaying():
        return 0.0          # nothing comes back that is waited for
    if transport:
        return min(TRANSPORT_WAIT * (2 ** max(0, attempt - 1)),
                   TRANSPORT_WAIT_MAX)
    return min(RETRY_WAIT * attempt, RETRY_WAIT_MAX)


def unserved(exc: BaseException) -> bool:
    """A 429, a 5xx or a timeout: the server was asked and did not do the work.

    None says anything about the request. A rate limit lifts and a server
    recovers, and the same request is answered then. A request that timed out
    was never answered either: a server whose engine stopped taking requests
    kept its connections open until every one of them timed out, and their
    documents were stamped with the coordinates never read. Every other 4xx
    refuses the request itself, and refuses it every time.
    """
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status == 429 or status >= 500
    return providers.timed_out(exc)


def server_side(exc: BaseException) -> bool:
    """Whether a failure is the server's: it never arrived, or was `unserved`.

    These wait on the long curve and count towards the dead-server streak. A
    429 retried after two seconds is the same 429.
    """
    return (not isinstance(getattr(exc, "status_code", None), int)
            or unserved(exc))


class Unserved:
    """Documents one of whose requests ended on a 429, a 5xx or a timeout.

    Such a request was never answered, so its document is not finished,
    whichever request it was: a passage's rows, one coordinate, the frame, a
    search sentence. `finish_document` leaves the document unstamped and a
    resume harvests it again. Counted under None: requests of the run itself.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._count: dict = {}

    def note(self, document_id) -> None:
        with self._lock:
            self._count[document_id] = self._count.get(document_id, 0) + 1

    def of(self, document_id) -> int:
        with self._lock:
            return self._count.get(document_id, 0)

    def clear(self) -> None:
        with self._lock:
            self._count.clear()


# For the whole run, like STOP: the request loops only know a document's id.
UNSERVED = Unserved()


class Failures:
    """What the failures of one request mean, the same for every request of
    the stage. The rule stands here once and not in each retry loop: of nine
    loops, three kept all of it, and the compute request asked again at once
    after a server error, asked a refused request again, and left its
    document stamped as finished when no attempt of it was served.

    A failure that is the server's (`server_side`) is asked again, after the
    long wait (`retry_wait`). Any other refuses the request itself, every
    time, and is not asked again. A request given up on whose last attempt
    the server did not serve (`unserved`) leaves its document unfinished
    (`UNSERVED`): the stamp is withheld and a resume reads it again.

    *document_id* is the document the request reads, None for a request of
    the run itself. *noted* is False for a request whose end is told another
    way: one the document is finished without (the places map, the review),
    or one whose hole carries its cause to the stamp itself (the rows
    harvest, `not_happened`). It still waits and stops by the rule.
    """

    def __init__(self, document_id=None, noted: bool = True):
        self.document_id = document_id
        self.noted = noted
        self.transport = False
        self.lost = False

    def failed(self, exc: BaseException) -> bool:
        """Whether the request that raised *exc* is asked again."""
        self.transport, self.lost = server_side(exc), unserved(exc)
        return self.transport

    def answered(self) -> None:
        """The server answered the request, whatever its reply says."""
        self.transport = self.lost = False

    def wait(self, attempt: int) -> None:
        """Before asking again after attempt *attempt*: the long curve after
        the server's failure, the short one after a reply."""
        time.sleep(retry_wait(attempt, self.transport))

    def given_up(self) -> None:
        """The request is asked no more and has no answer."""
        if self.lost and self.noted:
            UNSERVED.note(self.document_id)
# Requests in flight against the server, for the whole run — not per document.
# vLLM batches continuously: what it can schedule is what it is given, and a
# handful of requests leaves four GPUs idle between tokens. The first pilot
# ran eight at a time and did 0.14 requests a second.
LLM_PARALLEL = int(os.environ.get("EXTRACT_LLM_PARALLEL", "128"))
# Sandbox rounds per harvest. A computed value carries its code and the code's
# output as evidence; without the sandbox the model would have to work the
# number out itself, and that number would have no evidence at all.
CODE_ROUNDS = int(os.environ.get("EXTRACT_CODE_ROUNDS", "2"))
# How many code runs the sandbox takes at a time, for the whole run. A code
# run waiting for its turn stands on the sandbox's own timeout otherwise.
SANDBOX_SLOTS = threading.BoundedSemaphore(
    int(os.environ.get("CODE_EXEC_PARALLEL", "1")))
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
# Threads for the two cheap halves: retrieval planning (FAISS + SQL) and
# verification (PyMuPDF quote location). Neither talks to the LLM server.
PLAN_PARALLEL = int(os.environ.get("EXTRACT_PLAN_PARALLEL", "8"))
# The longest stretch of source text one request may carry. A section over
# this is split into windows and each window asked separately: truncating
# would drop values silently, which is the one thing this stage may not do.
MAX_SOURCE_CHARS = int(os.environ.get("EXTRACT_MAX_SOURCE_CHARS", "16000"))
# Tables and figures go to the model as pictures as well as text: the
# transcription IS a reading of that picture, and a model that can see both
# can notice when they disagree.
ATTACH_IMAGES = os.environ.get("EXTRACT_ATTACH_IMAGES", "1") != "0"
IMAGE_MAX_SIDE = int(os.environ.get("EXTRACT_IMAGE_MAX_SIDE", "1280"))
# A section can run over a page break; how many of its pages to try before
# giving up on placing the quote.
LOCATE_MAX_PAGES = int(os.environ.get("EXTRACT_LOCATE_MAX_PAGES", "3"))
# Pages whose words stay in memory for the locator, across documents.
LOCATE_CACHE_PAGES = int(os.environ.get("EXTRACT_LOCATE_CACHE_PAGES", "512"))

ANCHORS_PROMPT_ID = "extraction/anchors"
# The one sentence a document is searched with, written for THAT document.
PHRASE_PROMPT_ID = "extraction/phrase"
# The prompts of a harvest from the survey (survey.py, reading.py,
# combing.py, settings.py, seeking.py), the run's own wherever the profile
# writes them and its spec names groups (`surveyed_flow`).
SURVEY_PROMPT_IDS = (survey_map.SURVEY_PROMPT_ID, *reading_map.PROMPT_IDS,
                     combing_map.COMB_PROMPT_ID, reading_map.CHECK_PROMPT_ID,
                     settings_map.SETTINGS_PROMPT_ID,
                     seeking_map.SEEK_PROMPT_ID)
# The flow this run harvests with: only the survey. Stamps and producers
# record it and the prompts it sends, and nothing compares either; those of
# older harvests say "fieldwise" (`schema.py`), which is still read.
SURVEYED = "survey"
FLOW = SURVEYED
# The second reading of one value, under a window narrowed to the two passages
# the row may legally quote from. Not in SURVEY_PROMPT_IDS, which are the harvest's
# own prompts: what the review writes into a stamp goes under `review/`.
REVIEW_PROMPT_ID = "extraction/review"

# The anchors.json key of the "which quantity is this" question. It belongs to
# no single parameter, so it cannot be keyed by one.
PARAMETER_ANCHOR = "#parameter"
# The same for "which entry of the unit lists is this", asked before it.
UNIT_ANCHOR = "#unit"
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
# What the last stage may spend. Its own number rather than a share of the
# one above: reading the rest of a plan is a different search from ranking
# passages out of it, and the two sharing a budget is what left the stage
# unreachable for every sweep that needed it.
REST_MAX_WINDOWS = int(os.environ.get("EXTRACT_REST_MAX_WINDOWS", "12"))
# A rest stage that only the end of the document stops: the budget is
# compared, never counted down window by window, so no plan comes near it.
REST_TO_END = 1_000_000


def read_to_end() -> None:
    """Every sweep from here on reads the rest of its document to the end, so
    a coordinate ends read or `unstated` and never `exhausted`."""
    global REST_MAX_WINDOWS
    REST_MAX_WINDOWS = REST_TO_END


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


class Coalescer:
    """embed(items) from any number of threads, sent to the model in batches.

    The searches of every document in flight ask for vectors at the same
    time, a few probes each. One worker takes everything that has queued up,
    embeds it in one call, and hands each caller its slice; what arrives
    while that call runs is the next batch. So a batch is as large as the
    demand of the moment and no larger, and the card runs one call at a time
    instead of a hundred small ones racing for it.
    """

    def __init__(self, backend: Callable):
        self._backend = backend
        self._cond = threading.Condition()
        self._queue: list = []
        self._worker: Optional[threading.Thread] = None
        self.calls = 0

    def embed(self, items: list) -> list:
        if not items:
            return []
        slot = {"items": list(items), "done": False}
        with self._cond:
            self._queue.append(slot)
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(target=self._run, daemon=True,
                                                name="embed")
                self._worker.start()
            self._cond.notify_all()
            while not slot["done"]:
                self._cond.wait()
        if "error" in slot:
            raise slot["error"]
        return slot["vectors"]

    def _run(self) -> None:
        while True:
            with self._cond:
                while not self._queue:
                    if not self._cond.wait(timeout=60) and not self._queue:
                        self._worker = None
                        return
                batch, self._queue = self._queue, []
            flat = [item for slot in batch for item in slot["items"]]
            try:
                vectors = self._backend().embed(flat)
                self.calls += 1
            except Exception as exc:          # every caller hears of it
                vectors, error = None, exc
            with self._cond:
                at = 0
                for slot in batch:
                    if vectors is None:
                        slot["error"] = error
                    else:
                        slot["vectors"] = vectors[at:at + len(slot["items"])]
                        at += len(slot["items"])
                    slot["done"] = True
                self._cond.notify_all()


COALESCED = Coalescer(embedder)


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


# Owners (sections, tables, figures) whose content a run keeps. The whole of
# the largest corpus fits (KWP: 252,909), so a run reads each owner once; past
# the bound the oldest goes, so a larger corpus cannot grow into it.
CONTENT_CACHE_OWNERS = int(os.environ.get("EXTRACT_CONTENT_CACHE_OWNERS",
                                          "300000"))


def make_shared_content(limit: Optional[int] = None) -> Callable:
    """fetch_owner_content for every thread of a run, each owner read once.

    The harvest's helpers used to give each thread a `make_content_fetcher`
    of its own, unbounded, in pools that live as long as the run. The KWP run
    of 2026-10-14 had 2,308 threads and grew from 46 to 53 GB of heap between
    its third and its sixth hour: the same sections held once per thread that
    had read them. One store for all threads holds each owner once.

    A hit is a dict lookup and waits for nobody. A miss reads under the lock
    and looks again first, so two threads missing the same owner read it once.
    Each caller passes its own connection: the store is shared, the SQLite
    handle is not.
    """
    from docpipe.inference import db as inference_db

    bound = CONTENT_CACHE_OWNERS if limit is None else limit
    lock = threading.Lock()
    seen: dict = {}

    def fetch(conn, owner_kind: str, owner_id: int):
        key = (owner_kind, owner_id)
        try:
            return seen[key]
        except KeyError:
            pass
        with lock:
            if key not in seen:
                content = inference_db.fetch_owner_content(conn, owner_kind,
                                                           owner_id)
                if bound > 0 and len(seen) >= bound:
                    seen.pop(next(iter(seen)))
                seen[key] = content
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

    def embed_many(probes: list) -> list:
        """The vectors of *probes*: the cached ones read, the others embedded
        in one call that waits with every other thread's (`COALESCED`)."""
        keys = [query_cache.make_key("text", text=p, image_bytes=None)
                for p in probes]
        vectors = [query_cache.get(cache_conn, key) for key in keys]
        missing = [i for i, vec in enumerate(vectors) if vec is None]
        if missing:
            fresh = COALESCED.embed([{"text": probes[i]} for i in missing])
            for i, vec in zip(missing, fresh):
                vectors[i] = vec
            query_cache.put_many(cache_conn, [(keys[i], vectors[i])
                                              for i in missing])
        return vectors

    # A sweep calls this once per parameter and per round with the same probe
    # list, and only `exclude` differs between rounds. Without these two the
    # document's sub-index is rebuilt and the identical score matrix recomputed
    # sixteen times over — four parameters by four rounds.
    document: list = [None, None]         # document_id, prepared
    search: list = [None, None]           # probe key, (scores, positions)
    default_limit = limit

    def retrieve(probes: list, document_id: int, exclude: set,
                 limit: Optional[int] = None) -> list:
        """*limit* per call overrides the one given at construction: the
        sweep asks for as many passages as its remaining windows can show."""
        if document[0] != document_id:
            document[:] = [document_id, faiss_store.prepare_document(
                conn, index, id_to_pos, document_id, all_types)]
            search[:] = [None, None]
        key = (document_id, tuple(probes))
        if search[0] != key:
            search[:] = [key, faiss_store.search_prepared(
                document[1], embed_many(list(probes)))]
        scores, positions = search[1]
        hits = faiss_store.fuse_prepared(
            conn, document[1], scores, positions,
            default_limit if limit is None else limit,
            content_fetcher=content_fetcher, exclude=exclude, probes=probes,
            per_probe_top=per_probe_top)
        return [_source_of(hit) for hit in hits]

    return retrieve


# How much of a parent section rides along with its table. Kassel's median
# section is 894 characters and its longest is 6,038, so most fit whole and
# the rest are cut around the table's own placeholder rather than dropped:
# the sentence that dates a table stands next to its placeholder and nowhere
# else.
PARENT_CHARS = int(os.environ.get("EXTRACT_PARENT_CHARS", "4000"))


def make_parents(db_path: Path, content: Optional[Callable] = None) -> Callable:
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
    The content read through it is: *content* is the run's shared store
    (`make_shared_content`), or one of its own.
    """
    local = threading.local()
    shared = content or make_shared_content()

    def fetcher():
        if getattr(local, "conn", None) is None:
            local.conn = sqlite3.connect(readonly_uri(db_path), uri=True)
            local.conn.row_factory = sqlite3.Row
        return local.conn, shared

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
                                text=window_around(parent.text, f"[{block}",
                                             PARENT_CHARS),
                                provenance=parent.provenance,
                                image_path=parent.image_path)
            out.append(parent)
        return out

    return parents


def make_owner_sources(db_path: Path,
                       content: Optional[Callable] = None) -> Callable:
    """(owners) -> {(kind, id): Source} for passages a harvest already named.

    The harvest stores the address of a passage and not its text, so a pass
    that reads one coordinate again has to fetch it back. Through the same
    two functions the harvest used -- the cached fetcher and `_source_of` --
    so the heading is prefixed the same way and a quote that was checkable
    during the harvest stays checkable.

    Its own connection per thread, read-only, and memoised across calls in
    *content*, the run's shared store or one of its own: one section is the
    parent of several rows and would otherwise be read once per row.
    """
    local = threading.local()
    shared = content or make_shared_content()

    def _connections():
        if getattr(local, "conn", None) is None:
            local.conn = sqlite3.connect(readonly_uri(db_path), uri=True)
            local.conn.row_factory = sqlite3.Row
        return local.conn, shared

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


def make_review_sources(db_path: Path,
                        content: Optional[Callable] = None) -> Callable:
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
    handles are not shared. The content is, with the parents too: *content*,
    the run's shared store or one of its own.
    """
    local = threading.local()
    shared = content or make_shared_content()
    parents = make_parents(db_path, content=shared)

    def _connections():
        if getattr(local, "conn", None) is None:
            local.conn = sqlite3.connect(readonly_uri(db_path), uri=True)
            local.conn.row_factory = sqlite3.Row
        return local.conn, shared

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


def make_rest_of_document(db_path: Path,
                          content: Optional[Callable] = None) -> Callable:
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

    A section's tables and figures follow it, in page order. The floor read
    sections only, and 71 percent of corpus_m5's tuples came out of images:
    "the whole document" that left out every table was not the whole document.

    Each call reads a whole document, so what it read goes into *content*, the
    run's shared store, and not into a store per thread.
    """
    local = threading.local()
    shared = content or make_shared_content()

    def connections():
        if getattr(local, "conn", None) is None:
            local.conn = sqlite3.connect(readonly_uri(db_path), uri=True)
            local.conn.row_factory = sqlite3.Row
        return local.conn, shared

    def rest_of_document(document_id: int, exclude: set,
                         start: Optional[int] = None) -> list:
        conn, fetch = connections()
        try:
            order = [(int(r[0]), r[1]) for r in conn.execute(
                "SELECT id, section_number FROM Sections WHERE document = ? "
                "ORDER BY COALESCE(section_number, id)", (document_id,))]
            blocks: dict = {}
            for kind, table in (("table", "Tables"), ("figure", "Images")):
                for r in conn.execute(
                        f"SELECT o.id, o.section FROM {table} o "
                        f"JOIN Sections s ON o.section = s.id "
                        f"WHERE s.document = ? ORDER BY o.page_number, o.id",
                        (document_id,)):
                    blocks.setdefault(int(r[1]), []).append((kind, int(r[0])))
        except Exception as exc:
            log.warning("   sections of document %s unreadable: %s",
                        document_id, exc)
            return []
        if start is not None:
            at = next((i for i, (_id, number) in enumerate(order)
                       if number is not None and number >= start), 0)
            order = order[at:] + order[:at]
        owners = [(kind, owner_id) for section_id, _number in order
                  for kind, owner_id in ([("section", section_id)]
                                         + blocks.get(section_id, []))]
        out: list = []
        for kind, owner_id in owners:
            if (kind, owner_id) in exclude:
                continue
            hit = fetch(conn, kind, owner_id)
            if hit is None:
                continue
            out.append(_source_of({**hit, "owner_kind": kind,
                                   "owner_id": owner_id}, via="comb"))
        return out

    return rest_of_document


def make_search_reranker(image_root: Optional[Path] = None
                         ) -> Optional[Callable]:
    """() -> one thread's reranker of every search (`rerank.Reranker`), or
    None where the run is given no RERANK_BASE_URL (owner decisions
    2026-11-06 and 2026-11-08). A figure is scored with its picture, as the
    reading shows it."""
    from docpipe.inference import rerank as rerank_map
    if not rerank_map.RERANK_BASE_URL:
        return None

    def figure_image(source) -> Optional[dict]:
        if (source.owner_kind == "figure" and source.image_path
                and ATTACH_IMAGES):
            return _image_part(str(image_root / source.image_path)
                               if image_root else source.image_path)
        return None

    log.info("extraction: searches reranked by %s at %s, %d per kind",
             rerank_map.RERANK_MODEL, rerank_map.RERANK_BASE_URL,
             rerank_map.RERANK_POOL)
    return lambda: rerank_map.make_reranker(image_of=figure_image)


def make_more_sources(db_path: Path, index, id_to_pos: dict,
                      cache_path: Path,
                      content: Optional[Callable] = None,
                      reranker: Optional[Callable] = None) -> Callable:
    """(document_id, queries, exclude) -> the passages the model asked for.

    Retrieval a second time, but from a query the MODEL wrote rather than one
    the spec generated. It runs during the harvest, not the plan, so it opens
    its own connections per thread: the harvest pool is a hundred threads
    wide and SQLite handles are not shared across them.

    Queries the model invents are one-offs, so they miss the primed cache and
    are embedded on the spot. That is the whole cost of the round trip, and
    it only happens when the model says the passages it was given are not
    enough.

    *limit* bounds what one call hands back. The ranking covers the whole
    document, and handed over whole it marked every passage of the plan as
    seen after the first round: the stage that reads the rest in order then
    found nothing left, and a sweep whose budget had cut the ranked list
    ended "unstated" instead of "exhausted". corpus_m5 wrote 0 exhausted
    coordinates in 263,997 sweeps that way. 0 means no bound.

    The passages' content comes from *content*, the run's shared store or one
    of its own, and not from a store per thread.

    *reranker()* makes one thread's reranker (`rerank.Reranker`), which puts
    the best passages of each kind in its own order before they are handed
    back; None leaves the vector search's order.
    """
    from docpipe.inference import query_cache

    local = threading.local()
    shared = content or make_shared_content()

    def connections():
        if getattr(local, "conn", None) is None:
            local.conn = sqlite3.connect(readonly_uri(db_path), uri=True)
            local.conn.row_factory = sqlite3.Row
            local.cache = query_cache.connect(cache_path, create=False)
            # One per thread, so the document's sub-index and the score
            # matrix survive from one round to the next; built per call they
            # were rebuilt for every round of every coordinate.
            local.retrieve = make_retrieve(local.conn, index, id_to_pos,
                                           local.cache, shared)
            local.rerank = reranker() if reranker is not None else None
        return local.retrieve

    def more_sources(document_id: int, queries: list, exclude: set,
                     limit: int = 0) -> list:
        retrieve = connections()
        found: list = []
        taken = set(exclude)
        try:
            # Every probe: a search asks with one sentence per table of its
            # open rows, and the ranking keeps each one's best match (max
            # over probes). Their vectors come in one batch (`embed_many`).
            for source in retrieve(list(queries), document_id, taken,
                                   limit=limit):
                key = (source.owner_kind, source.owner_id)
                if key in taken:
                    continue
                taken.add(key)
                found.append(source)
            if local.rerank is not None:
                found = local.rerank.order(document_id, list(queries), found)
        except Exception as exc:
            log.warning("   more-passages for document %s failed: %s",
                        document_id, exc)
            return []
        return found

    return more_sources


def fill_dynamic_axes(spec: Spec, vocabularies: Optional[dict]) -> Spec:
    """A copy of *spec* whose dynamic axes carry THIS document's list.

    The countries a publication names differ per publication, and a list of
    all 249 would bury the handful it names. Nothing but the model can map a
    wording onto an entry, and it can only do so if it is shown the list it
    may choose from; the mapping then arrives flagged, like every other
    judgement call the harvest records.
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
    # A copy in which only the lists differ: the questions the spec asks go
    # with it.
    return replace(spec, parameters=parameters) if changed else spec


def spec_of(batch, spec):
    """The spec a batch is read against: its document's, or the run's.

    The lists a document closes were built for the search and then left
    behind: the requests that read the passages and the check of their
    answers were built from the run's spec, where a dynamic list is empty.
    So the model was offered nothing to choose from on exactly the fields
    whose point is the choice, and wrote a wording instead.
    """
    own = getattr(batch, "spec", None)
    return spec if own is None else own


def narrow_spec(spec: Spec, only) -> Spec:
    """A copy of *spec* that asks these parameters (by uri) and no other.

    The spec itself when `only` is empty, so a harvest that names no
    parameter reads what it always read. Every request is built from the spec
    its batch carries (`spec_of`): the quantities the rows request offers,
    the units, the parameter question and the grammar of the reply. A batch
    that carries the narrowed copy therefore offers the model the named
    parameters and their units alone, which is how a pass for a new parameter
    keeps every row of a stored parameter from arising.
    """
    wanted = set(only or ())
    if not wanted:
        return spec
    return replace(spec, parameters=[p for p in spec.parameters
                                     if p.uri in wanted])


def make_document_spec(conn, spec: Spec,
                       document_axes: Optional[Callable]) -> Callable:
    """(document id) -> this document's spec, or None when its lists cannot
    be closed.

    For the passes that read a harvest already on disk. Asked against an
    empty list a dynamic axis degrades to a wording, which is a demotion
    nothing would report, so such a document is left alone and counted.
    """
    def document_spec(document_id):
        if document_axes is None:
            return spec
        if document_id is None:
            return None
        try:
            filled = document_axes(conn, document_id)
        except Exception as exc:              # pragma: no cover - defensive
            log.warning("   document %s: dynamic axes unreadable: %s",
                        document_id, exc)
            return None
        return fill_dynamic_axes(spec, filled) if filled else None

    return document_spec


def document_spec_per_call(db_path, spec: Spec,
                           document_axes: Optional[Callable]) -> Callable:
    """`make_document_spec` for a caller that runs one document per thread.

    A SQLite connection belongs to the thread that opened it, so each call
    opens its own, reads the document's lists and closes it again. Nothing
    is open between two calls.
    """
    def document_spec(document_id):
        conn = sqlite3.connect(readonly_uri(db_path), uri=True)
        conn.row_factory = sqlite3.Row
        try:
            return make_document_spec(conn, spec, document_axes)(document_id)
        finally:
            conn.close()

    return document_spec


@contextmanager
def document_specs(db_path, spec: Spec, document_axes: Optional[Callable]):
    """`spec_for` for a pass over a harvest on disk, the corpus open for as
    long as the pass runs. None when the profile closes no list per document:
    such a pass needs no database."""
    if document_axes is None:
        yield None
        return
    conn = sqlite3.connect(readonly_uri(db_path), uri=True)
    conn.row_factory = sqlite3.Row
    try:
        yield make_document_spec(conn, spec, document_axes)
    finally:
        conn.close()


# Bumped when the SET of anchor targets changes, not just their wording: an
# anchors.json written for three parameters must not be read back as if it
# also held the twenty-two question anchors this version asks for.
ANCHOR_SCHEMA = "per-question-1"


def _key16(raw: str) -> str:
    """Sixteen hex characters. Long enough that two configurations do not
    collide, short enough to read in a stamp beside twenty-nine other keys."""
    import hashlib
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def anchors_key() -> str:
    """Everything an anchor set depends on that is NOT one question: the
    anchor prompt, the model and the version of the target SET. The cache is
    stored under it and the stamp records it.

    Not the questions, though it used to hash them. Everything a target tuple
    carries is already a stamp key of its own -- a parameter's label and
    description in `parameter/<uri>`, an axis' question in
    `axis/<uri>/<name>`, the spec's own question and the parameter list in
    `slot/parameter`, the unit question and its lists in `slot/unit` -- and
    the anchor prompt and the model are stamp keys too
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
    out: list = [(PARAMETER_ANCHOR, say("anchor_parameter"), "",
                  spec.parameter_question),
                 (UNIT_ANCHOR, say("anchor_unit"), "",
                  spec.unit_question)]
    for parameter in spec.parameters:
        # asked_slots, not axis_slots: an anchor is a sentence to search
        # with, and a coordinate the spec derives is never searched for.
        for slot in fields.asked_slots(parameter):
            out.append((anchor_key(parameter.uri, slot.name),
                        f"{parameter.label} / {slot.name}",
                        parameter.description, slot.question))
    return [t for t in out
            if t[0] not in (PARAMETER_ANCHOR, UNIT_ANCHOR) or t[3]]


def phrase_payload(parameter, context: Optional[dict] = None,
                   frame: Optional[dict] = None) -> dict:
    """What a phrase request is written from: the parameter's label and
    description, the names of its list where it has one, what the document
    says of itself (*context*) and the pair the sentence searches for
    (*frame*)."""
    body = {"label": parameter.label, "description": parameter.description}
    if parameter.vocabulary:
        # The entries a document names, which the label alone never does
        # (owner decision 2026-11-05: the sentence is written from label,
        # description and list names).
        body["names"] = [labels[0] for labels in parameter.vocabulary.values()
                         if labels]
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
    return body


def document_context_of(db_path: Optional[Path],
                        document_context: Optional[Callable]) -> Callable:
    """context_of(document_id): what the document says of itself (the
    profile's `document_context`), each call on its own read-only
    connection; {} where the profile has none."""
    def context_of(document_id) -> dict:
        if document_context is None or db_path is None:
            return {}
        conn = sqlite3.connect(readonly_uri(db_path), uri=True)
        try:
            return dict(document_context(conn, document_id) or {})
        finally:
            conn.close()
    return context_of


def make_seek_probes(own=(), context_of: Optional[Callable] = None,
                     write: Optional[Callable] = None) -> Callable:
    """probes(parameter, document_id) -> the sentences the search for a
    parameter the survey named no passage for ranks with
    (`surveyed.sought_lists`, owner decision 2026-11-05).

    A parameter about the document itself (*own*, the profile's
    `FRONT_PAGE_PARAMETERS`: its title, authors, date, DOI and abstract) gets
    a sentence written for this document from what it says of itself
    (*context_of(document_id)*, the profile's `document_context`), since the
    document's own name finds its title page. Any other gets one sentence per
    run, written once from
    its label, description and list names and kept: the document's name
    pulls such a sentence toward the title page and away from the passage
    that states the value. *write(parameter, context)* writes the sentences,
    one phrase request (`document_anchor`) where not given. A parameter no
    sentence could be written for gets none, and the search falls back to
    its label. A document's own sentence is sent in that document's turn, the
    run's before every document, since every document waits on it
    (`document_anchor`, *shared*; owner decision 2026-11-07).
    """
    own = set(own or ())
    lock = threading.Lock()
    made: dict = {}

    def phrase(parameter, context, document_id, shared=False):
        if write is not None:
            return list(write(parameter, context) or [])
        return document_anchor(SimpleNamespace(parameters=[parameter]),
                               context, document_id=document_id,
                               shared=shared).get(parameter.uri, [])

    def probes(parameter, document_id) -> list:
        if parameter.uri in own:
            context = dict(context_of(document_id) if context_of else {})
            sentences = phrase(parameter, context, document_id)
            per = "document"
        else:
            with lock:
                if parameter.uri not in made:
                    made[parameter.uri] = phrase(parameter, None, document_id,
                                                 shared=True)
                sentences = made[parameter.uri]
            per = "run"
        for text in sentences:
            trace.event("seek_probe", document_id, parameter=parameter.uri,
                        per=per, text=text)
        return list(sentences)
    return probes


def document_anchor(spec: Spec, context: Optional[dict] = None,
                    client=None, prompt=None,
                    frame: Optional[dict] = None,
                    document_id: Optional[int] = None,
                    shared: bool = False) -> dict:
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

    Each request is sent for *document_id*, in that document's turn, with
    the ticket of the thread that asked (`_for`), although a thread of the
    pool below sends it: such a thread belongs to no document, and a request
    of none goes before every document. A *shared* sentence, the one the run
    keeps for every document (`make_seek_probes`), is sent for none, as
    everything every document waits on is; *document_id* still notes its
    failures and traces it (owner decision 2026-11-07).
    """
    prompt = prompt if prompt is not None else prompts.load(PHRASE_PROMPT_ID)
    client = _repeating(client or _client())
    context = {k: v for k, v in (context or {}).items()
               if isinstance(v, str) and v.strip()}
    behalf = (None, None) if shared else (document_id,
                                          scheduler.current()[1])

    def one(parameter):
        payload = json.dumps(phrase_payload(parameter, context, frame),
                             ensure_ascii=False, indent=2)
        failures = Failures(document_id)
        conversation: list = [{"role": "user", "content": payload}]
        limit = int(prompt.meta.get("max_tokens", 300))
        faults = 0
        for attempt in range(1, MAX_RETRIES + 1):
            started = time.time()
            try:
                with scheduler.on_behalf(*behalf):
                    response = client.chat.completions.create(
                        model=LLM_MODEL,
                        temperature=retry_temperature(
                            float(prompt.meta.get("temperature", 0)), faults),
                        max_tokens=limit,
                        messages=[{"role": "system", "content": prompt.text},
                                  *conversation],
                        extra_body=request_extras(),
                        **providers.formatted("llm", "phrase_reply",
                                              replies.phrase()),
                    )
                failures.answered()
                token_usage.reply(response, LLM_MODEL)
                _asked("phrase", document_id, response, attempt=attempt,
                       started=started, parameter=parameter.uri)
                reply = response.choices[0]
                phrase = ((_loads_object(reply.message.content) or {})
                          .get("phrase") or "")
                phrase = phrase.strip() if isinstance(phrase, str) else ""
                if phrase:
                    return parameter.uri, [phrase]
                # The same retry rule as everywhere else: a reply that could
                # not be read is asked again WITH the reason. Three silent
                # tries were three copies of the same reply.
                cause, correction = _reply_fault(reply, limit)
                faults += 1
                log.warning("phrase %s attempt %d: %s reply",
                            parameter.uri, attempt, cause)
                conversation.append({"role": "assistant",
                                     "content": reply.message.content or ""})
                conversation.append({"role": "user", "content": correction})
            except Exception as exc:
                log.warning("phrase %s attempt %d failed: %s",
                            parameter.uri, attempt, exc)
                if not failures.failed(exc):
                    break
            if attempt < MAX_RETRIES:
                failures.wait(attempt)
        failures.given_up()
        log.warning("phrase %s: no anchor written for this document",
                    parameter.uri)
        return parameter.uri, []

    # One request per parameter, all at once: in sequence they were four
    # round trips per document under a plan pool of eight, and planning a
    # group of 64 plans took half an hour with the GPUs waiting.
    from concurrent.futures import ThreadPoolExecutor
    out: dict = {}
    with ThreadPoolExecutor(max_workers=max(len(spec.parameters), 1)) as pool:
        for uri, phrase in pool.map(one, spec.parameters):
            if phrase:
                out[uri] = phrase
    return out


# The server's context window. Read from the server at the start of a run
# (`set_model_len`); the job serves at least `context_budget`.
MAX_MODEL_LEN = int(os.environ.get("EXTRACT_MAX_MODEL_LEN", "32768"))
# Prompt characters per token, set low so a prompt is never estimated short.
PROMPT_CHARS_PER_TOKEN = 2.62
# One crop at IMAGE_MAX_SIDE on both sides, one visual token per 28 px square.
IMAGE_TOKENS = (IMAGE_MAX_SIDE // 28 + 1) ** 2 + 2
# Room kept free between the estimate and the window.
ANSWER_MARGIN = 256
# Less room than this for the answer and the request is not sent.
MIN_ANSWER_TOKENS = 512


def set_model_len(tokens: Optional[int]) -> None:
    """The window the server reports, when it reports one."""
    global MAX_MODEL_LEN
    if tokens:
        MAX_MODEL_LEN = int(tokens)


# The adaptive request limit every client waits in, steered by the server's
# queue (throttle.py); None while it is off or the server has no /metrics.
LIMIT = None
# The one queue every request of the run is sent through, oldest document
# first (scheduler.py), and the threads a sweep asks its windows ahead on.
# Both None while the limit is off: a sweep then asks one window at a time.
SCHEDULER = None
AHEAD = None


def start_limit() -> None:
    """Steer the requests by the server's queue unless EXTRACT_LIMIT_ADAPTIVE=0."""
    global LIMIT
    if LIMIT is not None or os.environ.get("EXTRACT_LIMIT_ADAPTIVE",
                                           "1") == "0":
        return
    if providers.replaying():
        return              # no queue to read and nothing to be refused by
    from . import throttle
    gate = providers.gate("llm")
    # A hosted API has no queue to read; what it refuses steers the limit.
    LIMIT = (throttle.start(LLM_BASE_URL) if gate is None
             else throttle.start_hosted(gate))
    if LIMIT is not None:
        global SCHEDULER, AHEAD
        SCHEDULER = scheduler.Scheduler(LIMIT)
        AHEAD = ThreadPoolExecutor(max_workers=LIMIT.maximum,
                                   thread_name_prefix="ahead")
    if LIMIT is not None and FIELD_PARALLEL < LIMIT.maximum:
        log.info("llm limit: EXTRACT_FIELD_PARALLEL=%d opens fewer field "
                 "requests than EXTRACT_LIMIT_MAX=%d allows", FIELD_PARALLEL,
                 LIMIT.maximum)


def start_fixed_limit(requests: int) -> None:
    """The run's one queue (`SCHEDULER`), with a limit of *requests* open at
    once that does not move: a probe's places (owner decision 2026-11-07,
    the places count requests with the model, not the conversations open,
    so one that waits for its search holds none). Every client made after
    this sends through it (`_client`)."""
    global LIMIT, SCHEDULER
    from . import throttle
    LIMIT = throttle.AdaptiveLimit(start=requests, minimum=requests,
                                   maximum=requests)
    SCHEDULER = scheduler.Scheduler(LIMIT)


class PromptCounter:
    """The prompt of a request counted with the served model's own tokenizer.

    The text of every message goes through the model's chat template with the
    settings every request carries (`request_extras`) and is counted exactly;
    a crop is counted at IMAGE_TOKENS, the most one can take. The estimate
    this replaces ran short on tables of figures, where the tokenizer gives
    every digit a token of its own: requests went out one token over the
    window and were refused, and a refused request that carried a crop broke
    the server's multimodal cache (vLLM before 0.28, CVE-2026-105753).
    """

    def __init__(self, tokenizer):
        self._tokenizer = tokenizer
        # One tokenizer for every thread, and a fast tokenizer is not safe to
        # share between threads that encode at once.
        self._lock = threading.Lock()

    def __call__(self, system: str, conversation: list) -> int:
        messages, images = [{"role": "system", "content": system or ""}], 0
        for message in conversation:
            content = message.get("content")
            if not isinstance(content, str):
                texts = []
                for part in content or ():
                    if part.get("type") == "image_url":
                        images += 1
                    else:
                        texts.append(part.get("text") or "")
                # One newline more per part than the template joins with:
                # counted high, never short.
                content = "\n".join(texts)
            messages.append({"role": message.get("role", "user"),
                             "content": content})
        kwargs = request_extras().get("chat_template_kwargs") or {}
        with self._lock:
            text = self._tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True,
                **kwargs)
            ids = self._tokenizer.encode(text, add_special_tokens=False)
        return len(ids) + images * IMAGE_TOKENS


# Set by `start_counting` for the run; None counts by estimate.
PROMPT_COUNTER: Optional[PromptCounter] = None


def start_counting(model: Optional[str] = None) -> None:
    """Count every prompt of the run with the served model's tokenizer.

    For a server of one's own, whose tokenizer lies in the local model cache.
    A hosted API's tokenizer is its own and a recorded run sends nothing;
    both keep the estimate. A tokenizer that cannot be loaded ends the run
    here, before the first request, and not as refusals hours into it.
    """
    global PROMPT_COUNTER
    if PROMPT_COUNTER is not None or providers.replaying() or providers.hosted("llm"):
        return
    from transformers import AutoTokenizer
    name = model or LLM_MODEL
    try:
        PROMPT_COUNTER = PromptCounter(AutoTokenizer.from_pretrained(name))
    except Exception as exc:
        raise RuntimeError(
            f"the tokenizer of {name} could not be loaded, and every request "
            f"is sized with it: {exc}\n  it is read from the model cache "
            f"(HF_HOME) the server loads the model from") from exc
    log.info("prompt tokens: counted with the tokenizer of %s", name)


def prompt_tokens(system: str, conversation: list) -> int:
    """What a request's system prompt, messages and crops take.

    Counted before sending, so a request is sized to the window instead of
    shrunk after the server refused it. vLLM's refusal names only a lower
    bound ("at least N input tokens" is the window minus the requested answer,
    plus one), and reading that as the prompt shrank the answer by 33 tokens
    per attempt until the coordinates were written off. With the model's
    tokenizer (`start_counting`) the text is counted exactly; without one it
    is estimated high.
    """
    if PROMPT_COUNTER is not None:
        return PROMPT_COUNTER(system, conversation)
    chars, images = len(system or ""), 0
    for message in conversation:
        content = message.get("content")
        if isinstance(content, str):
            chars += len(content)
            continue
        for part in content or ():
            if part.get("type") == "image_url":
                images += 1
            else:
                chars += len(part.get("text") or "")
    return (int(chars / PROMPT_CHARS_PER_TOKEN) + images * IMAGE_TOKENS
            + 16 * (len(conversation) + 1))


def answer_room(system: str, conversation: list, wanted: int) -> int:
    """max_tokens for this request: *wanted*, or what the window leaves."""
    return min(int(wanted), MAX_MODEL_LEN - ANSWER_MARGIN
               - prompt_tokens(system, conversation))


def make_page_count(db_path: Optional[Path]) -> Callable:
    """document_id -> its page count in the catalog, None where unknown."""
    def pages(document_id: int) -> Optional[int]:
        if db_path is None:
            return None
        try:
            conn = sqlite3.connect(readonly_uri(db_path), uri=True)
            try:
                row = conn.execute("SELECT num_pages FROM Documents "
                                   "WHERE id = ?", (document_id,)).fetchone()
            finally:
                conn.close()
        except sqlite3.Error:
            return None
        return int(row[0]) if row and row[0] else None
    return pages


# Where a prompt shows the reply its request asks for (`system_text`).
EXAMPLE_PLACE = "example"


def system_text(prompt, example: Optional[dict]) -> str:
    """The system prompt one request sends: the prompt with its example
    reply ({{example}}) written for this request, as one line of JSON (owner
    decisions 2026-11-06: every request's example shows exactly the
    coordinates it asks, each read, so the model has no key to leave out). A
    prompt without that place is sent as it is written; one with it and no
    example is an error before anything is sent, as every open placeholder
    is (`prompts.Prompt.render`)."""
    if EXAMPLE_PLACE not in getattr(prompt, "placeholders", ()):
        return prompt.text
    if example is None:
        raise KeyError(f"{prompt.id}: the prompt shows the reply of its "
                       f"request and the request gave no example")
    return prompt.render(**{EXAMPLE_PLACE: json.dumps(
        example, ensure_ascii=False, separators=(",", ":"))})


def ask_in_grammar(client, prompt, conversation: list, shape: dict,
                   document_id: int, where: str, key: str,
                   example: Optional[dict] = None,
                   thread: Optional[thread_map.Thread] = None, **noted):
    """One request of the rebuilt harvest: the reply as a dict, "cut_off"
    when it did not fit its room, or None when it could not be read. The
    prompt shows *example*, the reply this request asks for
    (`system_text`).

    With *thread* the request is one message of a conversation (owner
    decisions 2026-11-07): a follow-up is sent under the system prompt the
    conversation began with, and the answer that stands is kept in it with
    every message sent, so the next follow-up goes after it
    (`thread.Thread`).

    Asked again with the cause when the reply is no JSON object, or one
    without a key its schema requires (`_lacking`), as every request of the
    stage is; a reply cut off at its limit is not rescued. Each answer is
    traced as `<where>_ask` with *noted*.

    A request whose last attempt ended on a 429, a 5xx or a timeout was
    never answered, so its document is noted (`UNSERVED`) and goes
    unstamped, as for every request of the run. One that timed out is asked
    again with the time a repeat gets (`_repeating`), whatever client it was
    handed, as every request of the harvest is.
    """
    client = _repeating(client)
    temperature = float(prompt.meta.get("temperature", 0))
    max_tokens = int(prompt.meta.get("max_tokens", 4096))
    text = (thread.system if thread is not None and thread.begun
            else system_text(prompt, example))
    failures = Failures(document_id)
    faults = 0
    for attempt in range(1, MAX_RETRIES + 1):
        limit = answer_room(text, conversation, max_tokens)
        if limit < MIN_ANSWER_TOKENS:
            return "cut_off"
        started = time.time()
        try:
            with _for(document_id):
                response = client.chat.completions.create(
                    model=LLM_MODEL,
                    temperature=retry_temperature(temperature, faults),
                    max_tokens=limit,
                    messages=[{"role": "system", "content": text},
                              *conversation],
                    response_format=shape,
                    extra_body=request_extras())
            failures.answered()
            reply = response.choices[0]
            usage = getattr(response, "usage", None)
            _observe_usage(usage)
            trace.event(f"{where}_ask", document_id, attempt=attempt,
                        ms=int((time.time() - started) * 1000),
                        prompt_tokens=getattr(usage, "prompt_tokens", None),
                        completion_tokens=getattr(usage, "completion_tokens",
                                                  None), **noted)
            answer = _loads_object(reply.message.content)
            lacking = _lacking(answer, shape)
            if isinstance(answer, dict) and lacking is None:
                if thread is not None:
                    thread.system = text
                    thread.messages = [
                        *conversation,
                        {"role": "assistant",
                         "content": reply.message.content or ""}]
                return answer
            faults += 1
            cause, correction = _reply_fault(reply, limit,
                                             key=lacking or key)
            trace.event("error", document_id, where=where,
                        kind="unreadable", cause=cause, attempt=attempt)
            if cause == "cut_off":
                return "cut_off"
            conversation = conversation + [
                {"role": "assistant", "content": reply.message.content or ""},
                {"role": "user", "content": correction}]
        except Exception as exc:
            log.warning("   %s %s attempt %d failed: %s", where, document_id,
                        attempt, exc)
            trace.event("error", document_id, where=where, kind="exception",
                        attempt=attempt, detail=str(exc)[:300])
            if not failures.failed(exc):
                return None
        if attempt < MAX_RETRIES:
            failures.wait(attempt)
    failures.given_up()
    return None


# The fields each prompt's follow-ups carry, whose words its file must hold
# (`thread.cut`, owner decisions 2026-11-07): a run whose prompt lacks them
# stops at its start (`surveyed_flow`).
FOLLOWS = {
    reading_map.READ_VALUES_PROMPT_ID: reading_map.VALUE_FOLLOWS,
    reading_map.READ_TEXT_PROMPT_ID: reading_map.TEXT_FOLLOWS,
    combing_map.COMB_PROMPT_ID: combing_map.FOLLOWS,
    reading_map.CHECK_PROMPT_ID: reading_map.CHECK_FOLLOWS,
    survey_map.SURVEY_PROMPT_ID: survey_map.FOLLOWS,
    years_map.YEARS_PROMPT_ID: years_map.FOLLOWS,
    settings_map.SETTINGS_PROMPT_ID: settings_map.FOLLOWS,
    seeking_map.SEEK_PROMPT_ID: seeking_map.FOLLOWS,
    naming_map.NAMING_PROMPT_ID: naming_map.FOLLOWS,
    naming_map.GROUPS_PROMPT_ID: naming_map.FOLLOWS,
    naming_map.SEVERAL_PROMPT_ID: naming_map.FOLLOWS,
    computing.COMPUTE_PROMPT_ID: computing.FOLLOWS,
}


def parts_of(prompt_id: str, spec: Optional[Spec] = None, profile=None):
    """The prompt *prompt_id* cut at its parts (`thread.cut`): with *spec*,
    the reading's groups must each have theirs, and every field its
    follow-ups carry (`FOLLOWS`) its words. LookupError where it does not
    fit."""
    prompt = prompts.load(prompt_id, profile)
    groups = (spec.groups.values() if spec is not None
              and prompt_id == reading_map.READ_TEXT_PROMPT_ID else None)
    return thread_map.cut(prompt, groups, follows=FOLLOWS.get(prompt_id, ()))


def threaded(parts, thread, payload: Optional[dict] = None,
             follow: Optional[dict] = None, content=None,
             example: Optional[dict] = None) -> tuple:
    """(prompt, conversation) of one message of *thread* (owner decisions
    2026-11-07): a follow-up (*follow*) goes after the answer that stands,
    in the words of the parts its fields need, with the reply the request
    asks for (*example*) where they show one; a first message shows
    *payload* (as *content* where given, such as a figure with its crop)
    under the system prompt of what every request of its kind is told and
    the part of each field it carries."""
    if follow is not None:
        return parts.prompt, thread.then(parts.follow_up(follow, example))
    thread.first = payload
    if content is None:
        content = json.dumps(payload, ensure_ascii=False, indent=2)
    return parts.system(payload), [{"role": "user", "content": content}]


def told(follow: Optional[dict]) -> int:
    """How many corrections a follow-up carries, for the trace."""
    return len((follow or {}).get(thread_map.CORRECTIONS) or ())


def worded(words: str, payload: dict) -> str:
    """A message: its words, then what it shows as JSON."""
    data = json.dumps(payload, ensure_ascii=False, indent=2)
    return f"{words}\n\n{data}" if words else data


def answers_in(thread) -> int:
    """How many answers a conversation holds."""
    return sum(1 for message in thread.messages
               if message.get("role") == "assistant")


def shows_in_full(thread, parameter) -> bool:
    """Has a message of this conversation shown *parameter* with its full
    definition? A coordinate that classifies is shown it once, with the
    first of them that is asked (owner decision 2026-11-07: one coordinate
    per message)."""
    wanted = json.dumps(parameter.description, ensure_ascii=False)[1:-1]
    for message in thread.messages:
        if message.get("role") != "user":
            continue
        content = message.get("content")
        texts = [content] if isinstance(content, str) else [
            part.get("text", "") for part in content or ()
            if isinstance(part, dict)]
        if any(wanted in (text or "") for text in texts):
            return True
    return False


def make_reader(spec: Spec, image_root: Optional[Path] = None):
    """The reading of one parameter's passages (`reading.Reader`), or None
    when the profile writes no prompts for it or its spec names no groups.
    Two kinds of request, each with one task and one value (owner decisions
    2026-11-04 and 2026-11-05), each a message of a conversation (owner
    decisions 2026-11-07, `thread.py`): the values of a passage, the next
    one after each answer, and one value's coordinates, one coordinate per
    message with the words of its group (`thread.Parts.group`). A system
    prompt holds what its kind of request is told and the part of each
    field its first message carries. A figure goes with its crop, in the
    first message, and a value only the crop shows is read off it (owner
    decisions 2026-11-05 and 2026-11-07). Neither request has tools (owner
    decision 2026-11-05, ticket 26)."""
    if not spec.groups:
        return None
    try:
        values_parts = parts_of(reading_map.READ_VALUES_PROMPT_ID)
        text_parts = parts_of(reading_map.READ_TEXT_PROMPT_ID, spec)
    except (FileNotFoundError, LookupError):
        return None
    client = _client()
    frame_slots = frame_slots_of(spec)
    from docpipe.profile import active_profile
    states = year_states_of(active_profile())

    def document_of(source) -> int:
        return int((source.provenance or {}).get("document_id") or 0)

    def image_of(source) -> Optional[dict]:
        """The crop that goes with a request about *source*: a figure's, or
        None."""
        if source.owner_kind == "figure" and source.image_path \
                and ATTACH_IMAGES:
            return _image_part(str(image_root / source.image_path)
                               if image_root else source.image_path)
        return None

    def drawn(source) -> bool:
        """Does a request about *source* send a figure's image, so a value
        only the image shows is read off it?"""
        return image_of(source) is not None

    def content_of(source, text: str):
        """The user message of a request about *source*: its payload, and a
        figure's crop beside it."""
        part = image_of(source)
        if part is not None:
            return [{"type": "text", "text": text}, part]
        return text

    def ask_values(source, parameter, context, read, thread, follow=None,
                   drawn=False):
        # The first message shows the passage; what follows an answer is the
        # ask for the next value or a correction (owner decisions
        # 2026-11-07).
        example = reading_map.values_example(parameter, drawn)
        if thread.begun:
            prompt = values_parts.prompt
            conversation = thread.then(values_parts.follow_up(follow,
                                                              example))
        else:
            payload = reading_map.values_payload(source, parameter, context,
                                                 read, drawn)
            prompt = values_parts.system(payload)
            conversation = [{"role": "user", "content": content_of(
                source, json.dumps(payload, ensure_ascii=False, indent=2))}]
        return ask_in_grammar(
            client, prompt, conversation,
            reading_map.values_response_format(parameter, drawn),
            document_of(source), "read_values", "value", example=example,
            thread=thread, parameter=parameter.uri, kind=source.owner_kind,
            owner=source.owner_id, round=answers_in(thread) + 1,
            corrections=told(follow))

    def ask_text(source, parameter, group, slots, row, context, thread,
                 follow=None):
        # The first message of a value's conversation shows the passage and
        # the value with its first coordinate in the words of its group;
        # each next coordinate is a message of its own; a correction follows
        # the answer it is about (owner decisions 2026-11-07).
        example = reading_map.text_example(slots)
        if follow is not None:
            prompt = text_parts.prompt
            conversation = thread.then(text_parts.follow_up(follow, example))
        elif thread.begun:
            payload = reading_map.group_payload(
                parameter, slots, group.where, context,
                full=group.full_definition and not shows_in_full(
                    thread, parameter))
            prompt = text_parts.prompt
            conversation = thread.then(worded(
                text_parts.group(group.name, example), payload))
        else:
            payload = reading_map.text_payload(
                source, parameter, slots, row, group.where, context,
                full=group.full_definition)
            thread.first = payload
            prompt = text_parts.system(payload)
            conversation = [{"role": "user", "content": content_of(
                source, worded(text_parts.group(group.name, example),
                               payload))}]
        return ask_in_grammar(
            client, prompt, conversation,
            reading_map.text_response_format(slots), document_of(source),
            "read_text", slots[0].name, example=example, thread=thread,
            parameter=parameter.uri, kind=source.owner_kind,
            owner=source.owner_id,
            group=group.name if group is not None else None,
            value=row.label, corrections=told(follow))

    return reading_map.Reader(
        spec, ask_values, ask_text,
        shown_with=reading_map.heading_of,
        bases=lambda pairs: named_years(pairs, frame_slots, states),
        known=row_context, drawn=drawn, span_marks=span_marks_of(),
        pool=AHEAD, trace=trace.event)


def check_asker(client, parts=None) -> Optional[Callable]:
    """The request that asks of a find whether the place it was quoted from
    speaks about its value (`reading.Judge`, owner decisions 2026-11-07),
    the same for a find of the second reading and one of the combing; None
    where the profile writes no prompt for it. *parts* is the prompt cut at
    its parts where the caller has it."""
    if parts is None:
        try:
            parts = parts_of(reading_map.CHECK_PROMPT_ID)
        except (FileNotFoundError, LookupError):
            return None

    def check(payload, shape, document_id, source, group=None, example=None,
              thread=None, follow=None):
        # A find quoted from a passage the value's own request did not show:
        # does that place speak about the value?
        thread = thread if thread is not None else thread_map.Thread()
        prompt, conversation = threaded(parts, thread, payload, follow,
                                        example=example)
        return ask_in_grammar(
            client, prompt, conversation, shape, document_id, "comb_check",
            "about", example=example, thread=thread,
            parameter=thread.first["parameter"]["key"],
            kind=source.owner_kind, owner=source.owner_id, group=group,
            corrections=told(follow))
    return check


def make_namer(spec: Spec, passages_of: Callable) -> Optional[Callable]:
    """The requests that ask which of a document's names mean the same
    thing once it is folded (`naming.Namer`, owner decisions 2026-11-06):
    `name(report)`, which marks the report's rows. None where the spec
    merges no names or the profile writes no prompt for it, which
    `surveyed_flow` refuses at the start of a run. *passages_of(document_id)*
    is the plan's passages in their order. The names are embedded with the
    run's embedding model (`COALESCED`)."""
    if not naming_map.merges(spec):
        return None
    try:
        groups_parts, parts, several_parts = (
            parts_of(prompt_id) for prompt_id in naming_map.NAMING_PROMPT_IDS)
    except (FileNotFoundError, LookupError):
        return None
    client = _client()

    def ask_groups(payload, shape, document_id, kind, example=None,
                   thread=None, follow=None):
        # The candidates (owner decision 2026-11-06): every name with its
        # quote, the groups that may name one thing; what was wrong follows
        # the answer (owner decisions 2026-11-07).
        thread = thread if thread is not None else thread_map.Thread()
        prompt, conversation = threaded(groups_parts, thread, payload,
                                        follow, example=example)
        return ask_in_grammar(
            client, prompt, conversation, shape, document_id,
            "naming_groups", naming_map.GROUPS, example=example,
            thread=thread, kind=kind, names=len(payload["names"]),
            corrections=told(follow))

    def ask(payload, shape, document_id, kind, example=None, thread=None,
            follow=None):
        # One request per name (owner decision 2026-11-06): the name asked
        # with its places, its candidates with their quotes.
        thread = thread if thread is not None else thread_map.Thread()
        prompt, conversation = threaded(parts, thread, payload, follow,
                                        example=example)
        return ask_in_grammar(
            client, prompt, conversation, shape, document_id, "naming",
            naming_map.MEANT, example=example, thread=thread, kind=kind,
            names=len(payload["names"]),
            places=len(payload["name"]["places"]), corrections=told(follow))

    def ask_several(payload, shape, document_id, kind, example=None,
                    thread=None, follow=None):
        # One request per wording of several things and document (owner
        # decision 2026-11-07): the words with their places, every thing of
        # the document with its quote.
        thread = thread if thread is not None else thread_map.Thread()
        prompt, conversation = threaded(several_parts, thread, payload,
                                        follow, example=example)
        return ask_in_grammar(
            client, prompt, conversation, shape, document_id,
            "naming_several", naming_map.MEANT, example=example,
            thread=thread, kind=kind, names=len(payload["names"]),
            places=len(payload["group"]["places"]), corrections=told(follow))

    def embed(texts: list) -> list:
        return COALESCED.embed([{"text": text} for text in texts])
    namer = naming_map.Namer(spec, ask, trace=trace.event, pool=AHEAD,
                             ask_groups=ask_groups, embed=embed,
                             ask_several=ask_several)

    def name(report) -> None:
        passages = {(s.owner_kind, s.owner_id): s
                    for s in passages_of(report.document_id)}
        namer(report.document_id, report.tuples, passages)
    return name


def make_comber(spec: Spec, rank: Callable, seek: Optional[Callable] = None):
    """The search for what the reading left open (`combing.Comber`), or None
    when the profile writes no prompt for it or its spec names no groups.
    *rank(document_id, probes, exclude)* is the plan's passages best first
    for the search sentences, `make_more_sources` in a harvest. *seek* is
    the sought search's sentences (`make_seek_probes`)."""
    if not spec.groups:
        return None
    try:
        comb_parts, check_parts = (parts_of(prompt_id) for prompt_id in
                                   (combing_map.COMB_PROMPT_ID,
                                    reading_map.CHECK_PROMPT_ID))
    except (FileNotFoundError, LookupError):
        return None
    client = _client()
    frame_slots = frame_slots_of(spec)
    from docpipe.profile import active_profile
    states = year_states_of(active_profile())

    def ask(payload, shape, document_id, source, group=None, example=None,
            thread=None, follow=None):
        # The rounds of one value's search are one conversation, each later
        # message what is new since the answer before (owner decisions
        # 2026-11-07).
        thread = thread if thread is not None else thread_map.Thread()
        prompt, conversation = threaded(comb_parts, thread, payload, follow,
                                        example=example)
        return ask_in_grammar(
            client, prompt, conversation, shape, document_id, "comb", "rows",
            example=example, thread=thread,
            parameter=thread.first["parameter"]["key"],
            kind=source.owner_kind, owner=source.owner_id, group=group,
            round=answers_in(thread) + 1, corrections=told(follow))

    comber = combing_map.Comber(
        spec, ask, rank, row_context,
        bases=lambda pairs: named_years(pairs, frame_slots, states),
        pool=AHEAD, trace=trace.event,
        check=check_asker(client, check_parts), span_marks=span_marks_of())
    # The sentences the search for a parameter the survey named no passage
    # for ranks with (`make_seek_probes`); None searches with its label.
    comber.seek = seek
    return comber


def frame_slots_of(spec: Spec) -> list:
    """The coordinates of the plan's frame, which its base and target years
    date a value by: the pair of each group the survey reads, and of a group
    the reading reads that names one (`spec.Group.paired`)."""
    return [slot for group in spec.groups.values()
            if group.read_in == "survey" or group.pair
            for slot in fields.frame_slots(spec, group.paired)]


def survey_slots_of(spec: Spec) -> list:
    """The coordinates the survey reads per passage: the pair of each group
    it reads; none where the reading asks every coordinate per value."""
    return [slot for group in spec.groups_read_in("survey")
            for slot in fields.frame_slots(spec, group.paired)]


def dates_by_plan(spec: Spec) -> bool:
    """Does the spec date a value by the plan's own years: has its frame a
    year?"""
    return any(slot.kind == fields.NUMBER for slot in frame_slots_of(spec))


def make_years(spec: Spec, rank: Optional[Callable] = None):
    """The request for a plan's base and target years, once per plan
    (`years.PlanYears`, owner decision 2026-11-06), or None where the spec's
    frame has no year or the profile writes no prompt for it. *rank* is the
    plan best first for a sentence the model writes ("similar")."""
    if not dates_by_plan(spec):
        return None
    try:
        parts = parts_of(years_map.YEARS_PROMPT_ID)
    except (FileNotFoundError, LookupError):
        return None
    client = _client()
    from docpipe.profile import active_profile
    states = year_states_of(active_profile())

    def ask(payload, document_id, thread=None, follow=None):
        # The rounds are one conversation, each later message what is new
        # since the answer before (owner decisions 2026-11-07).
        thread = thread if thread is not None else thread_map.Thread()
        example = years_map.example()
        prompt, conversation = threaded(parts, thread, payload, follow,
                                        example=example)
        return ask_in_grammar(
            client, prompt, conversation, years_map.response_format(),
            document_id, "years", "base_years", example=example,
            thread=thread, round=answers_in(thread) + 1,
            corrections=told(follow))
    return years_map.PlanYears(ask, frame_slots_of(spec), states, rank=rank,
                               trace=trace.event)


def make_settings(spec: Spec, rank: Optional[Callable] = None):
    """The request for what a plan settles for all its values, once per plan
    (`settings.PlanSettings`, owner decision 2026-11-07), or None where the
    profile writes no prompt for it. *rank* is the plan best first for a
    sentence the model writes ("similar")."""
    try:
        parts = parts_of(settings_map.SETTINGS_PROMPT_ID)
    except (FileNotFoundError, LookupError):
        return None
    client = _client()

    def ask(payload, document_id, thread=None, follow=None):
        # The rounds are one conversation, each later message what is new
        # since the answer before (owner decisions 2026-11-07).
        thread = thread if thread is not None else thread_map.Thread()
        example = settings_map.example()
        prompt, conversation = threaded(parts, thread, payload, follow,
                                        example=example)
        return ask_in_grammar(
            client, prompt, conversation, settings_map.response_format(),
            document_id, "settings", "settings", example=example,
            thread=thread, round=answers_in(thread) + 1,
            corrections=told(follow))
    return settings_map.PlanSettings(ask, rank=rank, trace=trace.event)


def make_seeker(spec: Spec, rank: Optional[Callable] = None):
    """The model's own search for a parameter whose walk down its list read
    no value (`seeking.FreeSearch`, owner decision 2026-11-07), or None
    where the profile writes no prompt for it. *rank* is the plan best first
    for a sentence the model writes ("similar")."""
    try:
        parts = parts_of(seeking_map.SEEK_PROMPT_ID)
    except (FileNotFoundError, LookupError):
        return None
    client = _client()

    def ask(payload, document_id, thread=None, follow=None):
        # The rounds are one conversation, each later message what is new
        # since the answer before (owner decisions 2026-11-07).
        thread = thread if thread is not None else thread_map.Thread()
        example = seeking_map.example()
        prompt, conversation = threaded(parts, thread, payload, follow,
                                        example=example)
        return ask_in_grammar(
            client, prompt, conversation, seeking_map.response_format(),
            document_id, "seek_free", "places", example=example,
            thread=thread, parameter=thread.first["parameter"]["key"],
            round=answers_in(thread) + 1, corrections=told(follow))
    return seeking_map.FreeSearch(ask, rank=rank, trace=trace.event)


def title_line(passages: list, name: Optional[str],
               pages: tuple = (1, 2)) -> Optional[Source]:
    """The first line of the plan's first page, else its second, that names
    *name*, the place the plan is about, as a passage a quote may stand in
    (owner decision 2026-11-06: every reading request shows it). None where
    no such line stands there, or no name is known."""
    if not name or not name.strip():
        return None
    wanted = flat_text(name).casefold()
    for page in pages:
        for source in passages:
            if (source.provenance or {}).get("page") != page:
                continue
            for line in (source.text or "").splitlines():
                if wanted in flat_text(line).casefold():
                    return replace(source, text=line.strip(), body=None)
    return None


def make_title_page(db_path: Optional[Path], profile) -> Optional[Callable]:
    """title_page(document_id, passages): the line of the title page that
    names the plan's own place (`title_line`), its name from the profile's
    `document_context`; None where the profile does not show it
    (`TITLE_PAGE_LINE`)."""
    if profile is None or not profile.component("extraction",
                                                "TITLE_PAGE_LINE"):
        return None
    context_of = document_context_of(db_path, profile.component(
        "extraction", "document_context"))

    def title_page(document_id: int, passages: list) -> Optional[Source]:
        return title_line(passages, context_of(document_id).get("name"))
    return title_page


def make_survey(db_path: Optional[Path], spec: Spec, out: Path,
                content: Optional[Callable] = None,
                every: Optional[Callable] = None,
                image_root: Optional[Path] = None, scope: str = ""):
    """The survey of whole plans (`survey.Survey`), or None when the profile
    writes no prompt for it or its spec names no groups. *every* is
    (document, exclude) -> passages, read from *db_path* when not given.
    Each request shows one passage, a figure with its crop beside the text
    as the reading shows it. *scope* names a survey of part of a plan, kept
    beside the whole one's."""
    if not spec.groups:
        return None
    try:
        parts = parts_of(survey_map.SURVEY_PROMPT_ID)
    except (FileNotFoundError, LookupError):
        return None
    client = _client()
    parameters = survey_map.parameters_of(spec)
    groups = survey_map.groups_shown(spec)
    slots = survey_map.tuple_slots(spec)
    every = every or make_rest_of_document(db_path, content=content)

    def content_of(context: list, body: dict):
        text = json.dumps(body, ensure_ascii=False, indent=2)
        source = survey_map.one_passage(context)
        if source.owner_kind == "figure" and source.image_path \
                and ATTACH_IMAGES:
            part = _image_part(str(image_root / source.image_path)
                               if image_root else source.image_path)
            if part is not None:
                return [{"type": "text", "text": text}, part]
        return text

    def ask(context: list, document_id: int, thread=None, follow=None):
        # What was wrong follows the answer (owner decisions 2026-11-07); a
        # figure goes with its crop in the first message.
        thread = thread if thread is not None else thread_map.Thread()
        body = (survey_map.payload(context, parameters, groups)
                if follow is None else None)
        example = survey_map.example(slots)
        prompt, conversation = threaded(
            parts, thread, body, follow,
            content=content_of(context, body) if body is not None else None,
            example=example)
        return ask_in_grammar(
            client, prompt, conversation,
            survey_map.response_format(parameters, slots),
            document_id, "survey", "parameters", example=example,
            thread=thread,
            passages=len(context), corrections=told(follow),
            figure=any(s.owner_kind == "figure" for s in context))

    key = survey_map.key_of(parts.prompt.text, parameters, groups,
                            LLM_MODEL)
    log.info("survey%s: one per plan over %d parameter(s) and the group(s) "
             "%s, kept in %s", f" ({scope})" if scope else "",
             len(parameters), ", ".join(groups) or "-", Path(out) / "survey")
    return survey_map.Survey(
        ask, lambda document_id: every(document_id, set()),
        make_page_count(db_path), parameters, slots, frame_pairs, key,
        store=Path(out) / "survey", scope=scope, pool=AHEAD,
        trace=trace.event)


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

    *rejected* collects one sentence per pair that did not get through, to be
    put back in front of the model. Silently dropping them is
    how a plan ended up with a scenario the ontology has no class for: the
    pair was refused, nobody said so, and the next window was asked the same
    question in the same way.
    """
    from .pipeline import answer_in_quote, option_named, year_in_range
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
                refuse(say("frame_missing", slot=slot.name))
                break
            quote = entry.get(f"{slot.name}_quote")
            if not isinstance(quote, str) or not quote.strip():
                refuse(say("frame_no_quote", slot=slot.name,
                                   given=given))
                break
            named = entry.get(f"{slot.name}_source")
            found = where.get(str(named))
            if found is None or not quote_in(found.text or "", quote):
                found = next((s for s in sources
                              if quote_in(s.text or "", quote)), None)
            if found is None:
                refuse(say("frame_quote_not_in_source",
                                   slot=slot.name, given=given,
                                   quote=quote.strip()[:80]))
                break
            wording = entry.get(f"{slot.name}_raw")
            wording = wording.strip() if isinstance(wording, str) else None
            if not answer_in_quote(slot, given, wording, quote):
                refuse(say("frame_answer_not_in_quote",
                                   slot=slot.name, given=given,
                                   quote=quote.strip()[:80]))
                break
            if slot.kind == fields.CHOICE and slot.options \
                    and option_named(slot, given) is None:
                # An answer that is not on the closed list. It used to be
                # taken as long as its wording stood in the quote, and the
                # class lookup behind it then came back empty -- 8,944 of
                # one corpus run's tuples carried an unmapped label for
                # exactly this reason. Asked again instead, and told which
                # list.
                refuse(say("frame_not_an_option", given=given,
                           slot=slot.name,
                           options=say("frame_options", slot=slot.name)))
                break
            if slot.kind == fields.NUMBER:
                try:
                    given = int(str(given).strip())
                except (TypeError, ValueError):
                    refuse(say("frame_not_a_year",
                                       slot=slot.name, given=given))
                    break
                if not year_in_range(given):
                    refuse(say("frame_not_a_year",
                                       slot=slot.name, given=given))
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


# ---------------------------------------------------------------------------
# Harvest: one source + one parameter -> the model's claimed tuples
# ---------------------------------------------------------------------------

# Seconds without any answer from the server before the run ends. A request
# that finds the server gone fails, waits and asks again, and a batch counts
# as unreachable only once every one of its requests has given up: when vLLM
# died on the first corpus run with the adaptive limit, the runner took 78
# minutes to notice.
SERVER_DEAD_AFTER = float(os.environ.get("EXTRACT_SERVER_DEAD_AFTER", "180"))
SERVER_PROBE_EVERY = 15.0


def probe_server(base_url: str = None, timeout: float = 10.0) -> bool:
    """Whether the server answers `GET {base_url}/models` at all.

    Any reply below 500 counts: a server that refuses the key is still there.
    """
    import urllib.error
    import urllib.request
    request = urllib.request.Request((base_url or LLM_BASE_URL).rstrip("/")
                                     + "/models")
    if LLM_API_KEY:
        request.add_header("Authorization", f"Bearer {LLM_API_KEY}")
    try:
        with urllib.request.urlopen(request, timeout=timeout):
            return True
    except urllib.error.HTTPError as exc:
        return exc.code < 500
    except Exception:
        return False


def watch_server(on_dead: Callable, *, probe: Callable = probe_server,
                 every: float = SERVER_PROBE_EVERY,
                 dead_after: float = SERVER_DEAD_AFTER,
                 clock: Callable = time.monotonic,
                 sleep: Callable = time.sleep) -> threading.Thread:
    """A daemon thread that calls *on_dead(seconds)* once the server has not
    answered for *dead_after* seconds, then stops watching."""

    def watch() -> None:
        silent_since = None
        while True:
            sleep(every)
            if probe():
                silent_since = None
                continue
            now = clock()
            if silent_since is None:
                silent_since = now
                log.warning("extraction: the model server did not answer the "
                            "health probe")
            elif now - silent_since >= dead_after:
                on_dead(now - silent_since)
                return

    thread = threading.Thread(target=watch, name="server-watch", daemon=True)
    thread.start()
    return thread


_SHARED_HTTP = None
_SHARED_HTTP_LOCK = threading.Lock()


def shared_http(limit=None):
    """The one connection pool every request of the run goes out through.

    Each kind of request has a client of its own (reading, combing, the
    check, the years, ...), and each client used to keep a pool of its own:
    connections it had opened stayed open while it sent nothing, so a probe
    with 18 requests in flight held 40 connections to the proxy, and a server
    that takes about 20 at once refused the rest outright (one probe,
    1,110 requests refused). One pool for all, as large as the requests the
    run may have open at once (*limit*, the run's `LIMIT`), holds no more
    connections than requests in flight. Made once, with the first client.
    """
    global _SHARED_HTTP
    with _SHARED_HTTP_LOCK:
        if _SHARED_HTTP is None:
            import httpx
            most = getattr(limit if limit is not None else LIMIT,
                           "maximum", None)
            _SHARED_HTTP = httpx.Client(
                limits=httpx.Limits(max_connections=most,
                                    max_keepalive_connections=most),
                timeout=LLM_TIMEOUT)
        return _SHARED_HTTP


def _client():
    """The one client shape this stage uses, for the provider it is set to.
    A request that timed out is repeated with the time of a repeat
    (`_repeating`). Every client of the run sends through one connection
    pool (`shared_http`)."""
    shared = ({"http_client": shared_http()}
              if providers.provider("llm") == providers.OPENAI_COMPATIBLE
              else {})
    client = providers.client("llm", base_url=LLM_BASE_URL,
                              api_key=LLM_API_KEY, timeout=LLM_TIMEOUT,
                              max_retries=0, **shared)
    if SCHEDULER is None:
        # Several model names on one endpoint share their places as the chat's
        # do. One model and one place is the plain client.
        from ..inference import pool
        return _repeating(pool.over(client))
    return _repeating(scheduler.Scheduled(client, SCHEDULER))


def _repeating(client):
    """*client*, whose repeat of a request that timed out gets
    `RETRY_TIMEOUT` (`scheduler.Repeats`): every request of the stage, made
    here or handed in."""
    return scheduler.repeating(client, RETRY_TIMEOUT, LLM_TIMEOUT)


def _for(document_id):
    """The requests sent inside belong to this document; the sweep's ticket,
    if the calling thread carries one, stays."""
    return scheduler.on_behalf(document_id, scheduler.current()[1])


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


_DECODER = json.JSONDecoder()


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


def _shape_rule() -> str:
    """What has to be said back whatever went wrong: the shape that was
    asked for."""
    return say("shape_rule")


def _lacking(answer, shape: Optional[dict]) -> Optional[str]:
    """The first key the schema of *shape* requires at its top that the
    object *answer* lacks; None when it has them all, or is no object.

    Such a reply parses and is still not the object that was asked for, so
    it is asked again as `missing_key` (owner decision 2026-11-04). A server
    that holds a reply to its grammar never sends it; one that holds it to
    no schema sent `{}` for tables full of values, which read as tables
    without any.
    """
    if not isinstance(answer, dict):
        return None
    schema = ((shape or {}).get("json_schema") or {}).get("schema") or {}
    return next((key for key in schema.get("required") or ()
                 if key not in answer), None)


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
    shape = _shape_rule()

    def cut_off() -> tuple:
        return "cut_off", (say("cut_off", limit=limit)
                           + (shorter or say("shorter")))

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
        return "reasoning_only", say("reasoning_only") + shape
    if not text:
        return cut_off() if ran_out else (
            "empty", say("empty") + shape)
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
            return "no_object", say("no_object") + shape
        try:
            _obj, end = _DECODER.raw_decode(text, start)
        except json.JSONDecodeError:
            around = text[max(start, exc.pos - 60):exc.pos + 20]
            return "syntax", say(
                "syntax", position=exc.pos - start, message=exc.msg,
                around=around) + shape
        extra = (text[:start] + text[end:]).strip()
        return "outside_text", say(
            "outside_text", extra=extra[:200]) + shape
    if not isinstance(data, dict):
        return "not_an_object", say(
            "not_an_object", kind=type(data).__name__) + shape
    if key and not isinstance(data.get(key), list):
        which = "key_missing" if key not in data else "key_not_a_list"
        return "missing_key", say(which, key=key) + shape
    return "wrong_shape", say("wrong_shape") + shape


def _parse_action(text) -> Optional[str]:
    """The python the model wants run, or None if it answered instead."""
    obj = _loads_object(text)
    if obj is None or obj.get("action") != "python":
        return None
    code = obj.get("code")
    return code if isinstance(code, str) and code.strip() else None


def _compute_reply(run: dict, done: str = "code_output") -> str:
    """What the model gets back after a sandbox round."""
    if not run.get("ok"):
        return say("code_failed", error=run.get("error")
                           or say("code_error_unknown"))
    out = (run.get("stdout") or "").strip()
    if not out:
        return say("code_silent")
    return say(done, output=out)


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
    token_usage.add(LLM_MODEL, input_tokens=prompt,
                    output_tokens=completion if isinstance(completion, int)
                    else 0,
                    cached_tokens=token_usage.cached_of(usage))
    with _USAGE_LOCK:
        _USAGE["n"] += 1
        _USAGE["prompt_sum"] += prompt
        _USAGE["prompt_max"] = max(_USAGE["prompt_max"], prompt)
        if isinstance(completion, int):
            _USAGE["completion_max"] = max(_USAGE["completion_max"], completion)


def _asked(stage: str, document_id, response, *, attempt: int,
           started: float, **noted) -> None:
    """One request that got a reply, in its document's trace as
    `<stage>_ask` with its attempt, time and tokens. Every request kind
    writes one, and the run's stats count each kind by its stage
    (`stats.from_traces`), so no kind of request goes uncounted (owner
    decision 2026-11-05)."""
    usage = getattr(response, "usage", None)
    trace.event(f"{stage}_ask", document_id, attempt=attempt,
                ms=int((time.time() - started) * 1000),
                prompt_tokens=getattr(usage, "prompt_tokens", None),
                completion_tokens=getattr(usage, "completion_tokens", None),
                **noted)


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


def row_context(claim: dict, asked=()) -> dict:
    """{axis: the plan's wording} of every coordinate this row has READ,
    the ones asked now left out. A derived coordinate is the spec's decision
    and its wording is the unit, so it says nothing about the number."""
    out = {}
    for key in sorted(claim):
        if not key.endswith("_state") or claim[key] != fields.READ:
            continue
        name = key[:-len("_state")]
        raw = claim.get(f"{name}_raw")
        if name in asked or name == fields.UNIT:
            continue
        if isinstance(raw, str) and raw.strip():
            out[name] = raw.strip()
        elif isinstance(claim.get(name), int):
            # A year has no wording where its number stands in the quote, and
            # the scenario read after it has to see it.
            out[name] = str(claim[name])
    return out


def cell_facts(value, quote, own=None, head=None) -> dict:
    """Which cell of the quoted table row a number sits in and the head of
    that column. Three numbers under three year columns share one quote, and
    the column is what tells them apart: a fact already in hand here, so it
    is handed over rather than left to be counted. A number printed in two
    cells has its *head* from its place in its row's list (`with_head`)."""
    cell = pipeline_cell_index(quote, value)
    if cell is None:
        return {"head": head} if head else {}
    facts = {"column": cell[0], "columns": cell[1]}
    if own is not None and own.owner_kind == "table":
        head = column_head(own.text, *cell)
        if head:
            facts["head"] = head
    return facts


def keeps_row(slot, answer, allowed) -> bool:
    """Does this gate answer keep the row in the slice this run serializes?

    The answer is the option's LABEL, because that is what a field reply
    carries and what merge_field writes: "Nutzenergie", not
    "out:useful_energy". The profile names classes, so the label is resolved
    here — reading the profile
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


def _review_payload(row: dict, shown: list, parameter, slots) -> dict:
    """The request body of one review request: one row, its two passages.

    Its own body: the review asks a different question of one row than any
    other request does, and shares nothing of their contract.
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
    if parameter.is_numeric:
        # The second reading names its unit as one entry too: the first
        # reading's is compared by factor, and a wording has none.
        listed["units_accepted"] = sorted(parameter.units_accepted)
    owner = next((s for s in shown
                  if (s.owner_kind, s.owner_id) == (
                      provenance.get("owner_kind"),
                      provenance.get("owner_id"))), None)
    listed.update(cell_facts(listed.get("value"), listed.get("quote"), owner,
                             row.get("head")))
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
                parts.append({"type": "text", "text": say(
                    "image_for", label=f"Q{index + 1}")})
                parts.append(part)
        if len(parts) > 1:
            content = parts
        # A pass over a written harvest: a row it could not read again gets
        # no flag and is read again by the next review (review.py).
        failures = Failures(noted=False)
        conversation: list = [{"role": "user", "content": content}]
        faults = 0
        for attempt in range(1, MAX_RETRIES + 1):
            limit = answer_room(prompt.text, conversation, max_tokens)
            if limit < MIN_ANSWER_TOKENS:
                log.warning("   review: the prompt leaves %d answer token(s) "
                            "in a window of %d -- not sent", limit,
                            MAX_MODEL_LEN)
                break
            started = time.time()
            try:
                response = client.chat.completions.create(
                    model=LLM_MODEL,
                    temperature=retry_temperature(temperature, faults),
                    max_tokens=limit,
                    messages=[{"role": "system", "content": prompt.text},
                              *conversation],
                    extra_body=request_extras(),
                    **providers.formatted("llm", "review_reply",
                                          replies.review(slots)),
                )
                failures.answered()
                reply = response.choices[0]
                _observe_usage(getattr(response, "usage", None))
                _asked("review", (row.get("provenance") or {}).get(
                    "document_id"), response, attempt=attempt,
                    started=started, parameter=getattr(parameter, "uri", None))
                answer = _loads_object(reply.message.content)
                if isinstance(answer, dict):
                    return answer
                # One row and two passages: there is nothing here to split, so
                # a reply that did not fit is told to quote less rather than
                # to answer for fewer rows.
                faults += 1
                cause, correction = _reply_fault(
                    reply, limit, shorter=say("shorter_review"))
                log.warning("   review attempt %d: %s reply%s",
                            attempt, cause, _unparsable(reply))
                conversation.append({"role": "assistant",
                                     "content": reply.message.content or ""})
                conversation.append({"role": "user", "content": correction})
            except Exception as exc:
                log.warning("   review attempt %d failed: %s", attempt, exc)
                if not failures.failed(exc):
                    break
            if attempt < MAX_RETRIES:
                failures.wait(attempt)
        failures.given_up()
        return None

    return ask


def make_completer(profile, db: Optional[Path] = None) -> Optional[Callable]:
    """The step that completes a document's rows from outside the document,
    after its fold and its computing (`profiles/<name>/completion.py:
    complete(report, spec, db=)`, *db* the run's database, for what the
    profile looks up there): `completed(report, spec)`, which adds what it
    found to the report and returns what it came to, traced as `completion`,
    or None where nothing was open. None where the profile has no such step.
    """
    complete = profile.component("completion", "complete")
    if complete is None:
        return None

    def completed(report, spec) -> Optional[dict]:
        outcome = complete(report, spec, db=db)
        if outcome:
            trace.event("completion", report.document_id, **outcome)
        return outcome
    return completed


def make_computer(profile, passages_of: Optional[Callable] = None,
                  pages_of: Optional[Callable] = None,
                  rank: Optional[Callable] = None) -> Optional[Callable]:
    """The step that works out what a document's verified rows leave open
    (`compute.py`): `compute(answered, report, locate=, spec=, stop=)`, which
    folds what it computed into the report and says False if a stop ended it.

    None where it cannot run: the profile names no open question or writes no
    prompt, or the run has no sandbox, since a number the model works out
    itself has no evidence.

    Two questions that come to one statement leave one row: the profile's
    `same` says when two worked-out rows are (owner decision 2026-11-03).

    *passages_of(document_id)* is the plan's passages in their order. With it
    a request has the reading's tools (`reading.Gathered`: the next or the
    previous section, a table or figure by its placeholder, a search by
    pattern or by a sentence), each passage cut to two pages of the plan
    (*pages_of*, `survey.budget_of`), and a question that takes a number
    (`Question.take`) may take it from whatever the request showed: a
    passage, its title, a hit's line or title (owner decision 2026-11-05).
    *rank(document_id, probes, exclude)* is the plan ranked for a sentence,
    which "similar" lists (`make_more_sources` in a run); without it that
    search finds nothing.
    """
    from docpipe.inference import code_exec

    open_questions = profile.component("compute", "questions")
    if open_questions is None or CODE_ROUNDS < 1 or not code_exec.is_enabled():
        return None
    same = profile.component("compute", "same")
    try:
        prompt = prompts.load(computing.COMPUTE_PROMPT_ID)
    except (FileNotFoundError, LookupError):
        return None
    # A prompt that lacks the words of a follow-up stops the run here, not
    # the step quietly.
    parts = thread_map.cut(prompt, follows=computing.FOLLOWS)
    client = _client()
    temperature = float(prompt.meta.get("temperature", 0))
    max_tokens = int(prompt.meta.get("max_tokens", 2048))
    pool = ThreadPoolExecutor(max_workers=FIELD_PARALLEL,
                              thread_name_prefix="compute")

    def ask(question, items: dict, document_id: int, stop,
            check: Optional[Callable] = None) -> tuple:
        """(how it ended, the new row or None, code runs, what it fetched and
        took). The conversation of one question: what it reads of the plan,
        a number it takes, code, its output, the number. *check(question,
        claim)* is why the row's own check refuses a claim, None where it
        takes it."""
        shown = computing.passages(question, items)
        order = list(passages_of(document_id)) if passages_of else []
        passages = {(s.owner_kind, s.owner_id): s for s in order}
        anchor = computing.owner_of(question.anchor)
        gathered = reading_map.Gathered(
            seen={(s.owner_kind, s.owner_id) for s in shown},
            cursor={"next": anchor, "previous": anchor},
            rank=(functools.partial(rank, document_id)
                  if rank is not None else None))
        budget = (survey_map.budget_of(order, pages_of(document_id)
                                       if pages_of else None)
                  if order else None)
        runs: list = []
        noted = {"taken": 0, "untaken": 0, "misquoted": 0, "rejected": 0,
                 "reason": None}
        faults = 0

        # The question is one conversation (owner decisions 2026-11-07):
        # its first message shows what is wanted, the numbers and their
        # passages; what it fetched, a number it took and its code's output
        # follow the answer that asked for them, each with what is new.
        first = {**computing.payload(question, shown, gathered.sources),
                 **gathered.context()}
        system = parts.system(first).text
        conversation = [{"role": "user", "content": json.dumps(
            first, ensure_ascii=False, indent=2)}]
        fetched = {"mark": gathered.mark()}

        def told(said: Optional[str], text: str) -> None:
            conversation.extend(({"role": "assistant", "content": said or ""},
                                 {"role": "user", "content": text}))

        def passage_of(number) -> str:
            source = passages.get(computing.owner_of(number.row))
            if source is None:
                item = computing.item_of(items, number.row)
                source = item.source if item is not None else None
            return (source.text or "") if source is not None else ""

        def ended(outcome: str, claim=None) -> tuple:
            return outcome, claim, runs, {
                "fetched": len(gathered.sources),
                "searched": len(gathered.hits), **noted}

        failures = Failures(document_id)
        # The wait follows the failures, not the rounds: a round of code, of
        # fetching or of taking is no failure.
        failed = 0
        attempt = 0
        while attempt < MAX_RETRIES + CODE_ROUNDS + 1:
            attempt += 1
            if stop is not None and stop.is_set():
                return ended("stopped")
            limit = answer_room(system, conversation, max_tokens)
            if limit < MIN_ANSWER_TOKENS:
                return ended("too_long")
            shape = replies.compute(
                computing.labels(question),
                more=reading_map.more_schema() if order else None,
                take=question.taking if question.take else None,
                quote=question.cites)
            started = time.time()
            try:
                with _for(document_id):
                    response = client.chat.completions.create(
                        model=LLM_MODEL,
                        temperature=retry_temperature(temperature, faults),
                        max_tokens=limit,
                        messages=[{"role": "system", "content": system},
                                  *conversation],
                        extra_body=request_extras(),
                        response_format=providers.grammar("compute_reply",
                                                          shape))
            except Exception as exc:
                log.warning("   compute %s attempt %d failed: %s",
                            document_id, attempt, exc)
                trace.event("error", document_id, where="compute",
                            kind="exception", attempt=attempt,
                            detail=str(exc)[:300])
                if not failures.failed(exc):
                    break
                failed += 1
                if attempt < MAX_RETRIES + CODE_ROUNDS + 1:
                    failures.wait(failed)
                continue
            failures.answered()
            reply = response.choices[0]
            _observe_usage(getattr(response, "usage", None))
            _asked("compute", document_id, response, attempt=attempt,
                   started=started)
            said = reply.message.content
            code = _parse_action(said)
            if code and len(runs) < CODE_ROUNDS:
                with SANDBOX_SLOTS:
                    out = code_exec.run_code(code, context=computing.context(
                        question, shown, gathered.sources))
                runs.append({"code": code,
                             "stdout": (out.get("stdout") or "")[:2000],
                             "ok": bool(out.get("ok")),
                             "error": out.get("error")})
                trace.event("code", document_id, attempt=attempt, **runs[-1])
                told(said, _compute_reply(runs[-1], "compute_output"))
                continue
            answer = _loads_object(said)
            if isinstance(answer, dict) and order and gathered.fetch(
                    answer.get("more"), order, passages, budget):
                # What it fetched follows the answer that asked for it, as in
                # the combing: a round that brings something new is no
                # attempt, and the window bounds how many there are.
                attempt -= 1
                told(said, parts.follow_up(gathered.since(fetched["mark"])))
                fetched["mark"] = gathered.mark()
                continue
            taken = answer.get("take") if isinstance(answer, dict) else None
            if isinstance(taken, dict) and question.take is not None:
                # Read from the passage its quote stands in, of all the
                # request showed, as a value round's value is (owner
                # decision 2026-11-05): a passage, its title, a hit's line
                # or title, each under the passage it was shown with.
                source = reading_map.passage_of(taken, [
                    *shown, *(one for each in shown
                              for one in reading_map.shown_as(
                                  each, (each.provenance or {}).get("title"))),
                    *gathered.evidence(passages)])
                made = (question.take(taken, source) if source is not None
                        else "quote not found in any passage shown")
                if isinstance(made, computing.Number):
                    question.numbers.append(made)
                    noted["taken"] += 1
                    # The number it took, as the first message shows the
                    # others, after the answer that took it.
                    entry = computing.payload(question, shown,
                                              gathered.sources)["numbers"][-1]
                    told(said, worded(say("compute_taken", label=entry["id"]),
                                      {"numbers": [entry]}))
                else:
                    faults += 1
                    noted["untaken"] += 1
                    told(said, say("compute_not_taken", reason=made))
                continue
            if not isinstance(answer, dict) or "value" not in answer:
                faults += 1
                cause, correction = _reply_fault(reply, limit)
                trace.event("error", document_id, where="compute",
                            kind="unreadable", cause=cause, attempt=attempt,
                            finish=getattr(reply, "finish_reason", None))
                told(said, correction)
                continue
            if answer["value"] is None:
                return ended("none")
            if not any(run["ok"] for run in runs):
                faults += 1
                told(said, say("compute_needs_code"))
                continue
            used = computing.used_numbers(question, answer)
            # The quote that says what the chosen number is has to stand in
            # its passage, as every quote does; one that does not is told,
            # not taken (owner decision 2026-11-04, the model chooses with
            # evidence).
            missing = computing.unquoted(question, answer, used, passage_of)
            if missing is not None:
                faults += 1
                noted["misquoted"] += 1
                told(said, say("compute_quote", label=missing))
                continue
            claim = computing.claim_of(question, answer["value"], used, runs,
                                       cited=answer.get("quote"))
            if not claim:
                return ended("none")
            # The row's own check, while the model can still answer it
            # (owner decision 2026-11-05): checked only once the conversation
            # had ended, 68 shares and 30 sums of a probe were refused without
            # the model ever hearing why.
            reason = check(question, claim) if check is not None else None
            if reason is not None:
                faults += 1
                noted["rejected"] += 1
                noted["reason"] = reason
                told(said, say("compute_rejected", reason=reason))
                continue
            return ended("read", claim)
        failures.given_up()
        return ended("unanswered")

    def compute(answered: list, report, *, locate: Optional[Callable] = None,
                spec=None, stop=None) -> bool:
        if not answered:
            return True
        doc_spec = spec_of(answered[0][0], spec)
        questions = open_questions(report.tuples, doc_spec)
        if not questions:
            return True
        items: dict = {}
        for batch, _reply in answered:
            for item in batch.items:
                source = item.source
                items.setdefault((source.owner_kind, source.owner_id),
                                 []).append(item)

        def item_for(question):
            # The row's parameter is its own, whatever its anchor's is.
            return replace(computing.item_of(items, question.anchor),
                           parameter=None)

        def check(question, claim) -> Optional[str]:
            """Why the fold refuses *claim*: the same check, into a report of
            its own. Locating its quote only marks a row, never refuses one."""
            tried = DocumentReport(document_id=report.document_id)
            fold_claims(item_for(question), [claim], tried, spec=doc_spec)
            return tried.refusals[0]["reason"] if tried.refusals else None

        started = time.time()
        asked = [(question, pool.submit(ask, question, items,
                                        report.document_id, stop, check))
                 for question in questions]
        made: list = []
        for question, future in asked:
            outcome, claim, runs, noted = future.result()
            if claim is not None:
                before = len(report.tuples)
                fold_claims(item_for(question), [claim], report,
                            locate=locate, spec=doc_spec)
                if len(report.tuples) == before:
                    outcome = "refused"
                elif same is not None and any(
                        same(report.tuples[-1], row, doc_spec) for row in made):
                    report.tuples.pop()
                    outcome = "same"
                else:
                    made.append(report.tuples[-1])
            trace.event("compute", report.document_id, kind=question.kind,
                        numbers=len(question.numbers), outcome=outcome,
                        runs=len(runs), **noted)
        log.info("   compute %s: %d question(s) in %.0f s",
                 report.document_id, len(questions), time.time() - started)
        return stop is None or not stop.is_set()

    return compute


def document_room(limit) -> Optional[Callable]:
    """(documents open) -> how many more may start now, or None without a
    steered limit (the ceiling alone decides then).

    A document is let in while the model requests in flight stay below what
    the throttle allows, one per look. A fixed count did not track the load:
    64 documents read to their end each kept one request open, and four
    GPUs ran at a fifth of their cache with nothing waiting. Planning sends
    nothing, so a document planning does not hold the next one back; the
    ones that start asking fill the limit, and while they hold it no further
    document starts.
    """
    if limit is None:
        return None

    def room(open_documents: int) -> int:
        return 1 if limit.in_flight < limit.limit else 0

    return room


def harvest_documents(documents: list, harvest_document: Callable, *,
                      in_flight: int, stop=None,
                      halted: Optional[Callable] = None,
                      room: Optional[Callable] = None) -> tuple:
    """Run *harvest_document(id, filename)*, *in_flight* at most at a time
    and, with *room* (`document_room`), as many as the server has room for.

    Not in groups: the moment one document is done the next one starts, so a
    slow plan holds its own place and nobody else's. A group of sixteen used
    to wait for its slowest batch, and on corpus_m5 that was a single field
    request answering alone on four GPUs for half an hour.

    *harvest_document* returns (written, failures). *stop* (SIGTERM) ends the
    loop at once without waiting for what is open; *halted* only stops new
    documents from starting, and the open ones are waited for. A document
    that is done, written or not, has the answers kept for its requests
    forgotten (`scheduler.read_out`).

    Returns (done, written, failures).
    """
    from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

    queue = list(documents)
    pending: dict = {}
    done = written = failures = 0
    started = time.time()
    in_flight = max(1, int(in_flight))

    def stopping() -> bool:
        return stop is not None and stop.is_set()

    pool = ThreadPoolExecutor(max_workers=in_flight,
                              thread_name_prefix="document")
    try:
        while queue or pending:
            allowed = in_flight - len(pending)
            if room is not None:
                allowed = min(allowed, room(len(pending)))
            while (queue and allowed > 0 and not stopping()
                   and not (halted is not None and halted())):
                document_id, filename = queue.pop(0)
                pending[pool.submit(harvest_document, document_id,
                                    filename)] = (document_id, filename)
                allowed -= 1
            if not pending or stopping():
                break
            # Looked at every second while documents wait for room, so the
            # next one starts soon after the load allows it.
            finished, _ = wait(list(pending),
                               timeout=1 if room is not None and queue else 5,
                               return_when=FIRST_COMPLETED)
            for future in finished:
                document_id, filename = pending.pop(future)
                done += 1
                # Done, written or not: the answers kept for its requests go
                # (`scheduler.read_out`).
                scheduler.read_out(document_id)
                try:
                    ok, failed = future.result()
                    failures += failed
                    written += 1 if ok else 0
                except Exception:
                    failures += 1
                    log.exception("extraction: %s failed", filename)
                log.info("extraction: %d/%d document(s) done, %d written, %d "
                         "in flight, %.0f s", done, len(documents), written,
                         len(pending), time.time() - started)
    finally:
        pool.shutdown(wait=not stopping(), cancel_futures=True)
    return done, written, failures


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
    lock = threading.Lock()
    documents: dict = {}
    section_pages: dict = {}
    # (pdf path, page) -> words. Bounded: a page's words are some tens of
    # kilobytes. Not an lru_cache, because that cannot say whether a key is
    # in it without calling through, and the call is what needs the lock.
    pages: dict = {}

    def words_of(pdf_path, page: int) -> list:
        """A hit is a dict lookup and waits for nobody. Only a miss enters
        MuPDF, under the lock, and checks again first: sixty-four documents
        finish together, and every hit of theirs used to queue behind
        whichever miss was laying out a page."""
        key = (str(pdf_path), page)
        words = pages.get(key)
        if words is not None:
            return words
        with lock:
            words = pages.get(key)
            if words is None:
                words = page_words(pdf_path, page)
                if len(pages) >= LOCATE_CACHE_PAGES:
                    pages.pop(next(iter(pages)))
                pages[key] = words
        return words

    def _lookup(document_id: int, owner_kind: str, owner_id: int) -> tuple:
        with lock:
            known = document_id in documents
            filename = documents.get(document_id)
            pages = section_pages.get((owner_kind, owner_id))
        if known and (owner_kind != "section" or pages is not None):
            return filename, pages or []
        conn = sqlite3.connect(readonly_uri(db_path), uri=True)
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
            # MuPDF is entered inside words_of, under the lock. The lock once
            # guarded the two dicts and not the library, so eight verification
            # threads opened and laid out PDFs at once; a corpus run died of
            # "stack smashing detected" after 204 documents, taking the rest
            # of its group with it.
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
            **prompts.versions(survey_prompt_ids()),
            **(fingerprints(spec) if spec is not None else {})}


def survey_prompt_ids(profile=None) -> tuple:
    """The prompts of a harvest from the survey: `SURVEY_PROMPT_IDS`, and
    the naming's and the plan's years' where the profile writes them, which
    a spec that merges names or dates a value by the plan's years sends
    (`naming.NAMING_PROMPT_IDS`, `years.YEARS_PROMPT_ID`, required by
    `surveyed_flow`)."""
    out = SURVEY_PROMPT_IDS
    for prompt_ids in (naming_map.NAMING_PROMPT_IDS,
                       (years_map.YEARS_PROMPT_ID,)):
        try:
            for prompt_id in prompt_ids:
                prompts.load(prompt_id, profile)
        except (FileNotFoundError, LookupError):
            continue
        out = (*out, *prompt_ids)
    return out


def surveyed_flow(spec: Spec, profile=None) -> bool:
    """Whether a run can harvest from the survey: its spec names groups. A
    spec without groups cannot be harvested (`main` stops on it).

    A spec with groups whose profile lacks a prompt of the survey is a broken
    profile: the run stops and names the prompt, as `spec.load` stops at a
    broken group (owner decision 2026-11-04). So does a group prompt whose
    parts are not the spec's groups, or one whose file lacks the words of a
    field its follow-ups carry (`parts_of`), before a request is sent rather
    than at the first plan's reading."""
    if not spec.groups:
        return False
    # The naming only where the spec merges names (`naming.py`), the plan's
    # years only where its frame has a year (`years.py`).
    needed = (*SURVEY_PROMPT_IDS,
              *(naming_map.NAMING_PROMPT_IDS
                if naming_map.merges(spec) else ()),
              *((years_map.YEARS_PROMPT_ID,) if dates_by_plan(spec) else ()))
    for prompt_id in needed:
        try:
            parts_of(prompt_id, spec, profile)
        except (FileNotFoundError, LookupError) as exc:
            raise LookupError(
                f"the spec names groups, so the profile "
                f"{getattr(profile, 'name', None) or 'in use'!r} must write "
                f"every prompt of the survey, and {prompt_id!r} is missing "
                f"or does not fit the groups: {exc}") from exc
    return True


def producer(kind: str, model: Optional[str] = None) -> dict:
    """Who wrote into a harvest in one pass. Recorded, never compared.

    A harvest is written once and then written into: a top-up reads single
    coordinates again, possibly under another model or prompt, a second
    reading flags values, a remap moves answers without a model at all. The
    stamp's `model` names the first of them only. This is one entry of the
    list that names them all. A coordinate a top-up re-read points at its
    entry by position (`fields.PRODUCER`), so entries are never removed or
    reordered.
    """
    from docpipe import __version__
    entry = {"pass": kind, "docpipe": __version__,
             "utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    if model is not None:
        entry.update(model=model, provider=providers.provider("llm"),
                     prompts=prompts.versions(survey_prompt_ids()), flow=FLOW)
    return entry


# {document name: {"sha256", "bytes"}} of the database this run reads, for
# the stamp. Filled by `note_documents`; empty when the database records
# none, and then the stamp says nothing about it and compares nothing.
DOCUMENT_CONTENT: dict = {}

# The stamp key that says which PDF a harvest was read from. Compared by its
# sha256 alone (`document_moved`), and only where both the stamp and this run
# know one: a stamp from before the key was written, or a database row with no
# checksum, leaves the document as current as it was.
DOCUMENT_KEY = "document"


def note_documents(db_path) -> int:
    """Read which bytes each document of the database is. Returns how many
    documents have that recorded."""
    DOCUMENT_CONTENT.clear()
    try:
        with sqlite3.connect(readonly_uri(db_path), uri=True) as conn:
            rows = conn.execute(
                "SELECT filename, sha256, bytes FROM Documents "
                "WHERE sha256 IS NOT NULL").fetchall()
    except sqlite3.Error:               # a database older than the record
        return 0
    for filename, sha256, size in rows:
        content = {"sha256": sha256, "bytes": size}
        DOCUMENT_CONTENT[filename] = content
        DOCUMENT_CONTENT[Path(filename).stem] = content
    return len(rows)


def note_index_model(db_path, command: str = "extraction") -> None:
    """Say so when this run embeds its probes with another model than the
    one the database's index was built with. A line in the log, no more;
    `command` is whose line it is."""
    from docpipe.embedding import config as embedding_config
    from docpipe.store import schema as store_schema
    try:
        with sqlite3.connect(readonly_uri(db_path), uri=True) as conn:
            mismatch = store_schema.embedding_mismatch(
                conn, embedding_config.EMBEDDING_MODEL)
    except sqlite3.Error:
        return
    if mismatch:
        log.warning("%s: %s", command, mismatch)


def stamp_record(name: str, kind: str = "harvest") -> dict:
    """The stamp keys that place a harvest. The version decides nothing,
    `document` is compared (`document_moved`), and of the producers
    `read_in_part` reads whether the document was read to its end."""
    from docpipe import __version__
    record = {"docpipe": __version__,
              "producers": [producer(kind, LLM_MODEL)]}
    if name in DOCUMENT_CONTENT:
        record[DOCUMENT_KEY] = DOCUMENT_CONTENT[name]
    return record


def document_current(name: str) -> dict:
    """The stamp key this run can say about one document, or {}.

    Per document and not part of `_stamp_current`: that is the key set of the
    whole run, which a top-up and a remap carry forward, and neither of them
    reads a PDF. Kept out of it, they neither earn this key nor lose it.
    """
    if name in DOCUMENT_CONTENT:
        return {DOCUMENT_KEY: DOCUMENT_CONTENT[name]}
    return {}


def document_moved(stored: dict, current: dict) -> bool:
    """True when the stamp and this run both name the document's bytes and
    the sha256 differs.

    A missing key on either side is not a difference. A stamp written before
    the key existed cannot say which PDF it read, and calling that stale would
    report the whole corpus for a sentence it never recorded; a database that
    records no checksum cannot say which PDF this run reads.
    """
    then, now = stored.get(DOCUMENT_KEY), current.get(DOCUMENT_KEY)
    if not isinstance(then, dict) or not isinstance(now, dict):
        return False
    return bool(then.get("sha256") and now.get("sha256")
                and then["sha256"] != now["sha256"])


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
# it. trace._handle starts its file anew, so the harvest's own would be lost,
# and scripts/harvest_compare.py reads `trace/` alone, so a top-up's requests
# are not counted into the harvest's cost.
TOPUP_TRACE_DIR = "trace-topup"
OPEN_TRACE_DIR = "trace-open"


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
    """Which keys differ from now; everything when unstamped.

    The ontology keys are compared (`QUESTION_KEYS`: one per parameter,
    value list, axis and slot), the whole-file sha `spec` only for a stamp
    that has none of them, and the sha256 of the PDF the harvest read from
    (`DOCUMENT_KEY`) where the stamp and `current` both carry one. The model,
    the anchors, every prompt and every recorded sentence are in the stamp for
    a reader and decide nothing: the owner's rule of 2026-09-10 is that a
    stamp rests on the KG/ontology parameters alone, so a reworded prompt or
    another model leaves a harvested corpus current. The PDF is the one
    addition the owner decided on: another file under the same name is not
    the document the ontology keys were read against.

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
    # Everything but the PDF: a stamp that is not there names no document, so
    # there is no other file for this one to be.
    unstamped = sorted(k for k in current if k != DOCUMENT_KEY)
    if not stamp_path.is_file():
        return unstamped
    try:
        stored = json.loads(stamp_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return unstamped
    detailed = any(k.startswith(QUESTION_KEYS) for k in current)

    def compared(key: str) -> bool:
        return key.startswith(QUESTION_KEYS) or (not detailed and key in COARSE)

    changed = {k for k in current
               if compared(k) and stored.get(k) != current[k]}
    if detailed:
        changed |= {k for k in stored if k not in current and compared(k)}
    if document_moved(stored, current):
        changed.add(DOCUMENT_KEY)
    return sorted(changed)


def documents_to_harvest(documents, out_dir: Path, spec_sha: str, *,
                         force: bool = False, force_stale: bool = False,
                         anchors_sha: str = "", spec: Optional[Spec] = None,
                         top_up: bool = False,
                         start_at: bool = False) -> list:
    """Which of these documents this run has work for.

    A top-up is the exception and it is not a small one: this filter drops
    exactly the documents whose stamp moved, which is the entire population a
    top-up exists to re-read. Filtered, the flag is a no-op that logs
    "nothing to harvest" unless --force-stale is also given. The pass that
    appends a parameter (`--top-up-parameters`) asks for the same, for the
    same reason.
    """
    if top_up:
        return list(documents)
    return [(did, fn) for did, fn in documents
            if not already_done(Path(fn).stem, out_dir, spec_sha,
                                force=force, force_stale=force_stale,
                                anchors_sha=anchors_sha, spec=spec,
                                start_at=start_at)]


def read_in_part(stamp_path: Path) -> bool:
    """Whether the stamp's document was read at its found places alone, with
    nothing having read the rest of it since."""
    from .remap import _read_stamp
    from .topup_rest import read_to_end
    stamp = _read_stamp(stamp_path) or {}
    return not read_to_end(stamp_path) and any(
        isinstance(p, dict) and p.get("pass") == found_places.PASS
        for p in stamp.get("producers") or ())


def already_done(name: str, out_dir: Path, spec_sha: str, *,
                 force: bool = False, force_stale: bool = False,
                 anchors_sha: str = "", spec: Optional[Spec] = None,
                 start_at: bool = False) -> bool:
    """True when this document needs no work: harvested under the current
    ontology keys — or stale with nobody asking for the redo. A document read
    at its found places alone is no work only for a run that starts at them:
    any other run owes it the rest of the plan."""
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
    if not start_at and read_in_part(stamp_path):
        log.info("extraction: %s was read at its found places alone — "
                 "harvested again", name)
        return False
    changed = stale(stamp_path, {**_stamp_current(spec_sha, anchors_sha, spec),
                                 **document_current(name)})
    if not changed:
        log.info("extraction: %s is current — skipped", name)
        return True
    if not force_stale:
        ontology = [k for k in changed if k != DOCUMENT_KEY]
        said = ([f"older {', '.join(ontology)}"] if ontology else []) \
            + (["another PDF than the one it was read from (the sha256 "
                "differs)"] if DOCUMENT_KEY in changed else [])
        log.warning("extraction: %s was harvested with %s; re-run with "
                    "--force-stale to redo it", name, " and ".join(said))
        if spec is not None:
            from .topup_parameter import gained
            new = gained(stamp_path, spec)
            if new:
                log.warning("extraction: %s has never been asked %d "
                            "parameter(s) of the spec: %s; --top-up-"
                            "parameters appends them without reading the "
                            "document again, where nothing else moved",
                            name, len(new), ", ".join(new))
        return True
    return False


# A document this many of whose sources died on an unreachable server was not
# harvested, whatever its file says. Half is the line: below it a plan really
# can be mostly holes, above it the server was gone.
UNREACHABLE_LIMIT = 0.5


def not_happened(report, *, answered: Optional[int] = None,
                 lost: int = 0) -> Optional[tuple]:
    """(cause, requests, of) when the reading of this document did not happen.

    The three ways a document comes back with a file and no reading, counted
    in the unit the message needs: "unreachable" is the sources that never
    reached the server, of the sources the plan held; "no_reply" is the
    sources planned, when not one batch came back (`answered` is how many did;
    None means the caller does not track it and the count is not checked);
    "unserved" is the requests that ended on a 429, a 5xx or a timeout, `lost` of them
    noted beside the report and the rest in its sentinels. None when the
    reading happened. `finish_document` withholds the stamp on any of them
    and the pass for a new parameter writes nothing.
    """
    failed = [r for r in report.refusals
              if r.get("claim", {}).get("_harvest_failed")]
    unreachable = sum(1 for r in failed
                      if r.get("claim", {}).get("_why") == "unreachable")
    sources = max(report.owners_harvested, len(failed))
    if sources and unreachable > sources * UNREACHABLE_LIMIT:
        return "unreachable", unreachable, sources
    if sources and answered == 0:
        return "no_reply", sources, sources
    lost += sum(1 for r in failed
                if r.get("claim", {}).get("_why") == "unserved")
    if lost:
        return "unserved", lost, lost
    return None


def finish_document(report, name: str, out_dir: Path, spec_sha: str,
                    anchors_sha: str = "", answered: Optional[int] = None,
                    spec: Optional[Spec] = None,
                    questions: Optional[dict] = None,
                    lost: int = 0) -> bool:
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

    `lost` is how many of the document's other requests (a coordinate,
    the frame, a search sentence) ended on a 429 or a 5xx, or timed out; the passages that
    ended there carry it in their sentinel. One is enough to withhold the
    stamp: the request was never answered and nothing says it cannot be.

    An earlier stamp is removed before the file is written. It vouched for
    the file this one replaces, and left in place it would have a resume
    skip a document whose stamp was just withheld. Returns whether the
    document is stamped.
    """
    failed = [r for r in report.refusals
              if r.get("claim", {}).get("_harvest_failed")]
    if failed:
        log.warning("extraction: %s: %d source(s) never answered", name, len(failed))
    # Before anything counts them: the same reading written twice is one
    # reading, and the states and the summary below have to agree with the
    # file they describe.
    repeated = drop_repeats(report)
    if repeated:
        log.info("extraction: %s: %d repeated row(s) dropped", name, repeated)
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
    stamp = out_dir / f"{name}.stamp.json"
    stamp.unlink(missing_ok=True)
    write_report(report, out_dir / f"{name}.jsonl", states)
    verdict = not_happened(report, answered=answered, lost=lost)
    if verdict is not None:
        cause, found, of = verdict
        if cause == "unreachable":
            log.error("extraction: %s: %d of %d source(s) never reached the "
                      "server — not stamped, so a resume harvests it again",
                      name, found, of)
        elif cause == "no_reply":
            log.error("extraction: %s: %d source(s) planned and not one "
                      "reply — not stamped, so a resume harvests it again",
                      name, of)
        else:
            log.error("extraction: %s: %d request(s) ended on a 429 or a "
                      "5xx — not stamped, so a resume harvests it again",
                      name, found)
        return False
    archive.keep(stamp)
    stamp.write_text(
        json.dumps({**_stamp_current(spec_sha, anchors_sha, spec),
                    **recorded_questions(questions),
                    **stamp_record(name, found_places.PASS
                                   if found_places.STAGE
                                   in getattr(report, "planned", ())
                                   else "harvest")},
                   ensure_ascii=False, indent=2),
        encoding="utf-8")
    return True


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
# corpus is the ~250 OEKG study regions with their groups, well inside it.
DYNAMIC_LIST_TOKENS = 4000


def field_slots(spec) -> list:
    """Every slot a request can ask, one per request: the parameter, the
    unit, each parameter's coordinates and the value of a category parameter
    asked again."""
    out = [fields.parameter_slot(spec), fields.unit_slot(spec)]
    for parameter in spec.parameters:
        out += fields.axis_slots(parameter)
        if parameter.value_type == "category":
            out.append(fields.value_choice(parameter))
    return [slot for slot in out if slot is not None]


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
    first. A request comes in two shapes, and the larger counts: one planned
    for a single parameter carries that parameter whole, and one planned for
    no parameter carries every parameter's class lists at once. The second
    was not counted until a profile had four lists, one of 153 classes, and
    its reading requests outgrew a budget that still measured the widest
    single parameter. A field request carries one slot's options as the
    model reads them, definitions and all, and the value of a category
    parameter asked again carries its whole list: 63,230 characters for 154
    sectors whose parameter payload counts 9,627. Unmeasured, that request
    did not fit the window and was never sent.

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
        together = len(json.dumps(_quantities_payload(spec),
                                  ensure_ascii=False))
        asked = max((len(json.dumps(slot.answerable(), ensure_ascii=False))
                     for slot in field_slots(spec) if slot.options),
                    default=0)
        dynamic = any(p.vocabulary_dynamic or
                      any(a.dynamic for a in p.axes.values())
                      for p in spec.parameters)
        payload = max(payload, max(widest, together, asked) // 3 + 600
                      + (DYNAMIC_LIST_TOKENS if dynamic else 0))
    return int(len(prompt.text.split()) * 3
               + max(BATCH_CHARS, MAX_SOURCE_CHARS) // 3    # the batch's text
               + (1200 * BATCH_SOURCES if ATTACH_IMAGES else 0)   # its crops
               + PRIOR_MAX * PRIOR_TOKENS                   # what we have already
               + payload                                    # payload + envelope
               + int(prompt.meta.get("max_tokens", 4096)))


def request_budget(spec, profile=None) -> int:
    """Tokens the largest request this run sends needs, per request.

    The window a server is started with has to hold every request kind of the
    run, so it follows the largest of them. Read off the prompts the run
    sends (`survey_prompt_ids`): the survey, the two reading requests, the
    combing and, where the profile writes it, the match. Never off one that
    no request carries, and not the review, which has a line of its own in
    the doctor.
    """
    return max(context_budget(prompts.load(prompt_id, profile), spec)
               for prompt_id in survey_prompt_ids())


def _documents(conn: sqlite3.Connection) -> list:
    """Every current document, the largest first.

    Admission is bounded (EXTRACT_BATCH_DOCS in flight) and a document lasts
    as long as its slowest sweep's chain of windows, which is sequential by
    design. Read in filename order, the tail of a run belonged to whichever
    plans sort last: one long plan alone on four cards for hours while the
    pools sat idle. Largest first is the makespan order under bounded
    concurrency; the filename breaks ties so the order is stable.
    """
    return [(int(r[0]), str(r[1]))
            for r in conn.execute(
                "SELECT d.id, d.filename FROM Documents d "
                "LEFT JOIN Sections s ON s.document = d.id "
                "WHERE d.is_current = 1 GROUP BY d.id, d.filename "
                "ORDER BY COUNT(s.id) DESC, d.filename")]


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


# The constant of a profile's extraction.py that says which frame pairs are
# which state of the plan (`pipeline.YEAR_STATES`).
YEAR_STATE_CONSTANTS = {"base": "BASE_YEAR", "target": "TARGET_YEAR"}


def span_marks_of() -> dict:
    """{coordinate: entry} a value stated for a span of years takes on each
    of its rows, as the active profile says it (`SPAN_MARKS`,
    `reading.span_rows`); {} where it says nothing."""
    from docpipe.profile import active_profile
    return dict(active_profile().component("extraction", "SPAN_MARKS")
                or {})


def year_states_of(profile) -> dict:
    """{state: which frame pairs are that state of the plan}, as the profile
    says it: their years date a row that names the state by word
    ("Basisjahr", "Zieljahr") and prints no year. None for a state the
    profile does not name, which then has no years."""
    return {state: profile.component("extraction", YEAR_STATE_CONSTANTS[state])
            for state in YEAR_STATES}


def fold_answers(answered: list, report, *, locate: Optional[Callable],
                 spec: Spec) -> None:
    """Every answered batch of a document folded into its report, and the
    rows and refusals that came of it traced.

    The harvest and the pass for a new parameter fold the same way: the same
    `fold_batch` against the spec the batch carries, so the checks a row
    meets are the harvest's own whichever of them read it.
    """
    for batch, reply in answered:
        fold_batch(batch, reply, report, locate=locate,
                   spec=spec_of(batch, spec))
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


def run_spec_path(args, profile):
    """The spec file this run reads: the one --spec names, else the
    profile's own, None where the profile names none. The stamps are written
    from this file, so a column of one's own has stamps of its own; the
    folder it writes into is kept apart by `scratch.folder_problem`."""
    if args.spec is not None:
        return args.spec
    return profile.component("extraction", "SPEC_PATH")


def _decisions_file(harvest_dir: Path) -> tuple:
    """(the decisions of people, where they were read from), for --serialize.

    The file is found where `evaluate` finds it by default, beside the
    harvest. A file that is not there, or that does not read, leaves the graph
    without decisions and says so: the graph does not depend on them, so a run
    must not stop on them either.
    """
    from . import gold as golden
    path = golden.path_beside(harvest_dir)
    if not path.is_file():
        log.info("serialize: %s is not a file: no decision is recorded", path)
        return None, path
    try:
        return golden.Gold.load(path), path
    except (ValueError, OSError) as exc:
        log.warning("serialize: %s does not read, so no decision is "
                    "recorded: %s", path, exc)
        return None, path


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        prog=program("docpipe.extraction"),
        description="Ontology-guided value extraction over an indexed corpus")
    parser.add_argument("db", type=Path, help="SQLite corpus database")
    parser.add_argument("index", type=Path, help="FAISS index")
    parser.add_argument("out", type=Path, help="Output directory (JSONL per document)")
    parser.add_argument("--image-root", type=Path, default=None,
                        help="Processed root holding the table/figure crops "
                             "(default: the profile's processed dir)")
    parser.add_argument("--pdf-root", type=Path, default=None,
                        help="PDF directory, holding the files the Documents "
                             "table names. A quote of a section's text is "
                             "looked up on its page there: the highlight "
                             "rectangles go into the row, and a quote that "
                             "is not found on the page gets the flag "
                             "not_located. Without it no quote is looked up. "
                             "Tables and figures are not compared with the "
                             "PDF. It also says where the crops are read "
                             "from, ROOT/processed, unless --image-root is "
                             "given")
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
                        help="Print the tokens the largest request of a "
                             "harvest needs and exit (feed it to the "
                             "server's --max-model-len)")
    parser.add_argument("--serialize", type=Path, default=None, metavar="TTL",
                        help="No harvest: hand the JSONL in OUT to the "
                             "profile's kg.make_serializer and write TTL")
    parser.add_argument("--no-provenance", dest="provenance",
                        action="store_false",
                        help="With --serialize: do not write the "
                             "provenance file beside the graph "
                             "(<graph>.prov.ttl; also EXTRACT_PROVENANCE=0)")
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
    parser.add_argument("--top-up-open", action="store_true",
                        help="over the harvest in --out: ask every coordinate "
                             "left exhausted, unanswered or unbacked again, "
                             "reading each document to its end, then read "
                             "the passages its trace says were never asked "
                             "for values and append their rows. Needs the "
                             "model, the index and the harvest's traces")
    parser.add_argument("--top-up-parameters", action="store_true",
                        help="append the parameters the spec has gained "
                             "since a document was harvested, over the "
                             "harvest in --out, instead of harvesting those "
                             "documents again: each is searched for the new "
                             "parameter alone and its rows follow the stored "
                             "lines, which stay as they are. A document "
                             "whose stamp moved in anything but the addition "
                             "is left stale as a whole, and one that was not "
                             "read completely is left as it was and ends the "
                             "run non-zero. Needs the model and the index. "
                             "Not combined with --top-up")
    parser.add_argument("--start-at", type=Path, action="append",
                        metavar="HARVEST",
                        help="start each document at the passages this "
                             "stored harvest found something in, instead of "
                             "searching: no anchors, no ranking, no rest of "
                             "the plan. Only the places are taken, the model "
                             "reads them again. A coordinate still open "
                             "afterwards is searched as in any run; a number "
                             "in another passage stays unread until "
                             "--top-up-open. A document without places is "
                             "planned as usual. Repeatable: the places add "
                             "up")
    parser.add_argument("--review", action="store_true",
                        help="read every value nobody can stand behind a "
                             "second time, over its own passage and the "
                             "section that passage stands in, and record "
                             "what the second reading came to. One request "
                             "per C or D value: `python "
                             "scripts/curation_list.py OUT --level C` prints "
                             "that count for free")
    parser.add_argument("--review-limit", type=int, default=0, metavar="N",
                        help="--review only: stop after N values (0 = all)")
    parser.add_argument("--remap", action="store_true",
                        help="map every coordinate's recorded wording onto "
                             "the vocabulary as the spec reads today, over "
                             "the harvest in --out. No model. Carries a "
                             "document's stamp forward for every answer "
                             "space it could fully re-map, so a grown option "
                             "list costs minutes instead of a corpus run")
    parser.add_argument("--spec", type=Path, default=None, metavar="FILE",
                        help="read the spec from FILE instead of the "
                             "profile's SPEC_PATH: a trial harvest of a "
                             "column of one's own (`docpipe column`). OUT "
                             "then has to lie below the folder of FILE, so "
                             "that the harvest has its own stamps and never "
                             "lands beside the profile's. Such a harvest is "
                             "not meant for the graph: nothing here hands it "
                             "to the serializer, and --serialize does not "
                             "read --spec (it says so)")
    add_profile_argument(parser)
    args = parser.parse_args(argv)
    if args.top_up_parameters and args.top_up:
        # Two passes over one harvest that write their trace into one folder
        # and truncate it per document: one command, one of them.
        parser.error("--top-up-parameters is not combined with --top-up")
    if args.top_up_open and (args.top_up or args.top_up_parameters):
        parser.error("--top-up-open is a pass of its own")
    if args.start_at and (args.top_up or args.top_up_parameters
                          or args.top_up_open):
        parser.error("--start-at starts a harvest, it is no top-up")
    for harvest in args.start_at or ():
        if not harvest.is_dir():
            parser.error(f"--start-at: {harvest} is no harvest")
        if harvest.resolve() == args.out.resolve():
            parser.error("--start-at names another harvest than OUT, which "
                         "this run writes")
    logging.basicConfig(level=args.log_level,
                        format="%(asctime)s [%(levelname)s] %(name)s %(message)s",
                        datefmt="%H:%M:%S")
    if args.spec is not None:
        problem = scratch.folder_problem(args.spec, args.out)
        if problem:
            parser.error(problem)

    profile = require_profile(args)
    token_usage.begin("extraction")
    if args.recheck:
        raw_spec_path = run_spec_path(args, profile)
        if raw_spec_path is None:
            parser.error(f"profile {profile.name!r} does not configure the "
                         f"extraction stage")
        from .recheck import run as recheck_run
        run_spec = load_spec(Path(raw_spec_path))
        with document_specs(args.db, run_spec, profile.component(
                "extraction", "document_axes")) as spec_for:
            stats = recheck_run(args.out, run_spec,
                                drop_stamps=not args.keep_stamps,
                                spec_for=spec_for)
        if stats[fields.LISTS_UNREADABLE]:
            log.warning("recheck: %d document(s) left alone, their choice "
                        "lists could not be closed",
                        stats[fields.LISTS_UNREADABLE])
        total = stats["coordinates"] or 1
        log.info("recheck: %d of %d coordinates survive the rule (%.1f%%), "
                 "over %d tuple(s)", stats["read"], stats["coordinates"],
                 100.0 * stats["read"] / total, stats["tuples"])
        return 0
    if args.remap:
        raw_spec_path = run_spec_path(args, profile)
        if raw_spec_path is None:
            parser.error(f"profile {profile.name!r} does not configure the "
                         f"extraction stage")
        spec_path = Path(raw_spec_path)
        spec = load_spec(spec_path)
        from .remap import run as remap_run
        # A dynamic list is the document's own, as its harvest offered it.
        with document_specs(args.db, spec, profile.component(
                "extraction", "document_axes")) as spec_for:
            stats = remap_run(args.out, spec,
                              _stamp_current(hashlib.sha256(spec_path.read_bytes()).hexdigest(),
                                            "", spec), spec_for=spec_for)
        if stats[fields.LISTS_UNREADABLE]:
            log.warning("remap: %d document(s) left alone, their choice "
                        "lists could not be closed",
                        stats[fields.LISTS_UNREADABLE])
        settled = stats["unchanged"] + stats["remapped"] \
            + stats["remapped (required)"] + stats["newly mapped"]
        log.info("remap: %d of %d coordinate(s) map onto the current lists, "
                 "%d document(s) carried their stamp forward", settled,
                 settled + stats["no wording"] + stats["not listed"],
                 stats["stamps carried forward"])
        return 0
    if args.serialize is not None:
        if args.spec is not None:
            # Said, not refused: the graph is the profile's, and a spec file
            # of one's own is not read for it.
            log.warning("serialize: --spec is not read here: the graph is "
                        "written from the profile's own spec and not from "
                        "%s", args.spec)
        from . import graph, provenance
        factory = profile.component("kg", "make_serializer")
        described = profile.component("kg", "PROVENANCE") or {}
        if factory is not None:
            serializer = factory(args.db)
        else:
            # No writer of its own: the graph block of the spec says what
            # an answer becomes, where the spec has one. The profile's, and
            # never --spec's: --serialize does not read that option.
            raw_spec_path = profile.component("extraction", "SPEC_PATH")
            if raw_spec_path is None:
                parser.error(f"profile {profile.name!r} has no extraction "
                             f"spec and no kg.make_serializer: nothing "
                             f"says what its graph is")
            try:
                serializer = graph.make_serializer(json.loads(
                    Path(raw_spec_path).read_text(encoding="utf-8")))
            except graph.GraphError as exc:
                parser.error(f"{raw_spec_path}: {exc}")
            described = {"base": serializer.base,
                         **(serializer.provenance or {})}
        writer = None
        if args.provenance and provenance.enabled() \
                and described.get("base"):
            writer = provenance.Writer(described["base"], described)
        from .serialize import (profile_context, run as serialize_run,
                                validate)
        held, gold_path = _decisions_file(args.out)
        try:
            counts = serialize_run(args.out, args.serialize, serializer,
                                   writer, gold=held, gold_source=gold_path)
        except ValueError as exc:
            log.error("serialize: %s", exc)
            return 1
        log.info("serialize: %d tuple(s) from %d document(s) -> %s",
                 sum(counts.values()), len(counts), args.serialize)
        written = [Path(args.serialize)]
        # A profile whose data schema closes its lists more tightly than the
        # graph does writes the graph a second time as that schema takes it,
        # beside the full one; the full one keeps everything that was read.
        strict = profile.component("kg", "make_strict_serializer")
        if strict is not None:
            beside = Path(args.serialize).with_suffix(".strict.ttl")
            try:
                taken = serialize_run(args.out, beside, strict(args.db))
                log.info("serialize: %d document(s) as the data schema takes "
                         "them -> %s", len(taken), beside)
                written.append(beside)
            except ValueError as exc:
                log.warning("serialize: strict graph not written: %s", exc)
        # The shapes the last `vocabulary --refresh` pulled. A profile that
        # names none has nothing to validate against; one that names them
        # but was never refreshed is told so rather than passed over.
        shapes = profile.component("vocabulary", "shapes")
        if shapes is not None:
            paths = shapes()
            if paths:
                # The graph is written by now, and the report must not take
                # the serialize result with it when the validator fails.
                context = profile_context(profile)
                for graph_path in written:
                    try:
                        validate(graph_path, paths, context=context)
                    except Exception:
                        log.exception("shacl: validation of %s failed, no "
                                      "report written", graph_path)
            else:
                log.warning("shacl: no shapes from a refresh, the graph is "
                            "not validated (python -m profiles.%s.vocabulary "
                            "--refresh)", profile.name)
        return 0

    if args.image_root is None:
        args.image_root = resolve_image_root(args.pdf_root,
                                             profile.processed_dir)

    # component, not require: extraction is an optional stage. A profile that
    # does not do OBIE must stay loadable everywhere else and only
    # fail here, when someone actually asks it to extract.
    raw_spec_path = run_spec_path(args, profile)
    if raw_spec_path is None:
        parser.error(f"profile {profile.name!r} does not configure the "
                     f"extraction stage (profiles/{profile.name}/extraction.py "
                     f"with SPEC_PATH)")
    spec_path = Path(raw_spec_path)
    spec = load_spec(spec_path)
    # Every run harvests from the survey of each plan, so the spec must name
    # groups (`surveyed_flow`). Recorded in each pass's producer entry.
    if not surveyed_flow(spec, profile):
        parser.error(f"the spec {spec_path} names no groups: a spec needs "
                     f"groups, since every run harvests from the survey of "
                     f"each plan")
    global FLOW
    FLOW = SURVEYED
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
        set_model_len(assert_serving(LLM_BASE_URL, LLM_API_KEY, LLM_MODEL,
                                     context_budget(review_prompt, spec),
                                     what="extraction review",
                                     flag="--max-model-len", role="llm"))
        start_limit()
        start_counting()
        from .review import run as review_run
        wanted = None
        if args.document:
            # The harvest files are named after the documents, so a
            # restriction is resolved through the same listing the harvest
            # selects from and fails the same way on an id that is not on it.
            listing = sqlite3.connect(readonly_uri(args.db), uri=True)
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
        with document_specs(args.db, spec, profile.component(
                "extraction", "document_axes")) as spec_for:
            stats = review_run(
                args.out, spec, ask=make_review_asker(args.image_root),
                sources_for=make_review_sources(args.db),
                documents=wanted, limit=args.review_limit,
                prompt_sha=review_prompt.sha256, model=LLM_MODEL,
                spec_for=spec_for,
                producer=producer("review", LLM_MODEL))
        if stats[fields.LISTS_UNREADABLE]:
            log.warning("review: %d document(s) left alone, their choice "
                        "lists could not be closed",
                        stats[fields.LISTS_UNREADABLE])
        log.info("review: %d value(s) read again — %d agreed, %d disagreed, "
                 "%d could not be backed, over %d document(s)",
                 stats["reviewed"], stats["agree"], stats["disagree"],
                 stats["unbacked"], stats["documents"])
        return 1 if unheld_requests() else 0
    spec_sha = hashlib.sha256(spec_path.read_bytes()).hexdigest()
    # A harvest from the survey writes no anchors, and its stamps say so.
    anchors_sha = ""
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
    # From the run's spec: a frame coordinate is asked once per document
    # with the list the spec holds, so a list a document closes is not
    # supported on a frame axis.
    frame_axes = fields.frame_slots(spec, profile.component("extraction",
                                                            "FRAME") or ())
    year_states = year_states_of(profile)

    log.info("extraction: from the survey of each plan: survey, reading, "
             "combing")
    # The largest request of the run, over the prompts it sends: what the
    # server is started with, what the doctor checks and what it is asked for.
    required = request_budget(spec)
    if args.print_context_budget:
        print(required)
        return 0
    # The window every request is sized against before it is sent.
    set_model_len(assert_serving(LLM_BASE_URL, LLM_API_KEY, LLM_MODEL,
                                 required, what="extraction",
                                 flag="--max-model-len", role="llm"))
    start_limit()
    start_counting()

    from concurrent.futures import ThreadPoolExecutor

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
    locate = make_locate(args.db, args.pdf_root)
    note_documents(args.db)
    note_index_model(args.db)

    listing = sqlite3.connect(readonly_uri(args.db), uri=True)
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
        top_up=args.top_up or args.top_up_parameters or args.top_up_open,
        start_at=bool(args.start_at))
    if args.top_up_parameters or args.top_up_open:
        from . import topup_parameter
        documents, unharvested = topup_parameter.with_harvest(documents,
                                                              args.out)
        if unharvested:
            log.info("top-up-parameters: %d document(s) have no harvest file "
                     "in %s and are left to the harvest", unharvested,
                     args.out)
    if not documents:
        log.info("extraction: nothing to harvest")
        return 0
    # What this run replaces is kept under its name (archive.py).
    archive.begin("top-up-open" if args.top_up_open
                  else "top-up" if args.top_up
                  else "top-up-parameters" if args.top_up_parameters
                  else found_places.PASS if args.start_at
                  else "harvest")

    # How many documents are in flight at once: as many as the server has
    # room for (`document_room`), and never more than this ceiling, which
    # only guards the runner's memory. Not a group: a document that is
    # written makes room for the next one.
    in_flight = max(1, int(os.environ.get("EXTRACT_BATCH_DOCS", "256")))
    room = document_room(LIMIT)
    log.info("extraction: %d document(s), %d parameter(s), "
             "plan_parallel=%d, llm_parallel=%d, documents in flight %s",
             len(documents), len(spec.parameters),
             PLAN_PARALLEL, LLM_PARALLEL,
             f"by the server's room, at most {in_flight}" if room
             else f"{in_flight}")

    UNSERVED.clear()

    # Creates the query-embedding cache the passage search reads.
    cache_path = args.out / "query_cache.db"
    query_cache.connect(cache_path).close()
    # One store of passage content for every helper and thread of this run.
    content = make_shared_content()
    more_sources = make_more_sources(
        args.db, faiss_index, id_to_pos, cache_path, content=content,
        reranker=make_search_reranker(args.image_root))
    # The combing of a harvest from the survey, which the passes over a
    # stored harvest re-read a coordinate with as well, and what it reads the
    # plan with.
    pages_of = make_page_count(args.db)
    every = make_rest_of_document(args.db, content=content)
    specs: dict = {}
    specs_lock = threading.Lock()

    def spec_for(document_id: int) -> Spec:
        """The spec with the lists this document closes, made once per
        document (`fill_dynamic_axes`, as `closed_spec` below)."""
        if document_axes is None:
            return spec
        with specs_lock:
            if document_id in specs:
                return specs[document_id]
        conn = sqlite3.connect(readonly_uri(args.db), uri=True)
        conn.row_factory = sqlite3.Row
        try:
            made = fill_dynamic_axes(spec, document_axes(conn, document_id))
        finally:
            conn.close()
        with specs_lock:
            return specs.setdefault(document_id, made)

    def rank(document_id: int, probes: list, exclude: set) -> list:
        """The whole plan, best first for the combing's search sentences."""
        return more_sources(document_id, probes, set(exclude), limit=0)

    own = profile.component("extraction", "FRONT_PAGE_PARAMETERS") or ()
    seek = make_seek_probes(own, document_context_of(args.db,
                                                     document_context))
    whole = surveyed_map.SurveyedHarvest(
        spec,
        lambda doc_spec, only, scope: make_survey(
            args.db, narrow_spec(doc_spec, only), args.out, every=every,
            image_root=args.image_root, scope=scope),
        lambda doc_spec: make_reader(doc_spec, args.image_root),
        lambda doc_spec: make_comber(doc_spec, rank, seek),
        lambda document_id: every(document_id, set()), pages_of,
        spec_for=spec_for, front=own,
        title=profile.component("extraction", "FRONT_PAGE_TITLE"),
        make_years=lambda doc_spec: make_years(doc_spec, rank),
        title_page_of=make_title_page(args.db, profile),
        make_settings=lambda doc_spec: make_settings(doc_spec, rank),
        make_seeker=lambda doc_spec: make_seeker(doc_spec, rank))

    def pass_sweep():
        """What a pass over a stored harvest re-reads a coordinate with: the
        combing."""
        return surveyed_map.comb_sweep(whole.comber_of, spec_for, every,
                                       pages_of)

    if args.top_up:
        from . import topup
        trace.open_trace(args.out / TOPUP_TRACE_DIR,
                         {did: Path(fn).stem for did, fn in documents}.get)
        frame_names = [slot.name for slot in frame_axes]
        listing = sqlite3.connect(readonly_uri(args.db), uri=True)
        listing.row_factory = sqlite3.Row

        document_spec = make_document_spec(listing, spec, document_axes)

        try:
            log.info("top-up: this may rewrite %s for every question whose "
                     "wording moved — the anchors key hashes the prompt and "
                     "the model, not the questions",
                     args.out / "anchors.json")
            stats = topup.run(
                args.out, spec,
                _stamp_current(spec_sha, anchors_sha, spec),
                {"sweep": pass_sweep(),
                 "owner_sources": make_owner_sources(args.db, content=content),
                 "document_spec": document_spec,
                 "frame_names": frame_names,
                 "frame_axes": frame_axes,
                 "year_states": year_states,
                 "dynamic_ok": document_axes is not None,
                 "locate": locate},
                only=args.top_up_key)
        finally:
            listing.close()
        log.info("top-up: %d row(s) re-read over %d document(s), %d stamp(s) "
                 "carried forward, %d blocked",
                 stats["rows"], stats["documents"],
                 stats["stamps carried forward"], stats["blocked"])
        write_stats(args.out, [TOPUP_TRACE_DIR],
                    {Path(fn).stem for _did, fn in documents})
        return 1 if unheld_requests() else 0

    if args.top_up_open:
        # First what the stored rows left open, then the passages nobody
        # read: the rows found there are asked to the end as well.
        from . import topup
        read_to_end()
        trace.open_trace(args.out / OPEN_TRACE_DIR,
                         {did: Path(fn).stem for did, fn in documents}.get)
        stats = topup.run_open(
            args.out, spec,
            {"sweep": pass_sweep(),
             "owner_sources": make_owner_sources(args.db, content=content),
             "document_spec": document_spec_per_call(args.db, spec,
                                                     document_axes),
             "frame_axes": frame_axes,
             "year_states": year_states,
             "locate": locate},
            names={Path(fn).stem for _did, fn in documents},
            workers=in_flight, room=room)
        log.info("top-up-open: %d open coordinate(s) asked over %d "
                 "document(s), %d still open", stats["open coordinates asked"],
                 stats["documents"], stats["open coordinates left"])

    document_name = {did: Path(fn).stem for did, fn in documents}
    # Every event carries the document it belongs to and lands in that
    # document's own file, so a redone document overwrites its own trace. A
    # pass over a stored harvest writes beside the harvest's traces and not
    # into them: they say what the harvest cost, and are opened for writing.
    if args.top_up_parameters:
        trace.open_trace(args.out / TOPUP_TRACE_DIR, document_name.get)
    elif args.top_up_open:
        from .topup_rest import TRACE_DIR as REST_TRACE_DIR
        trace.open_trace(args.out / REST_TRACE_DIR, document_name.get)
    else:
        trace.open_trace(args.out / "trace", document_name.get)

    computer = make_computer(profile,
                             lambda document_id: every(document_id, set()),
                             pages_of, rank)
    completer = make_completer(profile, args.db)
    namer = make_namer(spec, lambda document_id: every(document_id, set()))

    def verify(entry: tuple, replies: Optional[int] = None) -> bool:
        """Fold, work out, complete and write one document. *replies* is how
        many of its requests came back, its batches when not given: for a
        harvest from the survey the passages its survey answered."""
        name, report, answered = entry
        replies = len(answered) if replies is None else replies
        fold_answers(answered, report, locate=locate, spec=spec)
        # Stopped half way a document is half worked out, and unwritten like
        # one half read.
        if computer is not None and not computer(
                answered, report, locate=locate, spec=spec, stop=Halted):
            return False
        # Which names of the document mean the same thing, over every row
        # it now holds, worked-out ones included (owner decisions
        # 2026-11-06).
        if namer is not None:
            namer(report)
        if completer is not None:
            completer(report, spec)
        stamped = finish_document(report, name, args.out, spec_sha,
                                  anchors_sha, answered=replies, spec=spec,
                                  lost=UNSERVED.of(report.document_id))
        trace.flush(report.document_id)
        return stamped

    started = time.time()
    failures = 0
    # Set by the dead-server cut inside harvest_batches. Documents already
    # written stay written; the ones in flight are left unstamped and a resume
    # harvests them again.
    server_gone = [False]
    halt = threading.Event()

    class Halted:
        """SIGTERM or a dead server: nothing new starts, open work is left."""

        @staticmethod
        def is_set() -> bool:
            return STOP.is_set() or halt.is_set()

    def give_up() -> None:
        server_gone[0] = True
        halt.set()

    def server_dead(seconds: float) -> None:
        """No answer for minutes: nothing in flight can finish any more, so
        the run ends at once, like a SIGTERM, instead of waiting for every
        open request to spend its retries on a server that is gone."""
        give_up()
        log.error("extraction: the model server stopped answering — no reply "
                  "for %.0f s, the run ends here. What was harvested is "
                  "written and stamped, the rest is not, so a resume picks up "
                  "where this stopped.", seconds)
        trace.close()
        token_usage.flush()
        logging.shutdown()
        _hard_exit(1)

    # A hosted API is not a server of this run's own that can die under it,
    # and its address is not the one the probe would ask.
    if not providers.hosted("llm") and not providers.replaying():
        watch_server(server_dead)

    # Shared by every document in flight: the pool bounds the batches of all
    # of them together, the streak sees a dead server across all of them.
    batch_pool = ThreadPoolExecutor(max_workers=max(LLM_PARALLEL, 1),
                                    thread_name_prefix="batch")
    # Planning is retrieval on the embedder's card and SQL: PLAN_PARALLEL plans
    # at a time across all documents, not per document.
    plan_pool = ThreadPoolExecutor(max_workers=max(PLAN_PARALLEL, 1),
                                   thread_name_prefix="plan")
    # OpenAI client is thread-safe.
    rest_of_document = make_rest_of_document(args.db, content=content)
    found = (found_places.Found(args.start_at, document_name.get,
                                rest_of_document)
             if args.start_at else None)

    whole.halted = Halted.is_set

    def harvest_document(document_id: int, filename: str) -> tuple:
        """One document from its survey to its file: (written, failures).

        With --start-at the survey covers the passages earlier harvests
        found something in, and the rest of the plan for a parameter none
        of them was asked (`found.Found.gained`); the stamp then says the
        document was read in part.
        """
        name = Path(filename).stem
        kept = found.passages(document_id) if found is not None else []
        if kept:
            taken = surveyed_map.take_found(
                whole, document_id, kept,
                found.gained(document_id, spec))
            stage = found_places.STAGE
        else:
            taken = whole(document_id)
            stage = surveyed_map.STAGE
        if taken is None:
            return False, 0
        report = DocumentReport(document_id=document_id,
                                owners_harvested=taken.passages,
                                planned={stage: taken.passages},
                                sources_of=taken.sources_of)
        stamped = verify((name, report, taken.answered),
                         replies=taken.replies)
        return stamped, 0 if stamped else 1

    parameter_pass = None
    if args.top_up_parameters:
        parameter_pass = surveyed_map.ParameterPass(
            args.out, spec, _stamp_current(spec_sha, anchors_sha, spec),
            {"document_spec": document_spec_per_call(args.db, spec,
                                                     document_axes),
             "take": lambda document_id, uris: whole(
                 document_id, only=tuple(uris), scope="parameters"),
             "locate": locate,
             "frame_names": [slot.name for slot in frame_axes],
             "dynamic_ok": document_axes is not None})
        harvest_document = parameter_pass
    rest_pass = None
    if args.top_up_open:
        rest_pass = surveyed_map.UnreadPass(
            args.out,
            {"take": lambda document_id, passages, also: whole(
                document_id, scope="rest", passages=passages, also=also),
             "passages_of": lambda document_id: every(document_id, set()),
             "locate": locate, "spec": spec})
        harvest_document = rest_pass
    install_stop_handler()
    try:
        done, _written, failed = harvest_documents(
            documents, harvest_document, in_flight=in_flight, stop=STOP,
            halted=halt.is_set, room=room)
        failures += failed
    finally:
        stopped = STOP.is_set()
        batch_pool.shutdown(wait=not stopped, cancel_futures=stopped)
        plan_pool.shutdown(wait=not stopped, cancel_futures=stopped)
    if parameter_pass is not None:
        parameter_pass.report()
    if rest_pass is not None:
        rest_pass.report()

    if server_gone[0]:
        log.error("extraction: the model server stopped answering — the run "
                  "ends here after %d of %d document(s). What was harvested is "
                  "written and stamped, the rest is not, so a resume picks up "
                  "where this stopped.", done, len(documents))
        failures += 1

    if STOP.is_set():
        log.error("extraction: stopped by SIGTERM after %.0f s. The documents "
                  "whose every batch came back are written and stamped; a "
                  "resume harvests the rest.", time.time() - started)
        trace.close()
        token_usage.flush()
        logging.shutdown()
        # Not a return: the field sweeps still waiting on the server run in
        # non-daemon threads, and a normal exit would wait for every one.
        _hard_exit(STOPPED_EXIT)
        return STOPPED_EXIT

    log_usage(request_budget(spec))
    failures += unheld_requests()
    log.info("extraction: done in %.0f s, %d failure(s)",
             time.time() - started, failures)
    from .topup_rest import TRACE_DIR as REST_TRACES
    write_stats(args.out, [OPEN_TRACE_DIR, REST_TRACES] if args.top_up_open
                else [TOPUP_TRACE_DIR] if args.top_up_parameters
                else ["trace"], set(document_name.values()))
    return 1 if failures else 0


def write_stats(out: Path, traces: list, names: set) -> None:
    """Where this run found the harvest hard (stats.py), beside it. A
    failure to count is logged and never fails the run."""
    from . import stats
    trace.flush()
    try:
        stats.write(out, [Path(out) / t for t in traces], names)
    except Exception:
        log.exception("stats: not written")
