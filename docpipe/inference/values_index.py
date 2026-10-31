"""
values_index.py: Finds harvested values by what they mean.

A question names a value in a person's words, and the harvest holds it in the
plan's words and the spec's lists. Closed questions have to land on exactly
what was read there, and a word they miss leaves nothing. So every value gets
a line of words (`entry_text`) and a vector of that line, the chat looks for
the lines nearest to its search anchor, and the model chooses among them
(`values_route.answer_from_index`).

The vectors are a file of their own beside the harvest
(`<harvest>.values.db`), built from it and never written into it:

    docpipe values-index HARVEST          build it, or bring it up to date
    docpipe values-index HARVEST --check  say whether it is there and current

A vector is filed under a digest of its line. So a line that stayed keeps its
vector through a new harvest, two values that read alike share one, and a
build that stopped goes on where it stopped: what it finished stays in the
`.building` file beside the index, and two builds on two machines can be
poured into one.

A value without a vector, or vectors of another model, make the index stale.
A stale index is not asked: a value it does not hold could never be found, and
nobody would see that it is missing. The chat then asks its closed questions,
and the log says why.

Author: Felix Vossel
"""
from __future__ import annotations

import argparse
import hashlib
import logging
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional, Sequence

import numpy as np

from ..embedding import config as embedding_config
from ..store.schema import readonly_uri

log = logging.getLogger(__name__)

SUFFIX = ".values.db"
BUILDING = ".building"
# A line says these otherwise: the parameter and the unit stand in it by
# their own names, and an aggregation says how a number was summed, not what
# it is a number of.
LEFT_OUT = ("parameter", "unit", "aggregation")
_FLOAT = "float32"
_REPORT_SECONDS = 60


def path_for(harvest_dir) -> Path:
    harvest_dir = Path(harvest_dir)
    return harvest_dir.with_name(harvest_dir.name + SUFFIX)


def _squash(text) -> str:
    return " ".join(str(text).split())


def _coordinate(entry: dict, passage: str) -> Optional[str]:
    """One coordinate as a line says it: what was read, and beside a list
    entry the plan's own word for it, where that is another one and the
    passage's title does not say it anyway."""
    label = entry.get("label")
    said = label if label not in (None, "") else entry.get("value")
    if said in (None, ""):
        return None
    wording = _squash(entry.get("wording") or "")
    if label in (None, "") or not wording \
            or wording.casefold() == str(label).casefold() \
            or wording.casefold() in passage:
        return str(said)
    return f"{said} ({wording})"


def entry_text(value: dict, name: str) -> str:
    """The line one value is searched and chosen by: whose it is, what it is
    a number of, the number as the plan writes it, and the passage it stands
    in. Made of what the harvest holds and nothing else, so the same value
    gives the same line in every language a profile has."""
    source = value.get("source") or {}
    titles = list(dict.fromkeys(
        _squash(title) for title in (source.get("title"),
                                     source.get("section_title")) if title))
    passage = " ".join(titles).casefold()
    coordinates = value.get("coordinates") or {}
    about = [value.get("label") or value.get("parameter")]
    about += [_coordinate(coordinates[axis], passage) for axis in coordinates
              if axis not in LEFT_OUT]
    number = value.get("value_raw") or value.get("value_label")
    number = number if number not in (None, "") else value.get("value")
    amount = " ".join(_squash(part) for part in (number, value.get("unit"))
                      if part not in (None, ""))
    said = ", ".join(str(part) for part in about if part)
    return " ".join([f"{name}: {said}: {amount}."] + titles)


def lines_of(store, names: dict) -> list:
    """The line of every value of *store*, in its order. *names* says what a
    document is called; one it does not know goes by its harvest name."""
    return [entry_text(value, names.get(value["document"]) or value["document"])
            for value in store]


def document_names(catalog, conn) -> dict:
    """{harvest name of a document: what it is called}, for every document of
    the corpus, superseded ones too."""
    return {Path(entry.row["filename"]).stem: catalog.name(entry.row,
                                                           entry.facets)
            for entry in catalog.entries(conn, include_superseded=True)}


def _key(line: str) -> str:
    return hashlib.sha256(line.encode("utf-8", "surrogatepass")).hexdigest()


def _maker() -> str:
    """What made a vector: vectors of two models say nothing about each
    other, and a query is embedded with the configured one."""
    return (f"{embedding_config.EMBEDDING_MODEL}"
            f"/{embedding_config.EMBEDDING_DIM}")


def _maker_of(index: sqlite3.Connection) -> Optional[str]:
    row = index.execute('SELECT "value" FROM "meta" WHERE "key" = '
                        "'maker'").fetchone()
    return row[0] if row else None


