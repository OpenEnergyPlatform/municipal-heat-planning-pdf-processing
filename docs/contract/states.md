# What a coordinate's state means

Generated from `docpipe/extraction/fields.py` and the published schema by `scripts/build_docs.py`.

## What a coordinate's state records

Every axis value of a tuple, a coordinate in the [glossary](../glossary.md)'s
term, carries a `<name>_state` key beside its value, its raw wording, its
quote, its source, the window it was read in, and, when `unstated`, a
`<name>_seen` key for a wording the model noticed
(`docpipe/extraction/schema.py:209-262`). The state is one of seven fixed
strings, defined in `docpipe/extraction/fields.py`. A coordinate with no
value, and one never asked for, read the same on the row. The state
distinguishes a coordinate the document never mentions from one a run
ended before asking about. A coordinate's own value is `null` unless its
state is `read` or `derived` (`schema.py:265-279`). It is a finding about
the model, the document, the run, or the run's scope, never about more
than one of those at once.

## How the field sweep assigns it

Two states are written before any question reaches a model. `apply_derived`
(`fields.py:267-288`) fills a coordinate the spec's own `derive` rule
decides, such as kwp's `aggregation` coordinate on `energy_consumption` and
`emission` parameters, derived to `integral`, the only `derive` rules in
either profile (`profiles/kwp/extraction_spec.json:173,920`). Which
parameter a row belongs to is a separate decision, `derive_parameter`
(`fields.py:214-237`), written directly in `runner.py:2930-2943`, not
through `apply_derived`. `out_of_slice` is written the same way: a gate
coordinate the profile's `SLICE` names has put the row outside what this
run serializes, or no parameter of the spec could hold it, so none of its
coordinates are asked about. The field sweep decides everything else: for
each window's reply, `merge_field` writes `read` when the row's cited
quote sits in a shown source, is local to the row under the coordinate's
evidence rule, and carries the answer; `unstated` when the model names the
closed list's own `out:unstated` entry, since no passage can prove a
document does not say something
(`test_not_stated_is_an_answer_and_needs_no_passage`,
`tests/test_extraction_fieldwise.py:228`); and `unbacked` when a quote is
offered but fails one of those checks. Only `read` is final: a later
window's reply for a coordinate already `read` is discarded, and the row
keeps its first reading (`tests/test_extraction_fieldwise.py:871`).
`open_rows` still counts `unstated`, `unbacked`, and a coordinate no
reply has mentioned, as open, so the sweep keeps asking through
retrieval and then the rest of the document
(`test_one_window_saying_nothing_here_does_not_end_the_sweep`,
`tests/test_extraction_fieldwise.py:275`). `unstated` becomes permanent
only once the sweep has nothing left to read; if the window budget ends
first, every coordinate `open_rows` still counts, `unstated` included, is
instead written `exhausted`, and what no reply mentioned across every
round the sweep did run becomes `unanswered`, written once at the end by
`mark_unanswered`
(`test_every_coordinate_ends_with_a_state_even_when_nothing_answered`,
`tests/test_extraction_fieldwise.py:255`). See
[extraction](../stages/extraction.md) for the windows and rounds this
walks.

## Why seven, not fewer

Each pair states a different fact, and merging two removes a distinction
the run depends on. `unanswered` and `unstated` were the same empty cell
before the state existed: on the 1079-document run they made up 16 to 34
percent of every axis, one half a finding about the model and the other
about the document, with no way after the fact to tell which was which
(`docpipe/extraction/pipeline.py:825`). `exhausted` and `unstated` are the
same conflation about a whole run, and the reason the sweep reads past
retrieval first: before that stage existed, a harvest meant to mark plans
read to the end wrote 789 `exhausted` against 0 `unstated` on the M3 run,
because nothing after retrieval read a document the rest of the way
(`docpipe/extraction/runner.py:2831`). The two the sweep skips are kept
apart from `unstated` for the same reason it exists: asking the parameter
question anyway on the Kassel run would have cost 322 of 1,043 field
windows, 30.9 percent (`docpipe/extraction/fields.py:220`); asking the
coordinates of a row no parameter could hold, on the M3 acceptance run,
cost 178 of 853 field requests, 20.9 percent
(`docpipe/extraction/fields.py:252`); and before the slice gate ran first,
4,064 of 6,763 tuples harvested across 20 plans had all seven axes
filled in before being dropped for the two gate coordinates
(`docpipe/extraction/runner.py:2979`). The same split holds past the
coordinate: `docpipe/extraction/trust.py`'s `reasons` counts only
`exhausted` and `unbacked` as doubt about a reading, and treats every
other state, `derived`, `unstated` and `out_of_slice`, as a fact about the
document or the run's scope, not about the value itself.
[Trust](trust.md) grades a tuple from exactly that split.

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
