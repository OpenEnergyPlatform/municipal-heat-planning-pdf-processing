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
stands is no check and no grade
(`test_where_a_coordinates_passage_stands_is_not_a_reason`,
`tests/test_extraction_trust.py:73`). Neither check is the trust level: a
value read out of the document's own text and one read out of a picture,
with a coordinate the run gave up on, both clear it. `trust.py`'s `trust`
function computes a second, finer verdict: no model call, no corroborating
review, no tuned threshold (`trust.py:112-130`).

## What moves a value between the three levels

Level `A` adds nothing beyond that minimum check: every coordinate read,
no image involved
(`test_a_value_read_off_its_own_table_in_the_plans_text_is_an_a`,
`tests/test_extraction_trust.py:45`). A value drops to `B` for two
independent reasons: its evidence tier is `verify.TIER_VISUAL`, an owner
kind outside `verify.TEXT_KINDS` such as a table transcription or a figure
description (`verify.py:43-45,522-532`;
`test_a_reading_out_of_a_picture_is_a_b_and_not_a_warning`,
`tests/test_extraction_trust.py:51`); or the document had no text layer
and was transcribed page by page, passed to `trust()` as a `transcribed`
keyword read from the `page_text_transcribed` column
(`profiles/kwp/kg.py:408-410`, `:571`, `:662`) and capping a row at `B` even with
tier `TIER_TEXT` (`trust.py:121-128`;
`test_the_same_value_from_a_transcribed_plan_never_reaches_a`,
`tests/test_extraction_trust.py:61`). On the 559 tuples the levels were
cut at, 527 came out of a table or figure image, so image origin alone is
not a warning (`trust.py:39-41`).

A value falls to `C` only when something else is off: an `unbacked`,
`exhausted` or `unanswered` coordinate, a repaired quote, a computed
number, or a contested identity (`reasons`, `trust.py:77-109`;
`test_every_doubt_the_harvest_records_lowers_the_level`,
`tests/test_extraction_trust.py:94`;
`test_a_contested_identity_is_a_c_even_with_everything_else_right`,
`tests/test_extraction_trust.py:100`). A passage outside the row's own
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
unless forced, so a row is reviewed once
(`test_only_the_values_nobody_can_stand_behind_are_reviewed`,
`tests/test_extraction_review.py:101`; `test_a_row_is_reviewed_once`,
`tests/test_extraction_review.py:114`). The second reading writes exactly
one of three flags: `review:agree` when it matches the stored value,
`review:disagree` when it does not, `review:unbacked` when its own answer
cannot be checked against the narrowed window (`review.py:222-226`;
`test_agreement_writes_the_flag_and_moves_nothing_else`,
`tests/test_extraction_review.py:281`). None of the three raises the
level: an agreement is recorded as `corroborated`, since the second
reading checks self-consistency, not that it is right
(`trust.py:116-120`; `test_a_corroborated_row_is_still_a_c`,
`tests/test_extraction_review.py:305`). A disagreement becomes a
`review:disagree` reason instead, a fact a curator can count
(`test_a_disagreement_is_a_reason_a_curator_can_count`,
`tests/test_extraction_review.py:322`).

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
refused at import (`trust.check_prose`, `trust.py:203-215`;
`test_every_profile_words_every_mark_the_core_can_produce`,
`tests/test_extraction_trust.py:191`;
`test_a_table_that_words_a_mark_that_is_not_one_is_refused`,
`tests/test_extraction_trust.py:207`). The reason tokens are never
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
no tuples still gets a line, all levels at zero
(`test_a_document_with_nothing_in_it_still_has_a_summary`,
`tests/test_extraction_trust.py:292`). `parameter_states`, called from
`runner.py` and `topup_parameter.py`, records one state per parameter of the spec: `read`,
`unbacked`, `exhausted` (nothing of the document was answered, or a cut
request held one of the parameter's own ranked sources, or, without that
source list or a source named on the request, any cut at all) or
`unstated` (`trust.py:279-335`;
`test_parameter_states_names_every_parameter_of_the_spec`,
`tests/test_extraction_trust.py:300`).
