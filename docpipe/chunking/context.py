"""
context.py: A sentence of context before each table and figure of the index.

Owner decision 2026-11-17, from the literature on contextual retrieval (a 2026
BM25 study finds a context sentence per piece the one extension with a steady
gain on number questions): with the rule `context_sentence` on, the chat model
is asked for each table and figure for one sentence that says what it is
about, in which unit, for which area, scenario and years, as far as the table
or figure, its caption and the heading of its section say it. The entries of
the table or figure in the index begin with that sentence
(`chunking.build_embedding_inputs`, `pieces.item_pieces`); a stage that embeds
without the rule on reads none.

The request shows the whole table or figure (owner decision 2026-11-17,
"Nichts kürzen"): its text whole, its caption and the heading of its section.
A table whose request does not fit the model's window is asked in parts
(`requests_of`): each part shows the table's title, head and the lines under
it, the rows its rows stand under, and as many of its rows as fit, and each
part's sentence goes before the entries whose rows stand in that part
(`lead_of`). The window is the server's (`docpipe.window`).

A sentence is kept beside the document's results (CONTEXT_SENTENCES_JSON), under
the hash of exactly what the request showed and of the prompt, so it is asked
again only when the table, the caption, the heading or the prompt changed; how
a table was asked in parts is kept with it, under the hash of the whole
request, so that the embedding finds the sentences without asking the server.
The database holds the sentence its vectors were embedded with (Tables and
Images, column `context_sentence`; the parts as one JSON list), which is how
`--step sync` finds that a changed sentence is a changed entry.

An answer that is not one JSON object with the key `sentence` is asked again,
with its cause named, as often as stage 4 asks (refine_max_attempts), and is
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
# What the model is told when its sentence came back empty, before the request
# is asked again.
EMPTY_PROMPT_ID = "visuals/context_sentence_empty"
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
    """What the request shows of one table or figure, whole, or None for one
    that has neither a caption nor a text to say anything about."""
    caption = (item.get("caption") or "").strip()
    body = (item.get("markdown") if kind == "table"
            else item.get("description")) or ""
    if not caption and not body.strip():
        return None
    return {"kind": kind,
            "section_heading": (section.get("title") or "").strip(),
            "caption": caption,
            "text": body.strip()}


def requests_of(kind: str, section: dict, item: dict,
                fits: Optional[Callable[[dict], bool]] = None) -> list:
    """[(request, first line, last line)] that ask for the sentences of one
    table or figure: the whole where it fits (*fits*, the model's window;
    everything fits where none is given), lines None; else one request per
    part, each showing the lines every piece of the table shows and as many
    of its own rows as fit, with the first and the last of them. [] for one
    with nothing to show. `window.TooLong` where the lines every part shows
    do not fit beside one row, or, for an item without rows of its own, do
    not fit at all: nothing is cut, the caller names the item."""
    whole = shown(kind, section, item)
    if whole is None:
        return []
    if fits is None or fits(whole):
        return [(whole, None, None)]
    from docpipe.extraction import units
    from docpipe.window import split
    from .pieces import captions_of, item_source
    passage = units.passage_of(item_source(kind, section, item,
                                           captions_of(section)))
    own = [line.number for line in passage.lines
           if line.number not in passage.fixed]

    def render(numbers, replaced) -> str:
        shown_lines = sorted(set(passage.fixed) | set(numbers)
                             | passage.parents_of(numbers))
        return "\n".join(replaced.get(n, passage.line(n).text)
                         for n in shown_lines)

    def request(text: str) -> dict:
        return {**whole, "text": text}

    parts = split(own, render, lambda n: passage.line(n).text,
                  lambda text: fits(request(text)), units.sentences_of,
                  f"{kind} {item.get('id')}")
    return [(request(part.text), part.first, part.last) for part in parts]


def key_of(request: dict, salt: str) -> str:
    """The hash of exactly what a request shows, and of the prompt it is asked
    with."""
    text = json.dumps(request, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256((salt + "\n" + text).encode("utf-8")).hexdigest()


def prompt_salt() -> str:
    return prompts.load(PROMPT_ID).sha256


def read_kept(pdf_dir: Path) -> tuple:
    """({key: sentence}, {key of a whole request: [[first, last, key]]})
    kept for a document; empty where there is none or the file does not
    read."""
    try:
        with open(Path(pdf_dir) / CONTEXT_SENTENCES_JSON, "r",
                  encoding="utf-8") as fh:
            data = json.load(fh)
    except (FileNotFoundError, NotADirectoryError, ValueError):
        return {}, {}
    kept = data.get("sentences") if isinstance(data, dict) else None
    sentences = ({k: v for k, v in kept.items()
                  if isinstance(k, str) and isinstance(v, str) and v.strip()}
                 if isinstance(kept, dict) else {})
    split_at = data.get("parts") if isinstance(data, dict) else None
    parts = ({k: v for k, v in split_at.items()
              if isinstance(k, str) and isinstance(v, list)}
             if isinstance(split_at, dict) else {})
    return sentences, parts


def read_store(pdf_dir: Path) -> dict:
    """{key: sentence} kept for a document."""
    return read_kept(pdf_dir)[0]


def write_store(pdf_dir: Path, sentences: dict,
                parts: Optional[dict] = None) -> None:
    path = Path(pdf_dir) / CONTEXT_SENTENCES_JSON
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".",
                               suffix=".tmp")
    data: dict = {"sentences": sentences}
    if parts:
        data["parts"] = parts
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def kept_sentence(request: dict, salt: str, sentences: dict, parts: dict):
    """The sentence kept for what *request* shows (a string), the sentences
    of its parts ([{"first", "last", "sentence"}], the ones answered), or
    None."""
    key = key_of(request, salt)
    if key in sentences:
        return sentences[key]
    layout = parts.get(key)
    if not layout:
        return None
    out = [{"first": first, "last": last, "sentence": sentences[part]}
           for first, last, part in layout if part in sentences]
    return out or None


def attach(merged: dict, pdf_dir: Path, salt: Optional[str] = None) -> dict:
    """*merged* with `context_sentence` set on every table and figure whose
    kept sentence, or kept sentences of its parts, answer what the request
    shows now; the others get none."""
    sentences, parts = read_kept(pdf_dir)
    salt = prompt_salt() if salt is None and sentences else (salt or "")
    for kind, section, item in items_of(merged):
        request = shown(kind, section, item)
        found = kept_sentence(request, salt, sentences, parts) \
            if request else None
        if found:
            item["context_sentence"] = found
    return merged


def load_document(pdf_dir: Path, salt: Optional[str] = None) -> dict:
    """A document's merged JSON, with its kept sentences where the rule is on."""
    with open(Path(pdf_dir) / DOCUMENT_JSON, "r", encoding="utf-8") as fh:
        merged = json.load(fh)
    return attach(merged, pdf_dir, salt) if enabled() else merged


