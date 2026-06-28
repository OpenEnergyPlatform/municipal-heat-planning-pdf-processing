"""Shared pytest fixtures + lightweight stubs for heavy/optional deps.

Combines the preprocessing/imageprocessing harness (a fake OpenAI-compatible
vLLM client + no-sleep backoff) with the chunking/DB fixtures (kwp_db). Heavy or
optional libraries (fitz, cv2, torch, faiss, ollama, openai, PIL, numpy) are
stubbed only when not installed, so real libraries are used where available.
"""
import os
import pathlib
import sys
import types

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)


def _ensure_stub(name, attrs=None, submodules=None):
    """Install a minimal stub module under *name* only if it cannot be imported."""
    try:
        __import__(name)
        return
    except Exception:
        pass
    mod = types.ModuleType(name)
    for key, value in (attrs or {}).items():
        setattr(mod, key, value)
    sys.modules[name] = mod
    for sub, sattrs in (submodules or {}).items():
        smod = types.ModuleType(f"{name}.{sub}")
        for key, value in (sattrs or {}).items():
            setattr(smod, key, value)
        setattr(mod, sub, smod)
        sys.modules[f"{name}.{sub}"] = smod


class _StubAPIError(Exception):
    pass


class _StubAPITimeoutError(_StubAPIError):
    pass


class _DummyOpenAI:  # constructible vLLM client stand-in (never called under test)
    def __init__(self, *args, **kwargs):
        pass


# Heavy/optional deps: stubbed only when missing.
for _m in ("fitz", "cv2", "torch", "faiss", "ollama"):
    _ensure_stub(_m)
_ensure_stub("numpy", attrs={"ndarray": object})
_ensure_stub("PIL", submodules={"Image": {}})
_ensure_stub("openai", attrs={
    "OpenAI": _DummyOpenAI,
    "APIError": _StubAPIError,
    "APITimeoutError": _StubAPITimeoutError,
})


# ---------------------------------------------------------------------------
# Fake OpenAI-compatible (vLLM) client
# ---------------------------------------------------------------------------

def _response(content):
    """Builds an object shaped like an OpenAI chat-completions response."""
    return types.SimpleNamespace(
        choices=[types.SimpleNamespace(
            message=types.SimpleNamespace(content=content))]
    )


class _FakeCompletions:
    def __init__(self, responder, recorder):
        self._responder = responder
        self._recorder = recorder

    def create(self, **kwargs):
        if self._recorder is not None:
            self._recorder.append(kwargs)
        return self._responder(kwargs)


def _make_client(responder, model_id="test-model", recorder=None):
    client = types.SimpleNamespace()
    client.chat = types.SimpleNamespace(completions=_FakeCompletions(responder, recorder))
    client.models = types.SimpleNamespace(
        list=lambda: types.SimpleNamespace(data=[types.SimpleNamespace(id=model_id)])
    )
    return client


def _seq_responder(items):
    """Replies with each item in turn; raising it if it is an Exception."""
    state = {"i": 0}

    def responder(_kwargs):
        item = items[min(state["i"], len(items) - 1)]
        state["i"] += 1
        if isinstance(item, BaseException):
            raise item
        return _response(item)

    return responder


@pytest.fixture
def make_client():
    """Factory: make_client(responder, model_id=..., recorder=...) -> fake client."""
    return _make_client


@pytest.fixture
def seq_responder():
    """Factory: seq_responder([reply_or_exc, ...]) -> responder for make_client."""
    return _seq_responder


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    """Never actually sleep during retry/backoff tests."""
    import scripts.preprocessing.stage4_refine as s4
    import scripts.imageprocessing.vision as vis
    monkeypatch.setattr(s4.time, "sleep", lambda *a, **k: None)
    monkeypatch.setattr(vis.time, "sleep", lambda *a, **k: None)


# ---------------------------------------------------------------------------
# Chunking / DB fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def kwp_db(tmp_path):
    """A fresh SQLite DB with the v2 schema and one Document (id=1)."""
    from scripts.chunkingandembedding import database as DB
    schema = pathlib.Path(ROOT, "data", "KWP.db.sql").read_text(encoding="utf-8")
    db = tmp_path / "kwp.db"
    con = DB.connect(db)
    con.executescript(schema)
    con.execute("INSERT INTO Documents (id, filename, num_pages) VALUES (1, 'doc.pdf', 9)")
    con.commit()
    return db, con
