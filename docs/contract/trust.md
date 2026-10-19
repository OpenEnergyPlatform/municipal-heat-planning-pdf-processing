# How much of a value the run can stand behind

Generated from `docpipe/extraction/trust.py` and the published schema by `scripts/build_docs.py`.

## A minimum check, then a level

Every accepted tuple already passed a minimum check: `verify.py`'s
`verify_tuple` checks the number against its quote and the quote against a
shown source (`verify.py:365-552`). The field sweep in
`docpipe/extraction/pipeline.py` holds each coordinate to the same two
clauses, its quote stands in a shown source and carries the answer, and
writes the passage's owner onto the row (`merge_field`,
`pipeline.py:965-1188`); a closed-list coordinate is held to a third, naming
one of the list's own entries, or it is never marked read (`not_an_option`).
Where in the document that passage
stands is no check and no grade. Neither check is the trust level: a
value read out of the document's own text and one read out of a picture,
with a coordinate the run gave up on, both clear it. `trust.py`'s `trust`
function computes a second, finer verdict: no model call, no corroborating
review, no tuned threshold (`trust.py:112-130`).

## What moves a value between the three levels

Level `A` adds nothing beyond that minimum check: every coordinate read,
no image involved. A value drops to `B` for two
independent reasons: its evidence tier is `verify.TIER_VISUAL`, an owner
kind outside `verify.TEXT_KINDS` such as a table transcription or a figure
description (`verify.py:43-45,522-532`); or the document had no text layer
and was transcribed page by page, passed to `trust()` as a `transcribed`
keyword read from the `page_text_transcribed` column
(`profiles/kwp/kg.py:408-410`, `:571`, `:662`) and capping a row at `B` even with
tier `TIER_TEXT` (`trust.py:121-128`). On the 559 tuples the levels were
cut at, 527 came out of a table or figure image, so image origin alone is
not a warning (`trust.py:39-41`).

A value falls to `C` only when something else is off: an `unbacked`,
`exhausted` or `unanswered` coordinate, a repaired quote, a computed
number, or a contested identity (`reasons`, `trust.py:77-109`). A passage outside the row's own
table is no reason: the harvest takes any shown passage that carries the
answer, and grading it again here would be a check the harvest does not
make (`trust.py:28-31`).

## The reason vocabulary

Every `C` carries at least one reason, and the reasons form a closed list:
a reason nobody can enumerate is a reason nobody can count
(`trust.py:24-26`). A coordinate contributes `exhausted:<axis>`,
`unbacked:<axis>` or `unanswered:<axis>` (`trust.py:94-95`). A row's own
`flags` contribute `repaired`, `computed`, `not_located` or
`review:disagree` (`FLAG_REASONS`, `trust.py:72-74`). `conflict` is added
by a profile's own graph serializer resolving two competing readings of
one coordinate: kwp settles them first (`settle`: by the plan's wording,
by rounding, by trust), drops every claimant of what stays tied and never
marks `conflict`, scenarios keeps a chosen reading and marks it `conflict`
(`profiles/kwp/kg.py:514-580`, `profiles/scenarios/kg.py:701-702`; see
[graph](../stages/graph.md)). `page_transcribed` never by itself decides
the level: it caps a value at `B` rather than pushing it to `C`, since a
page with no text layer is a fact about the source, not about this reading
(`trust.py:102-108`, `:121`).

## Review and its flags

A `C` value can be read a second time by `docpipe/extraction/review.py`:
the same model, over a window narrowed to the row's own passage. Only
level `C` rows are candidates, and an already reviewed row is skipped
unless forced, so a row is reviewed once. The second reading writes exactly
one of three flags: `review:agree` when it matches the stored value,
`review:disagree` when it does not, `review:unbacked` when its own answer
cannot be checked against the narrowed window (`review.py:222-226`). None of the three raises the
level: an agreement is recorded as `corroborated`, since the second
reading checks self-consistency, not that it is right
(`trust.py:116-120`). A disagreement becomes a
`review:disagree` reason instead, a fact a curator can count.

## What the marks of a trust line say

