"""Extraction stage wiring: where the scenarios spec lives, and the list that
is only closed once a document is named.

One of the fields has a finite set of correct answers, but the set is not
the same for every publication, so it cannot sit in the spec file:

  scenario_region            the 249 study regions the OEKG actually uses,
                             narrowed to those the document names at all.

A scenario is read as the publication names it, and which entry of the
publication's list of scenarios a name is, a new one or one read before, is
asked while the publication is read (`docpipe/extraction/addressed.py`,
owner decisions 2026-11-08).

The narrowing is not a guess. Every claim has to quote its source verbatim, and
the sources are exactly the section, table and figure texts scanned here, so a
region whose name appears nowhere in them could never have been quoted. What is
dropped is unreachable, not merely unlikely — and dropping it keeps the prompt
at the handful of countries a paper mentions instead of all 249.

The list carries `out:` entries, and they are the point of this file as much
as the real entries are. A closed list without an escape hatch does not stop the
model from answering; it stops it from answering CORRECTLY, and what comes back
is the nearest entry that is not quite right. The OEKG knows 249 countries and
no aggregates, while a scenario is usually global — so without a world entry
the honest answer to "which region" does not exist in the list, and a paper
about worldwide emissions that happens to mention Germany once invites
"Germany". The world and the groups of countries are entries of the list now
and are written as their member countries.

Silence is the other half of the argument. An empty field already meant
"unmapped" and was already counted, but it meant three different things at
once — nothing fitted, the model did not look, the reply was cut short. A
chosen `out:` entry means exactly one of them, and it is the one worth
counting.
"""
import json
import re
import sqlite3
from docpipe import rules
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

# The entries a region list always has beside the regions a document
# names stand in the spec (`beside` of scenario_region, owner decision
# 2026-11-10). The first label of each is the answer token:
# runner._parameter_payload renders a choice list as {labels[0]: labels[1:]}
# and the prompt says to copy it character for character. So labels[0] is
# short and quotable, and the explanation is an alternate — value_to_uri()
# maps every label, so both spellings resolve. The long gloss first was a
# mistake: an answer nobody can retype without a slip is an answer that
# arrives as an unmapped wording, and an unmapped wording is exactly what
# these entries exist to prevent.
#
# A scenario is global far more often than national, and the OEKG's region list
# is 249 countries with no aggregate — no World, no EU27, no OECD, no R5.
# The groups are entries now (`region_aggregates.json`, from the regions of
# IAMconsortium/common-definitions, the UN's M49 and the World Bank): a group
# is written as its member countries. "several regions" stays for a group
# none of them has, "other region" for any other region the list lacks; the
# graph writes either as a study region of its own under the name the
# document prints (kg.printed_region, owner decision 2026-11-07).

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
    """A label that is only a word when its capitals are: US, UK, USA, U.S.
    (rule `acronym_most_chars`)."""
    return (len(label) <= rules.get("acronym_most_chars", "scenarios")
            and label.upper() == label and label.lower() != label)


def _code(label: str) -> bool:
    """A group's code: one word without a small letter ("LAM", "EU")."""
    return (" " not in label and label.lower() != label
            and not any(c.islower() for c in label))


def spellings(labels: list, joined: bool = False) -> list:
    """An entry's labels and the ways a paper writes them.

    "&" and "and" stand for each other. Where *joined*, a group's code and
    its name are joined as a paper joins them ("LAM (Latin America)",
    "Latin America (LAM)", "LAM - Latin America"): a wording made of two
    names of one entry names that entry, and `_one_meaning` keeps one two
    entries share from naming either.
    """
    out = list(labels)
    for label in labels:
        for one, other in ((" & ", " and "), (" and ", " & ")):
            if one in label:
                out.append(label.replace(one, other))
    if joined:
        names = [label for label in out if any(c.islower() for c in label)]
        for code in [label for label in labels if _code(label)]:
            for name in names:
                out += [f"{code} ({name})", f"{name} ({code})",
                        f"{code} - {name}", f"{code} – {name}"]
    return list(dict.fromkeys(out))


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


def _named(text: str, names) -> bool:
    """Does the text name one of these models, with its capitals? A model's
    name is a proper name: "IMAGE" is a model, "image" is a word of every
    paper with a figure."""
    return any(re.search(_WORD.format(re.escape(name)), text)
               for name in names)


