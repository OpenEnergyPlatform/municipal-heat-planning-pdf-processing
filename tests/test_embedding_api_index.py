"""Stage 6 through the api backend.

Promised: with EMBEDDING_INDEX_BACKEND=api the index is built from an
embeddings endpoint AND needs no model in this process, while the query
side's EMBEDDING_BACKEND changes nothing here; the vectors are unit vectors;
an input with a picture is left out and gets no database row; a vector of
another size than the index never reaches it; and a hosted endpoint that
says "not now" is asked again.
"""
import sys

import numpy as np
import pytest

from docpipe import providers
from docpipe.chunking import embedding as emb
from docpipe.chunking.chunking import EmbeddingInput
from docpipe.embedding import config as backend
from docpipe.embedding.api import ApiEmbedder


class _Index:
    def __init__(self, d):
        self.d, self.ids, self.vectors = d, [], []

    @property
    def ntotal(self):
        return len(self.ids)

    def add_with_ids(self, vectors, ids):
        self.ids.extend(int(i) for i in ids)
        self.vectors.extend(vectors.tolist())


class _Endpoint:
    """An ApiEmbedder's client: three numbers per text."""
    model = "embed-1"

    def __init__(self, width=3):
        self.width, self.seen = width, []

    def embed(self, items):
        self.seen.append([item for item in items])
        return [[float(len(item["text"]))] * self.width for item in items]


def _inp(text, i, image=None, kind="section_text"):
    return EmbeddingInput(embedding_type=kind, pdf_name="doc",
                          section_index=i, item_id=None, text=text,
                          image=image)


@pytest.fixture
def written(monkeypatch):
    calls = []

    class _Writer:
        def __init__(self, db_path):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def write(self, pdf_name, records):
            calls.extend(records)

    monkeypatch.setattr(emb, "EmbeddingWriter", _Writer)
    return calls


def test_the_api_backend_hands_the_index_unit_vectors():
    endpoint = _Endpoint()
    got = emb.ApiIndexEmbedder(endpoint).process(
        [{"text": "abcd"}, {"text": ""}])
    assert got.dtype == np.float32 and got.shape == (2, 3)
    assert np.isclose(np.linalg.norm(got[0]), 1.0)
    assert got[1].tolist() == [0.0, 0.0, 0.0]       # nothing to scale, no NaN


def test_an_input_with_a_picture_is_left_out_and_gets_no_row(written,
                                                             tmp_path):
    endpoint, index = _Endpoint(), _Index(3)
    inputs = [_inp("text one", 0), _inp("a figure", 1, image="crop.png",
                                        kind="figure_vl"),
              _inp("text two", 2)]
    end = emb.create_embeddings(inputs, index, 10, tmp_path / "db",
                                embedder=emb.ApiIndexEmbedder(endpoint))
    assert end == 12 and index.ids == [10, 11]
    assert [record[0] for record in written] == ["section_text",
                                                 "section_text"]
    assert all("image" not in item for batch in endpoint.seen
               for item in batch)


def test_an_embedder_that_takes_pictures_gets_the_input_that_carries_one(
        written, tmp_path):
    """Only a backend that says it takes text alone leaves a picture out:
    one that says nothing is a model, and the picture reaches it."""
    class _Model:
        seen = []

        def process(self, items):
            self.seen.append(list(items))
            return np.ones((len(items), 3), dtype=np.float32)

    embedder, index = _Model(), _Index(3)
    inputs = [_inp("text one", 0),
              _inp("a figure", 1, image="crop.png", kind="figure_vl")]
    end = emb.create_embeddings(inputs, index, 10, tmp_path / "db",
                                embedder=embedder)
    assert end == 12 and sorted(index.ids) == [10, 11]
    sent = [item for batch in embedder.seen for item in batch]
    assert {"text": "a figure", "image": "crop.png"} in sent
    assert {(record[0], record[3]) for record in written} == {
        ("section_text", 10), ("figure_vl", 11)}


def test_a_vector_of_another_size_never_reaches_the_index(written, tmp_path):
    index = _Index(4096)
    with pytest.raises(ValueError, match="EMBEDDING_DIM=3"):
        emb.create_embeddings([_inp("text", 0)], index, 0, tmp_path / "db",
                              embedder=emb.ApiIndexEmbedder(_Endpoint(3)))
    assert index.ids == [] and written == []


