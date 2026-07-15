"""
fileprocessing – Read the KWW excel meta-data, download new KWP PDFs, register them in the DB.

Usage:
  python -m src.fileprocessing /path_to_kww_excel/file.xlxs /path_to_db/KWP.db
"""
from .pipeline import run

__all__ = ["run"]