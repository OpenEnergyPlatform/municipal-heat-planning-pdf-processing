"""
estimate.py: What a run will cost, before it runs.

    docpipe estimate [STAGE ...] [--out DIR] [--db FILE] [--processed DIR]

For each stage named (default: all) it counts the work the stage still has,
by that stage's own rule for what is pending, and says how many requests that
is, how many tokens go in and out, and what that costs when the project file's
[prices] table names the model. It is an estimate and says so: it never calls
a model, and it stops nothing. It is a number to read before `docpipe <stage>`,
not a limit on it.

Every figure carries its basis, and there are two. Where this installation's
ledger (usage.py) holds requests of the stage under this profile and this
model, a request is taken to cost what those requests cost on average:
"measured". Where it holds none, the request is counted from the size of its
prompt: "counted", which is the stage's own over-estimate of tokens per word
and says nothing about the length of a reply. The two are not mixed inside one
figure, and the line says which one it used. A ledger kept the profile only
from the version that added the column on, so its older rows are no profile's.

The harvest (stage 7) is the exception to "counted". How many requests it
asks follows what retrieval finds and what the model reads, and neither is
known before it asks. So its basis is the trace of documents this profile has
harvested already, in the harvest directory (`--out`): requests and tokens
per section by kind of request, scaled to the sections still to harvest. With
no such trace it says it cannot estimate, and the command ends non-zero.

Author: Felix Vossel
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sqlite3
import sys
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence

from . import settings, usage
from .artifacts import (REFINEMENT_PARTIAL_JSON, SECTIONS_JSON,
                        SECTIONS_REFINED_JSON, VISUALS_JSON, DOCUMENT_JSON)
from .profile import (add_profile_argument, bind_command_line, program,
                      require_profile)
from .store.schema import readonly_uri

log = logging.getLogger(__name__)

# The commands that have work to count, in the order the pipeline runs them.
COMMANDS = ("ingest", "preprocess", "refine", "visuals", "chunk", "extract")

# The events of the harvest's trace that are one answered request each.
# runner.py writes them; a frame event without tokens is the summary of a
# frame search and no request.
TRACED = ("frame", "rows", "field")
TRACE_DIR = "trace"


class EstimateError(Exception):
    """A stage whose work could not be counted at all."""


@dataclass
class Where:
    """What the estimate reads: the profile's files and the ledger."""
    profile: object
    pdf_dir: Path
    processed: Path
    db: Path
    out: Optional[Path]
    ledger: dict
    prices: dict
    unattributed: int = 0       # ledger rows of runs from before the profile


@dataclass
class Estimate:
    """One stage's figures, each with the line that says where it comes from."""
    command: str
    what: str
    model: Optional[str] = None
    work: list = field(default_factory=list)        # [(count, unit)]
    notes: list = field(default_factory=list)       # what is not counted
    requests: Optional[int] = None
    kinds: list = field(default_factory=list)       # [(count, kind of request)]
    tokens_in: Optional[int] = None
    tokens_out: Optional[int] = None
    tokens_embedded: Optional[int] = None
    cached_in: int = 0
    basis: str = ""
    missing: Optional[str] = None       # why the requests could not be counted


# ---------------------------------------------------------------------------
# Reading what the stages left
# ---------------------------------------------------------------------------

@contextmanager
def _quiet(*names):
    """The stages log a line per document for what they decide. Here that is
    a number, so the lines are held back."""
    held = [(logging.getLogger(name), logging.getLogger(name).level)
            for name in names]
    for logger, _ in held:
        logger.setLevel(logging.ERROR)
    try:
        yield
    finally:
        for logger, level in held:
            logger.setLevel(level)


def _read_json(path: Path):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def _doc_dirs(processed: Path) -> list:
    """The documents' directories, as the stages list them. A root that is not
    there is no corpus with nothing to do: a mistyped path would read as zero
    work, so it is an error."""
    if not processed.is_dir():
        raise EstimateError(f"no processed directory at {processed}: nothing "
                            f"has been through stage 3 yet, or this is not "
                            f"where it went (--processed DIR)")
    return sorted(d for d in processed.iterdir() if d.is_dir())


def _words(text) -> int:
    if isinstance(text, list):
        text = " ".join(str(part) for part in text)
    return len(str(text or "").split())