def sentences_of(value) -> list:
    """[(first line, last line, sentence)] of an item's `context_sentence`:
    a sentence for the whole (lines None), the parts' sentences as a list,
    or that list as the JSON the database holds; [] for none."""
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("[{"):
            try:
                value = json.loads(text)
            except ValueError:
                return [(None, None, text)]
        else:
            return [(None, None, text)] if text else []
    if not isinstance(value, list):
        return []
    return [(part.get("first"), part.get("last"),
             str(part.get("sentence") or "").strip())
            for part in value if isinstance(part, dict)
            and str(part.get("sentence") or "").strip()]


def stored(value) -> Optional[str]:
    """An item's `context_sentence` as the database holds it: the sentence,
    or the parts' sentences as one JSON list."""
    if value is None or isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def lead_of(item: dict, first: Optional[int], last: Optional[int]) -> str:
    """The sentence and its line break that go before the entry of *item*
    whose own lines run from *first* to *last*: the sentence of the whole,
    or of the part that holds its first line (the first part for an entry
    of carried lines only); "" where there is none."""
    said = sentences_of(item.get("context_sentence"))
    if not said:
        return ""
    if len(said) == 1 and said[0][0] is None:
        return said[0][2] + "\n"
    for part_first, part_last, sentence in said:
        if first is None or part_first is None:
            return sentence + "\n"
        if part_first <= first <= (part_last if part_last is not None
                                   else first):
            return sentence + "\n"
    return ""


