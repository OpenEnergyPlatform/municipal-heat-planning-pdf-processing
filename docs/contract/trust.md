# How much of a value the run can stand behind

Generated from `docpipe/extraction/trust.py` and the published schema by `scripts/build_docs.py`.

trust.py – How much of a value the run can actually stand behind.

Every accepted tuple is verified: its number is in its quote, its quote is in
a shown source, every coordinate names the passage it was read in. That is a
floor, not a grade. Two values that both clear it can still differ by a lot:

  one has every coordinate read off its own table, in the plan's own text
  one has its year read off the caption of a different table three pages away

The second is the failure this whole repair is about, and until now nothing
downstream could tell the two apart. A reader of the graph saw two numbers.

So: a deterministic level per value, computed from what the harvest already
records. No model, no second opinion, no threshold anybody tuned.

  A  the plan's own text says it, every coordinate read, every passage local
  B  the same, but read out of a table transcription or a figure description
     -- which is a model's reading of a picture -- or out of a plan whose
     pages had no text layer at all and were transcribed page by page
  C  something is off: a passage that belongs to another row, a coordinate
     the run gave up on, a repaired quote, a computed number, a contested
     identity

The reasons are a closed list, because a reason nobody can enumerate is a
reason nobody can count. What makes a C is what a curator should look at.

A value can be read a second time (`review.py`), and what that came to is
recorded here as a mark. It never lifts a level: the second reading uses the
same model over a narrower window, so an agreement says the reading is
self-consistent and not that the passage it cites belongs to the row.

Measured on Kassel's 559 tuples, which is why the levels are cut here and not
somewhere else: 527 of 559 came out of a table or figure image, so image
origin alone separates nothing and is not a warning. What did separate, on
that run: 370 of 455 year readings cited a passage outside the row's own
table and its section, 87 percent of the area readings, 47 percent of the
scenarios, 49 percent of the sectors -- and 13 percent of the carriers, which
is the one coordinate the row itself really carries.

That run had no evidence rule at all, and this is where the reading of those
numbers has to be careful. The spec now sets the rule per axis -- own, local
or any -- and the harvest enforces it: a coordinate that broke its own rule
comes out `unbacked`, never `read`. So on a harvest written under the rule,
a passage outside the row's own source is only a finding for an axis whose
rule is `own`; for the others it is the rule working as written. Judging all
seven by the strictest one would report every legal reading as a doubt, which
is a signal that fires on the corpus and separates nothing -- the exact
mistake image origin was kept out of the reasons for.

Hence `own`: the set of axes a reader may hold to the row's own source. It
is a property of the spec, so the caller passes it; without it every read
coordinate is judged, which is right for a harvest from before the rule.

Author: Felix Vossel

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
