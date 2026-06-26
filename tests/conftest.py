"""Shared pytest fixtures + lightweight stubs for the heavy/optional deps."""
import os
import pathlib
import sys
import types

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)


def _stub_if_missing(name, attrs=None):
    try:
        __import__(name)
        return
    except Exception:
        pass
    mod = types.ModuleType(name)
    for k, v in (attrs or {}).items():
        setattr(mod, k, v)
    sys.modules[name] = mod


# Heavy/optional runtime deps not needed to unit-test the pure logic.
for _m in ("fitz", "cv2", "torch", "faiss", "ollama"):
    _stub_if_missing(_m)
_stub_if_missing("numpy", {"ndarray": object})
if "PIL" not in sys.modules:
    try:
        import PIL  # noqa: F401
    except Exception:
        pil = types.ModuleType("PIL")
        img = types.ModuleType("PIL.Image")
        pil.Image = img
        sys.modules["PIL"] = pil
        sys.modules["PIL.Image"] = img


@pytest.fixture
def kwp_db(tmp_path):
    """A fresh SQLite DB with the v2 schema and one Document (id=1)."""
    from scripts.chunkingandembedding import database as DB
    schema = pathlib.Path(ROOT, "data", "KWP.db.sql").read_text(encoding="utf-8")
    db = tmp_path / "kwp.db"
    con = DB.connect(db)
    con.executescript(schema)
    con.execute("INSERT INTO Documents (id, filename, num_pages) VALUES (1, 'doc.pdf', 9)")
    con.commit()
    return db, con
