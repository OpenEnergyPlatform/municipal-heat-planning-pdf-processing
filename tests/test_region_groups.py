"""A group of countries a scenario covers is written as its member countries,
its passage cited; the world as every country, "several regions" as none. A
member is placed on an OEKG region by its label or the same words in another
order, and one nothing places is counted AND never guessed; a group label that
is a country's is no group. A document is offered the groups it names, a
region of the AR6 database by its bare name where it names the family too."""
from pathlib import Path

from rdflib import Graph, URIRef

from profiles.scenarios import extraction, kg, vocabulary
from test_graph_from_shapes import OEO, oekg

REGION = "https://openenergyplatform.org/ontology/oekg/region/"
REGIONS = {REGION + "France": ["France"], REGION + "Spain": ["Spain"],
           REGION + "Moldova": ["Moldova (the Republic of)"],
           REGION + "Micronesia": ["Micronesia"]}
FAMILIES = [[{"R10": [{"Europe (R10)": {"ar6": "R10EUROPE",
                                        "countries": ["France", "Spain",
                                                      "Atlantis"]}},
                      "Other (R10)"]}]]
TREE = [{"geoAreaCode": "1", "geoAreaName": "World", "type": "Region",
         "children": [
             {"geoAreaCode": "151", "geoAreaName": "Eastern Europe",
              "type": "Region", "children": [
                  {"geoAreaCode": "498", "geoAreaName": "Republic of Moldova",
                   "type": "Country"}]},
             {"geoAreaCode": "57", "geoAreaName": "Micronesia",
              "type": "Region", "children": [
                  {"geoAreaCode": "583", "geoAreaName": "Micronesia",
                   "type": "Country"}]}]}]


def test_a_group_holds_the_regions_its_members_name_and_counts_the_rest():
    groups, missing = vocabulary.aggregates(FAMILIES, TREE, REGIONS)
    europe = groups["aggregate:iiasa:Europe (R10)"]
    assert europe["members"] == [REGION + "France", REGION + "Spain"]
    assert europe["labels"] == ["Europe (R10)", "R10EUROPE"]
    assert missing["member Atlantis"] == 1
    assert groups["aggregate:m49:151"]["members"] == [REGION + "Moldova"]
    assert "aggregate:m49:57" not in groups
    assert missing["label Micronesia is a country"] == 1
    assert sorted(groups[vocabulary.WORLD]["members"]) == sorted(REGIONS)


GROUPS = {"aggregate:iiasa:Europe (R10)": {
    "labels": ["Europe (R10)"], "members": [REGION + "France",
                                            REGION + "Spain"]}}


def regions_written(*uris):
    rows = [{"parameter": "publication_title", "value": "A Study",
             "quote": "A Study"},
            {"parameter": "scenario_label", "value": "NDC", "value_uri": "NDC",
             "value_raw": "NDC", "quote": "the NDC scenario"}]
    rows += [{"parameter": "scenario_region", "value": uri, "value_uri": uri,
              "value_raw": "Europe", "scenario": "NDC", "scenario_raw": "NDC",
              "quote": "NDC covers Europe"} for uri in uris]
    serializer = kg.make_serializer(Path("no-such.db"), model=oekg(),
                                    groups=GROUPS)
    text = serializer("doc", rows)
    graph = Graph().parse(data=text, format="turtle")
    return {str(o) for o in graph.objects(
        predicate=URIRef(OEO + "OEO_00020220"))}, text


def test_a_group_is_written_as_its_members_and_an_out_entry_as_none():
    written, text = regions_written("aggregate:iiasa:Europe (R10)")
    assert written == {REGION + "France", REGION + "Spain"}
    assert "NDC covers Europe" in text
    assert regions_written("out:multiregion")[0] == set()


def offered(monkeypatch, text):
    monkeypatch.setattr(extraction, "_document_text", lambda conn, i: text)
    monkeypatch.setattr(extraction, "_regions", lambda: REGIONS)
    groups, _ = vocabulary.aggregates(FAMILIES, TREE, REGIONS)
    monkeypatch.setattr(extraction, "aggregates", lambda: groups)
    return set(extraction.document_regions(None, 1))


def test_a_document_is_offered_the_world_and_the_groups_it_names(monkeypatch):
    named = offered(monkeypatch, "The R10 regions: Europe leads.")
    assert {extraction.WORLD, "aggregate:iiasa:Europe (R10)"} <= named
    bare = offered(monkeypatch, "Europe leads.")
    assert extraction.WORLD in bare
    assert "aggregate:iiasa:Europe (R10)" not in bare
