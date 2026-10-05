"""The small tools both graph writers share, and what they write with them.

What is promised: the two profile writers take their UUID building, their name
folding, their Turtle text and NOT_IN_GRAPH from one module of the core
(`docpipe/extraction/graphkit.py`), AND every IRI and every byte of Turtle
they write is what it was before the tools moved there. The second half is
held against text written down before the move (`tests/golden/`), generated
from the code as it was, over rows built to reach every tool.
"""
import re
import uuid
from pathlib import Path

import pytest

from docpipe.extraction import graph, graphkit
from tests import golden_graph_inputs as inputs

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = Path(__file__).resolve().parent / "golden"
BASE = "https://graph.test/id/"


def _golden(name: str) -> str:
    return (GOLDEN / name).read_text(encoding="utf-8")


def _definitions(text: str) -> int:
    return len(re.findall(r"^NOT_IN_GRAPH\s*=", text, flags=re.M))


# ----------------------------------------------------------- NOT_IN_GRAPH

def test_not_in_graph_is_defined_once_for_the_core_and_both_profiles():
    from profiles.kwp import kg as kwp
    from profiles.scenarios import kg as scenarios
    found = {}
    for root in ("docpipe", "profiles"):
        for path in (ROOT / root).rglob("*.py"):
            count = _definitions(path.read_text(encoding="utf-8"))
            if count:
                found[path.relative_to(ROOT).as_posix()] = count
    assert found == {"docpipe/extraction/graphkit.py": 1}
    assert kwp.NOT_IN_GRAPH is graphkit.NOT_IN_GRAPH
    assert scenarios.NOT_IN_GRAPH is graphkit.NOT_IN_GRAPH
    assert graphkit.NOT_IN_GRAPH == "out:"


def test_the_definition_count_can_see_a_second_definition():
    assert _definitions("NOT_IN_GRAPH = 'out:'\nNOT_IN_GRAPH = 'out:'\n") == 2
    assert _definitions("x = NOT_IN_GRAPH\n") == 0


# ---------------------------------------------------------------- the UUID

def test_an_identifier_is_the_uuid5_of_namespace_collection_and_name():
    namespace = graphkit.base_namespace(BASE)
    by_hand = str(uuid.uuid5(uuid.uuid5(uuid.uuid5(
        uuid.NAMESPACE_URL, BASE), "value"), "a|b"))
    assert graphkit.mint_uuid(namespace, "value", "a|b") == by_hand


def test_an_identifier_moves_with_each_of_its_three_parts():
    namespace = graphkit.base_namespace(BASE)
    here = graphkit.mint_uuid(namespace, "value", "a|b")
    assert graphkit.mint_uuid(graphkit.base_namespace(BASE + "x/"),
                              "value", "a|b") != here
    assert graphkit.mint_uuid(namespace, "organisation", "a|b") != here
    assert graphkit.mint_uuid(namespace, "value", "a|c") != here


def test_the_two_writers_mint_what_they_minted():
    """kwp hashes the name as given; scenarios folds it first."""
    from profiles.kwp import kg as kwp
    from profiles.scenarios import kg as scenarios
    assert kwp.mint("value", "a|b") == (
        f"{kwp.BASE}value/" + graphkit.mint_uuid(
            graphkit.base_namespace(kwp.BASE), "value", "a|b"))
    assert kwp.mint("organisation", "A") != kwp.mint("organisation", "a")
    assert scenarios.mint("organisation", "Beta Research Ltd.") \
        == scenarios.mint("organisation", "beta research")
    assert scenarios.mint("organisation", "Beta Research") \
        != scenarios.mint("author", "Beta Research")
    assert scenarios.mint("studyreport", "T").startswith(
        scenarios.BASE + "publication/")


# ----------------------------------------------------------- the name fold

def test_the_shared_fold_strips_a_legal_form_only_where_it_is_told_to():
    assert graphkit.normalise("  Beta   Research, INC. ") == "beta research inc"
    assert graphkit.normalise("Beta Research Inc", "(inc)") == "beta research"
    # a form that is not in the list stays, which is why the lists stay per
    # profile: one shared list would re-mint the organisations of the other
    assert graphkit.normalise("Beta Research Inc", "(ltd)") \
        == "beta research inc"
    # only at the end, and only as a word of its own
    assert graphkit.normalise("Inc Research", "(inc)") == "inc research"
    assert graphkit.normalise("Beta Reinc", "(inc)") == "beta reinc"


def test_the_legal_forms_stay_with_each_profile():
    from profiles.kwp import kg as kwp
    from profiles.scenarios import kg as scenarios
    assert kwp.normalise("Beta Research Inc") == "beta research inc"
    assert scenarios.normalise("Beta Research Inc") == "beta research"
    assert kwp.normalise("Beta Research Ltd.") == "beta research ltd"
    assert scenarios.normalise("Beta Research Ltd.") == "beta research"
    for fold in (kwp.normalise, scenarios.normalise):
        assert fold("Kassel Wärme Ingenieurbüro GmbH") \
            == "kassel wärme ingenieurbüro"
        assert fold("EGS-Plan e.V.") == "egs plan"


# -------------------------------------------------------------- the Turtle

def test_a_comment_is_one_flattened_line_cut_at_its_limit():
    line = graphkit.ttl_comment('a "quoted"\n   passage\twith\r\nbreaks')
    assert line == '# a "quoted" passage with breaks'
    assert "\n" not in line and "\r" not in line
    assert graphkit.ttl_comment("x", indent="    ") == "    # x"
    long = graphkit.ttl_comment("word " * 400)
    assert len(long) == len("# ") + graphkit.COMMENT_LIMIT
    assert graphkit.ttl_comment(None) == "# "


