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
from .stage_text import RULES as _stage_text
from .stage_layout import RULES as _stage_layout
from .stage_sections import RULES as _stage_sections
from .stage_refine import RULES as _stage_refine
from .stage_visuals import RULES as _stage_visuals
from .stage_chunks import RULES as _stage_chunks

# The stages before the harvest, 1 to 6, each with the decisions it used to
# hold as fixed values (owner request 2026-11-19, A1), on the tab "stages".
STAGES = (_stage_text + _stage_layout + _stage_sections + _stage_refine
          + _stage_visuals + _stage_chunks)

MORE = (_requests + _showing + _flowing + _taking + _passes + _search
        + STAGES)
