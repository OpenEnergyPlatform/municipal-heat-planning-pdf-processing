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
        If a municipality with the same name and organization ID already exists,
        the operation is ignored (ON CONFLICT DO NOTHING).
    """
    connection.execute(
        """
        INSERT INTO Municipalities (name, ags, organisation_unit)
        VALUES (?, ?, ?)
        ON CONFLICT(name, ags, organisation_unit) DO NOTHING;
        """,
        (name, ags, orga_id)
    )

def add_document(filename: str, orga_id: int, published: str, num_pages: int, added: str, connection: sqlite3.Connection) -> None:
    """
    Add a document to the database with its metadata.
    
    Args:
        filename: The name of the PDF file.
        orga_id: The ID of the organizational unit associated with the document.
        published: The publication date of the document.
        num_pages: The number of pages in the PDF document.
        added: The date when the document was added to the database.
        connection: Active SQLite database connection.
    """
    connection.execute(
        """
        INSERT INTO Documents (filename, organisation_unit, published, num_pages, added)
        VALUES (?, ?, ?, ?, ?)
        """,
        (filename, orga_id, published, num_pages, added)
    )