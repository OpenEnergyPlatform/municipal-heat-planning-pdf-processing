"""
completion.py: What a publication's own text leaves open of its identity,
looked up in an open catalogue (owner decisions 2026-11-04).

A paper's PDF is often the authors' manuscript: it prints its title and its
authors, and neither its DOI nor its year. After a document's fold a program
asks OpenAlex, whose records are CC0, for the publication's record and fills
the parameters its front pages do not give: the DOI, the year and, where
they name no author, the authors. The year is the value, as the parameter
defines it, and the record keeps the full date.

The record is the first one these keys find, in this order: the DOI the
corpus index holds for the document (`DocumentMeta.doi` in the run's
database), the DOI the harvest read, the title the harvest read. The index's DOI goes first because it
belongs to this very file, while a DOI read off the page can be one the
paper cites, such as a dataset's. A DOI names one publication, so its
record is taken as it is; a record the title finds counts only where at
least two of its authors' family names stand among the authors the harvest
read, those of the front pages where it read any there, or one where either
side names one author.

Such a row is built like a computed one: its quote and its passage are those
of the read value the record was found with, the printed DOI, else the
title; the record stands beside it (`catalogue`), and the flag `catalogue`
makes it a D (`trust.FLAG_REASONS`). A value the document prints on its
front pages goes first: a parameter read there, or looked up already, is not
looked up. One read only elsewhere is, since a chapter on other studies and
a reference list print other works' values, and the graph takes the record's
value before such a reading (owner decision 2026-11-05, `front.py`). The
title and the DOI the record is found with are those of the front pages
where they were read there. No model is asked.

The first time the catalogue cannot be reached at all, the run asks it no
more (`OFFLINE`, rule `catalogue_stop_when_offline`): each later document of
that run says so at once instead of waiting out the timeout. The state is the
run's, not the process's: a run that starts afterwards asks again.

Every value here is a rule read when the catalogue is asked (`rules.json`
beside `rules.py`): its address, the waiting time, the name the run gives it,
the keys and their order, the hits looked at, what a hit has to agree in, the
values it fills in and the flags a looked-up row shares with its anchor.

Author: Felix Vossel
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from typing import Callable, Optional

from docpipe import rules
from docpipe.extraction.trust import CATALOGUE
from docpipe.store.schema import readonly_uri
from profiles.scenarios.front import (front_pages, in_order, looked_up,
                                      read_in_front)



def works() -> str:
    """Where the catalogue answers (rule `catalogue_address`)."""
    return rules.get("catalogue_address", "scenarios")


# A generic client name where the rule `catalogue_user_agent` names none: the
# catalogue asks nothing more of a client.
GENERIC_CLIENT = "docpipe"
FIELDS = "id,doi,display_name,publication_date,publication_year,authorships"

TITLE = "publication_title"
AUTHOR = "publication_author"
DOI = "publication_doi"
SOURCE = "OpenAlex"

# The keys a record is found by, in the order the rule `catalogue_key_order`
# says (index DOI, read DOI, title).
BY_INDEX_DOI = "index_doi"
BY_READ_DOI = "doi"
BY_TITLE = "title"

# Set the first time the catalogue cannot be reached, and meant for the run
# that found it down: `offline` says so only while the rules that run took
# are the ones in effect (`docpipe.rules.use`), so a later run asks again.
OFFLINE = threading.Event()
_offline_for: list = [None]


def offline() -> bool:
    """Whether the catalogue was found unreachable by the run that goes on
    (rule `catalogue_stop_when_offline`)."""
    return (bool(rules.get("catalogue_stop_when_offline", "scenarios"))
            and OFFLINE.is_set()
            and (_offline_for[0] is None
                 or _offline_for[0] is rules.current()))


def went_offline() -> None:
    """Note that the catalogue could not be reached, for this run."""
    if rules.get("catalogue_stop_when_offline", "scenarios"):
        _offline_for[0] = rules.current()
        OFFLINE.set()


def _get(url: str) -> dict:
    request = urllib.request.Request(url, headers={
        "User-Agent": (rules.get("catalogue_user_agent", "scenarios")
                       or GENERIC_CLIENT)})
    with urllib.request.urlopen(
            request, timeout=rules.get("catalogue_timeout_s", "scenarios")) as response:
        return json.loads(response.read().decode("utf-8"))


def search_hits(title: str) -> list:
    """The records OpenAlex finds for *title*, as many as the rule
    `catalogue_hits_taken` says, best first."""
    query = urllib.parse.urlencode({
        "search": title, "select": FIELDS,
        "per_page": rules.get("catalogue_hits_taken", "scenarios")})
    return _get(f"{works()}?{query}").get("results") or []


def search(title: str) -> Optional[dict]:
    """The first record OpenAlex finds for *title*, or None."""
    results = search_hits(title)
    return results[0] if results else None


def by_doi(doi: str) -> Optional[dict]:
    """The record OpenAlex holds under *doi*, or None where it holds none."""
    query = urllib.parse.urlencode({"select": FIELDS})
    try:
        return _get(f"{works()}/doi:{urllib.parse.quote(doi, safe='/')}"
                    f"?{query}")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def _name_word() -> str:
    """What a word of a name looks like: letters, at least as many as the
    rule `name_word_least_letters` says."""
    least = rules.get("name_word_least_letters", "scenarios")
    return r"[^\W\d_]{%d,}" % least


def words(name) -> set:
    """The words of a person's name as two lists can share them: without
    accents, marks, digits and case ("Keywan Riahi1,2*" -> keywan, riahi)."""
    plain = unicodedata.normalize("NFKD", str(name or ""))
    plain = "".join(c for c in plain if not unicodedata.combining(c))
    return {word.casefold() for word in re.findall(_name_word(), plain)}


def family(name) -> str:
    """The family name of a catalogue's author, the last word of the name
    it displays ("Jingyu Liu" -> liu)."""
    plain = unicodedata.normalize("NFKD", str(name or ""))
    plain = "".join(c for c in plain if not unicodedata.combining(c))
    found = re.findall(_name_word(), plain)
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
    """Whether the record a title found is the document: as many of its
    family names among the authors read as the rule `catalogue_family_names`
    says. Where a side names fewer authors than that, all of its authors
    have to agree, unless the rule `catalogue_fewer_authors_suffice` is off:
    then the number is kept as it is, and a record or a paper with fewer
    authors is never accepted by its title."""
    families = {family(name) for name in authors_of(record)} - {""}
    named = [name for name in read if words(name)]
    needed = rules.get("catalogue_family_names", "scenarios")
    if rules.get("catalogue_fewer_authors_suffice", "scenarios"):
        needed = min(needed, len(families), len(named))
    elif len(families) < needed or len(named) < needed:
        return False
    return needed >= 1 and len(matched(record, read)) >= needed


def bare_doi(text) -> Optional[str]:
    """A DOI alone, without the resolver or the "doi:" before it."""
    doi = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:)\s*", "",
                 str(text or "").strip(), flags=re.I)
    return doi or None


def index_doi(conn, document_id) -> Optional[str]:
    """The DOI the corpus index holds for the document (`DocumentMeta.doi`),
    without its resolver, or None where it holds none."""
    try:
        row = conn.execute("SELECT doi FROM DocumentMeta WHERE document = ?",
                           (document_id,)).fetchone()
    except sqlite3.Error:
        return None
    return bare_doi(row[0]) if row and row[0] else None


def _index_doi_in(db, document_id) -> Optional[str]:
    try:
        conn = sqlite3.connect(readonly_uri(db), uri=True)
    except sqlite3.Error:
        return None
    try:
        return index_doi(conn, document_id)
    finally:
        conn.close()


def doi_of(record: dict) -> Optional[str]:
    return bare_doi(record.get("doi"))


def year_of(record: dict) -> Optional[str]:
    year = str(record.get("publication_year") or "")
    if not re.fullmatch(r"\d{4}", year):
        year = str(record.get("publication_date") or "")[:4]
    return year if re.fullmatch(r"\d{4}", year) else None


def _one(value) -> list:
    return [value] if value else []


# The parameters a record can fill, each with the values it takes from it;
# the rule `catalogue_fills` says which of them it does.
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
                      if flag in rules.get("catalogue_inherited_flags",
                                           "scenarios")] + [CATALOGUE],
               catalogue=evidence(record, key, hit))
    row["provenance"] = {**(anchor.get("provenance") or {}), "via": CATALOGUE}
    return row


def _most_read(rows: list) -> Optional[dict]:
    """The row of the value most of *rows* read, as the graph takes it."""
    if not rows:
        return None
    value = Counter(row["value"] for row in rows).most_common(1)[0][0]
    return next(row for row in rows if row["value"] == value)


def _by_title(title: str, read: list,
              fetch: Optional[Callable] = None) -> Optional[dict]:
    """The record the title finds: the first hit, or where the rule
    `catalogue_hits_taken` looks at more, the first of them the authors
    agree with, else the first."""
    if fetch is not None:
        return fetch(title)
    if rules.get("catalogue_hits_taken", "scenarios") == 1:
        return search(title)
    hits = search_hits(title)
    return next((hit for hit in hits if accepted(hit, read)),
                hits[0] if hits else None)


def complete(report, spec, *, fetch: Optional[Callable] = None,
             fetch_doi: Optional[Callable] = None,
             catalogue_doi: Optional[str] = None,
             db=None) -> Optional[dict]:
    """Fill what the document's front pages leave open of DOI, year and
    authors from its catalogue record. *catalogue_doi* is the DOI the corpus
    index holds for the document; where it is not given, it is read from
    *db*, the run's database. What it came to, for the trace, or None where
    nothing was open."""
    known = {parameter.uri for parameter in spec.parameters}
    front = front_pages([row for row in report.tuples
                         if row.get("parameter") == TITLE])

    def given(uri: str) -> bool:
        """Whether a front page gave *uri*, or the catalogue was asked."""
        rows = [row for row in report.tuples if row.get("parameter") == uri]
        return bool(read_in_front(rows, front)) \
            or any(looked_up(row) for row in rows)
    wanted = [uri for uri in rules.get("catalogue_fills", "scenarios")
              if uri in FILLED and uri in known and not given(uri)]
    if not wanted:
        return None

    def rows_of(uri: str) -> list:
        return [row for row in report.tuples if row.get("parameter") == uri
                and isinstance(row.get("value"), str) and row["value"].strip()]

    title_row = _most_read(in_order(rows_of(TITLE), front))
    # Without a title the graph has no node to put a value on.
    if title_row is None:
        return {"outcome": "no_title", "open": wanted}
    if offline():
        return {"outcome": "offline", "open": wanted}
    if catalogue_doi is None and db is not None:
        catalogue_doi = _index_doi_in(db, report.document_id)
    doi_row = _most_read(in_order([row for row in rows_of(DOI)
                                   if bare_doi(row["value"])], front))
    index_doi = bare_doi(catalogue_doi)
    offered = {BY_INDEX_DOI: ((index_doi, title_row) if index_doi else None),
               BY_READ_DOI: ((bare_doi(doi_row["value"]), doi_row)
                             if doi_row is not None else None),
               BY_TITLE: (title_row["value"], title_row)}
    keys = []
    for kind in rules.get("catalogue_key_order", "scenarios"):
        if offered.get(kind) is None:
            continue
        value, row = offered[kind]
        # One DOI is asked once, whichever of the two keys names it.
        if kind != BY_TITLE and any(k[1].casefold() == value.casefold()
                                    for k in keys if k[0] != BY_TITLE):
            continue
        keys.append((kind, value, row))
    read = [row.get("value") for row in in_order(
        [row for row in report.tuples if row.get("parameter") == AUTHOR],
        front)]

    record = key = anchor = None
    try:
        for kind, value, row in keys:
            found = (_by_title(value, read, fetch) if kind == BY_TITLE
                     else (fetch_doi or by_doi)(value))
            if found:
                record, key, anchor = found, (kind, value), row
                break
    except urllib.error.HTTPError as exc:   # it answered, with an error
        return {"outcome": "error", "open": wanted,
                "detail": f"HTTP {exc.code}"}
    except OSError as exc:                  # it could not be reached
        went_offline()
        return {"outcome": "offline", "open": wanted,
                "detail": str(exc)[:200]}
    except ValueError as exc:               # its reply was no record
        return {"outcome": "error", "open": wanted, "detail": str(exc)[:200]}
    if record is None:
        return {"outcome": "no_hit", "open": wanted}
    hit = matched(record, read)
    if (key[0] == BY_TITLE
            and rules.get("catalogue_title_hit_needs_authors", "scenarios")
            and not accepted(record, read)):
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
