"""
pages.py: A page index over the corpus, beside the vector index.

The passages of the corpus are searched by their transcription. Where the
transcription of a map or a chart does not hold the detail, the page itself
does. The page index embeds the image of each page of each document with the
corpus's multimodal embedder, so that a search sentence, embedded as the
harvest embeds it, can be compared with a page in the same space (owner
decision 2026-11-17, from the literature on searching the page image
directly: ColPali 2024, Nemotron ColEmbed V2 2026). A found page backs no
value: the passages that stand on it join the candidates of the search, and
the reading still needs a line that holds the value (the two checks stay).

The index is two files beside the corpus database, built from it and never
written into it (as the word index, `lexical.py`):

    <name>.pages.faiss   one vector per page
    <name>.pages.db      which document and page each vector is, and the
                         fingerprint

    docpipe pages DB          build it, or build it again
    docpipe pages DB --check  say whether it is there and current

The fingerprint is a digest over the model, the render size and the
documents the corpus database names (file, bytes, pages). An index of
another model, of another render size or of other documents is stale, and a
stale index is not asked: a page of a document that has since changed, or a
vector of another model, would be worse than none. An embedder that takes
text only cannot embed a page: the index says so and is not built.

Author: Felix Vossel
"""
from __future__ import annotations

import argparse
import hashlib
import logging
import sqlite3
import sys
import tempfile
import threading
from pathlib import Path
from typing import Callable, Optional, Sequence

import numpy as np

from ..store import schema as store_schema
from ..store.schema import readonly_uri

log = logging.getLogger(__name__)

FAISS_SUFFIX = ".pages.faiss"
DB_SUFFIX = ".pages.db"
# The render size of the layout model's input: a page of an embedder's
# input is a picture the processor scales down anyway, and 300 dpi (the
# crops' size) is four times the pixels for nothing.
DEFAULT_DPI = 150
BATCH = 8


def faiss_path_for(db_path) -> Path:
    db_path = Path(db_path)
    return db_path.with_name(db_path.stem + FAISS_SUFFIX)


def path_for(db_path) -> Path:
    """The small database of the page index (document, page, vector id)."""
    db_path = Path(db_path)
    return db_path.with_name(db_path.stem + DB_SUFFIX)


def _model() -> str:
    from ..embedding import config
    return config.EMBEDDING_MODEL


def _fingerprint(corpus: sqlite3.Connection, model: str, dpi: int) -> str:
    """A digest over the model, the render size and the documents and pages
    the corpus database names. A count would not see a document whose PDF
    was replaced."""
    digest = hashlib.sha256()
    digest.update(repr((str(model), int(dpi))).encode("utf-8"))
    for row in corpus.execute(
            'SELECT "id", "filename", "sha256", "bytes", "num_pages" '
            'FROM "Documents" ORDER BY 1'):
        digest.update(repr(tuple(row)).encode("utf-8", "surrogatepass"))
    for row in corpus.execute(
            'SELECT "document", "page_number" FROM "Pages" ORDER BY 1, 2'):
        digest.update(repr(tuple(row)).encode("utf-8"))
    return digest.hexdigest()


def render_page(pdf: Path, page_number: int, dpi: int):
    """The image of page *page_number* (from 1) of *pdf*, as the
    preprocessing renders a page (`rendering.render_page_to_pil`)."""
    import fitz
    from ..preprocessing import rendering
    with rendering.FITZ_LOCK:
        with fitz.open(str(pdf)) as doc:
            return rendering.render_page_to_pil(doc[page_number - 1], dpi)


def _unit_rows(vectors) -> np.ndarray:
    """A batch of vectors as unit rows of float32, whichever backend made it
    (the index compares by inner product)."""
    if hasattr(vectors, "detach"):
        import torch
        vectors = vectors.detach().to(torch.float32).cpu().numpy()
    array = np.asarray(vectors, dtype=np.float32)
    if array.ndim == 1:
        array = array[None, :]
    lengths = np.linalg.norm(array, axis=1, keepdims=True)
    return array / np.where(lengths == 0, 1.0, lengths)


