"""
scratch.py: Where a column of one's own lives, and why its harvest stays there.

A column of one's own is a spec of one parameter that no profile holds,
harvested over a few documents to see what the plans say. Its harvest is
written like every other: a JSONL per document with a stamp beside it, the
anchors, a query cache. A stamp is compared with the spec the run reads, so a
folder that holds the harvests of two specs reads as stale for one of them,
and a forced run of the one overwrites the files of the other. So the folder
is the column's own: a run that takes its spec from a file writes only below
the folder that file lies in, and never into the harvest of a profile.

The folder holds, under these names, what the commands in turn leave there:

    draft.json   `docpipe column` writes it, `docpipe compile examples`
                 proposes its example, `docpipe compile apply` carries the
                 accepted one over
    spec.json    what `compile apply --out` writes once nothing is open
    harvest/     `docpipe extract --spec spec.json`, its stamps and anchors
    values.csv   `docpipe export harvest`, if one asks for the table there

Nothing in the folder is meant for the graph. Nothing here hands it to the
serializer, and no run that reads its spec from a file serializes.

Author: Felix Vossel
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

DRAFT = "draft.json"
SPEC = "spec.json"
HARVEST = "harvest"
TABLE = "values.csv"
# Where `docpipe column` puts a column that is given no folder.
HOME = "scratch"


def _absolute(path) -> Path:
    """*path* made absolute and resolved. Absolute first: before Python 3.10
    `Path.resolve` leaves a relative path that does not exist yet relative on
    Windows, and a harvest folder is exactly that before its first run."""
    return Path(os.path.abspath(path)).resolve()


def folder_problem(spec_file, out) -> Optional[str]:
    """Why a run that reads *spec_file* may not write into *out*, or None.

    *out* has to lie below the folder of the spec file and not in it, so the
    harvest has a folder of its own beside the spec, the draft and the
    proposals. A profile's harvest lies elsewhere, so a run that took its
    spec from a file cannot reach it, forced or not.
    """
    home = _absolute(spec_file).parent
    target = _absolute(out)
    if home in target.parents:
        return None
    return (f"OUT {out} does not lie below {home}, the folder of the spec "
            f"file. A harvest made with --spec goes into a folder of its own "
            f"inside the spec's (`docpipe column` makes {HARVEST}/ for it), "
            f"so that it never lands beside a profile's")
