"""
runner.py: Wires the pure harvest loop of `pipeline.py` to the live stack.

A run reads each plan in pieces of numbered lines (`surveyed_flow`, which
stops the run where the spec names no groups or the profile lacks a prompt
of the harvest): every piece asked for every field in the order a reranker
gives it, each coordinate of each value found asked on its own, and a
coordinate its place does not state searched for (`addressed.py`, run per
document by `surveyed.py`), then the fold, the compute step and the file
with its stamp as below. The passes over a
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
import contextvars
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
from contextlib import ExitStack, contextmanager, nullcontext
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Callable, Optional

from docpipe import prompts
from docpipe import providers
from docpipe import rules
from docpipe.providers.governor import status_of
from docpipe import usage as token_usage
from docpipe.llm_preflight import (assert_serving, assert_step_models,
                                   request_extras)
from docpipe.profile import add_profile_argument, program, require_profile
from docpipe.store.schema import readonly_uri

from . import addressed as addressed_map
from . import blocks
from . import archive
from . import mend
from . import passflow
from . import compute as computing
from . import fields
from . import flow as flow_map
from . import shows as shows_map
from . import found as found_places
from . import reading as reading_map
from . import replies
from . import surveyed as surveyed_map
from . import thread as thread_map
from . import scheduler
from . import scratch
from . import lookup as lookup_map
from . import trace
from .wording import say
from .pipeline import (YEAR_STATES, DocumentReport, Source,
                       cell_index as pipeline_cell_index, column_head,
                       drop_repeats, fold_batch, fold_claims,
                       option_named, window_around, write_report)
from .trust import document_summary, parameter_states
from .spec import Spec, fingerprints, load as load_spec

log = logging.getLogger(__name__)

# The numbers of the flow the run reads with (`flow.Numbers`), once a run
# took its profile's flow (`take_flow`); until then `numbers()` reads what
# the default profile's flow file and the settings over it say at use.
NUMBERS: Optional[flow_map.Numbers] = None
# The boxes of the flow the run reads with, by id, and for each kind of
# request the first box that asks it, its home (`take_flow`, `in_home`).
_FLOW_NODES: dict = {}
_HOMES: dict = {}
# (the id of a question step, a kind of request) -> the step after it that
# asks this kind for it (`in_home`).
_ATTACHED_HOMES: dict = {}


def in_home(kind: Optional[str]):
    """Read with the values of the box that is the home of requests of this
    kind (the first box of the flow that asks it) while the block runs,
    unless the step that runs asks this kind itself. Requests of a kind are
    asked from other steps too: the entry of a list from the step of a find,
    the check that a find speaks about the value from the step that searches
    (it is attached to it, and the engine does not enter its box), the name
    of a scenario from a search. Such a request is asked as the step that
    asks that kind says (its model, its answer room, its extras), so that
    every request of a kind is asked alike, wherever it comes from."""
    step = rules.STEP.get()
    here = _FLOW_NODES.get(step.ident) if step is not None else None
    if here is not None and blocks.asks_of(here) == kind:
        return nullcontext()
    # A step that stands after the asking step and asks this kind says how
    # it is asked there ("Choose the list entry", owner decision
    # 2026-11-12); elsewhere the first of the flow.
    home = _ATTACHED_HOMES.get((step.ident if step is not None else None,
                                kind)) or (_HOMES.get(kind) if kind
                                           else None)
    if home is None:
        return nullcontext()
    from .engine import Engine
    return rules.in_step(rules.stepped(home, Engine.own_values(home)))


def attached_homes(tree: list) -> dict:
    """{(the id of a box, a kind of request): the step after it that asks
    this kind for it}: the steps that stand right after a box and apply to
    its answers (`blocks.Box.attached`), such as "Choose the list entry"."""
    out: dict = {}
    lists = [tree] + [steps for parent, _frames in flow_map.walk(tree)
                      for _label, steps in flow_map.children(parent)]
    for steps in lists:
        for i, node in enumerate(steps):
            if not isinstance(node, dict) or "box" not in node:
                continue
            for after in steps[i + 1:]:
                if not isinstance(after, dict) \
                        or not blocks.is_attached(after):
                    break
                asks = blocks.asks_of(after)
                if asks and not after.get("off"):
                    out.setdefault((str(node.get("id")), asks), after)
    return out


def llm_base_url() -> str:
    """Where the requests go (rule `llm_base_url`, set at the start)."""
    return providers.llm_base_url()


def llm_api_key() -> str:
    """The key of the model server (rule `llm_api_key`, set at the start)."""
    return providers.llm_api_key()


def llm_model() -> str:
    """The model the request sent now asks (rule `model`: the step's, else
    the run's)."""
    return providers.llm_model()


def llm_timeout() -> float:
    """What the first attempt of a request waits (rule `llm_timeout_s`)."""
    return providers.llm_timeout()


def reply_limit() -> int:
    """Replies out of their form the request sent now takes before it is
    left unanswered: the number `replies` of the flow as the step that sends
    it reads it, which the setting EXTRACT_MAX_RETRIES wins over."""
    return flow_map.number(numbers(), "replies")


def retry_timeout() -> float:
    """What a retry may take after a request timed out (rule
    `repeat_timeout_s`). The first attempt keeps `llm_timeout_s`, which is
    sized for a slow but working generation; a request the server did not
    answer in that time is unlikely to differ on its repeat, and three full
    timeouts held one field thread for 91 minutes."""
    return rules.get("repeat_timeout_s")


# Set by SIGTERM (a time-limit trap or a manual kill). The run stops
# taking new work, writes the documents whose every batch came back, and
# exits without waiting for the requests still open.
STOP = threading.Event()


def retry_temperature(base: float, faults: int) -> float:
    """The sampling temperature after `faults` unreadable replies. A
    malformed reply asked again at temperature 0 comes back the same, byte
    for byte, correction message or not: on corpus_m5 field retries repeated
    their first attempt exactly and all three were lost. Every reply fault
    raises the temperature of the next attempt by a step (rules
    `retry_temperature_step`, `retry_temperature_most`)."""
    return min(rules.get("retry_temperature_most"),
               base + rules.get("retry_temperature_step") * faults)


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
    growth = rules.get("retry_wait_growth")
    doubling = growth == "doubling" or (growth == "by_cause" and transport)
    steps = 2 ** max(0, attempt - 1) if doubling else attempt
    if transport:
        return min(rules.get("transport_wait_s") * steps,
                   rules.get("transport_wait_most_s"))
    return min(rules.get("retry_wait_s") * steps,
               rules.get("retry_wait_most_s"))


def failure_statuses() -> tuple:
    """((first, last) of each status range, whether a timeout counts) of the
    rule `server_failure_statuses`: the answers that mean the server did not
    do the work. Refused where an entry is none of 429, 500-599, timeout."""
    ranges, timeout = [], False
    for said in rules.get("server_failure_statuses"):
        if said == "timeout":
            timeout = True
            continue
        low, _, high = said.partition("-")
        try:
            ranges.append((int(low), int(high or low)))
        except ValueError:
            raise ValueError(
                f"server_failure_statuses: {said!r} is no status (429), "
                f"no range (500-599) and not timeout") from None
    return tuple(ranges), timeout


def unserved(exc: BaseException) -> bool:
    """A 429, a 5xx or a timeout: the server was asked and did not do the work
    (the statuses of the rule `server_failure_statuses`).

    None says anything about the request. A rate limit lifts and a server
    recovers, and the same request is answered then. A request that timed out
    was never answered either: a server whose engine stopped taking requests
    kept its connections open until every one of them timed out, and their
    documents were stamped with the coordinates never read. Every other 4xx
    refuses the request itself (`refused`). The status is read as the
    providers read it (`governor.status_of`): the client's own or that of
    its response, the reranker's.
    """
    status = status_of(exc)
    ranges, timeout = failure_statuses()
    if status is not None:
        return any(low <= status <= high for low, high in ranges)
    return timeout and providers.timed_out(exc)


def server_side(exc: BaseException) -> bool:
    """Whether a failure is the server's: no reply came at all (no
    connection, one that broke off, a timeout: `providers.no_reply`), or the
    server said it did not do the work (`unserved`).

    These wait on the long curve and count towards the dead-server streak. A
    429 retried after two seconds is the same 429. Any other failure without
    a status is a fault of our own code (owner decision 2026-11-12: only the
    server's error codes are asked again without a limit): asked again, the
    same request runs through the same code.
    """
    return unserved(exc) or (status_of(exc) is None
                             and providers.no_reply(exc))


def refused(exc: BaseException) -> bool:
    """A 4xx that is not the server's failure (429): the server refused the
    request itself, such as one too long for the model or one our code built
    wrong ("System message must be at the beginning."). It is asked again
    `refusal_retry_most` times at most, and a request refused to the end
    leaves its document unfinished (owner decision 2026-11-09): a later run
    reads it again, and nothing is lost without a word."""
    status = status_of(exc)
    return (status is not None and 400 <= status < 500
            and not unserved(exc))


class Unserved:
    """Documents one of whose requests ended on a 429, a 5xx or a timeout,
    on a refusal asked `refusal_retry_most` times (`refused`), or on a fault
    of our own code (owner decision 2026-11-12).

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
# Set where the run stops for a server that answers no more (`run`): with
# STOP the end of every request asked again for the server's failure.
HALT = threading.Event()


def halted() -> bool:
    """Does the run stop: a SIGTERM, or a server that answers no more?"""
    return STOP.is_set() or HALT.is_set()


def persistently(what: str, call: Callable) -> Callable:
    """*call*, asked again after the server's failure (`server_side`) until
    it answers or the run halts (owner decisions 2026-11-09 and 2026-11-12:
    only the server's error codes are asked again without a limit): a
    search, an embedding or a reranker that failed is never replaced by
    another order or by nothing. Each failure is logged and waited for on
    the long curve (`retry_wait`); a run that halts raises the last one.
    With the rule `search_retry_most` above 0 the server's failure is asked
    that many times at most and then raised. A request the server refuses
    (`refused`) is asked `refusal_retry_most` times at most, and a fault of
    our own code as often again as the rule `other_errors_retry` says, then
    each is raised: its document fails and stays unfinished, the run goes
    on, and a later run reads it again (owner decisions 2026-11-09 and
    2026-11-12)."""
    def again(*args, **kwargs):
        attempt = refusals = failures = faults = 0
        while True:
            attempt += 1
            try:
                return call(*args, **kwargs)
            except Exception as exc:
                if halted():
                    raise
                if refused(exc):
                    refusals += 1
                    if refusals >= rules.get("refusal_retry_most"):
                        log.error("   %s refused %d time(s), its document "
                                  "stays unfinished: %s", what, refusals,
                                  exc)
                        raise
                elif server_side(exc):
                    failures += 1
                    most = rules.get("search_retry_most")
                    if most and failures >= most:
                        log.error("   %s failed %d time(s), its document "
                                  "stays unfinished: %s", what, failures,
                                  exc)
                        raise
                else:
                    faults += 1
                    if faults > rules.get("other_errors_retry"):
                        log.error("   %s failed in our own code, its "
                                  "document stays unfinished: %s", what,
                                  exc, exc_info=exc)
                        raise
                log.warning("   %s failed (attempt %d), asked again: %s",
                            what, attempt, exc)
                time.sleep(retry_wait(attempt, server_side(exc)))
    return again


class Failures:
    """What the failures of one request mean, the same for every request of
    the stage. The rule stands here once and not in each retry loop: of nine
    loops, three kept all of it, and the compute request asked again at once
    after a server error, asked a refused request again, and left its
    document stamped as finished when no attempt of it was served.

    A failure that is the server's (`server_side`: no reply, a 429, a 5xx)
    is asked again, after the long wait (`retry_wait`), without a limit
    until the run halts (`halted`, owner decisions 2026-11-09 and
    2026-11-12: only the server's error codes are asked again without a
    limit), or as often as the rule `server_retry_most` says where it is
    above 0; a reply that could not be read is asked again as often as the
    number `replies` says at most (`attempts`, read for the request, in its
    step), and a request the server refuses (`refused`, owner decision
    2026-11-09) as often as `refusal_retry_most` says, after the short
    wait. Any other failure is a fault of our own code: asked again as
    often as the rule `other_errors_retry` says (0: not at all). A request
    given up on whose last attempt the server did not serve (`unserved`),
    refused, or failed in our own code leaves its document unfinished
    (`UNSERVED`): the stamp is withheld, the run goes on, a resume reads it
    again, and the log names the fault with where it arose.

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
        self.faults = 0
        # The failures of the server this request met, the refusals so far,
        # and the last refusal's words.
        self.server_failures = 0
        self.other_errors = 0
        self.refusals = 0
        self.why = ""
        # The last fault of our own code, None where the last failure was
        # none (`failed`).
        self.fault_of_ours: Optional[BaseException] = None

    def attempts(self, replies: int = 0):
        """The attempts of one request, 1, 2, ...: after a failure that is
        the server's (`failed` True) the next one after the long wait, until
        the run halts; after a reply that could not be read (`fault`) the
        next one after the short wait, *replies* such replies at most (the
        number `replies` of the flow, read for this request, where none is
        given); after a refusal the next one after the short wait, as long
        as `failed` says so. The caller ends the loop on an answer and where
        `failed` says no more."""
        attempt = 0
        while True:
            attempt += 1
            yield attempt
            if self.transport:
                if halted():
                    return
            elif self.faults >= (replies or reply_limit()):
                return
            self.wait(attempt)

    def failed(self, exc: BaseException) -> bool:
        """Whether the request that raised *exc* is asked again: after the
        server's failure until the run halts or the rule `server_retry_most`
        is reached (`attempts`), after a refusal until it is the
        `refusal_retry_most`th, after a fault of our own code as often as
        the rule `other_errors_retry` says. A request not asked again has
        no answer, and its document is not finished (`lost`)."""
        self.transport, self.lost = server_side(exc), unserved(exc)
        self.fault_of_ours = None
        if refused(exc):
            self.refusals += 1
            self.lost = True
            self.why = str(exc)[:300]
            return self.refusals < rules.get("refusal_retry_most")
        if not self.transport:
            # Neither the server's failure nor a refusal: a fault of our
            # own code (owner decision 2026-11-12), never answered either.
            self.other_errors += 1
            self.lost = True
            self.fault_of_ours = exc
            return self.other_errors <= rules.get("other_errors_retry")
        self.server_failures += 1
        most = rules.get("server_retry_most")
        if most and self.server_failures >= most:
            # Given up on the server's failure: never answered, so the
            # document is not finished.
            self.lost = True
            return False
        return True

    def answered(self) -> None:
        """The server answered the request, whatever its reply says."""
        self.transport = self.lost = False
        self.refusals = 0
        self.fault_of_ours = None

    def fault(self) -> int:
        """The reply could not be read: how many such replies so far."""
        self.faults += 1
        return self.faults

    def wait(self, attempt: int) -> None:
        """Before asking again after attempt *attempt*: the long curve after
        the server's failure, the short one after a reply."""
        time.sleep(retry_wait(attempt, self.transport))

    def given_up(self) -> None:
        """The request is asked no more and has no answer. A fault of our
        own code is logged with where it arose, whether or not its document
        is noted: it is what a person fixes."""
        if self.fault_of_ours is not None:
            log.error("   document %s: a request failed in our own code "
                      "and is not asked again%s: %s", self.document_id,
                      ", the document stays unfinished" if self.noted
                      else "", self.fault_of_ours,
                      exc_info=self.fault_of_ours)
        if self.lost and self.noted:
            UNSERVED.note(self.document_id)
            if self.refusals:
                log.warning("   document %s stays unfinished: the server "
                            "refused a request %d time(s): %s",
                            self.document_id, self.refusals, self.why)


def code_rounds() -> int:
    """Sandbox rounds per calculation question (rule `code_rounds`). A
    computed value carries its code and the code's output as evidence;
    without the sandbox the model would have to work the number out itself,
    and that number would have no evidence at all."""
    return rules.get("code_rounds")


# How many code runs the sandbox takes at a time, for the whole run (rule
# `code_slots`). A code run waiting for its turn stands on the sandbox's own
# timeout otherwise. One semaphore per size the rule has had.
_SANDBOX: dict = {}
_SANDBOX_LOCK = threading.Lock()


def sandbox_slots() -> threading.BoundedSemaphore:
    """The semaphore of the code runs the sandbox takes at once, as the rule
    `code_slots` says it now."""
    size = int(rules.get("code_slots"))
    with _SANDBOX_LOCK:
        if size not in _SANDBOX:
            _SANDBOX[size] = threading.BoundedSemaphore(size)
        return _SANDBOX[size]


def attach_images() -> bool:
    """Tables and figures go to the model as pictures as well as text (rule
    `attach_images`): the transcription IS a reading of that picture, and a
    model that can see both can notice when they disagree."""
    return bool(rules.get("attach_images"))


def image_max_side() -> int:
    """Pixels of a crop's longer side (rule `image_max_side`)."""
    return rules.get("image_max_side")



ANCHORS_PROMPT_ID = "extraction/anchors"
# The one sentence a document is searched with, written for THAT document.
PHRASE_PROMPT_ID = "extraction/phrase"
# The prompts of a harvest piece by piece (addressed.py), the run's own
# wherever the profile writes them and its spec names groups
# (`surveyed_flow`); the check of a find from another passage is the
# profile's choice, and the names request is asked only by a run that
# builds a list of names (`addressed.OPTIONAL`, `names_asked`).
SURVEY_PROMPT_IDS = tuple(prompt_id for kind, prompt_id
                          in addressed_map.PROMPT_IDS.items()
                          if kind not in addressed_map.OPTIONAL)
# The flow this run harvests with, under the name stamps and producers have
# recorded since the survey began it: every harvest reads passage by
# passage. Nothing compares it; older harvests say "fieldwise" (`schema.py`),
# which is still read.
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
# How many calculation questions run at once is the rule `compute_parallel`.
# What a search shows are numbers of the flow (`NUMBERS`, owner decisions
# 2026-11-09: "Bei 5 bleiben und das mit 50 passt", "Ja als Einstellung"):
# the pieces of a search for an open coordinate or a field the document has
# once, how many of them tables, figures and text get first, and how many a
# request shows. The settings EXTRACT_SEARCH_PIECES, EXTRACT_SEARCH_SHARES
# and EXTRACT_SEARCH_CHUNKS win over the flow's file for a run.
# A search that only the end of the document stops: every piece is shown.
REST_TO_END = 1_000_000
# Set by a pass that reads to the end (`read_to_end`).
TO_END = False


def read_to_end() -> None:
    """Every search from here on shows every piece of its document, so a
    coordinate ends read or `unstated` and never `exhausted`."""
    global TO_END
    TO_END = True


_flow_logged: Optional[tuple] = None


def take_flow(profile=None):
    """The numbers of the flow a run of *profile* reads with
    (`flow.in_effect`: its flow file, and the settings over it), taken for
    every request from here on and returned. They are logged whenever they
    differ from those logged before, each with where it comes from, so that
    the log of a job says what it read with."""
    global NUMBERS, _flow_logged, _FLOW_NODES, _HOMES, _ATTACHED_HOMES
    NUMBERS = flow_map.in_effect(profile)
    _FLOW_NODES = {}
    _HOMES = {}
    _ATTACHED_HOMES = attached_homes(flow_map.tree_of(profile))
    for node, _frames in flow_map.walk(flow_map.tree_of(profile)):
        if "box" in node:
            _FLOW_NODES[str(node.get("id"))] = node
    # The home of a kind of request is the first box asking it that takes
    # part in the run: a box that is off asks nothing.
    for node, _frames in flow_map.on(flow_map.tree_of(profile)):
        asks = blocks.asks_of(node) if "box" in node else None
        if asks:
            _HOMES.setdefault(asks, node)
    # A request the main flow never asks (the second reading, the example
    # of a field) has its home in the flow of its pass.
    for kind, node in passflow.homes(profile).items():
        _HOMES.setdefault(kind, node)
    taken = rules.use(profile)
    said = (tuple(NUMBERS.as_dict().items()),
            tuple(sorted(NUMBERS.origin.items())))
    if said != _flow_logged:
        _flow_logged = said
        by_origin: dict = {}
        for name, value in NUMBERS.as_dict().items():
            by_origin.setdefault(NUMBERS.origin.get(name, "?"), []).append(
                f"{name}={value}")
        log.info("flow: %s", "; ".join(
            f"{' '.join(numbers)} [{origin}]"
            for origin, numbers in by_origin.items()))
        # The rules a profile sets itself, and those a setting sets: what
        # the default profile's file says is not repeated.
        own = {name: value for name, value in taken.values.items()
               if not taken.owners.get(name, "").endswith(
                   f"of {rules.DEFAULT_NAME}")}
        log.info("rules: %s (sha256 %s)", "; ".join(
            f"{name}={json.dumps(value, ensure_ascii=False)[:60]} "
            f"[{taken.owners.get(name)}]" for name, value in own.items())
            or "those of the default profile", taken.sha256[:12])
    return NUMBERS


def numbers() -> flow_map.Numbers:
    """The numbers of the flow the run reads with: those `take_flow` took
    for the run's profile, else what the default profile's flow file and
    the settings over it say now."""
    return NUMBERS if NUMBERS is not None else flow_map.in_effect()


# ---------------------------------------------------------------------------
# Retrieval: probe text -> ranked unseen owners of one document
# ---------------------------------------------------------------------------

_EMBEDDER = None
_EMBEDDER_LOCK = threading.Lock()


def embedder():
    """The one resident embedding model this run uses.

    `get_embedder()` CONSTRUCTS a backend, it does not return a shared one, and
    this call used to sit inside the per-probe `embed()`. With several
    planning threads each asking for its own probes, every probe
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
    if heading and heading not in body[:rules.get("heading_in_front_chars")]:
        text = f"{heading}\n{body}"
    return Source(owner_kind=hit["owner_kind"], owner_id=hit["owner_id"],
                  text=text, provenance=provenance,
                  image_path=hit.get("image_path"),
                  body=body if text is not body else None)


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

    # Owners (sections, tables, figures) whose content a run keeps (rule
    # `content_cache_owners`). The whole of the largest corpus fits (KWP:
    # 252,909), so a run reads each owner once; past the bound the oldest
    # goes, so a larger corpus cannot grow into it.
    bound = rules.get("content_cache_owners") if limit is None else limit
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
            # How much of a parent section rides along with its table (rule
            # `review_parent_chars`). Kassel's median section is 894
            # characters and its longest is 6,038, so most fit whole and the
            # rest are cut around the table's own placeholder rather than
            # dropped: the sentence that dates a table stands next to its
            # placeholder and nowhere else.
            most = rules.get("review_parent_chars")
            if len(parent.text or "") > most:
                block = provenance.get("block_id") or ""
                parent = Source(owner_kind=parent.owner_kind,
                                owner_id=parent.owner_id,
                                text=window_around(parent.text, f"[{block}",
                                             most),
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
        if rules.get("review_shown_passages") != "own_and_section":
            return [own]
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
        if start is not None and rules.get("rest_starts_at_open_rows"):
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
    None where the run is given no reranker server (rule
    `rerank_base_url`; owner decisions 2026-11-06 and 2026-11-08). A figure
    is scored with its picture, as the reading shows it."""
    from docpipe.inference import rerank as rerank_map
    if not rerank_map.base_url():
        return None

    def figure_image(source) -> Optional[dict]:
        if (source.owner_kind == "figure" and source.image_path
                and attach_images() and rules.get("rerank_with_images")):
            return _image_part(str(image_root / source.image_path)
                               if image_root else source.image_path)
        return None

    log.info("extraction: searches reranked by %s at %s, %d per kind",
             rerank_map.model_name(), rerank_map.base_url(),
             rerank_map.pool_size("section"))
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
            # Raised, never an empty list: a search that could not run is
            # no finding about the plan (owner decision 2026-11-09), and
            # what asked it asks again (`persistently`).
            log.warning("   more-passages for document %s failed: %s",
                        document_id, exc)
            raise
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
        # after the parameter itself, and after it the entries the spec says
        # such a list always has (`Parameter.beside`): the list then exists
        # where the document names nothing of its own.
        values = vocabularies.get(parameter.uri)
        if parameter.vocabulary_dynamic and parameter.beside \
                and parameter.uri in vocabularies:
            values = {**(values or {}), **parameter.beside}
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
    return _key16(f"{versions.get(ANCHORS_PROMPT_ID)}|{llm_model()}"
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


# What a field's sentence request may carry (`phrase_payload`).
PHRASE_KEYS = ("label", "description", "names", "document", "frame")


def phrase_told(prompt) -> str:
    """The system prompt a field's sentence request is told, every part of
    *prompt* it may carry (`PHRASE_KEYS`)."""
    return thread_map.cut(prompt).system(PHRASE_KEYS).text


def step_asking(target: str, preset: str, profile=None) -> dict:
    """The step of a request asked apart from the reading of a document (a
    calculation, a second reading, the example of a field): the first of
    the flow of *profile* whose answer goes to *target*, on or off, else
    the first of the flow of a pass, else its *preset*; read once where the
    request's sender is made."""
    from docpipe.profile import active_profile
    profile = profile or active_profile()
    trees = [flow_map.tree_of(profile)]
    for name in passflow.names(profile):
        if name == passflow.MAIN:
            continue
        try:
            trees.append(passflow.load(name, profile))
        except (flow_map.FlowError, LookupError, OSError):
            continue
    for tree in trees:
        for node, _frames in flow_map.walk(tree):
            if "box" in node and blocks.target_of(node) == target:
                return node
    return {"id": preset, "box": "ask", "preset": preset}


def step_parts(step: dict, standard: str, profile=None) -> tuple:
    """(prompt, inputs) of a step asked apart from the reading: the prompt
    of its kind (*standard*) where it names that one, else its own
    (`own_prompt`), and the inputs its first message is built from."""
    from . import general
    parts = general.parts_of(step)
    named = parts["prompt"]
    prompt = (prompts.load(standard, profile) if profile is not None
              else prompts.load(standard)) if named == standard \
        else own_prompt(named, profile)
    return prompt, parts["inputs"]


def sentence_step() -> dict:
    """The step whose request writes a field's sentence, which the chunks
    of a field are ordered by and the search of a field of the whole
    document goes with: the first of the run's flow that orders the chunks
    by it (`targets.chunk_order`), on or off, else its preset."""
    for node in _FLOW_NODES.values():
        if blocks.target_of(node) == "chunk_order":
            return node
    return {"id": "sentences", "box": "ask", "preset": "sentences"}


def phrase_payload(parameter, context: Optional[dict] = None,
                   step: Optional[dict] = None) -> dict:
    """What a field's sentence request carries: the inputs of the step that
    writes it (*step*, `sentence_step` where None), from the field (its
    name, what it means and the names of its list, owner decision
    2026-11-05) and from what the document says of itself (*context*, its
    texts only)."""
    from . import general, shows
    context = {k: v for k, v in (context or {}).items()
               if isinstance(v, str) and v.strip()}
    inputs = general.parts_of(step or sentence_step())["inputs"]
    return shows.apart(inputs, {"field": parameter, "context": context})


def sentences_written(profile=None) -> str:
    """What names the sentences the orders of a harvest are made with
    (`addressed.Orders`): the part of the prompt a field's sentence is told
    (`phrase_told`), and the inputs and answer form of the step that writes
    them where they are not its preset's. An order kept from sentences
    written otherwise is made again; a part told only to the sentence of
    one coordinate's search changes no order."""
    from . import general
    step = sentence_step()
    parts = general.parts_of(step)
    prompt = prompts.load(PHRASE_PROMPT_ID, profile) \
        if parts["prompt"] == PHRASE_PROMPT_ID \
        else own_prompt(parts["prompt"], profile)
    written = "document:" + hashlib.sha256(
        phrase_told(prompt).encode("utf-8")).hexdigest()
    preset = general.preset_of(step)
    own = {key: parts[key] for key, theirs in (
        ("inputs", list(preset.inputs) if preset else None),
        ("reply", preset.reply if preset else None))
        if preset is None or parts[key] != theirs}
    if own:
        written += "|" + hashlib.sha256(json.dumps(
            own, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()[:16]
    return written


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


def make_seek_probes(context_of: Optional[Callable] = None,
                     write: Optional[Callable] = None) -> Callable:
    """probes(parameter, document_id) -> the sentences a plan's passages
    are ranked with for a parameter, which sets the order it reads them in,
    and the search after an open coordinate goes with where its answer
    wrote none (`addressed.Orders`, `engine.Engine.box_order`).

    Every parameter gets a sentence written for this document by the model,
    from the parameter's label, description and list names and from what
    the document says of itself (*context_of(document_id)*, the profile's
    `document_context`: the municipality of a plan, the title of a
    publication), as the chat turns a question into a sentence of the
    document before it searches (owner decisions 2026-11-05, 2026-11-08 and
    2026-11-09). *write(parameter, context)* writes the sentences, one
    phrase request (`document_anchor`) where not given. A parameter no
    sentence could be written for gets none, and the search falls back to
    its label. Each sentence is sent in its document's turn (owner decision
    2026-11-07).
    """
    def phrase(parameter, context, document_id):
        if write is not None:
            return list(write(parameter, context) or [])
        return document_anchor(SimpleNamespace(parameters=[parameter]),
                               context, document_id=document_id
                               ).get(parameter.uri, [])

    def probes(parameter, document_id) -> list:
        context = dict(context_of(document_id) if context_of else {})
        sentences = phrase(parameter, context, document_id)
        for text in sentences:
            trace.event("seek_probe", document_id, parameter=parameter.uri,
                        per="document", text=text)
        return list(sentences)
    return probes


def document_anchor(spec: Spec, context: Optional[dict] = None,
                    client=None, prompt=None,
                    document_id: Optional[int] = None,
                    step: Optional[dict] = None) -> dict:
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
    of none goes before every document (owner decision 2026-11-07).

    The request is built from the inputs of the step that orders the chunks
    by the sentence (*step*, `sentence_step` where None) and asked with its
    prompt (owner decision 2026-11-12 evening: every question is "Ask the
    model").
    """
    from . import general
    step = step or sentence_step()
    if prompt is None:
        named = general.parts_of(step)["prompt"]
        prompt = prompts.load(PHRASE_PROMPT_ID) \
            if named == PHRASE_PROMPT_ID else own_prompt(named)
    client = _repeating(client or _client())
    behalf = (document_id, scheduler.current()[1])

    def one(parameter):
        body = phrase_payload(parameter, context, step)
        payload = json.dumps(body, ensure_ascii=False, indent=2)
        # Told only what its message carries: the parts of the prompt for a
        # sentence of one coordinate stay out (`addressed.Reader.sentence`).
        system = thread_map.cut(prompt).system(body.keys()).text
        failures = Failures(document_id)
        conversation: list = [{"role": "user", "content": payload}]
        with in_home("phrase"):
            return written(parameter, failures, conversation, system)

    def written(parameter, failures, conversation, system):
        wanted = request_wanted("phrase")
        for attempt in failures.attempts():
            limit = request_room(system, conversation, wanted, whole=True)
            if limit is None:
                break
            started = time.time()
            try:
                with scheduler.on_behalf(*behalf):
                    response = send_request(
                        client, system, conversation, limit,
                        failures.faults, reply_grammar(
                            "phrase_reply", replies.phrase()))
                failures.answered()
                token_usage.reply(response, llm_model())
                _asked("phrase", document_id, response, attempt=attempt,
                       started=started, parameter=parameter.uri)
                reply = response.choices[0]
                phrase = ((_loads_object(reply.message.content, document_id,
                                         "phrase") or {})
                          .get("phrase") or "")
                phrase = phrase.strip() if isinstance(phrase, str) else ""
                if phrase:
                    return parameter.uri, [phrase]
                # The same retry rule as everywhere else: a reply that could
                # not be read is asked again WITH the reason. Three silent
                # tries were three copies of the same reply.
                cause, correction = _reply_fault(reply, limit)
                failures.fault()
                log.warning("phrase %s attempt %d: %s reply",
                            parameter.uri, attempt, cause)
                if rules.get("retry_shows_reply"):
                    conversation.append({
                        "role": "assistant",
                        "content": reply.message.content or ""})
                    conversation.append({"role": "user",
                                         "content": correction})
            except Exception as exc:
                log.warning("phrase %s attempt %d failed: %s",
                            parameter.uri, attempt, exc)
                if not failures.failed(exc):
                    break
        failures.given_up()
        log.warning("phrase %s: no anchor written for this document",
                    parameter.uri)
        return parameter.uri, []

    # One request per parameter, all at once: in sequence they were four
    # round trips per document under a plan pool of eight, and planning a
    # group of 64 plans took half an hour with the GPUs waiting.
    from concurrent.futures import ThreadPoolExecutor
    out: dict = {}
    # Each in the context of the caller: the box of the flow asking goes
    # with it into the trace (`addressed.ASKING`).
    asked = [(contextvars.copy_context(), parameter)
             for parameter in spec.parameters]
    together = rules.get("phrase_parallel") or len(spec.parameters)
    with ThreadPoolExecutor(max_workers=max(together, 1)) as pool:
        for uri, phrase in pool.map(lambda job: job[0].run(one, job[1]),
                                    asked):
            if phrase:
                out[uri] = phrase
    return out


# The server's context window as it reported it at the start of a run
# (`set_model_len`), None where it reported none: then the rule
# `model_window_tokens` says it. The job serves at least `context_budget`.
_SERVED_WINDOW: Optional[int] = None


def model_window() -> int:
    """The window every request is sized against."""
    if _SERVED_WINDOW:
        return _SERVED_WINDOW
    with rules.in_step(None):        # a value of the machine: the run's
        return int(rules.get("model_window_tokens"))


def image_tokens() -> int:
    """One crop at its longest side on both sides, one visual token per
    square of `image_token_side_px` pixels."""
    return (image_max_side() // rules.get("image_token_side_px") + 1) ** 2 + 2


def least_answer_tokens() -> int:
    """Less room than this for the answer and the request is not sent
    (rule `least_answer_tokens`)."""
    return rules.get("least_answer_tokens")


def set_model_len(tokens: Optional[int]) -> None:
    """The window the server reports, when it reports one."""
    global _SERVED_WINDOW
    if tokens:
        _SERVED_WINDOW = int(tokens)


# The adaptive request limit every client waits in, steered by the server's
# queue (throttle.py); None while it is off or the server has no /metrics.
LIMIT = None
# The one queue every request of the run is sent through, oldest document
# first (scheduler.py), and the threads a sweep asks its windows ahead on.
# Both None while the limit is off: a sweep then asks one window at a time.
SCHEDULER = None
AHEAD = None


def start_limit() -> None:
    """Steer the requests by the server's queue unless the rule
    `limit_adaptive` is off."""
    global LIMIT
    if LIMIT is not None or not rules.get("limit_adaptive"):
        return
    if providers.replaying():
        return              # no queue to read and nothing to be refused by
    from . import throttle
    gate = providers.gate("llm")
    # A hosted API has no queue to read; what it refuses steers the limit.
    LIMIT = (throttle.start(llm_base_url()) if gate is None
             else throttle.start_hosted(gate))
    if LIMIT is not None:
        global SCHEDULER, AHEAD
        SCHEDULER = scheduler.Scheduler(LIMIT)
        AHEAD = ThreadPoolExecutor(max_workers=LIMIT.maximum,
                                   thread_name_prefix="ahead")
    if LIMIT is not None and rules.get("compute_parallel") < LIMIT.maximum:
        log.info("llm limit: compute_parallel=%d opens fewer calculation "
                 "requests than limit_most=%d allows",
                 rules.get("compute_parallel"), LIMIT.maximum)


def start_fixed_limit(requests: int) -> None:
    """The run's one queue (`SCHEDULER`), with a limit of *requests* open at
    once that does not move: a probe's places (owner decision 2026-11-07,
    the places count requests with the model, not the conversations open,
    so one that waits for its search holds none). Every client made after
    this sends through it (`_client`)."""
    global LIMIT, SCHEDULER
    from . import throttle
    requests = rules.get("fixed_limit_requests") or requests
    LIMIT = throttle.AdaptiveLimit(start=requests, minimum=requests,
                                   maximum=requests)
    SCHEDULER = scheduler.Scheduler(LIMIT)


class PromptCounter:
    """The prompt of a request counted with the served model's own tokenizer.

    The text of every message goes through the model's chat template with the
    settings every request carries (`request_extras`) and is counted exactly;
    a crop is counted at `image_tokens`, the most one can take. The estimate
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
        return len(ids) + images * image_tokens()


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
    name = model or llm_model()
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
    return (int(chars / rules.get("prompt_chars_per_token"))
            + images * image_tokens()
            + rules.get("message_overhead_tokens") * (len(conversation) + 1))


def answer_room(system: str, conversation: list, wanted: int) -> int:
    """max_tokens for this request: *wanted*, or what the window leaves."""
    return min(int(wanted), model_window()
               - rules.get("answer_margin_tokens")
               - prompt_tokens(system, conversation))


def request_room(system: str, conversation: list, wanted: int,
                 whole: bool = False) -> Optional[int]:
    """max_tokens a request may ask, None where the room is less than
    `least_answer_tokens`: such a request is not sent and counts as an
    answer that was cut off. The room is the answer that is asked for, or,
    with *whole*, what the window leaves, however short the answer asked for
    is (a search sentence of 300 tokens is sent where the window holds 512
    more)."""
    limit = answer_room(system, conversation, wanted)
    room = answer_room(system, conversation, 1 << 30) if whole else limit
    return None if room < least_answer_tokens() else limit


def request_wanted(kind: str) -> int:
    """The longest answer, in tokens, a request may ask for (rule
    `max_tokens` of the step that asks its kind)."""
    return int(rules.get("max_tokens"))


def asked_values(kind: Optional[str], profile=None) -> dict:
    """The `max_tokens` and `temperature` a request of *kind* is asked with
    where no run is going (the editor's try, the compile step): the values
    of the box that is the kind's home in the flow of *profile*, else the
    run's. A request of no kind the flow has asks with the run's."""
    from docpipe.profile import active_profile
    from .engine import Engine
    home = None
    for node, _frames in flow_map.on(flow_map.tree_of(
            profile or active_profile())):
        if kind and "box" in node and blocks.asks_of(node) == kind:
            home = node
            break
    if home is None and kind:
        home = passflow.homes(profile or active_profile()).get(kind)
    with (rules.in_step(rules.stepped(home, Engine.own_values(home)))
          if home is not None else nullcontext()):
        return {"max_tokens": int(rules.get("max_tokens")),
                "temperature": float(rules.get("temperature"))}


def reply_grammar(name: str, schema: dict, always: bool = False):
    """The `response_format` of a request whose reply is *schema*: always
    for a request that never goes without its grammar, else as the rule
    `schema_grammar` and the provider say (`providers.reply_format`)."""
    return (providers.grammar(name, schema) if always
            else providers.reply_format("llm", name, schema))


def send_request(client, system: str, conversation: list, limit: int,
                 faults: int, response_format=None):
    """The one place a request of the harvest goes out: the model, the
    temperature after *faults* unreadable replies (rules `temperature`,
    `retry_temperature_step`, `retry_temperature_most`), the answer room
    *limit*, the system prompt and *conversation*, the reply grammar where
    one is asked for and the settings every request carries
    (`request_extras`), each read for the step that sends it."""
    kwargs = {"model": llm_model(),
              "temperature": retry_temperature(
                  float(rules.get("temperature")), faults),
              "max_tokens": limit,
              "messages": [{"role": "system", "content": system},
                           *conversation],
              "extra_body": request_extras()}
    if response_format is not None:
        kwargs["response_format"] = response_format
    return client.chat.completions.create(**kwargs)


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


# Where a prompt shows the reply its request asks for (`system_text`), and
# the reply where nothing shown holds what it asks.
EXAMPLE_PLACE = "example"
NOTHING_PLACE = "nothing"


def system_text(prompt, example) -> str:
    """The system prompt one request sends: the prompt with its example
    reply ({{example}}) written for this request, as one line of JSON (owner
    decisions 2026-11-06: every request's example shows exactly the
    coordinates it asks, each read, so the model has no key to leave out).
    A request that finds values gives two, a pair (owner decision
    2026-11-09: "immer ein Positiv und ein Negativbeispiel"): the first
    goes to {{example}}, the second to {{nothing}}. A prompt without such a
    place is sent as it is written; one with it and no example for it is an
    error before anything is sent, as every open placeholder is
    (`prompts.Prompt.render`)."""
    places = getattr(prompt, "placeholders", ())
    if EXAMPLE_PLACE not in places and NOTHING_PLACE not in places:
        return prompt.text
    if example is None:
        raise KeyError(f"{prompt.id}: the prompt shows the reply of its "
                       f"request and the request gave no example")
    pair = tuple(example) if isinstance(example, (tuple, list)) \
        else (example,)
    if len(pair) > 1 and NOTHING_PLACE not in places:
        raise KeyError(f"{prompt.id}: the request shows two replies and the "
                       f"prompt has a place for one")
    values = {name: json.dumps(one, ensure_ascii=False,
                               separators=(",", ":"))
              for name, one in zip((EXAMPLE_PLACE, NOTHING_PLACE), pair)}
    # A place the request shows no reply for (the flow's switch for the
    # empty example is off, or the request has no example) is empty text.
    return prompt.render(**{name: values.get(name, "")
                            for name in (EXAMPLE_PLACE, NOTHING_PLACE)
                            if name in places})


def ask_in_grammar(client, prompt, conversation: list, shape: dict,
                   document_id: int, where: str, key: str, /,
                   example: Optional[dict] = None, **noted):
    """One request of the harvest, in the step that asks its kind
    (`in_home`); see `_ask_in_grammar`."""
    with in_home(noted.get("asked") if where == "follow" else where):
        return _ask_in_grammar(client, prompt, conversation, shape,
                               document_id, where, key, example, **noted)


def _ask_in_grammar(client, prompt, conversation: list, shape: dict,
                    document_id: int, where: str, key: str,
                    example: Optional[dict] = None, **noted):
    """One request of the harvest: the reply as a dict, "cut_off" when it
    did not fit its room, or None when it could not be read. The prompt
    shows *example*, the reply this request asks for (`system_text`); the
    request is its prompt and *conversation*, one message (owner decisions
    2026-11-08: no request is a conversation).

    Asked again with the cause when the reply is no JSON object, or one
    without a key its schema requires (`_lacking`, rule
    `missing_key_asks_again`), as many such replies as the number `replies`
    says at most, as every request of the stage is (the answer shown to the
    model that wrote it where the rule `retry_shows_reply` is on); a reply
    cut off at its limit is not rescued. Each answer is traced
    as `<where>_ask` with *noted*.

    A 429, a 5xx or a timeout is asked again until the server answers or
    the run halts (`Failures.attempts`, owner decision 2026-11-09), a
    refusal `refusal_retry_most` times at most; a request whose last
    attempt ended on one was never answered, so its document is noted
    (`UNSERVED`) and goes unstamped, as for every request of the run. One
    that timed out is asked again with the time a repeat gets
    (`_repeating`), whatever client it was handed, as every request of the
    harvest is.
    """
    client = _repeating(client)
    wanted = request_wanted(where)
    text = system_text(prompt, example)
    failures = Failures(document_id)
    for attempt in failures.attempts():
        limit = request_room(text, conversation, wanted)
        if limit is None:
            return "cut_off"
        started = time.time()
        try:
            with _for(document_id):
                response = send_request(client, text, conversation, limit,
                                        failures.faults, shape)
            failures.answered()
            reply = response.choices[0]
            usage = getattr(response, "usage", None)
            _observe_usage(usage)
            box = addressed_map.asking_box()
            trace.event(f"{where}_ask", document_id, attempt=attempt,
                        ms=int((time.time() - started) * 1000),
                        prompt_tokens=getattr(usage, "prompt_tokens", None),
                        completion_tokens=getattr(usage, "completion_tokens",
                                                  None),
                        **({"box": box} if box else {}), **noted)
            answer = _loads_object(
                reply.message.content, document_id, where,
                closes=getattr(reply, "finish_reason", None) != "length")
            missing = (_lacking(answer, shape)
                       if rules.get("missing_key_asks_again") else None)
            if isinstance(answer, dict) and missing is None:
                return answer
            failures.fault()
            cause, correction = _reply_fault(reply, limit,
                                             key=missing or key)
            trace.event("error", document_id, where=where,
                        kind="unreadable", cause=cause, attempt=attempt)
            if cause == "cut_off":
                kept = (mend.rescued(reply.message.content, key)
                        if rules.get("cut_off") == "rescue" else None)
                if kept is None:
                    return "cut_off"
                # The complete entries stay, and the request still counts as
                # cut off: it is noted as one.
                trace.event("error", document_id, where=where,
                            kind="cut_off_rescued", rule="cut_off",
                            kept=len(next(iter(kept.values()))))
                return kept
            if rules.get("retry_shows_reply"):
                conversation = conversation + [
                    {"role": "assistant",
                     "content": reply.message.content or ""},
                    {"role": "user", "content": correction}]
        except Exception as exc:
            log.warning("   %s %s attempt %d failed: %s", where, document_id,
                        attempt, exc)
            trace.event("error", document_id, where=where, kind="exception",
                        attempt=attempt, detail=str(exc)[:300])
            if not failures.failed(exc):
                break
    failures.given_up()
    return None


def worded(words: str, payload: dict) -> str:
    """A message: its words, then what it shows as JSON."""
    data = json.dumps(payload, ensure_ascii=False, indent=2)
    return f"{words}\n\n{data}" if words else data


def run_each(jobs: list, run: Callable) -> list:
    """*run(job)* for each of *jobs*, side by side on the run's threads
    (`AHEAD`) where it has them, the results in the order of the jobs. Only
    the caller waits: no job waits for another, so the threads never wait
    for themselves. A job that fails takes back every job not yet begun."""
    jobs = list(jobs)
    if AHEAD is None or len(jobs) < 2:
        return [run(job) for job in jobs]
    # Each job runs in the context of its caller: the box of the flow
    # asking (`addressed.ASKING`) goes with it into the trace.
    futures = [AHEAD.submit(contextvars.copy_context().run, run, job)
               for job in jobs]
    try:
        return [future.result() for future in futures]
    except BaseException:
        for future in futures:
            future.cancel()
        raise


# What a request of the harvest names its reply's list or answer by, for the
# sentence that tells the model what was missing (`_reply_fault`).
ASK_KEYS = {"transcribe": "caption", "find": "found", "docfield": "found",
            "coord": "at", "search": "at", "list": "entry",
            "names": "entry", "check": "about", "work": "found",
            "phrase": "phrase"}


def request_prompt(parts, payload: dict, shape: Optional[dict] = None):
    """The prompt of one request: what every request of its kind is told,
    and the part of each field its payload carries (`thread.Parts.system`,
    owner decision 2026-11-07: no request is told about a field it does not
    carry); where its reply may fetch (*shape* offers "more"), the part
    `more`, and `get_image` where it may ask for a figure's picture (owner
    decision 2026-11-12)."""
    return parts.system(set(payload.keys()) | reply_offers(shape))


def reply_offers(shape: Optional[dict]) -> set:
    """{"more", "get_image"} as far as the reply form *shape* offers them:
    what a request's prompt tells about besides its payload."""
    schema = ((shape or {}).get("json_schema") or {}).get("schema") or {}
    more = (schema.get("properties") or {}).get("more")
    if not isinstance(more, dict):
        return set()
    gets = (((more.get("items") or {}).get("properties") or {})
            .get("get") or {}).get("enum") or ()
    return {"more"} | ({"get_image"} if addressed_map.IMAGE in gets
                       else set())


def make_asks(profile=None) -> Optional[addressed_map.Asks]:
    """The requests of the harvest (`addressed.Asks`), each with a prompt of
    its own and its payload as one message, no conversation (owner decisions
    2026-11-08) where the rule `conversation` keeps none (`messages`); None
    where the profile writes one of their prompts not,
    those of `addressed.OPTIONAL` aside. A request asked again
    (`follow`) goes under the prompt of the request it follows, its words
    after the payload. The sentence a search goes with is a request of its
    own (`phrase`, owner decision 2026-11-09), under the prompt the
    document's search sentences are written with."""
    loaded: dict = {}
    for kind, prompt_id in addressed_map.PROMPT_IDS.items():
        try:
            loaded[kind] = thread_map.cut(prompts.load(prompt_id, profile))
        except (FileNotFoundError, LookupError):
            # Writing out the figures prepares a document; the flow says
            # where its prompt is missing (`flow.prompt_problems`).
            if kind not in addressed_map.OPTIONAL and kind != "transcribe":
                return None
    client = _client()

    def follow_words() -> str:
        # The words after a follow-up's payload, of the way each group of
        # them has in the step of the request it follows (`thread.chosen`).
        return thread_map.chosen(loaded["follow"].common,
                                 loaded["follow"].prompt.id).strip()

    def message(payload: dict) -> str:
        return json.dumps(own(payload), ensure_ascii=False, indent=1)

    def own(payload: dict) -> dict:
        return {key: value for key, value in payload.items()
                if key not in ("conversation", addressed_map.PICTURE)}

    def messages(payload: dict, content: str) -> list:
        """The messages of a request: where the rule `conversation` keeps
        the questions asked before about the same value
        (`addressed.Reader._talk`), each of them and its answer as a
        message of its own, then this request's (owner decision
        2026-11-07: one question a message, a follow-up after it). A
        request that carries a figure's picture (`addressed.PICTURE`,
        owner decision 2026-11-12) sends it beside its message."""
        out = []
        for one in payload.get("conversation") or ():
            asked = message(one["sent"])
            if "follow_up" in one:
                asked = f"{asked}\n\n{follow_words()}"
            out += [{"role": "user", "content": asked},
                    {"role": "assistant", "content": json.dumps(
                        one["answer"], ensure_ascii=False)}]
        picture = payload.get(addressed_map.PICTURE)
        part = _image_part(picture) if picture else None
        if part is not None:
            return out + [{"role": "user", "content": [
                {"type": "text", "text": content}, part]}]
        return out + [{"role": "user", "content": content}]

    def asker(kind: str) -> Callable:
        parts = loaded[kind]

        def ask(payload, document_id, /, shape, example, **noted):
            return ask_in_grammar(
                client, request_prompt(parts, own(payload), shape),
                messages(payload, message(payload)),
                shape, document_id, kind, ASK_KEYS[kind], example, **noted)
        return ask

    def follow(kind, payload, document_id, /, shape, example, **noted):
        content = f"{message(payload)}\n\n{follow_words()}"
        return ask_in_grammar(
            client, request_prompt(loaded[kind], own(payload), shape),
            messages(payload, content),
            shape, document_id, "follow", ASK_KEYS[kind], example,
            **{**noted, "asked": kind})

    def optional(kind: str) -> Optional[Callable]:
        return asker(kind) if kind in loaded else None

    own_cut: dict = {}

    def own_parts(prompt):
        # A general step's prompt: a prompt file of the profile, or a text
        # of the step's own, cut at its markers like every prompt.
        key = json.dumps(prompt, sort_keys=True, ensure_ascii=False)
        if key not in own_cut:
            own_cut[key] = thread_map.cut(own_prompt(prompt, profile))
        return own_cut[key]

    def general_ask(prompt, payload, document_id, /, shape, example,
                    follow=False, kind=None, **noted):
        # A step's own prompt: of a step of the page's own, or of a
        # question whose prompt was changed, which keeps the name of its
        # kind in the log (owner decision 2026-11-12 evening).
        from . import general
        parts = own_parts(prompt)
        system = request_prompt(parts, own(payload), shape)
        text, payload = general.in_prompt(system.text, payload)
        system = replace(system, text=text)
        content = message(payload)
        if follow:
            content = f"{content}\n\n{follow_words()}"
        kind = kind or "own"
        key = ASK_KEYS.get(kind) or general.first_key(
            ((shape or {}).get("json_schema") or {}).get("schema") or {})
        return ask_in_grammar(
            client, system, messages(payload, content), shape, document_id,
            "follow" if follow else kind, key, example,
            **({**noted, "asked": kind} if follow else noted))
    return addressed_map.Asks(
        find=asker("find"), docfield=asker("docfield"), coord=asker("coord"),
        list=asker("list"), names=optional("names"),
        search=asker("search"), follow=follow, check=optional("check"),
        work=optional("work"), phrase=optional("phrase"),
        own=general_ask, transcribe=optional("transcribe"))


def own_prompt(prompt, profile=None):
    """The prompt of a general step: the prompt file *prompt* names
    ("extraction/find"), or {"text": ...} a text of the step's own, made as
    a prompt file of the profile would be (`prompts.made`)."""
    from docpipe.profile import active_profile
    profile = profile or active_profile()
    if isinstance(prompt, dict):
        text = str(prompt.get("text") or "")
        return prompts.made("own/step", profile, profile,
                            profile.prompts_dir / "own" / "step.md", text)
    return prompts.load(str(prompt), profile)


def image_path_of(source, image_root: Optional[Path]) -> Optional[str]:
    """Where a figure's crop is, None where the run sends no image or the
    figure has none."""
    if source.owner_kind != "figure" or not source.image_path \
            or not attach_images():
        return None
    return str(Path(image_root) / source.image_path) if image_root \
        else source.image_path


def transcript_fingerprint(profile) -> Callable:
    """fingerprint(told=None): what names the prompt and model that wrote a
    kept transcription of a figure (`addressed.Transcripts`, owner decision
    2026-11-08, e), told where it is read, in the step that writes out the
    figures, whose model it names; *told* the step's own prompt, inputs and
    answer form where they are not its preset's
    (`engine.Engine.writes_figures`). "" where the profile writes no prompt
    for it."""
    try:
        standard = prompts.load(addressed_map.PROMPT_IDS["transcribe"],
                                profile)
    except (FileNotFoundError, LookupError):
        standard = None

    def fingerprint(told: Optional[dict] = None) -> str:
        told = dict(told or {})
        prompt = own_prompt(told.pop("prompt"), profile) \
            if "prompt" in told else standard
        if prompt is None:
            return ""
        rest = "|" + json.dumps(told, sort_keys=True, ensure_ascii=False) \
            if told else ""
        return hashlib.sha256(
            f"{prompt.sha256}|{llm_model()}{rest}".encode("utf-8")
        ).hexdigest()[:16]
    return fingerprint


def search_budget() -> tuple:
    """(pieces, shares, per request) of every search of the run: how many
    pieces a search for an open coordinate or a field the document has
    once shows, how many of them each kind of passage gets first, and how
    many a request shows (owner decisions 2026-11-09: 50, 20 of tables, 15
    of figures, 15 of text, 5 a request), from the run's flow (`NUMBERS`);
    a pass that reads to the end shows every piece (`read_to_end`)."""
    taken = numbers()
    pieces = REST_TO_END if TO_END else taken.search_pieces
    return pieces, taken.shares(), taken.search_per_request


def make_reader(spec: Spec, profile, order: Callable, search_order: Callable,
                probes: Optional[Callable] = None,
                rerank: Optional[Callable] = None,
                context: Optional[Callable] = None,
                image_of: Optional[Callable] = None):
    """The reading of a document piece by piece (`addressed.Reader`), or
    None where its spec names no groups or the profile writes no prompts
    for it. What is asked once of a plan beside its fields
    (`Spec.plan_fields`) and the field that names other works
    (`Spec.works`) come from the spec (owner decision 2026-11-10); how much
    a search shows (`search_budget`) and every other number that bounds the
    reading from the run's flow (`NUMBERS`)."""
    if not spec.groups:
        return None
    asks = make_asks(profile)
    if asks is None:
        return None
    pieces, shares, per_request = search_budget()
    return addressed_map.Reader(
        spec, asks, order, search_order=search_order, rerank=rerank,
        probes=probes, known=row_context,
        plan_fields=spec.plan_fields, works=spec.works,
        frame_slots=frame_slots_of(spec), each=run_each, trace=trace.event,
        budget=pieces, shares=shares, per_request=per_request,
        context=context, numbers=numbers(),
        flow=flow_map.tree_of(profile), image_of=image_of)


class Persistent:
    """A reranker whose every order is asked again until it answers or the
    run halts, a refused one as often as the flow's `replies` says at most
    (`persistently`)."""

    def __init__(self, reranker):
        self.reranker = reranker
        self.order = persistently("rerank", reranker.order)


def make_chunk_reranker() -> Optional[Callable]:
    """() -> one thread's reranker of the pieces of a plan, which scores
    every piece it is given (`rerank.Reranker`), asked again until it
    answers (`Persistent`), or None where the run is given no reranker
    server (rule `rerank_base_url`). How many pieces it scores is the rule
    `rerank_chunk_pool`, read when it orders."""
    from docpipe.inference import rerank as rerank_map
    if not rerank_map.base_url():
        return None
    return lambda: Persistent(rerank_map.Reranker(
        pool_rule="rerank_chunk_pool"))


def make_harvest(spec: Spec, *, db_path: Optional[Path], out: Path,
                 image_root: Optional[Path], profile, every: Callable,
                 spec_for: Optional[Callable] = None,
                 rank: Optional[Callable] = None,
                 reranker: Optional[Callable] = None):
    """The harvest of a document piece by piece (`surveyed.SurveyedHarvest`)
    as a run and a probe make it: the order of the pieces by the reranker
    (*reranker*, `make_chunk_reranker`) and the search over passages
    (*rank*, `make_more_sources` with its reranker), a field's search
    sentences (`make_seek_probes`), the figures transcribed once and kept
    under *out* (`transcripts/`), the orders kept there too (`survey/`), and
    the numbers of the profile's flow (`take_flow`: the lines of a piece
    among them). *every(
    document_id, exclude)* is the plan's passages in its order. A search
    that fails is asked again until it answers, a refused one as often as
    the flow's `replies` says (`persistently`)."""
    if rank is not None:
        rank = persistently("search", rank)
    order, search_order, rerank = addressed_map.make_order(reranker, rank)
    component = (profile.component if profile is not None
                 else (lambda stage, name: None))
    context_of = document_context_of(
        db_path, component("extraction", "document_context"))
    seek = make_seek_probes(context_of)
    # The figures are written out by the step of the flow that does it
    # (`engine.Engine.writes_figures`) and kept under the harvest.
    transcripts = addressed_map.Transcripts(
        None, Path(out) / "transcripts", transcript_fingerprint(profile),
        lambda source: addressed_map.image_key(image_path_of(source,
                                                             image_root)))
    numbers = take_flow(profile)
    orders = addressed_map.Orders(order, seek, Path(out) / "survey",
                                  trace=trace.event,
                                  written=sentences_written(profile))
    log.info("harvest: pieces of %d lines, figures transcribed once under "
             "%s, orders kept in %s", numbers.piece_lines,
             Path(out) / "transcripts", Path(out) / "survey")
    return surveyed_map.SurveyedHarvest(
        spec,
        lambda doc_spec: make_reader(
            doc_spec, profile, order, search_order, seek, rerank, context_of,
            # The picture a coordinate request may ask for: the figure's
            # crop where the run attaches images (owner decision
            # 2026-11-12).
            lambda source: image_path_of(source, image_root)),
        lambda document_id: every(document_id, set()),
        spec_for=spec_for, transcripts=transcripts, orders=orders,
        numbers=numbers, each=run_each, trace=trace.event)


def frame_slots_of(spec: Spec) -> list:
    """The coordinates of the plan's frame, which its base and target years
    date a value by: the pair of each group that names one
    (`spec.Group.paired`)."""
    return [slot for group in spec.groups.values() if group.pair
            for slot in fields.frame_slots(spec, group.paired)]


def dates_by_plan(spec: Spec) -> bool:
    """Does the spec date a value by the plan's own years: has its frame a
    year?"""
    return any(slot.kind == fields.NUMBER for slot in frame_slots_of(spec))


# ---------------------------------------------------------------------------
# Harvest: one source + one parameter -> the model's claimed tuples
# ---------------------------------------------------------------------------

# Seconds without any answer from the server before the run ends. A request
# that finds the server gone fails, waits and asks again, and a batch counts
# as unreachable only once every one of its requests has given up: when vLLM
# died on the first corpus run with the adaptive limit, the runner took 78
# minutes to notice.


def probe_server(base_url: str = None,
                 timeout: Optional[float] = None) -> bool:
    """Whether the server answers `GET {base_url}/models` at all.

    Any reply below 500 counts: a server that refuses the key is still there.
    The time it waits is the rule `server_probe_timeout_s`.
    """
    import urllib.error
    import urllib.request
    if timeout is None:
        timeout = rules.get("server_probe_timeout_s")
    request = urllib.request.Request((base_url or llm_base_url()).rstrip("/")
                                     + "/models")
    if llm_api_key():
        request.add_header("Authorization", f"Bearer {llm_api_key()}")
    try:
        with urllib.request.urlopen(request, timeout=timeout):
            return True
    except urllib.error.HTTPError as exc:
        return exc.code < 500
    except Exception:
        return False


def watch_server(on_dead: Callable, *, probe: Callable = probe_server,
                 every: Optional[float] = None,
                 dead_after: Optional[float] = None,
                 clock: Callable = time.monotonic,
                 sleep: Callable = time.sleep) -> threading.Thread:
    """A daemon thread that calls *on_dead(seconds)* once the server has not
    answered for *dead_after* seconds (rule `server_dead_after_s`), probing
    every *every* (rule `server_probe_every_s`), then stops watching."""
    def watch() -> None:
        silent_since = None
        while True:
            # Read at each look: the rules may be changed while the run goes.
            sleep(rules.get("server_probe_every_s") if every is None
                  else every)
            limit = (rules.get("server_dead_after_s") if dead_after is None
                     else dead_after)
            if probe():
                silent_since = None
                continue
            now = clock()
            if silent_since is None:
                silent_since = now
                log.warning("extraction: the model server did not answer the "
                            "health probe")
            elif now - silent_since >= limit:
                on_dead(now - silent_since)
                return

    thread = threading.Thread(target=watch, name="server-watch", daemon=True)
    thread.start()
    return thread


_SHARED_HTTP = None
_SHARED_HTTP_LOCK = threading.Lock()


def shared_http(limit=None):
    """The one connection pool every request of the run goes out through.

    Each kind of request has a client of its own (finding, coordinates,
    lists, the search, the check, ...), and each client used to keep a
    pool of its own:
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
            most = rules.get("http_connections") or getattr(
                limit if limit is not None else LIMIT, "maximum", None)
            _SHARED_HTTP = httpx.Client(
                limits=httpx.Limits(max_connections=most,
                                    max_keepalive_connections=most),
                timeout=llm_timeout())
        return _SHARED_HTTP


def _client():
    """The one client shape this stage uses, for the provider it is set to.
    A request that timed out is repeated with the time of a repeat
    (`_repeating`). Every client of the run sends through one connection
    pool (`shared_http`)."""
    shared = ({"http_client": shared_http()}
              if providers.provider("llm") == providers.OPENAI_COMPATIBLE
              else {})
    client = providers.client("llm", base_url=llm_base_url(),
                              api_key=llm_api_key(), timeout=llm_timeout(),
                              max_retries=0, **shared)
    if SCHEDULER is None:
        # Several model names on one endpoint share their places as the chat's
        # do. One model and one place is the plain client.
        from ..inference import pool
        return _repeating(pool.over(client))
    return _repeating(scheduler.Scheduled(client, SCHEDULER))


def _repeating(client):
    """*client*, whose repeat of a request that timed out gets
    `repeat_timeout_s` (`scheduler.Repeats`, read where the request is
    sent): every request of the stage, made here or handed in."""
    return scheduler.repeating(client)


def _for(document_id):
    """The requests sent inside belong to this document; the sweep's ticket,
    if the calling thread carries one, stays."""
    return scheduler.on_behalf(document_id, scheduler.current()[1])


def _loads_object(raw_text, document_id=None, where: str = "",
                  closes: bool = True) -> Optional[dict]:
    """The one JSON object a reply was asked for, or None.

    Strict, and that is the point of it (decided on 2026-09-12). Every
    softener this used to carry -- closing the brackets a reply stopped
    short of, reading one object out of a longer text, stripping fences and
    think blocks -- turned a defective answer into a value that then stood
    in the harvest saying "read" with nothing under it. A reply that is not
    exactly the object that was asked for is asked again, and the retry says
    what was wrong with it (`_reply_fault`). Only the rule `repair_replies`
    brings a repair back, for the step that asks; a reply that was read
    after one is noted in the request log (`repaired`, with the repairs and
    the rule), for the document *document_id* and the request *where*.
    *closes* is False for a reply that was cut off: it is never closed.
    """
    text = (raw_text or "").strip()
    if not text:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        kinds = rules.get("repair_replies")
        if not kinds:
            return None
        data, used = mend.repaired(text, kinds, closes)
        if data is not None:
            trace.event("repaired", document_id, where=where, repairs=used,
                        rule="repair_replies")
        return data
    return data if isinstance(data, dict) else None


_DECODER = json.JSONDecoder()


_UNPARSABLE_SHOWN = 0


def _unparsable(reply) -> str:
    """Why a reply could not be read, for the first few that happen.

    A pilot lost 1093 of 16102 harvests to "reply carried no 'tuples' list"
    and the log could not say whether the model answered something else, was
    cut off mid-reasoning, or returned nothing at all. Bounded: the point is a
    handful of examples, not a second copy of the run in the log.
    """
    global _UNPARSABLE_SHOWN
    if _UNPARSABLE_SHOWN >= rules.get("show_unparsable"):
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


def _excerpt() -> tuple:
    """(characters before, after, of foreign text) of a broken answer the
    question asked again shows the model (rule `fault_excerpt_chars`)."""
    said = rules.get("fault_excerpt_chars")
    try:
        return said["before"], said["after"], said["foreign"]
    except KeyError as exc:
        raise ValueError(f"fault_excerpt_chars names no {exc}: it gives "
                         f"before, after and foreign") from None


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
            before, after, _foreign = _excerpt()
            around = text[max(start, exc.pos - before):exc.pos + after]
            return "syntax", say(
                "syntax", position=exc.pos - start, message=exc.msg,
                around=around) + shape
        extra = (text[:start] + text[end:]).strip()
        return "outside_text", say(
            "outside_text", extra=extra[:_excerpt()[2]]) + shape
    if not isinstance(data, dict):
        return "not_an_object", say(
            "not_an_object", kind=type(data).__name__) + shape
    if key and not isinstance(data.get(key), list):
        which = ("key_missing" if data.get(key) in (None, "")
                 or key not in data else "key_not_a_list")
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


_IMAGES: dict = {}
_IMAGES_LOCK = threading.Lock()


def _image_data_url(path: str) -> Optional[str]:
    """The crop, read, downscaled and base64'd — once per file, size and
    format per run.

    Every parameter asks the same table again, so the same PNG used to be
    reopened, resampled and re-encoded once per parameter. Bounded
    (`image_cache_crops`, the oldest leave first) because a corpus run meets
    thousands of crops and each one is a megabyte of base64. The key holds
    what the image depends on, the size (`image_max_side`) and the format
    (`image_format`) of the step that asks, so that a step with another size
    gets its own image and not the first one made.

    PNG, not JPEG, unless the rule says so: these crops are synthetic
    graphics with thin rules and small axis labels, exactly what JPEG
    artefacts blur first — and a blurred digit is the failure this whole
    stage exists to avoid. Deliberately not imported from llm_client, which
    binds the QA prompts at import time.
    """
    import base64
    import io
    side, kind = image_max_side(), rules.get("image_format")
    key = (path, side, kind)
    with _IMAGES_LOCK:
        if key in _IMAGES:
            return _IMAGES[key]
    try:
        from PIL import Image
        img = Image.open(path)
        if max(img.size) > side:
            img.thumbnail((side, side))
        if kind == "jpeg" and img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format=kind.upper())
    except Exception as exc:
        log.warning("   crop not attachable (%s): %s", path, exc)
        return None
    url = (f"data:image/{kind};base64,"
           + base64.b64encode(buf.getvalue()).decode())
    with _IMAGES_LOCK:
        most = rules.get("image_cache_crops")
        while most and len(_IMAGES) >= most:
            _IMAGES.pop(next(iter(_IMAGES)))
        if most:
            _IMAGES[key] = url
    return url


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
    token_usage.add(llm_model(), input_tokens=prompt,
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
    box = addressed_map.asking_box()
    trace.event(f"{stage}_ask", document_id, attempt=attempt,
                ms=int((time.time() - started) * 1000),
                prompt_tokens=getattr(usage, "prompt_tokens", None),
                completion_tokens=getattr(usage, "completion_tokens", None),
                **({"box": box} if box else {}), **noted)


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
    client = _client()
    step = step_asking("review_marks", "review")

    def ask(row: dict, shown: list, parameter, slots) -> Optional[dict]:
        # Asked with the values of the box that is the home of the second
        # reading (`in_home`), whoever calls.
        with in_home("review"):
            return _ask(row, shown, parameter, slots)

    def _ask(row: dict, shown: list, parameter, slots) -> Optional[dict]:
        # The prompt is composed where it is used: it names rules (the
        # least characters of a quote) the box may set for itself.
        prompt, inputs = step_parts(step, REVIEW_PROMPT_ID)
        payload = json.dumps(shows_map.apart(inputs, {"row": SimpleNamespace(
            row=row, shown=shown, parameter=parameter, slots=slots)}),
                             ensure_ascii=False, indent=2)
        # The crops ride along exactly as they do for a field request: a
        # transcription is a model's reading of a picture, and a review of a
        # transcription alone would be a review of that first reading.
        content: object = payload
        parts = [{"type": "text", "text": payload}]
        for index, source in enumerate(shown):
            path = source.image_path
            if not (path and attach_images()):
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
        for attempt in failures.attempts():
            limit = request_room(prompt.text, conversation,
                                 request_wanted("review"))
            if limit is None:
                log.warning("   review: the prompt leaves less than %d "
                            "answer token(s) in a window of %d -- not sent",
                            least_answer_tokens(), model_window())
                break
            started = time.time()
            try:
                response = send_request(
                    client, prompt.text, conversation, limit,
                    failures.faults,
                    reply_grammar("review_reply", replies.review(slots)))
                failures.answered()
                reply = response.choices[0]
                _observe_usage(getattr(response, "usage", None))
                _asked("review", (row.get("provenance") or {}).get(
                    "document_id"), response, attempt=attempt,
                    started=started, parameter=getattr(parameter, "uri", None))
                answer = _loads_object(
                    reply.message.content, (row.get("provenance") or {}).get(
                        "document_id"), "review")
                if isinstance(answer, dict):
                    return answer
                # One row and two passages: there is nothing here to split, so
                # a reply that did not fit is told to quote less rather than
                # to answer for fewer rows.
                failures.fault()
                cause, correction = _reply_fault(
                    reply, limit, shorter=say("shorter_review"))
                log.warning("   review attempt %d: %s reply%s",
                            attempt, cause, _unparsable(reply))
                if rules.get("retry_shows_reply"):
                    conversation.append({
                        "role": "assistant",
                        "content": reply.message.content or ""})
                    conversation.append({"role": "user",
                                         "content": correction})
            except Exception as exc:
                log.warning("   review attempt %d failed: %s", attempt, exc)
                if not failures.failed(exc):
                    break
        failures.given_up()
        return None

    return ask


def make_completer(profile, db: Optional[Path] = None) -> Optional[Callable]:
    """The step that completes a document's rows from outside the document,
    after its fold and its computing (`profiles/<name>/completion.py:
    complete(report, spec, db=)`, *db* the run's database, for what the
    profile looks up there): `completed(report, spec)`, which adds what it
    found to the report and returns what it came to, traced as `completion`,
    or None where nothing was open. None where the profile has no such step
    or the flow has its box (`catalogue`) off or not at all.
    """
    complete = profile.component("completion", "complete")
    if complete is None \
            or not flow_map.box_on(flow_map.tree_of(profile), "catalogue"):
        return None

    def completed(report, spec) -> Optional[dict]:
        outcome = complete(report, spec, db=db)
        if outcome:
            trace.event("completion", report.document_id, **outcome)
        return outcome
    return completed


_COMPUTE_POOLS: dict = {}
_COMPUTE_POOLS_LOCK = threading.Lock()


def compute_pool() -> ThreadPoolExecutor:
    """The threads the calculation questions of the whole run take turns on,
    as many as the rule `compute_parallel` says now (one pool for each size
    it has had)."""
    size = int(rules.get("compute_parallel"))
    with _COMPUTE_POOLS_LOCK:
        if size not in _COMPUTE_POOLS:
            _COMPUTE_POOLS[size] = ThreadPoolExecutor(
                max_workers=size, thread_name_prefix="compute")
        return _COMPUTE_POOLS[size]


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
    (*pages_of*, `lookup.two_pages`), and a question that takes a number
    (`Question.take`) may take it from whatever the request showed: a
    passage, its title, a hit's line or title (owner decision 2026-11-05).
    *rank(document_id, probes, exclude)* is the plan ranked for a sentence,
    which "similar" lists (`make_more_sources` in a run); without it that
    search finds nothing.
    """
    from docpipe.inference import code_exec

    open_questions = profile.component("compute", "questions")
    if open_questions is None or code_rounds() < 1 \
            or not flow_map.compute_on(flow_map.tree_of(profile)):
        return None
    if not code_exec.is_enabled():
        # The flow computes and the run has no sandbox: said, not left out
        # quietly (owner decision 2026-11-13, point 9).
        log.warning("compute: the flow computes, but no sandbox is set "
                    "(CODE_EXEC_URL): nothing is computed in this run")
        return None
    same = profile.component("compute", "same")
    # The question is asked as its step says: its prompt, and the inputs
    # its first message is built from (owner decision 2026-11-12 evening).
    try:
        prompt, inputs = step_parts(step_asking("computed", "compute",
                                                profile),
                                    computing.COMPUTE_PROMPT_ID)
    except (FileNotFoundError, LookupError):
        return None
    # A prompt that lacks the words of a follow-up stops the run here, not
    # the step quietly.
    parts = thread_map.cut(prompt, follows=computing.FOLLOWS)
    client = _client()

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
        budget = (lookup_map.two_pages(
            order, pages_of(document_id) if pages_of else None,
            rules.get("compute_fetch_pages")) if order else None)
        runs: list = []
        noted = {"taken": 0, "untaken": 0, "misquoted": 0, "rejected": 0,
                 "reason": None}
        faults = 0

        # The question is one conversation (owner decisions 2026-11-07):
        # its first message shows what is wanted, the numbers and their
        # passages; what it fetched, a number it took and its code's output
        # follow the answer that asked for them, each with what is new.
        first = {**shows_map.apart(inputs, {"question": SimpleNamespace(
            question=question, shown=shown, fetched=gathered.sources)}),
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
        while attempt < (reply_limit() + code_rounds()
                         + rules.get("compute_extra_attempts")):
            attempt += 1
            if stop is not None and stop.is_set():
                return ended("stopped")
            limit = request_room(system, conversation,
                                 request_wanted("compute"))
            if limit is None:
                return ended("too_long")
            shape = replies.compute(
                computing.labels(question),
                more=reading_map.more_schema() if order else None,
                take=question.taking if question.take else None,
                quote=question.cites)
            started = time.time()
            try:
                with _for(document_id):
                    response = send_request(
                        client, system, conversation, limit, faults,
                        reply_grammar("compute_reply", shape, always=True))
            except Exception as exc:
                log.warning("   compute %s attempt %d failed: %s",
                            document_id, attempt, exc)
                trace.event("error", document_id, where="compute",
                            kind="exception", attempt=attempt,
                            detail=str(exc)[:300])
                if not failures.failed(exc) or halted():
                    break
                # The server's failure takes no round (owner decision
                # 2026-11-09: asked again until it answers or the run
                # halts).
                failed += 1
                attempt -= 1
                failures.wait(failed)
                continue
            failures.answered()
            reply = response.choices[0]
            _observe_usage(getattr(response, "usage", None))
            _asked("compute", document_id, response, attempt=attempt,
                   started=started)
            said = reply.message.content
            code = _parse_action(said)
            if code and len(runs) < code_rounds():
                with sandbox_slots():
                    out = code_exec.run_code(code, context=computing.context(
                        question, shown, gathered.sources))
                if out.get("sandbox"):
                    # The sandbox failed, not the code: the model is not
                    # told, the question ends without a row and the log
                    # says so (owner decision 2026-11-13, point 9).
                    log.warning("   compute %s: the sandbox failed (%s), "
                                "question %s left without a row",
                                document_id, out.get("error"),
                                getattr(question, "label", question))
                    trace.event("error", document_id, where="compute",
                                kind="sandbox", attempt=attempt,
                                detail=str(out.get("error"))[:300])
                    return ended("sandbox_failed")
                runs.append({"code": code,
                             "stdout": (out.get("stdout") or "")[
                                 :rules.get("code_output_chars")],
                             "ok": bool(out.get("ok")),
                             "error": out.get("error")})
                trace.event("code", document_id, attempt=attempt, **runs[-1])
                told(said, _compute_reply(runs[-1], "compute_output"))
                continue
            answer = _loads_object(said)
            if isinstance(answer, dict) and order and gathered.fetch(
                    answer.get("more"), order, passages, budget):
                # What it fetched follows the answer that asked for it, as in
                # the search: a round that brings something new is no
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
                # or title, each under the passage it was shown with; where
                # the rule `check_quote_shown` is off, of the whole plan
                # (owner decision 2026-11-12).
                source = reading_map.passage_of(taken, [
                    *shown, *(one for each in shown
                              for one in reading_map.shown_as(
                                  each, (each.provenance or {}).get("title"))),
                    *gathered.evidence(passages)], order)
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
        # Each question in the context of the compute box of the flow, so
        # that its requests name it in the trace (`addressed.ASKING`).
        computing_box = next((node.get("id") for node in flow_map.tree_of(
            profile) if isinstance(node, dict)
            and rules.step_kind(node) == "compute"), None)
        with addressed_map.asking(addressed_map.Asking(computing_box)):
            pool = compute_pool()
            asked = [(question, pool.submit(
                contextvars.copy_context().run, ask, question, items,
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


def step_models(profile=None) -> dict:
    """{step id: model} of the steps of the flow that name a model of their
    own (rule `model`), for the check before the run
    (`llm_preflight.assert_step_models`). A step that is off asks
    nothing, so the model it names is not needed."""
    out: dict = {}
    for node, _frames in flow_map.on(flow_map.tree_of(profile)):
        named = (node.get("rules") or {}).get("model")
        if named:
            out[str(node.get("id"))] = str(named)
    return out


def preflight(required: int, *, what: str, profile=None) -> bool:
    """The check before the run (rule `preflight_on`): the server offers
    the model, its window holds *required* tokens, and, where a *profile*
    is given, the models its steps name are offered too. True where the
    check ran, False where the rule has the run ask nothing."""
    if not rules.get("preflight_on"):
        return False
    set_model_len(assert_serving(llm_base_url(), llm_api_key(), llm_model(),
                                 required, what=what, flag="--max-model-len",
                                 role="llm"))
    if profile is not None:
        assert_step_models(llm_base_url(), llm_api_key(),
                           step_models(profile), role="llm")
    return True


def documents_at_once() -> int:
    """The most documents read at the same time (rule
    `documents_in_flight`), at least one."""
    return max(1, int(rules.get("documents_in_flight")))


def dead_server_ends_run(seconds: float) -> bool:
    """Does a server that has not answered for *seconds* end the run (rule
    `dead_server_ends_run`)? Where it does not, the run says so and goes
    on."""
    if rules.get("dead_server_ends_run"):
        return True
    log.error("extraction: the model server stopped answering — no "
              "reply for %.0f s; the run goes on (rule "
              "dead_server_ends_run)", seconds)
    return False


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
    if limit is None or rules.get("document_admission") == "ceiling_only":
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
    if pdf_root is None or not rules.get("locate_quotes"):
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
                while len(pages) >= rules.get("locate_cache_pages"):
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
        for page in candidates[:rules.get("locate_max_pages")]:
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

    The numbers of the flow are not among these keys. They belong to the
    pass that read with them and stand in its entry (`producer`), so a pass
    over a stored harvest neither carries them forward nor finds them
    changed.
    """
    return {"spec": spec_sha, "model": llm_model(), "anchors": anchors_sha,
            **prompts.versions(survey_prompt_ids()),
            **(fingerprints(spec) if spec is not None else {})}


def survey_prompt_ids(profile=None) -> tuple:
    """The prompts of a harvest piece by piece (`SURVEY_PROMPT_IDS`), and
    those of `addressed.OPTIONAL` the profile writes: the check of a find
    from another passage, the names request."""
    out = list(SURVEY_PROMPT_IDS)
    for kind in addressed_map.OPTIONAL:
        try:
            prompts.load(addressed_map.PROMPT_IDS[kind], profile)
        except (FileNotFoundError, LookupError):
            continue
        out.append(addressed_map.PROMPT_IDS[kind])
    return tuple(out)


def surveyed_flow(spec: Spec, profile=None) -> bool:
    """Whether a run can harvest piece by piece: its spec names groups. A
    spec without groups cannot be harvested (`main` stops on it).

    A spec with groups whose profile lacks a prompt of the harvest is a
    broken profile: the run stops and names the prompt, as `spec.load`
    stops at a broken group (owner decision 2026-11-04), before a request
    is sent rather than at the first plan's reading."""
    if not spec.groups:
        return False
    wanted = list(SURVEY_PROMPT_IDS)
    if names_asked(spec):
        wanted.append(addressed_map.PROMPT_IDS["names"])
    for prompt_id in wanted:
        try:
            prompts.load(prompt_id, profile)
        except (FileNotFoundError, LookupError) as exc:
            raise LookupError(
                f"the spec names groups, so the profile "
                f"{getattr(profile, 'name', None) or 'in use'!r} must write "
                f"every prompt of the harvest, and {prompt_id!r} is missing: "
                f"{exc}") from exc
    return True


def names_asked(spec: Spec) -> bool:
    """Whether a run asks names against a document's lists: its spec
    merges a field or a coordinate into a list of names (a scenario), or
    keeps a list of works (`Spec.works`)."""
    merged = any(getattr(p, "merged", None)
                 or any(getattr(a, "merged", None) for a in p.axes.values())
                 for p in spec.parameters)
    return bool(merged or getattr(spec, "works", None))


def producer(kind: str, model: Optional[str] = None) -> dict:
    """Who wrote into a harvest in one pass. Recorded, never compared.

    A harvest is written once and then written into: a top-up reads single
    coordinates again, possibly under another model or prompt, a second
    reading flags values, a remap moves answers without a model at all. The
    stamp's `model` names the first of them only. This is one entry of the
    list that names them all. A coordinate a top-up re-read points at its
    entry by position (`fields.PRODUCER`), so entries are never removed or
    reordered.

    A pass that asks a model also names the flow it read with (`take_flow`):
    `numbers`, every number in effect, a setting that won over the flow file
    among them, and `flow_file`, the sha256 of the flow's files; and the
    rules (`rules_file`, the sha256 of the rules files, `rules_set`, the
    rules a setting set). For a reader: a changed number or rule makes no
    harvest stale.
    """
    from docpipe import __version__
    entry = {"pass": kind, "docpipe": __version__,
             "utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    if model is not None:
        taken = rules.current()
        entry.update(model=model, provider=providers.provider("llm"),
                     prompts=prompts.versions(survey_prompt_ids()), flow=FLOW,
                     numbers=numbers().as_dict(),
                     flow_file=numbers().sha256,
                     rules_file=taken.sha256,
                     **({"rules_set": {
                         name: taken.values[name] for name, owner
                         in taken.owners.items()
                         if not owner.startswith(rules.FILE)}}
                        if any(not owner.startswith(rules.FILE)
                               for owner in taken.owners.values()) else {}))
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
              "producers": [producer(kind, llm_model())]}
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
# (the keys that stand for it where nothing finer is: rule
# `coarse_stamp_keys`).

# What a run really asks a document through, one key per question and per
# answer space: the ontology keys, and the only ones `stale` compares. Their
# presence is what licenses ignoring `spec`: with nothing finer in the stamp
# there is nothing else to go on.


def question_keys() -> tuple:
    """The keys of a stamp that decide whether a document is read again
    (rule `question_keys`, owner decision 2026-09-10)."""
    return tuple(rules.get("question_keys"))


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

    The ontology keys are compared (`question_keys`: one per parameter,
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
    keys = question_keys()
    detailed = any(k.startswith(keys) for k in current)

    def compared(key: str) -> bool:
        return key.startswith(keys) or (
            not detailed and key in rules.get("coarse_stamp_keys"))

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
    if force or not rules.get("skip_current") \
            or not (out_dir / f"{name}.jsonl").exists():
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


def not_happened(report, *, answered: Optional[int] = None,
                 lost: int = 0) -> Optional[tuple]:
    """(cause, requests, of) when the reading of this document did not happen.

    The three ways a document comes back with a file and no reading, counted
    in the unit the message needs: "unreachable" is the sources that never
    reached the server, of the sources the plan held; "no_reply" is the
    sources planned, when not one batch came back (`answered` is how many did;
    None means the caller does not track it and the count is not checked);
    "unserved" is the requests that ended on a 429, a 5xx, a timeout, a
    refusal asked `refusal_retry_most` times or a fault of our own code
    asked `other_errors_retry` times, `lost` of them
    noted beside the report and the rest in its sentinels. None when the
    reading happened. `finish_document` withholds the stamp on any of them
    and the pass for a new parameter writes nothing.
    """
    failed = [r for r in report.refusals
              if r.get("claim", {}).get("_harvest_failed")]
    unreachable = sum(1 for r in failed
                      if r.get("claim", {}).get("_why") == "unreachable")
    sources = max(report.owners_harvested, len(failed))
    if sources and unreachable > sources * rules.get("unreachable_share"):
        return "unreachable", unreachable, sources
    if sources and answered == 0 and not rules.get("stamp_without_reply"):
        return "no_reply", sources, sources
    lost += sum(1 for r in failed
                if r.get("claim", {}).get("_why") == "unserved")
    if lost and rules.get("unserved_unstamped"):
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
    the frame, a search sentence) ended on a 429 or a 5xx, timed out,
    were refused to the end or failed in our own code; the passages that
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
                               sources_of=getattr(report, "sources_of", None),
                               uncombed=getattr(report, "uncombed", ()))
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
            log.error("extraction: %s: %d request(s) not served, refused "
                      "to the end or failed in our own code — not stamped, "
                      "so a resume harvests it again", name, found)
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
    if not rules.get("write_checks_schema"):
        return 0
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

    A request shows the pieces of a search: as many as the flow says
    (`search_per_request`), each of its lines (`piece_lines`) and headings
    (`headings`) at the tokens the longest line takes (`window_line_tokens`);
    each piece may bring a crop. Each number counts at its largest in the
    flow, wherever a box sets one for itself.
    """
    payload = rules.get("window_floor_tokens")
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
        # A choice list the profile fills per document is not in the spec
        # file, so it cannot be measured there: its ceiling is the rule
        # `dynamic_list_tokens`.
        payload = max(payload, max(widest, together, asked)
                      // rules.get("window_words_per_token")
                      + rules.get("window_extra_tokens")
                      + (rules.get("dynamic_list_tokens") if dynamic else 0))
    per_request = most_of_number("search_per_request")
    lines = most_of_number("piece_lines") + most_of_number("headings")
    # Of each group of ways the longest: a step may choose any of them.
    words = len(thread_map.widest(prompt.text,
                                  getattr(prompt, "id", "")).split())
    return int(words * rules.get("window_words_per_token")
               + per_request * lines
               * rules.get("window_line_tokens")         # the pieces' text
               + (rules.get("window_tokens_per_image") * per_request
                  if attach_images() else 0)               # their crops
               + payload                                    # payload + envelope
               + answer_tokens_of(prompt))


def most_of_number(name: str) -> int:
    """The largest value the number *name* of the flow takes in any box or
    frame of it that is on (the run's number, and what each node sets for
    itself)."""
    from docpipe.profile import active_profile
    from .engine import Engine
    most = int(flow_map.number(numbers(), name))
    for node, _frames in flow_map.on(flow_map.tree_of(active_profile())):
        said = Engine.own_values(node).get(name)
        if said is not None:
            most = max(most, int(said))
    return most


def answer_tokens_of(prompt) -> int:
    """The longest answer a request of *prompt*'s kind may ask for: the
    longest of those the steps of the flow that ask this kind set for
    themselves (rule `max_tokens`), else the run's."""
    from docpipe.profile import active_profile
    from . import blocks
    kind = next((name for name, prompt_id in addressed_map.PROMPT_IDS.items()
                 if prompt_id == getattr(prompt, "id", None)), None)
    name = "max_tokens"
    own = []
    for node in flow_map.boxes(flow_map.tree_of(active_profile())):
        said = (node.get("rules") or {}).get(name)
        if blocks.asks_of(node) == kind and said is not None:
            own.append(int(said))
    return max(own) if own else int(rules.get(name))


def request_budget(spec, profile=None) -> int:
    """Tokens the largest request this run sends needs, per request.

    The window a server is started with has to hold every request kind of the
    run, so it follows the largest of them. Read off the prompts the run
    sends (`survey_prompt_ids`): one per kind of request of the reading
    (`addressed.KINDS`). Never off one that no request carries, and not the
    review, which has a line of its own in the doctor.
    """
    return max(context_budget(prompts.load(prompt_id, profile), spec)
               for prompt_id in survey_prompt_ids())


def _documents(conn: sqlite3.Connection) -> list:
    """Every current document, the largest first (rule `largest_first`;
    otherwise by name).

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
                + ("WHERE d.is_current = 1 "
                   if rules.get("current_versions_only") else "")
                + "GROUP BY d.id, d.filename "
                + ("ORDER BY COUNT(s.id) DESC, d.filename"
                   if rules.get("largest_first") else "ORDER BY d.filename"))]


def select_documents(documents: list, wanted: Optional[list]) -> tuple:
    """(chosen, missing) for a --document restriction; no restriction = all.

    `missing` is what was asked for and is not on offer, which for this corpus
    means superseded rather than absent: `_documents` lists current versions
    only. A pilot has to hear about that instead of quietly being smaller than
    it was meant to be.
    """
    wanted = wanted or rules.get("documents")
    if not wanted:
        return documents, []
    ids = {int(one) for one in wanted}
    chosen = [d for d in documents if d[0] in ids]
    return chosen, sorted(ids - {d[0] for d in chosen})


def year_states_of(spec: Spec) -> dict:
    """{state: which frame pairs are that state of the plan}, as the spec
    says it at the plan field of the state's year (`plan_fields`, key `of`,
    owner decision 2026-11-10): their years date a row that names the state
    by word ("Basisjahr", "Zieljahr") and prints no year, in a pass over a
    stored harvest, which asks no plan its years. None for a state the spec
    does not say it of, which then has no years."""
    return {state: (spec.plan_fields.get(f"{state}_year") or {}).get("of")
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


# The switches of the follow-up passes and the flow each one chooses, in the
# order a run takes one where more than one is given.
SWITCH_FLOWS = (("recheck", "recheck"), ("remap", "remap"),
                ("review", "review"), ("top_up", "top_up"),
                ("top_up_open", "top_up_open"),
                ("top_up_parameters", "top_up_parameters"),
                ("start_at", "start_at"))
# What a flow without a harvest of its own reads: every document of the
# database, not only those the harvest would read.
LISTING_FLOWS = ("top_up", "top_up_open", "top_up_parameters")


def chosen_flow(args) -> tuple:
    """(the flow this run starts, why it cannot): `--flow NAME` or the flow
    the switch chooses, the main flow where there is neither. A switch that
    chooses another flow than `--flow` names is refused."""
    switched = [name for switch, name in SWITCH_FLOWS
                if getattr(args, switch, None)]
    if args.flow is not None:
        others = [name for name in switched if name != args.flow]
        if others:
            return args.flow, (f"--flow {args.flow} and the switch of the "
                               f"flow {others[0]} name two flows: a run "
                               f"starts one")
        if args.flow == "start_at" and not args.start_at:
            return args.flow, ("--flow start_at needs the harvest to start "
                               "at: --start-at HARVEST")
        return args.flow, None
    return (switched[0] if switched else passflow.MAIN), None


def follow_up_problem(name: str, profile) -> Optional[str]:
    """Why the flow *name* cannot be started for *profile*, or None."""
    if name == passflow.MAIN:
        return None
    if name not in passflow.names(profile):
        return (f"--flow {name}: the profile {profile.name!r} has no such "
                f"flow; it has {', '.join(passflow.names(profile))}")
    try:
        tree = passflow.load(name, profile)
    except (flow_map.FlowError, LookupError, OSError) as exc:
        return f"--flow {name}: {exc}"
    said = passflow.startable(tree)
    return f"--flow {name}: {said}" if said else None


def follow_up_run(args, spec, current, documents, document_name, whole,
                  every, locate, document_axes, frame_axes, year_states,
                  sweep, owner_sources, in_flight, room, harvest_document,
                  make_found, harvest_documents_of) -> passflow.Run:
    """What a flow of a follow-up pass runs with (`passflow.Run`): where the
    harvest is, the stamp this run would write, and the means to read a
    document again as the harvest reads it (`whole`: the survey of the
    plan, asked for the new parameters alone or for the passages nobody
    read)."""
    document_spec = document_spec_per_call(args.db, spec, document_axes)
    deps = {"sweep": sweep, "owner_sources": owner_sources,
            "document_spec": document_spec,
            "frame_names": [slot.name for slot in frame_axes],
            "frame_axes": frame_axes, "year_states": year_states,
            "dynamic_ok": document_axes is not None, "locate": locate}
    stems = {Path(fn).stem for _did, fn in documents}
    return passflow.Run(
        out=args.out, spec=spec, current=current, deps=deps,
        only=args.top_up_key, documents=documents, named=lambda: stems,
        in_flight=in_flight, room=room, locate=locate,
        document_spec=lambda document_id: (
            document_spec(document_id) if document_id else spec),
        take_parameters=lambda document_id, uris: whole(
            document_id, only=tuple(uris), scope="parameters"),
        take_passages=lambda document_id, passages, also: whole(
            document_id, scope="rest", passages=passages, also=also),
        passages_of=lambda document_id: every(document_id, set()),
        make_found=make_found, harvest_documents=harvest_documents_of,
        harvest_document=harvest_document,
        open_trace=lambda folder: trace.open_trace(args.out / folder,
                                                   document_name.get),
        begin_archive=archive.begin, flush_trace=trace.flush)


def log_follow_up(name: str, stats) -> None:
    """The line that says what a pass over a stored harvest did."""
    if name == "top_up":
        log.info("top-up: %d row(s) re-read over %d document(s), %d "
                 "stamp(s) carried forward, %d blocked", stats["rows"],
                 stats["documents"], stats["stamps carried forward"],
                 stats["blocked"])
    elif name == "top_up_open":
        log.info("top-up-open: %d open coordinate(s) asked over %d "
                 "document(s), %d still open",
                 stats["open coordinates asked"], stats["documents"],
                 stats["open coordinates left"])


def main(argv: Optional[list] = None) -> int:
    """The call line of the run. What a call switch sets for the run alone
    (`--document`, `--force`) is a rule laid over the rules for as long as
    the run goes (`rules.overlaid`), and gone after it."""
    with ExitStack() as stack:
        return _main(argv, stack)


def _main(argv: Optional[list], stack: ExitStack) -> int:
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
                        help="No harvest: write the JSONL in OUT as the "
                             "drawing of the profile's graph file says, as "
                             "TTL")
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
    parser.add_argument("--review-limit", type=int, default=None,
                        metavar="N",
                        help="--review only: stop after N values (0 = all; "
                             "the rule review_limit where not given)")
    parser.add_argument("--remap", action="store_true",
                        help="map every coordinate's recorded wording onto "
                             "the vocabulary as the spec reads today, over "
                             "the harvest in --out. No model. Carries a "
                             "document's stamp forward for every answer "
                             "space it could fully re-map, so a grown option "
                             "list costs minutes instead of a corpus run")
    parser.add_argument("--flow", default=None, metavar="NAME",
                        help="start the flow NAME: main (the harvest, as "
                             "without a switch) or a follow-up pass of the "
                             "profile (top_up, top_up_open, "
                             "top_up_parameters, remap, recheck, review, "
                             "start_at). Each switch above only chooses "
                             "its flow, so --top-up and --flow top_up are "
                             "the same run")
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
    if args.top_up_open and (args.top_up or args.top_up_parameters):
        parser.error("--top-up-open is a pass of its own")
    if args.start_at and (args.top_up or args.top_up_parameters
                          or args.top_up_open):
        parser.error("--start-at starts a harvest, it is no top-up")
    chosen, problem = chosen_flow(args)
    if problem:
        parser.error(problem)
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
    take_flow(profile)
    if args.top_up_parameters and args.top_up:
        # Two passes over one harvest: a run starts one flow, and these two
        # write their trace into one folder and write it anew per document.
        parser.error("--top-up-parameters is not combined with --top-up: "
                     + (passflow.shared_trace("top_up", "top_up_parameters",
                                              profile)
                        or "a run starts one flow"))
    problem = follow_up_problem(chosen, profile)
    if problem:
        parser.error(problem)
    # The switch is the flow it chooses: what follows asks the flow.
    for switch, name in SWITCH_FLOWS:
        if name != "start_at":
            setattr(args, switch, chosen == name)
    if chosen != "start_at":
        args.start_at = None
    if args.document:
        stack.enter_context(rules.overlaid(
            documents=[str(one) for one in args.document]))
    if args.force:
        stack.enter_context(rules.overlaid(skip_current=False))
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
                                drop_stamps=False if args.keep_stamps
                                else None,
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
        # The drawing of the profile's graph file says what an answer
        # becomes; the program writes it (`graph.py`).
        try:
            serializer = graph.make_serializer(profile, args.db)
        except graph.GraphError as exc:
            parser.error(str(exc))
        described = profile.component("kg", "PROVENANCE") or {}
        writer = None
        if args.provenance and provenance.enabled() and described:
            # Written under the graph rule `base` as it stands now; the
            # profile names only the vocabulary.
            from docpipe import graphfile
            base = graphfile.get("base", profile.name)
            if base:
                writer = provenance.Writer(base, {**described, "base": base})
        from .serialize import (apply_graph_file, profile_context,
                                run as serialize_run, validate)
        held, gold_path = _decisions_file(args.out)
        indexes = [{}]
        try:
            counts = serialize_run(args.out, args.serialize, serializer,
                                   writer, gold=held, gold_source=gold_path,
                                   index=indexes[0])
        except ValueError as exc:
            log.error("serialize: %s", exc)
            return 1
        log.info("serialize: %d tuple(s) from %d document(s) -> %s",
                 sum(counts.values()), len(counts), args.serialize)
        written = [Path(args.serialize)]
        # A profile whose data schema closes its lists more tightly than the
        # graph does writes the graph a second time as that schema takes it,
        # beside the full one; the full one keeps everything that was read.
        if serializer.writer.drawing.document.get("strict"):
            beside = Path(args.serialize).with_suffix(".strict.ttl")
            try:
                indexes.append({})
                taken = serialize_run(args.out, beside,
                                      graph.make_serializer(
                                          profile, args.db, strict=True),
                                      index=indexes[-1])
                log.info("serialize: %d document(s) as the data schema takes "
                         "them -> %s", len(taken), beside)
                written.append(beside)
            except ValueError as exc:
                log.warning("serialize: strict graph not written: %s", exc)
        # The shapes the last `vocabulary --refresh` pulled. A profile that
        # names none has nothing to validate against; one that names them
        # but was never refreshed is told so rather than passed over.
        shapes = profile.component("vocabulary", "shapes")
        paths = shapes() if shapes is not None else []
        context = profile_context(profile) if paths else ()
        # What the profile's graph file asks of the written graphs: classes
        # left out, nodes named anew, constraints that leave a value or a
        # paper out (`docpipe.graphfile`); nothing where it asks nothing.
        for graph_path, index in zip(written, indexes):
            try:
                apply_graph_file(graph_path, profile, paths, context, index)
            except Exception:
                log.exception("graph file: not applied to %s", graph_path)
        if shapes is not None:
            if paths:
                # The graph is written by now, and the report must not take
                # the serialize result with it when the validator fails.
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
    # Every run reads each plan passage by passage, so the spec must name
    # groups (`surveyed_flow`). Recorded in each pass's producer entry.
    if not surveyed_flow(spec, profile):
        parser.error(f"the spec {spec_path} names no groups: a spec needs "
                     f"groups, since every run reads each plan passage by "
                     f"passage")
    global FLOW
    FLOW = SURVEYED
    if args.review:
        # The two guards `main` applies below, applied here as well: this
        # branch returns before either of them is reached, and a review that
        # reads every table without its picture is a review of a
        # transcription.
        if attach_images() and not Path(args.image_root).is_dir():
            parser.error(f"image root {args.image_root} is not a directory — "
                         f"every table and figure crop would be missing. Pass "
                         f"--image-root, or EXTRACT_ATTACH_IMAGES=0 to review "
                         f"from the transcriptions alone")
        review_prompt, _inputs = step_parts(
            step_asking("review_marks", "review"), REVIEW_PROMPT_ID)
        preflight(context_budget(review_prompt, spec),
                  what="extraction review")
        start_limit()
        start_counting()
        from .review import run as review_run
        wanted = None
        if rules.get("documents"):
            # The harvest files are named after the documents, so a
            # restriction is resolved through the same listing the harvest
            # selects from and fails the same way on an id that is not on it.
            listing = sqlite3.connect(readonly_uri(args.db), uri=True)
            try:
                chosen, missing = select_documents(_documents(listing),
                                                   None)
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
                prompt_sha=review_prompt.sha256, model=llm_model(),
                spec_for=spec_for,
                producer=producer("review", llm_model()))
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
    # A harvest passage by passage writes no anchors, and its stamps say so.
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
    year_states = year_states_of(spec)

    log.info("extraction: each plan in pieces: find, coordinates, lists, "
             "search")
    # The largest request of the run, over the prompts it sends: what the
    # server is started with, what the doctor checks and what it is asked for.
    required = request_budget(spec)
    if args.print_context_budget:
        print(required)
        return 0
    # The window every request is sized against before it is sent.
    preflight(required, what="extraction", profile=profile)
    start_limit()
    start_counting()

    from concurrent.futures import ThreadPoolExecutor

    from docpipe.inference import faiss_store, query_cache
    # Not `index`. `plan` below closes over this name and reads it when it
    # runs, and the pair loop further down bound an `index` of its own: pairs
    # 8, 9 and 10 of Kassel were planned against an int and the job failed.
    faiss_index, id_to_pos = faiss_store.load_global_index(args.index)
    args.out.mkdir(parents=True, exist_ok=True)
    if attach_images() and not Path(args.image_root).is_dir():
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
    documents, missing = select_documents(documents, None)
    if missing:
        log.error("%d named document(s) not found or not current: %s",
                  len(missing), ", ".join(str(m) for m in missing))
        return 1

    documents = documents_to_harvest(
        documents, args.out, spec_sha, force=args.force,
        force_stale=args.force_stale, anchors_sha=anchors_sha, spec=spec,
        top_up=chosen in LISTING_FLOWS or chosen not in (
            passflow.MAIN, "start_at", "recheck", "remap", "review"),
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
    # What this run replaces is kept under its name (archive.py); a flow of
    # a follow-up pass names its own (the setting `archive` of its first box).
    if chosen == passflow.MAIN:
        archive.begin("harvest")

    # How many documents are in flight at once: as many as the server has
    # room for (`document_room`), and never more than this ceiling, which
    # only guards the runner's memory. Not a group: a document that is
    # written makes room for the next one.
    in_flight = documents_at_once()
    room = document_room(LIMIT)
    log.info("extraction: %d document(s), %d parameter(s), "
             "documents in flight %s",
             len(documents), len(spec.parameters),
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
    # What the reading searches the plan with, which the passes over a
    # stored harvest re-read a coordinate with as well.
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
        """The whole plan, best first for a search's sentences."""
        return more_sources(document_id, probes, set(exclude), limit=0)

    whole = make_harvest(spec, db_path=args.db, out=args.out,
                         image_root=args.image_root, profile=profile,
                         every=every, spec_for=spec_for, rank=rank,
                         reranker=make_chunk_reranker())

    def pass_sweep():
        """What a pass over a stored harvest asks a coordinate again with:
        the harvest's own questions (`surveyed.SurveyedHarvest.sweep`)."""
        return whole.sweep

    document_name = {did: Path(fn).stem for did, fn in documents}
    # Every event carries the document it belongs to and lands in that
    # document's own file, so a redone document overwrites its own trace. A
    # pass over a stored harvest writes beside the harvest's traces and not
    # into them (the setting `trace` of the box that starts it): they say
    # what the harvest cost, and are opened for writing.
    if chosen == passflow.MAIN:
        trace.open_trace(args.out / "trace", document_name.get)

    computer = make_computer(profile,
                             lambda document_id: every(document_id, set()),
                             pages_of, rank)
    completer = make_completer(profile, args.db)

    def verify(entry: tuple, replies: Optional[int] = None) -> bool:
        """Fold, work out, complete and write one document. *replies* is how
        many of its requests came back, its batches when not given: for a
        harvest passage by passage the readings that came back."""
        name, report, answered = entry
        replies = len(answered) if replies is None else replies
        fold_answers(answered, report, locate=locate, spec=spec)
        # Stopped half way a document is half worked out, and unwritten like
        # one half read.
        if computer is not None:
            reader = whole.reader_of(spec)
            # The calculation reads the values of its own step, the compute
            # box of the flow, and not those of the writing around it.
            with (reader.engine.step_of("compute") if reader is not None
                  else nullcontext()):
                if not computer(answered, report, locate=locate, spec=spec,
                                stop=Halted):
                    return False
        if completer is not None:
            reader = whole.reader_of(spec)
            # The completion reads the values of its own step, the
            # catalogue box of the flow.
            with (reader.engine.step_of("catalogue") if reader is not None
                  else nullcontext()):
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
    # The run's own: every request asked again for the server's failure
    # ends with it (`halted`).
    halt = HALT
    halt.clear()

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
        if not dead_server_ends_run(seconds):
            return
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

    # OpenAI client is thread-safe.
    rest_of_document = make_rest_of_document(args.db, content=content)
    # The places of the earlier harvests, made by the step of the flow
    # `start_at` that takes them (`passboxes.box_places`).
    found_of: list = [None]

    def make_found():
        found_of[0] = found_places.Found(args.start_at, document_name.get,
                                         rest_of_document)
        return found_of[0]

    whole.halted = Halted.is_set

    def harvest_document(document_id: int, filename: str) -> tuple:
        """One document from its order to its file: (written, failures).

        With --start-at the order covers the passages earlier harvests
        found something in, and the rest of the plan for a parameter none
        of them was asked (`found.Found.gained`); the stamp then says the
        document was read in part.
        """
        name = Path(filename).stem
        found = found_of[0]
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
                                sources_of=taken.sources_of,
                                uncombed=taken.uncombed)
        with whole.reader_of(spec).engine.step_of("write"):
            stamped = verify((name, report, taken.answered),
                             replies=taken.replies)
        return stamped, 0 if stamped else 1

    follow_up = None
    if chosen != passflow.MAIN:
        follow_up = follow_up_run(
            args, spec, _stamp_current(spec_sha, anchors_sha, spec),
            documents, document_name, whole, every, locate, document_axes,
            frame_axes, year_states, pass_sweep(),
            make_owner_sources(args.db, content=content), in_flight, room,
            harvest_document, make_found,
            lambda docs, step: harvest_documents(
                docs, step, in_flight=in_flight, stop=STOP,
                halted=halt.is_set, room=room))
    install_stop_handler()
    try:
        if follow_up is None:
            done, _written, failed = harvest_documents(
                documents, harvest_document, in_flight=in_flight, stop=STOP,
                halted=halt.is_set, room=room)
        else:
            passflow.run_named(chosen, follow_up, profile)
            done, failed = follow_up.done, follow_up.failed
        failures += failed
    finally:
        stopped = STOP.is_set()
    if follow_up is not None:
        log_follow_up(chosen, follow_up.stats)

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
    write_stats(args.out, follow_up.traces if follow_up is not None
                and follow_up.traces else ["trace"],
                set(document_name.values()))
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
