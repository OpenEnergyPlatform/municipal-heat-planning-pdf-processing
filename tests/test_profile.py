"""Profile loading and the paths derived from it."""
import os

import pytest

from docpipe.profile import ENV_VAR, Facet, Profile, active_profile, load_profile


def test_kwp_profile_loads_and_names_itself():
    p = load_profile("kwp")
    assert p.name == "kwp"
    assert p.source_language == "de" and p.answer_language == "de"
    assert any(f.field == "bundesland_lang" for f in p.facets)


def test_paths_are_profile_scoped(tmp_path):
    a = Profile(name="a", data_root=tmp_path / "a")
    b = Profile(name="b", data_root=tmp_path / "b")
    # two profiles must never share a file
    assert a.db_path != b.db_path
    assert a.index_path.parent == a.root and a.pdf_dir.parent == a.root
    assert a.db_path.name == "a.db"


def test_data_root_default_follows_env(monkeypatch, tmp_path):
    monkeypatch.setenv("DOCPIPE_DATA_ROOT", str(tmp_path))
    assert Profile(name="x").root == tmp_path / "x"


def test_unknown_profile_lists_the_available_ones():
    with pytest.raises(LookupError) as exc:
        load_profile("gibtsnicht")
    assert "kwp" in str(exc.value)


def test_no_profile_is_an_explicit_error(monkeypatch):
    monkeypatch.delenv(ENV_VAR, raising=False)
    assert active_profile() is None
    with pytest.raises(LookupError):
        load_profile()


def test_ambient_profile_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv(ENV_VAR, "kwp")
    assert active_profile().name == "kwp"


@pytest.mark.parametrize("bad", ["", "a/b", "a\\b"])
def test_rejects_unusable_names(bad):
    with pytest.raises(ValueError):
        Profile(name=bad)


def test_rejects_unknown_column_layout():
    with pytest.raises(ValueError):
        Profile(name="x", column_layout="zweispaltig")


def test_facet_defaults_to_multiselect():
    assert Facet("f", "F").widget == "multiselect"
