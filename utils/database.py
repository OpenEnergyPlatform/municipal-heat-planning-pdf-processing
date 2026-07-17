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

def document_exists(filename: str, connection: sqlite3.Connection) -> bool:
    """
    Check if a document with the given link already exists in the database.
    
    Args:
        link: The URL or file path identifier of the document.
        connection: Active SQLite database connection.
    
    Returns:
        True if the document exists in the Dokumente table, False otherwise.
    """
    cursor = connection.execute(
        """
        SELECT EXISTS(
            SELECT 1
            FROM Documents
            WHERE filename = ?
        )
        """,
        (filename,)
    )
    return bool(cursor.fetchone()[0])

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

def add_document(filename: str, orga_id: int, published: str, num_pages: int, added: str, ags: int, connection: sqlite3.Connection) -> None:
    """
    Add a document to the database with its metadata.

    Args:
        filename: The name of the PDF file.
        orga_id: The ID of the organizational unit associated with the document.
        published: The publication date of the document.
        num_pages: The number of pages in the PDF document.
        added: The date when the document was added to the database.
        ags: The municipality key (Gemeindeschlüssel) this plan belongs to —
             used to group re-published versions of the same plan.
        connection: Active SQLite database connection.
    """
    connection.execute(
        """
        INSERT INTO Documents (filename, organisation_unit, published, num_pages, added, municipality_ags)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (filename, orga_id, published, num_pages, added, ags)
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


def link_document_versions(connection: sqlite3.Connection) -> None:
    """
    Mark current vs. superseded document versions.

    Documents that share a municipality (`municipality_ags`) are versions of the
    same plan. Within each group the newest `published` date is the current
    version (`is_current=1`); every older one is marked `is_current=0` and points
    at the next-older version via `supersedes` (NULL for the oldest). Documents
    with no ags, or the only one for their ags, stay current with no predecessor.

    Idempotent: recomputes the whole grouping on every call.
    """
    from itertools import groupby

    rows = connection.execute(
        """
        SELECT id, municipality_ags, COALESCE(published, '')
        FROM Documents
        WHERE municipality_ags IS NOT NULL
        ORDER BY municipality_ags, COALESCE(published, ''), id
        """
    ).fetchall()

    for _ags, grp in groupby(rows, key=lambda r: r[1]):
        docs = list(grp)  # already oldest -> newest
        for i, (doc_id, _, _) in enumerate(docs):
            is_current = 1 if i == len(docs) - 1 else 0
            supersedes = docs[i - 1][0] if i > 0 else None
            connection.execute(
                "UPDATE Documents SET is_current = ?, supersedes = ? WHERE id = ?",
                (is_current, supersedes, doc_id),
            )