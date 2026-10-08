"""
source.py – Where the documents come from: a folder of PDFs.

    docpipe ingest                      # what lies in the data directory
    docpipe ingest --source ~/reports   # a folder, with its subfolders

Author: Felix Vossel
"""
from docpipe.ingest.folder import FolderSource

SOURCE = FolderSource
