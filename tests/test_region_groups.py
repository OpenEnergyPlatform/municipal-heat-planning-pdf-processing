"""A group of countries a scenario covers is written as its member countries,
its passage cited; the world as every country, "several regions" as none. A
member is placed on an OEKG region by its label or the same words in another
order, and one nothing places is counted AND never guessed; a group label that
is a country's is no group. A document is offered the groups it names, a
region of the IAM community by its bare name where it names the family too.
A model's region is its countries under its name and the codes its mapping
gives it, as the newest version of the model defines it, AND it is offered
only where the paper names the model with its capitals, AND a label two
offered groups share stays with the region of the paper's model or with none;
a World Bank group is its economies AND EU28 is the World Bank's Union and the
United Kingdom, AND the World Bank's sheet is read by its column names. A
member is found with its accents and its source's abbreviations undone, AND by
the words before its comma only where one region's labels hold them all; two
World Bank groups take the short forms a paper writes. "&" and "and" spell one
label, AND a group's code and name joined name the group, AND a country's
labels are not joined. The remap maps a stored wording onto the document's own
list, which the spec alone does not hold, AND leaves a document whose lists
cannot be closed alone, AND maps a wording the spelling rules make."""
import io
import zipfile
from pathlib import Path

from rdflib import Graph, URIRef

from profiles.scenarios import extraction, vocabulary
from test_graph_from_shapes import OEO, make_serializer

REGION = "https://openenergyplatform.org/ontology/oekg/region/"
REGIONS = {REGION + "France": ["France"], REGION + "Spain": ["Spain"],
           REGION + "Moldova": ["Moldova (the Republic of)"],
           REGION + "Micronesia": ["Micronesia"]}
