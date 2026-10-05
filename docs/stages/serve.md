# Handing the values on

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

## Module reference

The docstring of each module of this stage, verbatim from the code and generated by `scripts/build_docs.py`. The chapter above is the account; this is the reference. Edit the docstring, not this page.

<details>
<summary><code>docpipe/serve/__init__.py</code></summary>

serve: The harvested values, handed on.

`values.py` reads a harvest once: its values, what it says of the parameters
that have none (their states) and its refusals. Everything else here answers
from that reading: a table (`export.py`), an HTTP API (`http.py`) and an MCP
server (`mcp.py`), over the questions `tools.py` describes once. The chat
asks the same store (docpipe/inference/values_route.py). `passages.py` is
the one part that reads something else, the corpus database and its word
index, for the passage search.

Author: Felix Vossel

</details>

<details>
<summary><code>docpipe/serve/values.py</code></summary>

values.py: The harvested values of a corpus, as something that can be asked.

A harvest is one JSONL file per document, written for the run that made it.
Whoever wants a number out of it (a table, another program, an assistant,
the chat) wants the same few things: which documents, which parameters,
the values that match, and for each one what backs it. This module is that
one reading of a harvest, and the export, the HTTP API, the MCP server and
the chat all answer from it, so they cannot say different things.

A value is served as the harvest holds it, with what the harvest knows
about it and nothing added:

    id            its name (`identity.tuple_ids`): the document, the quote
                  and the value as written. The same after a new build of
                  the database and after a new harvest that reads the same.
    value, unit   as read, and converted into the parameter's unit where
                  the harvest did that
    coordinates   each with what was read, the wording it was read from and
                  how the reading ended (`fields.py`)
    quote, page   the words of the document the value stands in, and where
    level         A, B or C with the reasons (`trust.py`)

Nothing is filtered: a value of level C is served like one of level A, and
says that it is one. Leaving a level out is the asker's decision
(`level="B"` asks for B and better).

The same files say more than their values. A harvest file holds, per
parameter, a state line (`kind: parameter_state`) and the claims that were
refused (`kind: refusal`), and these are read here too, once, with the
values. A missing value is then an answer and not a silence:

    read          values of the parameter were read and accepted
    unstated      the document was read and does not carry it
    exhausted     the run ended before the document was read through
    unbacked      values were offered and refused (`refusals` says why)
    never_asked   the file has state lines, and none for this parameter
    not_recorded  the file has no state line at all: it was written before
                  states were kept

The first four are the harvest's words, as it wrote them. The last two are
not a state of the document: they say that the harvest holds none, and are
kept apart from `unstated` because "the plan does not say it" is a finding
and "nobody asked" is not. A document or a parameter the harvest does not
have at all is an error (`NotFound`), never an empty answer.

Beware the name: a tuple's own `parameter_state` key is the state of its
`parameter` coordinate, which is another thing (`coordinates`, below).

Author: Felix Vossel

</details>

<details>
<summary><code>docpipe/serve/export.py</code></summary>

export.py: What a harvest holds, as a table.

Three tables, each as a CSV for a spreadsheet or as JSON lines for a
program:

    values    one line per accepted value, with its quote and its page,
              because a number handed on without what backs it is no
              longer a verified one
    states    one line per document and parameter: what the harvest says
              about it, so "the plan does not say it" (unstated) leaves the
              harvest as a line and not as an absence
    refusals  one line per claim the harvest refused, with the reason

A coordinate of a value is three columns: what was read (`<name>`), its
label where the spec has one (`<name>_label`) and how the reading ended
(`<name>_state`). The columns of a file are the coordinates its values
have, in alphabetical order after the fixed ones. After all of those come
the passages the coordinates were read from (`<name>_quote`), appended so
that a table written before they existed keeps its columns where they were.

Author: Felix Vossel

</details>

<details>
<summary><code>docpipe/serve/tools.py</code></summary>

tools.py: The questions the store answers for a program.

The HTTP API and the MCP server offer the same eight, described once here,
so a program that asks over one gets what a program that asks over the
other gets:

    list_documents, list_parameters   what the harvest has values of
    find_values, get_value            the values, each with what backs it
    get_states, get_coverage          what the harvest says about a parameter
                                      that has no value: unstated, exhausted,
                                      unbacked, never asked
    find_refusals                     the claims that were refused, and why
    search                            passages of the documents by word

