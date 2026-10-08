"""Allow execution via: python -m docpipe.extraction"""
import sys

from docpipe.profile import bind_command_line

bind_command_line()          # --profile, before the stage is imported

from .runner import main     # noqa: E402

sys.exit(main())