def build(db_path, *, pdf_root, dpi: int = DEFAULT_DPI, embedder=None,
          render: Optional[Callable] = None, model: Optional[str] = None,
          out: Optional[Path] = None,
          faiss_out: Optional[Path] = None) -> dict:
    """Build the page index of a corpus database. Returns what it holds:
    `documents`, `pages`, `skipped` (documents with no PDF, by file name)
    and `failed` (pages the embedder could not serve)."""
    import faiss
    db_path = Path(db_path)
    out = Path(out) if out is not None else path_for(db_path)
    faiss_out = Path(faiss_out) if faiss_out is not None \
        else faiss_path_for(db_path)
    render = render or render_page
    if embedder is None:
        from ..chunking.embedding import load_embedder
        embedder = load_embedder(model or _model())
    model = str(model or getattr(embedder, "model", None) or _model())
    if getattr(embedder, "text_only", False):
        raise RuntimeError(
            f"the corpus's text vectors come from {model} through a backend "
            f"that takes text only: it cannot embed a page image, so the "
            f"page index is not built (a vLLM server in the messages form, "
            f"EMBEDDING_API_FORMAT, or the local model takes pictures)")
    corpus = sqlite3.connect(readonly_uri(db_path), uri=True)
    corpus.row_factory = sqlite3.Row
    try:
        said = store_schema.embedding_mismatch(corpus, model)
        if said:
            raise RuntimeError(f"{said}: a page vector would not share a "
                               f"space with the text vectors, so the page "
                               f"index is not built")
        fingerprint = _fingerprint(corpus, model, dpi)
        documents = [(int(r["id"]), r["filename"]) for r in corpus.execute(
            'SELECT "id", "filename" FROM "Documents" ORDER BY 1')]
        wanted = {}
        for row in corpus.execute(
                'SELECT "document", "page_number" FROM "Pages" '
                'ORDER BY 1, 2'):
            wanted.setdefault(int(row[0]), []).append(int(row[1]))
    finally:
        corpus.close()
    fresh_db = out.with_name(out.name + ".building")
    fresh_faiss = faiss_out.with_name(faiss_out.name + ".building")
    for part in (fresh_db, fresh_faiss):
        part.unlink() if part.exists() else None
    index = None
    held = {"documents": 0, "pages": 0, "skipped": [], "failed": 0}
    store = sqlite3.connect(fresh_db)
    done = False
    try:
        store.execute('CREATE TABLE "pages" ("vector" INTEGER PRIMARY KEY, '
                      '"document" INTEGER NOT NULL, "page" INTEGER NOT NULL)')
        store.execute('CREATE INDEX "idx_pages_document" ON "pages"'
                      '("document")')
        store.execute('CREATE TABLE "meta" ("key" TEXT PRIMARY KEY, '
                      '"value" TEXT)')
        next_id = 0
        with tempfile.TemporaryDirectory(prefix="pages_") as scratch:
            for document, filename in documents:
                pdf = Path(pdf_root) / (filename or "")
                numbers = wanted.get(document, [])
                if not numbers:
                    continue
                if not filename or not pdf.is_file():
                    held["skipped"].append(filename)
                    log.warning("pages: document %s (%s) has no PDF under "
                                "%s: its pages are not in the index",
                                document, filename, pdf_root)
                    continue
                kept = 0
                for start in range(0, len(numbers), BATCH):
                    batch = numbers[start:start + BATCH]
                    items, taken = [], []
                    for number in batch:
                        try:
                            picture = render(pdf, number, dpi)
                            target = Path(scratch) / f"{document}_{number}.png"
                            picture.save(target)
                        except Exception as exc:
                            held["failed"] += 1
                            log.warning("pages: %s page %s not rendered: %s",
                                        filename, number, exc)
                            continue
                        items.append({"text": "", "image": str(target)})
                        taken.append(number)
                    if not items:
                        continue
                    try:
                        vectors = _unit_rows(embedder.process(items))
                    except Exception as exc:
                        held["failed"] += len(items)
                        log.warning("pages: %s pages %s-%s not embedded: %s",
                                    filename, taken[0], taken[-1], exc)
                        continue
                    finally:
                        for item in items:
                            Path(item["image"]).unlink(missing_ok=True)
                    if index is None:
                        index = faiss.IndexFlatIP(int(vectors.shape[1]))
                    index.add(vectors)
                    store.executemany(
                        'INSERT INTO "pages" VALUES (?, ?, ?)',
                        [(next_id + i, document, number)
                         for i, number in enumerate(taken)])
                    next_id += len(taken)
                    kept += len(taken)
                held["pages"] += kept
                held["documents"] += 1 if kept else 0
                log.info("pages: %s: %d of %d page(s)", filename, kept,
                         len(numbers))
        if index is None:
            raise RuntimeError("no page was embedded: the page index is "
                               "not written")
        store.executemany('INSERT INTO "meta" VALUES (?, ?)', [
            ("fingerprint", fingerprint), ("model", model),
            ("dpi", str(int(dpi))), ("dim", str(index.d)),
            ("skipped", str(len(held["skipped"])))])
        store.commit()
        faiss.write_index(index, str(fresh_faiss))
        done = True
    finally:
        store.close()
        if not done:
            for part in (fresh_db, fresh_faiss):
                part.unlink() if part.exists() else None
    # Whole or not at all, and the vectors first: a database without its
    # vectors is no index, a vector file without its database is not read.
    try:
        fresh_faiss.replace(faiss_out)
        fresh_db.replace(out)
    except OSError as exc:
        for part in (fresh_db, fresh_faiss):
            part.unlink() if part.exists() else None
        raise RuntimeError(
            f"{out} could not be replaced ({exc}). A program that has it "
            f"open holds it: stop it and run this again.") from exc
    log.info("pages: %s holds %d page(s) of %d document(s); %d document(s) "
             "without a PDF, %d page(s) not embedded", out, held["pages"],
             held["documents"], len(held["skipped"]), held["failed"])
    return held


