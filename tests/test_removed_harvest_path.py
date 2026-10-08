"""The request for a whole tuple, the switch that chose it and the prompt it
read are gone.

Promised: nothing in the code, the profiles, the scripts or the tests names
the switch between the two ways of asking or the prompt of the one that is
gone, AND no profile carries a file for that prompt, AND the stamp schema does
not require its key, AND the reply grammar has no form in which a row carries
its coordinates, AND the harvester takes no prompt to choose between the two,
AND a run builds the one harvester there is.

A name that is removed is removed everywhere, so the scan below reads every
text file of the four trees for it. What stays on purpose is listed per token
with the file that keeps it and the reason. A scan that cannot find a token is
decoration, so it is first run over a folder built to hold one.
"""
import inspect
import json
import re
import shutil
from pathlib import Path

from docpipe.extraction import replies, runner
from docpipe.extraction.schema import stamp_schema

ROOT = Path(__file__).resolve().parent.parent
TREES = ("docpipe", "profiles", "scripts", "tests")
SUFFIXES = {".py", ".md", ".json", ".toml", ".txt", ".sh", ".yml", ".yaml",
            ".cfg", ".ini"}

# Each token is written in two halves: this file would otherwise be the one
# place that names what it says nobody names.
SWITCH = "FIELD" + "WISE"
PROMPT_CONSTANT = "HARVEST" + "_PROMPT_ID"
PROMPT_ID = "extraction/" + "harvest"
# The id of the prompt, and not the id of the harvest file's schema, which
# reads `extraction/harvest-line`.
PROMPT_ID_PATTERN = re.escape(PROMPT_ID) + r"(?![-\w])"

# token -> (pattern, {file: why it stays}). Files relative to the repository,
# with forward slashes.
KEPT = {
    SWITCH: (re.escape(SWITCH), {
        "tests/test_settings.py": "the table of settings that are gone: the "
                                  "name has to be refused in a project file",
    }),
    PROMPT_CONSTANT: (re.escape(PROMPT_CONSTANT), {}),
    PROMPT_ID: (PROMPT_ID_PATTERN, {
        "tests/test_legacy_stamp.py": "the key an older stamp still carries, "
                                      "which has to stay valid and current",
    }),
}


def scan(root: Path, pattern: str) -> list:
    """The files under the four trees of *root* that match *pattern*."""
    wanted = re.compile(pattern)
    found = []
    for tree in TREES:
        for path in sorted((root / tree).rglob("*")):
            if (path.is_file() and path.suffix in SUFFIXES
                    and "__pycache__" not in path.parts):
                if wanted.search(path.read_text(encoding="utf-8",
                                                errors="ignore")):
                    found.append(path.relative_to(root).as_posix())
    return found


def strays(root: Path, pattern: str, kept: dict) -> list:
    return [name for name in scan(root, pattern) if name not in kept]


def test_nothing_names_a_removed_token_but_where_it_is_kept():
    for token, (pattern, kept) in KEPT.items():
        assert strays(ROOT, pattern, kept) == [], token
        # What is kept is there: an entry nobody needs is a hole in the scan.
        assert sorted(scan(ROOT, pattern)) == sorted(kept), token


def test_the_scan_finds_a_token_where_it_is_not_kept(tmp_path):
    """Built to fail: a file of each tree names the switch, and one of them is
    the file that is allowed to."""
    for tree in TREES:
        (tmp_path / tree).mkdir()
        (tmp_path / tree / "module.py").write_text(
            f"# {SWITCH}\n", encoding="utf-8")
    (tmp_path / "tests" / "kept.py").write_text(f"X = '{SWITCH}'\n",
                                                encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "page.md").write_text(SWITCH, encoding="utf-8")
    kept = {"tests/kept.py": "built for this"}
    pattern = re.escape(SWITCH)
    assert strays(tmp_path, pattern, kept) == [
        "docpipe/module.py", "profiles/module.py", "scripts/module.py",
        "tests/module.py"]
    assert strays(tmp_path, pattern, {}) != strays(tmp_path, pattern, kept)


def test_the_scan_finds_the_prompt_and_not_the_id_of_the_harvest_files_schema(
        tmp_path):
    """Built to fail: the id of the prompt, in a file of a tree, is found; the
    id of the schema of the harvest file, which only starts like it, is not."""
    for tree in TREES:
        (tmp_path / tree).mkdir()
    (tmp_path / "tests" / "old.py").write_text(
        f'KEY = "{PROMPT_ID}"\n', encoding="utf-8")
    (tmp_path / "profiles" / "schema.json").write_text(
        f'{{"$id": "https://example.org/schema/{PROMPT_ID}-line"}}',
        encoding="utf-8")
    (tmp_path / "scripts" / "const.py").write_text(
        f"{PROMPT_CONSTANT} = 1\n", encoding="utf-8")
    assert scan(tmp_path, PROMPT_ID_PATTERN) == ["tests/old.py"]
    assert scan(tmp_path, re.escape(PROMPT_CONSTANT)) == ["scripts/const.py"]


def removed(function, names) -> set:
    """Which of *names* the function still takes as a parameter."""
    return set(names) & set(inspect.signature(function).parameters)


def test_a_row_of_the_reply_grammar_has_no_coordinates_of_its_own():
    assert set(inspect.signature(replies.rows).parameters) == {"sandbox"}
    row = replies.rows()["properties"]["tuples"]["items"]["properties"]
    assert set(row) == {"source", "unit_raw", "value", "value_raw", "quote",
                        "computed"}
    assert not hasattr(replies, "_coordinates")


