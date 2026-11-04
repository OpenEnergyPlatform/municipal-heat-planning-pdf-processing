"""
completion.py: What a publication's own text leaves open of its identity,
looked up in an open catalogue (owner decisions 2026-11-04).

A paper's PDF is often the authors' manuscript: it prints its title and its
authors, and neither its DOI nor its year. After a document's fold a program
asks OpenAlex, whose records are CC0, for the publication's record and fills
the parameters no reading filled: the DOI, the year and, where the text
yields no author at all, the authors. The year is the value, as the
parameter defines it, and the record keeps the full date.

The record is the first one these keys find, in this order: the DOI the
corpus index holds for the document (`catalogue_doi`), the DOI the harvest
read, the title the harvest read. The index's DOI goes first because it
belongs to this very file, while a DOI read off the page can be one the
paper cites, such as a dataset's. A DOI names one publication, so its
record is taken as it is; a record the title finds counts only where at
least two of its authors' family names stand among the authors the harvest
read, or one where either side names one author.

Such a row is built like a computed one: its quote and its passage are those
of the read value the record was found with, the printed DOI, else the
title; the record stands beside it (`catalogue`), and the flag `catalogue`
makes it a D (`trust.FLAG_REASONS`). A value the document prints goes
first: a parameter that has a row is not looked up. No model is asked.

The first time the catalogue cannot be reached at all, the run asks it no
more (`OFFLINE`): each later document says so at once instead of waiting
out the timeout.

Author: Felix Vossel
"""
from __future__ import annotations

import json
import re
import threading
import unicodedata
import urllib.error
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
DOI = "publication_doi"
# The flags of the anchor row that speak about its quote, which a looked-up
# row shares with it. The others are about the anchor's own reading.
QUOTE_FLAGS = ("quote_repaired", "not_located")
SOURCE = "OpenAlex"

# The keys a record is found by; tried index DOI, read DOI, title.
BY_INDEX_DOI = "index_doi"
BY_READ_DOI = "doi"
BY_TITLE = "title"

# Set the first time the catalogue cannot be reached; a run is one process.
OFFLINE = threading.Event()


def _get(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))


def search(title: str) -> Optional[dict]:
    """The first record OpenAlex finds for *title*, or None."""
    query = urllib.parse.urlencode({"search": title, "per_page": 1,
                                    "select": FIELDS})
    results = _get(f"{WORKS}?{query}").get("results") or []
    return results[0] if results else None


def by_doi(doi: str) -> Optional[dict]:
    """The record OpenAlex holds under *doi*, or None where it holds none."""
    query = urllib.parse.urlencode({"select": FIELDS})
    try:
        return _get(f"{WORKS}/doi:{urllib.parse.quote(doi, safe='/')}?{query}")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


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
    """Whether the record a title found is the document: two of its family
    names among the authors read, or one where either side names one."""
    families = {family(name) for name in authors_of(record)} - {""}
    named = [name for name in read if words(name)]
    needed = min(2, len(families), len(named))
    return needed >= 1 and len(matched(record, read)) >= needed


def bare_doi(text) -> Optional[str]:
    """A DOI alone, without the resolver or the "doi:" before it."""
    doi = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:)\s*", "",
                 str(text or "").strip(), flags=re.I)
    return doi or None


def doi_of(record: dict) -> Optional[str]:
    return bare_doi(record.get("doi"))


def year_of(record: dict) -> Optional[str]:
    year = str(record.get("publication_year") or "")
    if not re.fullmatch(r"\d{4}", year):
        year = str(record.get("publication_date") or "")[:4]
    return year if re.fullmatch(r"\d{4}", year) else None


def _one(value) -> list:
    return [value] if value else []


# The parameters a record fills, each with the values it takes from it.
FILLED = {DOI: lambda record: _one(doi_of(record)),
          "publication_date": lambda record: _one(year_of(record)),
          AUTHOR: lambda record: [name for name in authors_of(record)
                                  if words(name)]}