def test_a_single_line_literal_escapes_everything_that_would_break_it():
    text = 'say "no" \\ then\nstop\r\there'
    assert graphkit.ttl_escape(text) == (
        'say \\"no\\" \\\\ then\\nstop\\r\\there')
    assert graphkit.ttl_string(text) == f'"{graphkit.ttl_escape(text)}"'
    assert "\n" not in graphkit.ttl_string(text)


def test_the_core_writer_uses_the_shared_escape():
    assert graph.ttl_string is graphkit.ttl_string


def test_a_literal_over_several_lines_is_written_in_its_long_form():
    assert graphkit.ttl_literal('one "line"') == '"one \\"line\\""'
    long = graphkit.ttl_literal('first\r\nsecond "x"')
    assert long == '"""first\nsecond \\"x\\""""'
    assert long.startswith('"""') and long.endswith('"""')


@pytest.mark.parametrize("text", [
    'plain', 'with "quotes"', 'back\\slash', 'tab\there', 'line\nbreak',
    'Eignungsgebiet "Bad Dürrheim Nord"', 'ends with a quote"'])
def test_what_is_written_reads_back_as_the_text(text):
    rdflib = pytest.importorskip("rdflib")
    if not hasattr(rdflib.Graph, "parse"):
        pytest.skip("rdflib is a stub here")
    for write in (graphkit.ttl_string, graphkit.ttl_literal):
        loaded = rdflib.Graph().parse(
            data=f"<urn:s> <urn:p> {write(text)} .", format="turtle")
        (found,) = [str(o) for _s, _p, o in loaded]
        assert found == text


# ------------------------------------------------------ byte for byte, kwp

def test_the_kwp_graph_is_what_it_was_before_the_tools_moved(tmp_path):
    turtle, provenance = inputs.kwp_graph(tmp_path)
    assert turtle == _golden("kwp_graph.ttl")
    assert provenance == _golden("kwp_provenance.ttl")


def test_the_kwp_golden_reaches_what_it_is_there_for():
    text = _golden("kwp_graph.ttl")
    assert len(re.findall(r"^<https://openenergyplatform.org/id/mhpkg/value/",
                          text, flags=re.M)) >= 8
    # a sub-area and a municipality whose own names carry quotation marks
    assert 'rdfs:label "Eignungsgebiet \\"Bad Dürrheim Nord\\"" ;' in text
    assert 'rdfs:label "Gemeindegebiet Grevesmühlen \\"Nord\\""' in text
    # an office two plans name is one node, labelled once
    assert text.count('rdfs:label "Kassel Wärme Ingenieurbüro" .') == 1
    # every way two readings of one identity are settled
    assert "Named by the plan's wording" in text
    assert "Kept over a rounded reading" in text
    assert '"10.0"^^xsd:float' not in text and '"20.0"^^xsd:float' not in text
    # and a comment cut at its limit
    assert max(len(line) for line in text.splitlines()) \
        == len("# ") + graphkit.COMMENT_LIMIT


def test_the_kwp_comparison_sees_a_changed_identifier(tmp_path, monkeypatch):
    """A list of legal forms that lost one re-mints an office: the Turtle
    differs from the text written down, so the comparison can fail."""
    from profiles.kwp import kg as kwp
    monkeypatch.setattr(kwp, "LEGAL", r"(gmbh)")
    turtle, _provenance = inputs.kwp_graph(tmp_path)
    assert turtle != _golden("kwp_graph.ttl")


def test_the_kwp_comparison_sees_a_changed_row(tmp_path, monkeypatch):
    original = inputs.kwp_rows_kassel

    def changed():
        rows = original()
        rows[0] = dict(rows[0], value_target=242.0)
        return rows

    monkeypatch.setattr(inputs, "kwp_rows_kassel", changed)
    turtle, _provenance = inputs.kwp_graph(tmp_path)
    assert turtle != _golden("kwp_graph.ttl")


# ------------------------------------------------- byte for byte, scenarios

def test_the_scenarios_graph_is_what_it_was_before_the_tools_moved(tmp_path):
    assert inputs.scenarios_graph(tmp_path, evidence=False) \
        == _golden("scenarios_graph.ttl")


def test_the_scenarios_evidence_nodes_are_what_they_were(tmp_path):
    assert inputs.scenarios_graph(tmp_path, evidence=True) \
        == _golden("scenarios_evidence.ttl")


def test_the_scenarios_golden_reaches_what_it_is_there_for():
    text = _golden("scenarios_graph.ttl")
    assert 'dc:abstract """This report says \\"yes\\"\n' in text
    assert 'rdfs:label "The \\"Net Zero\\" Pathways \\\\ Outlook 2050"' in text
    assert text.count("a oeo:OEO_00000365 ;") == 2          # two factsheets
    assert 'dc:acronym "Current Policies" ;' in text
    assert "# confidence: C, repaired, worth checking" in text
    assert "oekgprov:" in _golden("scenarios_evidence.ttl")


def test_the_scenarios_comparison_sees_a_changed_identifier(tmp_path,
                                                            monkeypatch):
    from profiles.kwp import kg as kwp
    from profiles.scenarios import kg as scenarios
    monkeypatch.setattr(scenarios, "_LEGAL", kwp.LEGAL)
    assert inputs.scenarios_graph(tmp_path, evidence=False) \
        != _golden("scenarios_graph.ttl")


def test_the_scenarios_comparison_sees_a_changed_comment(tmp_path,
                                                         monkeypatch):
    monkeypatch.setattr(graphkit, "COMMENT_LIMIT", 20)
    assert inputs.scenarios_graph(tmp_path, evidence=False) \
        != _golden("scenarios_graph.ttl")
