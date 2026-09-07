"""
compare.py – The same question put to several documents at once.

A reader who has to know which of five heat plans assumes the higher renovation
rate does not want five chat sessions and a notepad. What they want is one
question, one row per plan, and a paragraph that says where the plans differ.

Three decisions carry this module.

Retrieval stays per document. A single search across five plans returns the
passages that answer best *overall*, and plans do not write at the same length:
one devotes a chapter to renovation, another a sentence. The chapter wins every
slot in the top-k, and the table then shows an empty cell for a plan that did
say something. So each document gets its own retrieval, its own source budget
and its own citations, and the answers are compared afterwards.

The comparison call sees the finished answers and nothing else. Not a source
passage, not a quote, not a page. Handed the passages, the model can ground a
claim about plan A in a sentence out of plan B, and the citation list under the
table -- which is per plan -- would not show it. What it may see is that a plan
produced no grounded answer, because "this plan does not say it" is a finding
about that plan and belongs in the comparison.

A plan that answered nothing keeps its row. It is the same rule the extraction
side follows: an empty cell is a statement, and dropping it would let the
reader assume the plan was not asked.

Author: Felix Vossel
"""
from __future__ import annotations

from typing import Callable, Optional, Sequence

from . import config, llm_client
from .answer import Corpus, _silent, answer_question


def _labelled(progress: Callable, label: str) -> Callable:
    """The turn's own progress stages, prefixed with the document they run for.

    Not a second spinner around them: a stage nested inside a stage tells the
    reader less than "Kassel · Retrieval", and one of the two would have to be
    silent anyway.
    """
    def _stage(text: str):
        return progress(f"{label} · {text}")

    return _stage


def summary(row: dict, limit: int = 300) -> str:
    """One document's answer as a single overview line, visibly cut.

    Cut and not wrapped: the overview exists to be read across five rows at a
    glance, and the full answer stands underneath it. The ellipsis is what
    keeps a cut from reading like the end of a sentence.
    """
    flat = " ".join(str(row.get("answer_text") or row.get("answer") or "").split())
    if not flat:
        return "—"
    return flat if len(flat) <= limit else flat[:limit].rstrip() + " …"


def plan_answers(rows: Sequence) -> list:
    """The payload the comparison call is given: a label and a finished answer.

    `answer_text` and not `answer`, because a JSON-formatted answer is the same
    content in a shape written for a machine, and the comparison reasons in
    prose. None means the document produced nothing grounded.
    """
    out = []
    for row in rows:
        text = (row.get("answer_text") or row.get("answer") or "").strip()
        out.append({"label": row["label"], "answer": text or None})
    return out


def compare_documents(task: str, corpus: Corpus, documents: Sequence,
                      scopes: list, *, as_json: bool = False,
                      histories: Optional[dict] = None,
                      progress: Callable = _silent) -> dict:
    """One question, several documents, one comparison.

    `documents` is a sequence of (document_id, label) pairs; `histories` maps a
    document id to that document's earlier turns, so a follow-up and a re-check
    work per plan exactly as they do in a single-plan chat.

    Returns {task, rows, comparison, answered, as_json, dropped}: `rows` is
    one answer_question result per document with `document_id` and `label`
    added, `comparison` is prose or None, `dropped` names the documents that
    did not fit the cap.
    """
    wanted = list(documents)
    kept = wanted[: config.COMPARE_MAX_DOCUMENTS]
    result = {"task": task, "rows": [], "comparison": None, "answered": 0,
              "as_json": as_json,
              "dropped": [label for _id, label in wanted[len(kept):]]}

    for document_id, label in kept:
        turn = answer_question(task, corpus, document_id, scopes,
                               as_json=as_json,
                               history=(histories or {}).get(document_id),
                               progress=_labelled(progress, label))
        result["rows"].append({**turn, "document_id": document_id,
                               "label": label})

    answers = plan_answers(result["rows"])
    result["answered"] = sum(1 for p in answers if p["answer"])
    # One answer is not a comparison: the table already shows it, and the other
    # plans' emptiness with it. Below two, the call would only paraphrase.
    if result["answered"] >= 2:
        with progress("⚖️ Comparison"):
            result["comparison"] = llm_client.compare_answers(task, answers)
    return result
