# docpipe.ruleset.stage_sections

`docpipe/ruleset/stage_sections.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

stage_sections.py: the rules of stage 3 (sections), the decisions the stage
used to hold as fixed values in its code (owner request 2026-11-19, A1:
"Die festen Werte werden Regeln mit dem heutigen Wert als Standard"). Their
values stand in the default profile's rules.json; a profile that decides
otherwise says so in its own. The stage reads each where it decides, when it
runs (`rules.get`), so that a changed value is the next run's.

Author: Felix Vossel

[Back to the index](../README.md)
