"""
fileprocessing – Download and meta-data enrichments of the original KWP PDF files.

Standalone module that reads meta-data from KWW excel file, downloads new PDF files,
registers WPs in the database.

Usage:
  python -m src.fileprocessing /path_to_kww_excel/file.xlxs /path_to_db/KWP.db
"""
from .pipeline import run

__all__ = ["run"]