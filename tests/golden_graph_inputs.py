"""The fixed rows the golden graph tests serialize, and how they are serialized.

Synthetic: no plan and no publication is quoted here. The rows are built to
reach every small tool the two graph writers share: a name with and without a
legal form, a quote with quotation marks, a backslash and a line break, a
sub-area whose own name carries quotation marks, a text over several lines, a
comment longer than a comment line is allowed to be, and every way two
readings of one identity are settled.
"""
import sqlite3
from pathlib import Path

LONG_QUOTE = ("Der Endenergieverbrauch " + "der Gebäude steigt " * 30
              + "und fällt danach wieder.")


def kwp_database(tmp_path: Path) -> Path:
    db = tmp_path / "kwp.db"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE Documents (id INTEGER PRIMARY KEY, filename TEXT,
                                published TEXT, is_current INTEGER,
                                page_text_transcribed INTEGER);
        CREATE TABLE DocumentMeta (document INTEGER, municipality_ags TEXT);
        CREATE TABLE Municipalities (ags TEXT, name TEXT);
        INSERT INTO Documents VALUES (857, 'plan_kassel.pdf',
                                      '20240315', 1, 0);
        INSERT INTO DocumentMeta VALUES (857, '06611000');
        INSERT INTO Documents VALUES (1082, 'plan_ohne_textebene.pdf',
                                      '2025-09-01', 1, 96);
        INSERT INTO DocumentMeta VALUES (1082, '13074053');
        INSERT INTO Municipalities VALUES ('06611000', 'Kassel');
        INSERT INTO Municipalities VALUES ('13074053', 'Grevesmühlen "Nord"');
    """)
    conn.commit()
    conn.close()
    return db


def kwp_row(**overrides) -> dict:
    row = {"kind": "tuple", "parameter": "energy_consumption", "value": 241000,
           "value_target": 241.0, "unit_raw": "kWh/a",
           "quantity": "OEO_00050016", "quantity_raw": "Endenergieverbrauch",
           "carrier": "OEO_00000292", "carrier_raw": "Erdgas", "sector": None,
           "year": 2030, "aggregation": "OEO_00140070",
           "aggregation_state": "derived", "aggregation_raw": "kWh/a",
           "scenario": "target", "spatial_scope": "municipality",
           "tier": "text_located", "quote": "| Erdgas | 241.000 |",
           "provenance": {"document_id": 857, "page": 12,
                          "owner_kind": "table", "owner_id": 5,
                          "title": "Endenergie"}}
    row.update(overrides)
    return row


def kwp_office(label: str) -> dict:
    return {"kind": "tuple", "parameter": "planning_organisation",
            "value": label, "quote": label, "tier": "text_located",
            "provenance": {"document_id": 857}}


def kwp_rows_kassel() -> list:
    return [
        kwp_row(quote='Erdgas "241.000" \\ kWh/a\nzweite Zeile',
                flags=["quote_repaired"]),
        kwp_row(scenario="status_quo", year=2022, value_target=120.0,
                sector="OEO_00000214", quote=LONG_QUOTE),
        kwp_row(scenario="trend", year=2035, carrier="OEO_00000132",
                value_target=77.0, compute="a + b", tier="visual_source",
                flags=["computed"]),
        kwp_row(spatial_scope="sub_area", value_target=7.0,
                spatial_scope_raw='Eignungsgebiet "Bad Dürrheim Nord"'),
        kwp_row(spatial_scope="sub_area", value_target=8.0, year=2040,
                spatial_scope_raw="Nordstadt (Süd)"),
        # one identity, two numbers, one wording: nothing stays
        kwp_row(year=2041, sector="OEO_00000405", value_target=10.0,
                sector_raw="Gebäude"),
        kwp_row(year=2041, sector="OEO_00000405", value_target=20.0,
                sector_raw="Gebäude"),
        # one number said twice, once rounded: the precise one stays
        kwp_row(year=2045, carrier="OEO_00000139", value=1626000,
                value_target=1626.0, carrier_raw="Strom"),
        kwp_row(year=2045, carrier="OEO_00000139", value=1600000,
                value_target=1600.0, carrier_raw="Strom"),
        # two numbers the plan words differently: a node each, by wording
        kwp_row(year=2050, sector="OEO_00000405", value_target=5.0,
                sector_raw="Öffentliche Gebäude"),
        kwp_row(year=2050, sector="OEO_00000405", value_target=6.0,
                sector_raw="Wirtschaftlich genutzte Gebäude"),
        # two numbers, one wording, a lower trust level loses
        kwp_row(year=2055, value_target=3.0, year_state="exhausted"),
        kwp_row(year=2055, value_target=4.0),
        kwp_office("Kassel Wärme Ingenieurbüro GmbH"),
        kwp_office("kassel wärme ingenieurbüro"),
        kwp_office("EGS-Plan e.V."),
        # left out, each for its own reason
        kwp_row(quantity=None, quantity_raw="Endenergiebedarf"),
        kwp_row(year=None), kwp_row(aggregation=None),
        kwp_row(scenario="out:variant"),
        kwp_row(spatial_scope="sub_area", spatial_scope_raw=""),
    ]


def kwp_rows_transcribed() -> list:
    row = kwp_row(provenance={"document_id": 1082, "page": 3,
                           "owner_kind": "section", "owner_id": 8},
               value_target=55.0, quote="Strom 55 GWh")
    return [row, kwp_office("Kassel Wärme Ingenieurbüro"),
            kwp_office("Stadtwerke Grevesmühlen AG")]


def kwp_graph(tmp_path: Path) -> tuple:
    """(the graph's Turtle, the provenance of its values) of two documents.

    The provenance is what is written per document; the vocabulary's header
    above it is another test's."""
    from docpipe.extraction import provenance
    from profiles.kwp import kg
    serializer = kg.make_serializer(kwp_database(tmp_path))
    writer = provenance.Writer(kg.PROVENANCE["base"], kg.PROVENANCE)
    parts = []
    for name, rows in (("plan_kassel", kwp_rows_kassel()),
                       ("plan_ohne_textebene", kwp_rows_transcribed())):
        parts.append(serializer(name, rows))
        writer.add(name, serializer.claims.pop(name), {},
                   transcribed=name == "plan_ohne_textebene")
    return "\n".join(parts), "\n".join(writer.parts)


def scenarios_database(tmp_path: Path) -> Path:
    db = tmp_path / "ar6.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        "CREATE TABLE Documents (id INTEGER PRIMARY KEY, filename TEXT);"
        "CREATE TABLE DocumentMeta (document INTEGER, title TEXT, year "
        "INTEGER, doi TEXT);"
        "CREATE TABLE Scenarios (id INTEGER PRIMARY KEY, ar6_id INTEGER,"
        " name TEXT);"
        "CREATE TABLE DocumentScenarios (document INTEGER, scenario INTEGER);"
        "INSERT INTO Documents VALUES (1, 'outlook_2050.pdf');"
        "INSERT INTO Scenarios VALUES (1, 42, 'CurPol');"
        "INSERT INTO Scenarios VALUES (2, 43, 'EN_NPi2020_300f');"
        "INSERT INTO Scenarios VALUES (3, 44, 'EN_NPi2020_400');"
        "INSERT INTO DocumentScenarios VALUES (1, 1);"
        "INSERT INTO DocumentScenarios VALUES (1, 2);"
        "INSERT INTO DocumentScenarios VALUES (1, 3);")
    conn.commit()
    conn.close()
    return db