def _open_building(fresh: Path) -> sqlite3.Connection:
    """The file a build writes: what an earlier build of the same model left
    there, or a new one."""
    if fresh.exists():
        left = sqlite3.connect(fresh)
        try:
            usable = _maker_of(left) == _maker()
        except sqlite3.DatabaseError:
            usable = False
        if usable:
            return left
        left.close()
        fresh.unlink()
    index = sqlite3.connect(fresh)
    index.execute('CREATE TABLE "vectors" ("key" TEXT PRIMARY KEY, '
                  '"vector" BLOB NOT NULL)')
    index.execute('CREATE TABLE "meta" ("key" TEXT PRIMARY KEY, "value" TEXT)')
    index.execute('INSERT INTO "meta" VALUES (?, ?)', ("maker", _maker()))
    index.commit()
    return index


def _take_over(index: sqlite3.Connection, out: Path, wanted: dict) -> None:
    """The vectors the finished index already holds for *wanted*, copied
    into the file being built."""
    if not out.is_file():
        return
    finished = sqlite3.connect(readonly_uri(out), uri=True)
    try:
        if _maker_of(finished) == _maker():
            for key, vector in finished.execute('SELECT "key", "vector" '
                                                'FROM "vectors"'):
                if key in wanted:
                    index.execute('INSERT OR IGNORE INTO "vectors" '
                                  'VALUES (?, ?)', (key, vector))
    except sqlite3.DatabaseError as exc:
        log.warning("values index: %s could not be read (%s); its vectors "
                    "are made again", out, exc)
    finally:
        finished.close()
    index.commit()


def build(harvest_dir, lines: Iterable[str], *, embedder=None,
          out: Optional[Path] = None, batch: Optional[int] = None) -> dict:
    """Bring the index of a harvest up to *lines*.

    Only a line without a vector is embedded, shortest first, so a batch pads
    to about its own length. Each batch is committed: a build that stops
    keeps what it finished in `<index>.building`, and the next one goes on
    from there. The index itself is replaced whole, at the end. Returns
    {lines, reused, embedded, seconds}, which the index keeps too.
    """
    out = Path(out) if out is not None else path_for(harvest_dir)
    batch = batch or embedding_config.EMBEDDING_BATCH_SIZE
    wanted = {_key(line): line for line in lines}
    fresh = out.with_name(out.name + BUILDING)
    started = time.monotonic()
    index = _open_building(fresh)
    try:
        _take_over(index, out, wanted)
        held = {row[0] for row in index.execute('SELECT "key" FROM "vectors"')}
        index.executemany('DELETE FROM "vectors" WHERE "key" = ?',
                          [(key,) for key in held - set(wanted)])
        index.commit()
        todo = sorted((line for key, line in wanted.items()
                       if key not in held), key=len)
        reused = len(wanted) - len(todo)
        log.info("values index: %d line(s), %d with a vector, %d to embed",
                 len(wanted), reused, len(todo))
        if todo and embedder is None:
            from ..embedding import get_embedder
            embedder = get_embedder()
        said = time.monotonic()
        for start in range(0, len(todo), batch):
            part = todo[start:start + batch]
            vectors = embedder.embed([{"text": line} for line in part])
            index.executemany(
                'INSERT OR REPLACE INTO "vectors" VALUES (?, ?)',
                [(_key(line), np.asarray(vector, dtype=_FLOAT).tobytes())
                 for line, vector in zip(part, vectors)])
            index.commit()
            if time.monotonic() - said >= _REPORT_SECONDS:
                said = time.monotonic()
                done = start + len(part)
                log.info("values index: %d of %d embedded, %.1f lines/s",
                         done, len(todo), done / (said - started))
        seconds = time.monotonic() - started
        made = {"lines": len(wanted), "reused": reused,
                "embedded": len(todo), "seconds": round(seconds, 1)}
        index.executemany('INSERT OR REPLACE INTO "meta" VALUES (?, ?)',
                          [(key, str(value)) for key, value in made.items()])
        index.commit()
    finally:
        index.close()
    # Whole or not at all: a chat that opens the index mid-build would miss
    # values, and nothing would tell it.
    try:
        fresh.replace(out)
    except OSError as exc:
        raise RuntimeError(
            f"{out} could not be replaced ({exc}). A program that has it open "
            f"holds it, most likely the chat: stop it and run this again. "
            f"{fresh} holds the finished index.") from exc
    log.info("values index: %s holds %s", out, made)
    return made


def state(lines: Iterable[str], index_path: Path) -> str:
    """`current`, `stale` or `missing`."""
    index_path = Path(index_path)
    if not index_path.is_file():
        return "missing"
    index = sqlite3.connect(readonly_uri(index_path), uri=True)
    try:
        if _maker_of(index) != _maker():
            return "stale"
        held = {row[0] for row in index.execute('SELECT "key" FROM "vectors"')}
    except sqlite3.DatabaseError:
        return "stale"
    finally:
        index.close()
    return "current" if {_key(line) for line in lines} <= held else "stale"


