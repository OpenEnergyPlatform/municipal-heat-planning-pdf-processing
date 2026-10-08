#!/usr/bin/env python3
"""
chat_search_recall.py - How often the chat's search puts the passage and the
page a harvested value was read from among its hits.

The harvest read every accepted value from one passage, and its two checks
(the quote stands in a shown passage, the answer stands in the quote) already
say that passage carries the value. That is a target nobody has to judge. For
each accepted value this script puts the spec's question for the value's
parameter, the parameter's label, to the chat's own search path: the search
sentence the model writes, its embedding, and the hybrid search over the
scopes the index holds. It then counts whether the value's passage, and the
page that passage starts on, are among the first hits the chat reads and
among all the hits it retrieves.

    python scripts/chat_search_recall.py data/extraction/corpus --profile kwp
    python scripts/chat_search_recall.py <harvest dir> --db <db> --index <index>
    python scripts/chat_search_recall.py <harvest dir> --whole-corpus

The counts are split by how the harvest came to read the passage, as far as
its trace says: found by a search of its own (the plan listed the passage as a
retrieval hit), or by the document's structure (the plan listed it so and not
as a hit). A passage the harvest found by search is one a search is likely to
find again, so that row reads better than the other and the two are not one
number. Two more rows hold what the trace does not say: a passage that no plan
event of its document lists (read after the plan, for instance from a search
the model asked for, so not a finding by structure either) and a document
without a plan in the trace.

It stops after the search. No passage is read, no answer is written, nothing
judges a number, and so nothing here says whether the chat answers right. A
passage is named by the database's own ids, which are counters: a database
built again since the harvest needs `python -m docpipe.extraction.identity`
first, or a value's passage is another one. A value whose passage is not in the
database under its document is counted and left out. Where the search sentence
is the question itself, the model did not answer and the chat's own fallback
searched with the question: that is counted and said, not hidden.

Needs the model server and the embedder, and reads the corpus database and
index read-only. The vectors are not cached, so a run measures the embedder
that is configured now.

Author: Felix Vossel
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docpipe import jsonl                                           # noqa: E402
from docpipe.estimate import TRACE_DIR                              # noqa: E402
from docpipe.extraction.serialize import collect                    # noqa: E402
from docpipe.profile import (add_profile_argument,                  # noqa: E402
                             bind_command_line, require_profile)

# How the harvest came to read a passage, from its trace.
SEARCH = "found by search"
STRUCTURE = "found by structure"
UNPLANNED = "not in the plan"
UNKNOWN = "no plan in the trace"
ORIGINS = (SEARCH, STRUCTURE, UNPLANNED, UNKNOWN)
# The words the plan event uses for a passage a search listed and for one the
# document's structure listed.
RETRIEVAL = "retrieval"
BY_STRUCTURE = "structure"


@dataclass(frozen=True)
class Value:
    """One accepted value and where the harvest read it from."""
    document: str            # the harvest's name for the document
    document_id: int
    parameter: str          # the spec's uri
    kind: str               # section | table | figure
    owner: int              # the passage's id in the database
    page: Optional[int]     # the page the passage starts on


# The harvest and its trace
def harvest_values(rows_by_document: dict) -> tuple:
    """([Value], {why: rows}) of the accepted rows of a harvest.

    A row that does not say where it was read from cannot be asked about, and
    is counted under `no address` instead of being dropped without a word.
    """
    values, left = [], collections.Counter()
    for document, rows in rows_by_document.items():
        for row in rows:
            where = row.get("provenance") or {}
            kind, owner = where.get("owner_kind"), where.get("owner_id")
            document_id = where.get("document_id")
            if not (isinstance(kind, str) and isinstance(owner, int)
                    and isinstance(document_id, int)
                    and isinstance(row.get("parameter"), str)):
                left["no address"] += 1
                continue
            page = where.get("page")
            values.append(Value(
                document, document_id, row["parameter"], kind, owner,
                page if isinstance(page, int) else None))
    return values, left


@dataclass
class Plans:
    """What the harvest's trace says about how passages were planned."""
    origins: dict            # (document id, kind, owner) -> {plan origins}
    traced: set              # ids of the documents that have plan events

    def of(self, value: Value) -> str:
        if value.document_id not in self.traced:
            return UNKNOWN
        planned = self.origins.get(
            (value.document_id, value.kind, value.owner), ())
        if RETRIEVAL in planned:
            return SEARCH
        # Absence from the plan is not structure: a passage the model asked
        # for after the plan was found by a search, and the trace says neither.
        return STRUCTURE if BY_STRUCTURE in planned else UNPLANNED


