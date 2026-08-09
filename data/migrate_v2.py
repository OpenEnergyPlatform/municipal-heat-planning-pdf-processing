"""
migrate_v2.py – Migrate an old KWP.db to the v2 schema (data-preserving).

The v2 schema (data/KWP.db.sql) adds foreign keys, page-provenance tables
(Pages / SectionPages / Segments) and a dedicated Embeddings table replacing
the per-row *_embedding id columns.

This builds a NEW database file from the old one and never modifies the old
DB. After verifying the result you can swap it in:

    python data/migrate_v2.py data/KWP.db data/KWP_v2.db
    # inspect data/KWP_v2.db, then:
    #   move data/KWP.db data/KWP_v1_backup.db
    #   move data/KWP_v2.db data/KWP.db

What is preserved: OrganisationUnits, Municipalities, Documents, Sections
(title/page_number), Tables, Images, and all FAISS embedding ids.
What is derived: Pages (from existing page numbers), SectionPages (one page per
old section), Embeddings (from the old *_embedding columns).
What starts empty: Segments and per-section content — populated on the next
`chunkingandembedding` run with --force.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from typing import Optional

# Old *_embedding column → (embedding_type, owner_kind) in the Embeddings table.
_SECTION_EMB = [("text_embedding", "section_text"), ("title_embedding", "section_title")]
_TABLE_EMB = [("text_embedding", "table_text"), ("image_embedding", "table_vl")]
_IMAGE_EMB = [("text_embedding", "figure_text"), ("image_embedding", "figure_vl")]


def migrate(old_db: Path, new_db: Path, schema_sql: Path) -> None:
    old_db, new_db, schema_sql = Path(old_db), Path(new_db), Path(schema_sql)
    if not old_db.exists():
        raise SystemExit(f"Old DB not found: {old_db}")
    if new_db.exists():
        raise SystemExit(f"Refusing to overwrite existing {new_db}")

    new = sqlite3.connect(new_db)
    # On ANY failure, close and delete the half-built file. `executescript`
    # below commits the schema (its own BEGIN/COMMIT), so an empty file would
    # otherwise survive and trip the overwrite guard on a corrected re-run.
    try:
        new.executescript(schema_sql.read_text(encoding="utf-8"))
        new.execute("PRAGMA foreign_keys = OFF")  # bulk load; verified at the end
        new.execute("ATTACH DATABASE ? AS old", (str(old_db),))

        # ── Master data (ids preserved) ─────────────────────────────────────
        new.execute("INSERT INTO main.OrganisationUnits SELECT id, name, state FROM old.OrganisationUnits")
        new.execute("INSERT INTO main.Municipalities SELECT id, name, ags, organisation_unit FROM old.Municipalities")
        new.execute(
            "INSERT INTO main.Documents (id, organisation_unit, filename, published, num_pages, added) "
            "SELECT id, organisation_unit, filename, published, num_pages, added FROM old.Documents"
        )

        # ── Sections (content NULL; populated on next chunking run) ──────────
        new.execute(
            "INSERT INTO main.Sections (id, document, section_number, title, content, page_number) "
            "SELECT id, document, section_number, title, NULL, page_number FROM old.Sections"
        )

        # ── Tables / Images (block_id derived from the file stem) ────────────
        for old_id, section, path, page_number, caption, markdown in new.execute(
            "SELECT id, section, path, page_number, caption, markdown FROM old.Tables"
        ).fetchall():
            new.execute(
                "INSERT INTO main.Tables (id, section, block_id, path, page_number, caption, markdown) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (old_id, section, Path(path).stem if path else None, path, page_number, caption, markdown),
            )
        for old_id, section, path, page_number, caption, description in new.execute(
            "SELECT id, section, path, page_number, caption, description FROM old.Images"
        ).fetchall():
            new.execute(
                "INSERT INTO main.Images (id, section, block_id, path, page_number, caption, description) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (old_id, section, Path(path).stem if path else None, path, page_number, caption, description),
            )

        # ── Pages (from every page number seen) + SectionPages (one/section) ─
        page_id: dict[tuple[int, int], int] = {}

        def _ensure_page(document: int, pno: int) -> int:
            key = (document, pno)
            if key not in page_id:
                cur = new.execute(
                    "INSERT INTO main.Pages (document, page_number) VALUES (?, ?)", key
                )
                page_id[key] = cur.lastrowid
            return page_id[key]

        rows = new.execute(
            "SELECT document, page_number FROM old.Sections WHERE page_number IS NOT NULL "
            "UNION "
            "SELECT s.document, t.page_number FROM old.Tables t JOIN old.Sections s ON t.section = s.id "
            "  WHERE t.page_number IS NOT NULL "
            "UNION "
            "SELECT s.document, i.page_number FROM old.Images i JOIN old.Sections s ON i.section = s.id "
            "  WHERE i.page_number IS NOT NULL"
        ).fetchall()
        for document, pno in rows:
            _ensure_page(document, pno)

        for sec_id, document, pno in new.execute(
            "SELECT id, document, page_number FROM old.Sections WHERE page_number IS NOT NULL"
        ).fetchall():
            new.execute(
                "INSERT OR IGNORE INTO main.SectionPages (section, page) VALUES (?, ?)",
                (sec_id, _ensure_page(document, pno)),
            )

        # ── Embeddings (from the old *_embedding columns) ────────────────────
        n_emb = 0
        dropped: list[tuple] = []
        for table, kind, cols in [("old.Sections", "section", _SECTION_EMB),
                                  ("old.Tables", "table", _TABLE_EMB),
                                  ("old.Images", "figure", _IMAGE_EMB)]:
            ins, drp = _migrate_embeddings(new, table, kind, cols)
            n_emb += ins
            dropped.extend(drp)

        # ── Reconcile org-unit refs the FK-less old schema permitted ─────────
        # (must run while foreign_keys is OFF, before the integrity check).
        docs_fixed, munis_fixed, placeholder_id = _reconcile_org_units(new)

        # ── Integrity check BEFORE commit (so a violation leaves no file) ────
        violations = new.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise SystemExit(f"Foreign-key violations after migration: {violations[:10]}")

        counts = {
            t: new.execute(f"SELECT count(*) FROM main.{t}").fetchone()[0]
            for t in ("OrganisationUnits", "Municipalities", "Documents", "Pages",
                      "Sections", "SectionPages", "Segments", "Tables", "Images", "Embeddings")
        }
        new.commit()
    except BaseException:
        new.close()
        try:
            new_db.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    new.close()

    print(f"Migration OK → {new_db}")
    for t, n in counts.items():
        print(f"  {t:18} {n}")
    print(f"  (embeddings migrated: {n_emb})")
    if docs_fixed or munis_fixed:
        print(f"  NOTE: reconciled {docs_fixed} Document(s) with a dangling "
              f"organisation_unit (set to NULL).")
        if munis_fixed:
            print(f"        {munis_fixed} Municipality(ies) (NOT NULL) repointed to a "
                  f"synthesised placeholder OrganisationUnit id={placeholder_id}.")
    if dropped:
        print(f"  WARNING: skipped {len(dropped)} embedding(s) that reused a FAISS id "
              f"already claimed by another owner (pre-existing duplicate in the "
              f"old DB). Re-run embedding with --force to regenerate clean ids.")
        for ok, oid, et, fid in dropped[:10]:
            print(f"    - faiss_id {fid} wanted by {ok} #{oid} ({et})")
        if len(dropped) > 10:
            print(f"    ... and {len(dropped) - 10} more")
    print("Segments + Section.content are empty; populate them with a "
          "`chunkingandembedding --force` run on the new DB.")


def _reconcile_org_units(conn) -> tuple[int, int, Optional[int]]:
    """
    Repair organisation_unit references that were legal in the FK-less old
    schema but would violate the v2 foreign keys, so a real long-lived DB can
    still be migrated instead of aborting at the integrity check.

      * Documents.organisation_unit is nullable (ON DELETE SET NULL) → a
        dangling ref is set to NULL (lossless).
      * Municipalities.organisation_unit is NOT NULL → dangling rows are
        repointed to a synthesised placeholder OrganisationUnit so the rows
        survive rather than being dropped.

    Must run while `PRAGMA foreign_keys = OFF`. Returns
    (documents_fixed, municipalities_fixed, placeholder_ou_id).
    """
    docs_fixed = conn.execute(
        "UPDATE main.Documents SET organisation_unit = NULL "
        "WHERE organisation_unit IS NOT NULL AND organisation_unit NOT IN "
        "(SELECT id FROM main.OrganisationUnits)"
    ).rowcount

    munis_fixed = conn.execute(
        "SELECT count(*) FROM main.Municipalities WHERE organisation_unit NOT IN "
        "(SELECT id FROM main.OrganisationUnits)"
    ).fetchone()[0]
    placeholder_id = None
    if munis_fixed:
        placeholder_id = conn.execute(
            "INSERT INTO main.OrganisationUnits (name, state) "
            "VALUES ('__unknown__ (migrated)', NULL)"
        ).lastrowid
        conn.execute(
            "UPDATE main.Municipalities SET organisation_unit = ? "
            "WHERE organisation_unit NOT IN (SELECT id FROM main.OrganisationUnits)",
            (placeholder_id,),
        )
    return docs_fixed, munis_fixed, placeholder_id


def _migrate_embeddings(conn, table: str, owner_kind: str, columns: list) -> tuple[int, list]:
    """
    Copy non-null *_embedding ids from *table* into the Embeddings table.

    Returns (inserted, dropped) where dropped is a list of
    (owner_kind, owner_id, embedding_type, faiss_id) tuples whose FAISS id was
    already claimed by another owner (PK conflict) — a data inconsistency in the
    old DB, enumerated by the caller for auditing.
    """
    inserted = 0
    dropped: list[tuple] = []
    select = ", ".join(["id"] + [c for c, _t in columns])
    for row in conn.execute(f"SELECT {select} FROM {table}").fetchall():
        owner_id = row[0]
        for offset, (_col, etype) in enumerate(columns, start=1):
            faiss_id = row[offset]
            if faiss_id is None:
                continue
            cur = conn.execute(
                "INSERT OR IGNORE INTO main.Embeddings (faiss_id, embedding_type, owner_kind, owner_id) "
                "VALUES (?, ?, ?, ?)",
                (faiss_id, etype, owner_kind, owner_id),
            )
            if cur.rowcount:
                inserted += 1
            else:
                dropped.append((owner_kind, owner_id, etype, faiss_id))
    return inserted, dropped


def main() -> None:
    if len(sys.argv) < 3:
        print("usage: python data/migrate_v2.py OLD.db NEW.db [schema.sql]")
        raise SystemExit(2)
    old_db = Path(sys.argv[1])
    new_db = Path(sys.argv[2])
    schema = Path(sys.argv[3]) if len(sys.argv) > 3 else Path(__file__).with_name("KWP.db.sql")
    migrate(old_db, new_db, schema)


if __name__ == "__main__":
    main()