A question the store cannot answer is one of three errors, so that a caller
can tell them apart: `BadRequest` (the question is malformed), `NotFound`
(a document or a parameter the harvest does not have) and `Unavailable`
(the search has no database or no word index behind it).

Author: Felix Vossel

</details>

<details>
<summary><code>docpipe/serve/http.py</code></summary>

http.py: The value store over HTTP, read only.

    GET /                 what this server answers
    GET /documents        the documents with values
    GET /parameters       the parameters, their units and coordinates
    GET /values           the values that match the query
                          ?document= &parameter= &level= &text=
                          &limit= &offset= &coordinate.<name>=<value>
    GET /values/<id>      one value with everything that backs it
    GET /states           what the harvest says of a parameter in a document
                          (unstated, exhausted, ... never asked)
                          ?document= &parameter= &state= &limit= &offset=
    GET /coverage         documents by parameters, each cell its state
                          ?document= &parameter= &limit= &offset=
    GET /refusals         the claims that were refused, and why
                          ?document= &parameter= &limit= &offset=
    GET /search           passages by word: ?text= &document= &limit=
                          (503 with the reason where there is no corpus
                          database or word index)

Answers are JSON. Nothing can be written through it. A document or a
parameter the harvest does not have is a 404, not an empty answer.

It listens on this machine only unless told otherwise, and it does not
listen anywhere else without a token: with DOCPIPE_API_TOKEN set every
request has to carry `Authorization: Bearer <token>`. The standard
library's server is used as it is: fine behind a reverse proxy or for a
group, not something to put on the open internet by itself.

Author: Felix Vossel

</details>

<details>
<summary><code>docpipe/serve/mcp.py</code></summary>

mcp.py: The value store as a Model Context Protocol server.

An assistant that speaks MCP is given the eight questions of `tools.py` as
tools and gets the same answers the HTTP API gives. The server talks over
standard input and output, one JSON-RPC message per line, which is how an
assistant starts a tool on the machine it runs on:

    {"command": "docpipe", "args": ["serve", "HARVEST_DIR", "--mcp"]}

Only what a tool server needs is spoken: `initialize`, `ping`,
`tools/list` and `tools/call`. No message is written to standard output
that is not an answer; the log goes to standard error.

Author: Felix Vossel

</details>

<details>
<summary><code>docpipe/serve/passages.py</code></summary>

passages.py: The passages of the corpus, found by word.

`find_values` answers from what the harvest read. This answers from what
the documents say, for the question the harvest has no value for: it asks
the word index (`inference/lexical.py`) and hands back each passage with
its document, the title of its section, its page and its text, so that a
program can quote it. It is a search and not a reading: a passage found
here is not a verified value.

It needs the corpus database and the word index built from it. Without
either it says so, with what to do about it, and answers no search. A
missing index that answered "nothing found" would read as "the corpus does
not say it", and a stale one would name a passage the database no longer
has. The index is checked once, when the server starts, as the chat does.

Author: Felix Vossel

</details>

<details>
<summary><code>docpipe/serve/cli.py</code></summary>

cli.py: `docpipe export` and `docpipe serve`.

    docpipe export HARVEST_DIR --out values.csv
    docpipe export HARVEST_DIR --format jsonl --level B --out values.jsonl
    docpipe export HARVEST_DIR --what states --out states.csv
    docpipe export HARVEST_DIR --what refusals --out refusals.csv
    docpipe serve HARVEST_DIR --http [--port 8750]
    docpipe serve HARVEST_DIR --mcp

Both read the harvest once (`values.py`). With a profile the values carry
the labels of its spec and the transcribed mark of its database; without
one they carry what the harvest itself says.

The corpus database is named as the chat names it: `--db`, else
INFERENCE_DB_PATH, else the profile's when it is there. `serve` opens the
passage search on it (`passages.py`); without a database, or without the
word index `docpipe lexical` builds, the search says so and answers none.
`export` does not need the passages and does not open them.

Author: Felix Vossel

</details>

[Back to the index](../README.md)