def read_plans(directory: Path, names: Iterable[str]) -> Plans:
    """The plan events of the trace beside a harvest, for the named
    documents. A missing trace is no plan, not an error: it is said."""
    origins: dict = collections.defaultdict(set)
    traced: set = set()
    for name in names:
        path = Path(directory) / TRACE_DIR / f"{name}.trace.jsonl"
        if not path.is_file():
            continue
        for line in jsonl.read(path):
            if '"plan"' not in line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict) or event.get("t") != "plan" \
                    or not isinstance(event.get("doc"), int):
                continue
            traced.add(event["doc"])
            origins[(event["doc"], event.get("kind"),
                     event.get("owner"))].add(event.get("origin"))
    return Plans(dict(origins), traced)


# The chat's search
class ChatSearch:
    """The chat's search for one question, as the chat runs it.

    The search sentence is the model's, the embedding the configured
    embedder's, and the ranking `answer.search_hits`, which `answer_question`
    calls too. One search per (document, parameter): its question does not
    change with the value, and the ranking does not either.
    """

    def __init__(self, corpus, scopes: list, questions: dict):
        from docpipe.inference import answer, llm_client
        self._answer, self._llm = answer, llm_client
        self.corpus, self.scopes, self.questions = corpus, scopes, questions
        self._seen: dict = {}
        # Searches whose sentence is the question itself: the model's
        # request did not come back with one.
        self.sentence_is_question = 0

    def __len__(self) -> int:
        return len(self._seen)

    def __call__(self, document_id: Optional[int], parameter: str) -> list:
        """[(kind, owner, document id, page)] of the hits, best first."""
        key = (document_id, parameter)
        if key not in self._seen:
            question = self.questions[parameter]
            phrase, _recheck = self._llm.make_search_phrase(
                question, visual=self._answer.scopes_are_visual(self.scopes))
            if phrase.strip() == question.strip():
                self.sentence_is_question += 1
            vector, _cached = self.corpus.embed({"text": phrase})
            hits = self._answer.search_hits(
                question, phrase, vector, self.corpus, document_id,
                self.scopes)
            self._seen[key] = [
                (hit["owner_kind"], hit["owner_id"], hit.get("document_id"),
                 hit.get("page_number")) for hit in hits]
        return self._seen[key]


# The count
def measure(values: list, search: Callable, plans: Plans,
            in_database: Callable, first: int, *,
            whole_corpus: bool = False) -> dict:
    """{origin: Counter} and {"left": Counter} of the values.

    A value counts `passage first` / `passage hits` when its passage is among
    the first `first` hits / among all the hits, and the same for its page;
    `pages` counts the values that name one. A value whose passage is not in
    the database under its document is left out and counted.
    """
    counts = {origin: collections.Counter() for origin in ORIGINS}
    left: collections.Counter = collections.Counter()
    for value in values:
        if not in_database(value):
            left["not in the database"] += 1
            continue
        hits = search(None if whole_corpus else value.document_id,
                      value.parameter)
        count = counts[plans.of(value)]
        count["values"] += 1
        passages = [(kind, owner) for kind, owner, _d, _p in hits]
        pages = [(document, page) for _k, _o, document, page in hits]
        here = (value.kind, value.owner)
        if here in passages[:first]:
            count["passage first"] += 1
        if here in passages:
            count["passage hits"] += 1
        if value.page is not None:
            count["pages"] += 1
            there = (value.document_id, value.page)
            if there in pages[:first]:
                count["page first"] += 1
            if there in pages:
                count["page hits"] += 1
    return {"counts": counts, "left": left}


def _share(found: int, of: int) -> str:
    return f"{found:,}/{of:,} ({100.0 * found / of:.1f}%)" if of else "-"


def render(result: dict, *, first: int, hits: int, searches: int,
           sentence_is_question: int, whole_corpus: bool, accepted: int,
           unplaced: dict) -> str:
    """The report, as text."""
    counts, left = result["counts"], result["left"]
    measured = sum(c["values"] for c in counts.values())
    out = [
        "chat search against the harvest: does the search put the value's "
        "passage and page among its hits",
        f"search: {'the whole corpus' if whole_corpus else 'one document'}; "
        f"the chat reads the first {first} of the up to {hits} hits it "
        f"retrieves",
        f"question: the label of the value's parameter in the spec; "
        f"{searches:,} search(es), one per "
        f"{'parameter' if whole_corpus else 'document and parameter'}",
        f"searches whose sentence is the question itself (the model gave "
        f"none): {sentence_is_question:,} of {searches:,}",
        f"values: {accepted:,} accepted; {measured:,} measured",
    ]
    for why, count in sorted({**unplaced, **left}.items()):
        out.append(f"  not measured, {why}: {count:,} value(s)")
    header = (f"{'':<24}{'values':>8}  {'passage in first ' + str(first):<22}"
              f"{'passage in all hits':<22}{'page in first ' + str(first):<22}"
              f"{'page in all hits':<22}")
    out += ["", header.rstrip()]
    total: collections.Counter = collections.Counter()
    for origin in ORIGINS:
        total.update(counts[origin])
    for label, count in [*((o, counts[o]) for o in ORIGINS), ("all", total)]:
        out.append((
            f"{label:<24}{count['values']:>8,}  "
            f"{_share(count['passage first'], count['values']):<22}"
            f"{_share(count['passage hits'], count['values']):<22}"
            f"{_share(count['page first'], count['pages']):<22}"
            f"{_share(count['page hits'], count['pages']):<22}").rstrip())
    out.append("")
    out.append("Passage columns are of values; page columns are of the "
               "values that name a page.")
    out.append(f"{SEARCH}: the plan of the harvest listed the passage as a "
               f"retrieval hit; {STRUCTURE}: it listed it by the document's "
               f"structure; {UNPLANNED}: no plan event of the document lists "
               f"it, so it was read after the plan.")
    return "\n".join(out)