def _one_meaning(offered: dict, groups: dict) -> dict:
    """The offered entries, each label kept where it means one thing.

    Two entries offered under one label would make one answer name two
    groups. The region of a model the paper names keeps the label; where no
    such region or two of them carry it, no entry does. An entry left
    without a label is not offered.
    """
    from docpipe.extraction.spec import fold_label
    holders: dict = {}
    for key, labels in offered.items():
        for label in labels:
            keys = holders.setdefault(fold_label(label), [])
            if key not in keys:
                keys.append(key)
    out = {}
    for key, labels in offered.items():
        kept = []
        for label in labels:
            keys = holders[fold_label(label)]
            models = [k for k in keys if (groups.get(k) or {}).get("named_by")]
            if keys == [key] or models == [key]:
                kept.append(label)
        if kept:
            out[key] = kept
    return out


def document_regions(conn: sqlite3.Connection, document_id: int) -> dict:
    """The countries and groups of countries this document names.

    The world is always offered, as `global` was. A group of the IAM
    regions is also offered by its bare name where the document names its
    family: a paper writes "the R10 regions" and then "Europe". A model's
    own region is offered where the paper names the model and the region,
    and keeps a label it shares with another group (`_one_meaning`). Every
    entry is offered with the ways a paper writes its labels (`spellings`).
    """
    groups = aggregates()
    out = ({WORLD: spellings(groups[WORLD]["labels"], True)}
           if WORLD in groups else {})
    text = _document_text(conn, document_id)
    if not text:
        return out
    for iri, labels in _regions().items():
        labels = spellings(labels)
        if _mentioned(text, labels):
            out[iri] = labels
    for key, group in groups.items():
        labels = spellings(group["labels"], True)
        if group.get("named_by"):
            if (key not in out
                    and (_named(text, group["named_by"])
                         or not rules.get("model_region_needs_model", "scenarios"))
                    and _mentioned(text, labels)):
                out[key] = labels
            continue
        family = group.get("family")
        named = labels + ([labels[0].rsplit(" (", 1)[0]]
                          if family and _mentioned(text, [family]) else [])
        if key not in out and _mentioned(text, named):
            out[key] = labels
    return _one_meaning(out, groups)


def document_axes(conn: sqlite3.Connection, document_id: int) -> dict:
    """Per-document choice lists, keyed by axis name and by parameter uri.

    The regions this document names, possibly none. The run appends the
    out: entries the spec lists beside them (`beside` of scenario_region,
    `runner.fill_dynamic_axes`), so the list exists even when the narrowing
    finds nothing. That case is not hypothetical — a publication that names
    no country at all used to leave the field with no list, and a field with
    no list is free text again.
    """
    return {"scenario_region": dict(document_regions(conn, document_id))}

# How the documents write the decimal is the rule `decimal_mark` (the
# default profile's rules.json; "3,251" is 3251 here).

# How many lines a piece holds is a number of the flow (`flow.json`, owner
# decision 2026-11-08, f: eight; twelve only measured where a probe loses
# values).

# What a publication settles for all its values (`plan_fields`) and the
# works it presents, compares, reviews or cites beside itself (`works`)
# stand in the spec, with the texts a request shows of them (owner decision
# 2026-11-10).

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
PROMPT_CHECKS = ()


def shapes_files() -> list:
    """The OEKG shapes of the last `vocabulary --refresh`, or none.

    Where the preflight finds the file the rule `not_extracted` is held
    against: the
    same one the serializer reads its paths from.
    """
    from profiles.scenarios import vocabulary   # lazy: it reads the spec
    return [path for path in vocabulary.shapes() if path.is_file()]


# The properties of the OEKG shapes that no parameter reads, each left out on
# purpose and each with its reason, are the rule `not_extracted` (rules.json
# beside this file, owner decision 2026-10-05 for the first five): `docpipe
# compile diff` lists them and the preflight warns about every one that is
# neither a parameter nor there.


# What the stage says to the model outside its prompts (why an answer was not
# taken, what was wrong with a reply) is a file beside them:
# prompts/extraction/phrases.json (docpipe/phrases.py).


def document_context(conn, document_id: int) -> dict:
    """What a publication says of itself, for the sentence it is searched
    with: its title as the corpus index holds it (`DocumentMeta.title`).
    Missing metadata is no error: the sentence is then written from the
    parameter alone."""
    try:
        row = conn.execute("SELECT title FROM DocumentMeta WHERE document = ?",
                           (document_id,)).fetchone()
    except Exception:
        return {}
    title = (row[0] or "").strip() if row else ""
    return {"name": title} if title else {}
