# How much of a value the run can stand behind

Generated from `docpipe/extraction/trust.py` and the published schema by `scripts/build_docs.py`.

## A minimum check, then a level

Every accepted tuple already passed a minimum check: `verify.py`'s
`verify_tuple` checks the number against its quote and the quote against a
shown source (`verify.py:403-453`). The field sweep in
`docpipe/extraction/pipeline.py` writes each coordinate's own passage
owner onto the row (`pipeline.py:729`) and decides whether that passage is
the coordinate's own evidence, under `evidence_is_local`
(`pipeline.py:541-560`). Neither check is the trust level: a value read
entirely off its own table and one whose year came from another table's
caption three pages away both clear it. `trust.py`'s `trust` function
computes a second, finer verdict: no model call, no corroborating review,
no tuned threshold (`trust.py:174-192`).

## What moves a value between the three levels

Level `A` adds nothing beyond that minimum check: every coordinate read,
every passage local, no image involved
(`test_a_value_read_off_its_own_table_in_the_plans_text_is_an_a`,
`tests/test_extraction_trust.py:45`). A value drops to `B` for two
independent reasons: its evidence tier is `verify.TIER_VISUAL`, an owner
kind outside `verify.TEXT_KINDS` such as a table transcription or a figure
description (`verify.py:41-42,433-448`;
`test_a_reading_out_of_a_picture_is_a_b_and_not_a_warning`,
`tests/test_extraction_trust.py:51`); or the document had no text layer
and was transcribed page by page, passed to `trust()` as a `transcribed`
keyword read from the `page_text_transcribed` column
(`profiles/kwp/kg.py:408-409,502,516`) and capping a row at `B` even with
tier `TIER_TEXT` (`trust.py:184-188`;
`test_the_same_value_from_a_transcribed_plan_never_reaches_a`,
`tests/test_extraction_trust.py:61`). On the 559 tuples the levels were
cut at, 527 came out of a table or figure image, so image origin alone is
not a warning (`trust.py:43-46`).

A value falls to `C` only when something else is off: an `unbacked` or
`exhausted` coordinate, a passage outside the row's own source, a
repaired quote, a computed number, or a contested identity
(`trust.py:121-171`; `test_a_passage_that_belongs_to_another_row_is_a_c`,
`tests/test_extraction_trust.py:73`;
`test_a_contested_identity_is_a_c_even_with_everything_else_right`,
`tests/test_extraction_trust.py:99`). A foreign passage counts only for an
axis whose evidence rule is `own`, not `local` or `any`
(`docpipe/extraction/spec.py:711-729`; see
[extraction](../stages/extraction.md)): `any`, an axis' default
(`spec.py:155`), is no restriction at all, so most axes are never judged
as nonlocal (`spec.py:717-718`), and the strictest rule for every axis
would flag every legal reading as a doubt (`trust.py:52-61`;
`test_an_axis_the_spec_lets_read_a_page_away_is_not_a_doubt`,
`tests/test_extraction_trust.py:305`). Before that rule existed, on the
same 559 tuples, 370 of 455 year readings, 87 percent of the area
readings, 47 percent of the scenarios and 49 percent of the sectors cited
a foreign passage, against 13 percent of the carriers, which a row carries directly, and that
spread is what separated a level `C` (`trust.py:46-50`).

## The reason vocabulary

Every `C` carries at least one reason, and the reasons form a closed list:
a reason nobody can enumerate is a reason nobody can count
(`trust.py:33-35`). A coordinate contributes `nonlocal:<axis>`,
`exhausted:<axis>` or `unbacked:<axis>` (`trust.py:143-157`). A row's own
`flags` contribute `repaired`, `computed`, `not_located` or
`review:disagree` (`FLAG_REASONS`, `trust.py:97-99`). `conflict` is added
by a profile's own graph serializer resolving two competing readings of
one coordinate: kwp drops every colliding row before it reaches a trust
line, scenarios keeps a chosen reading and marks it `conflict`
(`profiles/kwp/kg.py:648-669`, `profiles/scenarios/kg.py:690-692`; see
[graph](../stages/graph.md)). `page_transcribed` never by itself decides
the level: it caps a value at `B` rather than pushing it to `C`, since a
page with no text layer is a fact about the source, not about this reading
(`trust.py:164-170,183`).

## Review and its flags

A `C` value can be read a second time by `docpipe/extraction/review.py`:
the same model, over a window narrowed to the row's own passage. Only
level `C` rows are candidates, and an already reviewed row is skipped
unless forced, so a row is reviewed once
(`test_only_the_values_nobody_can_stand_behind_are_reviewed`,
`tests/test_extraction_review.py:103`; `test_a_row_is_reviewed_once`,
`tests/test_extraction_review.py:116`). The second reading writes exactly
one of three flags: `review:agree` when it matches the stored value,
`review:disagree` when it does not, `review:unbacked` when its own answer
cannot be checked against the narrowed window (`review.py:220-224`;
`test_agreement_writes_the_flag_and_moves_nothing_else`,
`tests/test_extraction_review.py:282`). None of the three raises the
level: an agreement is recorded as `corroborated`, since the second
reading checks self-consistency, not that the passage it cites belongs to
the row (`trust.py:182`; `test_a_corroborated_row_is_still_a_c`,
`tests/test_extraction_review.py:306`). A disagreement becomes a
`review:disagree` reason instead, a fact a curator can count
(`test_a_disagreement_is_a_reason_a_curator_can_count`,
`tests/test_extraction_review.py:323`).

