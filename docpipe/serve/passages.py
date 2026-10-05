"""
passages.py: The passages of the corpus, found by word.

`find_values` answers from what the harvest read. This answers from what
the documents say, for the question the harvest has no value for: it asks
the word index (`inference/lexical.py`) and hands back each passage with
its document, the title of its section, its page and its text, so that a
program can quote it. It is a search and not a reading: a passage found
here is not a verified value.

It needs the corpus database and the word index built from it. Without
either it says so, with what to do about it, and answers no search. A
missing index that answered "nothing found" would read as "the corpus does
not say it", and a stale one would name a passage the database no longer
has. The index is checked once, when the server starts, as the chat does.

Author: Felix Vossel
"""
from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path
from typing import Optional

from ..inference import db as corpus
from ..inference import lexical
from ..store.schema import readonly_uri
from .values import MAX_LIMIT, NotFound

log = logging.getLogger(__name__)

DEFAULT_LIMIT = 10
NO_DATABASE = ("no corpus database was given: name one with --db, or a "
               "--profile that has one")


class Unavailable(RuntimeError):
    """A search that cannot be answered here, and why."""


class Passages:
    """The corpus database and its word index, opened read-only.

    Never raises for what is missing: `why` says what, and `search` raises
    `Unavailable` with it. Documents are named as the harvest names them,
    the file name without its ending.
    """

    def __init__(self, db_path=None):
        self.db_path = Path(db_path) if db_path is not None else None
        self.why: Optional[str] = None
        self._lock = threading.Lock()
        self._conn: Optional[sqlite3.Connection] = None
        self._index: Optional[sqlite3.Connection] = None
        self._ids: dict = {}            # harvest name -> Documents.id
        self._names: dict = {}          # Documents.id -> harvest name
        self.why = self._open()
        if self.why is not None:
            log.warning("passages: search is not available: %s", self.why)
            self.close()
        else:
            log.info("passages: search is ready on %s (%d document(s))",
                     self.db_path, len(self._names))

    @property
    def available(self) -> bool:
        return self.why is None

    def _open(self) -> Optional[str]:
        """None when the search is ready, else why it is not."""
        if self.db_path is None:
            return NO_DATABASE
        if not self.db_path.is_file():
            return f"{self.db_path} is not a file"
        index_path = lexical.path_for(self.db_path)
        found = lexical.state(self.db_path)
        if found == "missing":
            return (f"the word index {index_path} is missing: `docpipe "
                    f"lexical {self.db_path}` builds it")
        if found != "current":
            return (f"the word index {index_path} was built from another "
                    f"state of {self.db_path}: `docpipe lexical "
                    f"{self.db_path}` builds it again")
        try:
            self._conn = corpus.connect_readonly(self.db_path)
            self._index = sqlite3.connect(readonly_uri(index_path), uri=True,
                                          check_same_thread=False)
            for ident, filename in self._conn.execute(
                    'SELECT "id", "filename" FROM "Documents"'):
                name = Path(filename).stem if filename else None
                self._names[ident] = name
                if name is not None:
                    self._ids[name] = ident
        except sqlite3.DatabaseError as exc:
            return f"{self.db_path} could not be read as a corpus ({exc})"
        # Asked once here and not only at the first search: an SQLite without
        # FTS5 opens the index and fails every query, and the tool would be
        # listed as working all the same.
        try:
            self._index.execute('SELECT 1 FROM "passages" LIMIT 1').fetchall()
        except sqlite3.DatabaseError as exc:
            return (f"the word index {index_path} could not be asked here "
                    f"({exc})")
        return None

    def close(self) -> None:
        for handle in (self._conn, self._index):
            if handle is not None:
                handle.close()
        self._conn = self._index = None

    def search(self, text: str, *, document: Optional[str] = None,
               limit: int = DEFAULT_LIMIT) -> dict:
        """{words, passages}: the passages that carry words of *text*, best
        first, at most *limit* of them and never more than `MAX_LIMIT`.

        `words` are the words that were looked for; a passage with any of
        them is found, one with more of them and rarer ones ranks higher. A
        passage is {document, kind, id, title, section_title, page, text,
        rank}. *document* limits the search to one document, by its harvest
        name. Raises `Unavailable` where there is no search to ask and
        `NotFound` for a document the database does not have.
        """
        if self.why is not None:
            raise Unavailable(self.why)
        words = lexical.words(text)
        if not words:
            raise ValueError("text has no word to look for")
        if limit < 0:
            raise ValueError("limit is not negative")
        wanted = None
        if document is not None:
            wanted = self._ids.get(document)
            if wanted is None:
                raise NotFound(f"the corpus database has no document "
                               f"{document!r}")
        with self._lock:
            try:
                hits = lexical.search(self._index, text, document=wanted,
                                      limit=min(limit, MAX_LIMIT))
            except sqlite3.OperationalError as exc:
                raise Unavailable(
                    f"the word index could not be asked: {exc}") from exc
            found = []
            for rank, (kind, owner, document_id) in enumerate(hits, 1):
                content = corpus.fetch_owner_content(self._conn, kind, owner)
                if content is None:
                    raise Unavailable(
                        f"the word index names {kind} {owner}, which "
                        f"{self.db_path} no longer has: `docpipe lexical "
                        f"{self.db_path}` builds it again")
                found.append({
                    "document": self._names.get(document_id),
                    "kind": kind, "id": owner,
                    "title": content.get("title"),
                    "section_title": content.get("section_title"),
                    "page": content.get("page_number"),
                    "text": content.get("text"), "rank": rank})
        return {"words": words, "passages": found}
