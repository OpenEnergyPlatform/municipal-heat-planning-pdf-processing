"""Allow execution via: python -m docpipe.extraction"""
import sys

from .runner import main

sys.exit(main())