def _readonly(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(readonly_uri(path), uri=True)


# ---------------------------------------------------------------------------
# The ledger and the price
# ---------------------------------------------------------------------------

def _measured(est: Estimate, where: Where, ledger_stage: str, *,
              embedding: bool = False) -> bool:
    """Take the tokens of `est.requests` from the ledger, when it holds
    requests of this stage under this profile and model. Says what it holds
    when it does not."""
    row = where.ledger.get((ledger_stage, est.model))
    if row is None or row.requests <= 0:
        others = sorted(model for (stage, model) in where.ledger
                        if stage == ledger_stage)
        est.basis = (f"counted from prompt sizes: the ledger holds no "
                     f"requests of stage {ledger_stage} under profile "
                     f"{where.profile.name} and model {est.model}"
                     + (f" (only of {', '.join(others)})" if others else "")
                     + (f"; {where.unattributed:,} ledger row(s) of runs from "
                        f"before the profile was kept belong to no profile "
                        f"and are not used" if where.unattributed else ""))
        return False

    share = est.requests / row.requests       # of the ledger's requests
    if embedding:
        est.tokens_embedded = int(round(row.embedding_tokens * share))
        shown = (f"{row.embedding_tokens / row.requests:,.0f} embedding "
                 f"tokens")
    else:
        est.tokens_in = int(round(row.input_tokens * share))
        est.tokens_out = int(round(row.output_tokens * share))
        if row.input_tokens:
            est.cached_in = int(round(
                est.tokens_in * row.cached_tokens / row.input_tokens))
        shown = (f"{row.input_tokens / row.requests:,.0f} tokens in and "
                 f"{row.output_tokens / row.requests:,.0f} out")
    est.basis = (f"measured: a mean of {shown} per request over the "
                 f"{row.requests:,} requests the ledger holds for stage "
                 f"{ledger_stage}, model {est.model}, profile "
                 f"{where.profile.name}, in {row.runs:,} run(s)")
    return True


def _price(est: Estimate, prices: dict) -> Optional[tuple]:
    """(amount, whether it is only a part of it), None when the model has no
    price. Tokens that could not be counted are not guessed at: the amount
    then leaves them out and says so."""
    price = prices.get(est.model)
    if price is None:
        return None
    row = ("", est.model, 0, est.requests or 0, est.tokens_in or 0,
           est.tokens_out or 0, est.tokens_embedded or 0)
    amount = usage.cost(row, prices, est.cached_in)
    partial = any(tokens is None and kind in price for tokens, kind in (
        (est.tokens_in, "input"), (est.tokens_out, "output"),
        (est.tokens_embedded, "embedding")))
    return amount, partial


# ---------------------------------------------------------------------------
# Stages that ask no model
# ---------------------------------------------------------------------------

def ingest(where: Where) -> Estimate:
    est = Estimate("ingest", "stage 1: register and fetch the documents the "
                             "profile's source names", requests=0)
    est.basis = "no model is asked"
    est.notes.append("what is left to register is what the profile's source "
                     "lists, which only `docpipe ingest` reads")
    return est


def preprocess(where: Where) -> Estimate:
    """Stages 2 and 3. Its own rule (pipeline.run_folder): a PDF of the
    folder whose processed directory has no sections.json is still to do."""
    est = Estimate("preprocess", "stages 2-3: layout, reading order, "
                                 "sections", requests=0)
    est.basis = "no model is asked"
    if not where.pdf_dir.is_dir():
        raise EstimateError(f"no PDF directory at {where.pdf_dir} "
                            f"(--pdf-dir DIR)")
    pending = [pdf for pdf in sorted(where.pdf_dir.glob("*.pdf"))
               if not (where.processed / pdf.stem / SECTIONS_JSON).is_file()]
    pages: dict = {}
    if where.db.is_file():
        with _readonly(where.db) as conn:
            pages = {name: n for name, n in conn.execute(
                "SELECT filename, num_pages FROM Documents")}
    known = [pdf for pdf in pending if pages.get(pdf.name) is not None]
    est.work = [(len(pending), "documents"),
                (sum(pages[pdf.name] for pdf in known), "pages")]
    if len(known) < len(pending):
        est.notes.append(
            f"{len(pending) - len(known):,} of those documents are not in "
            f"the database (docpipe ingest registers them), so their pages "
            f"are not counted")
    est.notes.append(
        "layout runs on this machine; with --transcribe-missing-text the "
        "vision model reads each page that has no text layer, and which "
        "pages those are is known only after stage 2 has read them")
    return est


# ---------------------------------------------------------------------------
# Refine
# ---------------------------------------------------------------------------

def refine(where: Where) -> Estimate:
    """Stage 4. Its own rule (refine.run_refine): a document with a stage-3
    result and no refined result is still to do, and so is one with an
    unfinished pass of the same input, of which only the windows the server
    did not serve are asked."""
    from docpipe.refinement import config, refine as stage, split

    # the stage's own bindings: they are what its window loop and its
    # requests read
    est = Estimate("refine", "stage 4: repair the text of each section",
                   model=stage.LLM_MODEL)
    window = stage.WINDOW_SIZE
    documents = sections_n = windows = cuts = resumed = unreadable = 0
    words_in = 0
    for doc in _doc_dirs(where.processed):
        if not (doc / SECTIONS_JSON).is_file():
            continue
        final = doc / SECTIONS_REFINED_JSON
        partial = stage._read_partial(doc / REFINEMENT_PARTIAL_JSON)
        if final.is_file() and partial is None:
            continue
        data = _read_json(doc / SECTIONS_JSON)
        if not isinstance(data, dict):
            unreadable += 1
            continue
        sections = data.get("sections", [])
        stage._strip_table_source_text(sections)
        resumes = (partial is not None
                   and partial.get("key") == stage._partial_key(sections))
        if partial is not None and not resumes and final.is_file():
            continue        # an unfinished pass of another input: the stage
            #               returns the refined result it finds
        documents += 1
        if resumes:
            resumed += 1
            sections = partial["sections"]
            asked = {int(i) for i, reply in partial["windows"].items()
                     if isinstance(reply, list)}
        else:
            asked = set()
            cuts += sum(1 for section in sections if split.needs_split(section))
        sections_n += len(sections)
        for index in range(0, len(sections), window):
            if index // window in asked:
                continue
            windows += 1
            words_in += _words(json.dumps(
                {"sections": [{k: v for k, v in s.items()
                               if k not in ("segments", "pages")}
                              for s in sections[index:index + window]]},
                ensure_ascii=False, indent=2))
    est.work = [(documents, "documents"), (sections_n, "sections")]
    est.requests = windows + cuts
    est.kinds = [(windows, f"windows of {window} sections"),
                 (cuts, "cuts of an oversized section")]
    if resumed:
        est.notes.append(f"{resumed:,} of the documents resume an unfinished "
                         f"pass: only its windows the server did not serve "
                         f"are counted")
    if unreadable:
        est.notes.append(f"{unreadable:,} document(s) have a "
                         f"{SECTIONS_JSON} that cannot be read and are not "
                         f"counted")
    est.notes.append("windows are counted before oversized sections are "
                     "cut, which makes a few more")
    if not _measured(est, where, "refinement"):
        # a request is the system prompt and the window; its reply is the
        # window handed back, which the stage sizes by this headroom
        per = config.TOKENS_PER_WORD
        est.tokens_in = int(windows * _words(config.system_prompt()) * per
                            + words_in * per)
        est.basis += (f"; the system prompt and each window as the JSON it is "
                      f"sent in, at {per:g} tokens per word")
        if not config.REFINE_RETURN_CORRECTIONS:
            est.tokens_out = int(words_in * per * config.REPLY_HEADROOM)
            est.basis += (f", and a reply as long as its window times "
                          f"{config.REPLY_HEADROOM:g}")
        est.notes.append("the cuts of oversized sections are not counted in "
                         "tokens")
    return est


# ---------------------------------------------------------------------------
# Visuals
# ---------------------------------------------------------------------------

def visuals(where: Where) -> Estimate:
    """Stage 5. Its own rule (pipeline.run_single): a table without a
    "markdown" and a figure without a "description" in visuals.json is still
    to do, unless its image is missing, which the stage skips."""
    from docpipe.visuals import config

    est = Estimate("visuals", "stage 5: transcribe tables, describe figures",
                   model=config.VLM_MODEL)
    pending = {"table": 0, "figure": 0}
    section_words = {"table": 0, "figure": 0}
    documents = cached = no_image = unreadable = 0
    for doc in _doc_dirs(where.processed):
        source = next((doc / name for name in (SECTIONS_REFINED_JSON,
                                               SECTIONS_JSON)
                       if (doc / name).exists()), None)
        if source is None:
            continue
        data = _read_json(source)
        if not isinstance(data, dict):
            unreadable += 1
            continue
        done: set = set()
        earlier = _read_json(doc / VISUALS_JSON) \
            if (doc / VISUALS_JSON).exists() else None
        for section in (earlier or {}).get("sections", []):
            done |= {t["id"] for t in section.get("tables", [])
                     if t.get("markdown")}
            done |= {f["id"] for f in section.get("figures", [])
                     if f.get("description")}
        before = sum(pending.values())
        for section in data.get("sections", []):
            context = _words(str(section.get("content", ""))[:800])
            for kind, key in (("table", "tables"), ("figure", "figures")):
                for item in section.get(key, []):
                    if item.get("id") in done:
                        cached += 1
                    elif not item.get("path") \
                            or not (doc / item["path"]).exists():
                        no_image += 1
                    else:
                        pending[kind] += 1
                        section_words[kind] += context
        documents += sum(pending.values()) > before
    est.work = [(documents, "documents"),
                (pending["table"], "tables"),
                (pending["figure"], "figures")]
    est.requests = pending["table"] + pending["figure"]
    est.kinds = [(pending["table"], "table transcriptions"),
                 (pending["figure"], "figure descriptions")]
    if cached:
        est.notes.append(f"{cached:,} tables and figures are described "
                         f"already and not counted")
    if no_image:
        est.notes.append(f"{no_image:,} tables and figures have no image "
                         f"file, which the stage skips")
    if unreadable:
        est.notes.append(f"{unreadable:,} document(s) have a section file "
                         f"that cannot be read and are not counted")
    est.notes.append("a table that fails its quality check is asked a second "
                     "time, and one that returns no usable JSON a third: "
                     "those requests are not counted")
    if _measured(est, where, "visuals"):
        est.notes.append("the mean is over tables and figures together: the "
                         "ledger does not tell them apart")
    else:
        per = config.TOKENS_PER_WORD
        prompts = {"table": _words(config.table_system_prompt())
                   + _words(config.table_user_prompt()),
                   "figure": _words(config.figure_system_prompt())
                   + _words(config.figure_user_prompt())}
        est.tokens_in = int(sum(
            (pending[kind] * (prompts[kind] * per + config.IMAGE_TOKENS)
             + section_words[kind] * per) for kind in pending))
        est.basis += (f"; both prompts, {config.IMAGE_TOKENS:,} tokens for "
                      f"the image and the first 800 characters of the "
                      f"section, at {per:g} tokens per word")
        est.notes.append("the length of a transcription or a description is "
                         "in no prompt: output tokens are not counted")
    return est


# ---------------------------------------------------------------------------
# Chunk
# ---------------------------------------------------------------------------

def _embedded(conn: sqlite3.Connection, name: str) -> set:
    """What `database.get_existing_embeddings` says of a document, over a
    connection that cannot write: (embedding type, section, item) of every
    input that has its vector."""
    from docpipe.chunking import database

    doc_id = database._resolve_document_id(name, conn)
    existing: set = set()
    if doc_id is None:
        return existing
    for number, etype in conn.execute(database._EXISTING_SECTION_SQL,
                                      (doc_id,)):
        existing.add((etype, number, None))
    for sql in (database._EXISTING_TABLE_SQL, database._EXISTING_FIGURE_SQL):
        for number, block, etype in conn.execute(sql, (doc_id,)):
            existing.add((etype, number, block))
    return existing


def chunk(where: Where) -> Estimate:
    """Stage 6. Its own rule (pipeline.run, the embed step): the inputs of a
    merged document that have no embedding in the database yet. The merge and
    the database step come first in the same run and ask no model."""
    from docpipe.chunking import chunking, config
    from docpipe.refinement.config import TOKENS_PER_WORD

    est = Estimate("chunk", "stage 6: merge, database, embeddings",
                   model=config.EMBEDDING_MODEL)
    documents = inputs = tokens = unmerged = unreadable = 0
    with _quiet("docpipe.chunking.chunking"):
        conn = _readonly(where.db) if where.db.is_file() else None
        try:
            for doc in _doc_dirs(where.processed):
                if not (doc / DOCUMENT_JSON).is_file():
                    unmerged += (doc / SECTIONS_JSON).is_file()
                    continue
                merged = _read_json(doc / DOCUMENT_JSON)
                if not isinstance(merged, dict):
                    unreadable += 1
                    continue
                existing = _embedded(conn, doc.name) if conn is not None \
                    else set()
                todo = [item for item in chunking.build_embedding_inputs(
                    merged, doc.name, doc)
                    if (item.embedding_type, item.section_index,
                        item.item_id) not in existing]
                if todo:
                    documents += 1
                inputs += len(todo)
                tokens += sum(min(int(_words(item.text) * TOKENS_PER_WORD),
                                  config.MAX_TOKEN_LENGTH) for item in todo)
        finally:
            if conn is not None:
                conn.close()
    est.work = [(documents, "documents"), (inputs, "inputs to embed")]
    est.requests = inputs
    est.kinds = [(inputs, "embedded inputs")]
    if unmerged:
        est.notes.append(f"{unmerged:,} documents have no {DOCUMENT_JSON} yet: "
                         f"the merge step makes it, and what it holds is "
                         f"counted only then")
    if unreadable:
        est.notes.append(f"{unreadable:,} document(s) have a {DOCUMENT_JSON} "
                         f"that cannot be read and are not counted")
    if conn is None:
        est.notes.append("no database yet: every input counts, since the "
                         "database step registers the documents first")
    if not _measured(est, where, "chunking", embedding=True):
        est.tokens_embedded = tokens
        est.basis += (f"; the text of each input at {TOKENS_PER_WORD:g} tokens "
                      f"per word, at most {config.MAX_TOKEN_LENGTH:,} per "
                      f"input")
        est.notes.append("a picture's tokens are not counted, only the text "
                         "that goes with it")
    return est


# ---------------------------------------------------------------------------
# Extract
# ---------------------------------------------------------------------------

def _trace_of(out: Path, harvested: list, sections_of: dict) -> tuple:
    """(documents, sections, {kind: [requests, tokens in, tokens out]}) of the
    trace the harvest left for the documents it stamped."""
    documents = sections = 0
    counted = {kind: [0, 0, 0] for kind in TRACED}
    for name, doc_id in harvested:
        path = out / TRACE_DIR / f"{name}.trace.jsonl"
        if not path.is_file():
            continue
        documents += 1
        sections += sections_of.get(doc_id, 0)
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except ValueError:
                    continue            # the last line of a run that was killed
                kind = record.get("t") if isinstance(record, dict) else None
                tokens = record.get("prompt_tokens") if kind in TRACED \
                    else None
                if not isinstance(tokens, int) or isinstance(tokens, bool):
                    continue
                done = record.get("completion_tokens")
                counted[kind][0] += 1
                counted[kind][1] += tokens
                counted[kind][2] += done if isinstance(done, int) else 0
    return documents, sections, counted


def extract(where: Where) -> Estimate:
    """Stage 7. Its own rule (runner.documents_to_harvest): a current
    document whose harvest is missing, unstamped or, under the ontology's
    keys and the PDF it was read from, current is not to do; the others
    are."""
    from docpipe.extraction import runner

    profile = where.profile
    spec_path = profile.component("extraction", "SPEC_PATH")
    if spec_path is None:
        raise EstimateError(f"profile {profile.name!r} does not configure "
                            f"the extraction stage")
    if not where.db.is_file():
        raise EstimateError(f"no corpus database at {where.db}")
    spec_path = Path(spec_path)
    spec = runner.load_spec(spec_path)
    spec_sha = hashlib.sha256(spec_path.read_bytes()).hexdigest()
    anchors_sha = runner.anchors_key()
    est = Estimate("extract", "stage 7: harvest values", model=runner.LLM_MODEL)
    with _readonly(where.db) as conn:
        documents = runner._documents(conn)
        sections_of = dict(conn.execute(
            "SELECT document, COUNT(*) FROM Sections GROUP BY document"))
        tables_of = dict(conn.execute(
            "SELECT s.document, COUNT(*) FROM Tables t JOIN Sections s "
            "ON t.section = s.id GROUP BY s.document"))
        figures_of = dict(conn.execute(
            "SELECT s.document, COUNT(*) FROM Images t JOIN Sections s "
            "ON t.section = s.id GROUP BY s.document"))
        pages_of = dict(conn.execute("SELECT id, num_pages FROM Documents"))
    pending = everything = list(documents)
    if where.out is not None:
        # Which PDF each document is, as the run itself would read it: a
        # document whose stamp names another file is stale there, so it is
        # not work to count here.
        runner.note_documents(where.db)
        with _quiet("docpipe.extraction.runner"):
            pending = runner.documents_to_harvest(
                documents, where.out, spec_sha, anchors_sha=anchors_sha,
                spec=spec)
            everything = runner.documents_to_harvest(
                documents, where.out, spec_sha, force_stale=True,
                anchors_sha=anchors_sha, spec=spec)
    ids = [doc_id for doc_id, _ in pending]
    sections = sum(sections_of.get(i, 0) for i in ids)
    est.work = [(len(pending), "documents"),
                (sum(pages_of.get(i) or 0 for i in ids), "pages"),
                (sections, "sections"),
                (sum(tables_of.get(i, 0) for i in ids), "tables"),
                (sum(figures_of.get(i, 0) for i in ids), "figures")]
    if where.out is None:
        est.notes.append("no --out: nothing is known to be harvested already, "
                         "so every current document is counted")
    elif len(everything) > len(pending):
        est.notes.append(
            f"{len(everything) - len(pending):,} documents were harvested "
            f"under an older spec or from another PDF; `docpipe extract "
            f"--force-stale` reads them again and they are not counted")
    if not pending:
        est.requests = 0
        est.basis = "nothing is to harvest"
        return est
    harvested = ([] if where.out is None else
                 [(Path(fn).stem, doc_id) for doc_id, fn in documents
                  if (where.out / f"{Path(fn).stem}.stamp.json").is_file()])
    traced, traced_sections, counted = _trace_of(
        where.out, harvested, sections_of) if harvested else (0, 0, {})
    answered = sum(counted[kind][0] for kind in TRACED) if counted else 0
    if not (traced_sections and answered):
        # a trace with no answered request is no basis either: scaled, it
        # would call a corpus that still has to be read free
        est.missing = (
            "the requests of a harvest follow what retrieval finds and what "
            "the model reads, so the basis is the trace of documents already "
            "harvested under this profile, and "
            + ("none is given (--out DIR)" if where.out is None else
               f"{where.out} holds none for a stamped document" if not traced
               else f"{where.out / TRACE_DIR} holds no answered request for "
                    f"the {traced:,} stamped document(s) it covers")
            + ": harvest a few documents (docpipe extract ... --document ID), "
              "then estimate again")
        return est
    # per section of the documents traced, scaled to the sections still to do
    asked = {kind: int(round(counted[kind][0] * sections / traced_sections))
             for kind in TRACED}
    est.requests = sum(asked.values())
    est.tokens_in = est.tokens_out = 0
    for kind in TRACED:
        n, tokens_in, tokens_out = counted[kind]
        if n:
            est.tokens_in += int(round(asked[kind] * tokens_in / n))
            est.tokens_out += int(round(asked[kind] * tokens_out / n))
    est.kinds = [(asked[kind], f"{kind} requests") for kind in TRACED]
    row = where.ledger.get(("extraction", est.model))
    if row is not None and row.input_tokens:
        est.cached_in = int(round(est.tokens_in * row.cached_tokens
                                  / row.input_tokens))
    est.basis = (f"measured: the trace of {traced:,} harvested documents in "
                 f"{where.out / TRACE_DIR} ({traced_sections:,} sections; "
                 + ", ".join(f"{counted[kind][0]:,} {kind} requests"
                             for kind in TRACED)
                 + f"), scaled to the {sections:,} sections still to do; "
                   f"only requests that were answered are in a trace")
    if est.cached_in:
        est.basis += (f"; the cached share of the input is the ledger's "
                      f"({row.cached_tokens:,} of {row.input_tokens:,} "
                      f"tokens)")
    # the harvest books these in the ledger, and its trace has them without
    # tokens: they are a request each and are in none of the three kinds above
    est.notes.append("the requests that write each document's search "
                     "sentences (at least one per parameter) are not in the "
                     "trace and are not counted")
    return est


STAGE_FUNCTIONS = {"ingest": ingest, "preprocess": preprocess,
                   "refine": refine, "visuals": visuals, "chunk": chunk,
                   "extract": extract}


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------

def report(est: Estimate, prices: dict) -> list:
    """The lines of one stage's estimate."""
    model = f"  [{est.model}]" if est.model else ""
    lines = [f"{est.command}  {est.what}{model}"]
    if est.work:
        lines.append("  work      " + ", ".join(f"{n:,} {unit}"
                                                 for n, unit in est.work))
    if est.missing:
        lines.append(f"  requests  not estimated: {est.missing}")
    else:
        text = (f"about {est.requests:,} requests" if est.requests
                else "no requests")
        shown = [f"{n:,} {kind}" for n, kind in est.kinds if n]
        if len(shown) > 1:
            text += " (" + ", ".join(shown) + ")"
        lines.append("  requests  " + text)
        tokens = []
        if est.tokens_in is not None:
            cached = (f", {est.cached_in:,} of them cached"
                      if est.cached_in else "")
            tokens.append(f"{est.tokens_in:,} tokens in{cached}")
        if est.tokens_out is not None:
            tokens.append(f"{est.tokens_out:,} tokens out")
        if est.tokens_embedded is not None:
            tokens.append(f"{est.tokens_embedded:,} tokens embedded")
        if tokens and est.requests:
            lines.append("  tokens    about " + ", ".join(tokens))
        if est.basis:
            lines.append("  basis     " + est.basis)
        if est.model and est.requests:
            priced = _price(est, prices)
            if priced is not None:
                amount, partial = priced
                # the currency is whatever the file's author priced in
                lines.append(
                    f"  price     {'at least ' if partial else 'about '}"
                    f"{amount:,.2f} in the currency of [prices]"
                    + (" (tokens that cannot be counted are left out)"
                       if partial else ""))
            elif prices:
                lines.append(f"  price     not counted: [prices] has none for "
                             f"{est.model}")
    lines += [f"  note      {note}" for note in est.notes]
    return lines


def _where(args, profile) -> Where:
    ledger = usage.db_path()
    return Where(
        profile=profile,
        pdf_dir=args.pdf_dir or profile.pdf_dir,
        processed=args.processed or profile.processed_dir,
        db=args.db or profile.db_path,
        out=args.out,
        ledger=usage.sums(ledger, profile.name),
        prices=settings.prices(),
        unattributed=usage.unattributed(ledger))


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog=program("docpipe.estimate"),
        description="What a run will cost before it runs: for each stage the "
                    "work it still has, the requests that are, their tokens "
                    "and, with [prices] in the project file, their price. An "
                    "estimate: no model is called and nothing is stopped.")
    parser.add_argument("stages", nargs="*", metavar="STAGE",
                        help="one of " + ", ".join(COMMANDS)
                             + " (default: all of them)")
    parser.add_argument("--pdf-dir", type=Path, default=None,
                        help="the PDFs (default: the profile's)")
    parser.add_argument("--processed", type=Path, default=None,
                        help="the processed root (default: the profile's)")
    parser.add_argument("--db", type=Path, default=None,
                        help="the corpus database (default: the profile's)")
    parser.add_argument("--out", type=Path, default=None,
                        help="the harvest directory: what extract has "
                             "harvested already, and the trace it estimates "
                             "from")
    add_profile_argument(parser)
    # before a stage is imported: what a stage binds on import is the
    # profile's, and `python -m docpipe.estimate` has no `__main__` to say it
    bind_command_line(argv)
    args = parser.parse_args(argv)
    unknown = [name for name in args.stages if name not in COMMANDS]
    if unknown:
        parser.error(f"unknown stage {', '.join(unknown)}: one of "
                     f"{', '.join(COMMANDS)}")
    wanted = [name for name in COMMANDS
              if not args.stages or name in args.stages]
    profile = require_profile(args)
    where = _where(args, profile)
    print(f"estimate for profile {profile.name}: no model was called and "
          f"nothing was run")
    unestimated = []
    for name in wanted:
        print()
        try:
            est = STAGE_FUNCTIONS[name](where)
        except EstimateError as exc:
            unestimated.append(name)
            print(f"{name}  not estimated: {exc}")
            continue
        except ImportError as exc:
            # a stage reads its own constants and rules, so an installation
            # without what the stage imports cannot count it; the others
            # are still counted
            unestimated.append(name)
            print(f"{name}  not estimated: this installation cannot import "
                  f"what the stage's count reads ({type(exc).__name__}: "
                  f"{exc})")
            continue
        if est.missing:
            unestimated.append(name)
        print("\n".join(report(est, where.prices)))
    if not where.prices:
        print("\nno [prices] table in the project file, so no price: per "
              "million tokens, e.g. \"model\" = { input = 1.0, output = 5.0 }")
    if unestimated:
        print(f"estimate: {len(unestimated)} of {len(wanted)} stage(s) could "
              f"not be estimated ({', '.join(unestimated)}), the reasons are "
              f"above", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