def test_the_backend_setting_decides_and_the_api_needs_no_model(monkeypatch):
    monkeypatch.setenv("EMBEDDING_INDEX_BACKEND", "api")
    monkeypatch.setattr(backend, "EMBEDDING_BASE_URL", "https://e.test/v1")
    # the model's own module would be imported for the local backend only
    monkeypatch.setitem(sys.modules, "docpipe.chunking.qwen3_vl_embedding",
                        None)
    embedder = emb.load_embedder("ignored")
    assert isinstance(embedder, emb.ApiIndexEmbedder) and embedder.text_only


def test_the_query_side_setting_does_not_move_the_index_build(monkeypatch):
    """Queries through an endpoint, the index from the model: a common setup."""
    monkeypatch.delenv("EMBEDDING_INDEX_BACKEND", raising=False)
    monkeypatch.setenv("EMBEDDING_BACKEND", "api")
    monkeypatch.setattr(backend, "BACKEND", "api")
    assert emb.index_backend() == "local"
    loaded = []
    monkeypatch.setitem(sys.modules, "torch", type(sys)("torch"))
    sys.modules["torch"].bfloat16 = "bf16"
    fake = type(sys)("docpipe.chunking.qwen3_vl_embedding")

    class _Model:
        replicas, devices = [1], ["cpu"]

        def __init__(self, **kwargs):
            loaded.append(kwargs["model_name_or_path"])

    fake.MultiGPUEmbedder = _Model
    monkeypatch.setitem(sys.modules, "docpipe.chunking.qwen3_vl_embedding",
                        fake)
    assert isinstance(emb.load_embedder("the-model"), _Model)
    assert loaded == ["the-model"]


def test_a_hosted_embedding_provider_needs_no_address(monkeypatch):
    monkeypatch.delenv("EMBEDDING_BASE_URL", raising=False)
    monkeypatch.setattr(backend, "EMBEDDING_BASE_URL", "")
    with pytest.raises(ValueError, match="EMBEDDING_BASE_URL"):
        ApiEmbedder()                           # a server of one's own does
    monkeypatch.setenv("EMBEDDING_PROVIDER", "gemini")
    asked = []
    monkeypatch.setattr(providers, "client",
                        lambda role, **kw: asked.append((role, kw)) or "c")
    assert ApiEmbedder().client() == "c"
    assert asked[0][0] == "embedding"


def test_a_hosted_endpoint_that_says_not_now_is_asked_again(monkeypatch):
    """And one's own server once, as before; a refusal is never retried."""
    class _Busy(Exception):
        def __init__(self, status):
            super().__init__(f"HTTP {status}")
            self.status_code = status

    def endpoint(script):
        calls = []

        def create(model, input):
            calls.append(list(input))
            outcome = script.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            vectors = [type("D", (), {"embedding": [1.0]})() for _ in input]
            return type("R", (), {"data": vectors, "usage": None})()
        made = type("C", (), {"embeddings": type("E", (), {
            "create": staticmethod(create)})()})()
        return made, calls

    monkeypatch.setattr(backend, "EMBEDDING_BASE_URL", "https://e.test/v1")
    api = ApiEmbedder()
    client, calls = endpoint([_Busy(429)])
    monkeypatch.setattr(api, "client", lambda: client)
    with pytest.raises(_Busy):                  # one's own server: asked once
        api.embed([{"text": "a"}])
    assert len(calls) == 1

    monkeypatch.setenv("EMBEDDING_PROVIDER", "gemini")
    client, calls = endpoint([_Busy(429), _Busy(503), "served"])
    monkeypatch.setattr(api, "client", lambda: client)
    assert api.embed([{"text": "a"}]) == [[1.0]]
    assert len(calls) == 3
    client, calls = endpoint([_Busy(400), "never reached"])
    monkeypatch.setattr(api, "client", lambda: client)
    with pytest.raises(_Busy):                  # a refusal is not "not now"
        api.embed([{"text": "a"}])
    assert len(calls) == 1
    from docpipe.embedding import api as api_module
    client, calls = endpoint([_Busy(429)] * api_module.HOSTED_ATTEMPTS)
    monkeypatch.setattr(api, "client", lambda: client)
    with pytest.raises(_Busy):                  # and not for ever
        api.embed([{"text": "a"}])
    assert len(calls) == api_module.HOSTED_ATTEMPTS
