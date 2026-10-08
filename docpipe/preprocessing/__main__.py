"""Allow execution via: python -m docpipe.preprocessing"""
from docpipe.profile import bind_command_line

bind_command_line()          # --profile, before the stage is imported

from .pipeline import main   # noqa: E402

main()
