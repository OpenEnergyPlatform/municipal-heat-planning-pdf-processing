"""Length-sorted batches, and preparation that overlaps with the GPUs."""
import numpy as np
import pytest

from docpipe.chunking import embedding as emb
from docpipe.chunking.chunking import EmbeddingInput


class _FakeIndex:
    def __init__(self):
        self.ids = []

    @property
    def ntotal(self):
        return len(self.ids)

    def add_with_ids(self, vectors, ids):
        self.ids.extend(int(i) for i in ids)


class _RecordingEmbedder:
    """Records the batches it is handed, and their length spread."""

    def __init__(self):
        self.batches = []

    def process(self, model_inputs):
        self.batches.append([len(m["text"]) for m in model_inputs])
        import torch
        return torch.zeros(len(model_inputs), 4)


def _inp(n_chars, i, kind="section_text"):
    return EmbeddingInput(embedding_type=kind, pdf_name="doc", section_index=i,
                          item_id=None, text="x" * n_chars)


@pytest.fixture
def written(monkeypatch):
    """Intercepts the DB writeback; collects (pdf_name, records) per write."""
    calls = []

    class _FakeWriter:
        def __init__(self, db_path):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def write(self, pdf_name, records):
            calls.append((pdf_name, records))

    monkeypatch.setattr(emb, "EmbeddingWriter", _FakeWriter)
    return calls


def test_a_batch_no_longer_mixes_titles_with_full_sections(written, tmp_path):
    """Padding is per batch: unsorted, five-character titles ride along with a
    9000-character section and cost the same."""
    inputs = []
    for i in range(64):
        inputs.append(_inp(5 if i % 2 else 9000, i))

    embedder = _RecordingEmbedder()
    emb.create_embeddings(inputs, _FakeIndex(), 0, tmp_path / "db",
                          embedder=embedder, batch_size=32)

    spreads = [max(b) - min(b) for b in embedder.batches]
    assert max(spreads) == 0, "each batch should hold one length class"


def test_every_input_is_embedded_exactly_once(written, tmp_path):
    inputs = [_inp(10 * i + 1, i) for i in range(100)]
    embedder = _RecordingEmbedder()

    emb.create_embeddings(inputs, _FakeIndex(), 0, tmp_path / "db",
                          embedder=embedder, batch_size=32)

    seen = sorted(n for batch in embedder.batches for n in batch)
    assert seen == sorted(len(i.text) for i in inputs)


def test_ids_stay_unique_and_contiguous(written, tmp_path):
    index = _FakeIndex()
    inputs = [_inp(100, i) for i in range(50)]

    end = emb.create_embeddings(inputs, index, 1000, tmp_path / "db",
                                embedder=_RecordingEmbedder(), batch_size=16)

    assert index.ids == list(range(1000, 1050))
    assert end == 1050


def test_text_and_image_inputs_stay_in_separate_batches(written, tmp_path):
    inputs = [_inp(100, 0), _inp(100, 1)]
    inputs.append(EmbeddingInput(embedding_type="table_vl", pdf_name="doc",
                                 section_index=2, item_id="p1_tbl0",
                                 text="caption", image="/tmp/x.png"))
    embedder = _RecordingEmbedder()

    emb.create_embeddings(inputs, _FakeIndex(), 0, tmp_path / "db",
                          embedder=embedder, batch_size=32)

    assert [len(b) for b in embedder.batches] == [2, 1]


def _merged(n_sections):
    """A merged document of n plain sections, each with one table."""
    return {"sections": [
        {"title": "S%d" % i, "content": "c", "page_number": 1, "pages": [1],
         "segments": [],
         "tables": [{"id": "s%d_tbl0" % i, "path": "", "page_number": 1}],
         "figures": []}
        for i in range(n_sections)]}


def test_the_db_writeback_opens_one_connection_for_the_whole_call(
        kwp_db, tmp_path, monkeypatch):
    """Batches are packed by text length across documents, so a 32-item batch
    routinely straddles many: a connection per (batch, document) pair was close
    to one connect, two PRAGMAs and a document lookup per embedding."""
    from docpipe.chunking import database as DB

    db_path, con = kwp_db
    con.execute("INSERT INTO Documents (id, filename, num_pages) VALUES (2, 'other.pdf', 9)")
    DB._insert_sections(1, _merged(32), con)
    DB._insert_sections(2, _merged(32), con)
    con.commit()

    inputs = []
    for section in range(32):                 # interleaved: every batch straddles
        for name in ("doc", "other"):
            inputs.append(EmbeddingInput(
                embedding_type="table_text", pdf_name=name, section_index=section,
                item_id="s%d_tbl0" % section, text="x" * 100))

    opened = []
    real_connect = DB.connect
    monkeypatch.setattr(DB, "connect",
                        lambda p: (opened.append(str(p)), real_connect(p))[1])

    emb.create_embeddings(inputs, _FakeIndex(), 0, db_path,
                          embedder=_RecordingEmbedder(), batch_size=32)

    assert len(opened) == 1, f"{len(opened)} connections for one call"
    # and every record still found its owner, in the right document
    rows = con.execute(
        "SELECT s.document, COUNT(*) FROM Embeddings e "
        "JOIN Tables t ON e.owner_id = t.id JOIN Sections s ON t.section = s.id "
        "WHERE e.owner_kind = 'table' GROUP BY s.document").fetchall()
    assert rows == [(1, 32), (2, 32)]


