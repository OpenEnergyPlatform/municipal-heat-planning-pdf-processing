"""
artifacts.py: Names the per-document result files under `<doc>/results/`,
in the order the pipeline writes them, and finds the document directories
that hold them.

One definition serves all five pipeline modules: a filename spelled out in
four separate config.py files drifts, and the module that reads a file is
rarely the one that wrote it. The same goes for the listing: preprocessing
writes a nested folder of PDFs to a nested folder of document directories,
and a stage that lists only the first level loses every document below it,
so every stage lists through `document_dirs`.

Author: Felix Vossel
"""
from __future__ import annotations

import os
from pathlib import Path


DIR_RESULTS = "results"
DIR_IMAGES  = "images"

PAGES_JSON            = f"{DIR_RESULTS}/pages.json"             # preprocessing (extract)
SECTIONS_JSON         = f"{DIR_RESULTS}/sections.json"          # preprocessing (structure)
PAGE_TRANSCRIPTION_REPORT_JSON = (
    f"{DIR_RESULTS}/page_transcription_report.json")            # preprocessing (model-read pages)
SECTIONS_REFINED_JSON = f"{DIR_RESULTS}/sections_refined.json"  # refinement
REFINEMENT_REPORT_JSON = f"{DIR_RESULTS}/refinement_report.json"  # refinement (what failed)
REFINEMENT_PARTIAL_JSON = (
    f"{DIR_RESULTS}/sections_refined.partial.json")             # refinement (unfinished)
VISUALS_JSON          = f"{DIR_RESULTS}/visuals.json"           # visuals
DOCUMENT_JSON         = f"{DIR_RESULTS}/document.json"          # chunking (merge) → database

# What the stages after stage 3 and stage 5 read of these two files is written
# down in docpipe/schemas/<name>.schema.json. Each file carries the version of
# its own shape under the key "version", counted apart; a file without the key
# is version 1. The schemas are documentation and tests: no stage opens them,
# and none refuses a file because it does not fit.
SECTIONS_VERSION = 1
VISUALS_VERSION  = 1
SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"


class DuplicateDocumentName(ValueError):
    """Two document directories of one name under different subfolders."""


def document_dirs(root, *markers: str, distinct: bool = True) -> list:
    """The document directories under *root*, at any depth, in path order.

    A document directory is one that holds any of *markers* (a name under it,
    such as SECTIONS_JSON, which says the stage this listing is for can read
    it). Nothing below a document directory is searched. A directory that
    holds none of them is searched, because a subfolder of the source folder
    is a directory like that, and so is a document the stage cannot read yet.
    With every document directly under *root* this is what iterating *root*
    and keeping the directories that hold a marker gave, in the same order.

    The stages know a document by the name of its directory (the database
    row is `<name>.pdf`), so two of one name under different subfolders are
    one document too many: that is refused with both places named, unless
    *distinct* is off for a caller that only reads the directories.
    """
    root = Path(root)
    found: list = []
    # Resolved targets of the links searched through: a link back up the tree
    # would otherwise be searched for ever.
    linked: set = {os.path.realpath(root)}

    def search(folder: Path) -> None:
        with os.scandir(folder) as entries:
            children = [folder / entry.name for entry in entries
                        if entry.is_dir()]
        for child in children:
            if any((child / marker).exists() for marker in markers):
                found.append(child)
                continue
            if child.is_symlink():
                target = os.path.realpath(child)
                if target in linked:
                    continue
                linked.add(target)
            search(child)

    search(root)
    found.sort()
    if distinct:
        refuse_same_names(found, root)
    return found


def refuse_same_names(directories, root) -> None:
    """Raise DuplicateDocumentName if two of *directories* (under *root*)
    have one name, with the places of each such name."""
    root = Path(root)
    named: dict = {}
    for path in directories:
        named.setdefault(path.name, []).append(path)
    twice = {name: paths for name, paths in named.items() if len(paths) > 1}
    if twice:
        lines = [f"  {name}: " + ", ".join(
            path.parent.relative_to(root).as_posix() for path in paths)
            for name, paths in sorted(twice.items())]
        raise DuplicateDocumentName(
            "a document is known by the name of its directory, and "
            f"these names occur more than once under {root}:\n"
            + "\n".join(lines))
