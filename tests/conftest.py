"""Shared pytest fixtures + lightweight stubs for heavy/optional deps.

Combines the preprocessing/imageprocessing harness (a fake OpenAI-compatible
vLLM client + no-sleep backoff) with the chunking/DB fixtures (kwp_db). Heavy or
optional libraries (fitz, cv2, torch, faiss, ollama, openai, PIL, numpy) are
stubbed only when not installed, so real libraries are used where available.
"""
import os
import pathlib
import shutil
import sys
import tempfile
import types

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

# ---------------------------------------------------------------------------
# The suite must not depend on a big /tmp
# ---------------------------------------------------------------------------

# What one run of this suite needs where pytest puts `tmp_path`. Measured: a
# compute node of hpc3 gives every job a 10 MB tmpfs on /tmp, and this suite
# writes SQLite databases, PDFs and harvest files into tmp_path by the
# hundred. It fills, and from there the failures say nothing about disk: the
# same test came back FAILED in one tree and ERROR in another, 313 names
# against 329, the two lists mirror images of each other. Half a gigabyte is
# an order of magnitude over what the suite really writes, which is the right
# side to err on for a check whose job is to never fire on a real machine.
TMP_MIN_BYTES = 512 * 1024 * 1024


def usable_tmp(path, usage=None) -> bool:
    """Whether pytest's temp root has room for a run of this suite.

    False is not an error. It means the run is moved beside the repo, where
    there is room, and said out loud -- because a temp directory nobody chose
    is exactly the kind of thing that is invisible until it breaks 300 tests
    at once and none of them mentions it.
    """
    try:
        return (usage or shutil.disk_usage)(path).free >= TMP_MIN_BYTES
    except OSError:
        # Unreadable is not the same as full, and both are reasons to move.
        return False


def pytest_configure(config):
    """Put the temp root somewhere it fits, unless the caller chose one."""
    if getattr(config.option, "basetemp", None):
        return
    root = tempfile.gettempdir()
    if usable_tmp(root):
        return
    local = pathlib.Path(ROOT) / ".pytest_tmp"
    local.mkdir(parents=True, exist_ok=True)
    config.option.basetemp = str(local)
    config.issue_config_time_warning(
        pytest.PytestConfigWarning(
            f"{root} has less than {TMP_MIN_BYTES // (1024 * 1024)} MB free, "
            f"so tmp_path moves to {local}. A full temp directory does not "
            f"report itself -- it reports as failing tests."),
        stacklevel=2)

# A stage binds its prompts when it is imported, and prompts belong to a
# profile — so importing one without a profile is an error, not a default.
# Tests that care about another profile pass it explicitly.
os.environ["DOCPIPE_PROFILE"] = "kwp"


# Which of the heavy libraries below are stand-ins rather than the real
# thing. A stub is enough to IMPORT the modules under test; it is not enough
# to run the ones that do tensor arithmetic or vector search, and those must
# skip rather than fail on an attribute the stub does not have. Before this
# the local suite could not be collected at all: five files raised
# `module 'torch' has no attribute 'bfloat16'` at import time and took the
# whole run down with them.
STUBBED: set = set()


def needs_real(*names):
    """Skip this whole module unless these libraries are really installed."""
    missing = sorted(n for n in names if n in STUBBED)
    if missing:
        pytest.skip(f"needs the real {', '.join(missing)}, not the conftest "
                    f"stand-in", allow_module_level=True)


def _ensure_stub(name, attrs=None, submodules=None):
    """Install a minimal stub module under *name* only if it cannot be imported."""
    try:
        __import__(name)
        return
    except Exception:
        pass
    STUBBED.add(name)
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


def api_error(message="boom", timeout=False):
    """An `openai` error, built the way the INSTALLED openai wants it.

    The stub above takes a message and nothing else. The real library's
    `APIError.__init__` takes `(message, request, *, body)` and raises
    TypeError on a bare message -- so a test written against the stub passes
    on a machine that does not have openai and fails on every machine that
    does. That is exactly the wrong way round: the machine with the real
    library is the one the run happens on, and this failed there and nowhere
    else for as long as the suite was only ever run here.
    """
    kind = _real_openai().APITimeoutError if timeout else _real_openai().APIError
    for build in (lambda: kind(message, request=None, body=None),
                  lambda: kind(request=None),
                  lambda: kind(message)):
        try:
            return build()
        except TypeError:
            continue
    raise TypeError(f"cannot construct {kind!r}")


def _real_openai():
    import openai
    return openai


@pytest.fixture
def openai_error():
    """Factory: openai_error(message, timeout=False) -> a raisable error."""
    return api_error


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
    import docpipe.refinement.refine as s4
    import docpipe.visuals.vision as vis
    monkeypatch.setattr(s4.time, "sleep", lambda *a, **k: None)
    monkeypatch.setattr(vis.time, "sleep", lambda *a, **k: None)


# ---------------------------------------------------------------------------
# Chunking / DB fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def kwp_db(tmp_path):
    """A fresh SQLite DB with the core + kwp schema and one Document (id=1)."""
    from docpipe import store
    from docpipe.profile import load_profile
    from docpipe.chunking import database as DB
    db = tmp_path / "kwp.db"
    con = DB.connect(db)
    store.apply(con, load_profile("kwp"))
    con.execute("INSERT INTO Documents (id, filename, num_pages) VALUES (1, 'doc.pdf', 9)")
    con.commit()
    return db, con
