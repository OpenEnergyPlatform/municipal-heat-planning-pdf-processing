# What a coordinate's state means

Generated from `docpipe/extraction/fields.py` and the published schema by `scripts/build_docs.py`.

Every coordinate of every accepted value carries one of these, always. The distinction they exist for is the one between a finding about the document and a finding about the run: "the plan does not say it" and "we stopped looking" are not the same fact, and an empty cell says neither.

| constant | value | what it says |
|---|---|---|
| `READ` | `read` | answered, and the cited passage carries the answer |
| `DERIVED` | `derived` | not asked: the spec decides this coordinate from something already on the row (the unit) |
| `SAID_UNSTATED` | `unstated` | answered: the passages shown do not state it. A finding about the document, and only final once the sweep ran out of it |
| `UNANSWERED` | `unanswered` | the field reply never mentioned this row. A finding about the model |
| `EXHAUSTED` | `exhausted` | still open when the window budget ended with the document unread. A finding about the run |
| `UNBACKED` | `unbacked` | answered, but no shown passage carried the answer, or the passage belonged to another row, and no later window fixed it |
| `OUT_OF_SLICE` | `out_of_slice` | never asked: a gate coordinate (the profile's SLICE) had already put the row outside what this run serializes |

[Back to the index](../README.md)