def evidence(record: dict, key: tuple, hit: list) -> dict:
    """The record a looked-up value stands on, as the row carries it."""
    return {"source": SOURCE, "id": record.get("id"),
            "key": key[0], "searched": key[1],
            "title": record.get("display_name"),
            "authors": authors_of(record), "matched": hit,
            "doi": doi_of(record),
            "publication_date": record.get("publication_date")}


def row_of(anchor: dict, uri: str, value: str, record: dict, key: tuple,
           hit: list) -> dict:
    """A looked-up value in the shape of the read row it was found with:
    its quote and its passage, the record beside it."""
    row = dict(anchor)
    row.update(parameter=uri, value=value, value_raw=value,
               flags=[flag for flag in anchor.get("flags") or ()
                      if flag in QUOTE_FLAGS] + [CATALOGUE],
               catalogue=evidence(record, key, hit))
    row["provenance"] = {**(anchor.get("provenance") or {}), "via": CATALOGUE}
    return row


def _most_read(rows: list) -> Optional[dict]:
    """The row of the value most of *rows* read, as the graph takes it."""
    if not rows:
        return None
    value = Counter(row["value"] for row in rows).most_common(1)[0][0]
    return next(row for row in rows if row["value"] == value)


def complete(report, spec, *, fetch: Optional[Callable] = None,
             fetch_doi: Optional[Callable] = None,
             catalogue_doi: Optional[str] = None) -> Optional[dict]:
    """Fill what the document leaves open of DOI, year and authors from its
    catalogue record. *catalogue_doi* is the DOI the corpus index holds for
    the document. What it came to, for the trace, or None where nothing was
    open."""
    known = {parameter.uri for parameter in spec.parameters}
    filled = {row.get("parameter") for row in report.tuples}
    wanted = [uri for uri in FILLED if uri in known and uri not in filled]
    if not wanted:
        return None

    def rows_of(uri: str) -> list:
        return [row for row in report.tuples if row.get("parameter") == uri
                and isinstance(row.get("value"), str) and row["value"].strip()]

    title_row = _most_read(rows_of(TITLE))
    # Without a title the graph has no node to put a value on.
    if title_row is None:
        return {"outcome": "no_title", "open": wanted}
    if OFFLINE.is_set():
        return {"outcome": "offline", "open": wanted}
    doi_row = _most_read([row for row in rows_of(DOI)
                          if bare_doi(row["value"])])
    keys = []
    index_doi = bare_doi(catalogue_doi)
    if index_doi:
        keys.append((BY_INDEX_DOI, index_doi, title_row))
    if doi_row is not None and not any(
            k[1].casefold() == bare_doi(doi_row["value"]).casefold()
            for k in keys):
        keys.append((BY_READ_DOI, bare_doi(doi_row["value"]), doi_row))
    keys.append((BY_TITLE, title_row["value"], title_row))
    read = [row.get("value") for row in report.tuples
            if row.get("parameter") == AUTHOR]

    record = key = anchor = None
    try:
        for kind, value, row in keys:
            found = ((fetch or search)(value) if kind == BY_TITLE
                     else (fetch_doi or by_doi)(value))
            if found:
                record, key, anchor = found, (kind, value), row
                break
    except urllib.error.HTTPError as exc:   # it answered, with an error
        return {"outcome": "error", "open": wanted,
                "detail": f"HTTP {exc.code}"}
    except OSError as exc:                  # it could not be reached
        OFFLINE.set()
        return {"outcome": "offline", "open": wanted,
                "detail": str(exc)[:200]}
    except ValueError as exc:               # its reply was no record
        return {"outcome": "error", "open": wanted, "detail": str(exc)[:200]}
    if record is None:
        return {"outcome": "no_hit", "open": wanted}
    hit = matched(record, read)
    if key[0] == BY_TITLE and not accepted(record, read):
        return {"outcome": "authors", "open": wanted, "id": record.get("id"),
                "matched": hit}
    taken = []
    for uri in wanted:
        values = FILLED[uri](record)
        for value in values:
            report.tuples.append(row_of(anchor, uri, value, record, key, hit))
        if values:
            taken.append(uri)
    return {"outcome": "taken" if taken else "empty", "filled": taken,
            "open": [uri for uri in wanted if uri not in taken],
            "id": record.get("id"), "key": key[0], "matched": hit}