def ask_document(merged: dict, pdf_dir: Path, ask: Callable, *,
                 salt: Optional[str] = None, workers: int = 1,
                 fits: Optional[Callable[[dict], bool]] = None) -> dict:
    """Ask for the sentences of each table and figure of one document that
    has none kept for what it shows now; keep what came back. *ask* takes a
    request and returns the sentence or None; *fits* says whether a request
    fits the model's window (`requests_of`). Returns the counts: asked,
    answered and dropped (requests: sent, with a sentence back, without
    one), kept and too_long (tables and figures: with their sentences there
    already; too long to be asked in any part, each named in the log and
    left without a sentence)."""
    from docpipe.window import TooLong
    salt = prompt_salt() if salt is None else salt
    store, layouts = read_kept(pdf_dir)
    todo: dict = {}
    kept = 0
    unfit = 0
    now_parts: dict = {}
    current: set = set()
    for kind, section, item in items_of(merged):
        whole = shown(kind, section, item)
        if whole is None:
            continue
        whole_key = key_of(whole, salt)
        current.add(whole_key)
        layout = layouts.get(whole_key)
        if whole_key in store or (layout and all(
                part in store for _f, _l, part in layout)):
            kept += 1
            if layout:
                now_parts[whole_key] = layout
                current.update(part for _f, _l, part in layout)
            continue
        try:
            asked = requests_of(kind, section, item, fits)
        except TooLong as exc:
            # Cannot be shown whole in any part: named, left without a
            # sentence (nothing is cut or sent), the rest goes on.
            log.error("%s: context sentence: %s %s left out (%s)",
                      Path(pdf_dir).name, kind, item.get("id"), exc)
            unfit += 1
            continue
        if len(asked) > 1 or (asked and asked[0][1] is not None):
            layout = [[first, last, key_of(request, salt)]
                      for request, first, last in asked]
            now_parts[whole_key] = layout
        for request, _first, _last in asked:
            key = key_of(request, salt)
            current.add(key)
            if key not in store:
                todo.setdefault(key, request)
    answers: dict = {}
    if todo:
        with ThreadPoolExecutor(max_workers=max(1, min(workers, len(todo)))) as pool:
            for key, sentence in zip(todo, pool.map(ask, todo.values())):
                if isinstance(sentence, str) and sentence.strip():
                    answers[key] = sentence.strip()
    # What is kept is what the document shows now: a sentence of a caption that
    # changed goes.
    now = {k: v for k, v in {**store, **answers}.items() if k in current}
    if (now != store or now_parts != layouts
            or not (Path(pdf_dir) / CONTEXT_SENTENCES_JSON).exists()):
        write_store(pdf_dir, now, now_parts)
    counts = {"asked": len(todo), "answered": len(answers), "kept": kept,
              "dropped": len(todo) - len(answers), "too_long": unfit}
    return counts


def ask_all(data_dir: Path, ask: Optional[Callable] = None,
            fits: Optional[Callable[[dict], bool]] = None) -> dict:
    """Ask for every document under *data_dir*, when the rule is on; {} when it
    is off (nothing is asked, nothing is written)."""
    if not enabled():
        return {}
    from docpipe.refinement.config import LLM_NUM_PARALLEL
    if ask is None:
        ask, fits = make_ask()
    salt = prompt_salt()
    total = {"asked": 0, "answered": 0, "kept": 0, "dropped": 0,
             "too_long": 0}
    for pdf_dir in document_dirs(Path(data_dir), DOCUMENT_JSON):
        with open(pdf_dir / DOCUMENT_JSON, "r", encoding="utf-8") as fh:
            merged = json.load(fh)
        counts = ask_document(merged, pdf_dir, ask, salt=salt,
                              workers=LLM_NUM_PARALLEL, fits=fits)
        for name, n in counts.items():
            total[name] += n
        if counts["asked"] or counts["too_long"]:
            log.info("%s: context sentences: requests asked %d, answered %d, "
                     "dropped %d; tables and figures too long %d",
                     pdf_dir.name, counts["asked"], counts["answered"],
                     counts["dropped"], counts["too_long"])
    log.info("context sentences: requests asked %d, answered %d, dropped %d; "
             "tables and figures kept %d, too long %d", total["asked"],
             total["answered"], total["dropped"], total["kept"],
             total["too_long"])
    return total


