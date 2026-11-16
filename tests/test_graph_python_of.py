"""The logic of a brick as Python (`graphblocks.python_of`): the Graph tab shows a
brick as the Python block it would be, so it can be changed there.

The promise, in one sentence: the Python made of a brick is a block that
compiles in the space a run gives AND gives, on a call, exactly what the
brick gives AND runs as it stands, with its own import lines for every name of
its module the block's names lack. Each part has a case that keeps it and one
that breaks it by construction."""
import types

import pytest

from docpipe.editor import graphpage
from docpipe.extraction import bricks, graph, graphblocks
from docpipe.extraction.bricks import Brick, Call
from docpipe.profile import load_profile

PROFILES = {name: load_profile(name) for name in ("kwp", "scenarios")}


def every_brick():
    """(where, name, brick) of the core and of both profiles."""
    out = [("core", name, one) for name, one in bricks.CORE.items()]
    for name, profile in PROFILES.items():
        own = {one.name for one in profile.component("kg", "BRICKS") or ()}
        out += [(name, n, one) for n, one in bricks.registry(profile).items()
                if n in own]
    return out


ALL = every_brick()
IDS = [f"{where}:{name}" for where, name, _ in ALL]


def space_of(where):
    return graph.python_space(PROFILES[where]) if where in PROFILES else {}


class Doc:
    """What the sample calls of the bricks ask of a document."""
    prefixes = {"oeo": "https://example.org/oeo/", "obo": "https://obo/"}
    legal_forms = "GmbH"

    def __init__(self):
        self.counted = []

    def count(self, what, name=""):
        self.counted.append((what, name))


def both(brick, code, **given):
    """(what the brick gives, what the Python of it gives) on one call."""
    first, second = Doc(), Doc()
    expect = brick.run(Call(doc=first, **given))
    got = graphblocks.compiled(code, {})(Call(doc=second, **given))
    return expect, got, first.counted, second.counted


def without_imports(code):
    """The code with its import lines at the top taken out."""
    lines = code.split("\n")
    at = lines.index("def run(call):")
    return "\n".join(lines[at:])


# -- every brick becomes a block ------------------------------------------------

@pytest.mark.parametrize("where,name,brick", ALL, ids=IDS)
def test_the_python_of_a_brick_is_a_block_that_compiles_in_a_runs_space(
        where, name, brick):
    code = graphblocks.python_of(brick)
    assert graphblocks.python_problem(code) is None
    assert code.count("def run(call):") == 1
    run = graphblocks.compiled(code, space_of(where))
    assert callable(run)


def test_a_brick_whose_source_is_not_to_be_had_gives_no_python():
    # the promise "every brick has Python" fails for it, and the test above
    # would say so
    space: dict = {}
    exec("def made(call):\n    return None\n", space)
    gone = Brick("gone", "value", "", "", "", space["made"])
    code = graphblocks.python_of(gone)
    assert code == ""
    assert graphblocks.python_problem(code) is not None


def test_the_def_line_is_run_of_call_without_annotations():
    code = graphblocks.python_of(bricks.CORE["trimmed"])
    assert code.startswith("def run(call):\n")
    assert "-> str" not in code and "Call" not in code


def test_a_relative_import_of_the_body_is_written_out_in_full():
    code = graphblocks.python_of(bricks.CORE["kept_coordinates"])
    assert "from docpipe.extraction import fields" in code
    assert "from ." not in code


def test_the_page_gets_the_python_of_every_brick_it_is_sent():
    for name, profile in PROFILES.items():
        sent = {one["name"]: one for one in graphpage.bricks_of(profile)}
        for brick_name, brick in bricks.registry(profile).items():
            assert sent[brick_name]["python"] == graphblocks.python_of(brick)
            assert sent[brick_name]["python"]


# -- the Python gives what the brick gives ---------------------------------------

