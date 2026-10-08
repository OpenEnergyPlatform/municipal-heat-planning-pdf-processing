"""What `docpipe init` leaves behind besides the profile, and what the package
brings for it.

Promised: a new project asks the refinement for corrections (`[refine]
return_corrections = true` in its own docpipe.toml, with a comment line that
says what it does), and the setting is read from that file; the core, the
built-in profile, kwp and scenarios do not ask for it, so nothing already
stored goes stale; the package ships the metadata shape as a package file that
pyproject names AND the built-in profile names no extraction spec, so nothing
starts to harvest silently under it.
"""
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from docpipe import cli, settings
from tests.test_entry_points import PROBE

ROOT = Path(__file__).resolve().parent.parent
STRIP = ("DOCPIPE_PROFILE", "DOCPIPE_PROFILE_PATH", "DOCPIPE_CONFIG",
         "DOCPIPE_DATA_ROOT", "DOCPIPE_ENV_FILE", "REFINE_RETURN_CORRECTIONS")


def _docpipe(*args, cwd, **env):
    child = {k: v for k, v in os.environ.items() if k not in STRIP}
    child.update(env, PYTHONPATH=str(ROOT),
                 DOCPIPE_USAGE_DB=str(Path(cwd) / "usage.db"))
    return subprocess.run([sys.executable, "-c", PROBE, "docpipe", *args],
                          cwd=str(cwd), env=child, capture_output=True,
                          text=True)


# ---- the refinement ------------------------------------------------------------

def test_a_new_project_asks_for_corrections_and_says_what_that_is(tmp_path):
    assert cli.main(["init", "demo", "--dir", str(tmp_path)]) == 0
    path = tmp_path / settings.PROJECT_FILE
    assert settings.read(path) == {"DOCPIPE_PROFILE": "demo",
                                   "REFINE_RETURN_CORRECTIONS": "1"}
    lines = path.read_text(encoding="utf-8").splitlines()
    key = lines.index("return_corrections = true")
    assert lines[key - 2] == "[refine]"
    assert lines[key - 1].startswith("# ") and "corrections" in lines[key - 1]


def test_the_setting_is_what_the_file_says_and_the_file_has_to_say_it():
    """Built to fall: the same file without the line, and with the key
    misspelled, are not the same project."""
    said = cli.PROJECT_TOML.format(name="demo")
    gone = said.replace("return_corrections = true\n", "")
    assert "REFINE_RETURN_CORRECTIONS" not in _read(gone)
    typo = said.replace("return_corrections", "return_correction")
    with pytest.raises(settings.ConfigError, match="is no setting"):
        _read(typo)


def _read(text):
    import tempfile
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / settings.PROJECT_FILE
        path.write_text(text, encoding="utf-8")
        return settings.read(path)


def test_the_setting_is_in_effect_in_the_new_project_and_nowhere_else(
        tmp_path):
    home, elsewhere = tmp_path / "home", tmp_path / "elsewhere"
    home.mkdir()
    elsewhere.mkdir()
    assert _docpipe("init", "demo", cwd=home).returncode == 0
    wanted = "REFINE_RETURN_CORRECTIONS"
    inside = _docpipe("config", "--stage", "refine", cwd=home).stdout
    row = next(line for line in inside.splitlines() if wanted in line)
    assert re.search(r"refine\.return_corrections\s+1\s+\[docpipe\.toml;", row)
    outside = _docpipe("config", "--stage", "refine", cwd=elsewhere).stdout
    row = next(line for line in outside.splitlines() if wanted in line)
    assert re.search(r"refine\.return_corrections\s+0\s+\[default;", row)
    # what the environment says stands over the file
    said = _docpipe("config", "--stage", "refine", cwd=home,
                    REFINE_RETURN_CORRECTIONS="0").stdout
    row = next(line for line in said.splitlines() if wanted in line)
    assert re.search(r"refine\.return_corrections\s+0\s+\[environment;", row)


def test_nothing_but_a_new_project_asks_for_corrections():
    """The default stays off, and neither the built-in profile nor the two
    profiles of this repository switch it on: the results they stored are
    read with the prompt they were made with."""
    assert settings.BY_ENV["REFINE_RETURN_CORRECTIONS"].default == "0"
    for home in (ROOT / "docpipe" / "builtin", ROOT / "profiles" / "kwp",
                 ROOT / "profiles" / "scenarios"):
        for path in home.rglob("*"):
            if path.is_file() and path.suffix in (".py", ".toml", ".json",
                                                  ".md", ".sql"):
                assert "return_corrections" not in path.read_text(
                    encoding="utf-8").lower(), path


# ---- the built-in profile and the package file ---------------------------------

def test_the_built_in_profile_names_no_extraction_spec():
    """`component` hands what the profile it extends names to every profile
    that names nothing, so a spec here would start to harvest under every
    project that has none."""
    import ast

    from docpipe.profile import load_profile
    default = ROOT / "docpipe" / "builtin" / "default" / "extraction.py"
    tree = ast.parse(default.read_text(encoding="utf-8"))
    assigned = {target.id for node in ast.walk(tree)
                if isinstance(node, (ast.Assign, ast.AnnAssign))
                for target in (node.targets if isinstance(node, ast.Assign)
                               else [node.target])
                if isinstance(target, ast.Name)}
    assert "SPEC_PATH" not in assigned
    assert load_profile("default").component("extraction", "SPEC_PATH") is None


def test_extract_under_the_built_in_profile_stops_and_says_why(tmp_path):
    run = _docpipe("--profile", "default", "extract", "a.db", "a.bin", "out",
                   cwd=tmp_path)
    assert run.returncode == 2
    assert "profile 'default' does not configure the extraction stage" \
        in run.stderr
    assert not (tmp_path / "out").exists()


def _packaged(relative: str, patterns) -> bool:
    """Would setuptools take this file of the package, by its package-data
    patterns? `**/` is any folders, `*` is any name part."""
    for pattern in patterns:
        text = re.escape(pattern).replace(r"\*\*/", "(?:.*/)?").replace(
            r"\*", "[^/]*")
        if re.fullmatch(text, relative):
            return True
    return False


def _package_data() -> list:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    block = re.search(r"\[tool\.setuptools\.package-data\]\n(?:#.*\n)*"
                      r"docpipe = \[(.*?)\]", text, re.S)
    return re.findall(r'"([^"]+)"', block.group(1))


def test_the_metadata_shape_is_a_package_file_that_pyproject_names():
    from docpipe.compile import shapes
    assert shapes.BUNDLED.is_file()
    relative = shapes.BUNDLED.relative_to(ROOT / "docpipe").as_posix()
    assert _packaged(relative, _package_data())
    # built to fall: without the extension in the list it would be left out
    assert not _packaged(relative, [p for p in _package_data()
                                    if not p.endswith(".ttl")])
    # and the sources are not taken for what they are not
    assert not _packaged("compile/draft.py", _package_data())
