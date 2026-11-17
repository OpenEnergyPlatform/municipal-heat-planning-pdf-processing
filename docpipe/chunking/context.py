"""
context.py: A sentence of context before each table and figure of the index.

Owner decision 2026-11-17, from the literature on contextual retrieval (a 2026
BM25 study finds a context sentence per piece the one extension with a steady
gain on number questions): with the rule `context_sentence` on, the chat model
is asked once for each table and figure for one sentence that says what it is
about, in which unit, for which area, scenario and years, as far as its
caption, its head and the heading of its section say it. The text input and the
text of the picture input of the table or figure begin with that sentence
(`chunking.build_embedding_inputs`); a stage that embeds without the rule on
reads none.

A sentence is kept beside the document's results (CONTEXT_SENTENCES_JSON), under
the hash of exactly what the request showed and of the prompt, so it is asked
again only when the caption, the head, the heading or the prompt changed. The
database holds the sentence its vectors were embedded with (Tables and Images,
column `context_sentence`), which is how `--step sync` finds that a changed
sentence is a changed entry.

An answer that is not one JSON object with the key `sentence` is asked again,
with its cause named, as often as the other stages ask (MAX_RETRIES), and is
never embedded: the table or figure keeps its text as it was and is asked again
by the next run. Nothing is repaired.

Author: Felix Vossel
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Optional

from docpipe import prompts, providers, reading, rules, usage
from docpipe.artifacts import document_dirs
from docpipe.llm_preflight import request_extras

from .config import CONTEXT_SENTENCES_JSON, DOCUMENT_JSON

log = logging.getLogger(__name__)

PROMPT_ID = "visuals/context_sentence"
SCHEMA = {"type": "object",
          "properties": {"sentence": {"type": "string"}},
          "required": ["sentence"], "additionalProperties": False}

def enabled() -> bool:
    return bool(rules.get("context_sentence"))


def items_of(merged: dict):
    """(kind, section, item) of every table and figure of a merged document."""
    for section in merged.get("sections", []):
        for item in section.get("tables") or []:
            yield "table", section, item
        for item in section.get("figures") or []:
            yield "figure", section, item


def shown(kind: str, section: dict, item: dict) -> Optional[dict]:
    """What the request shows of one table or figure, or None for one that has
    neither a caption nor a body to say anything about."""
    caption = (item.get("caption") or "").strip()
    body = (item.get("markdown") if kind == "table"
            else item.get("description")) or ""
    if not caption and not body.strip():
        return None
    return {"kind": kind,
            "section_heading": (section.get("title") or "").strip(),
            "caption": caption,
            "head": body.strip()[:int(rules.get("context_head_chars"))]}


def key_of(request: dict, salt: str) -> str:
    """The hash of exactly what a request shows, and of the prompt it is asked
    with."""
    text = json.dumps(request, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256((salt + "\n" + text).encode("utf-8")).hexdigest()


def prompt_salt() -> str:
    return prompts.load(PROMPT_ID).sha256


def read_store(pdf_dir: Path) -> dict:
    """{key: sentence} kept for a document; {} where there is none or the file
    does not read."""
    try:
        with open(Path(pdf_dir) / CONTEXT_SENTENCES_JSON, "r",
                  encoding="utf-8") as fh:
            data = json.load(fh)
    except (FileNotFoundError, NotADirectoryError, ValueError):
        return {}
    kept = data.get("sentences") if isinstance(data, dict) else None
    return ({k: v for k, v in kept.items()
             if isinstance(k, str) and isinstance(v, str) and v.strip()}
            if isinstance(kept, dict) else {})


def write_store(pdf_dir: Path, sentences: dict) -> None:
    path = Path(pdf_dir) / CONTEXT_SENTENCES_JSON
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".",
                               suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"sentences": sentences}, fh, ensure_ascii=False,
                      indent=2)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def attach(merged: dict, pdf_dir: Path, salt: Optional[str] = None) -> dict:
    """*merged* with `context_sentence` set on every table and figure whose
    kept sentence answers what the request shows now; the others get none."""
    store = read_store(pdf_dir)
    salt = prompt_salt() if salt is None and store else (salt or "")
    for kind, section, item in items_of(merged):
        request = shown(kind, section, item)
        sentence = store.get(key_of(request, salt)) if request else None
        if sentence:
            item["context_sentence"] = sentence
    return merged


def load_document(pdf_dir: Path, salt: Optional[str] = None) -> dict:
    """A document's merged JSON, with its kept sentences where the rule is on."""
    with open(Path(pdf_dir) / DOCUMENT_JSON, "r", encoding="utf-8") as fh:
        merged = json.load(fh)
    return attach(merged, pdf_dir, salt) if enabled() else merged


