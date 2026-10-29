"""Extraction stage wiring: where the ar6 spec lives, and the lists that are
only closed once a document is named.

Two of the ar6 fields have a finite set of correct answers, but the set is not
the same for every publication, so it cannot sit in the spec file:

  scenario / scenario_label  the AR6 scenarios THIS publication documents.
                             The corpus holds 1389 of them, one publication
                             documents up to 146, and the model has to pick
                             from that publication's own list.
  scenario_region            the 249 study regions the OEKG actually uses,
                             narrowed to those the document names at all.

The narrowing is not a guess. Every claim has to quote its source verbatim, and
the sources are exactly the section, table and figure texts scanned here, so a
region whose name appears nowhere in them could never have been quoted. What is
dropped is unreachable, not merely unlikely — and dropping it keeps the prompt
at the handful of countries a paper mentions instead of all 249.

Both lists carry `out:` entries, and they are the point of this file as much as
the real entries are. A closed list without an escape hatch does not stop the
model from answering; it stops it from answering CORRECTLY, and what comes back
is the nearest entry that is not quite right. The OEKG knows 249 countries and
no aggregates, while an AR6 scenario is usually global — so without
a world entry the honest answer to "which region" does not exist in the list,
and a paper about worldwide emissions that happens to mention Germany once
invites "Germany". The world and the groups of countries are entries of the
list now and are written as their member countries. The same holds for a run identifier: naming a family is not
naming a run, and the model needs a way to say so that is not silence.

Silence is the other half of the argument. An empty field already meant
"unmapped" and was already counted, but it meant three different things at
once — nothing fitted, the model did not look, the reply was cut short. A
chosen `out:` entry means exactly one of them, and it is the one worth
counting.
"""
import json
import re
import sqlite3
from pathlib import Path

SPEC_PATH = Path(__file__).with_name("extraction_spec.json")
REGIONS_PATH = Path(__file__).with_name("regions.json")
AGGREGATES_PATH = Path(__file__).with_name("region_aggregates.json")
WORLD = "aggregate:World"

# Every label is matched on word boundaries, short or long. "US" hides inside
# "thus" and "UK" inside "Ukraine", but so does Niger inside Nigeria, India
# inside Indiana and Chile inside Chilean — and those are the expensive ones,
# because they put a wrong country in front of the model as a valid choice.
# The cost is the other direction: a paper that only ever writes "Chilean" no
# longer offers Chile. That is the cheaper mistake, and it is a visible one —
# the model then has to choose the out: entry, which is counted.
_WORD = r"(?<!\w){}(?!\w)"


# The entries that are not a thing in the graph. `kg.py` refuses to mint an IRI
# or a link from any of them (NOT_IN_GRAPH, one definition for both profiles in
# docpipe/extraction/graphkit.py) and counts them by name.

# The first label is the answer token: runner._parameter_payload renders a
# choice list as {labels[0]: labels[1:]} and the prompt says to copy it
# character for character. So labels[0] is short and quotable, and the
# explanation is an alternate — value_to_uri() maps every label, so both
# spellings resolve. The long gloss first was a mistake: an answer nobody can
# retype without a slip is an answer that arrives as an unmapped wording, and
# an unmapped wording is exactly what these entries exist to prevent.
#
# A scenario is global far more often than national, and the OEKG's region list
# is 249 countries with no aggregate — no World, no EU27, no OECD, no R5.
# The groups are entries now (`region_aggregates.json`, from the AR6
# database's regions and the UN's M49): a group is written as its member
# countries. "several regions" stays for a group neither source has.
REGION_OUT = {
    "out:multiregion": ["several regions", "several countries", "EU27", "OECD",
                        "several countries or a group the list does not "
                        "carry"],
    "out:other": ["other region",
                  "something else that is not a country of the list"],
}