# The corpus
def open_chat(db_path: Path, index_path: Path):
    """(corpus, scopes, in_database) as the chat opens them: the database
    read-only, the global index, the word index where it is current, and the
    configured embedder asked one query at a time without a cache."""
    from docpipe.app import config
    from docpipe.inference import answer, db, faiss_store, lexical

    for path in (db_path, index_path):
        if not Path(path).is_file():
            raise SystemExit(f"{path} is not a file: this reads a corpus "
                             f"that `docpipe chunk` has written")
    conn = db.connect_readonly(db_path)
    index, id_to_pos = faiss_store.load_global_index(index_path)

    def embed(item: dict):
        # Imported here: a backend that loads a model is loaded when it is
        # first asked, as in the chat, and a cache would hand back the
        # vectors of the embedder this one is measured against.
        from docpipe.embedding import get_embedder
        return get_embedder().embed_one(item), False

    corpus = answer.Corpus(
        conn=conn, index=index, id_to_pos=id_to_pos, embed=embed,
        lexical=lexical.connect(db_path) if config.LEXICAL else None)

    def in_database(value: Value) -> bool:
        try:
            content = db.fetch_owner_content(conn, value.kind, value.owner)
        except ValueError:
            return False
        return content is not None \
            and content.get("document_id") == value.document_id

    return corpus, db.available_scopes(conn), in_database


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python scripts/chat_search_recall.py",
        description="Count how often the chat's search puts the passage and "
                    "the page a harvested value was read from among its "
                    "hits. Stops after the search.")
    parser.add_argument("harvest", type=Path,
                        help="harvest directory (<name>.jsonl per document, "
                             "and trace/ beside them)")
    parser.add_argument("--db", type=Path, default=None,
                        help="corpus database (default: the chat's)")
    parser.add_argument("--index", type=Path, default=None,
                        help="FAISS index (default: the chat's)")
    parser.add_argument("--whole-corpus", action="store_true",
                        help="search the whole corpus, as the chat does with "
                             "its box ticked, instead of the value's document")
    parser.add_argument("--documents", type=int, default=None,
                        help="only the first N documents of the harvest, "
                             "by name")
    add_profile_argument(parser)
    return parser


def main(argv: Optional[list] = None) -> int:
    bind_command_line(argv)           # --profile, before the chat's modules
    args = _parser().parse_args(argv)
    if not args.harvest.is_dir():
        print(f"not a directory: {args.harvest}", file=sys.stderr)
        return 1
    profile = require_profile(args)
    spec_path = profile.component("extraction", "SPEC_PATH")
    if spec_path is None:
        print(f"profile {profile.name!r} has no extraction spec: there is "
              f"no question to ask", file=sys.stderr)
        return 1
    from docpipe.extraction.spec import load as load_spec
    questions = {p.uri: p.label for p in load_spec(spec_path).parameters}

    harvest = collect(args.harvest)
    if args.documents is not None:
        harvest = dict(list(harvest.items())[:max(0, args.documents)])
    values, unplaced = harvest_values(harvest)
    accepted = sum(len(rows) for rows in harvest.values())
    if not accepted:
        print(f"{args.harvest} holds no accepted value", file=sys.stderr)
        return 1
    # A value of a parameter the spec no longer has has no question.
    asked = [v for v in values if v.parameter in questions]
    if len(asked) < len(values):
        unplaced["parameter not in the spec"] = len(values) - len(asked)
    plans = read_plans(args.harvest, harvest)

    from docpipe.app import config
    from docpipe.inference.config import MAX_CHUNK_ATTEMPTS, TOP_K
    corpus, scopes, in_database = open_chat(
        args.db or config.DB_PATH, args.index or config.INDEX_PATH)
    search = ChatSearch(corpus, scopes, questions)
    result = measure(asked, search, plans, in_database, MAX_CHUNK_ATTEMPTS,
                     whole_corpus=args.whole_corpus)
    print(render(result, first=MAX_CHUNK_ATTEMPTS, hits=TOP_K,
                 searches=len(search),
                 sentence_is_question=search.sentence_is_question,
                 whole_corpus=args.whole_corpus, accepted=accepted,
                 unplaced=dict(unplaced)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
