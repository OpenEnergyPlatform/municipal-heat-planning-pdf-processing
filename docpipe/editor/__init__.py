"""
docpipe.editor: `docpipe edit`, a profile's extraction spec in the browser.

Author: Felix Vossel
"""
from __future__ import annotations

from typing import Sequence


def main(rest: Sequence[str]) -> int:
    """`docpipe edit`. The server is imported here and not above, so the
    logic in `specs` can be used without it."""
    from . import server
    return server.command(rest)