# ---------------------------------------------------------------------------
# The pipeline's embed step: preparation must overlap the embedding
# ---------------------------------------------------------------------------

def _corpus(tmp_path, n_docs, items_per_doc):
    import json
    root = tmp_path / "processed"
    for d in range(n_docs):
        doc = root / ("doc%02d" % d)
        (doc / "results").mkdir(parents=True)
        (doc / "results/document.json").write_text(
            json.dumps({"sections": [{"title": "T", "content": "x"}]}),
            encoding="utf-8")
    return root


def test_the_gpus_start_before_the_last_document_is_read(tmp_path, monkeypatch):
    """The whole point: 91 of 184 minutes of the last run were spent preparing
    all 800 documents while every GPU sat idle."""
    from docpipe.chunking import pipeline as pl

    root = _corpus(tmp_path, 12, 1)
    timeline = []

    def fake_prepare_inputs(merged, pdf_name, pdf_dir):
        timeline.append(("prepare", pdf_name))
        return [_inp(100, i) for i in range(500)]

    def fake_create(inputs, index, next_id, db_path, **kw):
        timeline.append(("embed", len(inputs)))
        return next_id + len(inputs)

    monkeypatch.setattr(pl, "build_embedding_inputs", fake_prepare_inputs)
    monkeypatch.setattr(pl, "create_embeddings", fake_create)
    monkeypatch.setattr(pl, "document_id", lambda db, name: 1)
    monkeypatch.setattr(pl, "get_existing_embeddings",
                        lambda db, name, doc_id=None: set())
    monkeypatch.setattr(pl, "load_or_create_index", lambda p: (_FakeIndex(), 0))
    monkeypatch.setattr(pl, "next_faiss_id", lambda p: 0)
    monkeypatch.setattr(pl, "load_embedder", lambda name: None)
    monkeypatch.setattr(pl, "save_index", lambda index, path: None)

    pl.run(root, tmp_path / "db.sqlite", tmp_path / "idx", step="embed")

    kinds = [k for k, _ in timeline]
    assert "embed" in kinds, "nothing was embedded"
    first_embed = kinds.index("embed")
    assert first_embed < len(kinds) - 1, \
        "embedding only started after every document was prepared"
    assert kinds.count("embed") > 1, "the corpus went out in one late lump"


def test_every_document_is_embedded_exactly_once_across_the_chunks(tmp_path, monkeypatch):
    from docpipe.chunking import pipeline as pl

    root = _corpus(tmp_path, 10, 1)
    seen = []

    monkeypatch.setattr(pl, "build_embedding_inputs",
                        lambda merged, name, d: [_inp(50, 0)] * 700)
    monkeypatch.setattr(pl, "create_embeddings",
                        lambda inputs, index, next_id, db, **kw: (
                            seen.append(len(inputs)) or next_id + len(inputs)))
    monkeypatch.setattr(pl, "document_id", lambda db, name: 1)
    monkeypatch.setattr(pl, "get_existing_embeddings",
                        lambda db, name, doc_id=None: set())
    monkeypatch.setattr(pl, "load_or_create_index", lambda p: (_FakeIndex(), 0))
    monkeypatch.setattr(pl, "next_faiss_id", lambda p: 0)
    monkeypatch.setattr(pl, "load_embedder", lambda name: None)
    monkeypatch.setattr(pl, "save_index", lambda index, path: None)

    pl.run(root, tmp_path / "db.sqlite", tmp_path / "idx", step="embed")

    assert sum(seen) == 10 * 700


