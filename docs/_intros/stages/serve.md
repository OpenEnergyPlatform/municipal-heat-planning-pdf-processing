## What it is for

A harvest is one JSONL file per document, written for the run that made it.
Whoever wants a number out of it, a spreadsheet, another program, an
assistant or the chat, wants the same few things: which documents, which
parameters, the values that match, and for each one what backs it. This
package reads a harvest once (`values.py`) and everything else answers from
that reading, so a table, an API, a tool server and the chat cannot say
different things.

```
docpipe export HARVEST_DIR --out values.csv
docpipe export HARVEST_DIR --format jsonl --level B --out values.jsonl
docpipe serve HARVEST_DIR --http [--port 8750]
docpipe serve HARVEST_DIR --mcp
```

A value is served as the harvest holds it: its `id` (see
[extraction](extraction.md)), the value and unit, every coordinate with what
was read, the wording and how the reading ended, the quote and the page, and
the trust level with its reasons. Nothing is filtered: a value of level C is
served like one of level A and says that it is one. Leaving a level out is
the asker's choice (`--level B` asks for B and better). A number handed on
without what backs it is no longer a verified one, which is why the quote and
the page are in every line.

| way | what it is |
|---|---|
| `export` | one line per value, CSV or JSON lines; a coordinate is three columns (what was read, its label, its state) |
| `serve --http` | a read-only JSON API: `/documents`, `/parameters`, `/values`, `/values/<id>`; nothing can be written through it |
| `serve --mcp` | the same four questions as tools of a Model Context Protocol server on standard input and output |
| the chat | answers a question for a number from the same store (see [asking the corpus](inference.md)) |

An export writes every value that matches (`find(limit=None)`), however
many; the answer of a server stays held to `MAX_LIMIT` values, and the rest
is asked for with `offset`. An export without `--out` writes standard output
as UTF-8, and the tool server reads standard input and writes standard output
as UTF-8, whatever the terminal's code page. CSV lines end CR LF, as the
format says. A text cell that begins like a
formula (`=`, `+`, `-`, `@`), or with a tab or a carriage return, is also
written as text, with a leading apostrophe.

Two rows of one document conflict when they state the same parameter under
the same coordinates with another number, and both then say so in their
reasons. The numbers are compared in the unit the parameter is kept in
(`value_target`) where both rows have it, so 241 GWh and 241000 MWh are one
reading written twice and not a conflict; where one has none, in the value
and unit as read.

The HTTP server listens on this machine only unless told otherwise (an IPv6
host is served too), and does not listen anywhere else without a token
(`DOCPIPE_API_TOKEN`; every request then carries `Authorization: Bearer
<token>`, the scheme in any case). The token is compared as the bytes that
were sent. A query that gives an argument or a coordinate twice is refused
with 400, not answered with one of the two. It is the standard library's
server: fine behind a reverse proxy or for a group, not for the open
internet on its own.

With a profile the values carry the labels of its spec and the transcribed
mark of its database; without one they carry what the harvest itself says.
