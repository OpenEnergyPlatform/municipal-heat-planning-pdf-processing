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
docpipe export HARVEST_DIR --what states --out states.csv
docpipe export HARVEST_DIR --what refusals --out refusals.csv
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
| `export` | `--what values` (the default): one line per value, CSV or JSON lines; a coordinate is three columns (what was read, its label, its state), and its quote is appended after the others. `--what states`: one line per document and parameter. `--what refusals`: one line per claim that was refused |
| `serve --http` | a read-only JSON API: `/documents`, `/parameters`, `/values`, `/values/<id>`, `/states`, `/coverage`, `/refusals` and `/search`; nothing can be written through it |
| `serve --mcp` | the same eight questions as tools of a Model Context Protocol server on standard input and output: `list_documents`, `list_parameters`, `find_values`, `get_value`, `get_states`, `get_coverage`, `find_refusals` and `search` |
| the chat | answers a question for a number from the same store (see [asking the corpus](inference.md)) |

## What the harvest says when it has no value

A harvest file holds more than its values. For each document and parameter
it holds a state line, and it holds the claims it refused. These are read
with the values, from the same files, so that a missing value is an answer
and not a silence (the states themselves are on [what a coordinate's state
means](../contract/states.md)). A document and a parameter are in one of
six states:

| state | means |
|---|---|
| `read` | values were read and accepted |
| `unstated` | the document was read through and does not carry it |
| `exhausted` | the run ended before the document was read through |
| `unbacked` | values were offered and refused; `refusals` says why |
| `never_asked` | the file has state lines, and none for this parameter |
| `not_recorded` | the file has no state line at all, because it was written before states were kept |

The first four are what the harvest wrote. The last two are the store's
own and say that the harvest holds nothing, which is not the same as
`unstated`: "the plan does not say it" is a finding about the plan, and
"nobody asked" is not. `get_states` (`/states`) lists the pairs, narrowed by
document, parameter or state. `get_coverage` (`/coverage`) is the table of
documents by parameters, plans without a value included, with the tally
over all documents and not only over the page; it is the way to ask which
parameters a harvest has at all, since `list_parameters` names only those
that have values. `find_refusals` (`/refusals`) lists what was refused
and why. A document or a parameter the harvest does not have is an error
(`NotFound`, a 404 over HTTP and an error result over MCP) and never an
empty answer; the one exception is `export --what values`, which still says
`0 value(s)` and exits 0 for an unknown document or parameter, while the
export of states and refusals exits non-zero. A coordinate of a value
carries its quote, and where the reading was linked from another passage
that passage as well.

A state line is written by the run that harvested the document. A
`--recheck` keeps it as it was and a `--top-up` does not rewrite it, and a
top-up can move a value to the refusals, so a cell can say `read` while
`find_values` serves fewer values than the line counts. The server reports
the line as it stands.

## Searching the passages

`search` (`/search`) answers a question the harvest has no value for from
what the documents say: it asks the word index that `docpipe lexical`
builds and returns each passage with its document, kind, id, title,
section title, page, text and rank. A passage found this way is a search
hit, not a verified value. It needs the corpus database and the word index;
the database is named as the chat names it, by `--db`, then
`INFERENCE_DB_PATH`, then the profile's (an export never opens it). With no
database, no index, an index that is stale or names a passage the database
no longer has, or a SQLite without full-text search, the server still
starts, the search is checked once at start and listed as `NOT AVAILABLE`
with the reason in its description, and a call is a 503 over HTTP and an
error result over MCP, saying what to build. The search does not choose a
document version, so older versions of a plan are searched too, and a
passage's text is returned whole, so the number of
passages is the only bound; it is held to `MAX_LIMIT`, like every answer.
The index is not looked at again after the start: a passage that has
vanished is reported, but one that was rewritten is not noticed.

An export writes every value that matches (`find(limit=None)`), however
many; the answer of a server stays held to `MAX_LIMIT` values, and the rest
is asked for with `offset`. `--level` belongs to the values and is refused
for the other two tables. A harvest line that cannot be used is counted: an
export says how many on standard error and still exits 0, and the HTTP
index shows the number as `unreadable_lines`. An export without `--out` writes standard output
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