REGION = "https://openenergyplatform.org/ontology/oekg/region/Germany"
TYPE = "https://openenergyplatform.org/ontology/oeo/OEO_00020311"
SECTOR = "https://openenergyplatform.org/ontology/oeo/OEO_00000367"


def scenarios_row(parameter, value, **extra) -> dict:
    row = {"parameter": parameter, "value": value,
           "quote": f"the document says {value}", "tier": "text_located",
           "provenance": {"page": 4, "owner_kind": "section", "owner_id": 4}}
    row.update(extra)
    return row


def scenarios_rows() -> list:
    where = {"page": 9, "owner_kind": "table", "owner_id": 3,
             "rects": [[10.0, 20.0, 110.5, 40.25]]}
    return [
        scenarios_row("publication_title", 'The "Net Zero" Pathways \\ Outlook 2050',
                      quote='The "Net Zero" Pathways \\ Outlook 2050'),
        scenarios_row("publication_title", 'The "Net Zero" Pathways'),
        scenarios_row("publication_author", "Meyer, A."),
        scenarios_row("publication_author", "Oeko-Institut"),
        scenarios_row("publication_author", "Oeko-Institut e.V."),
        scenarios_row("publication_date", "2024"),
        scenarios_row("publication_doi", "10.1234/outlook.2050"),
        scenarios_row("publication_abstract",
                      'This report says "yes"\nand then goes on.\nA third line.'),
        scenarios_row("study_organisation", "Beta Research"),
        scenarios_row("study_organisation", "Beta Research Ltd."),
        scenarios_row("study_organisation", "Gamma Inc"),
        scenarios_row("study_funder", "Horizon 2020"),
        scenarios_row("study_funder", "ACME GmbH"),
        scenarios_row("study_project_name", "Pathways Assessment Project"),
        scenarios_row("study_acronym", "PAP"),
        scenarios_row("study_sector", "Verkehr", value_uri=SECTOR,
                      flags=["mapped:sector"]),
        scenarios_row("study_descriptor", "Nonsense", value_uri="out:other"),
        scenarios_row("study_technology", "Fusion"),
        scenarios_row("scenario_label", "CurPol", value_uri="CurPol",
                      value_raw="Current Policies",
                      quote="the Current Policies scenario (CurPol)",
                      provenance=where),
        scenarios_row("scenario_label", "NPi", value_uri="EN_NPi2020_300f",
                      value_raw="NPi", quote="the NPi scenario"),
        scenarios_row("scenario_type", "Referenz", value_uri=TYPE, scenario="CurPol",
                      scenario_raw="Current Policies"),
        scenarios_row("scenario_region", "Deutschland", value_uri=REGION,
                      scenario="CurPol", scenario_raw="Current Policies",
                      flags=["quote_repaired"]),
        scenarios_row("scenario_region", "Welt", value_uri="out:global",
                      scenario="CurPol", scenario_raw="Current Policies"),
        scenarios_row("scenario_year", "2050", scenario="CurPol",
                      scenario_raw="Current Policies"),
        scenarios_row("scenario_year", "bis 2070", scenario="CurPol",
                      scenario_raw="Current Policies"),
        scenarios_row("scenario_abstract", "assumes no additional policies",
                      scenario="CurPol", scenario_raw="Current Policies",
                      quote="CurPol assumes no additional policies\nat all"),
        scenarios_row("scenario_year", "2030", scenario="out:family",
                      scenario_raw="Something Else", scenario_state="exhausted"),
        scenarios_row("scenario_year", "2040", scenario_state="exhausted"),
    ]


def scenarios_graph(tmp_path: Path, evidence: bool) -> str:
    from profiles.scenarios import kg
    saved = kg.EVIDENCE
    kg.EVIDENCE = evidence
    here = tmp_path / ("evidence" if evidence else "comments")
    here.mkdir()
    try:
        serializer = kg.make_serializer(scenarios_database(here))
        return serializer("outlook_2050", scenarios_rows())
    finally:
        kg.EVIDENCE = saved
