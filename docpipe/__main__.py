"""Allow execution via: python -m docpipe"""
import sys

# Guarded: a worker process started with spawn imports this module
# again and must not run the command a second time.
if __name__ == "__main__":
    from .cli import main

    sys.exit(main())