def ask_document(merged: dict, pdf_dir: Path, ask: Callable, *,
                 salt: Optional[str] = None, workers: int = 1) -> dict:
    """Ask for the sentence of each table and figure of one document that has
    none kept for what it shows now; keep what came back. *ask* takes the
    request and returns the sentence or None. Returns the counts: asked,
    answered, kept (already there), dropped (no sentence came back)."""
    salt = prompt_salt() if salt is None else salt
    store = read_store(pdf_dir)
    todo: dict = {}
    kept = 0
    for kind, section, item in items_of(merged):
        request = shown(kind, section, item)
        if request is None:
            continue
        key = key_of(request, salt)
        if key in store:
            kept += 1
        else:
            todo.setdefault(key, request)
    answers: dict = {}
    if todo:
        with ThreadPoolExecutor(max_workers=max(1, min(workers, len(todo)))) as pool:
            for key, sentence in zip(todo, pool.map(ask, todo.values())):
                if isinstance(sentence, str) and sentence.strip():
                    answers[key] = sentence.strip()
    # What is kept is what the document shows now: a sentence of a caption that
    # changed goes.
    current = {key_of(r, salt) for r in (
        shown(k, s, i) for k, s, i in items_of(merged)) if r}
    now = {k: v for k, v in {**store, **answers}.items() if k in current}
    if now != store or not (Path(pdf_dir) / CONTEXT_SENTENCES_JSON).exists():
        write_store(pdf_dir, now)
    counts = {"asked": len(todo), "answered": len(answers), "kept": kept,
              "dropped": len(todo) - len(answers)}
    return counts


def ask_all(data_dir: Path, ask: Optional[Callable] = None) -> dict:
    """Ask for every document under *data_dir*, when the rule is on; {} when it
    is off (nothing is asked, nothing is written)."""
    if not enabled():
        return {}
    from docpipe.refinement.config import LLM_NUM_PARALLEL
    ask = ask or make_ask()
    salt = prompt_salt()
    total = {"asked": 0, "answered": 0, "kept": 0, "dropped": 0}
    for pdf_dir in document_dirs(Path(data_dir), DOCUMENT_JSON):
        with open(pdf_dir / DOCUMENT_JSON, "r", encoding="utf-8") as fh:
            merged = json.load(fh)
        counts = ask_document(merged, pdf_dir, ask, salt=salt,
                              workers=LLM_NUM_PARALLEL)
        for name, n in counts.items():
            total[name] += n
        if counts["asked"]:
            log.info("%s: context sentences asked %d, answered %d, dropped %d",
                     pdf_dir.name, counts["asked"], counts["answered"],
                     counts["dropped"])
    log.info("context sentences (requests): %s", total)
    return total


def make_ask() -> Callable:
    """The request to the chat model of the refinement stage (LLM_BASE_URL,
    LLM_MODEL, or the profile's provider settings)."""
    from docpipe.refinement import config as llm
    client = providers.client("llm", base_url=llm.LLM_BASE_URL,
                              api_key=llm.LLM_API_KEY, timeout=llm.LLM_TIMEOUT,
                              max_retries=0)
    prompt = prompts.load(PROMPT_ID)
    return lambda request: ask_model(
        client, request, system=prompt.text, model=llm.LLM_MODEL,
        temperature=float(prompt.meta.get("temperature", 0.1)),
        max_tokens=int(prompt.meta.get("max_tokens", 400)),
        max_retries=llm.MAX_RETRIES)


def ask_model(client, request: dict, *, system: str, model: str,
              temperature: float, max_tokens: int, max_retries: int,
              wait: Callable = time.sleep) -> Optional[str]:
    """One request. The reply is read as exactly one JSON object with the key
    `sentence`; a reply that is not is asked again with its cause named, at most
    *max_retries* times. None where no sentence came back."""
    base = [{"role": "system", "content": system},
            {"role": "user",
             "content": json.dumps(request, ensure_ascii=False)}]
    messages = list(base)
    shape = providers.grammar("context_sentence", SCHEMA)
    for attempt in range(1, max_retries + 1):
        try:
            response = client.chat.completions.create(
                model=model, messages=messages, response_format=shape,
                temperature=temperature, max_tokens=max_tokens,
                extra_body=request_extras())
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            if isinstance(status, int) and 400 <= status < 500 and status != 429:
                log.error("context sentence: the server rejected the request "
                          "(HTTP %d): %s", status, exc)
                return None
            log.error("context sentence: attempt %d/%d failed: %s", attempt,
                      max_retries, exc)
            messages = list(base)
            if attempt < max_retries:
                wait(5 * attempt)
            continue
        usage.reply(response, model)
        choice = reading.first(response)
        found, cause, said = reading.read(choice, key="sentence", of=str)
        if not cause and found["sentence"].strip():
            return found["sentence"].strip()
        if cause == "cut_off":
            return None
        cause = cause or "empty"
        log.warning("context sentence: attempt %d/%d: %s reply", attempt,
                    max_retries, cause)
        content = getattr(getattr(choice, "message", None), "content", None)
        messages = base + [
            {"role": "assistant", "content": content if isinstance(content, str) else ""},
            {"role": "user", "content": said or "The sentence is empty. Answer with one JSON object with a non-empty sentence."}]
    return None
