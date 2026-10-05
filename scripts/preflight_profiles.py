#!/usr/bin/env python3
"""
preflight_profiles.py – Both profiles of this repository, everything a
corpus run rests on.

The checks are the package's (`docpipe preflight`, docpipe/extraction/
preflight.py) and hold for any profile. This file runs them for the two
profiles kept here, so the command that stands before a corpus run did not
change:

    python scripts/preflight_profiles.py
    python scripts/preflight_profiles.py kwp

Author: Felix Vossel
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from docpipe.extraction.preflight import (  # noqa: E402,F401
    SHRUGS, audit, main as _main, report, silent_parameters)

OURS = ["kwp", "scenarios"]


def main(argv: list) -> int:
    return _main(list(argv) or OURS)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