def test_the_index_is_not_written_once_per_flush(written, tmp_path, monkeypatch):
    """A million 4096-dim vectors is a ~16 GB file, rewritten whole. Saving it
    at the end of every embed call was ~244 rewrites over a build, each one with
    the GPUs idle. Counted wherever the save lives — this runs the real
    create_embeddings, which used to do it itself."""
    from docpipe.chunking import pipeline as pl

    root = _corpus(tmp_path, 40, 1)
    index = _FakeIndex()
    saves = []

    def record(idx, path):
        saves.append(idx.ntotal)

    monkeypatch.setattr(pl, "build_embedding_inputs",
                        lambda merged, name, d: [_inp(50, 0)] * 1000)
    monkeypatch.setattr(pl, "document_id", lambda db, name: 1)
    monkeypatch.setattr(pl, "get_existing_embeddings",
                        lambda db, name, doc_id=None: set())
    monkeypatch.setattr(pl, "load_or_create_index", lambda p: (index, 0))
    monkeypatch.setattr(pl, "next_faiss_id", lambda p: 0)
    monkeypatch.setattr(pl, "load_embedder", lambda name: _RecordingEmbedder())
    monkeypatch.setattr(pl, "save_index", record)
    monkeypatch.setattr(emb, "save_index", record)
    monkeypatch.setattr(pl, "EMBED_SAVE_VECTORS", 20_000)

    pl.run(root, tmp_path / "db.sqlite", tmp_path / "idx", step="embed")

    # 40 docs x 1000 items = 40k vectors, flushed in chunks of 5000: eight embed
    # calls, insurance every 20k vectors, plus the save that ends the run.
    assert index.ntotal == 40_000
    assert 0 < len(saves) <= 4, f"{len(saves)} index writes for 8 flushes"
    assert saves[-1] == 40_000, "the finished index was not saved"


def test_a_crash_mid_run_never_loses_more_than_the_insurance_interval(
        tmp_path, monkeypatch):
    """The save is rarer, not gone: it fires on vectors added since the last
    save, so a killed run re-embeds a bounded amount whatever the flush size."""
    from docpipe.chunking import pipeline as pl

    root = _corpus(tmp_path, 12, 1)
    index = _FakeIndex()
    saves = []

    def fake_create(inputs, idx, next_id, db_path, **kw):
        idx.ids.extend(range(next_id, next_id + len(inputs)))
        return next_id + len(inputs)

    monkeypatch.setattr(pl, "build_embedding_inputs",
                        lambda merged, name, d: [_inp(50, 0)] * 5000)
    monkeypatch.setattr(pl, "create_embeddings", fake_create)
    monkeypatch.setattr(pl, "document_id", lambda db, name: 1)
    monkeypatch.setattr(pl, "get_existing_embeddings",
                        lambda db, name, doc_id=None: set())
    monkeypatch.setattr(pl, "load_or_create_index", lambda p: (index, 0))
    monkeypatch.setattr(pl, "next_faiss_id", lambda p: 0)
    monkeypatch.setattr(pl, "load_embedder", lambda name: None)
    monkeypatch.setattr(pl, "save_index", lambda i, path: saves.append(i.ntotal))
    monkeypatch.setattr(pl, "EMBED_SAVE_VECTORS", 10_000)

    pl.run(root, tmp_path / "db.sqlite", tmp_path / "idx", step="embed")

    gaps = [b - a for a, b in zip([0] + saves, saves)]
    assert max(gaps) <= 10_000 + 4096, f"up to {max(gaps)} vectors unsaved"


class _RecordingPool:
    """A pool that runs the work at once and counts what was submitted."""

    def __init__(self):
        self.submitted = 0

    def submit(self, fn, item):
        self.submitted += 1
        value = fn(item)

        class _Done:
            def result(self_inner):
                return value
        return _Done()


def test_preparation_never_runs_the_whole_corpus_ahead_of_the_gpus():
    """The OOM that killed the 1078-plan run at 194 GB. Executor.map submits
    EVERY item immediately and makes only the consumption lazy (verified on the
    cluster's 3.11: after taking the first result, all 500 tasks had already
    run). Preparation is far faster than embedding, so the finished inputs of
    the whole corpus stay resident - about a million section texts. What is
    held has to depend on the window, not on how many plans there are."""
    from docpipe.chunking.pipeline import prepared_ahead

    pool = _RecordingPool()
    consumed = []
    stream = prepared_ahead(pool, range(1000), lambda i: i, ahead=32)
    for _ in range(5):                      # the GPUs are still on the first chunks
        consumed.append(next(stream))
    assert consumed == [0, 1, 2, 3, 4], "documents must arrive in order"
    assert pool.submitted <= 32 + 5, (
        f"{pool.submitted} of 1000 documents prepared while 5 were consumed")


def test_the_window_still_yields_every_item_exactly_once():
    from docpipe.chunking.pipeline import prepared_ahead
    pool = _RecordingPool()
    assert list(prepared_ahead(pool, range(70), lambda i: i * 2, ahead=8)) ==         [i * 2 for i in range(70)]
    assert pool.submitted == 70


# ---------------------------------------------------------------------------
# crash reconciliation: a DB row whose vector never reached the index file
# ---------------------------------------------------------------------------

