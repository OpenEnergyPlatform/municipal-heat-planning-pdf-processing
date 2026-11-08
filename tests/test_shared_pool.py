"""Every request of a run goes out through one connection pool, no larger
than the requests the run may have open at once: a server behind a proxy
that takes about 20 connections refused the rest of a probe whose eleven
clients each kept their own.

- Two clients of the run share one pool, AND that pool holds at most the
  run's limit of connections.
"""
from types import SimpleNamespace

import pytest

from docpipe.extraction import runner


@pytest.fixture
def fresh(monkeypatch):
    monkeypatch.setattr(runner, "_SHARED_HTTP", None)
    monkeypatch.setattr(runner, "LIMIT", SimpleNamespace(maximum=18))
    monkeypatch.setattr(runner, "SCHEDULER", None)
    monkeypatch.setattr(runner, "LLM_BASE_URL", "http://127.0.0.1:9/v1")
    yield
    if runner._SHARED_HTTP is not None:
        runner._SHARED_HTTP.close()


def made(monkeypatch):
    """The keyword arguments of every client the run asks the provider for."""
    calls = []
    monkeypatch.setattr(runner.providers, "client",
                        lambda role, **kwargs: calls.append(kwargs) or object())
    return calls


def test_two_clients_of_a_run_share_one_pool_of_the_run_s_size(fresh,
                                                               monkeypatch):
    calls = made(monkeypatch)
    runner._client(), runner._client()
    first, second = (call["http_client"] for call in calls)
    assert first is second is runner.shared_http()
    pool = first._transport._pool
    assert pool._max_connections == 18
    assert pool._max_keepalive_connections == 18


def test_a_pool_of_its_own_per_client_is_found(fresh, monkeypatch):
    import httpx
    calls = made(monkeypatch)
    monkeypatch.setattr(runner, "shared_http",
                        lambda limit=None: httpx.Client())
    runner._client(), runner._client()
    first, second = (call["http_client"] for call in calls)
    assert first is not second
