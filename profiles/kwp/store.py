"""
store.py – The project's own tables: organisations, municipalities and
their KWW metadata. The core never touches these.

Author: Felix Vossel
"""
import sqlite3


def update_organisation_unit(name: str, state: str, connection: sqlite3.Connection) -> int:
    """
    Update or create an organizational unit (Organisationseinheiten) and return its ID.
    
    Args:
        name: The name of the organizational unit.
        bundesland: The federal state (Bundesland) to which the organization belongs.
        connection: Active SQLite database connection.
    
    Returns:
        The ID of the organizational unit (either newly created or existing).
    
    Note:
        If an organizational unit with the same name and federal state already exists,
        its ID is returned without creating a duplicate.
    """
    results = connection.execute(
        """
        INSERT INTO OrganisationUnits (name, state)
        VALUES (?, ?)
        ON CONFLICT(name, state) DO NOTHING
        RETURNING id;
        """,
        (name, state)
    )

    row = results.fetchone()
    if row is not None:
        orga_id = row[0]
    else:
        row = connection.execute(
            """
            SELECT id FROM OrganisationUnits
            WHERE name = ? AND state = ?
            """,
            (name, state)
        ).fetchone()
        orga_id = row[0]

    return orga_id

def add_municipality(name: str, ags: str, orga_id: int, connection: sqlite3.Connection) -> None:
    """
    Add a municipality (Gemeinden) to the database.
    
    Args:
        name: The name of the municipality.
        orga_id: The ID of the associated organizational unit.
        connection: Active SQLite database connection.
    
    Note:
        ags is the municipality's unique key; on a re-run the existing row is
        refreshed (ON CONFLICT(ags) DO UPDATE), so name / organisation_unit
        follow the latest Excel without tripping the UNIQUE(ags) constraint.
    """
    connection.execute(
        """
        INSERT INTO Municipalities (name, ags, organisation_unit)
        VALUES (?, ?, ?)
        ON CONFLICT(ags) DO UPDATE SET
            name = excluded.name,
            organisation_unit = excluded.organisation_unit
        """,
        (name, ags, orga_id)
    )

def ensure_municipality_meta_table(columns: list, connection: sqlite3.Connection) -> None:
    """
    Create the MunicipalityMeta table if absent. Idempotent (additive migration
    for DBs that predate it).

    `columns` is a list of (excel_column, db_column, sqltype) triples; only
    db_column + sqltype are used here. sqltype "DATE" maps to TEXT (ISO string).
    Keyed by `ags` (FK to Municipalities.ags — one metadata row per municipality).
    """
    defs = ",\n".join(
        f'    "{db}" {"TEXT" if t == "DATE" else t}' for _, db, t in columns
    )
    connection.execute(
        f'CREATE TABLE IF NOT EXISTS "MunicipalityMeta" (\n'
        f'    "ags" INTEGER PRIMARY KEY '
        f'REFERENCES "Municipalities"("ags") ON DELETE CASCADE,\n{defs}\n)'
    )

def upsert_municipality_meta(ags: int, values: dict, connection: sqlite3.Connection) -> None:
    """
    Insert or replace the metadata row for `ags`. `values` maps db_column → value
    (already coerced; None for missing). On a re-run the row is refreshed, so the
    metadata follows the latest Excel.
    """
    cols = list(values.keys())
    assignments = ", ".join(f'"{c}" = excluded."{c}"' for c in cols)
    placeholders = ", ".join(["?"] * (len(cols) + 1))
    quoted = ", ".join(f'"{c}"' for c in ["ags"] + cols)
    connection.execute(
        f'INSERT INTO MunicipalityMeta ({quoted}) VALUES ({placeholders}) '
        f'ON CONFLICT(ags) DO UPDATE SET {assignments}',
        [ags] + [values[c] for c in cols],
    )
