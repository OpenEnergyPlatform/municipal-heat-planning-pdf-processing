"""
lexical.py: A word index over the corpus, beside the vector index.

The vector search finds a passage by what it means. It is weak exactly
where a question is most specific: a name, an abbreviation, a number, a
place. "Stadtwerke Marburg" and "Stadtwerke Kassel" are neighbours in the
embedding space and different words on the page, and a search over a whole
corpus that cannot tell them apart answers from the wrong document. A word
index can, so the chat asks both and merges the two rankings
(`hybrid.py`).

The index is a file of its own beside the corpus database
(`<name>.lexical.db`), built from it and never written into it: the corpus
database stays what the chunk stage made, and the chat keeps opening it
read-only.

    docpipe lexical DB          build it, or build it again
    docpipe lexical DB --check  say whether it is there and current

It holds one row per section, table and figure with its title and text
(SQLite FTS5). It notes a digest of the passages it was built from; a
database whose passages have since changed makes it stale, and a stale
index is not asked: a hit for a passage that no longer exists, or for a
word it no longer has, would be worse than none.

Author: Felix Vossel
"""
from __future__ import annotations

import argparse
import hashlib
import logging
import re
import sqlite3
import sys
from pathlib import Path
from typing import Iterable, Optional, Sequence

from ..store.schema import readonly_uri

log = logging.getLogger(__name__)

SUFFIX = ".lexical.db"
KINDS = ("section", "table", "figure")
SOURCES = {
    "section": ('SELECT s."id", s."document", s."title", s."content" '
                'FROM "Sections" s'),
    "table": ('SELECT t."id", s."document", t."caption", t."markdown" '
              'FROM "Tables" t JOIN "Sections" s ON s."id" = t."section"'),
    "figure": ('SELECT i."id", s."document", i."caption", i."description" '
               'FROM "Images" i JOIN "Sections" s ON s."id" = i."section"'),
}
_WORD = re.compile(r"\w+", re.UNICODE)
# Words that are in every passage rank nothing and cost a scan each.
MAX_WORDS = 24


def path_for(db_path) -> Path:
    db_path = Path(db_path)
    return db_path.with_name(db_path.stem + SUFFIX)


def _passages(corpus: sqlite3.Connection):
    """(kind, id, document, title, text) of every passage of a corpus, in
    an order that is the same every time."""
    for kind in KINDS:
        for owner, document, title, text in corpus.execute(
                SOURCES[kind] + " ORDER BY 1"):
            yield kind, owner, document, title or "", text or ""


def _note(digest, passage: tuple) -> None:
    digest.update(repr(passage).encode("utf-8", "surrogatepass"))


def _fingerprint(corpus: sqlite3.Connection) -> str:
    """A digest over every passage: its kind, its id, its document and its
    words. A count would not see a text that was rewritten in place, and
    the index would go on finding words the passage no longer has."""
    digest = hashlib.sha256()
    for passage in _passages(corpus):
        _note(digest, passage)
    return digest.hexdigest()


def build(db_path, out: Optional[Path] = None) -> dict:
    """Build the word index of a corpus database. Returns what it holds."""
    db_path = Path(db_path)
    out = Path(out) if out is not None else path_for(db_path)
    corpus = sqlite3.connect(readonly_uri(db_path), uri=True)
    fresh = out.with_name(out.name + ".building")
    fresh.unlink() if fresh.exists() else None
    index = sqlite3.connect(fresh)
    done = False
    try:
        try:
            index.execute(
                'CREATE VIRTUAL TABLE "passages" USING fts5('
                '"title", "text", "owner_kind" UNINDEXED, '
                '"owner_id" UNINDEXED, "document" UNINDEXED, '
                "tokenize = 'unicode61 remove_diacritics 2')")
        except sqlite3.OperationalError as exc:
            raise RuntimeError(
                f"this Python's SQLite has no FTS5 ({exc}); the word index "
                f"cannot be built here") from exc
        index.execute('CREATE TABLE "meta" ("key" TEXT PRIMARY KEY, '
                      '"value" TEXT)')
        held = dict.fromkeys(KINDS, 0)
        digest = hashlib.sha256()
        for passage in _passages(corpus):
            _note(digest, passage)
            kind, owner, document, title, text = passage
            if not (title or text):
                continue
            index.execute(
                'INSERT INTO "passages" ("title", "text", "owner_kind", '
                '"owner_id", "document") VALUES (?, ?, ?, ?, ?)',
                (title, text, kind, owner, document))
            held[kind] += 1
        index.execute('INSERT INTO "meta" VALUES (?, ?)',
                      ("corpus", digest.hexdigest()))
        index.commit()
        done = True
    finally:
        index.close()
        corpus.close()
        if not done:
            fresh.unlink()
    # Whole or not at all: a chat that opens the index mid-build would
    # search half a corpus.
    try:
        fresh.replace(out)
    except OSError as exc:
        fresh.unlink()
        raise RuntimeError(
            f"{out} could not be replaced ({exc}). A program that has it "
            f"open holds it, most likely the chat: stop it and run this "
            f"again. The index that was there is as it was.") from exc
    log.info("lexical: %s holds %s", out, held)
    return held