FAMILIES = [[{"R10": [{"Europe (R10)": {"countries": ["France", "Spain",
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
    assert europe["labels"] == ["Europe (R10)"]
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
    serializer = make_serializer(Path("no-such.db"), groups=GROUPS)
    text = serializer("doc", rows)
    graph = Graph().parse(data=text, format="turtle")
    return {str(o) for o in graph.objects(
        predicate=URIRef(OEO + "OEO_00020220"))}, text


def test_a_group_is_written_as_its_members_and_an_unlisted_one_as_printed():
    written, text = regions_written("aggregate:iiasa:Europe (R10)")
    assert written == {REGION + "France", REGION + "Spain"}
    assert "NDC covers Europe" in text
    # A group the list lacks is a study region of its own, named as printed
    # (owner decision 2026-11-07), never the members of a nearby group.
    (one,) = regions_written("out:multiregion")[0]
    assert one.startswith(REGION) and one not in written
    assert "rdfs:label \"Europe\"" in regions_written("out:multiregion")[1]


def offered(monkeypatch, text, families=FAMILIES, codes=None):
    monkeypatch.setattr(extraction, "_document_text", lambda conn, i: text)
    monkeypatch.setattr(extraction, "_regions", lambda: REGIONS)
    groups, _ = vocabulary.aggregates(families, TREE, REGIONS, codes)
    monkeypatch.setattr(extraction, "aggregates", lambda: groups)
    return set(extraction.document_regions(None, 1))


def test_a_document_is_offered_the_world_and_the_groups_it_names(monkeypatch):
    named = offered(monkeypatch, "The R10 regions: Europe leads.")
    assert {extraction.WORLD, "aggregate:iiasa:Europe (R10)"} <= named
    bare = offered(monkeypatch, "Europe leads.")
    assert extraction.WORLD in bare
    assert "aggregate:iiasa:Europe (R10)" not in bare


# A model of two versions, the older one first: the newer one's region holds
# Spain too, so keeping the file order would keep the wrong one.
MODELS = [[{"EPPA 7": [{"EPPA 7|South": {"countries": ["France"]}}]}],
          [{"EPPA 8": [{"EPPA 8|South": {"countries": ["France", "Spain"]}},
                       {"EPPA 8|Western Europe": {"countries": "France"}}]}],
          [{"REMIND 3.0": [{"REMIND 3.0|South": {"countries": ["Spain"]}}]}]]
CODES = {"EPPA 7|South": ["SOU"], "EPPA 8|South": ["SOU"],
         "REMIND 3.0|South": ["SOU"]}
EPPA_SOUTH = "aggregate:iiasa:EPPA 8|South"
REMIND_SOUTH = "aggregate:iiasa:REMIND 3.0|South"


def test_a_models_region_is_its_countries_as_its_newest_version_has_them():
    groups, _ = vocabulary.aggregates(MODELS, [], REGIONS, CODES)
    south = groups[EPPA_SOUTH]
    assert south["members"] == [REGION + "France", REGION + "Spain"]
    assert south["labels"] == ["South", "SOU"]
    assert "EPPA" in south["named_by"]
    assert "aggregate:iiasa:EPPA 7|South" not in groups
    assert groups["aggregate:iiasa:EPPA 8|Western Europe"]["members"] == [
        REGION + "France"]
    newer = sorted(["X 4.10", "X 4.9"], key=vocabulary._version_key)
    assert newer == ["X 4.9", "X 4.10"]


def test_a_models_region_is_offered_where_the_paper_names_the_model(
        monkeypatch):
    named = offered(monkeypatch, "EPPA splits the world; SOU leads.",
                    MODELS, CODES)
    assert EPPA_SOUTH in named and REMIND_SOUTH not in named
    assert EPPA_SOUTH not in offered(monkeypatch, "SOU leads.", MODELS, CODES)
    assert EPPA_SOUTH not in offered(monkeypatch, "In eppa terms SOU leads.",
                                     MODELS, CODES)


def test_a_shared_label_stays_with_the_papers_model_or_with_none(monkeypatch):
    tree = [{"geoAreaCode": "1", "geoAreaName": "World", "type": "Region",
             "children": [{"geoAreaCode": "155",
                           "geoAreaName": "Western Europe", "type": "Region",
                           "children": [{"geoAreaCode": "250",
                                         "geoAreaName": "France",
                                         "type": "Country"}]}]}]
    monkeypatch.setattr(extraction, "_regions", lambda: REGIONS)
    groups, _ = vocabulary.aggregates(MODELS, tree, REGIONS, CODES)
    monkeypatch.setattr(extraction, "aggregates", lambda: groups)
    monkeypatch.setattr(extraction, "_document_text",
                        lambda conn, i: "EPPA: Western Europe grows.")
    named = set(extraction.document_regions(None, 1))
    assert "aggregate:iiasa:EPPA 8|Western Europe" in named
    assert "aggregate:m49:155" not in named
    monkeypatch.setattr(extraction, "_document_text",
                        lambda conn, i: "EPPA and REMIND agree: SOU leads.")
    both = set(extraction.document_regions(None, 1))
    assert EPPA_SOUTH not in both and REMIND_SOUTH not in both


def test_a_world_bank_group_is_its_economies_and_eu28_adds_the_uk():
    regions = {**REGIONS, REGION + "UnitedKingdom": ["United Kingdom"]}
    banks = [("EUU", "European Union", ["France", "Spain"])]
    groups, _ = vocabulary.aggregates([], [], regions, banks=banks)
    assert groups["aggregate:worldbank:EUU"]["members"] == [
        REGION + "France", REGION + "Spain"]
    assert set(groups["aggregate:EU28"]["members"]) == {
        REGION + "France", REGION + "Spain", REGION + "UnitedKingdom"}
    without, missing = vocabulary.aggregates([], [], regions)
    assert "aggregate:EU28" not in without and missing["group EU28"] == 1


def workbook(rows: list) -> io.BytesIO:
    """An xlsx file of one sheet, `compositions`, its cells shared strings."""
    strings = sorted({cell for row in rows for cell in row})
    main = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    sheet = "".join(
        f'<row r="{n + 1}">' + "".join(
            f'<c r="{chr(65 + i)}{n + 1}" t="s"><v>{strings.index(cell)}</v></c>'
            for i, cell in enumerate(row)) + "</row>"
        for n, row in enumerate(rows))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as book:
        book.writestr("xl/workbook.xml",
                      f'<workbook xmlns="{main}" xmlns:r="{rel}"><sheets>'
                      '<sheet name="List" sheetId="1" r:id="rId1"/>'
                      '<sheet name="compositions" sheetId="2" r:id="rId2"/>'
                      "</sheets></workbook>")
        book.writestr("xl/_rels/workbook.xml.rels",
                      '<Relationships xmlns="http://schemas.openxmlformats.org/'
                      'package/2006/relationships">'
                      '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/>'
                      '<Relationship Id="rId2" Target="worksheets/sheet2.xml"/>'
                      "</Relationships>")
        book.writestr("xl/sharedStrings.xml",
                      f'<sst xmlns="{main}">' + "".join(
                          f"<si><t>{s}</t></si>" for s in strings) + "</sst>")
        book.writestr("xl/worksheets/sheet1.xml",
                      f'<worksheet xmlns="{main}"><sheetData/></worksheet>')
        book.writestr("xl/worksheets/sheet2.xml",
                      f'<worksheet xmlns="{main}"><sheetData>{sheet}'
                      "</sheetData></worksheet>")
    out.seek(0)
    return out


def test_the_world_bank_sheet_is_read_by_its_column_names():
    # The economy's column stands first: read by place, it would be the code.
    book = workbook([["WB_Country_Name", "WB_Group_Code", "WB_Group_Name"],
                     ["France", "EUU", "European Union"],
                     ["Spain", "EUU", "European Union"]])
    assert vocabulary.worldbank(book) == [
        ("EUU", "European Union", ["France", "Spain"])]


def remapped(tmp_path, document, spec_for, wording="EU28"):
    """The region a stored tuple of *document* names after the remap, and
    the remap's counts. The tuple was harvested as "several regions" with
    *wording*, before the list held a group of that name."""
    import json
    from docpipe.extraction import remap, runner
    from docpipe.extraction.spec import load as load_spec
    spec = load_spec(json.loads((Path(__file__).resolve().parent.parent
                                 / "profiles" / "scenarios"
                                 / "extraction_spec.json")
                                .read_text(encoding="utf-8")))
    path = tmp_path / "doc.jsonl"
    rows = [{"kind": "tuple", "parameter": "scenario_region",
             "value": "several regions", "value_uri": "out:multiregion",
             "value_raw": wording, "quote": f"{wording} cuts its emissions"},
            {"kind": "summary", "document_id": document}]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n",
                    encoding="utf-8")
    current = runner._stamp_current("spec", "", spec)
    stats = remap.remap_file(path, spec, current,
                             spec_for and (lambda d: spec_for(spec, d)))
    stored = [json.loads(line) for line in path.read_text(
        encoding="utf-8").splitlines() if line.strip()]
    return stored[0]["value_uri"], stats


def own_lists(spec, document):
    """Document 7's own lists hold EU28; document 8's cannot be closed."""
    from docpipe.extraction import runner
    if document != 7:
        return None
    return runner.fill_dynamic_axes(spec, {"scenario_region": {
        "aggregate:EU28": ["EU28", "EU-28"],
        "out:multiregion": ["several regions"]}})


def test_the_remap_maps_a_wording_onto_the_documents_own_list(tmp_path):
    from docpipe.extraction.fields import LISTS_UNREADABLE
    assert remapped(tmp_path, 7, own_lists)[0] == "aggregate:EU28"
    # Against the spec alone the document's list is not there.
    assert remapped(tmp_path, 7, None)[0] == "out:multiregion"
    region, stats = remapped(tmp_path, 8, own_lists)
    assert region == "out:multiregion" and stats[LISTS_UNREADABLE] == 1


PLACES = {REGION + "Congo": ["Congo", "Republic of the Congo"],
          REGION + "CongoDemocraticRepublicOf": [
              "Democratic Republic of the Congo"],
          REGION + "Egypt": ["Egypt"],
          REGION + "SaoTomeAndPrincipe": ["Sao Tome and Principe"],
          REGION + "SaintLucia": ["Saint Lucia"],
          REGION + "KoreaRepublicOf": ["Republic of Korea"],
          REGION + "KoreaDemocraticPeoplesRepublicOf": ["North Korea"]}


def members_of(names):
    groups, missing = vocabulary.aggregates([], [], PLACES,
                                            banks=[("T", "Test", names)])
    return (groups.get("aggregate:worldbank:T") or {}).get("members", []),         missing


def test_a_member_is_found_with_its_accents_and_abbreviations_undone():
    found, _ = members_of([u"São Tomé and Príncipe", "St. Lucia"])
    assert found == [REGION + "SaoTomeAndPrincipe", REGION + "SaintLucia"]


def test_the_words_before_a_comma_find_a_member_one_region_holds():
    found, _ = members_of(["Egypt, Arab Rep.", "Congo, Dem. Rep.",
                           "Congo, Rep."])
    assert found == [REGION + "Egypt", REGION + "CongoDemocraticRepublicOf",
                     REGION + "Congo"]
    # Two regions hold "Korea" and the whole name is no label of either.
    none, missing = members_of(["Korea, Dem. People's Rep."])
    assert none == [] and missing["member Korea, Dem. People's Rep."] == 1


def test_two_world_bank_groups_take_the_short_forms_a_paper_writes():
    banks = [("EUU", "European Union", ["France"]),
             ("OED", "OECD members", ["Spain"]),
             ("EMU", "Euro area", ["France"])]
    groups, _ = vocabulary.aggregates([], [], REGIONS, banks=banks)
    assert groups["aggregate:worldbank:EUU"]["labels"] == [
        "European Union", "EU"]
    assert groups["aggregate:worldbank:OED"]["labels"] == ["OECD members",
                                                           "OECD"]
    assert groups["aggregate:worldbank:EMU"]["labels"] == ["Euro area"]


def test_and_and_the_ampersand_spell_one_label():
    assert "Middle East and North Africa" in extraction.spellings(
        ["Middle East & North Africa"])
    assert "Trinidad & Tobago" in extraction.spellings(["Trinidad and Tobago"])
    assert extraction.spellings(["Andorra"]) == ["Andorra"]


def test_a_groups_code_and_name_joined_name_it_and_a_countrys_are_not():
    joined = set(extraction.spellings(["Latin America", "LAM"], True))
    assert {"LAM (Latin America)", "Latin America (LAM)",
            "LAM - Latin America"} <= joined
    assert "LAM (Asia)" not in joined
    assert extraction.spellings(["United States", "USA"]) == [
        "United States", "USA"]


def test_a_wording_the_rules_make_is_offered_and_remapped(monkeypatch,
                                                          tmp_path):
    from docpipe.extraction import runner
    banks = [("MEA", "Middle East & North Africa", ["France"])]
    groups, _ = vocabulary.aggregates(MODELS, [], REGIONS, CODES, banks)
    usa = REGION + "UnitedStates"
    monkeypatch.setattr(extraction, "_regions",
                        lambda: {**REGIONS, usa: ["United States", "USA"]})
    monkeypatch.setattr(extraction, "aggregates", lambda: groups)
    monkeypatch.setattr(extraction, "_document_text", lambda conn, i: (
        "In EPPA, SOU (South), the USA and the Middle East and North Africa "
        "grow."))
    own = extraction.document_regions(None, 1)
    assert {"aggregate:worldbank:MEA", EPPA_SOUTH} <= set(own)
    assert own[usa] == ["United States", "USA"]

    def lists(spec, document):
        return runner.fill_dynamic_axes(spec, {"scenario_region": {
            **own, "out:multiregion": ["several regions"]}})
    assert remapped(tmp_path, 1, lists, "SOU (South)")[0] == EPPA_SOUTH
    assert remapped(tmp_path, 1, lists, "Middle East and North Africa")[0]         == "aggregate:worldbank:MEA"
    # Two names of two entries name neither.
    assert remapped(tmp_path, 1, lists,
                    "SOU (Middle East & North Africa)")[0] == "out:multiregion"
