"""
statements.py: Which of the statements a model made the reader is shown.

The answer of the chat is a list of statements, each with its own evidence
(`replies.answer`). A statement is shown only if its evidence stands, and the
reader is told how many were not (`back`). What a statement has to show is
the existing rule and nothing beyond it:

  text      its quote stands in the excerpt it cites, whole, and is at least
            as long as a quote has to be (`llm_client.grounded_quote`)
  image     the crop it reads off was attached to this call, or is one the
            model asked for and got, and it names what it read
            (`llm_client.visual_reading`)
  computed  its quote stands in the excerpt that holds the inputs AND the run
            it names is a run of this call that ran without an error

Whether a statement says what its quote says is reading, not a check (the
harvest's second half has no counterpart here). Nothing in this module asks
a model anything or reads a file.

Statements are carried forward as checked and never rewritten: what a later
batch is shown of the earlier ones is `texts`, and what it adds is appended.

Author: Felix Vossel
"""
from __future__ import annotations

from typing import Optional

from . import llm_client, replies

# Why a statement was dropped. The reader of the app is told one sentence and
# a count; the cause per statement goes to the log.
WHY = ("blank", "no_source", "quote", "image", "run")


def _number(value) -> Optional[int]:
    """The integer a model wrote for an index or a run, or None. The reply
    schema asks for an integer, and nothing else is turned into one: a float
    would read as the number before its point (1.7 as 1), and a digit in
    quotation marks is text the model wrote where a number was asked."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _flat(text) -> str:
    """One line: a statement is a list item and a line of the history."""
    return " ".join(str(text or "").split())


def back(statements, *, items: dict, hits: list, attached: set,
         delivered: dict, runs: list, run_offset: int = 0,
         grounded=None, visual=None) -> tuple:
    """(shown, dropped) of the statements a model made for one batch.

    *items* maps the index of each excerpt of this batch to it, *hits* is the
    retrieval list those indices point into, *attached* the indices whose crop
    went with the call, *delivered* maps the block of each crop the model
    asked for and got to {"hit": the passage it belongs to}, *runs* are the
    code runs of this call ({"code", "output"}) and *run_offset* the number of
    runs before them in the turn, so a shown run carries its number in the
    turn.

    A shown statement is {"text", "basis", "index", "block", "owner_kind",
    "owner_id", "quote", "visual", "computed", "run", "hit"}; a dropped one is
    what the model wrote and its `why` (one of `WHY`). Every statement is one
    or the other: len(shown) + len(dropped) == len(statements).

    *grounded* and *visual* are the checks (`llm_client.grounded_quote`,
    `llm_client.visual_reading`), looked up when called so that nothing here
    is bound to a copy of them.
    """
    grounded = grounded or llm_client.grounded_quote
    visual = visual or llm_client.visual_reading
    shown, dropped = [], []

    def drop(statement, why):
        row = dict(statement) if isinstance(statement, dict) \
            else {"statement": statement}
        row["why"] = why
        dropped.append(row)

    for statement in statements or []:
        if not isinstance(statement, dict):
            drop(statement, "blank")
            continue
        text = _flat(statement.get("statement"))
        basis = statement.get("basis")
        if not text or basis not in replies.BASES:
            drop(statement, "blank")
            continue
        index = _number(statement.get("index"))
        block = llm_client.crop_id(statement.get("block"))
        # what the model wrote, with the index as the number it is
        read = {**statement, "index": index}
        entry = {"text": text, "basis": basis, "index": index,
                 "block": block or None, "visual": False, "computed": False,
                 "run": None}

        if basis == "image" and block:
            # A crop the model asked for: it has no index in this batch.
            reading = visual(read, attached, frozenset(delivered))
            if reading is None:
                drop(statement, "image")
                continue
            hit = delivered[block]["hit"]
            entry.update(quote=reading, visual=True, index=None, block=block)
        else:
            if index not in items or not 0 <= index < len(hits):
                drop(statement, "no_source")
                continue
            hit = hits[index]
            if basis == "image":
                reading = visual(read, attached, frozenset(delivered))
                if reading is None:
                    drop(statement, "image")
                    continue
                entry.update(quote=reading, visual=True)
            else:
                quote = grounded(statement.get("quote", ""), items[index])
                if quote is None:
                    drop(statement, "quote")
                    continue
                entry["quote"] = quote
                if basis == "computed":
                    number = _number(statement.get("run"))
                    ran = (number is not None and 1 <= number <= len(runs)
                           and (runs[number - 1].get("output") or {})
                           .get("ok") is True)
                    if not ran:
                        drop(statement, "run")
                        continue
                    entry.update(computed=True, run=run_offset + number)
        entry.update(owner_kind=hit["owner_kind"], owner_id=hit["owner_id"],
                     hit=hit)
        shown.append(entry)
    return shown, dropped


def blocks_named(wrote) -> set:
    """The crops the statements of a reply name as their `block`: the ones
    whose passage has to be looked up before the statements are checked."""
    return {llm_client.crop_id(s.get("block")) for s in wrote or ()
            if isinstance(s, dict)} - {""}


def texts(shown: list) -> list:
    """What a later batch is told was already said: the checked statements,
    exactly as they were checked."""
    return [s["text"] for s in shown]


def citations_of(shown: list) -> list:
    """One citation per distinct (source, quote, run) over the shown
    statements in order, numbered from 1; each statement gets the number of
    its citation as `citation`.

    The quote is part of the key: two statements from one table with two
    quotes are two pieces of evidence, and a reader checking the first must
    not be sent to the second. A calculated statement is a citation of its
    own for each run it names.
    """
    cited: dict = {}
    out: list = []
    for statement in shown:
        key = (statement["owner_kind"], statement["owner_id"],
               llm_client._norm(statement["quote"]), statement["run"])
        if key not in cited:
            out.append({**statement["hit"], "quote": statement["quote"],
                        "visual": statement["visual"],
                        "computed": statement["computed"],
                        "run": statement["run"], "n": len(out) + 1})
            cited[key] = out[-1]
        statement["citation"] = cited[key]["n"]
    return out


def assemble(shown: list, marker: str, note: str) -> tuple:
    """(answer, answer_text) of the shown statements.

    One statement is a sentence, two or more are a list; each carries the
    number of its citation. `answer_text` is the same statements without
    list marks and numbers: what a follow-up and a comparison are given, so
    a statement that was dropped can reach neither.

    A statement read off a picture has to say so. Where one does not, the
    profile's note is added once, under the answer and under its text.
    """
    if not shown:
        return None, None

    def mark(statement):
        number = statement.get("citation")
        return f" [{number}]" if number else ""

    if len(shown) == 1:
        answer = shown[0]["text"] + mark(shown[0])
    else:
        answer = "\n".join(f"- {s['text']}{mark(s)}" for s in shown)
    answer_text = "\n".join(s["text"] for s in shown)
    if any(s["visual"] and marker.casefold() not in s["text"].casefold()
           for s in shown):
        answer = answer.rstrip() + "\n\n" + note
        answer_text = answer_text.rstrip() + "\n\n" + note
    return answer, answer_text
