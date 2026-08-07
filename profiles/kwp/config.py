"""
Constants for the fileprocessing module. The schema lives in docpipe/store
plus profiles/<name>/schema.sql.
"""

EXCEL_SHEET = "Datensatz Status quo KWP"

# Municipalities whose KWW PDF link is broken and for which a correct PDF was
# sourced by hand. Keyed by Gemeindeschlüssel → the local filename to use
# instead of the KWW link. The file must be placed in the data dir by hand; it
# is never downloaded. (Previously the "Ersetzte Datei" column in our own copy
# of the Excel; the KWW export does not carry it.)
PDF_OVERRIDES = {
    1051011: "waermeplan_brunsbuettel_20241210.pdf",             # Brunsbüttel
    1051072: "waermeplan_marne_20241104.pdf",                    # Marne
    1053032: "waermeplan_geesthacht_20241230.pdf",              # Geesthacht
    1061046: "waermeplan_itzehoe_20240930.pdf",                  # Itzehoe
    3352011: "waermeplan_cuxhaven_20251106.pdf",                 # Cuxhaven
    3359038: "waermeplan_stade_20250327_komprimierte_version.pdf",  # Stade
    7143041: "waermeplan_selters_20250711.pdf",                  # Krümmel
    7143044: "waermeplan_selters_20250711.pdf",                  # Marienrachdorf
    7143045: "waermeplan_selters_20250711.pdf",                  # Maroth
    7143046: "waermeplan_selters_20250711.pdf",                  # Maxsain
    7143056: "waermeplan_selters_20250711.pdf",                  # Nordhofen
    7143064: "waermeplan_selters_20250711.pdf",                  # Rückeroth
    7143066: "waermeplan_selters_20250711.pdf",                  # Schenkelberg
    7143067: "waermeplan_selters_20250711.pdf",                  # Selters (Westerwald)
    7143085: "waermeplan_selters_20250711.pdf",                  # Wölferlingen
    8116012: "waermeplan_bissingen_an_der_teck_2024q1.pdf",      # Bissingen an der Teck
    # Amt Haddeby (Konvoi, 8 Gemeinden): the KWW link 404s; the plan is published
    # at daten.verwaltungsportal.de as "Bericht_KWP_Haddeby_Versand_komprimiert".
    # Kept under the KWW name so the convoy marker and the date survive.
    1059012: "waermeplan_konvoi_amt_haddeby_20250606.pdf",       # Borgwedel
    1059018: "waermeplan_konvoi_amt_haddeby_20250606.pdf",       # Busdorf
    1059019: "waermeplan_konvoi_amt_haddeby_20250606.pdf",       # Dannewerk
    1059026: "waermeplan_konvoi_amt_haddeby_20250606.pdf",       # Fahrdorf
    1059032: "waermeplan_konvoi_amt_haddeby_20250606.pdf",       # Geltorf
    1059043: "waermeplan_konvoi_amt_haddeby_20250606.pdf",       # Jagel
    1059056: "waermeplan_konvoi_amt_haddeby_20250606.pdf",       # Lottorf
    1059078: "waermeplan_konvoi_amt_haddeby_20250606.pdf",       # Selk
    # KWW link 404s; the plan is published on the municipality's own site.
    3157001: "waermeplan_edemissen_20250923.pdf",                # Edemissen
    # Konvoi NI13 (Bad Sachsa und Walkenried); KWW link 404s, the plan comes
    # from the town's own site.
    3159004: "waermeplan_bad_sachsa_20250725.pdf",               # Bad Sachsa
    3159036: "waermeplan_bad_sachsa_20250725.pdf",               # Walkenried
    # KWW link 404s; the Erläuterungsbericht is on the town's own site.
    3252003: "waermeplan_bad-pyrmont_20260701.pdf",              # Bad Pyrmont
    # KWW link 404s; the Erläuterungsbericht is on the Stadtwerke's site.
    3257031: "waermeplan_rinteln_20260529.pdf",                  # Rinteln
    # Konvoi "NI SG Nenndorf" (4 Gemeinden); KWW link 404s, the Abschlussbericht
    # is on the Samtgemeinde's own site.
    3257006: "waermeplan_sg-nenndorf_20251218.pdf",              # Bad Nenndorf
    3257011: "waermeplan_sg-nenndorf_20251218.pdf",              # Haste
    3257016: "waermeplan_sg-nenndorf_20251218.pdf",              # Hohnhorst
    3257036: "waermeplan_sg-nenndorf_20251218.pdf",              # Suthfeld
    # Konvoi "NI SG Elbmarsch" (3 Gemeinden); KWW link 404s (and ends in
    # ".pdf.pdf"), the Abschlussbericht is on klimaschutz-elbmarsch.de.
    3353007: "waermeplan_elbmarsch_20250801.pdf",                # Drage (Elbe)
    3353023: "waermeplan_elbmarsch_20250801.pdf",                # Marschacht
    3353033: "waermeplan_elbmarsch_20250801.pdf",                # Tespe
    # KWW link 404s; the Abschlussbericht is on the municipality's own site.
    # The KWW name carries no date, so neither does ours.
    3356002: "waermeplan_grasberg.pdf",                          # Grasberg
    # KWW link 404s; the Abschlussbericht is on the municipality's own site.
    3356011: "waermeplan_worpswede_20250829.pdf",                # Worpswede
}

