"""
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
"""
from __future__ import annotations

from typing import Optional

from .fields import EXHAUSTED, READ, SAID_UNSTATED, UNBACKED
from .verify import TIER_TEXT

LEVEL_A = "A"
LEVEL_B = "B"
LEVEL_C = "C"

# What a second reading of one value came to. The same model reads a
# window that is a strict subset of the one the sweep already walked,
# so it is a self-consistency check and not an independent reading,
# and only the middle one is a reason: a disagreement is a fact about
# the value, while an agreement and an unbackable answer are facts
# about the review. The last is recorded so the row is not asked a
# third time and so the rate is countable: a review that comes back
# unbacked on most rows points to a broken prompt, and nothing else
# in the harvest reports that.
REVIEW_AGREE = "review:agree"
REVIEW_DISAGREE = "review:disagree"
REVIEW_UNBACKED = "review:unbacked"

# Flags that document how the value itself was arrived at. Each is a
# reason on its own, and each is a different thing for a curator to
# check.
FLAG_REASONS = {"quote_repaired": "repaired", "computed": "computed",
                "not_located": "not_located",
                REVIEW_DISAGREE: "review:disagree"}


def _owners(row: dict) -> set:
    """The sources a coordinate of THIS row may have been read in.

    Its own table or section, and the section that table stands in. The same
    pair `pipeline.evidence_is_local` enforces for an axis with evidence
    "own" -- read here from what the harvest wrote down, because by the time
    a graph is built the window is long gone.
    """
    provenance = row.get("provenance") or {}
    out = set()
    kind, owner = provenance.get("owner_kind"), provenance.get("owner_id")
    if kind and owner is not None:
        out.add((kind, owner))
    parent = provenance.get("parent_section")
    if parent is not None:
        out.add(("section", parent))
    return out


def reasons(row: dict, *, conflict: bool = False, transcribed: bool = False,
            own: Optional[frozenset] = None) -> list:
    """Every reason this value is not an A, in a fixed order.

    An empty list means the harvest sees nothing wrong with the value.

    `own` is (parameter uri, axis name) for the axes whose evidence
    rule is `own` (`spec.own_evidence`). Only those axes are held to
    the row's own source; an axis the spec lets read a page away was
    already judged where the pages were, and reporting it here would
    mark a legal reading as a doubt. A value of None judges every
    axis, matching the treatment of a harvest written before the rule
    existed.
    """
    found: list = []
    local = _owners(row)
    parameter = row.get("parameter")
    for key in sorted(row):
        if not key.endswith("_state"):
            continue
        name = key[:-len("_state")]
        state = row[key]
        if state in (EXHAUSTED, UNBACKED):
            found.append(f"{state}:{name}")
            continue
        if state != READ:
            # Derived, "the document does not say it", or never asked
            # because the row left at the gate: none of those is a
            # doubt about the reading. They are findings about the
            # document or about this run's scope, and are recorded as
            # such elsewhere.
            continue
        if own is not None and (parameter, name) not in own:
            continue
        source = row.get(f"{name}_source")
        if local and source and tuple(source) not in local:
            found.append(f"nonlocal:{name}")
    for flag in row.get("flags") or []:
        reason = FLAG_REASONS.get(flag)
        if reason and reason not in found:
            found.append(reason)
    if conflict:
        found.append("conflict")
    if transcribed:
        # Not a doubt about the reading, but a doubt about the page it
        # was read from: this document had no text layer and a model
        # transcribed it, so the section text is itself a reading. Its
        # own reason, because it caps the level rather than condemning
        # the value.
        found.append("page_transcribed")
    return found


def trust(row: dict, *, conflict: bool = False, transcribed: bool = False,
          corroborated: bool = False, own: Optional[frozenset] = None) -> dict:
    """{level, reasons, image_origin, corroborated} for one accepted tuple."""
    why = reasons(row, conflict=conflict, transcribed=transcribed, own=own)
    # The review's own answer, read off the row rather than passed in: the
    # serializers build a verdict from a stored tuple and have no second
    # reading to hand. It never enters `hard`, so it never lifts a level --
    # see the module docstring.
    corroborated = corroborated or REVIEW_AGREE in (row.get("flags") or [])
    hard = [r for r in why if r != "page_transcribed"]
    image = row.get("tier") != TIER_TEXT
    if hard:
        level = LEVEL_C
    elif image or transcribed:
        level = LEVEL_B
    else:
        level = LEVEL_A
    return {"level": level, "reasons": why, "image_origin": image,
            "corroborated": bool(corroborated)}


# The pieces of a trust line, in the order they are said. Names, not words:
# the level is a fact about the harvest, the sentence is a fact about the
# reader, and the two corpora do not share a reader. One profile serves German
# heat plans, the other English scenario studies, and the core cannot know
# which. So a profile words each of these in its own `kg.TRUST_PROSE`, and
# `MARKS` is what that table is held against: a mark added here is a missing
# key there, reported at import, rather than a line nobody notices missing.
#
# `image_origin` and `image_origin_named` are one mark with and without its
# argument. Split here so a profile's half stays a table of strings instead of
# growing a conditional.
MARKS = ("level", "image_origin", "image_origin_named", "corroborated",
         "reasons", "review")

# Inside the reasons mark. The reason tokens themselves are never
# translated: they are a closed machine vocabulary, anchored by
# schema.TRUST_REASONS, and a curator greps for `nonlocal:carrier` in
# either corpus.
REASON_JOIN = ", "


