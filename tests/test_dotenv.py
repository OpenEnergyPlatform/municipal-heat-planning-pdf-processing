"""Loading the .env early enough that config modules see it.

Config modules capture os.environ at import time, so *when* the file is read
decides whether it has any effect at all. The app used to load it in its own
config module — which app.py imports after docpipe.inference, so the endpoint
key was silently "EMPTY" and the LLM answered 401.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

from docpipe.dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def env_file(tmp_path, monkeypatch):
    p = tmp_path / "test.env"
    monkeypatch.setenv("DOCPIPE_ENV_FILE", str(p))
    return p


def test_it_reads_key_value_lines(env_file, monkeypatch):
    monkeypatch.delenv("SOME_KEY", raising=False)
    env_file.write_text("SOME_KEY=abc123\n", encoding="utf-8")

    assert load_dotenv() == env_file
    assert os.environ["SOME_KEY"] == "abc123"


def test_an_explicit_environment_variable_wins(env_file, monkeypatch):
    """A SLURM export or a systemd Environment= must not be overwritten by a
    file that happens to sit in the working directory."""
    monkeypatch.setenv("SOME_KEY", "from-the-environment")
    env_file.write_text("SOME_KEY=from-the-file\n", encoding="utf-8")

    load_dotenv()

    assert os.environ["SOME_KEY"] == "from-the-environment"


def test_comments_blanks_and_quotes(env_file, monkeypatch):
    for k in ("A", "B", "C"):
        monkeypatch.delenv(k, raising=False)
    env_file.write_text('# a comment\n\nA="quoted"\nB=\'single\'\nC=bare\nnot a pair\n',
                        encoding="utf-8")

    load_dotenv()

    assert (os.environ["A"], os.environ["B"], os.environ["C"]) == ("quoted", "single", "bare")


def test_a_missing_file_is_not_an_error(monkeypatch, tmp_path):
    monkeypatch.setenv("DOCPIPE_ENV_FILE", str(tmp_path / "nope.env"))
    monkeypatch.chdir(tmp_path)          # no ./.env either

    assert load_dotenv() is None


def test_the_value_reaches_the_config_that_reads_it(tmp_path):
    """The regression, in a fresh interpreter: importing a config module under
    docpipe must already see the file's values, because import time is when it
    captures them. Checked on docpipe.embedding.config because it pulls in no
    third-party package — the property under test is the import order, and that
    is the same for every config module in the tree."""
    env = tmp_path / "x.env"
    env.write_text("EMBEDDING_BACKEND=backends.nf4:Nf4Embedder\n", encoding="utf-8")

    child = os.environ.copy()
    child["DOCPIPE_ENV_FILE"] = str(env)
    child["PYTHONPATH"] = str(REPO_ROOT)
    child.pop("EMBEDDING_BACKEND", None)

    out = subprocess.run(
        [sys.executable, "-c",
         "from docpipe.embedding import config; print(config.BACKEND)"],
        capture_output=True, text=True, env=child, cwd=str(tmp_path),
    )

    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "backends.nf4:Nf4Embedder"
