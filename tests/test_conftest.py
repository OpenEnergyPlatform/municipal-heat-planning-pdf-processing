"""The suite must not depend on a big /tmp.

A compute node of hpc3 gives a job a 10 MB tmpfs on /tmp. This suite writes
databases, PDFs and harvest files into `tmp_path` by the hundred, so it fills
it -- and a full temp directory does not report itself. It reports as failing
tests: the same names came back FAILED in one tree and ERROR in another, 313
against 329, with the two lists mirror images of each other and not one line
of either saying "out of disk".
"""
import pathlib
import types

import conftest


def _usage(free_mb):
    return lambda path: types.SimpleNamespace(
        total=0, used=0, free=free_mb * 1024 * 1024)


class _Option:
    def __init__(self, basetemp=None):
        self.basetemp = basetemp


class _Config:
    def __init__(self, basetemp=None):
        self.option = _Option(basetemp)
        self.warnings = []

    def issue_config_time_warning(self, warning, stacklevel=1):
        self.warnings.append(str(warning))


def test_room_enough_is_the_only_thing_that_decides(monkeypatch, tmp_path):
    assert conftest.usable_tmp(tmp_path, usage=_usage(4096)) is True
    assert conftest.usable_tmp(tmp_path, usage=_usage(10)) is False
    # Exactly the threshold is enough; one byte under it is not.
    exact = conftest.TMP_MIN_BYTES

    def probe(path, free=exact):
        return types.SimpleNamespace(total=0, used=0, free=free)

    assert conftest.usable_tmp(tmp_path, usage=probe) is True
    assert conftest.usable_tmp(
        tmp_path, usage=lambda p: types.SimpleNamespace(
            total=0, used=0, free=exact - 1)) is False


def test_a_temp_directory_that_cannot_be_read_is_a_reason_to_move(tmp_path):
    """Unreadable is not the same as full, and both are reasons to move. The
    one thing that must not happen is an exception out of a configure hook,
    which takes the whole run down before a single test is collected."""
    def angry(path):
        raise OSError("no")

    assert conftest.usable_tmp(tmp_path, usage=angry) is False


def test_a_temp_root_with_no_room_moves_beside_the_repo_and_says_so(
        monkeypatch, tmp_path):
    monkeypatch.setattr(conftest.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(conftest.shutil, "disk_usage", _usage(10))
    config = _Config()
    conftest.pytest_configure(config)
    moved = pathlib.Path(config.option.basetemp)
    assert moved == pathlib.Path(conftest.ROOT) / ".pytest_tmp"
    assert moved.is_dir(), "it has to exist by the time pytest uses it"
    assert config.warnings and "less than" in config.warnings[0]


def test_a_temp_root_with_room_is_left_exactly_as_it_was(monkeypatch, tmp_path):
    monkeypatch.setattr(conftest.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(conftest.shutil, "disk_usage", _usage(4096))
    config = _Config()
    conftest.pytest_configure(config)
    assert config.option.basetemp is None
    assert not config.warnings


def test_a_basetemp_the_caller_chose_is_never_second_guessed(
        monkeypatch, tmp_path):
    """--basetemp is a decision, and a run that quietly writes somewhere else
    than the directory the caller named is worse than a full disk."""
    monkeypatch.setattr(conftest.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(conftest.shutil, "disk_usage", _usage(1))
    config = _Config(basetemp=str(tmp_path / "mine"))
    conftest.pytest_configure(config)
    assert config.option.basetemp == str(tmp_path / "mine")
    assert not config.warnings


# ---------------------------------------------------------------------------
# The openai errors a test raises have to be the installed library's
# ---------------------------------------------------------------------------

class _RealShaped(Exception):
    """`openai.APIError.__init__(self, message, request, *, body)`."""

    def __init__(self, message, request, *, body=None):
        super().__init__(message)
        self.request, self.body = request, body


class _StubShaped(Exception):
    """What conftest installs when openai cannot be imported."""


class _RequestOnly(Exception):
    """`openai.APITimeoutError.__init__(self, request)` -- no message at all."""

    def __init__(self, request):
        super().__init__("timed out")
        self.request = request


def test_an_openai_error_is_built_the_way_the_installed_library_wants(
        monkeypatch):
    """It failed on the HPC and nowhere else, for a year, because the suite
    was only ever run where openai is absent: the stub takes a message, the
    real class takes a request too and raises TypeError without it. The
    machine with the real library is the one the run happens on."""
    import types

    for shape in (_RealShaped, _StubShaped, _RequestOnly):
        monkeypatch.setattr(conftest, "_real_openai",
                            lambda shape=shape: types.SimpleNamespace(
                                APIError=shape, APITimeoutError=shape))
        error = conftest.api_error("boom")
        assert isinstance(error, shape), shape
        assert isinstance(error, BaseException)
        assert isinstance(conftest.api_error("t", timeout=True), shape)


def test_a_shape_none_of_the_forms_fit_is_said_out_loud(monkeypatch):
    """Silently handing back something unraisable would turn one clear error
    into a test that passes for the wrong reason."""
    import types

    class _Impossible(Exception):
        def __init__(self, a, b, c, d):
            super().__init__("no")

    monkeypatch.setattr(conftest, "_real_openai",
                        lambda: types.SimpleNamespace(
                            APIError=_Impossible, APITimeoutError=_Impossible))
    try:
        conftest.api_error("boom")
    except TypeError as exc:
        assert "cannot construct" in str(exc)
    else:
        raise AssertionError("it has to say so")
