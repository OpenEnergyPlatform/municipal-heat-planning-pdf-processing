"""`python -m docpipe.compile`."""
import sys

from ..profile import bind_command_line

bind_command_line()

from .cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