# The AR6 identifiers are finer than the language of the papers: the pilot's
# 146-scenario document writes "NPi", and the database has EN_NPi2020_300f,
# _400 and _3000. That wording names a family, not a run, and `ambiguous()` in
# kg.py drops the link when it happens. It cannot tell that case apart from a
# scenario the publication simply does not have in AR6 — these two can.
SCENARIO_OUT = {
    "out:family": ["scenario family", "family",
                   "a scenario family or a description that fits several "
                   "runs and none of them exactly",
                   "a scenario family, not a single run"],
    "out:not_documented": ["not in AR6", "not in the AR6 list",
                           "a scenario of this publication that is not in "
                           "its AR6 list"],
}


def _regions() -> dict:
    return json.loads(REGIONS_PATH.read_text(encoding="utf-8"))


def aggregates() -> dict:
    """{key: {labels, members, ...}}, the groups of countries of the last
    refresh; empty before one has written them."""
    if not AGGREGATES_PATH.is_file():
        return {}
    return json.loads(AGGREGATES_PATH.read_text(encoding="utf-8"))


def _document_text(conn: sqlite3.Connection, document_id: int) -> str:
    """Everything a harvest of this document could ever quote from."""
    # The captions belong in here as much as the bodies do: a harvest quotes
    # the caption of a table as readily as its cells, so a country named only
    # in "Figure 3: Emissions in India" is quotable — and if the narrowing has
    # not seen it, the model is offered no class for it and answers with a
    # wording nobody can resolve.
    rows = conn.execute(
        "SELECT s.content FROM Sections s WHERE s.document = ? "
        "UNION ALL "
        "SELECT t.markdown FROM Tables t JOIN Sections s ON t.section = s.id "
        "WHERE s.document = ? "
        "UNION ALL "
        "SELECT t.caption FROM Tables t JOIN Sections s ON t.section = s.id "
        "WHERE s.document = ? "
        "UNION ALL "
        "SELECT i.description FROM Images i JOIN Sections s ON i.section = s.id "
        "WHERE s.document = ? "
        "UNION ALL "
        "SELECT i.caption FROM Images i JOIN Sections s ON i.section = s.id "
        "WHERE s.document = ?",
        (document_id,) * 5,
    ).fetchall()
    return "\n".join(str(r[0]) for r in rows if r[0])


def _acronym(label: str) -> bool:
    """A label that is only a word when its capitals are: US, UK, USA, U.S."""
    return len(label) <= 4 and label.upper() == label and label.lower() != label


def _mentioned(text: str, labels: list) -> bool:
    lowered = text.casefold()
    for label in labels:
        # "US" casefolds onto the English pronoun, and these publications are
        # English, so every one of them would be offered the United States as
        # a class next to the out: entries — reintroducing exactly the pull
        # those entries exist to remove. An all-caps acronym is matched with
        # its capitals; everything else is matched casefolded.
        if _acronym(label):
            if re.search(_WORD.format(re.escape(label)), text):
                return True
            continue
        needle = label.casefold()
        if needle not in lowered:
            continue
        if re.search(_WORD.format(re.escape(needle)), lowered):
            return True
    return False


def document_scenarios(conn: sqlite3.Connection, document_id: int) -> dict:
    """The AR6 scenarios this publication documents, as a choice list.

    Keyed by the AR6 name itself rather than an invented IRI: the name is the
    identity the corpus links against, and kg.py resolves it the same way.
    """
    rows = conn.execute(
        "SELECT sc.name FROM Scenarios sc "
        "JOIN DocumentScenarios ds ON ds.scenario = sc.id "
        "WHERE ds.document = ? ORDER BY sc.name",
        (document_id,),
    ).fetchall()
    return {str(r[0]): [str(r[0])] for r in rows if r[0]}