def state(db_path, index_path: Optional[Path] = None, *,
          faiss_path: Optional[Path] = None, model: Optional[str] = None,
          dpi: Optional[int] = None) -> str:
    """`current`, `stale` or `missing`. *model* is the model that embeds the
    search sentences now (the configured one); *dpi* the render size asked
    for (the index's own where None)."""
    index_path = Path(index_path) if index_path else path_for(db_path)
    faiss_path = Path(faiss_path) if faiss_path else faiss_path_for(db_path)
    if not index_path.is_file() or not faiss_path.is_file():
        return "missing"
    corpus = sqlite3.connect(readonly_uri(db_path), uri=True)
    index = sqlite3.connect(readonly_uri(index_path), uri=True)
    try:
        held = dict(index.execute('SELECT "key", "value" FROM "meta"'))
        use = int(dpi) if dpi is not None else int(held.get("dpi", 0))
        expected = _fingerprint(corpus, model or _model(), use)
        return "current" if held.get("fingerprint") == expected \
            else "stale"
    except (sqlite3.DatabaseError, ValueError):
        return "stale"
    finally:
        index.close()
        corpus.close()


class PageIndex:
    """The pages of a corpus with a vector each, searched per document."""

    def __init__(self, index, rows: dict):
        # *index* has `reconstruct(i)`; *rows* is {document: [(page, vector)]}.
        self._index = index
        self._rows = rows
        self._matrices: dict = {}
        self._lock = threading.Lock()

    def documents(self) -> list:
        return sorted(self._rows)

    def _matrix(self, document: int):
        with self._lock:
            if document not in self._matrices:
                rows = self._rows.get(document, [])
                self._matrices[document] = (
                    [page for page, _ in rows],
                    np.vstack([np.asarray(self._index.reconstruct(int(v)),
                                          dtype=np.float32)
                               for _, v in rows]) if rows else None)
            return self._matrices[document]

    def search(self, vectors: Sequence, document: int,
               most: int) -> list:
        """The page numbers of *document* that lie closest to any of
        *vectors*, best first, at most *most*: the best score any sentence
        gave a page decides where it stands (as the vector search of the
        passages does)."""
        pages, matrix = self._matrix(int(document))
        if matrix is None or most <= 0 or not len(vectors):
            return []
        queries = _unit_rows(vectors)
        scores = (matrix @ queries.T).max(axis=1)
        order = sorted(range(len(pages)),
                       key=lambda i: (-float(scores[i]), pages[i]))
        return [pages[i] for i in order[:most]]