## What the marks of a trust line say

A profile's serializer writes one line above every value node, built from
up to six marks in a fixed order: `level`, `image_origin` or
`image_origin_named`, `corroborated`, `reasons`, `review` (`trust.marks`,
`trust.py:216-238`). Only the marks a verdict actually has appear, and
`image_origin_named` replaces `image_origin` when the row's provenance
records the image's file name. Each mark's wording is the profile's own:
the [kwp](../profiles/kwp.md) and [scenarios](../profiles/scenarios.md)
serializers each state a `TRUST_PROSE` table, in German and in English
(`profiles/kwp/kg.py:484-491`, `profiles/scenarios/kg.py:472-479`), and a
profile missing a mark, or wording one that is not on this list, is
refused at import (`trust.check_prose`, `trust.py:241-253`;
`test_every_profile_words_every_mark_the_core_can_produce`,
`tests/test_extraction_trust.py:189`;
`test_a_table_that_words_a_mark_that_is_not_one_is_refused`,
`tests/test_extraction_trust.py:205`). The reason tokens are never
translated, so a curator greps for `nonlocal:carrier` in either corpus and
finds the same string (`trust.py:209-213`).

## Two summaries above the row

`trust.py` defines two more public functions. `document_summary`, called
from six modules including `runner.py` and `review.py`, builds the
`kind: summary` line a harvest file ends with: counts of tuples by level,
by reason and by image origin (`trust.py:269-305`). It carries the `own`
rule down to a document's reported levels: three tuples with a foreign
year read `C` with no rule passed, `A` once the rule holds `carrier` and
`sector` to their own source
(`test_the_summary_hands_the_rule_down`,
`tests/test_extraction_trust.py:337`), and a document with no tuples
still gets a line, all levels at zero
(`test_a_document_with_nothing_in_it_still_has_a_summary`,
`tests/test_extraction_trust.py:290`). `parameter_states`, called from
`runner.py` alone, records one state per parameter of the spec: `read`,
`unbacked`, `exhausted` (a run cut short document wide, not per
parameter) or `unstated` (`trust.py:315-351`;
`test_parameter_states_names_every_parameter_of_the_spec`,
`tests/test_extraction_trust.py:417`).

## What `docpipe/extraction/trust.py` says

<details>
<summary><code>docpipe/extraction/trust.py</code></summary>

trust.py: Grades every harvested value by how far the run can stand
behind it.

Every accepted tuple is verified: its number is in its quote, its
quote is in a shown source, and every coordinate names the passage it
was read in. That is a floor, not a grade. Two values that both clear
it can still differ by a lot:

  one has every coordinate read off its own table, in the document's
  own text
  one has its year read off the caption of a different table three
  pages away

The second case is the failure this module addresses, and before this
module existed nothing downstream could tell the two apart. A reader
of the graph saw two numbers with no way to compare their reliability.

The module computes a deterministic level per value, from what the
harvest already records: no model call, no second opinion, no
threshold anybody tuned.

  A  the document's own text states it, every coordinate read, every
     passage local
  B  the same, but read out of a table transcription or a figure
     description (a model's reading of a picture), or out of a
     document whose pages had no text layer and were transcribed page
     by page
  C  something is off: a passage that belongs to another row, a
     coordinate the run gave up on, a repaired quote, a computed
     number, a contested identity

The reasons form a closed list, because a reason nobody can enumerate
is a reason nobody can count. What makes a value a C is what a curator
should examine.

A value can be read a second time (`review.py`), and what that reading
came to is recorded here as a mark. It never raises a level: the
second reading uses the same model over a narrower window, so an
agreement states that the reading is self-consistent, not that the
passage it cites belongs to the row.

Measured on Kassel's 559 tuples, which is why the levels are cut at
this point and not elsewhere: 527 of 559 tuples came out of a table or
figure image, so image origin alone separates nothing and is not by
itself a warning. What did separate, on that run: 370 of 455 year
readings cited a passage outside the row's own table and its section,
as did 87 percent of the area readings, 47 percent of the scenarios,
49 percent of the sectors, and 13 percent of the carriers, the one
coordinate the row itself carries directly.

That run had no evidence rule at all, so reading those numbers
requires care. The spec now sets the rule per axis (own, local or
any), and the harvest enforces it: a coordinate that breaks its own
rule comes out `unbacked`, never `read`. On a harvest written under
the rule, a passage outside the row's own source is a finding only
for an axis whose rule is `own`; for the others it is the rule
working as written. Judging all seven axes by the strictest rule
would report every legal reading as a doubt, a signal that fires
across the whole corpus and separates nothing, the same mistake image
origin was kept out of the reasons for.

Hence `own`: the set of axes a reader may hold to the row's own
source. It is a property of the spec, so the caller passes it in;
without it, every read coordinate is judged, matching the treatment
of a harvest written before the rule existed.

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
- `^(nonlocal|exhausted|unbacked):[a-z_]+$`

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