def document_regions(conn: sqlite3.Connection, document_id: int) -> dict:
    """The countries and groups of countries this document names.

    The world is always offered, as `global` was. A group of the AR6
    database is also offered by its bare name where the document names its
    family: a paper writes "the R10 regions" and then "Europe".
    """
    groups = aggregates()
    out = ({WORLD: groups[WORLD]["labels"]} if WORLD in groups else {})
    text = _document_text(conn, document_id)
    if not text:
        return out
    out.update({iri: labels for iri, labels in _regions().items()
                if _mentioned(text, labels)})
    for key, group in groups.items():
        labels = group["labels"]
        family = group.get("family")
        named = labels + ([labels[0].rsplit(" (", 1)[0]]
                          if family and _mentioned(text, [family]) else [])
        if key not in out and _mentioned(text, named):
            out[key] = labels
    return out


def document_axes(conn: sqlite3.Connection, document_id: int) -> dict:
    """Per-document choice lists, keyed by axis name and by parameter uri.

    The out: entries are appended unconditionally, so every list exists even
    when the narrowing finds nothing. That case is not hypothetical — a
    publication with no runs in DocumentScenarios, or one that names no country
    at all, used to leave the field with no list, and a field with no list is
    free text again.
    """
    scenarios = dict(document_scenarios(conn, document_id))
    scenarios.update(SCENARIO_OUT)
    regions = dict(document_regions(conn, document_id))
    regions.update(REGION_OUT)
    return {
        "scenario": scenarios,          # the coordinate on the other fields
        "scenario_label": scenarios,    # and the value of the field itself
        "scenario_region": regions,
    }

# How the documents write the decimal. It decides what the digits leave
# open: "3,251" is 3251 here, and "1.234" is 1.234.
DECIMAL_MARK = "."

# What a publication says about itself, asked once more on its own over the
# opening of the document, besides wherever else it is read. Asked among
# forty other rows it was left out: the title in 17 documents, the abstract
# in 132 of 164, the date in 60, though nearly every one prints them there.
FRONT_PAGE_PARAMETERS = ("publication_title", "publication_author",
                         "publication_date", "publication_doi",
                         "publication_abstract")

# The language tag of the ontology's alternative labels that the vocabulary
# snapshot keeps for this profile, the words its spec is held against. The
# publications are English, and so are the words offered for them.
ALT_LABEL_LANGUAGE = "en"

# The language of the core's contract text in this profile's prompts (see the
# same constant of the kwp profile).
CONTRACT_LANGUAGE = "en"


# What the preflight (`docpipe preflight`) holds this profile's prompts to,
# beyond the keys the stage reads by name: a wording the run depends on. The
# prompts are in the profile's language, so the passage is too.
# (what is checked, prompt, passage, True: has to be there, False: must not)
PROMPT_CHECKS = (
    ("field prompt asks one field", "extraction/field",
     "EXACTLY ONE field", True),
    ("rows prompt no longer fixes one parameter", "extraction/rows",
     '"parameter": the field', False),
)


def shapes_files() -> list:
    """The OEKG shapes of the last `vocabulary --refresh`, or none.

    Where the preflight finds the file `NOT_EXTRACTED` is held against: the
    same one the serializer reads its paths from.
    """
    from profiles.scenarios import vocabulary   # lazy: it reads the spec
    return [path for path in vocabulary.shapes() if path.is_file()]


# The properties of the OEKG shapes that no parameter reads, each left out on
# purpose and each with its reason. `docpipe compile diff` lists them and the
# preflight warns about every one that is neither a parameter nor here. Keyed
# by (shape, property): the shape as the compiler names it, the property by
# the end of its IRI. The first group is the owner's decision (2026-10-05):
# nobody asks for these five, though none of them is required. The rest the
# serializer writes itself or never touches.
_NO_DATASET_NODE = "the serializer writes no dataset node"
_NO_FACTSHEET = ("the serializer writes no factsheet of this kind, so there "
                 "is nothing to give it")
_OWN_UUID = ("the serializer writes it on every node it mints (kg.P_UUID), "
             "behind no parameter")
