"""Extraction stage wiring: the kwp spec, the frame, and what a plan says
about itself."""
from pathlib import Path

SPEC_PATH = Path(__file__).with_name("extraction_spec.json")

# No coordinate closes a row of this profile: every value is asked all its
# coordinates and the graph keeps what it holds (owner decision 2026-11-04).
# A quantity the ontology has no class for yet (an avoided emission) is read
# like any other and reaches the graph once a class exists (owner decision
# 2026-11-03).
#
# How many lines a piece holds is a number of the flow (`flow.json`, owner
# decision 2026-11-08, f: eight; twelve only measured where a probe loses
# values).

# What a plan settles for all its values and its own years
# (`plan_fields`) stands in the spec, with the texts a request shows of each
# (owner decision 2026-11-10).


def document_context(conn, document_id: int) -> dict:
    """What this plan says about itself, for the sentence it is searched with.

    The municipality, because a plan writes its own name into headings,
    captions and table titles, and a search anchor that carries it ranks this
    plan's own sections above the boilerplate every plan shares. It lives in
    the catalog join and in no query the core makes, so the core asks the
    profile for it rather than growing a second idea of what a document is.

    Missing metadata is not an error here. The anchor is written from the
    ontology annotation either way and this only makes it sharper.
    """
    try:
        row = conn.execute("""
            SELECT m.name
            FROM Documents d
            LEFT JOIN DocumentMeta dm  ON dm.document = d.id
            LEFT JOIN Municipalities m ON dm.municipality_ags = m.ags
            WHERE d.id = ?
        """, (document_id,)).fetchone()
    except Exception:
        return {}
    # By position. Whether a connection carries a row factory is the caller's
    # business, and a hook that only works on one of the two shapes is a hook
    # that works until somebody passes a plain connection.
    name = row[0] if row else None
    return {"name": name} if name else {}


# Which coordinates belong to the DOCUMENT and not to the row. A plan has
# three scenario containers and a handful of reference years, and they stand
# in headings, captions and column headers -- the carrier and the sector stand
# in the table row itself and are different in every cell. So these two are
# found ONCE, before any value, and every value request afterwards asks for
# one of the pairs that were really found.
#
# Not a cross product. A plan with a target scenario for 2030/2035/2040/2045
# and an inventory for 2022 has five pairs, not twenty.
#
# Measured on M3, this is what it replaces: the year axis produced 1,849
# refusals against 0 readings, because every window after the first excluded
# the row's own source and only that one could carry the year.
FRAME = ("scenario", "year")


# Which frame pairs are the plan's own state and which its target stands in
# the spec, at the plan fields `base_year` and `target_year` (`of`, owner
# decision 2026-11-10). Their years are the plan's base and target years, each
# with the frame's quote that prints it: a row whose table says only
# "Basisjahr", "Ist-Zustand", "Bilanzjahr" or "Zieljahr" answers one of them
# and cites the passage with that word; the number is proven by the frame's
# passage (owner decisions 2026-09-22 and 2026-10-06, the model chooses among
# them). A run asks a plan its base and target years itself (the same plan
# fields); a pass over a stored harvest takes them from the stored pairs by
# that rule. corpus_m5 dropped 127,233 year answers whose wording stood in
# their quote and whose number did not, "Basisjahr" among the most common, and
# a later harvest about 14,500 for the target, "Zieljahr" 12,369 of them.

# What counts as a year here (a zone number printed beside a value, 169002,
# was answered as its year; owner decision 2026-11-01), what a value stated
# for a span of years takes on each of its rows (owner decision 2026-11-07:
# "als ca. für jedes distinkte Jahr erfassen") and how the documents write
# the decimal ("3,251 GWh" is 3.251 here) are rules: rules.json beside this
# file (`year_range`, `span_marks`, `decimal_mark`).

# The language tag of the ontology's alternative labels that the vocabulary
# snapshot keeps for this profile, the words its spec is held against.
ALT_LABEL_LANGUAGE = "de"

# The language of the core's contract text in this profile's prompts: the
# parts files of its own that name a template (`template: rows`) are put
# together with the template of this language. Not inherited by a profile that
# extends this one with parts files of its own.
CONTRACT_LANGUAGE = "de"


# What the preflight (`docpipe preflight`) holds this profile's prompts to,
# beyond the keys the stage reads by name: a wording the run depends on. The
# prompts are in the profile's language, so the passage is too.
# (what is checked, prompt, passage, True: has to be there, False: must not)
PROMPT_CHECKS = ()


# What the stage says to the model outside its prompts (why an answer was not
# taken, what was wrong with a reply) is a file beside them:
# prompts/extraction/phrases.json (docpipe/phrases.py).


def shapes_files() -> list:
    """The MHPKG shapes of the last `vocabulary --refresh`, or none: the
    files the spec is held against (`docpipe compile diff`, the preflight,
    the Sources tab of `docpipe edit`)."""
    from profiles.kwp import vocabulary   # lazy: it reads the spec
    return [path for path in vocabulary.shapes() if path.is_file()]


def spec_for_shapes(raw: dict) -> dict:
    """The spec as the shapes name its properties: this profile's `kg`
    blocks name schema slots and classes (`"schema_slot":
    "refers_to_energy_carrier"`), which the MHPKG schema turns into the
    predicate and class its shapes carry (`mhpkg.resolve`)."""
    from profiles.kwp import mhpkg
    return mhpkg.resolve(raw, mhpkg.load())
