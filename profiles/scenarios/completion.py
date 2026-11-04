"""
completion.py: What a publication's own text leaves open of its identity,
looked up in an open catalogue (owner decisions 2026-11-04).

A paper's PDF is often the authors' manuscript: it prints its title and its
authors, and neither its DOI nor its year. After a document's fold a program
asks OpenAlex, whose records are CC0, for the title the harvest read, and
takes the first hit only where at least two of its authors' family names
stand among the authors the harvest read; where either side names one
author, that one. Its DOI and its year then enter the harvest for the
parameters no reading filled. The year is the value, as the parameter
defines it, and the record keeps the full date.

Such a row is built like a computed one: its quote and its passage are the
title it was looked up with, the record stands beside it (`catalogue`), and
the flag `catalogue` makes it a D (`trust.FLAG_REASONS`). A value the
document prints goes first: a parameter that has a row is not looked up. No
model is asked.

Author: Felix Vossel
"""
from __future__ import annotations

import json
import re
import unicodedata
import urllib.parse
import urllib.request
from collections import Counter
from typing import Callable, Optional

from docpipe.extraction.trust import CATALOGUE

WORKS = "https://api.openalex.org/works"
# A generic client name: the catalogue asks nothing more of a client.
USER_AGENT = "docpipe"
TIMEOUT = 30
FIELDS = "id,doi,display_name,publication_date,publication_year,authorships"

TITLE = "publication_title"
AUTHOR = "publication_author"
# The flags of the title row that speak about its quote, which a looked-up
# row shares with it. The others are about the title's own reading.
QUOTE_FLAGS = ("quote_repaired", "not_located")
SOURCE = "OpenAlex"


def search(title: str) -> Optional[dict]:
    """The first record OpenAlex finds for *title*, or None."""
    query = urllib.parse.urlencode({"search": title, "per_page": 1,
                                    "select": FIELDS})
    request = urllib.request.Request(f"{WORKS}?{query}",
                                     headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        found = json.loads(response.read().decode("utf-8"))
    results = found.get("results") or []
    return results[0] if results else None


def words(name) -> set:
    """The words of a person's name as two lists can share them: without
    accents, marks, digits and case ("Keywan Riahi1,2*" -> keywan, riahi)."""
    plain = unicodedata.normalize("NFKD", str(name or ""))
    plain = "".join(c for c in plain if not unicodedata.combining(c))
    return {word.casefold() for word in re.findall(r"[^\W\d_]{2,}", plain)}


def family(name) -> str:
    """The family name of a catalogue's author, the last word of the name
    it displays ("Jingyu Liu" -> liu)."""
    plain = unicodedata.normalize("NFKD", str(name or ""))
    plain = "".join(c for c in plain if not unicodedata.combining(c))
    found = re.findall(r"[^\W\d_]{2,}", plain)
    return found[-1].casefold() if found else ""


def authors_of(record: dict) -> list:
    return [(entry.get("author") or {}).get("display_name") or ""
            for entry in record.get("authorships") or ()]


def matched(record: dict, read: list) -> list:
    """The family names of the record's authors that stand among the words
    of the authors the harvest read, each once, in the record's order."""
    said = set().union(*(words(name) for name in read)) if read else set()
    out: list = []
    for name in authors_of(record):
        name = family(name)
        if name and name in said and name not in out:
            out.append(name)
    return out


def accepted(record: dict, read: list) -> bool:
    """Whether the record is the document: two of its family names among the
    authors read, or one where either side names one author."""
    families = {family(name) for name in authors_of(record)} - {""}
    named = [name for name in read if words(name)]
    needed = min(2, len(families), len(named))
    return needed >= 1 and len(matched(record, read)) >= needed


def doi_of(record: dict) -> Optional[str]:
    """The DOI alone, without the resolver before it."""
    doi = str(record.get("doi") or "").strip()
    doi = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:)", "", doi, flags=re.I)
    return doi or None


def year_of(record: dict) -> Optional[str]:
    year = str(record.get("publication_year") or "")
    if not re.fullmatch(r"\d{4}", year):
        year = str(record.get("publication_date") or "")[:4]
    return year if re.fullmatch(r"\d{4}", year) else None


# The parameters a record fills, each with what it takes from the record.
FILLED = {"publication_doi": doi_of, "publication_date": year_of}


def evidence(record: dict, title: str, hit: list) -> dict:
    """The record a looked-up value stands on, as the row carries it."""
    return {"source": SOURCE, "id": record.get("id"),
            "searched": title, "title": record.get("display_name"),
            "authors": authors_of(record), "matched": hit,
            "doi": doi_of(record),
            "publication_date": record.get("publication_date")}


def row_of(title_row: dict, uri: str, value: str, record: dict,
           hit: list) -> dict:
    """A looked-up value in the shape of the title row it was looked up
    with: its quote and its passage, the record beside it."""
    row = dict(title_row)
    row.update(parameter=uri, value=value, value_raw=value,
               flags=[flag for flag in title_row.get("flags") or ()
                      if flag in QUOTE_FLAGS] + [CATALOGUE],
               catalogue=evidence(record, title_row["value"], hit))
    row["provenance"] = {**(title_row.get("provenance") or {}),
                         "via": CATALOGUE}
    return row


def complete(report, spec, *, fetch: Optional[Callable] = None
             ) -> Optional[dict]:
    """Fill what the document leaves open of DOI and year from the record
    its title and authors find. What it came to, for the trace, or None
    where nothing was open."""
    known = {parameter.uri for parameter in spec.parameters}
    filled = {row.get("parameter") for row in report.tuples}
    wanted = [uri for uri in FILLED if uri in known and uri not in filled]
    if not wanted:
        return None
    titles = [row for row in report.tuples if row.get("parameter") == TITLE
              and isinstance(row.get("value"), str) and row["value"].strip()]
    if not titles:
        return {"outcome": "no_title", "open": wanted}
    # The title most of its rows read, as the graph takes it.
    title = Counter(row["value"] for row in titles).most_common(1)[0][0]
    title_row = next(row for row in titles if row["value"] == title)
    read = [row.get("value") for row in report.tuples
            if row.get("parameter") == AUTHOR]
    try:
        record = (fetch or search)(title)
    except Exception as exc:   # the catalogue is outside the run's hands
        return {"outcome": "error", "open": wanted, "detail": str(exc)[:200]}
    if not record:
        return {"outcome": "no_hit", "open": wanted}
    hit = matched(record, read)
    if not accepted(record, read):
        return {"outcome": "authors", "open": wanted, "id": record.get("id"),
                "matched": hit}
    taken = []
    for uri in wanted:
        value = FILLED[uri](record)
        if value:
            report.tuples.append(row_of(title_row, uri, value, record, hit))
            taken.append(uri)
    return {"outcome": "taken" if taken else "empty", "filled": taken,
            "open": [uri for uri in wanted if uri not in taken],
            "id": record.get("id"), "matched": hit}
