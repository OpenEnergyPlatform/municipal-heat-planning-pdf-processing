"""`python -m docpipe.compile`."""
import sys

# Guarded: a worker process started with spawn imports this module
# again and must not run the command a second time.
if __name__ == "__main__":
    from ..profile import bind_command_line
    bind_command_line()
    from .cli import main  # noqa: E402
    sys.exit(main())
