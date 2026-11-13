"""Allow execution via: python -m docpipe.serve"""
import sys

# Guarded: a worker process started with spawn imports this module
# again and must not run the command a second time.
if __name__ == "__main__":
    from ..profile import bind_command_line

    bind_command_line()          # --profile, before the stage is imported

    from .cli import serve_main  # noqa: E402

    sys.exit(serve_main())
