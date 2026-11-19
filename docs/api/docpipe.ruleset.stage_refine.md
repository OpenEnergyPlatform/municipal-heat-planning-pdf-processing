# docpipe.ruleset.stage_refine

`docpipe/ruleset/stage_refine.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

stage_refine.py: the rules of stage 4 (refinement), the decisions the stage
used to hold as fixed values in its code (owner request 2026-11-19, A1:
"Die festen Werte werden Regeln mit dem heutigen Wert als Standard"). Their
values stand in the default profile's rules.json; a profile that decides
otherwise says so in its own. The stage reads each where it decides, when it
runs (`rules.get`), so that a changed value is the next run's.

Author: Felix Vossel

[Back to the index](../README.md)
