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
    calls = []
    monkeypatch.setattr(emb, "write_embedding_ids_batch",
                        lambda db, doc, records: calls.append((doc, records)))
    monkeypatch.setattr(emb, "save_index", lambda index, path: None)
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
    monkeypatch.setattr(pl, "get_existing_embeddings", lambda db, name: set())
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
    monkeypatch.setattr(pl, "get_existing_embeddings", lambda db, name: set())
    monkeypatch.setattr(pl, "load_or_create_index", lambda p: (_FakeIndex(), 0))
    monkeypatch.setattr(pl, "next_faiss_id", lambda p: 0)
    monkeypatch.setattr(pl, "load_embedder", lambda name: None)
    monkeypatch.setattr(pl, "save_index", lambda index, path: None)

    pl.run(root, tmp_path / "db.sqlite", tmp_path / "idx", step="embed")

    assert sum(seen) == 10 * 700