A profile's serializer writes one line above every value node, built from
up to six marks in a fixed order: `level`, `image_origin` or
`image_origin_named`, `corroborated`, `reasons`, `review` (`trust.marks`,
`trust.py:168-200`). Only the marks a verdict actually has appear, and
`image_origin_named` replaces `image_origin` when the row's provenance
records the image's file name. Each mark's wording is the profile's own:
the [kwp](../profiles/kwp.md) and [scenarios](../profiles/scenarios.md)
serializers each state a `TRUST_PROSE` table, both in English
(`profiles/kwp/kg.py:587-594`, `profiles/scenarios/kg.py:464-471`), and a
profile missing a mark, or wording one that is not on this list, is
refused at import (`trust.check_prose`, `trust.py:203-215`). The reason tokens are never
translated, so a curator greps for `exhausted:carrier` in either corpus and
finds the same string (`trust.py:169-173`).

## Two summaries above the row

`trust.py` defines two more public functions. `document_summary`, called
from seven modules including `runner.py`, `review.py` and `topup_parameter.py`,
builds the `kind: summary` line a harvest file ends with: counts of tuples by
level, by reason and by image origin (`trust.py:231-273`). The pass that appends
a parameter builds it again over every tuple and refusal the file now holds;
the refusals of the first pass are counted as they were stored and are not
revisited, so a value refused then for want of the parameter stays in the
count, which says what the harvest refused and not how many of those a later
pass could read. A document with
no tuples still gets a line, all levels at zero. `parameter_states`, called from
`runner.py` and `topup_parameter.py`, records one state per parameter of the spec: `read`,
`unbacked`, `exhausted` (nothing of the document was answered, or a cut
request held one of the parameter's own ranked sources, or, without that
source list or a source named on the request, any cut at all) or
`unstated` (`trust.py:279-335`).

## What `docpipe/extraction/trust.py` says

<details>
<summary><code>docpipe/extraction/trust.py</code></summary>

trust.py: Grades every harvested value by how far the run can stand
behind it.

Every accepted tuple is verified: its number is in its quote, its
quote is in a shown source, and every coordinate names the passage it
was read in, and that passage carries its answer. That is a floor, not
a grade. Two values that both clear it can still differ: one was read
out of the document's own text with every coordinate read, the other
out of a picture, with a coordinate the run gave up on.

The module computes a deterministic level per value, from what the
harvest already records: no model call, no second opinion, no
threshold anybody tuned.

  A  the document's own text states it, every coordinate read
  B  the same, but read out of a table transcription or a figure
     description (a model's reading of a picture), or out of a
     document whose pages had no text layer and were transcribed page
     by page
  C  something is off: a coordinate the run gave up on or could not
     back, a repaired quote, a computed number, a contested identity

The reasons form a closed list, because a reason nobody can enumerate
is a reason nobody can count. What makes a value a C is what a curator
should examine.

Where in the document a coordinate's passage stands is not a reason.
The harvest takes a reading whose quote stands in a shown passage and
carries the answer, and grading it again by that passage's distance
from the row would be a check the harvest does not make.

A value can be read a second time (`review.py`), and what that reading
came to is recorded here as a mark. It never raises a level: the
second reading uses the same model over a narrower window, so an
agreement states that the reading is self-consistent, not that it is
right.

Measured on Kassel's 559 tuples, 527 came out of a table or figure
image, so image origin alone separates nothing and is not by itself a
warning.

Author: Felix Vossel

</details>

## The levels

| level | what it says |
|---|---|
| `A` | read off its own passage, in the document's own text |
| `B` | the same, but out of an image transcription or a page a model transcribed |
| `C` | something is off; see reasons |

## The reasons

A closed list, because a reason nobody can enumerate is a reason nobody can count. The published schema accepts exactly these shapes:

- `^computed$`
- `^not_located$`
- `^repaired$`
- `^review:disagree$`
- `^conflict$`
- `^page_transcribed$`
- `^(exhausted|unbacked|unanswered):[a-z_]+$`

## Reasons that come off a flag

| flag on the row | reason it becomes |
|---|---|
| `computed` | `computed` |
| `not_located` | `not_located` |
| `quote_repaired` | `repaired` |
| `review:disagree` | `review:disagree` |

## The marks of a trust line

The line the serializer writes above a value node is made of these marks, in this order, each worded by the profile in its own language (`TRUST_PROSE`) and only where it applies:

1. `level`
2. `image_origin`
3. `image_origin_named`
4. `corroborated`
5. `reasons`
6. `review`

Inside the `reasons` mark the reasons are joined with `, `; the reason tokens themselves are never translated.

[Back to the index](../README.md)
