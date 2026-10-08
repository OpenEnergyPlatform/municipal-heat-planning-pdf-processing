"""
graphkit.py: The small tools the graph writers share.

A profile's graph is written by its own `kg.py`, and by `graph.py` where the
spec says what the graph is. All of them build an identifier from a name,
fold a name to one spelling, write Turtle text and refuse the entries of a
choice list that are not a thing in the graph. That is here, once.

What stays with each writer is what only it decides: which coordinates make
an IRI, which reading of one value wins over another, which legal forms a
name loses, which rows reach the graph at all. A tool here takes what differs
as an argument and never as a default of its own.

Author: Felix Vossel
"""
from __future__ import annotations

import re
import unicodedata
import uuid

# The entries of a choice list that say what a row IS when nothing in the list
# fits (a sum, an unknown, a family of scenarios). They are answers, not
# classes, so no IRI, type or link is ever made from one.
NOT_IN_GRAPH = "out:"

# A Turtle comment line is cut here, so one long quote cannot swallow a file.
COMMENT_LIMIT = 400


def base_namespace(base: str) -> uuid.UUID:
    """The UUID namespace of a graph: its base IRI, hashed as a URL."""
    return uuid.uuid5(uuid.NAMESPACE_URL, base)


def mint_uuid(namespace: uuid.UUID, collection: str, name: str) -> str:
    """UUIDv5 of *name* inside *collection* of a graph's namespace.

    Never v4: v4 is random, and two runs over one document must mint one
    IRI. The caller says which name identifies the thing; it is hashed as
    given, so a writer that folds names does so before it calls.
    """
    return str(uuid.uuid5(uuid.uuid5(namespace, collection), name))


def normalise(label: str, legal: str = "") -> str:
    """One spelling for a name: two writings of it mint one IRI.

    Folded to NFC and lower case, punctuation and runs of space to one space.
    *legal* is the regular expression of the legal forms the writer's corpus
    ends a name with (an alternation, no anchors); a name loses one at its
    end. The lists differ between corpora and a shared one would re-mint
    every organisation of one of them, so there is no default.
    """
    s = unicodedata.normalize("NFC", label).casefold()
    s = re.sub(r"[^\w\s]", " ", s, flags=re.U)
    s = re.sub(r"\s+", " ", s).strip()
    if legal:
        s = re.sub(rf"\s+{legal}$", "", s)
    return s.strip()


def ttl_comment(text, indent: str = "") -> str:
    """One Turtle comment line, flattened so a quote cannot break the file."""
    flat = re.sub(r"\s+", " ", str(text or "")).strip()
    return f"{indent}# " + flat[:COMMENT_LIMIT]


def ttl_escape(text) -> str:
    """The inside of a Turtle "..." literal, every character that would end
    or break a single-line literal written out."""
    return (str(text).replace("\\", "\\\\").replace('"', '\\"')
            .replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t"))


def ttl_string(text) -> str:
    """A text as a Turtle string literal, quotes included."""
    return f'"{ttl_escape(text)}"'


def ttl_literal(text) -> str:
    """A text as a Turtle string literal that may run over several lines.

    Abstracts do, so the long form is used whenever the text is not a single
    clean line. A single line is not escaped past its backslashes and quotes.
    """
    s = str(text)
    escaped = s.replace("\\", "\\\\").replace('"', '\\"')
    if "\n" in s or "\r" in s:
        return '"""' + escaped.replace("\r", "") + '"""'
    return f'"{escaped}"'