NOT_EXTRACTED = {
    # contact person
    ("study", "OEO_00000508"):
        "has contact person: optional in the shapes, and the bundle carries "
        "authors, organisations and funders and no contact person",
    # the study's energy carrier tag
    ("study", "OEO_00020432"):
        "covers energy carrier: optional in the shapes, a closed list; the "
        "sector and technology tags of the study are asked and its energy "
        "carrier tag is not",
    # the study's sector division tag
    ("study", "OEO_00390079"):
        "based on sector division: a closed list the AR6 papers almost never "
        "answer; on the AR6 run 531 of 535 answers were a sector and four "
        "publications named a listed division (owner, 2026-10-29)",
    # interacting region
    ("scenario", "OEO_00020222"):
        "has interacting region: optional in the shapes; a scenario's study "
        "region is asked and its interacting region is not",
    # input and output datasets of a scenario
    ("scenario", "OEO_00020436"):
        "has information output: optional in the shapes, and "
        + _NO_DATASET_NODE,
    ("scenario", "OEO_00020437"):
        "has information input: optional in the shapes, and "
        + _NO_DATASET_NODE,
    # the publication's reference link
    ("publication", "OEO_00390078"):
        "has reference: optional in the shapes; the report carries no link "
        "to its reference",
    ("region", "OEO_00390078"):
        "has reference: optional in the shapes; a region is only referenced "
        "by its IRI and never written",
    # written by the serializer itself
    ("study", "BFO_0000051"):
        "has part: the serializer writes it from the kg block of the "
        "scenario coordinate, the bundle holds its report and its "
        "factsheets, and no parameter asks for it",
    ("scenario", "OEO_00020220"):
        "has study region: the serializer writes its parent, has spatial "
        "region, for scenario_region, and the bundle body for the platform "
        "writes this one itself",
    ("publication", "OEO_00390095"): "has uuid: " + _OWN_UUID,
    ("scenario", "OEO_00390095"): "has uuid: " + _OWN_UUID,
    ("common", "label"):
        "label of the objects of the author, organisation, funder, tag and "
        "scenario type properties: the serializer writes it for the authors, "
        "organisations and funders it mints, and a tag or a scenario type is "
        "the IRI of a node the OEKG already holds with its label",
    ("region", "label"):
        "label: a region is only referenced by its IRI, the node exists in "
        "the OEKG with its label, and writing ours would give it a second one",
    # shapes of nodes the serializer never writes
    ("dataset", "label"): "label: " + _NO_DATASET_NODE,
    ("dataset", "has_id"): "has_id: " + _NO_DATASET_NODE,
    ("dataset", "OEO_00390094"): "has iri: " + _NO_DATASET_NODE,
    ("dataset", "OEO_00390095"): "has uuid: " + _NO_DATASET_NODE,
    ("framework", "label"): "label: " + _NO_FACTSHEET,
    ("framework", "OEO_00390094"): "has iri: " + _NO_FACTSHEET,
    ("model", "label"): "label: " + _NO_FACTSHEET,
    ("model", "OEO_00390094"): "has iri: " + _NO_FACTSHEET,
}