def _seed_embedding_rows(con, faiss_ids):
    """One Section per faiss id on Document 1, each with its own Embeddings row
    (the UNIQUE(owner_kind, owner_id, embedding_type) forbids sharing one)."""
    for n, fid in enumerate(faiss_ids):
        con.execute("INSERT INTO Sections (id, document, section_number, title) "
                    "VALUES (?, 1, ?, 'S')", (n + 1, n))
        con.execute("INSERT INTO Embeddings (faiss_id, embedding_type, "
                    "owner_kind, owner_id) VALUES (?, 'section_text', "
                    "'section', ?)", (fid, n + 1))
    con.commit()


def test_rows_without_a_vector_in_the_index_are_dropped(kwp_db):
    """The OOM/timeout failure mode: a batch's rows were written, the chunk's
    index save never ran. Those rows must not survive to be read as
    'already embedded'."""
    from docpipe.chunking.database import drop_embeddings_missing_from_index
    db_path, con = kwp_db
    _seed_embedding_rows(con, [10, 11, 12, 13])
    # The index only made it to disk with 10 and 11.
    dropped = drop_embeddings_missing_from_index(db_path, [10, 11])
    assert dropped == 2
    survivors = {r[0] for r in con.execute("SELECT faiss_id FROM Embeddings")}
    assert survivors == {10, 11}


def test_an_empty_index_never_wipes_the_table(kwp_db):
    """An empty id list is a mistyped index path, not 'nothing is embedded'.
    Deleting every row on that basis would be the worse failure."""
    from docpipe.chunking.database import drop_embeddings_missing_from_index
    db_path, con = kwp_db
    _seed_embedding_rows(con, [10, 11])
    assert drop_embeddings_missing_from_index(db_path, []) == 0
    assert con.execute("SELECT COUNT(*) FROM Embeddings").fetchone()[0] == 2


def test_a_clean_run_drops_nothing(kwp_db):
    from docpipe.chunking.database import drop_embeddings_missing_from_index
    db_path, con = kwp_db
    _seed_embedding_rows(con, [10, 11, 12])
    assert drop_embeddings_missing_from_index(db_path, [10, 11, 12, 13]) == 0
    assert con.execute("SELECT COUNT(*) FROM Embeddings").fetchone()[0] == 3


# ---------------------------------------------------------------------------
# a document the database does not know must never reach the GPUs
# ---------------------------------------------------------------------------

def test_a_directory_without_a_documents_row_is_skipped_not_embedded(
        tmp_path, monkeypatch):
    """Measured on the live corpus: two processed directories had no Documents
    row. Every run embedded them, the vectors entered the FAISS index, and the
    DB write returned silently because no owner could be resolved - 1096 dead
    vectors per run, growing, with nothing in the log."""
    from docpipe.chunking import pipeline as pl

    root = _corpus(tmp_path, 3, 1)
    known = {"doc00", "doc02"}
    embedded = []

    monkeypatch.setattr(pl, "document_id",
                        lambda db, name: 1 if name in known else None)
    monkeypatch.setattr(
        pl, "build_embedding_inputs",
        lambda merged, name, d: [EmbeddingInput(
            embedding_type="section_text", pdf_name=name, section_index=0,
            item_id=None, text="x" * 50)])
    monkeypatch.setattr(pl, "create_embeddings",
                        lambda inputs, index, next_id, db, **kw: (
                            embedded.extend(i.pdf_name for i in inputs)
                            or next_id + len(inputs)))
    monkeypatch.setattr(pl, "get_existing_embeddings",
                        lambda db, name, doc_id=None: set())
    monkeypatch.setattr(pl, "load_or_create_index", lambda p: (_FakeIndex(), 0))
    monkeypatch.setattr(pl, "next_faiss_id", lambda p: 0)
    monkeypatch.setattr(pl, "load_embedder", lambda name: None)
    monkeypatch.setattr(pl, "save_index", lambda index, path: None)

    pl.run(root, tmp_path / "db.sqlite", tmp_path / "idx", step="embed")

    assert "doc01" not in embedded, "the unregistered document reached the GPUs"
    assert set(embedded) == known, "the registered ones were embedded"


def test_the_writer_shouts_instead_of_returning_in_silence(kwp_db, caplog):
    """The backstop. If it is ever reached, the vectors are already in the
    index, so silence is the one unacceptable answer."""
    import logging
    from docpipe.chunking.database import write_embedding_ids_batch
    db_path, _con = kwp_db
    with caplog.at_level(logging.ERROR):
        write_embedding_ids_batch(db_path, "a_document_nobody_registered",
                                  [("section_text", 0, None, 4711)])
    assert any("no Documents row" in r.getMessage() for r in caplog.records)
