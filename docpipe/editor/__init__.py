"""
docpipe.editor: `docpipe edit`, a profile's extraction spec, prompts,
sentences and the numbers of its flow in the browser.

Author: Felix Vossel
"""
from __future__ import annotations

from typing import Sequence


def main(rest: Sequence[str]) -> int:
    """`docpipe edit`. The server is imported here and not above, so the
    logic beside it can be used without it."""
    from . import server
    return server.command(rest)
