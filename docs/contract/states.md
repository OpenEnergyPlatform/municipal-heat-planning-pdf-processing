# What a coordinate's state means

Generated from `docpipe/extraction/fields.py` and the published schema by `scripts/build_docs.py`.

## What a coordinate's state records

Every axis value of a tuple, a coordinate in the [glossary](../glossary.md)'s
term, carries a `<name>_state` key beside its value, its raw wording, its
quote, its source, the window it was read in, and, when `unstated` or a
closed-list answer names none of its entries, a
`<name>_seen` key for a wording the model noticed
(`docpipe/extraction/schema.py:212-293`). The state is one of seven fixed
strings, defined in `docpipe/extraction/fields.py`. A coordinate with no
value, and one never asked for, read the same on the row. The state
distinguishes a coordinate the document never mentions from one a run
ended before asking about. A coordinate's own value is `null` unless its
state is `read` or `derived` (`schema.py:296-310`). It is a finding about
the model, the document, the run, or the run's scope, never about more
than one of those at once.

A harvest also holds one state line per document and parameter, which says
whether values were read, the document does not carry the parameter, or the run
ended first. That is a state of the parameter in a document and not of a
coordinate (a tuple's own `parameter_state` key is the state of its `parameter`
coordinate). The pass that appends a parameter the spec gained after the
harvest (`--top-up-parameters`) writes one such line for each parameter it
appends, and takes the line as the proof that the parameter was read in that
document. `docpipe export --what states` and the server's `get_states` and
`get_coverage` serve those lines; see [handing the values on](../stages/serve.md).

## How the run assigns it

Two states are written without a question to a model. `apply_derived`
(`fields.py`) fills a coordinate the spec's own `derive` rule decides, such as
kwp's `aggregation` coordinate on `energy_consumption` and `emission`. It is
asked first, like any other, and the unit's entry is taken, as `derived`, only
where no request read the coordinate (`fields.derives`, `surveyed.derive_left`
once the coordinates were asked, owner decision 2026-11-07); a coordinate
asked and left open loses its answer, quote and state to it. The years between
the first and the last year of a span the plan states are `derived` too, from the
span (`reading.span_rows`). Which parameter a row belongs to is a separate
decision, `derive_parameter`; in this flow nobody asks it: a row is read
for the one field its request names, and the fold writes its `parameter_state` as
`derived` (`pipeline.fold_claims`, owner decision 2026-11-05). `out_of_slice` is
written when a coordinate with an entry a value must have (`keep`) reads the row
as no value of its parameter, or when no parameter of the spec could hold it (a
number with no unit, or with one no parameter accepts): the coordinates after it
are never asked about. Where a spec has no numeric parameter nothing is
measured: a bare year or a dotted date is a wording there
(`fields.is_wording`). Everything else a reply decides: `merge_field` writes
`read` when the row's cited quote, the line the answer's address names, sits in a
shown source and carries the answer; `unstated` when no shown line states it, which
the code writes (a reply of 0, where the search has nothing left to show, or where
only the value's own place could state the coordinate); and `unbacked` when an
address and words are offered but fail one of those checks, or a closed-list answer
names none of its entries (`not_an_option`), and still fail after their follow-up.
Only `read` is final: a later reply for a coordinate already `read` is discarded,
and the row keeps its first reading.

A coordinate whose own place does not state it, and which is not one only that
place can state, is searched for: the pieces beside the value's, then the pieces a
search finds for a sentence as the plan would print the answer, five at a time. It
goes on until a find holds or every piece of the plan was shown. `unstated` becomes
permanent only once the search has nothing left to show; if the search has asked its
budget of requests first, it is written `exhausted`; a coordinate whose own request
came to no reply, and what no request mentioned, becomes `unanswered`, written once
at the end by `mark_unanswered`. A pass over a stored harvest (`--top-up`,
`--top-up-parameters`, `--top-up-open`) asks the same way. See
[extraction](../stages/extraction.md) (Asking a coordinate of a value and Searching
for what a value's place does not say) for the requests.

## Why seven, not fewer

Each pair states a different fact, and merging two removes a distinction
the run depends on. `unanswered` and `unstated` were the same empty cell
before the state existed: on the 1079-document run they made up 16 to 34
percent of every axis, one half a finding about the model and the other
about the document, with no way after the fact to tell which was which
(`docpipe/extraction/pipeline.py:1306`). `exhausted` and `unstated` are the
same conflation about a whole run, and the reason the search reads the plan to
its end before it writes `unstated`: before it did, a harvest meant to mark plans
read to the end wrote 789 `exhausted` against 0 `unstated` on the M3 run,
because nothing after retrieval read a document the rest of the way. The two that are never asked are kept apart from `unstated` for the same reason
they exist: in the field-by-field flow, which was removed on 2026-11-08, asking
the parameter question anyway on the Kassel run would have cost 322 of 1,043
field windows, 30.9 percent; asking the coordinates of a row no parameter could
hold, on the M3 acceptance run, cost 178 of 853 field requests, 20.9 percent; and
before the slice gate ran first, 4,064 of 6,763 tuples harvested across 20 plans
had all seven axes filled in before being dropped for the two gate coordinates. The same split holds past
the coordinate: `docpipe/extraction/trust.py`'s `reasons` counts
`exhausted`, `unbacked` and `unanswered` as reasons, and
treats every other state, `derived`, `unstated` and `out_of_slice`, as a
fact about the document or the run's scope, not about the value itself.
[Trust](trust.md) grades a tuple from exactly that split: a coordinate nobody
read, `exhausted` or `unanswered`, makes it a `C`, a reading that could not be
backed, `unbacked`, a `D`.

| constant | value | what it says |
|---|---|---|
| `READ` | `read` | answered, and the cited passage carries the answer |
| `DERIVED` | `derived` | not asked: the spec decides this coordinate from something already on the row (the unit), or the request names it (the parameter of a row read for one field) |
| `SAID_UNSTATED` | `unstated` | answered: the passages shown do not state it. A finding about the document, and only final once the sweep ran out of it |
| `UNANSWERED` | `unanswered` | the field reply never mentioned this row. A finding about the model |
| `EXHAUSTED` | `exhausted` | still open when the window budget ended with the document unread. A finding about the run |
| `UNBACKED` | `unbacked` | answered, but no shown passage carried the answer, or the passage belonged to another row, and no later window fixed it |
| `OUT_OF_SLICE` | `out_of_slice` | never asked: a gate coordinate (the profile's SLICE) had already put the row outside what this run serializes |

[Back to the index](../README.md)