def connect(db_path, index_path: Optional[Path] = None, *,
            faiss_path: Optional[Path] = None, model: Optional[str] = None,
            dpi: Optional[int] = None) -> Optional[PageIndex]:
    """The page index of a corpus, or None when it is missing or stale. None
    is said in the log, once, with what to do."""
    index_path = Path(index_path) if index_path else path_for(db_path)
    faiss_path = Path(faiss_path) if faiss_path else faiss_path_for(db_path)
    found = state(db_path, index_path, faiss_path=faiss_path, model=model,
                  dpi=dpi)
    if found != "current":
        log.warning("pages: the page index %s is %s; the search does not "
                    "use page images. `docpipe pages %s` builds it.",
                    index_path, found, db_path)
        return None
    import faiss
    index = faiss.read_index(str(faiss_path))
    store = sqlite3.connect(readonly_uri(index_path), uri=True)
    try:
        rows: dict = {}
        for vector, document, page in store.execute(
                'SELECT "vector", "document", "page" FROM "pages" '
                'ORDER BY "document", "page"'):
            rows.setdefault(int(document), []).append((int(page),
                                                       int(vector)))
    finally:
        store.close()
    return PageIndex(index, rows)


def passages_on(corpus: sqlite3.Connection, document: int,
                pages: Sequence[int]) -> list:
    """[(kind, id)] of the passages of *document* that stand on *pages*:
    those of the first page first, on a page the sections, then the tables,
    then the figures. A passage that spans pages (a section over
    `SectionPages`, a table or figure over its `Segments`) stands on each of
    them and is listed once."""
    out: list = []
    seen: set = set()
    for page in pages:
        found = []
        found += [("section", int(r[0])) for r in corpus.execute(
            'SELECT DISTINCT s."id" FROM "Sections" s WHERE s."document" = ? '
            'AND (s."page_number" = ? OR s."id" IN (SELECT sp."section" '
            'FROM "SectionPages" sp JOIN "Pages" p ON p."id" = sp."page" '
            'WHERE p."document" = ? AND p."page_number" = ?)) '
            'ORDER BY s."id"', (document, page, document, page))]
        for kind, table in (("table", "Tables"), ("figure", "Images")):
            segment = "table" if kind == "table" else "figure"
            found += [(kind, int(r[0])) for r in corpus.execute(
                f'SELECT DISTINCT o."id" FROM "{table}" o '
                f'JOIN "Sections" s ON s."id" = o."section" '
                f'WHERE s."document" = ? AND (o."page_number" = ? OR '
                f'EXISTS (SELECT 1 FROM "Segments" g JOIN "Pages" p ON '
                f'p."id" = g."page" WHERE g."section" = o."section" AND '
                f'g."kind" = ? AND g."ref" = o."block_id" AND '
                f'p."page_number" = ?)) ORDER BY o."id"',
                (document, page, segment, page))]
        for key in found:
            if key not in seen:
                seen.add(key)
                out.append(key)
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    from ..profile import add_profile_argument, program, resolve_profile
    parser = argparse.ArgumentParser(
        prog=program("docpipe.inference.pages"),
        description="Build the page index the harvest searches beside the "
                    "vector index: one vector per page image.")
    add_profile_argument(parser)
    parser.add_argument("db", type=Path, nargs="?",
                        help="corpus database (default: the profile's)")
    parser.add_argument("--check", action="store_true",
                        help="only say whether the index is current")
    parser.add_argument("--dpi", type=int, default=None,
                        help=f"render size of a page (default: "
                             f"{DEFAULT_DPI}, the layout model's)")
    parser.add_argument("--pdf-root", type=Path, default=None,
                        help="folder of the PDFs (default: the profile's)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(name)s "
                               "%(message)s", datefmt="%H:%M:%S")
    db = args.db
    profile = None
    if db is None or args.pdf_root is None:
        profile = resolve_profile(args)
    if db is None:
        db = Path(profile.db_path) if profile is not None else None
    if db is None or not Path(db).is_file():
        raise SystemExit(f"{db} is not a file: name the corpus database, or "
                         f"a --profile that has one")
    if args.check:
        found = state(db, dpi=args.dpi)
        print(f"{path_for(db)}: {found}")
        return 0 if found == "current" else 1
    root = args.pdf_root or (profile.pdf_dir if profile is not None
                             else None)
    if root is None:
        raise SystemExit("name the folder of the PDFs with --pdf-root, or a "
                         "--profile that has one")
    try:
        held = build(db, pdf_root=root, dpi=args.dpi or DEFAULT_DPI)
    except RuntimeError as exc:
        raise SystemExit(str(exc))
    print(f"{path_for(db)}: {held['pages']} page(s) of {held['documents']} "
          f"document(s); {len(held['skipped'])} document(s) without a PDF, "
          f"{held['failed']} page(s) not embedded")
    return 0


if __name__ == "__main__":
    from docpipe.profile import bind_command_line
    bind_command_line()
    sys.exit(main())
