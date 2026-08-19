"""
runner.py – Wiring the harvest loop to the live stack.

pipeline.py owns the loop and is pure; this module supplies its three
callables from the real world — FAISS retrieval with owner exclusion, the
harvesting LLM call, the native-PDF text behind a source — plus resume
stamps and the CLI. Heavy imports (faiss, torch-backed embedders, fitz)
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
import json
import logging
import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Callable, Optional

from docpipe import prompts
from docpipe.llm_preflight import assert_serving
from docpipe.profile import add_profile_argument, resolve_profile

from .pipeline import Source, harvest_document, write_report
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

HARVEST_PROMPT_ID = "extraction/harvest"
QUERIES_PROMPT_ID = "extraction/queries"
PROMPT_IDS = (HARVEST_PROMPT_ID, QUERIES_PROMPT_ID)

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
_FENCE_OPEN = re.compile(r"^```(?:json)?\s*")
_FENCE_CLOSE = re.compile(r"\s*```$")


# ---------------------------------------------------------------------------
# Retrieval: probe text -> ranked unseen owners of one document
# ---------------------------------------------------------------------------

def make_retrieve(conn: sqlite3.Connection, index, id_to_pos: dict,
                  cache_conn) -> Callable:
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
        from docpipe.embedding import get_embedder
        vec = get_embedder().embed_one({"text": probe})
        query_cache.put(cache_conn, key, vec)
        return vec

    def retrieve(probe: str, document_id: int, exclude: set) -> list:
        hits = faiss_store.retrieve(
            conn, index, id_to_pos, document_id, all_types,
            embed(probe), TOP_K, exclude=exclude)
        sources = []
        for hit in hits:
            sources.append(Source(
                owner_kind=hit["owner_kind"],
                owner_id=hit["owner_id"],
                text=hit.get("text") or "",
                provenance={
                    "document_id": hit.get("document_id"),
                    "page": hit.get("page_number"),
                    "section_number": hit.get("section_number"),
                    "section_title": hit.get("section_title"),
                    "title": hit.get("title"),
                },
                readoff=hit["owner_kind"] == "figure",
            ))
        return sources

    return retrieve


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


def make_candidates(db_path: Path) -> Callable:
    """Token-filtered owners of one document, straight from SQL.

    LIKE over the stored text is deliberately dumb: it is the *floor*, not
    the harvest. Retrieval finds what wording variance hides from tokens;
    this finds what ranking hides from retrieval. Own connection per call -
    the callable runs inside worker threads.
    """
    from docpipe.inference import db as inference_db

    def candidates(document_id: int, parameter) -> list:
        tokens = _candidate_tokens(parameter)
        like = lambda column: " OR ".join([f"{column} LIKE ?"] * len(tokens))
        params = [f"%{t}%" for t in tokens]
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
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
                hit = inference_db.fetch_owner_content(conn, owner_kind, owner_id)
                if hit is None:
                    continue
                sources.append(Source(
                    owner_kind=owner_kind, owner_id=owner_id,
                    text=hit.get("text") or "",
                    provenance={"document_id": hit.get("document_id"),
                                "page": hit.get("page_number"),
                                "section_number": hit.get("section_number"),
                                "section_title": hit.get("section_title"),
                                "title": hit.get("title"),
                                "via": "fallback"},
                    readoff=owner_kind == "figure"))
            return sources
        finally:
            conn.close()

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
            axes[name] = {"labels": sorted(
                {label for labels in axis.vocabulary.values() for label in labels})}
        elif axis.type == "int":
            axes[name] = {"type": "int"}
        else:
            axes[name] = {"enum": list(axis.enum or ())}
    return {"uri": parameter.uri, "label": parameter.label,
            "description": parameter.description,
            "units_accepted": sorted(parameter.units_accepted),
            "axes": axes, "example": parameter.example}


def make_harvester() -> Callable:
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
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = client.chat.completions.create(
                    model=LLM_MODEL, temperature=temperature,
                    max_tokens=max_tokens,
                    messages=[{"role": "system", "content": prompt.text},
                              {"role": "user", "content": payload}])
                tuples = _parse_tuples(response.choices[0].message.content)
                if tuples is not None:
                    return tuples
                log.warning("   harvest %s/%s attempt %d: reply carried no "
                            "'tuples' list", source.owner_kind,
                            source.owner_id, attempt)
            except Exception as exc:
                log.warning("   harvest %s/%s attempt %d failed: %s",
                            source.owner_kind, source.owner_id, attempt, exc)
            time.sleep(min(2 * attempt, 6))
        # A source the model never answered for is a hole in the harvest, and
        # holes must be visible: the caller counts these via the sentinel.
        return [{"_harvest_failed": True}]

    return harvest


# ---------------------------------------------------------------------------
# Native PDF text behind a source
# ---------------------------------------------------------------------------

def make_pdf_text(db_path: Path, pdf_root: Optional[Path]) -> Optional[Callable]:
    if pdf_root is None:
        return None

    def lookup(source: Source) -> Optional[str]:
        try:
            import fitz
        except ImportError:
            return None
        page_number = source.provenance.get("page")
        document_id = source.provenance.get("document_id")
        if not page_number or not document_id:
            return None
        # Own connection: lookups run inside worker threads.
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            row = conn.execute("SELECT filename FROM Documents WHERE id = ?",
                               (document_id,)).fetchone()
            bbox_row = None
            if source.owner_kind == "table":
                bbox_row = conn.execute("SELECT bbox FROM Tables WHERE id = ?",
                                        (source.owner_id,)).fetchone()
        finally:
            conn.close()
        if row is None:
            return None
        pdf_path = pdf_root / row[0]
        if not pdf_path.is_file():
            return None
        try:
            doc = fitz.open(str(pdf_path))
            try:
                page = doc.load_page(int(page_number) - 1)
                rects = None
                if bbox_row and bbox_row[0]:
                    try:
                        rects = json.loads(bbox_row[0])
                    except (TypeError, json.JSONDecodeError):
                        rects = None
                if rects:
                    return " ".join(
                        page.get_text(clip=fitz.Rect(*r)) for r in rects)
                return page.get_text()
            finally:
                doc.close()
        except Exception:
            return None

    return lookup


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
    out_path = out_dir / f"{name}.jsonl"
    stamp_path = out_dir / f"{name}.stamp.json"
    current = _stamp_current(spec_sha)
    if out_path.exists() and not force:
        changed = stale(stamp_path, current)
        if not changed:
            log.info("extraction: %s is current — skipped", name)
            return True
        if not force_stale:
            log.warning("extraction: %s was harvested with older %s; re-run "
                        "with --force-stale to redo it", name, ", ".join(changed))
            return True
    report = harvest_document(document_id, spec, templates,
                              retrieve=deps["retrieve"],
                              harvest=deps["harvest"],
                              pdf_text=deps.get("pdf_text"),
                              candidates=deps.get("candidates"),
                              max_rounds=MAX_ROUNDS)
    failed = [r for r in report.refusals
              if r.get("claim", {}).get("_harvest_failed")]
    if failed:
        log.warning("extraction: %s: %d source(s) never answered", name, len(failed))
    write_report(report, out_path)
    stamp_path.write_text(json.dumps(current, indent=2), encoding="utf-8")
    return True


def _documents(conn: sqlite3.Connection) -> list:
    return [(int(r[0]), str(r[1]))
            for r in conn.execute(
                "SELECT id, filename FROM Documents WHERE is_current = 1 "
                "ORDER BY filename")]


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m docpipe.extraction",
        description="Ontology-guided value extraction over an indexed corpus")
    parser.add_argument("db", type=Path, help="SQLite corpus database")
    parser.add_argument("index", type=Path, help="FAISS index")
    parser.add_argument("out", type=Path, help="Output directory (JSONL per document)")
    parser.add_argument("--pdf-root", type=Path, default=None,
                        help="PDF directory for the digit-exact native check")
    parser.add_argument("--document", type=int, default=None,
                        help="One document id instead of the whole corpus")
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

    harvest_prompt = prompts.load(HARVEST_PROMPT_ID)
    required = int(len(harvest_prompt.text.split()) * 3
                   + 6000                                  # largest source, generous
                   + int(harvest_prompt.meta.get("max_tokens", 4096)))
    if args.print_context_budget:
        print(required)
        return 0
    assert_serving(LLM_BASE_URL, LLM_API_KEY, LLM_MODEL, required,
                   what="extraction", flag="--max-model-len")

    from concurrent.futures import ThreadPoolExecutor, as_completed

    from docpipe.inference import faiss_store, query_cache
    index, id_to_pos = faiss_store.load_global_index(args.index)
    args.out.mkdir(parents=True, exist_ok=True)
    harvest = make_harvester()                    # OpenAI client is thread-safe
    pdf_text = make_pdf_text(args.db, args.pdf_root)
    candidates = make_candidates(args.db)

    with sqlite3.connect(f"file:{args.db}?mode=ro", uri=True) as listing:
        documents = _documents(listing)
    if args.document is not None:
        documents = [d for d in documents if d[0] == args.document]
        if not documents:
            log.error("document %s not found or not current", args.document)
            return 1

    doc_parallel = int(os.environ.get("EXTRACT_DOC_PARALLEL", "4"))
    log.info("extraction: %d document(s), %d parameter(s), top_k=%d, "
             "max_rounds=%d, doc_parallel=%d", len(documents),
             len(spec.parameters), TOP_K, MAX_ROUNDS, doc_parallel)

    def work(document_id: int, filename: str) -> Optional[str]:
        # SQLite connections are not shared across threads: every task opens
        # its own pair. The probes are identical across documents, so after
        # the first document the embedding cache answers nearly everything
        # and the per-task cache connection stays cheap.
        conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        cache_conn = query_cache.connect(args.out / "query_cache.db")
        try:
            deps = {"retrieve": make_retrieve(conn, index, id_to_pos, cache_conn),
                    "harvest": harvest, "pdf_text": pdf_text,
                    "candidates": candidates}
            run_document(document_id, Path(filename).stem, args.out, spec,
                         spec_sha, templates, deps,
                         force=args.force, force_stale=args.force_stale)
            return None
        finally:
            conn.close()
            cache_conn.close()

    failures = 0
    with ThreadPoolExecutor(max_workers=doc_parallel) as pool:
        futures = {pool.submit(work, did, fn): fn for did, fn in documents}
        for future in as_completed(futures):
            try:
                future.result()
            except Exception:
                failures += 1
                log.exception("extraction: %s failed", futures[future])
    log.info("extraction: done, %d failure(s)", failures)
    return 1 if failures else 0
