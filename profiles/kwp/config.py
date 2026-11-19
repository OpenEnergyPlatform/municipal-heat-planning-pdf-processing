"""
Constants for the fileprocessing module. The schema lives in docpipe/store
plus profiles/<name>/schema.sql.
"""
import json
from pathlib import Path
from urllib.parse import urlparse

EXCEL_SHEET = "Datensatz Status quo KWP"


def link_filename(link) -> str:
    """A KWW "Link Wärmeplan" reduced to the local file name it becomes.

    Ingest names documents this way and the catalog looks them up this way, so
    the two must not drift: whoever changes it changes both at once.
    """
    return Path(urlparse(str(link).strip().lower()).path).name.lower()

# The exceptions of the register, each a data file of this profile that the
# editor shows and edits (owner request 2026-11-19, A2), every entry with the
# municipality it is about ("place") and why it is there ("why"):
#
# - pdf_overrides.json: municipalities whose KWW PDF link is broken and for
#   which a correct PDF was sourced by hand, by Gemeindeschlüssel -> the local
#   file ("file") to use instead of the KWW link. The file must be placed in
#   the data dir by hand; it is never downloaded. A file KWW renamed is held to
#   the name it is registered under the same way.
# - shared_file_owners.json: files the register hands to several
#   municipalities that are NOT a convoy (KWW pasted one town's link into
#   another town's row), by local file -> the Gemeindeschlüssel of the
#   municipality the document belongs to ("owner"), read off the document.
#   Without it the version grouping would have to guess. The OTHER
#   municipality still has no plan of its own here; it needs its real link.
PDF_OVERRIDES_PATH = Path(__file__).with_name("pdf_overrides.json")
SHARED_FILE_OWNERS_PATH = Path(__file__).with_name("shared_file_owners.json")


def _entries(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


PDF_OVERRIDES = {int(key): entry["file"]
                 for key, entry in _entries(PDF_OVERRIDES_PATH).items()}
SHARED_FILE_OWNERS = {name: entry["owner"] for name, entry
                      in _entries(SHARED_FILE_OWNERS_PATH).items()}

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

