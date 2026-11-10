"""Extraction stage wiring: the kwp spec, the slice gate, the frame, and what
a plan says about itself."""
import json
from pathlib import Path

SPEC_PATH = Path(__file__).with_name("extraction_spec.json")

# Which coordinates decide whether a value belongs in the graph at all, in the
# order they are asked, and which answers keep the row. They are asked FIRST
# and alone: a row that falls out here costs three requests instead of eight.
# Measured on the 20-plan draft, of 6,763 harvested tuples the serializer
# dropped 1,554 for a quantity the graph does not hold.
#
# THE SCENARIO NO LONGER GATES. It did, and it was the bigger half: 2,510 of
# those 6,763 tuples were dropped for being a status quo, a trend or a
# potential rather than the target scenario, and dropping them was a decision
# about the graph rather than about the plan. MHPO names all three
# (aggregated inventory analysis MHPO_00020005, aggregated potential analysis
# MHPO_00020006) and OEO names the reference scenarios, so a heat plan's
# inventory belongs in the graph as much as its target does and the row has
# to be asked its coordinates to get there.
#
# What still gates is the quantity, and only through its out: entries: those
# are deliberate non-classes the model chose (a share, a specific figure), and
# no ontology term is waiting for them.
#
# None means "any class the graph takes", which is every entry that does not
# start with out:. A tuple names the answers that keep the row.
#
# The year closes no row and stands here for its order alone: every axis behind
# it reads with the year known. Asked side by side, up to 1,368 tuples of
# corpus_m7_100 took the scenario of a chart's title for a year it does not
# hold (owner decision 2026-11-02).
#
# Quantities of their own the ontology has no class for yet are read on every
# axis into the harvest, and reach the graph once a class does (owner decision
# 2026-11-03). Every other out: entry still closes its row. Generation, useful
# energy and a saving left this list on 2026-11-07: each has an energy unit,
# so each is an OEO energy value, and the list offers that class.
READ_IN_FULL = ("out:avoided",)


def kept_quantities() -> tuple:
    """Every class of the spec's quantity lists, and READ_IN_FULL."""
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    entries = {uri for parameter in spec["parameters"]
               for uri in ((parameter.get("axes") or {}).get("quantity")
                           or {}).get("vocabulary", {})}
    return tuple(sorted(uri for uri in entries
                        if not uri.startswith("out:") or uri in READ_IN_FULL))


SLICE = {"quantity": kept_quantities(), "year": None}


# Lines of a piece the plan is read in (owner decision 2026-11-08, f: eight;
# twelve only measured where a probe loses values).
CHUNK_UNITS = 8

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


# Which frame pairs are the plan's own state. Their years are the plan's base
# years, each with the frame's quote that prints it. A row whose table says
# only "Basisjahr", "Ist-Zustand" or "Bilanzjahr" answers one of them and
# cites the passage with that word; the number is proven by the frame's
# passage (owner decision 2026-09-22, the model chooses among them). corpus_m5
# dropped 127,233 year answers whose wording stood in their quote and whose
# number did not, "Basisjahr" among the most common.
BASE_YEAR = {"scenario": "status_quo"}

# What counts as a year here: a zone number printed beside a value (169002)
# was answered as its year, in the frame and on a row (owner decision
# 2026-11-01).
YEAR_RANGE = (1900, 2100)

# Which frame pairs are the plan's target. Their years are the plan's target
# years, each with the frame's quote that prints it. A row whose table says
# only "Zieljahr" answers one of them the same way (owner decision
# 2026-10-06, the model chooses among them): the current harvest dropped
# about 14,500 year answers whose quote carried the plan's word for its
# target and not the number, "Zieljahr" 12,369 of them.
TARGET_YEAR = {"scenario": "target"}

# What a value stated for a span of years takes on each of its rows, one per
# year of the span (`reading.span_rows`, owner decision 2026-11-07: "als ca.
# für jedes distinkte Jahr erfassen"): "im Mittel der Jahre 2019 bis 2021"
# is the value for 2019, 2020 and 2021, each approximate.
SPAN_MARKS = {"qualifier": "out:approximate"}


# How the documents write the decimal. It decides what the digits leave
# open: "3,251 GWh" is 3.251 here, and "1.234" is 1234.
DECIMAL_MARK = ","

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