@dataclass
class Index:
    """The vectors of one harvest in memory, one row per different line."""
    values: list            # the store's values
    lines: list             # the line of each, in the same order
    matrix: np.ndarray      # (different lines, dimensions)
    rows: np.ndarray        # the row of each value
    of_document: dict = field(default_factory=dict)

    def __post_init__(self):
        for at, value in enumerate(self.values):
            self.of_document.setdefault(value["document"], []).append(at)

    def search(self, vector, *, document: Optional[str] = None,
               levels: Optional[Sequence[str]] = None) -> list:
        """[(value, line)] of the values of *document* (None: of all) in
        *levels* (None: every one), nearest to *vector* first. Values that
        read alike are one line, and stand here once."""
        places = (range(len(self.values)) if document is None
                  else self.of_document.get(document, ()))
        if levels is not None:
            places = [at for at in places
                      if self.values[at]["level"] in levels]
        places = np.fromiter(places, dtype="int64")
        if not len(places):
            return []
        rows = self.rows[places]
        query = np.asarray(vector, dtype=_FLOAT).reshape(-1)
        scores = (self.matrix @ query)[rows]
        found, seen = [], set()
        for at in np.argsort(-scores, kind="stable").tolist():
            row = int(rows[at])
            if row not in seen:
                seen.add(row)
                found.append((self.values[places[at]],
                              self.lines[places[at]]))
        return found


def load(harvest_dir, store, names: dict,
         index_path: Optional[Path] = None) -> Optional[Index]:
    """The index of a harvest in memory, or None when it is missing or stale.
    None is said in the log, once, with what to do."""
    index_path = Path(index_path) if index_path else path_for(harvest_dir)
    lines = lines_of(store, names)
    found = state(lines, index_path)
    if found != "current":
        log.warning("values index: %s is %s; the chat asks closed questions "
                    "for the harvest. `docpipe values-index %s` builds it.",
                    index_path, found, harvest_dir)
        return None
    keys = [_key(line) for line in lines]
    position = {key: at for at, key in enumerate(dict.fromkeys(keys))}
    matrix = np.empty((len(position), embedding_config.EMBEDDING_DIM),
                      dtype=_FLOAT)
    index = sqlite3.connect(readonly_uri(index_path), uri=True)
    try:
        for key, vector in index.execute('SELECT "key", "vector" '
                                         'FROM "vectors"'):
            at = position.get(key)
            if at is not None:
                matrix[at] = np.frombuffer(vector, dtype=_FLOAT)
    finally:
        index.close()
    log.info("values index: %s, %d value(s) on %d line(s)", index_path,
             len(keys), len(position))
    return Index(values=list(store), lines=lines, matrix=matrix,
                 rows=np.fromiter((position[key] for key in keys),
                                  dtype="int64", count=len(keys)))


def main(argv: Optional[Sequence[str]] = None) -> int:
    from ..extraction import gold, trust
    from ..extraction.spec import load as load_spec
    from ..profile import add_profile_argument, program, resolve_profile
    from ..serve.values import Values
    from . import catalog, db as corpus_db
    parser = argparse.ArgumentParser(
        prog=program("docpipe.inference.values_index"),
        description="Build the vectors the chat finds harvested values by.")
    add_profile_argument(parser)
    parser.add_argument("harvest", type=Path, help="harvest directory")
    parser.add_argument("--db", type=Path,
                        help="corpus database (default: the profile's)")
    parser.add_argument("--check", action="store_true",
                        help="only say whether the index is current")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(name)s "
                               "%(message)s", datefmt="%H:%M:%S")
    profile = resolve_profile(args)
    database = args.db or (profile.db_path if profile is not None else None)
    if database is None or not Path(database).is_file():
        raise SystemExit(f"{database} is not a file: name the corpus database "
                         f"with --db, or a --profile that has one")
    if not args.harvest.is_dir():
        raise SystemExit(f"{args.harvest} is not a directory")
    path = profile.component("extraction", "SPEC_PATH") if profile else None
    store = Values(gold.harvest(args.harvest),
                   spec=load_spec(path) if path is not None else None,
                   transcribed=trust.transcribed_documents(database))
    conn = corpus_db.connect_readonly(database)
    try:
        names = document_names(catalog.load_catalog(profile), conn)
    finally:
        conn.close()
    lines = lines_of(store, names)
    if args.check:
        found = state(lines, path_for(args.harvest))
        print(f"{path_for(args.harvest)}: {found}")
        return 0 if found == "current" else 1
    try:
        made = build(args.harvest, lines)
    except RuntimeError as exc:
        raise SystemExit(str(exc))
    print(f"{path_for(args.harvest)}: {made['lines']} line(s), "
          f"{made['embedded']} embedded, {made['reused']} reused, "
          f"{made['seconds']} s")
    return 0


if __name__ == "__main__":
    from docpipe.profile import bind_command_line
    bind_command_line()
    sys.exit(main())
