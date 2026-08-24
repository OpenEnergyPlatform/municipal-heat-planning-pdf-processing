"""
Constants for the fileprocessing module. The schema lives in docpipe/store
plus profiles/<name>/schema.sql.
"""
from pathlib import Path
from urllib.parse import urlparse

EXCEL_SHEET = "Datensatz Status quo KWP"


def link_filename(link) -> str:
    """A KWW "Link Wärmeplan" reduced to the local file name it becomes.

    Ingest names documents this way and the catalog looks them up this way, so
    the two must not drift: whoever changes it changes both at once.
    """
    return Path(urlparse(str(link).strip().lower()).path).name.lower()

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
    # KWW link 404s; the Abschlussbericht is on the municipality's own site.
    3459033: "waermeplan_wallenhorst_2025.pdf",                  # Wallenhorst
    # KWW link 404s; the Abschlussbericht is on the municipality's own site.
    3462007: "waermeplan_langeoog_20240327.pdf",                 # Langeoog
    # KWW link 404s; the plan is in the town's Ratsinfo. Not to be confused with
    # the Landkreis Friesland/Wittmund report, which is a different document.
    3462019: "waermeplan_wittmund_20251213.pdf",                 # Wittmund
    # Konvoi "NI SG Esens" (7 Gemeinden); KWW link 404s, the Abschlussbericht is
    # at daten.verwaltungsportal.de. The KWW name says 20260502, the plan and the
    # register both say 05.02.2026 — the name is kept as KWW writes it.
    3462002: "waermeplan_esens_20260502.pdf",                    # Dunum
    3462003: "waermeplan_esens_20260502.pdf",                    # Esens
    3462006: "waermeplan_esens_20260502.pdf",                    # Holtgast
    3462008: "waermeplan_esens_20260502.pdf",                    # Moorweg
    3462010: "waermeplan_esens_20260502.pdf",                    # Neuharlingersiel
    3462015: "waermeplan_esens_20260502.pdf",                    # Stedesdorf
    3462017: "waermeplan_esens_20260502.pdf",                    # Werdum
    # KWW link 404s; taken from the NRW participation portal, where it is filed
    # as the draft ("Entwurf") — the document itself is the Erläuterungsbericht.
    5970040: "waermeplan_siegen_20260618.pdf",                   # Siegen
    # Konvoi "RLP VG Langenlonsheim-Stromberg" (17 Gemeinden); KWW link 404s,
    # the Endbericht is on the Verbandsgemeinde's own site.
    7133018: "waermeplan_konvoi_vg-langenlonsheim-stromberg_20260127.pdf",  # Bretzenheim
    7133023: "waermeplan_konvoi_vg-langenlonsheim-stromberg_20260127.pdf",  # Daxweiler
    7133025: "waermeplan_konvoi_vg-langenlonsheim-stromberg_20260127.pdf",  # Dörrebach
    7133026: "waermeplan_konvoi_vg-langenlonsheim-stromberg_20260127.pdf",  # Dorsheim
    7133028: "waermeplan_konvoi_vg-langenlonsheim-stromberg_20260127.pdf",  # Eckenroth
    7133035: "waermeplan_konvoi_vg-langenlonsheim-stromberg_20260127.pdf",  # Guldental
    7133054: "waermeplan_konvoi_vg-langenlonsheim-stromberg_20260127.pdf",  # Langenlonsheim
    7133056: "waermeplan_konvoi_vg-langenlonsheim-stromberg_20260127.pdf",  # Laubenheim
    7133085: "waermeplan_konvoi_vg-langenlonsheim-stromberg_20260127.pdf",  # Roth (bei Stromberg)
    7133087: "waermeplan_konvoi_vg-langenlonsheim-stromberg_20260127.pdf",  # Rümmelsheim
    7133091: "waermeplan_konvoi_vg-langenlonsheim-stromberg_20260127.pdf",  # Schöneberg (Hunsrück)
    7133093: "waermeplan_konvoi_vg-langenlonsheim-stromberg_20260127.pdf",  # Schweppenhausen
    7133095: "waermeplan_konvoi_vg-langenlonsheim-stromberg_20260127.pdf",  # Seibersbach
    7133103: "waermeplan_konvoi_vg-langenlonsheim-stromberg_20260127.pdf",  # Stromberg
    7133108: "waermeplan_konvoi_vg-langenlonsheim-stromberg_20260127.pdf",  # Waldlaubersheim
    7133110: "waermeplan_konvoi_vg-langenlonsheim-stromberg_20260127.pdf",  # Warmsroth
    7133114: "waermeplan_konvoi_vg-langenlonsheim-stromberg_20260127.pdf",  # Windesheim
    # KWW link 404s; the Fachgutachten is on the town's own site. The register
    # has no convoy for Mayen even though the report calls itself one.
    7137068: "waermeplan_mayen_20260114.pdf",                    # Mayen
    # KWW link 404s; the Fachgutachten is on the town's own site. Same case as
    # Mayen: a convoy report, but the register lists Bendorf on its own.
    7137203: "waermeplan_bendorf_20260430.pdf",                  # Bendorf
    # Konvoi "RLP VG Maifeld" (18 Gemeinden); KWW link 404s, the plan is on the
    # Verbandsgemeinde's own site.
    7137023: "waermeplan_konvoi_vg-maifeld_20260311.pdf",        # Einig
    7137027: "waermeplan_konvoi_vg-maifeld_20260311.pdf",        # Gappenach
    7137029: "waermeplan_konvoi_vg-maifeld_20260311.pdf",        # Gering
    7137030: "waermeplan_konvoi_vg-maifeld_20260311.pdf",        # Gierschnach
    7137041: "waermeplan_konvoi_vg-maifeld_20260311.pdf",        # Kalt
    7137048: "waermeplan_konvoi_vg-maifeld_20260311.pdf",        # Kerben
    7137053: "waermeplan_konvoi_vg-maifeld_20260311.pdf",        # Kollig
    7137065: "waermeplan_konvoi_vg-maifeld_20260311.pdf",        # Lonnig
    7137070: "waermeplan_konvoi_vg-maifeld_20260311.pdf",        # Mertloch
    7137080: "waermeplan_konvoi_vg-maifeld_20260311.pdf",        # Naunheim
    7137086: "waermeplan_konvoi_vg-maifeld_20260311.pdf",        # Ochtendung
    7137087: "waermeplan_konvoi_vg-maifeld_20260311.pdf",        # Pillig
    7137089: "waermeplan_konvoi_vg-maifeld_20260311.pdf",        # Polch
    7137095: "waermeplan_konvoi_vg-maifeld_20260311.pdf",        # Rüber
    7137102: "waermeplan_konvoi_vg-maifeld_20260311.pdf",        # Trimbs
    7137112: "waermeplan_konvoi_vg-maifeld_20260311.pdf",        # Welling
    7137114: "waermeplan_konvoi_vg-maifeld_20260311.pdf",        # Wierschem
    7137501: "waermeplan_konvoi_vg-maifeld_20260311.pdf",        # Münstermaifeld
    # Konvoi "RLP VG Asbach" (4 Gemeinden); KWW link 404s, the Abschlussbericht
    # is on the Verbandsgemeinde's own site.
    7138003: "waermeplan_vg-asbach_20260522.pdf",                # Asbach (Westerwald)
    7138044: "waermeplan_vg-asbach_20260522.pdf",                # Neustadt (Wied)
    7138077: "waermeplan_vg-asbach_20260522.pdf",                # Windhagen
    7138080: "waermeplan_vg-asbach_20260522.pdf",                # Buchholz (Westerwald)
    # Konvoi "RLP VG Rengsdorf-Waldbreitbach" (20 Gemeinden); KWW link 404s, the
    # Endbericht is on the Verbandsgemeinde's own site.
    7138002: "waermeplan_konvoi_vg-rengsdorf-waldbreitbach_20260501.pdf",  # Anhausen
    7138005: "waermeplan_konvoi_vg-rengsdorf-waldbreitbach_20260501.pdf",  # Bonefeld
    7138006: "waermeplan_konvoi_vg-rengsdorf-waldbreitbach_20260501.pdf",  # Breitscheid (Westerwald)
    7138007: "waermeplan_konvoi_vg-rengsdorf-waldbreitbach_20260501.pdf",  # Hausen (Wied)
    7138010: "waermeplan_konvoi_vg-rengsdorf-waldbreitbach_20260501.pdf",  # Datzeroth
    7138015: "waermeplan_konvoi_vg-rengsdorf-waldbreitbach_20260501.pdf",  # Ehlscheid
    7138026: "waermeplan_konvoi_vg-rengsdorf-waldbreitbach_20260501.pdf",  # Hardert
    7138030: "waermeplan_konvoi_vg-rengsdorf-waldbreitbach_20260501.pdf",  # Hümmerich
    7138036: "waermeplan_konvoi_vg-rengsdorf-waldbreitbach_20260501.pdf",  # Kurtscheid
    7138042: "waermeplan_konvoi_vg-rengsdorf-waldbreitbach_20260501.pdf",  # Meinborn
    7138043: "waermeplan_konvoi_vg-rengsdorf-waldbreitbach_20260501.pdf",  # Melsbach
    7138047: "waermeplan_konvoi_vg-rengsdorf-waldbreitbach_20260501.pdf",  # Niederbreitbach
    7138053: "waermeplan_konvoi_vg-rengsdorf-waldbreitbach_20260501.pdf",  # Oberhonnefeld-Gierend
    7138054: "waermeplan_konvoi_vg-rengsdorf-waldbreitbach_20260501.pdf",  # Oberraden
    7138061: "waermeplan_konvoi_vg-rengsdorf-waldbreitbach_20260501.pdf",  # Rengsdorf
    7138065: "waermeplan_konvoi_vg-rengsdorf-waldbreitbach_20260501.pdf",  # Roßbach (Wied)
    7138066: "waermeplan_konvoi_vg-rengsdorf-waldbreitbach_20260501.pdf",  # Rüscheid
    7138071: "waermeplan_konvoi_vg-rengsdorf-waldbreitbach_20260501.pdf",  # Straßenhaus
    7138072: "waermeplan_konvoi_vg-rengsdorf-waldbreitbach_20260501.pdf",  # Thalhausen
    7138076: "waermeplan_konvoi_vg-rengsdorf-waldbreitbach_20260501.pdf",  # Waldbreitbach
    # Konvoi "RLP VG Wittlich Land" (45 Gemeinden); KWW link 404s, the Endbericht
    # is on the Verbandsgemeinde's own site.
    7231001: "waermeplan_konvoi_vg-wittlich-land_20260331.pdf",  # Altrich
    7231003: "waermeplan_konvoi_vg-wittlich-land_20260331.pdf",  # Arenrath
    7231007: "waermeplan_konvoi_vg-wittlich-land_20260331.pdf",  # Bergweiler
    7231009: "waermeplan_konvoi_vg-wittlich-land_20260331.pdf",  # Bettenfeld
    7231010: "waermeplan_konvoi_vg-wittlich-land_20260331.pdf",  # Binsfeld
    7231013: "waermeplan_konvoi_vg-wittlich-land_20260331.pdf",  # Bruch
    7231021: "waermeplan_konvoi_vg-wittlich-land_20260331.pdf",  # Dierfeld
    7231022: "waermeplan_konvoi_vg-wittlich-land_20260331.pdf",  # Dierscheid
    7231023: "waermeplan_konvoi_vg-wittlich-land_20260331.pdf",  # Dodenburg
    7231024: "waermeplan_konvoi_vg-wittlich-land_20260331.pdf",  # Dreis
    7231025: "waermeplan_konvoi_vg-wittlich-land_20260331.pdf",  # Eckfeld
    7231026: "waermeplan_konvoi_vg-wittlich-land_20260331.pdf",  # Eisenschmitt
    7231031: "waermeplan_konvoi_vg-wittlich-land_20260331.pdf",  # Esch (bei Wittlich)
    7231036: "waermeplan_konvoi_vg-wittlich-land_20260331.pdf",  # Gipperath
    7231037: "waermeplan_konvoi_vg-wittlich-land_20260331.pdf",  # Gladbach
    7231044: "waermeplan_konvoi_vg-wittlich-land_20260331.pdf",  # Greimerath (Eifel)
    7231046: "waermeplan_konvoi_vg-wittlich-land_20260331.pdf",  # Großlittgen
    7231049: "waermeplan_konvoi_vg-wittlich-land_20260331.pdf",  # Hasborn
    7231050: "waermeplan_konvoi_vg-wittlich-land_20260331.pdf",  # Heckenmünster
    7231051: "waermeplan_konvoi_vg-wittlich-land_20260331.pdf",  # Heidweiler
    7231053: "waermeplan_konvoi_vg-wittlich-land_20260331.pdf",  # Hetzerath
    7231062: "waermeplan_konvoi_vg-wittlich-land_20260331.pdf",  # Hupperath
    7231065: "waermeplan_konvoi_vg-wittlich-land_20260331.pdf",  # Karl
    7231069: "waermeplan_konvoi_vg-wittlich-land_20260331.pdf",  # Klausen
    7231074: "waermeplan_konvoi_vg-wittlich-land_20260331.pdf",  # Laufeld
    7231080: "waermeplan_konvoi_vg-wittlich-land_20260331.pdf",  # Manderscheid
    7231082: "waermeplan_konvoi_vg-wittlich-land_20260331.pdf",  # Meerfeld
    7231085: "waermeplan_konvoi_vg-wittlich-land_20260331.pdf",  # Minderlittgen
    7231091: "waermeplan_konvoi_vg-wittlich-land_20260331.pdf",  # Musweiler
    7231095: "waermeplan_konvoi_vg-wittlich-land_20260331.pdf",  # Niederöfflingen
    7231096: "waermeplan_konvoi_vg-wittlich-land_20260331.pdf",  # Niederscheidweiler
    7231100: "waermeplan_konvoi_vg-wittlich-land_20260331.pdf",  # Oberöfflingen
    7231101: "waermeplan_konvoi_vg-wittlich-land_20260331.pdf",  # Oberscheidweiler
    7231103: "waermeplan_konvoi_vg-wittlich-land_20260331.pdf",  # Osann-Monzel
    7231104: "waermeplan_konvoi_vg-wittlich-land_20260331.pdf",  # Pantenburg
    7231107: "waermeplan_konvoi_vg-wittlich-land_20260331.pdf",  # Platten
    7231108: "waermeplan_konvoi_vg-wittlich-land_20260331.pdf",  # Plein
    7231111: "waermeplan_konvoi_vg-wittlich-land_20260331.pdf",  # Rivenich
    7231113: "waermeplan_konvoi_vg-wittlich-land_20260331.pdf",  # Salmtal
    7231114: "waermeplan_konvoi_vg-wittlich-land_20260331.pdf",  # Schladt
    7231116: "waermeplan_konvoi_vg-wittlich-land_20260331.pdf",  # Schwarzenborn (Eifel)
    7231117: "waermeplan_konvoi_vg-wittlich-land_20260331.pdf",  # Sehlem
    7231127: "waermeplan_konvoi_vg-wittlich-land_20260331.pdf",  # Wallscheid
    7231503: "waermeplan_konvoi_vg-wittlich-land_20260331.pdf",  # Landscheid
    7231504: "waermeplan_konvoi_vg-wittlich-land_20260331.pdf",  # Niersbach
    # Konvoi "RLP VG Gerolstein" (38 Gemeinden); KWW link 404s, the
    # Abschlussbericht is on the Verbandsgemeinde's own site.
    7233002: "waermeplan_konvoi_vg-gerolstein_20260609.pdf",  # Basberg
    7233004: "waermeplan_konvoi_vg-gerolstein_20260609.pdf",  # Berlingen
    7233005: "waermeplan_konvoi_vg-gerolstein_20260609.pdf",  # Berndorf
    7233007: "waermeplan_konvoi_vg-gerolstein_20260609.pdf",  # Birgel
    7233019: "waermeplan_konvoi_vg-gerolstein_20260609.pdf",  # Dohm-Lammersdorf
    7233022: "waermeplan_konvoi_vg-gerolstein_20260609.pdf",  # Esch (bei Gerolstein)
    7233023: "waermeplan_konvoi_vg-gerolstein_20260609.pdf",  # Feusdorf
    7233026: "waermeplan_konvoi_vg-gerolstein_20260609.pdf",  # Gerolstein
    7233028: "waermeplan_konvoi_vg-gerolstein_20260609.pdf",  # Gönnersdorf (Eifel)
    7233029: "waermeplan_konvoi_vg-gerolstein_20260609.pdf",  # Hillesheim (Eifel)
    7233033: "waermeplan_konvoi_vg-gerolstein_20260609.pdf",  # Hohenfels-Essingen
    7233035: "waermeplan_konvoi_vg-gerolstein_20260609.pdf",  # Jünkerath
    7233036: "waermeplan_konvoi_vg-gerolstein_20260609.pdf",  # Kalenborn-Scheuern
    7233038: "waermeplan_konvoi_vg-gerolstein_20260609.pdf",  # Kerpen (Eifel)
    7233041: "waermeplan_konvoi_vg-gerolstein_20260609.pdf",  # Lissendorf
    7233050: "waermeplan_konvoi_vg-gerolstein_20260609.pdf",  # Neroth
    7233053: "waermeplan_konvoi_vg-gerolstein_20260609.pdf",  # Oberbettingen
    7233054: "waermeplan_konvoi_vg-gerolstein_20260609.pdf",  # Oberehe-Stroheich
    7233056: "waermeplan_konvoi_vg-gerolstein_20260609.pdf",  # Pelm
    7233058: "waermeplan_konvoi_vg-gerolstein_20260609.pdf",  # Rockeskyll
    7233060: "waermeplan_konvoi_vg-gerolstein_20260609.pdf",  # Salm
    7233076: "waermeplan_konvoi_vg-gerolstein_20260609.pdf",  # Üxheim
    7233080: "waermeplan_konvoi_vg-gerolstein_20260609.pdf",  # Walsdorf (Eifel)
    7233083: "waermeplan_konvoi_vg-gerolstein_20260609.pdf",  # Wiesbaum
    7233204: "waermeplan_konvoi_vg-gerolstein_20260609.pdf",  # Birresborn
    7233209: "waermeplan_konvoi_vg-gerolstein_20260609.pdf",  # Densborn
    7233211: "waermeplan_konvoi_vg-gerolstein_20260609.pdf",  # Duppach
    7233214: "waermeplan_konvoi_vg-gerolstein_20260609.pdf",  # Hallschlag
    7233219: "waermeplan_konvoi_vg-gerolstein_20260609.pdf",  # Kerschenbach
    7233223: "waermeplan_konvoi_vg-gerolstein_20260609.pdf",  # Kopp
    7233227: "waermeplan_konvoi_vg-gerolstein_20260609.pdf",  # Mürlenbach
    7233229: "waermeplan_konvoi_vg-gerolstein_20260609.pdf",  # Nohn
    7233232: "waermeplan_konvoi_vg-gerolstein_20260609.pdf",  # Ormont
    7233235: "waermeplan_konvoi_vg-gerolstein_20260609.pdf",  # Reuth
    7233237: "waermeplan_konvoi_vg-gerolstein_20260609.pdf",  # Scheid
    7233239: "waermeplan_konvoi_vg-gerolstein_20260609.pdf",  # Schüller
    7233240: "waermeplan_konvoi_vg-gerolstein_20260609.pdf",  # Stadtkyll
    7233241: "waermeplan_konvoi_vg-gerolstein_20260609.pdf",  # Steffeln
    # Konvoi "RLP VG Kirchheimbolanden" (16 Gemeinden); KWW link 404s, the
    # Abschlussbericht is on the Verbandsgemeinde's own site.
    7333005: "waermeplan_konvoi_vg-kirchheimbolanden_20260115.pdf",  # Bennhausen
    7333007: "waermeplan_konvoi_vg-kirchheimbolanden_20260115.pdf",  # Bischheim
    7333010: "waermeplan_konvoi_vg-kirchheimbolanden_20260115.pdf",  # Bolanden
    7333013: "waermeplan_konvoi_vg-kirchheimbolanden_20260115.pdf",  # Dannenfels
    7333022: "waermeplan_konvoi_vg-kirchheimbolanden_20260115.pdf",  # Gauersheim
    7333031: "waermeplan_konvoi_vg-kirchheimbolanden_20260115.pdf",  # Ilbesheim
    7333035: "waermeplan_konvoi_vg-kirchheimbolanden_20260115.pdf",  # Jakobsweiler
    7333039: "waermeplan_konvoi_vg-kirchheimbolanden_20260115.pdf",  # Kirchheimbolanden
    7333040: "waermeplan_konvoi_vg-kirchheimbolanden_20260115.pdf",  # Kriegsfeld
    7333045: "waermeplan_konvoi_vg-kirchheimbolanden_20260115.pdf",  # Marnheim
    7333046: "waermeplan_konvoi_vg-kirchheimbolanden_20260115.pdf",  # Mörsfeld
    7333047: "waermeplan_konvoi_vg-kirchheimbolanden_20260115.pdf",  # Morschheim
    7333056: "waermeplan_konvoi_vg-kirchheimbolanden_20260115.pdf",  # Oberwiesen
    7333057: "waermeplan_konvoi_vg-kirchheimbolanden_20260115.pdf",  # Orbis
    7333062: "waermeplan_konvoi_vg-kirchheimbolanden_20260115.pdf",  # Rittersheim
    7333076: "waermeplan_konvoi_vg-kirchheimbolanden_20260115.pdf",  # Stetten (Pfalz)
    # Konvoi "RLP VG Lingenfeld" (6 Gemeinden); KWW link 404s, the
    # Abschlussbericht is on the Verbandsgemeinde's own site.
    7334006: "waermeplan_konvoi_vg-lingenfeld_20260601.pdf",  # Freisbach
    7334017: "waermeplan_konvoi_vg-lingenfeld_20260601.pdf",  # Lingenfeld
    7334018: "waermeplan_konvoi_vg-lingenfeld_20260601.pdf",  # Lustadt
    7334028: "waermeplan_konvoi_vg-lingenfeld_20260601.pdf",  # Schwegenheim
    7334032: "waermeplan_konvoi_vg-lingenfeld_20260601.pdf",  # Weingarten (Pfalz)
    7334033: "waermeplan_konvoi_vg-lingenfeld_20260601.pdf",  # Westheim (Pfalz)
    # KWW link 404s; the Endbericht is on the municipality's own site.
    7338004: "waermeplan_bobenheim-roxheim_20260309.pdf",       # Bobenheim-Roxheim
    # KWW link 404s; the report is on the municipality's climate-protection site.
    7339009: "waermeplan_budenheim_20260226.pdf",                # Budenheim
    # KWW link 404s; the Abschlussbericht is in the town's Sitzungsdienst. The
    # other two members of Konvoi "BW Weissach" have no public link at all.
    8115050: "waermeplan_weil-der-stadt_20260503.pdf",           # Weil der Stadt
    # KWW link 404s; taken from the town's own site, where the only version on
    # offer carries the marking ENTWURF.
    8415053: "waermeplan_muensingen_20260316.pdf",               # Münsingen
    # KWW link 404s; the plan is on the town's own site.
    9173147: "waermeplan_wolfratshausen_20260708.pdf",           # Wolfratshausen
    # KWW link 404s; the Endfassung is on the municipality's own site.
    9181121: "waermeplan_fuchstal_20250901.pdf",                 # Fuchstal
    # KWW link 404s. The August 2026 export has since split the two links
    # (Baden 20260401, Oberbayern 20251101), but both still serve the SAME
    # bytes, and those bytes are the Kinzigtal report. We keep the file the
    # corpus already holds; Oberbayern's claim on it is settled in
    # SHARED_FILE_OWNERS.
    8317046: "waermeplan_hofstetten_20251101.pdf",               # Hofstetten (Baden)
    # KWW link 404s; the plan is on the municipality's own site.
    9181140: "waermeplan_schwifting_20251030.pdf",               # Schwifting
    # KWW link 404s; the plan is on the municipality's own site.
    9181141: "waermeplan_puergen_20250527.pdf",                  # Pürgen
    # KWW link 404s; the Endbericht is on the town's own site.
    9184119: "waermeplan_garching_20251201.pdf",                 # Garching b.München
    # KWW link 404s; the Abschlussbericht is on the town's own site.
    9184123: "waermeplan_haar_20250801.pdf",                     # Haar
    # KWW link 404s; the plan is on the municipality's own site.
    9184130: "waermeplan_ismaning_20260226.pdf",                 # Ismaning
    # KWW link 404s; the report is on the municipality's own site.
    9184134: "waermeplan_oberhaching_20260227.pdf",              # Oberhaching
    # KWW link 404s; the report is on the municipality's own site.
    9186125: "waermeplan_gerolsbach_20250606.pdf",               # Gerolsbach
    # KWW link 404s; the Abschlussbericht is on the municipality's own site.
    9186139: "waermeplan_muenchsmuenster_20260301.pdf",          # Münchsmünster
    # KWW link 404s; the report is at daten2.verwaltungsportal.de. KWW names
    # this one "Waermeplanung_", not "Waermeplan_" — kept as they write it.
    9186116: "waermeplanung_ernsgaden_20260301.pdf",             # Ernsgaden
    # KWW link 404s; the municipality serves the PDF straight off a page URL
    # with no .pdf suffix.
    9186144: "waermeplan_poernbach_20260312.pdf",                # Pörnbach
    # KWW link 404s; the Abschlussbericht is on the town's own site.
    9187117: "waermeplan_bad-aibling_20260201.pdf",              # Bad Aibling
    # KWW link 404s; the Abschlussbericht is on the municipality's own site.
    9187169: "waermeplan_rohrdorf_20250401.pdf",                 # Rohrdorf (am Inn)
    # KWW link 404s; the Abschlussbericht is at daten2.verwaltungsportal.de.
    9187179: "waermeplan_tuntenhausen_20250531.pdf",             # Tuntenhausen
    # KWW link 404s; served straight off a page URL with no .pdf suffix.
    9188113: "waermeplan_berg_20260312.pdf",                     # Berg (Starnberger See)
    # KWW link 404s; the Endbericht is on the municipality's own site.
    9189111: "waermeplan_altenmarkt_20250729.pdf",               # Altenmarkt a.d.Alz
    # Konvoi "BY Metten und Offenberg"; KWW link 404s, the Endbericht is on the
    # market town's own site.
    9271132: "waermeplan_markt-metten-und-offenberg_20251201.pdf",  # Metten
    9271140: "waermeplan_markt-metten-und-offenberg_20251201.pdf",  # Offenberg
    # Konvoi "BY Ilzer Land" (12 Gemeinden); KWW link 404s, the Abschlussbericht
    # is in the ILE's Nextcloud share.
    9272120: "waermeplan_konvoi-ilzer-land_20260301.pdf",  # Grafenau
    9272140: "waermeplan_konvoi-ilzer-land_20260301.pdf",  # Ringelai
    9272141: "waermeplan_konvoi-ilzer-land_20260301.pdf",  # Röhrnbach
    9272142: "waermeplan_konvoi-ilzer-land_20260301.pdf",  # Saldenburg
    9272116: "waermeplan_konvoi-ilzer-land_20260301.pdf",  # Eppenschlag
    9272128: "waermeplan_konvoi-ilzer-land_20260301.pdf",  # Innernzell
    9272145: "waermeplan_konvoi-ilzer-land_20260301.pdf",  # Schöfweg
    9272147: "waermeplan_konvoi-ilzer-land_20260301.pdf",  # Schönberg (Niederbayern)
    9272150: "waermeplan_konvoi-ilzer-land_20260301.pdf",  # Thurmansbang
    9272119: "waermeplan_konvoi-ilzer-land_20260301.pdf",  # Fürsteneck
    9272138: "waermeplan_konvoi-ilzer-land_20260301.pdf",  # Perlesreut
    9275128: "waermeplan_konvoi-ilzer-land_20260301.pdf",  # Hutthurm
    # Konvoi "BY Abteiland" (8 Gemeinden); KWW link 404s. Careful: jandelsbrunn.de
    # serves a same-day report for that one municipality — this is the ILE-wide
    # one from abteiland.de, which covers all eight.
    9272129: "waermeplan_konvoi-abteiland-jandelsbrunn_20260527.pdf",  # Jandelsbrunn
    9272136: "waermeplan_konvoi-abteiland-jandelsbrunn_20260527.pdf",  # Neureichenau
    9272151: "waermeplan_konvoi-abteiland-jandelsbrunn_20260527.pdf",  # Waldkirchen
    9275118: "waermeplan_konvoi-abteiland-jandelsbrunn_20260527.pdf",  # Breitenberg (Niederbayern)
    9275126: "waermeplan_konvoi-abteiland-jandelsbrunn_20260527.pdf",  # Hauzenberg
    9275137: "waermeplan_konvoi-abteiland-jandelsbrunn_20260527.pdf",  # Obernzell
    9275148: "waermeplan_konvoi-abteiland-jandelsbrunn_20260527.pdf",  # Sonnen
    9275150: "waermeplan_konvoi-abteiland-jandelsbrunn_20260527.pdf",  # Thyrnau
    # --- Aus dem Lauf vom 2026-08-07: 40 tote KWW-Links plus Regensburg,
    # dessen KWW-PDF ein Scan ohne Textebene ist. Ersatz jeweils von der
    # Kommune, dem Planer (waermeplan.net) oder verwaltungsportal.de.
    13072012: "waermeplan_amt_rostocker_heide.pdf",  # Bentwisch
    13072015: "waermeplan_amt_rostocker_heide.pdf",  # Blankenhagen
    13072032: "waermeplan_amt_rostocker_heide.pdf",  # Gelbensande
    13072072: "waermeplan_amt_rostocker_heide.pdf",  # Mönchhagen
    13072088: "waermeplan_amt_rostocker_heide.pdf",  # Rövershagen
    9674120: "waermeplan_bundorf_20250601.pdf",  # Bundorf
    9674121: "waermeplan_burgpreppach_20250601.pdf",  # Burgpreppach
    9377116: "waermeplan_erbendorf_20260218.pdf",  # Erbendorf
    9674223: "waermeplan_ermershausen_20250601.pdf",  # Ermershausen
    9371122: "waermeplan_freudenberg_20260416.pdf",  # Freudenberg (Oberpfalz)
    9371123: "waermeplan_gebenbach_20260416.pdf",  # Gebenbach
    15086055: "waermeplan_gommern_20250328.pdf",  # Gommern
    12067201: "waermeplan_gruenheide__mark__20251009.pdf",  # Grünheide (Mark)
    9371126: "waermeplan_hahnbach_20260416.pdf",  # Hahnbach
    10045114: "waermeplan_homburg_20260512.pdf",  # Homburg
    9571111: "waermeplan_konvoi-adelshofen_mittelfranken__20260301.pdf",  # Adelshofen (Mittelfranken)
    9471111: "waermeplan_konvoi-allianz-regnitz-aisch_20260223.pdf",  # Altendorf (Kreis Bamberg)
    9471123: "waermeplan_konvoi-allianz-regnitz-aisch_20260223.pdf",  # Buttenheim
    9474123: "waermeplan_konvoi-allianz-regnitz-aisch_20260223.pdf",  # Eggolsheim
    9474133: "waermeplan_konvoi-allianz-regnitz-aisch_20260223.pdf",  # Hallerndorf
    9276116: "waermeplan_konvoi-gruener-dreiberg_20251124.pdf",  # Bischofsmais
    9276126: "waermeplan_konvoi-gruener-dreiberg_20251124.pdf",  # Kirchberg i.Wald
    9276127: "waermeplan_konvoi-gruener-dreiberg_20251124.pdf",  # Kirchdorf i.Wald
    9276139: "waermeplan_konvoi-gruener-dreiberg_20251124.pdf",  # Rinchnach
    9272143: "waermeplan_konvoi-nationalparkgemeinden_20251001.pdf",  # Sankt Oswald-Riedlhütte
    9272146: "waermeplan_konvoi-nationalparkgemeinden_20251001.pdf",  # Neuschönau
    9272149: "waermeplan_konvoi-nationalparkgemeinden_20251001.pdf",  # Spiegelau
    9276115: "waermeplan_konvoi-nationalparkgemeinden_20251001.pdf",  # Bayerisch Eisenstein
    9276121: "waermeplan_konvoi-nationalparkgemeinden_20251001.pdf",  # Frauenau
    9276130: "waermeplan_konvoi-nationalparkgemeinden_20251001.pdf",  # Lindberg
    9571188: "waermeplan_konvoi-ohrenbach_20260301.pdf",  # Ohrenbach
    9571205: "waermeplan_konvoi-steinsfeld_20260301.pdf",  # Steinsfeld
    9278140: "waermeplan_konvoi-strasskirchen-und-irlbach_20250930.pdf",  # Irlbach
    9278192: "waermeplan_konvoi-strasskirchen-und-irlbach_20250930.pdf",  # Straßkirchen
    9474132: "waermeplan_konvoi-suedliche-fraenkische-schweiz_20260301.pdf",  # Gräfenberg
    9474138: "waermeplan_konvoi-suedliche-fraenkische-schweiz_20260301.pdf",  # Hiltpoltstein
    9474140: "waermeplan_konvoi-suedliche-fraenkische-schweiz_20260301.pdf",  # Igensdorf
    9474173: "waermeplan_konvoi-suedliche-fraenkische-schweiz_20260301.pdf",  # Weißenohe
    9575113: "waermeplan_konvoi-vg-diespeck_20260301.pdf",  # Baudenbach
    9575118: "waermeplan_konvoi-vg-diespeck_20260301.pdf",  # Diespeck
    9575128: "waermeplan_konvoi-vg-diespeck_20260301.pdf",  # Gutenstetten
    9575150: "waermeplan_konvoi-vg-diespeck_20260301.pdf",  # Münchsteinach
    9375131: "waermeplan_konvoi-vg-kallmuenz-duggendorf_20260301..pdf",  # Duggendorf
    9375153: "waermeplan_konvoi-vg-kallmuenz-holzheim-am-forst_20260301..pdf",  # Holzheim a.Forst
    9375156: "waermeplan_konvoi-vg-kallmuenz-kallmuenz_20260301.pdf",  # Kallmünz
    9475174: "waermeplan_konvoi-vg-sparneck_20260407.pdf",  # Sparneck
    9475184: "waermeplan_konvoi-vg-sparneck_20260407.pdf",  # Weißdorf
    15087275: "waermeplan_mansfeld-suedharz_20251101.pdf",  # Mansfeld
    14729270: "waermeplan_markranstaedt_20250825.pdf",  # Markranstädt
    9371121: "waermeplan_markt-freihung_20260416.pdf",  # Freihung
    9375170: "waermeplan_mintraching_20250731.pdf",  # Mintraching
    9371141: "waermeplan_neukirchen-bei-sulzbach-rosenberg_20260101.pdf",  # Neukirchen b.Sulzbach-Rosenberg
    9678164: "waermeplan_oberschwarzach_20251014.pdf",  # Oberschwarzach
    9777158: "waermeplan_pforzen_20250926.pdf",  # Pforzen
    9371144: "waermeplan_poppenricht_20260416.pdf",  # Poppenricht
    9362000: "waermeplan_regensburg_20260429.pdf",  # Regensburg
    16073076: "waermeplan_rudolstadt_202506.pdf",  # Rudolstadt
    12061444: "waermeplan_schulzendorf_2025.pdf",  # Schulzendorf
    9677116: "waermeplan_vg-burgsinn-aura-im-sinngrund_20260301.pdf",  # Aura i.Sinngrund
    9677122: "waermeplan_vg-burgsinn-burgsinn_20260301.pdf",  # Burgsinn
    9677128: "waermeplan_vg-burgsinn-fellen_20260301.pdf",  # Fellen
    9677159: "waermeplan_vg-burgsinn-mittelsinn_20260301.pdf",  # Mittelsinn
    9677169: "waermeplan_vg-burgsinn-obersinn_20260301.pdf",  # Obersinn
    15088216: "waermeplan_wettin-loebejuen_20250724.pdf",  # Wettin-Löbejün
    9674139: "warmeplan_vg_theres_20260225.pdf",  # Gädheim
    9674180: "warmeplan_vg_theres_20260225.pdf",  # Theres
    9674219: "warmeplan_vg_theres_20260225.pdf",  # Wonfurt
    # KWW gave these three the link of a DIFFERENT town (see SHARED_FILE_OWNERS).
    # Their own plans, verified by the town named in the document:
    8216007: "waermeplan_buehl_20251016.pdf",                    # Bühl (nicht Greding)
    3252007: "waermeplan_hessisch-oldendorf_20251216.pdf",       # Hessisch Oldendorf (nicht Oldenburg)
    8215090: "waermeplan_weingarten-baden_20231113.pdf",         # Weingarten (Baden) (nicht Ravensburg)
}