def marks(verdict: dict, row: Optional[dict] = None) -> tuple:
    """The verdict as ordered (mark, arguments) pairs, only those that apply.

    The arguments come out already rendered to strings, because the profile's
    half is a table of format strings and a table cannot join a list.

    `row` carries the one thing the verdict does not: the image the value was
    read out of. Without it the line says a picture was involved but not which
    picture, which is the difference between a warning and a lead.
    """
    out = [("level", {"level": verdict["level"]})]
    if verdict.get("image_origin"):
        image = ((row or {}).get("provenance") or {}).get("image")
        out.append(("image_origin_named", {"image": image}) if image
                   else ("image_origin", {}))
    if verdict.get("corroborated"):
        out.append(("corroborated", {}))
    if verdict["reasons"]:
        out.append(("reasons",
                    {"reasons": REASON_JOIN.join(verdict["reasons"])}))
    if verdict["level"] == LEVEL_C:
        out.append(("review", {}))
    return tuple(out)


def check_prose(prose: dict, where: str) -> dict:
    """`prose` back, or raise if it does not word every mark exactly once.

    Checked when the serializer is imported and not at the first C of a corpus
    run: a mark nobody worded is one missing piece of one comment line in one
    document out of a thousand, and nothing reads that.
    """
    missing = sorted(set(MARKS) - set(prose))
    extra = sorted(set(prose) - set(MARKS))
    if missing or extra:
        raise LookupError(f"{where} words {missing} nowhere and {extra} for "
                          f"no mark of trust.MARKS")
    return prose


def render(verdict: dict, prose: dict, *, join: str,
           row: Optional[dict] = None) -> str:
    """One line a reader of the graph can act on, in the profile's words.

    The pieces and their order are the core's, every character is the
    profile's. `row` is keyword-only although the sentence it replaces took it
    second: a call site left over from then raises rather than quietly losing
    the image name.
    """
    return join.join(prose[mark].format(**args)
                     for mark, args in marks(verdict, row))


def document_summary(document_id, tuples, refusals,
                     *, own: Optional[frozenset] = None) -> dict:
    """One `kind: summary` line per document: the harvest's view of its run.

    A corpus of 1.082 plans cannot be read tuple by tuple, and the question a
    reader actually has, "how much of this plan can I use", has no answer
    in a file of 559 rows. So every harvest file ends with the distribution
    over its own values.

    Called a summary and not a plan line because the trace schema already
    has a `plan` kind, and there it means a planned source. Two files, two
    meanings, one word is how a reader ends up counting the wrong thing.

    What it cannot say is in here by its absence. A contested identity is
    decided by the serializer, when two tuples turn out to mint the same
    value IRI, and a second reading is a later pass: neither exists yet when
    this line is written, so neither is counted. `trust` takes them as
    arguments for exactly that reason, and the graph side recomputes the
    levels with them. The levels here are the floor: a value that is a C
    already will not become an A later.

    `own` is passed straight to `trust`; see there for why an axis the spec
    lets read a page away is not held to the row's own source.
    """
    levels = {LEVEL_A: 0, LEVEL_B: 0, LEVEL_C: 0}
    why: dict = {}
    image = 0
    for row in tuples:
        verdict = trust(row, own=own)
        levels[verdict["level"]] += 1
        image += bool(verdict["image_origin"])
        for reason in verdict["reasons"]:
            why[reason] = why.get(reason, 0) + 1
    return {"document_id": document_id, "tuples": len(tuples),
            "refusals": len(refusals), "levels": levels,
            "reasons": {k: why[k] for k in sorted(why)},
            "image_origin": image}


# What a whole PARAMETER came to in one document, as against what one
# coordinate of one row came to. Four of the seven row states, because the
# other three are statements about a coordinate that was asked and this is a
# statement about a question that may never have been reached.
PARAMETER_STATES = (READ, UNBACKED, EXHAUSTED, SAID_UNSTATED)


def parameter_states(spec, tuples: list, refusals: list, *,
                     harvested: int = 0,
                     answered: Optional[int] = None) -> list:
    """One state per parameter of the spec, in spec order.

    Every state this pipeline writes is a state of a ROW: `apply_derived`,
    `merge_field`, `apply_frame` and `mark_unanswered` all loop over rows. So a
    parameter that produced no row leaves no byte anywhere, and "the document
    does not name its planning office" and "we never got round to asking" are
    the same empty file. Measured on Kassel: `planning_organisation` came back
    with 0 tuples and no state at all.

    `exhausted` is the one that is a fact about the RUN and not about the
    document, and it is document-wide rather than per parameter: under the
    document-level plan there is no per-parameter run signal to read, the
    report keys its rounds by the literal string "document". So a truncated
    run marks every unanswered parameter exhausted together, which is the
    honest reading of "we stopped before the end".
    """
    cut = bool(harvested) and (answered == 0 or any(
        (r.get("claim") or {}).get("_harvest_failed") for r in refusals))
    out = []
    for parameter in getattr(spec, "parameters", ()):
        uri = parameter.uri
        mine = sum(1 for t in tuples if t.get("parameter") == uri)
        refused = sum(1 for r in refusals if r.get("parameter") == uri)
        if mine:
            state = READ
        elif refused:
            state = UNBACKED
        elif cut:
            state = EXHAUSTED
        else:
            state = SAID_UNSTATED
        out.append({"parameter": uri, "state": state,
                    "tuples": mine, "refusals": refused})
    return out
