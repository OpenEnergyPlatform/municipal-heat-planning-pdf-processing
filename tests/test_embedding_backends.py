"""Choosing an embedding backend, and what the API backend cannot do."""
import pytest

from docpipe import embedding
from docpipe.embedding.api import ApiEmbedder


class _FakeResponse:
    def __init__(self, vectors):
        self.data = [type("D", (), {"embedding": v})() for v in vectors]


class _FakeClient:
    def __init__(self):
        self.calls = []
        self.embeddings = self

    def create(self, model, input):
        self.calls.append(list(input))
        return _FakeResponse([[float(len(t))] * 3 for t in input])


def _api(monkeypatch, **kw):
    emb = ApiEmbedder(base_url="https://example.test/v1", **kw)
    client = _FakeClient()
    monkeypatch.setattr(emb, "client", lambda: client)
    return emb, client


def test_backend_is_configuration_not_code(monkeypatch):
    monkeypatch.setenv("EMBEDDING_BASE_URL", "https://example.test/v1")
    assert isinstance(embedding.get_embedder("api", base_url="https://example.test/v1"),
                      ApiEmbedder)
    with pytest.raises(ValueError):
        embedding.get_embedder("telepathy")


# ---------------------------------------------------------------------------
# The extension point: an implementation this repository does not contain
# ---------------------------------------------------------------------------

def test_a_deployment_can_bind_its_own_implementation():
    """The inference server loads its model quantized and frees it again. That
    is a property of its two cards, not of the pipeline, so the code lives
    there and is named here by import path."""
    emb = embedding.get_embedder("tests.fake_backend:FakeEmbedder", tag="nf4")

    assert emb.tag == "nf4"
    assert emb.embed_one({"text": "abc"}) == [3.0]


def test_the_import_path_may_name_a_function_too():
    emb = embedding.get_embedder("tests.fake_backend:make_embedder")

    assert emb.tag == "factory"


@pytest.mark.parametrize("spec, hint", [
    ("tests.fake_backend", "package.module:attribute"),   # no colon → not a path
    ("tests.no_such_module:X", "tests.no_such_module"),
    ("tests.fake_backend:Missing", "Missing"),
])
def test_a_broken_backend_says_which_part_broke(spec, hint):
    """An unimportable backend is a deployment typo; the message has to name
    the piece that failed, or the operator is left guessing."""
    with pytest.raises(ValueError) as exc:
        embedding.get_embedder(spec)
    assert hint in str(exc.value)


def test_api_backend_needs_an_endpoint(monkeypatch):
    monkeypatch.setattr("docpipe.embedding.config.EMBEDDING_BASE_URL", "")
    with pytest.raises(ValueError):
        ApiEmbedder()


def test_api_embeds_text_in_batches(monkeypatch):
    emb, client = _api(monkeypatch, batch_size=2)
    out = emb.embed([{"text": "a"}, {"text": "bb"}, {"text": "ccc"}])
    assert [v[0] for v in out] == [1.0, 2.0, 3.0]
    assert client.calls == [["a", "bb"], ["ccc"]]      # two requests, not three


def test_api_refuses_images_instead_of_dropping_them(monkeypatch):
    """The OpenAI embeddings schema has no image field — silently embedding the
    caption instead would give a *_vl vector that never saw the picture."""
    emb, _ = _api(monkeypatch)
    with pytest.raises(ValueError) as exc:
        emb.embed([{"text": "ok"}, {"text": "chart", "image": "/tmp/x.png"}])
    assert "local" in str(exc.value)


def test_embed_one_goes_through_the_batch_path(monkeypatch):
    emb, client = _api(monkeypatch)
    assert emb.embed_one({"text": "abcd"})[0] == 4.0
    assert client.calls == [["abcd"]]