# What the stage says to the model outside its prompts: why an answer was not
# taken, what was wrong with a reply, what stands beside an image. In the
# language of the prompts, and read by docpipe/extraction/wording.py, which
# says what each name is filled with.
PHRASES = {
    # the closed list as a request shows it: protocol keys, so English in
    # every profile
    "option_means": 'means',
    "option_spellings": 'spellings',
    "unstated_means": 'these passages do not state it',
    "unstated_spelling": 'not stated in these passages',
    # why a coordinate's answer was not taken
    "kind_whole_number": 'a whole number',
    "kind_text": 'a piece of text',
    "not_an_option": (
        'Your "value" {given!r} is none of the entries of "options". '
        'Choose exactly one name from it, copied character for '
        'character, including one that starts with "out:". If none fits '
        'although the passage states the field, leave "value" out and '
        'give the wording in "value_raw".'),
    "value_not_an_option": (
        'The value {value!r} of this row is none of the entries of '
        '{given!r}. Choose the field whose list holds this value, or '
        'answer that these passages do not state it.'),
    "wrong_type": (
        'Your "value" {given!r} is not {wrong}. Answer with {wrong}, '
        'exactly as the passage writes it.'),
    "quote_not_in_source": (
        'Your "quote" stands in none of the sources shown. Copy a '
        'passage character for character from "sources" or from the '
        '"quote" of the row itself.'),
    "quote_too_short": (
        'Your "quote" is too short to name a place (at least {minimum} '
        'characters). Quote the whole sentence or the whole line the '
        'answer stands in.'),
    "answer_not_in_quote": (
        'Your "quote" does not contain {answer!r}. Quote the place where '
        'it really stands, or answer with "{unstated}".'),
    # The key of the frame request that holds the entries of a closed frame
    # coordinate. The frame prompt reads them there.
    "frame_options": "scenarios",
    # why a pair of the document's frame was not taken
    "frame_missing": 'A pair lacked "{slot}".',
    "frame_no_quote": 'For {slot}={given!r}, "{slot}_quote" was missing.',
    "frame_quote_not_in_source": (
        'The quote for {slot}={given!r} stands in none of the passages '
        'shown: {quote!r}. Copy it character for character from '
        '"sources".'),
    "frame_answer_not_in_quote": (
        '{slot}={given!r} does not stand in its quote {quote!r}. Write '
        'the wording of the document into "{slot}_raw".'),
    "frame_not_an_option": (
        '{given!r} is none of the keys of "{options}". Choose exactly '
        'one of them, copied character for character, and write the word '
        'of the document into "{slot}_raw".'),
    "frame_not_a_year": (
        '{slot}={given!r} is not a whole year. Give the year with four '
        'digits.'),
    # a reply that could not be read
    "shape_rule": (
        ' Output ONLY the JSON object, on ONE line, with no text before '
        'or after it, no code fence, no <think> block and no second '
        'object. Quotation marks INSIDE a quote must be escaped as \\" — '
        'if that is tedious, shorten the quote to a place without '
        'quotation marks.'),
    "cut_off": (
        'Your answer was cut off after {limit} tokens and is therefore '
        'not a complete JSON object. '),
    "shorter": (
        'Answer more briefly: quote only the short place where the field '
        'stands.'),
    "shorter_frame": (
        'Answer with fewer pairs and quote only the short place where '
        'the scenario or the year stands.'),
    "shorter_rows": (
        'Answer with fewer tuples and quote only the short place where '
        'the value stands.'),
    "shorter_field": (
        'Put rows with the same answer together in "groups" and quote '
        'only the short place where the field stands.'),
    "shorter_review": (
        'Quote only the short place where the field stands, and leave '
        'out every field the two passages do not carry.'),
    "reasoning_only": (
        'You only thought and answered nothing: your reply was empty. Do '
        'not think ahead, output the result directly.'),
    "empty": 'Your answer was empty.',
    "no_object": 'Your answer contained no JSON object at all.',
    "syntax": (
        'Your JSON breaks at character {position} ({message}), at this '
        'place: {around!r}.'),
    "outside_text": 'There was text beside the JSON object: {extra!r}.',
    "not_an_object": (
        'Your answer was a {kind} structure and not a JSON object.'),
    "key_missing": 'Your answer lacked "{key}".',
    "key_not_a_list": 'In your answer "{key}" was not a list.',
    "wrong_shape": 'Your answer did not have the form that was asked for.',
    # what the model gets back after a calculation
    "code_failed": (
        'The code did not run: {error}. Answer now without a '
        'calculation, or correct the code.'),
    "code_error_unknown": 'unknown',
    "code_silent": (
        'The code ran but printed nothing. Print every result with '
        'print(), or answer without a calculation.'),
    "code_output": (
        'Output of the code:\n{output}\n\nAnswer now with the tuple '
        'object. Calculated values carry "computed": true.'),
    # labels inside a request
    "image_for": 'Image for {label}:',
    "anchor_parameter": 'Field',
    "anchor_unit": 'Unit',
}