# Files the register hands to several municipalities that are NOT a convoy: KWW
# pasted one town's link into another town's row. Keyed by the local filename →
# the Gemeindeschlüssel of the municipality the document actually belongs to,
# read off the document itself. Without this the version grouping would have to
# guess, and the guess is wrong as often as not. The OTHER municipality still
# has no plan of its own here — it needs its real link.
SHARED_FILE_OWNERS = {
    # "KOMMUNALE WÄRMEPLANUNG für die Stadt Greding"; Bühl (8216007) not named once.
    "waermeplan_greding_20251016.pdf": 9576122,        # Greding
    # "Abschlussbericht für die Stadt Oldenburg"; Hessisch Oldendorf (3252007) absent.
    "waermeplan_oldenburg_20251112.pdf": 3403000,      # Oldenburg (Oldb)
    # Weingarten 190x, Ravensburg 63x, Karlsruhe 0x → the Württemberg one,
    # not Weingarten (Baden) (8215090).
    "waermeplan_weingarten_20231113.pdf": 8436082,     # Weingarten (Ravensburg)
    # "Gemeinde Hofstetten im Kinzigtal", Konvoiführer Haslach i.K. — Baden.
    # Hofstetten (Oberbayern) (9181124) is 600 km away and is not named in it;
    # its KWW row simply points at this file. It has no plan of its own here.
    "waermeplan_hofstetten_20251101.pdf": 8317046,     # Hofstetten (Baden)
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