def messages_of(system: str, request: dict) -> list:
    return [{"role": "system", "content": system},
            {"role": "user", "content": json.dumps(request, ensure_ascii=False)}]


def window_fits(system: str, max_tokens: int, *, base_url: str, model: str,
                api_key: str = "") -> Callable[[dict], bool]:
    """fits(request): does a request with *system* and room for a reply of
    *max_tokens* tokens fit the window of the server at *base_url*? The
    window is the server's (`docpipe.window.served_limit`), else the rule
    `model_window_tokens`; a request whose bytes and the frame of an empty
    request fit is let through uncounted, any other one is counted by the
    server's own template (`/tokenize`), and by its bytes where the server
    counts none."""
    from docpipe import window
    limit = (window.served_limit(base_url, model, api_key)
             or int(rules.get("model_window_tokens")))
    frame = window.server_frame(base_url, model,
                                [{"role": "system", "content": ""},
                                 {"role": "user", "content": ""}],
                                api_key, add_generation_prompt=True)
    room = limit - int(max_tokens)

    def fits(request) -> bool:
        # A request, or the messages of one (a re-ask, `reading.again`).
        messages = (request if isinstance(request, list)
                    else messages_of(system, request))
        size = sum(len(m["content"].encode("utf-8")) for m in messages)
        if frame is not None and size + frame <= room:
            return True
        if frame is None:
            return size <= room
        exact = window.server_frame(base_url, model, messages, api_key,
                                    add_generation_prompt=True)
        return (exact if exact is not None else size + frame) <= room
    return fits


def make_ask() -> tuple:
    """(ask, fits): the request to the chat model of the refinement stage
    (LLM_BASE_URL, LLM_MODEL, or the profile's provider settings), and
    whether a request fits its window."""
    from docpipe.refinement import config as llm
    client = providers.client("llm", base_url=llm.LLM_BASE_URL,
                              api_key=llm.LLM_API_KEY, timeout=llm.LLM_TIMEOUT,
                              max_retries=0)
    prompt = prompts.load(PROMPT_ID)
    max_tokens = int(prompt.meta.get(
        "max_tokens", rules.get("context_default_max_tokens")))
    fits = window_fits(prompt.text, max_tokens, base_url=llm.LLM_BASE_URL,
                       model=llm.LLM_MODEL, api_key=llm.LLM_API_KEY)
    ask = lambda request: ask_model(
        client, request, system=prompt.text, model=llm.LLM_MODEL,
        temperature=float(prompt.meta.get(
            "temperature", rules.get("context_default_temperature"))),
        max_tokens=max_tokens,
        max_retries=int(rules.get("refine_max_attempts")), fits=fits)
    return ask, fits


def ask_model(client, request: dict, *, system: str, model: str,
              temperature: float, max_tokens: int, max_retries: int,
              wait: Callable = time.sleep,
              fits: Optional[Callable] = None) -> Optional[str]:
    """One request. The reply is read as exactly one JSON object with the key
    `sentence`; a reply that is not is asked again with its cause named, at most
    *max_retries* times, all of it shown where that fits the window (*fits*
    over messages), else the request anew with its cause named
    (`reading.again`). None where no sentence came back."""
    base = messages_of(system, request)
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
        messages = reading.again(
            base, content, said or prompts.text(EMPTY_PROMPT_ID), cause,
            fits=fits)
    return None