# KWW Excel columns carried into the MunicipalityMeta table, as
# (excel_column, db_column, sqltype). Excludes the identity columns already
# modelled elsewhere (Gemeindename, Gemeindeschlüssel), the KWW-internal
# workflow fields ("Eintrag durch", "Information von KuKs; Quellen und weitere
# Anmerkungen") and the "VG Schlüssel für Formel" helper (identical to
# Verbandsschlüssel). All numeric columns are whole-valued → INTEGER.
MUNICIPALITY_META_COLUMNS = [
    ("Verbandsschlüssel", "verbandsschluessel", "INTEGER"),
    ("Landkreisschlüssel", "landkreisschluessel", "INTEGER"),
    ("Amtlicher Regionalschlüssel (ARS)", "ars", "INTEGER"),
    ("Bundesland kurz", "bundesland_kurz", "TEXT"),
    ("Bundesland lang", "bundesland_lang", "TEXT"),
    ("Verbandsname", "verbandsname", "TEXT"),
    ("Verbandstyp", "verbandstyp", "TEXT"),
    ("Landkreis", "landkreis", "TEXT"),
    ("Textkennzeichen", "textkennzeichen", "TEXT"),
    ("NKI-Förderung", "nki_foerderung", "TEXT"),
    ("Konvoi ID", "konvoi_id", "TEXT"),
    ("Konvoimitgliedschaft", "konvoimitgliedschaft", "TEXT"),
    ("Stand in der KWP", "stand_in_der_kwp", "TEXT"),
    ("Einwohnendenzahl nach GVZ", "einwohnendenzahl_gvz", "INTEGER"),
    ("Einwohnergröße", "einwohnergroesse", "INTEGER"),
    ("Größe nach WPG", "groesse_nach_wpg", "TEXT"),
    ("Gemeindefläche in km²", "gemeindeflaeche_km2", "INTEGER"),
    ("Bevölkerungsdichte", "bevoelkerungsdichte", "INTEGER"),
    ("Link Wärmeplan", "link_waermeplan", "TEXT"),
    ("Datum der Veröffentlichung", "datum_veroeffentlichung", "DATE"),
    ("Jahr der Veröffentlichung", "jahr_veroeffentlichung", "INTEGER"),
    ("Dienstleister", "dienstleister", "TEXT"),
    # KWW renamed this in the August 2026 export and it now ships a real
    # date rather than "19.06.2025".
    ("Aktualität", "aktualitaet", "DATE"),
    ("vereinfachtes Verfahren", "vereinfachtes_verfahren", "TEXT"),
    ("Verkürzte KWP", "verkuerzte_kwp", "TEXT"),
    ("PVS ID", "pvs_id", "INTEGER"),
    ("Verbandsangehörigkeit", "verbandsangehoerigkeit", "TEXT"),
    ("Anzahl Mitgliedsgemeinden", "anzahl_mitgliedsgemeinden", "INTEGER"),
    ("EW Verbandsgemeinden", "ew_verbandsgemeinden", "INTEGER"),
]