def test_the_harvester_takes_no_prompt_to_choose():
    assert removed(runner.make_harvester, ("prompt_id", "whole")) == set()
    assert set(inspect.signature(runner.make_harvester).parameters) == {
        "image_root", "spec"}


def test_a_function_that_still_takes_what_was_removed_is_found():
    """Built to fail: the old signatures, which the checks above refuse."""
    def rows(spec=None, *, whole=False, sandbox=True): ...

    def make_harvester(image_root=None, prompt_id="x", spec=None): ...

    assert removed(rows, ("prompt_id", "whole", "spec")) == {"whole", "spec"}
    assert removed(make_harvester, ("prompt_id", "whole")) == {"prompt_id"}
    assert set(inspect.signature(rows).parameters) != {"sandbox"}


def chooses_between_builders(function) -> bool:
    """Whether the function builds the rows harvester on its own, which is
    what a branch between the two harvesters did."""
    return "make_harvester(" in inspect.getsource(function)


def test_a_run_builds_the_one_harvester_and_the_module_has_no_switch():
    """`main` once chose between two builders by a module constant. It builds
    the field-wise one, which builds the rows request itself."""
    assert "make_fieldwise_harvester(" in inspect.getsource(runner.main)
    assert not chooses_between_builders(runner.main)
    assert not hasattr(runner, SWITCH)


def test_a_main_that_chose_between_builders_is_found():
    """Built to fail: a main with the old branch in it."""
    def old_main(flag, make_fieldwise_harvester, make_harvester):
        return (make_fieldwise_harvester() if flag else make_harvester())

    assert chooses_between_builders(old_main)


# ---------------------------------------------------------------------------
# The prompt itself
# ---------------------------------------------------------------------------

def harvest_files(root: Path) -> list:
    """The files of a prompt of that name under the code and the profiles of
    *root*."""
    return sorted(path.relative_to(root).as_posix()
                  for tree in ("docpipe", "profiles")
                  for path in (root / tree).rglob("harvest.md"))


def test_no_runner_constant_no_stamp_entry_and_no_file_is_left_of_the_prompt():
    assert not hasattr(runner, PROMPT_CONSTANT)
    assert runner.PROMPT_IDS == (
        runner.QUERIES_PROMPT_ID, runner.ANCHORS_PROMPT_ID,
        runner.ROWS_PROMPT_ID, runner.FIELD_PROMPT_ID,
        runner.PHRASE_PROMPT_ID, runner.FRAME_PROMPT_ID)
    assert PROMPT_ID not in runner.PROMPT_IDS
    assert harvest_files(ROOT) == []


def test_a_file_of_the_prompt_is_found_where_a_profile_would_carry_it(tmp_path):
    """Built to fail: the prompts folder of a profile with the file in it."""
    folder = tmp_path / "profiles" / "kwp" / "prompts" / "extraction"
    folder.mkdir(parents=True)
    (folder / "rows.md").write_text("kept", encoding="utf-8")
    (folder / "harvest.md").write_text("back again", encoding="utf-8")
    assert harvest_files(tmp_path) == [
        (folder / "harvest.md").relative_to(tmp_path).as_posix()]


def test_a_profile_that_carries_the_prompt_is_one_the_architecture_test_refuses(
        tmp_path):
    """The guard that keeps a prompt nobody loads off the disk. Built to fail:
    a copy of a profile's prompts with the file put back, run through the
    same comparison, leaves exactly that prompt over."""
    from tests.test_architecture import CORE, PROFILES, _requested_prompt_ids
    home = tmp_path / "kwp"
    shutil.copytree(PROFILES / "kwp" / "prompts", home / "prompts")

    def left_over():
        on_disk = {f"{p.parent.name}/{p.stem}"
                   for p in (home / "prompts").rglob("*.md")}
        return on_disk - _requested_prompt_ids(CORE, home)

    assert left_over() == set()
    (home / "prompts" / "extraction" / "harvest.md").write_text(
        "back again", encoding="utf-8")
    assert left_over() == {PROMPT_ID}


def requires_the_key(shape: dict) -> bool:
    return PROMPT_ID in shape["required"]


def describes_the_key(shape: dict) -> bool:
    """Whether a stamp that still carries the key is one the schema names."""
    return any(re.search(name, PROMPT_ID)
               for name in shape["patternProperties"])


def test_the_stamp_schema_and_its_published_copies_do_not_require_the_key():
    for profile in ("kwp", "scenarios"):
        published = json.loads((ROOT / "profiles" / profile
                                / "extraction_schema.json").read_text(
            encoding="utf-8"))["stamp"]
        for shape in (stamp_schema(), published):
            assert not requires_the_key(shape), profile
            assert "extraction/rows" in shape["required"], profile
            assert describes_the_key(shape), profile


def test_a_schema_that_requires_the_key_or_forgets_it_is_found():
    """Built to fail: the stamp schema as it was, with the key required, and
    one with the key's pattern taken out, which a stored stamp would not
    validate against."""
    shape = stamp_schema()
    old = {**shape, "required": [*shape["required"], PROMPT_ID]}
    assert requires_the_key(old)
    patterns = {name: value for name, value in shape["patternProperties"].items()
                if not re.search(name, PROMPT_ID)}
    assert not describes_the_key({**shape, "patternProperties": patterns})