def state(db_path, index_path: Optional[Path] = None) -> str:
    """`current`, `stale` or `missing`."""
    index_path = Path(index_path) if index_path else path_for(db_path)
    if not index_path.is_file():
        return "missing"
    corpus = sqlite3.connect(readonly_uri(db_path),
                             uri=True)
    index = sqlite3.connect(readonly_uri(index_path), uri=True)
    try:
        row = index.execute('SELECT "value" FROM "meta" WHERE "key" = '
                            "'corpus'").fetchone()
        return "current" if row and row[0] == _fingerprint(corpus) \
            else "stale"
    except sqlite3.DatabaseError:
        return "stale"
    finally:
        index.close()
        corpus.close()


def connect(db_path, index_path: Optional[Path] = None
            ) -> Optional[sqlite3.Connection]:
    """The word index of a corpus, opened read-only, or None when it is
    missing or stale. None is said in the log, once, with what to do."""
    index_path = Path(index_path) if index_path else path_for(db_path)
    found = state(db_path, index_path)
    if found != "current":
        log.warning("lexical: the word index %s is %s; the search is by "
                    "meaning only. `docpipe lexical %s` builds it.",
                    index_path, found, db_path)
        return None
    return sqlite3.connect(readonly_uri(index_path), uri=True,
                           check_same_thread=False)


def words(text: str) -> list:
    """The words of a question as they are looked for: each once, in the
    order they came, and not more than a question plausibly has."""
    seen: list = []
    for word in _WORD.findall(text or ""):
        # Lowered and no more: the index folds what it stores itself and
        # keeps a sharp s, which `casefold` would write as "ss".
        folded = word.lower()
        if len(folded) > 1 and folded not in seen:
            seen.append(folded)
    return seen[:MAX_WORDS]


def search(index: sqlite3.Connection, text: str, *,
           document: Optional[int] = None,
           kinds: Optional[Iterable[str]] = None,
           limit: int = 50) -> list:
    """[(owner_kind, owner_id, document)] best first, for the passages that
    carry words of *text*. A passage with more of them, and with rarer
    ones, ranks higher (BM25); a word in the title counts double."""
    looked_for = words(text)
    if not looked_for or limit <= 0:
        return []
    # Each word quoted: the question's punctuation is not FTS5 syntax.
    query = " OR ".join(f'"{word}"' for word in looked_for)
    where = ['"passages" MATCH ?']
    params: list = [query]
    if document is not None:
        where.append('"document" = ?')
        params.append(document)
    kinds = [kind for kind in (kinds or ()) if kind in KINDS]
    if kinds:
        where.append(f'"owner_kind" IN ({",".join("?" * len(kinds))})')
        params.extend(kinds)
    params.append(limit)
    rows = index.execute(
        'SELECT "owner_kind", "owner_id", "document" FROM "passages" '
        f'WHERE {" AND ".join(where)} '
        'ORDER BY bm25("passages", 2.0, 1.0) LIMIT ?', params).fetchall()
    return [(str(kind), int(owner), document_id)
            for kind, owner, document_id in rows]


def main(argv: Optional[Sequence[str]] = None) -> int:
    from ..profile import add_profile_argument, program, resolve_profile
    parser = argparse.ArgumentParser(
        prog=program("docpipe.inference.lexical"),
        description="Build the word index the chat searches beside the "
                    "vector index.")
    add_profile_argument(parser)
    parser.add_argument("db", type=Path, nargs="?",
                        help="corpus database (default: the profile's)")
    parser.add_argument("--check", action="store_true",
                        help="only say whether the index is current")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(name)s "
                               "%(message)s", datefmt="%H:%M:%S")
    db = args.db
    if db is None:
        profile = resolve_profile(args)
        db = Path(profile.db_path) if profile is not None else None
    if db is None or not Path(db).is_file():
        raise SystemExit(f"{db} is not a file: name the corpus database, or "
                         f"a --profile that has one")
    if args.check:
        found = state(db)
        print(f"{path_for(db)}: {found}")
        return 0 if found == "current" else 1
    try:
        held = build(db)
    except RuntimeError as exc:
        raise SystemExit(str(exc))
    print(f"{path_for(db)}: {sum(held.values())} passage(s) "
          f"({', '.join(f'{count} {kind}(s)' for kind, count in held.items())})")
    return 0


if __name__ == "__main__":
    from docpipe.profile import bind_command_line
    bind_command_line()
    sys.exit(main())
