"""Allow execution via: python -m docpipe.ingest"""
from docpipe.profile import bind_command_line

bind_command_line()          # --profile, before the stage is imported

from .cli import main        # noqa: E402

main()
