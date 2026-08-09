"""
migrate_artifact_names.py – Rename the per-document artefacts of an already
processed tree to the names in ``docpipe.artifacts``.

The old names lied about their place in the pipeline: ``structured_output_final``
was followed by two more stages, ``structured_output_images`` holds no images,
and ``output.json`` — the one the database reads — was the vaguest of the five.

Renaming costs nothing (the files are keyed by name only, never by path stored
elsewhere), so a processed tree does not have to be rebuilt:

    python -m docpipe.migrate_artifact_names data/pdf/processed
    python -m docpipe.migrate_artifact_names data/pdf/processed --apply

Author: Felix Vossel
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

from docpipe.artifacts import (DIR_RESULTS, DOCUMENT_JSON, PAGES_JSON,
                               SECTIONS_JSON, SECTIONS_REFINED_JSON,
                               VISUALS_JSON)

log = logging.getLogger(__name__)

RENAMES = {
    "pages_extracted.json":          Path(PAGES_JSON).name,
    "structured_output.json":        Path(SECTIONS_JSON).name,
    "structured_output_final.json":  Path(SECTIONS_REFINED_JSON).name,
    "structured_output_images.json": Path(VISUALS_JSON).name,
    "output.json":                   Path(DOCUMENT_JSON).name,
}


def pending(root: Path) -> list[tuple[Path, Path]]:
    """(old, new) for every artefact still carrying its old name."""
    out = []
    for results in sorted(root.glob("*/" + DIR_RESULTS)):
        for old_name, new_name in RENAMES.items():
            old = results / old_name
            if old.exists():
                out.append((old, results / new_name))
    return out


def migrate(root: Path, apply: bool = False) -> int:
    """Renames what `pending` finds. Returns the number of files renamed."""
    todo = pending(root)
    if not todo:
        log.info("Nothing to rename under %s.", root)
        return 0

    done = 0
    for old, new in todo:
        if new.exists():
            # Both names present: a half-finished earlier run, or a tree
            # processed twice. The new one is authoritative; leave both.
            log.warning("%s: %s exists already – skipping", old.parent, new.name)
            continue
        if apply:
            old.rename(new)
        done += 1

    log.info("%s %d file(s) across %d document(s).",
             "Renamed" if apply else "Would rename", done,
             len({o.parent for o, _ in todo}))
    if not apply:
        log.info("Dry run – pass --apply to do it.")
    return done


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m docpipe.migrate_artifact_names")
    p.add_argument("root", type=Path, help="the processed root (holding one dir per document)")
    p.add_argument("--apply", action="store_true", help="actually rename")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    migrate(args.root, apply=args.apply)


if __name__ == "__main__":
    main()
