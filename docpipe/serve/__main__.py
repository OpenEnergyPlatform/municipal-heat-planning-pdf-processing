"""Allow execution via: python -m docpipe.serve"""
import sys

from ..profile import bind_command_line

bind_command_line()          # --profile, before the stage is imported

from .cli import serve_main  # noqa: E402

sys.exit(serve_main())