def test_answer_class_gives_what_the_brick_gives():
    brick = bricks.CORE["answer_class"]
    code = graphblocks.python_of(brick)
    for value, settings in (
            ("OEO_00000128", {}),
            ("OEO_00000128", {"prefix": "obo"}),
            ("out:total", {"total_class": "OEO_00000010"}),
            ("out:total", {}),
            ("not a class", {}),
            (None, {}),
            ("UO_1", {"prefix_by_family": {"UO_": "obo"}}),
            ("OEO_9", {"prefix_by_family": {"UO_": "obo"}}),
            ("OEO_9", {"outside_root": {"OEO_9": "a name"}})):
        expect, got, counted, counted_too = both(brick, code, value=value,
                                                 settings=settings)
        assert got == expect and counted == counted_too, (value, settings)
    assert both(brick, code, value="OEO_00000128")[0] == [
        ("oeo:OEO_00000128", "https://example.org/oeo/OEO_00000128")]


@pytest.mark.parametrize("name,values", [
    ("decimal", (5.0, "7.25", None, 3)),
    ("whole_number", (5, "7", None, 3.0)),
    ("text", ("a", "", None, "two\nlines")),
    ("trimmed", ("  a  ", "b")),
    ("year_to_datetime", ("in 2040", "no year", None))])
def test_a_value_brick_gives_what_the_brick_gives(name, values):
    brick = bricks.CORE[name]
    code = graphblocks.python_of(brick)
    for value in values:
        expect, got, *_ = both(brick, code, value=value)
        assert got == expect, value


def test_remove_words_gives_what_the_brick_gives():
    brick = bricks.CORE["remove_words"]
    code = graphblocks.python_of(brick)
    for value, settings in (
            ("Stadtwerke Musterstadt GmbH", {"legal_forms": True}),
            ("Stadtwerke Musterstadt GmbH", {}),
            ("a (b) c", {"pattern": r"\(.*?\)", "trim": False}),
            (" ,a, ", {}),
            (None, {})):
        expect, got, *_ = both(brick, code, value=value, settings=settings)
        assert got == expect, (value, settings)
    assert both(brick, code, value="Stadtwerke GmbH",
                settings={"legal_forms": True})[0] == "Stadtwerke"


def test_a_wrong_python_is_found_by_the_comparison():
    # the comparison fails by construction for code that is not the brick's
    brick = bricks.CORE["decimal"]
    other = "def run(call):\n    return []\n"
    expect, got, *_ = both(brick, other, value=5.0)
    assert got != expect


# -- the import lines make it run as it stands -------------------------------------

def test_a_name_of_the_bricks_module_is_imported_at_the_top():
    code = graphblocks.python_of(bricks.CORE["year_to_datetime"])
    assert "from docpipe.extraction.bricks import _YEAR" in code
    expect, got, *_ = both(bricks.CORE["year_to_datetime"], code,
                           value="in 2040")
    assert got == expect == [('"2040-01-01T00:00:00"^^xsd:dateTime',
                              "2040-01-01T00:00:00")]


def test_the_code_without_its_import_lines_fails_for_a_name_of_its_module():
    brick = bricks.CORE["year_to_datetime"]
    bare = without_imports(graphblocks.python_of(brick))
    run = graphblocks.compiled(bare, {})
    with pytest.raises(NameError):
        run(Call(doc=Doc(), value="in 2040"))


def test_a_profile_brick_imports_what_its_module_has():
    code = graphblocks.python_of(PROFILES["kwp"].component(
        "kg", "BRICKS")[0])
    assert "from profiles.kwp.kg import" in code
    assert "strict_refusal" in code.split("def run")[0]
    bare = without_imports(code)
    run = graphblocks.compiled(bare, space_of("kwp"))
    with pytest.raises(NameError):
        run(Call(doc=types.SimpleNamespace(
            writer=types.SimpleNamespace(drawing=types.SimpleNamespace(
                box={"part": {}}, raw={}))), row={}, settings={}))


def test_a_name_a_block_has_is_not_imported():
    # re, literal, is_class and NOT_IN_GRAPH stand in a block's space
    for name in ("remove_words", "answer_class", "text"):
        head = graphblocks.python_of(bricks.CORE[name]).split("def run")[0]
        for have in graphblocks.BLOCK_NAMES:
            assert f"import {have}" not in head and f", {have}" not in head
