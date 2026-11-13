"""
ruleset: the rules of the reading by the part of the run that reads them.

Each module names its rules (`RULES`, made with `kit.rule`) with
the kinds of steps that read them (`steps`); their values stand in the
default profile's rules.json like every rule of the core.
"""
from .requests import RULES as _requests
from .showing import RULES as _showing
from .flowing import RULES as _flowing
from .taking import RULES as _taking
from .passes import RULES as _passes
from .search import RULES as _search

MORE = _requests + _showing + _flowing + _taking + _passes + _search
