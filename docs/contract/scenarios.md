# The harvest contract: scenarios

Generated from `profiles/scenarios/extraction_schema.json` by `scripts/build_docs.py`, which is itself generated from the profile's `extraction_spec.json` by `docpipe/extraction/schema.py`. Edit neither: change the spec and regenerate.

One JSON object per line of a harvest file. Every line is one of the kinds below and nothing else, and each of them is closed (`additionalProperties: false`) — a new record kind costs a branch in `docpipe/extraction/schema.py`, a regeneration of both checked-in schemas, and a branch in `read_harvest` in `scripts/harvest_compare.py`.

## `parameter_state`

What one parameter of the spec came to in this document. Every other state in this file belongs to a row, so a parameter that produced no row left no byte at all and "the document does not carry it" and "it was never asked" were the same empty file.

### `document_id`

### `kind`

### `parameter`

The spec's uri for the parameter, the same key a tuple carries.

### `refusals`

### `state`

### `tuples`

## `refusal`

### `claim`

The claim as the model returned it. A dead-server sentinel carries _harvest_failed with _why, or _cut_off.

### `kind`

### `owner`

[owner_kind, owner_id]

### `parameter`

The spec parameter, or whatever the claim named.

### `reason`

Why the claim was refused; one of the reason families of verify.py and pipeline.py.

## `summary`

The last line of the file: how this document's own values are distributed. A contested identity is decided by the serializer and a second reading is a later pass, so neither is counted here -- the levels are a floor, and the graph side recomputes them.

### `document_id`

### `image_origin`

Values read out of a table or figure image rather than the document's text.

### `kind`

### `levels`

How many values reached each level.

### `reasons`

Why values are not an A, counted. A closed list: a reason nobody can enumerate is a reason nobody can count.

### `refusals`

### `tuples`

## `publication_abstract`

How the row becomes a node:

- `node`: `scenariobundle`
- `property`: `{'predicate': 'abstract', 'prefix': 'dc'}`

<details><summary>Why</summary>

On the bundle, not on the report: the shapes carry the study's abstract there.

</details>

### `compute`

The sandbox runs behind a computed value: {code, stdout, ok, error}.

### `computed`

The value came out of the sandbox, not off the page; the quote proves the inputs it was computed from.

### `flags`

Non-fatal verifier findings. mapped:<axis>:<wording>-><uri> is the model mapping a word the spec does not list; period:* says whether a bare amount was shown to be a yearly one; review:* is what a second reading of this value under a narrower window came to, and only review:disagree is a reason.

### `kind`

### `parameter`

Spec parameter: Abstract.

The prompt's own wording:

> Um WELCHES Feld handelt es sich bei diesem Wert? Entscheide danach, was die Quelle über ihn sagt: die Beschriftung, die Einheit und die Überschrift des Abschnitts. Zitiere die Stelle, aus der das hervorgeht.

### `parameter_quote`

The verbatim passage carrying 'parameter'. Present exactly when parameter_state is 'read'.

### `parameter_raw`

The document's own wording 'parameter' was read from. This is what a later re-mapping onto a changed vocabulary works on, so a choice without it is counted (raw_missing).

### `parameter_raw_foreign`

The wording does not name the option chosen for 'parameter' -- the model mapped a word the spec does not list onto this class. Kept and counted, not refused: some of those mappings are right.

### `parameter_seen`

A wording the model noticed for 'parameter' while answering 'not stated'. Vocabulary review material, never evidence.

### `parameter_source`

Which source the passage for 'parameter' was found in. How far that may be from the row is the axis' own rule (own | local | any).

### `parameter_state`

How the coordinate 'parameter' ended. Always present: a missing key and a refused reading must not look alike.

### `parameter_window`

[stage, index] of the window 'parameter' was read in. A coordinate read in window 1 and one read in window 22 cost different amounts. `frame` is the one that is not a window: the coordinate was read ONCE for the document and applied to this row, and the index is which of the document's pairs it came from.

### `provenance`

### `quote`

The passage of the owner source that contains the value. Whitespace-collapsed containment; a retyped table row may be repaired, which sets the flag quote_repaired.

### `tier`

text_located: the quote sits in the document's own refined text, so it can be checked against the PDF. visual_source: it sits in a table transcription, a caption or a figure description, which are model output and want human curation.

### `unit`

Empty: a wording has no unit. The key is present so every row has the same shape.

### `unit_raw`

Empty, as unit.

### `value`

The wording as the document writes it.

### `value_raw`

The wording before any tidying (an organisation's legal form, a title's line break).

### `value_uri`

The entry of the parameter's own vocabulary the wording resolved to; null when the list did not hold it. Only a category parameter has a vocabulary, so this one never writes the key at all.

## `publication_author`

How the row becomes a node:

- `class`: `OEO_00000064`
- `edge_from`: `{'label': 'has author', 'node': 'studyreport', 'predicate': 'OEO_00000506', 'prefix': 'oeo'}`
- `node`: `author`
- `property`: `{'label': 'label', 'predicate': 'label', 'prefix': 'rdfs'}`

<details><summary>Why</summary>

One node per distinct name. Two spellings of one person are one node and keep both passages.

</details>

### `compute`

The sandbox runs behind a computed value: {code, stdout, ok, error}.

### `computed`

The value came out of the sandbox, not off the page; the quote proves the inputs it was computed from.

### `flags`

Non-fatal verifier findings. mapped:<axis>:<wording>-><uri> is the model mapping a word the spec does not list; period:* says whether a bare amount was shown to be a yearly one; review:* is what a second reading of this value under a narrower window came to, and only review:disagree is a reason.

### `kind`

### `parameter`

Spec parameter: Autorin oder Autor.

The prompt's own wording:

> Um WELCHES Feld handelt es sich bei diesem Wert? Entscheide danach, was die Quelle über ihn sagt: die Beschriftung, die Einheit und die Überschrift des Abschnitts. Zitiere die Stelle, aus der das hervorgeht.

### `parameter_quote`

The verbatim passage carrying 'parameter'. Present exactly when parameter_state is 'read'.

### `parameter_raw`

The document's own wording 'parameter' was read from. This is what a later re-mapping onto a changed vocabulary works on, so a choice without it is counted (raw_missing).

### `parameter_raw_foreign`

The wording does not name the option chosen for 'parameter' -- the model mapped a word the spec does not list onto this class. Kept and counted, not refused: some of those mappings are right.

### `parameter_seen`

A wording the model noticed for 'parameter' while answering 'not stated'. Vocabulary review material, never evidence.

### `parameter_source`

Which source the passage for 'parameter' was found in. How far that may be from the row is the axis' own rule (own | local | any).

### `parameter_state`

How the coordinate 'parameter' ended. Always present: a missing key and a refused reading must not look alike.

### `parameter_window`

[stage, index] of the window 'parameter' was read in. A coordinate read in window 1 and one read in window 22 cost different amounts. `frame` is the one that is not a window: the coordinate was read ONCE for the document and applied to this row, and the index is which of the document's pairs it came from.

### `provenance`

### `quote`

The passage of the owner source that contains the value. Whitespace-collapsed containment; a retyped table row may be repaired, which sets the flag quote_repaired.

### `tier`

text_located: the quote sits in the document's own refined text, so it can be checked against the PDF. visual_source: it sits in a table transcription, a caption or a figure description, which are model output and want human curation.

### `unit`

Empty: a wording has no unit. The key is present so every row has the same shape.

### `unit_raw`

Empty, as unit.

### `value`

The wording as the document writes it.

### `value_raw`

The wording before any tidying (an organisation's legal form, a title's line break).

### `value_uri`

The entry of the parameter's own vocabulary the wording resolved to; null when the list did not hold it. Only a category parameter has a vocabulary, so this one never writes the key at all.

## `publication_date`

How the row becomes a node:

- `node`: `studyreport`
- `property`: `{'datatype': 'xsd:dateTime', 'label': 'has publication date', 'predicate': 'OEO_00390096', 'prefix': 'oeo'}`

<details><summary>Why</summary>

A PDF states a year; the serializer pads it to YYYY-01-01T00:00:00, which the document does not say. The day and the month are the datatype's, not the paper's.

</details>

### `compute`

The sandbox runs behind a computed value: {code, stdout, ok, error}.

### `computed`

The value came out of the sandbox, not off the page; the quote proves the inputs it was computed from.

### `flags`

Non-fatal verifier findings. mapped:<axis>:<wording>-><uri> is the model mapping a word the spec does not list; period:* says whether a bare amount was shown to be a yearly one; review:* is what a second reading of this value under a narrower window came to, and only review:disagree is a reason.

### `kind`

### `parameter`

Spec parameter: Erscheinungsjahr.

The prompt's own wording:

> Um WELCHES Feld handelt es sich bei diesem Wert? Entscheide danach, was die Quelle über ihn sagt: die Beschriftung, die Einheit und die Überschrift des Abschnitts. Zitiere die Stelle, aus der das hervorgeht.

### `parameter_quote`

The verbatim passage carrying 'parameter'. Present exactly when parameter_state is 'read'.

### `parameter_raw`

The document's own wording 'parameter' was read from. This is what a later re-mapping onto a changed vocabulary works on, so a choice without it is counted (raw_missing).

### `parameter_raw_foreign`

The wording does not name the option chosen for 'parameter' -- the model mapped a word the spec does not list onto this class. Kept and counted, not refused: some of those mappings are right.

### `parameter_seen`

A wording the model noticed for 'parameter' while answering 'not stated'. Vocabulary review material, never evidence.

### `parameter_source`

Which source the passage for 'parameter' was found in. How far that may be from the row is the axis' own rule (own | local | any).

### `parameter_state`

How the coordinate 'parameter' ended. Always present: a missing key and a refused reading must not look alike.

### `parameter_window`

[stage, index] of the window 'parameter' was read in. A coordinate read in window 1 and one read in window 22 cost different amounts. `frame` is the one that is not a window: the coordinate was read ONCE for the document and applied to this row, and the index is which of the document's pairs it came from.

### `provenance`

### `quote`

The passage of the owner source that contains the value. Whitespace-collapsed containment; a retyped table row may be repaired, which sets the flag quote_repaired.

### `tier`

text_located: the quote sits in the document's own refined text, so it can be checked against the PDF. visual_source: it sits in a table transcription, a caption or a figure description, which are model output and want human curation.

### `unit`

Empty: a wording has no unit. The key is present so every row has the same shape.

### `unit_raw`

Empty, as unit.

### `value`

The wording as the document writes it.

### `value_raw`

The wording before any tidying (an organisation's legal form, a title's line break).

### `value_uri`

The entry of the parameter's own vocabulary the wording resolved to; null when the list did not hold it. Only a category parameter has a vocabulary, so this one never writes the key at all.

## `publication_doi`

How the row becomes a node:

- `node`: `studyreport`
- `property`: `{'label': 'has doi', 'predicate': 'OEO_00390098', 'prefix': 'oeo'}`

### `compute`

The sandbox runs behind a computed value: {code, stdout, ok, error}.

### `computed`

The value came out of the sandbox, not off the page; the quote proves the inputs it was computed from.

### `flags`

Non-fatal verifier findings. mapped:<axis>:<wording>-><uri> is the model mapping a word the spec does not list; period:* says whether a bare amount was shown to be a yearly one; review:* is what a second reading of this value under a narrower window came to, and only review:disagree is a reason.

### `kind`

### `parameter`

Spec parameter: DOI.

The prompt's own wording:

> Um WELCHES Feld handelt es sich bei diesem Wert? Entscheide danach, was die Quelle über ihn sagt: die Beschriftung, die Einheit und die Überschrift des Abschnitts. Zitiere die Stelle, aus der das hervorgeht.

### `parameter_quote`

The verbatim passage carrying 'parameter'. Present exactly when parameter_state is 'read'.

### `parameter_raw`

The document's own wording 'parameter' was read from. This is what a later re-mapping onto a changed vocabulary works on, so a choice without it is counted (raw_missing).

### `parameter_raw_foreign`

The wording does not name the option chosen for 'parameter' -- the model mapped a word the spec does not list onto this class. Kept and counted, not refused: some of those mappings are right.

### `parameter_seen`

A wording the model noticed for 'parameter' while answering 'not stated'. Vocabulary review material, never evidence.

### `parameter_source`

Which source the passage for 'parameter' was found in. How far that may be from the row is the axis' own rule (own | local | any).

### `parameter_state`

How the coordinate 'parameter' ended. Always present: a missing key and a refused reading must not look alike.

### `parameter_window`

[stage, index] of the window 'parameter' was read in. A coordinate read in window 1 and one read in window 22 cost different amounts. `frame` is the one that is not a window: the coordinate was read ONCE for the document and applied to this row, and the index is which of the document's pairs it came from.

### `provenance`

### `quote`

The passage of the owner source that contains the value. Whitespace-collapsed containment; a retyped table row may be repaired, which sets the flag quote_repaired.

### `tier`

text_located: the quote sits in the document's own refined text, so it can be checked against the PDF. visual_source: it sits in a table transcription, a caption or a figure description, which are model output and want human curation.

### `unit`

Empty: a wording has no unit. The key is present so every row has the same shape.

### `unit_raw`

Empty, as unit.

### `value`

The wording as the document writes it.

### `value_raw`

The wording before any tidying (an organisation's legal form, a title's line break).

### `value_uri`

The entry of the parameter's own vocabulary the wording resolved to; null when the list did not hold it. Only a category parameter has a vocabulary, so this one never writes the key at all.

## `publication_title`

How the row becomes a node:

- `class`: `OEO_00020012`
- `node`: `studyreport`
- `property`: `{'label': 'label', 'predicate': 'label', 'prefix': 'rdfs'}`

<details><summary>Why</summary>

Mints the study report. The title is also the bundle's label when no project name was read, and half of every scenario factsheet's IRI. Mint recipes are prose here, not keys: see the _comment.

</details>

### `compute`

The sandbox runs behind a computed value: {code, stdout, ok, error}.

### `computed`

The value came out of the sandbox, not off the page; the quote proves the inputs it was computed from.

### `flags`

Non-fatal verifier findings. mapped:<axis>:<wording>-><uri> is the model mapping a word the spec does not list; period:* says whether a bare amount was shown to be a yearly one; review:* is what a second reading of this value under a narrower window came to, and only review:disagree is a reason.

### `kind`

### `parameter`

Spec parameter: Titel der Publikation.

The prompt's own wording:

> Um WELCHES Feld handelt es sich bei diesem Wert? Entscheide danach, was die Quelle über ihn sagt: die Beschriftung, die Einheit und die Überschrift des Abschnitts. Zitiere die Stelle, aus der das hervorgeht.

### `parameter_quote`

The verbatim passage carrying 'parameter'. Present exactly when parameter_state is 'read'.

### `parameter_raw`

The document's own wording 'parameter' was read from. This is what a later re-mapping onto a changed vocabulary works on, so a choice without it is counted (raw_missing).

### `parameter_raw_foreign`

The wording does not name the option chosen for 'parameter' -- the model mapped a word the spec does not list onto this class. Kept and counted, not refused: some of those mappings are right.

### `parameter_seen`

A wording the model noticed for 'parameter' while answering 'not stated'. Vocabulary review material, never evidence.

### `parameter_source`

Which source the passage for 'parameter' was found in. How far that may be from the row is the axis' own rule (own | local | any).

### `parameter_state`

How the coordinate 'parameter' ended. Always present: a missing key and a refused reading must not look alike.

### `parameter_window`

[stage, index] of the window 'parameter' was read in. A coordinate read in window 1 and one read in window 22 cost different amounts. `frame` is the one that is not a window: the coordinate was read ONCE for the document and applied to this row, and the index is which of the document's pairs it came from.

### `provenance`

### `quote`

The passage of the owner source that contains the value. Whitespace-collapsed containment; a retyped table row may be repaired, which sets the flag quote_repaired.

### `tier`

text_located: the quote sits in the document's own refined text, so it can be checked against the PDF. visual_source: it sits in a table transcription, a caption or a figure description, which are model output and want human curation.

### `unit`

Empty: a wording has no unit. The key is present so every row has the same shape.

### `unit_raw`

Empty, as unit.

### `value`

The wording as the document writes it.

### `value_raw`

The wording before any tidying (an organisation's legal form, a title's line break).

### `value_uri`

The entry of the parameter's own vocabulary the wording resolved to; null when the list did not hold it. Only a category parameter has a vocabulary, so this one never writes the key at all.

## `scenario_abstract`

How the row becomes a node:

- `node`: `scenariofactsheet`
- `property`: `{'predicate': 'abstract', 'prefix': 'dc'}`

### `compute`

The sandbox runs behind a computed value: {code, stdout, ok, error}.

### `computed`

The value came out of the sandbox, not off the page; the quote proves the inputs it was computed from.

### `flags`

Non-fatal verifier findings. mapped:<axis>:<wording>-><uri> is the model mapping a word the spec does not list; period:* says whether a bare amount was shown to be a yearly one; review:* is what a second reading of this value under a narrower window came to, and only review:disagree is a reason.

### `kind`

### `parameter`

Spec parameter: Kurzbeschreibung eines Szenarios.

The prompt's own wording:

> Um WELCHES Feld handelt es sich bei diesem Wert? Entscheide danach, was die Quelle über ihn sagt: die Beschriftung, die Einheit und die Überschrift des Abschnitts. Zitiere die Stelle, aus der das hervorgeht.

### `parameter_quote`

The verbatim passage carrying 'parameter'. Present exactly when parameter_state is 'read'.

### `parameter_raw`

The document's own wording 'parameter' was read from. This is what a later re-mapping onto a changed vocabulary works on, so a choice without it is counted (raw_missing).

### `parameter_raw_foreign`

The wording does not name the option chosen for 'parameter' -- the model mapped a word the spec does not list onto this class. Kept and counted, not refused: some of those mappings are right.

### `parameter_seen`

A wording the model noticed for 'parameter' while answering 'not stated'. Vocabulary review material, never evidence.

### `parameter_source`

Which source the passage for 'parameter' was found in. How far that may be from the row is the axis' own rule (own | local | any).

### `parameter_state`

How the coordinate 'parameter' ended. Always present: a missing key and a refused reading must not look alike.

### `parameter_window`

[stage, index] of the window 'parameter' was read in. A coordinate read in window 1 and one read in window 22 cost different amounts. `frame` is the one that is not a window: the coordinate was read ONCE for the document and applied to this row, and the index is which of the document's pairs it came from.

### `provenance`

### `quote`

The passage of the owner source that contains the value. Whitespace-collapsed containment; a retyped table row may be repaired, which sets the flag quote_repaired.

### `scenario`

Axis 'scenario' of Kurzbeschreibung eines Szenarios. null unless scenario_state is 'read' or 'derived'.

The prompt's own wording:

> Auf welches Szenario dieser Publikation bezieht sich der Wert? Die Liste führt die Laufkennungen, die genau diese Publikation in der AR6-Datenbank dokumentiert. Im Text stehen sie fast nie, dort heißt dasselbe Szenario "Current Policies" oder "the NDC scenario". Nennt das Dokument nur die Familie, ist "Szenario-Familie" die richtige Antwort und keine Kennung. Belege mit einer Passage aus der Quelle der Zeile selbst oder aus dem Abschnitt, in dem diese Quelle steht. Steht die eigene Quelle unter den gezeigten, nennt die Anfrage sie als "source"; steht auch ihr Abschnitt darunter, als "section".

- `class`: `OEO_00000365`
- `linked_by`: `{'label': 'has part', 'node': 'scenariobundle', 'predicate': 'BFO_0000051', 'prefix': 'obo'}`
- `node`: `scenariofactsheet`
- `role`: `parent`

<details><summary>Why</summary>

Which factsheet holds the value. Unlike the kwp `parent` axis there is no map from the answer to a container class: the answer IS the identity of a node minted per document from the AR6 run the wording resolves to. A wording that resolves to no run is its own factsheet, and an out: entry is none at all.

</details>

### `scenario_quote`

The verbatim passage carrying 'scenario'. Present exactly when scenario_state is 'read'.

### `scenario_raw`

The document's own wording 'scenario' was read from. This is what a later re-mapping onto a changed vocabulary works on, so a choice without it is counted (raw_missing).

### `scenario_raw_foreign`

The wording does not name the option chosen for 'scenario' -- the model mapped a word the spec does not list onto this class. Kept and counted, not refused: some of those mappings are right.

### `scenario_seen`

A wording the model noticed for 'scenario' while answering 'not stated'. Vocabulary review material, never evidence.

### `scenario_source`

Which source the passage for 'scenario' was found in. How far that may be from the row is the axis' own rule (own | local | any).

### `scenario_state`

How the coordinate 'scenario' ended. Always present: a missing key and a refused reading must not look alike.

### `scenario_window`

[stage, index] of the window 'scenario' was read in. A coordinate read in window 1 and one read in window 22 cost different amounts. `frame` is the one that is not a window: the coordinate was read ONCE for the document and applied to this row, and the index is which of the document's pairs it came from.

### `tier`

text_located: the quote sits in the document's own refined text, so it can be checked against the PDF. visual_source: it sits in a table transcription, a caption or a figure description, which are model output and want human curation.

### `unit`

Empty: a wording has no unit. The key is present so every row has the same shape.

### `unit_raw`

Empty, as unit.

### `value`

The wording as the document writes it.

### `value_raw`

The wording before any tidying (an organisation's legal form, a title's line break).

### `value_uri`

The entry of the parameter's own vocabulary the wording resolved to; null when the list did not hold it. Only a category parameter has a vocabulary, so this one never writes the key at all.

A coordinate is `null` unless its `<axis>_state` says it was read or derived — that is what the `allOf` branches encode, one per coordinate.

## `scenario_label`

How the row becomes a node:

- `also`: `{'predicate': 'acronym', 'prefix': 'dc'}`
- `class`: `OEO_00000365`
- `node`: `scenariofactsheet`
- `property`: `{'label': 'label', 'predicate': 'label', 'prefix': 'rdfs'}`

<details><summary>Why</summary>

The AR6 run name labels the factsheet; the document's own wording is the acronym beside it. With no long name known for a run both carry the same string, which is the usual case in this corpus.

</details>

### `compute`

The sandbox runs behind a computed value: {code, stdout, ok, error}.

### `computed`

The value came out of the sandbox, not off the page; the quote proves the inputs it was computed from.

### `flags`

Non-fatal verifier findings. mapped:<axis>:<wording>-><uri> is the model mapping a word the spec does not list; period:* says whether a bare amount was shown to be a yearly one; review:* is what a second reading of this value under a narrower window came to, and only review:disagree is a reason.

### `kind`

### `parameter`

Spec parameter: Name des Szenarios.

The prompt's own wording:

> Um WELCHES Feld handelt es sich bei diesem Wert? Entscheide danach, was die Quelle über ihn sagt: die Beschriftung, die Einheit und die Überschrift des Abschnitts. Zitiere die Stelle, aus der das hervorgeht.

### `parameter_quote`

The verbatim passage carrying 'parameter'. Present exactly when parameter_state is 'read'.

### `parameter_raw`

The document's own wording 'parameter' was read from. This is what a later re-mapping onto a changed vocabulary works on, so a choice without it is counted (raw_missing).

### `parameter_raw_foreign`

The wording does not name the option chosen for 'parameter' -- the model mapped a word the spec does not list onto this class. Kept and counted, not refused: some of those mappings are right.

### `parameter_seen`

A wording the model noticed for 'parameter' while answering 'not stated'. Vocabulary review material, never evidence.

### `parameter_source`

Which source the passage for 'parameter' was found in. How far that may be from the row is the axis' own rule (own | local | any).

### `parameter_state`

How the coordinate 'parameter' ended. Always present: a missing key and a refused reading must not look alike.

### `parameter_window`

[stage, index] of the window 'parameter' was read in. A coordinate read in window 1 and one read in window 22 cost different amounts. `frame` is the one that is not a window: the coordinate was read ONCE for the document and applied to this row, and the index is which of the document's pairs it came from.

### `provenance`

### `quote`

The passage of the owner source that contains the value. Whitespace-collapsed containment; a retyped table row may be repaired, which sets the flag quote_repaired.

### `tier`

text_located: the quote sits in the document's own refined text, so it can be checked against the PDF. visual_source: it sits in a table transcription, a caption or a figure description, which are model output and want human curation.

### `unit`

Empty: a wording has no unit. The key is present so every row has the same shape.

### `unit_raw`

Empty, as unit.

### `value`

The wording as the document writes it.

### `value_raw`

The wording before any tidying (an organisation's legal form, a title's line break).

### `value_uri`

The entry of the parameter's own vocabulary the wording resolved to; null when the list did not hold it. The list is per document: the profile supplies it before the harvest, so it is not in this schema.

## `scenario_region`

How the row becomes a node:

- `node`: `scenariofactsheet`
- `property`: `{'label': 'has spatial region', 'predicate': 'OEO_00010378', 'prefix': 'oeo'}`

<details><summary>Why</summary>

The object is an OEKG region individual that already exists over there and is only referenced. A wording the list did not hold mints nothing: writing our own gloss under oekg/region/ would put a 250th region beside the 249 real ones. The predicate is oeo:OEO_00010378 has spatial region and not oeo:OEO_00020220 has study region, although the second says exactly what we mean: its domain is oeo:OEO_00000364 scenario and the subject here is the scenario FACTSHEET, which is not one. has spatial region is its direct parent, domained on information content entity, which the factsheet is.

</details>

### `compute`

The sandbox runs behind a computed value: {code, stdout, ok, error}.

### `computed`

The value came out of the sandbox, not off the page; the quote proves the inputs it was computed from.

### `flags`

Non-fatal verifier findings. mapped:<axis>:<wording>-><uri> is the model mapping a word the spec does not list; period:* says whether a bare amount was shown to be a yearly one; review:* is what a second reading of this value under a narrower window came to, and only review:disagree is a reason.

### `kind`

### `parameter`

Spec parameter: Betrachtete Region eines Szenarios.

The prompt's own wording:

> Um WELCHES Feld handelt es sich bei diesem Wert? Entscheide danach, was die Quelle über ihn sagt: die Beschriftung, die Einheit und die Überschrift des Abschnitts. Zitiere die Stelle, aus der das hervorgeht.

### `parameter_quote`

The verbatim passage carrying 'parameter'. Present exactly when parameter_state is 'read'.

### `parameter_raw`

The document's own wording 'parameter' was read from. This is what a later re-mapping onto a changed vocabulary works on, so a choice without it is counted (raw_missing).

### `parameter_raw_foreign`

The wording does not name the option chosen for 'parameter' -- the model mapped a word the spec does not list onto this class. Kept and counted, not refused: some of those mappings are right.

### `parameter_seen`

A wording the model noticed for 'parameter' while answering 'not stated'. Vocabulary review material, never evidence.

### `parameter_source`

Which source the passage for 'parameter' was found in. How far that may be from the row is the axis' own rule (own | local | any).

### `parameter_state`

How the coordinate 'parameter' ended. Always present: a missing key and a refused reading must not look alike.

### `parameter_window`

[stage, index] of the window 'parameter' was read in. A coordinate read in window 1 and one read in window 22 cost different amounts. `frame` is the one that is not a window: the coordinate was read ONCE for the document and applied to this row, and the index is which of the document's pairs it came from.

### `provenance`

### `quote`

The passage of the owner source that contains the value. Whitespace-collapsed containment; a retyped table row may be repaired, which sets the flag quote_repaired.

### `scenario`

Axis 'scenario' of Betrachtete Region eines Szenarios. null unless scenario_state is 'read' or 'derived'.

The prompt's own wording:

> Auf welches Szenario dieser Publikation bezieht sich der Wert? Die Liste führt die Laufkennungen, die genau diese Publikation in der AR6-Datenbank dokumentiert. Im Text stehen sie fast nie, dort heißt dasselbe Szenario "Current Policies" oder "the NDC scenario". Nennt das Dokument nur die Familie, ist "Szenario-Familie" die richtige Antwort und keine Kennung. Belege mit einer Passage aus der Quelle der Zeile, aus dem Abschnitt, in dem sie steht, oder von der Nachbarseite. Die ersten beiden nennt die Anfrage als "source" und "section", soweit sie mitgezeigt werden.

- `class`: `OEO_00000365`
- `linked_by`: `{'label': 'has part', 'node': 'scenariobundle', 'predicate': 'BFO_0000051', 'prefix': 'obo'}`
- `node`: `scenariofactsheet`
- `role`: `parent`

<details><summary>Why</summary>

Which factsheet holds the value. Unlike the kwp `parent` axis there is no map from the answer to a container class: the answer IS the identity of a node minted per document from the AR6 run the wording resolves to. A wording that resolves to no run is its own factsheet, and an out: entry is none at all.

</details>

### `scenario_quote`

The verbatim passage carrying 'scenario'. Present exactly when scenario_state is 'read'.

### `scenario_raw`

The document's own wording 'scenario' was read from. This is what a later re-mapping onto a changed vocabulary works on, so a choice without it is counted (raw_missing).

### `scenario_raw_foreign`

The wording does not name the option chosen for 'scenario' -- the model mapped a word the spec does not list onto this class. Kept and counted, not refused: some of those mappings are right.

### `scenario_seen`

A wording the model noticed for 'scenario' while answering 'not stated'. Vocabulary review material, never evidence.

### `scenario_source`

Which source the passage for 'scenario' was found in. How far that may be from the row is the axis' own rule (own | local | any).

### `scenario_state`

How the coordinate 'scenario' ended. Always present: a missing key and a refused reading must not look alike.

### `scenario_window`

[stage, index] of the window 'scenario' was read in. A coordinate read in window 1 and one read in window 22 cost different amounts. `frame` is the one that is not a window: the coordinate was read ONCE for the document and applied to this row, and the index is which of the document's pairs it came from.

### `tier`

text_located: the quote sits in the document's own refined text, so it can be checked against the PDF. visual_source: it sits in a table transcription, a caption or a figure description, which are model output and want human curation.

### `unit`

Empty: a wording has no unit. The key is present so every row has the same shape.

### `unit_raw`

Empty, as unit.

### `value`

The wording as the document writes it.

### `value_raw`

The wording before any tidying (an organisation's legal form, a title's line break).

### `value_uri`

The entry of the parameter's own vocabulary the wording resolved to; null when the list did not hold it. The list is per document: the profile supplies it before the harvest, so it is not in this schema.

A coordinate is `null` unless its `<axis>_state` says it was read or derived — that is what the `allOf` branches encode, one per coordinate.

## `scenario_type`

How the row becomes a node:

- `node`: `scenariofactsheet`
- `property`: `{'label': 'has scenario type', 'predicate': 'OEO_00390073', 'prefix': 'oeo'}`

<details><summary>Why</summary>

The object is one of the classes the shapes accept, chosen from the list, never written. Every factsheet additionally carries OEO_00020517 IAM scenario, which is not behind a harvested value and stands in the serializer.

</details>

### `compute`

The sandbox runs behind a computed value: {code, stdout, ok, error}.

### `computed`

The value came out of the sandbox, not off the page; the quote proves the inputs it was computed from.

### `flags`

Non-fatal verifier findings. mapped:<axis>:<wording>-><uri> is the model mapping a word the spec does not list; period:* says whether a bare amount was shown to be a yearly one; review:* is what a second reading of this value under a narrower window came to, and only review:disagree is a reason.

### `kind`

### `parameter`

Spec parameter: Art des Szenarios.

The prompt's own wording:

> Um WELCHES Feld handelt es sich bei diesem Wert? Entscheide danach, was die Quelle über ihn sagt: die Beschriftung, die Einheit und die Überschrift des Abschnitts. Zitiere die Stelle, aus der das hervorgeht.

### `parameter_quote`

The verbatim passage carrying 'parameter'. Present exactly when parameter_state is 'read'.

### `parameter_raw`

The document's own wording 'parameter' was read from. This is what a later re-mapping onto a changed vocabulary works on, so a choice without it is counted (raw_missing).

### `parameter_raw_foreign`

The wording does not name the option chosen for 'parameter' -- the model mapped a word the spec does not list onto this class. Kept and counted, not refused: some of those mappings are right.

### `parameter_seen`

A wording the model noticed for 'parameter' while answering 'not stated'. Vocabulary review material, never evidence.

### `parameter_source`

Which source the passage for 'parameter' was found in. How far that may be from the row is the axis' own rule (own | local | any).

### `parameter_state`

How the coordinate 'parameter' ended. Always present: a missing key and a refused reading must not look alike.

### `parameter_window`

[stage, index] of the window 'parameter' was read in. A coordinate read in window 1 and one read in window 22 cost different amounts. `frame` is the one that is not a window: the coordinate was read ONCE for the document and applied to this row, and the index is which of the document's pairs it came from.

### `provenance`

### `quote`

The passage of the owner source that contains the value. Whitespace-collapsed containment; a retyped table row may be repaired, which sets the flag quote_repaired.

### `scenario`

Axis 'scenario' of Art des Szenarios. null unless scenario_state is 'read' or 'derived'.

The prompt's own wording:

> Auf welches Szenario dieser Publikation bezieht sich der Wert? Die Liste führt die Laufkennungen, die genau diese Publikation in der AR6-Datenbank dokumentiert. Im Text stehen sie fast nie, dort heißt dasselbe Szenario "Current Policies" oder "the NDC scenario". Nennt das Dokument nur die Familie, ist "Szenario-Familie" die richtige Antwort und keine Kennung. Belege mit einer Passage aus der Quelle der Zeile selbst oder aus dem Abschnitt, in dem diese Quelle steht. Steht die eigene Quelle unter den gezeigten, nennt die Anfrage sie als "source"; steht auch ihr Abschnitt darunter, als "section".

- `class`: `OEO_00000365`
- `linked_by`: `{'label': 'has part', 'node': 'scenariobundle', 'predicate': 'BFO_0000051', 'prefix': 'obo'}`
- `node`: `scenariofactsheet`
- `role`: `parent`

<details><summary>Why</summary>

Which factsheet holds the value. Unlike the kwp `parent` axis there is no map from the answer to a container class: the answer IS the identity of a node minted per document from the AR6 run the wording resolves to. A wording that resolves to no run is its own factsheet, and an out: entry is none at all.

</details>

### `scenario_quote`

The verbatim passage carrying 'scenario'. Present exactly when scenario_state is 'read'.

### `scenario_raw`

The document's own wording 'scenario' was read from. This is what a later re-mapping onto a changed vocabulary works on, so a choice without it is counted (raw_missing).

### `scenario_raw_foreign`

The wording does not name the option chosen for 'scenario' -- the model mapped a word the spec does not list onto this class. Kept and counted, not refused: some of those mappings are right.

### `scenario_seen`

A wording the model noticed for 'scenario' while answering 'not stated'. Vocabulary review material, never evidence.

### `scenario_source`

Which source the passage for 'scenario' was found in. How far that may be from the row is the axis' own rule (own | local | any).

### `scenario_state`

How the coordinate 'scenario' ended. Always present: a missing key and a refused reading must not look alike.

### `scenario_window`

[stage, index] of the window 'scenario' was read in. A coordinate read in window 1 and one read in window 22 cost different amounts. `frame` is the one that is not a window: the coordinate was read ONCE for the document and applied to this row, and the index is which of the document's pairs it came from.

### `tier`

text_located: the quote sits in the document's own refined text, so it can be checked against the PDF. visual_source: it sits in a table transcription, a caption or a figure description, which are model output and want human curation.

### `unit`

Empty: a wording has no unit. The key is present so every row has the same shape.

### `unit_raw`

Empty, as unit.

### `value`

The wording as the document writes it.

### `value_raw`

The wording before any tidying (an organisation's legal form, a title's line break).

### `value_uri`

The entry of the parameter's own vocabulary the wording resolved to; null when the list did not hold it. The list is closed; an entry beginning 'out:' is a deliberate non-class answer and mints no node.

<details><summary>What it may answer (18)</summary>

- **CO2 emission scenario** → `https://openenergyplatform.org/ontology/oeo/OEO_00020321` — A CO2 emission scenario is an emission scenario that describes a possible CO2 emission trajectory.
- **climate scenario** → `https://openenergyplatform.org/ontology/oeo/OEO_00030007` — A climate scenario is a scenario that describes a possible future state of a climate system.
  - also written: Klimaszenario
- **economic scenario** → `https://openenergyplatform.org/ontology/oeo/OEO_00030008` — An economic scenario is a scenario that describes a possible future state of economic systems.
  - also written: Wirtschaftsszenario
- **emission scenario** → `https://openenergyplatform.org/ontology/oeo/OEO_00030009` — An emission scenario is a scenario that describes a possible emission trajectory.
  - also written: emissions scenario, Emissionsszenario
- **energy scenario** → `https://openenergyplatform.org/ontology/oeo/OEO_00030010` — An energy scenario is a scenario that describes a possible future state of an energy system.
  - also written: Energieszenario
- **explorative scenario** → `https://openenergyplatform.org/ontology/oeo/OEO_00020248` — An explorative scenario is a scenario that contains certain constraints / statements regarding measures that are taken in the near future / today to explore where these measures will lead to in a later future. The later future is not predefined in the scenario.
  - also written: exploratory scenario, exploratives Szenario
- **greenhouse gas emission scenario** → `https://openenergyplatform.org/ontology/oeo/OEO_00020317` — A greenhouse gas emission scenario is an emission scenario that describes a possible greenhouse gas emission trajectory.
  - also written: GHG emission scenario
- **keine dieser Arten** → `out:not_in_list` — Der Text nennt eine Art, die keine dieser Klassen trifft. Nicht zu verwechseln damit, dass der Text gar keine Art nennt: das ist die Antwort, dass es in diesen Passagen nicht steht.
  - also written: die Art, die der Text nennt, steht nicht in der Liste
- **policy scenario** → `https://openenergyplatform.org/ontology/oeo/OEO_00020309` — A policy scenario is a scenario in which certain policy instruments or transformative measures and their impacts are assessed.
- **reference scenario** → `https://openenergyplatform.org/ontology/oeo/OEO_00020314` — A reference scenario is a scenario that is used as a reference, e.g. in a scenario comparison. It has the reference role.
  - also written: reference case
- **robust system scenario** → `https://openenergyplatform.org/ontology/oeo/OEO_00020411` — A robust system scenario is an explorative scenario that describes an energy system that is designed to evolve in a robust way.
  - also written: robust investment decision, robust transformation pathway
- **scenario** → `https://openenergyplatform.org/ontology/oeo/OEO_00000364` — A scenario is an information content entity that contains statements about a possible future development based on a coherent and internally consistent set of assumptions and their motivation.
  - also written: Szenario, narrative, storyline
- **statistically robust scenario** → `https://openenergyplatform.org/ontology/oeo/OEO_00020412` — A statistically robust scenario is a scenario that is the basis for statistically robust projection data.
- **sufficiency scenario** → `https://openenergyplatform.org/ontology/oeo/OEO_00020345` — A sufficiency scenario is a scenario that comprises sufficiency strategies.
- **target driven scenario** → `https://openenergyplatform.org/ontology/oeo/OEO_00020247` — A target driven scenario is a scenario that contains certain target constraints/ statements that in a possible future shall be realized. The path how the targets will be met is not predefined in the scenario.
  - also written: normative scenario, backcasting scenario, Zielszenario
- **with additional measures scenario** → `https://openenergyplatform.org/ontology/oeo/OEO_00020312` — A with additional measures scenario (WAM) is a policy scenario that includes policy instruments and transformative measures which have been adopted and implemented to mitigate climate change or meet energy objectives, as well as policy instruments and transformative measures which are planned for that purpose.
  - also written: WAM, with additional measures, WAM scenario
- **with existing measures scenario** → `https://openenergyplatform.org/ontology/oeo/OEO_00020311` — A with existing measures scenario (WEM) is a policy scenario that includes policy instruments and transformative measures that have been adopted and implemented.
  - also written: WEM, with existing measures, WEM scenario
- **without measures scenario** → `https://openenergyplatform.org/ontology/oeo/OEO_00020310` — A without measures scenario (WOM) is a policy scenario that excludes all policy instruments and transformative measures which are planned, adopted or implemented.
  - also written: WOM, without measures, WOM scenario

</details>

A coordinate is `null` unless its `<axis>_state` says it was read or derived — that is what the `allOf` branches encode, one per coordinate.

## `scenario_year`

How the row becomes a node:

- `node`: `scenariofactsheet`
- `property`: `{'datatype': 'xsd:dateTime', 'label': 'has scenario year value', 'predicate': 'OEO_00020440', 'prefix': 'oeo'}`

<details><summary>Why</summary>

One triple per distinct four-digit year on the factsheet, padded to the first of January as the datatype demands.

</details>

### `compute`

The sandbox runs behind a computed value: {code, stdout, ok, error}.

### `computed`

The value came out of the sandbox, not off the page; the quote proves the inputs it was computed from.

### `flags`

Non-fatal verifier findings. mapped:<axis>:<wording>-><uri> is the model mapping a word the spec does not list; period:* says whether a bare amount was shown to be a yearly one; review:* is what a second reading of this value under a narrower window came to, and only review:disagree is a reason.

### `kind`

### `parameter`

Spec parameter: Projiziertes Jahr eines Szenarios.

The prompt's own wording:

> Um WELCHES Feld handelt es sich bei diesem Wert? Entscheide danach, was die Quelle über ihn sagt: die Beschriftung, die Einheit und die Überschrift des Abschnitts. Zitiere die Stelle, aus der das hervorgeht.

### `parameter_quote`

The verbatim passage carrying 'parameter'. Present exactly when parameter_state is 'read'.

### `parameter_raw`

The document's own wording 'parameter' was read from. This is what a later re-mapping onto a changed vocabulary works on, so a choice without it is counted (raw_missing).

### `parameter_raw_foreign`

The wording does not name the option chosen for 'parameter' -- the model mapped a word the spec does not list onto this class. Kept and counted, not refused: some of those mappings are right.

### `parameter_seen`

A wording the model noticed for 'parameter' while answering 'not stated'. Vocabulary review material, never evidence.

### `parameter_source`

Which source the passage for 'parameter' was found in. How far that may be from the row is the axis' own rule (own | local | any).

### `parameter_state`

How the coordinate 'parameter' ended. Always present: a missing key and a refused reading must not look alike.

### `parameter_window`

[stage, index] of the window 'parameter' was read in. A coordinate read in window 1 and one read in window 22 cost different amounts. `frame` is the one that is not a window: the coordinate was read ONCE for the document and applied to this row, and the index is which of the document's pairs it came from.

### `provenance`

### `quote`

The passage of the owner source that contains the value. Whitespace-collapsed containment; a retyped table row may be repaired, which sets the flag quote_repaired.

### `scenario`

Axis 'scenario' of Projiziertes Jahr eines Szenarios. null unless scenario_state is 'read' or 'derived'.

The prompt's own wording:

> Auf welches Szenario dieser Publikation bezieht sich der Wert? Die Liste führt die Laufkennungen, die genau diese Publikation in der AR6-Datenbank dokumentiert. Im Text stehen sie fast nie, dort heißt dasselbe Szenario "Current Policies" oder "the NDC scenario". Nennt das Dokument nur die Familie, ist "Szenario-Familie" die richtige Antwort und keine Kennung. Belege mit einer Passage aus der Quelle der Zeile selbst oder aus dem Abschnitt, in dem diese Quelle steht. Steht die eigene Quelle unter den gezeigten, nennt die Anfrage sie als "source"; steht auch ihr Abschnitt darunter, als "section".

- `class`: `OEO_00000365`
- `linked_by`: `{'label': 'has part', 'node': 'scenariobundle', 'predicate': 'BFO_0000051', 'prefix': 'obo'}`
- `node`: `scenariofactsheet`
- `role`: `parent`

<details><summary>Why</summary>

Which factsheet holds the value. Unlike the kwp `parent` axis there is no map from the answer to a container class: the answer IS the identity of a node minted per document from the AR6 run the wording resolves to. A wording that resolves to no run is its own factsheet, and an out: entry is none at all.

</details>

### `scenario_quote`

The verbatim passage carrying 'scenario'. Present exactly when scenario_state is 'read'.

### `scenario_raw`

The document's own wording 'scenario' was read from. This is what a later re-mapping onto a changed vocabulary works on, so a choice without it is counted (raw_missing).

### `scenario_raw_foreign`

The wording does not name the option chosen for 'scenario' -- the model mapped a word the spec does not list onto this class. Kept and counted, not refused: some of those mappings are right.

### `scenario_seen`

A wording the model noticed for 'scenario' while answering 'not stated'. Vocabulary review material, never evidence.

### `scenario_source`

Which source the passage for 'scenario' was found in. How far that may be from the row is the axis' own rule (own | local | any).

### `scenario_state`

How the coordinate 'scenario' ended. Always present: a missing key and a refused reading must not look alike.

### `scenario_window`

[stage, index] of the window 'scenario' was read in. A coordinate read in window 1 and one read in window 22 cost different amounts. `frame` is the one that is not a window: the coordinate was read ONCE for the document and applied to this row, and the index is which of the document's pairs it came from.

### `tier`

text_located: the quote sits in the document's own refined text, so it can be checked against the PDF. visual_source: it sits in a table transcription, a caption or a figure description, which are model output and want human curation.

### `unit`

Empty: a wording has no unit. The key is present so every row has the same shape.

### `unit_raw`

Empty, as unit.

### `value`

The wording as the document writes it.

### `value_raw`

The wording before any tidying (an organisation's legal form, a title's line break).

### `value_uri`

The entry of the parameter's own vocabulary the wording resolved to; null when the list did not hold it. Only a category parameter has a vocabulary, so this one never writes the key at all.

A coordinate is `null` unless its `<axis>_state` says it was read or derived — that is what the `allOf` branches encode, one per coordinate.

## `study_acronym`

How the row becomes a node:

- `node`: `scenariobundle`
- `property`: `{'predicate': 'acronym', 'prefix': 'dc'}`

### `compute`

The sandbox runs behind a computed value: {code, stdout, ok, error}.

### `computed`

The value came out of the sandbox, not off the page; the quote proves the inputs it was computed from.

### `flags`

Non-fatal verifier findings. mapped:<axis>:<wording>-><uri> is the model mapping a word the spec does not list; period:* says whether a bare amount was shown to be a yearly one; review:* is what a second reading of this value under a narrower window came to, and only review:disagree is a reason.

### `kind`

### `parameter`

Spec parameter: Projektakronym.

The prompt's own wording:

> Um WELCHES Feld handelt es sich bei diesem Wert? Entscheide danach, was die Quelle über ihn sagt: die Beschriftung, die Einheit und die Überschrift des Abschnitts. Zitiere die Stelle, aus der das hervorgeht.

### `parameter_quote`

The verbatim passage carrying 'parameter'. Present exactly when parameter_state is 'read'.

### `parameter_raw`

The document's own wording 'parameter' was read from. This is what a later re-mapping onto a changed vocabulary works on, so a choice without it is counted (raw_missing).

### `parameter_raw_foreign`

The wording does not name the option chosen for 'parameter' -- the model mapped a word the spec does not list onto this class. Kept and counted, not refused: some of those mappings are right.

### `parameter_seen`

A wording the model noticed for 'parameter' while answering 'not stated'. Vocabulary review material, never evidence.

### `parameter_source`

Which source the passage for 'parameter' was found in. How far that may be from the row is the axis' own rule (own | local | any).

### `parameter_state`

How the coordinate 'parameter' ended. Always present: a missing key and a refused reading must not look alike.

### `parameter_window`

[stage, index] of the window 'parameter' was read in. A coordinate read in window 1 and one read in window 22 cost different amounts. `frame` is the one that is not a window: the coordinate was read ONCE for the document and applied to this row, and the index is which of the document's pairs it came from.

### `provenance`

### `quote`

The passage of the owner source that contains the value. Whitespace-collapsed containment; a retyped table row may be repaired, which sets the flag quote_repaired.

### `tier`

text_located: the quote sits in the document's own refined text, so it can be checked against the PDF. visual_source: it sits in a table transcription, a caption or a figure description, which are model output and want human curation.

### `unit`

Empty: a wording has no unit. The key is present so every row has the same shape.

### `unit_raw`

Empty, as unit.

### `value`

The wording as the document writes it.

### `value_raw`

The wording before any tidying (an organisation's legal form, a title's line break).

### `value_uri`

The entry of the parameter's own vocabulary the wording resolved to; null when the list did not hold it. Only a category parameter has a vocabulary, so this one never writes the key at all.

## `study_funder`

How the row becomes a node:

- `class`: `OEO_00090001`
- `edge_from`: `{'label': 'has funding source', 'node': 'scenariobundle', 'predicate': 'OEO_00000509', 'prefix': 'oeo'}`
- `node`: `funder`
- `property`: `{'label': 'label', 'predicate': 'label', 'prefix': 'rdfs'}`

### `compute`

The sandbox runs behind a computed value: {code, stdout, ok, error}.

### `computed`

The value came out of the sandbox, not off the page; the quote proves the inputs it was computed from.

### `flags`

Non-fatal verifier findings. mapped:<axis>:<wording>-><uri> is the model mapping a word the spec does not list; period:* says whether a bare amount was shown to be a yearly one; review:* is what a second reading of this value under a narrower window came to, and only review:disagree is a reason.

### `kind`

### `parameter`

Spec parameter: Fördermittelgeber.

The prompt's own wording:

> Um WELCHES Feld handelt es sich bei diesem Wert? Entscheide danach, was die Quelle über ihn sagt: die Beschriftung, die Einheit und die Überschrift des Abschnitts. Zitiere die Stelle, aus der das hervorgeht.

### `parameter_quote`

The verbatim passage carrying 'parameter'. Present exactly when parameter_state is 'read'.

### `parameter_raw`

The document's own wording 'parameter' was read from. This is what a later re-mapping onto a changed vocabulary works on, so a choice without it is counted (raw_missing).

### `parameter_raw_foreign`

The wording does not name the option chosen for 'parameter' -- the model mapped a word the spec does not list onto this class. Kept and counted, not refused: some of those mappings are right.

### `parameter_seen`

A wording the model noticed for 'parameter' while answering 'not stated'. Vocabulary review material, never evidence.

### `parameter_source`

Which source the passage for 'parameter' was found in. How far that may be from the row is the axis' own rule (own | local | any).

### `parameter_state`

How the coordinate 'parameter' ended. Always present: a missing key and a refused reading must not look alike.

### `parameter_window`

[stage, index] of the window 'parameter' was read in. A coordinate read in window 1 and one read in window 22 cost different amounts. `frame` is the one that is not a window: the coordinate was read ONCE for the document and applied to this row, and the index is which of the document's pairs it came from.

### `provenance`

### `quote`

The passage of the owner source that contains the value. Whitespace-collapsed containment; a retyped table row may be repaired, which sets the flag quote_repaired.

### `tier`

text_located: the quote sits in the document's own refined text, so it can be checked against the PDF. visual_source: it sits in a table transcription, a caption or a figure description, which are model output and want human curation.

### `unit`

Empty: a wording has no unit. The key is present so every row has the same shape.

### `unit_raw`

Empty, as unit.

### `value`

The wording as the document writes it.

### `value_raw`

The wording before any tidying (an organisation's legal form, a title's line break).

### `value_uri`

The entry of the parameter's own vocabulary the wording resolved to; null when the list did not hold it. Only a category parameter has a vocabulary, so this one never writes the key at all.

## `study_organisation`

How the row becomes a node:

- `class`: `OEO_00030022`
- `edge_from`: `{'label': 'has organisation', 'node': 'scenariobundle', 'predicate': 'OEO_00000510', 'prefix': 'oeo'}`
- `node`: `organisation`
- `property`: `{'label': 'label', 'predicate': 'label', 'prefix': 'rdfs'}`

### `compute`

The sandbox runs behind a computed value: {code, stdout, ok, error}.

### `computed`

The value came out of the sandbox, not off the page; the quote proves the inputs it was computed from.

### `flags`

Non-fatal verifier findings. mapped:<axis>:<wording>-><uri> is the model mapping a word the spec does not list; period:* says whether a bare amount was shown to be a yearly one; review:* is what a second reading of this value under a narrower window came to, and only review:disagree is a reason.

### `kind`

### `parameter`

Spec parameter: Beteiligte Institution.

The prompt's own wording:

> Um WELCHES Feld handelt es sich bei diesem Wert? Entscheide danach, was die Quelle über ihn sagt: die Beschriftung, die Einheit und die Überschrift des Abschnitts. Zitiere die Stelle, aus der das hervorgeht.

### `parameter_quote`

The verbatim passage carrying 'parameter'. Present exactly when parameter_state is 'read'.

### `parameter_raw`

The document's own wording 'parameter' was read from. This is what a later re-mapping onto a changed vocabulary works on, so a choice without it is counted (raw_missing).

### `parameter_raw_foreign`

The wording does not name the option chosen for 'parameter' -- the model mapped a word the spec does not list onto this class. Kept and counted, not refused: some of those mappings are right.

### `parameter_seen`

A wording the model noticed for 'parameter' while answering 'not stated'. Vocabulary review material, never evidence.

### `parameter_source`

Which source the passage for 'parameter' was found in. How far that may be from the row is the axis' own rule (own | local | any).

### `parameter_state`

How the coordinate 'parameter' ended. Always present: a missing key and a refused reading must not look alike.

### `parameter_window`

[stage, index] of the window 'parameter' was read in. A coordinate read in window 1 and one read in window 22 cost different amounts. `frame` is the one that is not a window: the coordinate was read ONCE for the document and applied to this row, and the index is which of the document's pairs it came from.

### `provenance`

### `quote`

The passage of the owner source that contains the value. Whitespace-collapsed containment; a retyped table row may be repaired, which sets the flag quote_repaired.

### `tier`

text_located: the quote sits in the document's own refined text, so it can be checked against the PDF. visual_source: it sits in a table transcription, a caption or a figure description, which are model output and want human curation.

### `unit`

Empty: a wording has no unit. The key is present so every row has the same shape.

### `unit_raw`

Empty, as unit.

### `value`

The wording as the document writes it.

### `value_raw`

The wording before any tidying (an organisation's legal form, a title's line break).

### `value_uri`

The entry of the parameter's own vocabulary the wording resolved to; null when the list did not hold it. Only a category parameter has a vocabulary, so this one never writes the key at all.

## `study_project_name`

How the row becomes a node:

- `class`: `OEO_00020227`
- `node`: `scenariobundle`
- `property`: `{'label': 'label', 'predicate': 'label', 'prefix': 'rdfs'}`

<details><summary>Why</summary>

Mints the bundle and labels it. Falls back to the publication title where the document names no project.

</details>

### `compute`

The sandbox runs behind a computed value: {code, stdout, ok, error}.

### `computed`

The value came out of the sandbox, not off the page; the quote proves the inputs it was computed from.

### `flags`

Non-fatal verifier findings. mapped:<axis>:<wording>-><uri> is the model mapping a word the spec does not list; period:* says whether a bare amount was shown to be a yearly one; review:* is what a second reading of this value under a narrower window came to, and only review:disagree is a reason.

### `kind`

### `parameter`

Spec parameter: Projektname.

The prompt's own wording:

> Um WELCHES Feld handelt es sich bei diesem Wert? Entscheide danach, was die Quelle über ihn sagt: die Beschriftung, die Einheit und die Überschrift des Abschnitts. Zitiere die Stelle, aus der das hervorgeht.

### `parameter_quote`

The verbatim passage carrying 'parameter'. Present exactly when parameter_state is 'read'.

### `parameter_raw`

The document's own wording 'parameter' was read from. This is what a later re-mapping onto a changed vocabulary works on, so a choice without it is counted (raw_missing).

### `parameter_raw_foreign`

The wording does not name the option chosen for 'parameter' -- the model mapped a word the spec does not list onto this class. Kept and counted, not refused: some of those mappings are right.

### `parameter_seen`

A wording the model noticed for 'parameter' while answering 'not stated'. Vocabulary review material, never evidence.

### `parameter_source`

Which source the passage for 'parameter' was found in. How far that may be from the row is the axis' own rule (own | local | any).

### `parameter_state`

How the coordinate 'parameter' ended. Always present: a missing key and a refused reading must not look alike.

### `parameter_window`

[stage, index] of the window 'parameter' was read in. A coordinate read in window 1 and one read in window 22 cost different amounts. `frame` is the one that is not a window: the coordinate was read ONCE for the document and applied to this row, and the index is which of the document's pairs it came from.

### `provenance`

### `quote`

The passage of the owner source that contains the value. Whitespace-collapsed containment; a retyped table row may be repaired, which sets the flag quote_repaired.

### `tier`

text_located: the quote sits in the document's own refined text, so it can be checked against the PDF. visual_source: it sits in a table transcription, a caption or a figure description, which are model output and want human curation.

### `unit`

Empty: a wording has no unit. The key is present so every row has the same shape.

### `unit_raw`

Empty, as unit.

### `value`

The wording as the document writes it.

### `value_raw`

The wording before any tidying (an organisation's legal form, a title's line break).

### `value_uri`

The entry of the parameter's own vocabulary the wording resolved to; null when the list did not hold it. Only a category parameter has a vocabulary, so this one never writes the key at all.

## The stamp

One `<document>.stamp.json` beside each harvest file, closed like the records (`additionalProperties: false`).

A key that differs from the current run makes the document stale and it is harvested again -- every key but `spec`, which is recorded so a reader can say which file a harvest came from and is not compared. Withheld when the harvest did not happen. The parameter/, value/, axis/ and slot/ keys say WHICH question changed, so a moving ontology costs the coordinates it touched rather than a full re-read of the corpus; a stamp written before they existed carries none of them, and for it `spec` decides again, so it is stale in all of them.

| key | what it records |
|---|---|
| `anchors` | The anchor prompt, the model, the version of the target set and the profile's frozen anchor file, together. NOT the questions: which question was asked is carried by the parameter/, value/, axis/ and slot/ keys, and a question that is GONE by the rule that a key the stamp still carries and the run no longer asks makes the document stale. The anchors decide which passages a document was read from, so a document read under one set is not the same result as one read under another. Empty when anchors were off. |
| `model` | the serving model |
| `page_text_transcribed` | How many pages of this document a model read rather than the PDF. A harvest from a transcribed document is a reading of a reading. |
| `spec` | sha256 of extraction_spec.json. A record, not a verdict: it moves on a comment, an indent or a graph annotation, none of which any question is asked through. Compared, it would outvote every key below it. |
| `^axis/[^/]+/[^/]+$` | What this coordinate asks and what it may answer: the question, the evidence rule, and the offered list with its spellings and its definitions. Everything the model sees for this axis, and nothing else. |
| `^extraction/(harvest\|queries\|anchors\|rows\|field\|phrase\|frame)$` | sha256 of the prompt file |
| `^parameter/[^/]+$` | What this parameter asks, without its axes and without its own list: label, description, value type, accepted units and the example. A new option on ONE axis, or in the list the parameter answers from, must not make every value of the parameter stale -- those have keys of their own. |
| `^question_text/[^/]+$` | The sentence THIS document was searched with. Recorded and never compared: it is written per document, so the document itself is part of it and no two runs produce the same one. What decides whether the harvest is current is its recipe, and that is already here -- the generator prompt, the model, and the annotation inside parameter/. |
| `^review/(prompt\|model)$` | What read this document a second time. Recorded and never compared: the review does not decide whether the harvest is current, and comparing it would report every reviewed document stale the day the review prompt changes. |
| `^slot/parameter$` | The one coordinate that belongs to no parameter: which quantity a number is. Its question and the parameters it offers, uri and label. Also the only key that moves when a parameter is dropped. |
| `^value/[^/]+$` | The list a category parameter answers from. Its own key, because a moved option can be re-mapped from the wording the harvest kept while a rewritten question cannot. |

## The trace

One event per line; `t` names it and `doc` the document. Read by scripts/trace_report.py.

11 record kinds, told apart by `t`:

- `plan`: `chars`, `doc`, `image`, `kind`, `origin`, `owner`, `rank`
- `anchor`: `doc`, `parameter`, `text`
- `frame`: `attempt`, `completion_tokens`, `doc`, `missed`, `ms`, `pairs`, `prompt_tokens`, `scenarios`, `sources`, `status`, `years`
- `rows`: `attempt`, `completion_tokens`, `doc`, `ms`, `origins`, `prompt`, `prompt_tokens`, `ranks`, `rows`, `sources`, `status`
- `field`: `anchor`, `attempt`, `completion_tokens`, `doc`, `filled`, `filled_by`, `ms`, `open`, `parameter`, `prompt_tokens`, `raw_foreign`, `raw_missing`, `reply`, `shown`, `slot`, `stage`, `unbacked`, `unbacked_by`, `unquoted`, `unstated`, `window`
- `sweep`: `anchor`, `asked`, `combed`, `doc`, `exhausted`, `filled`, `raw_foreign`, `raw_missing`, `retried`, `rows`, `slot`, `unbacked`, `unquoted`, `unstated`, `windows`
- `drop`: `attempt`, `doc`, `field`, `row`, `slot`, `why`, `window`
- `error`: `attempt`, `detail`, `doc`, `finish`, `kind`, `ms`, `slot`, `sources`, `status`, `where`, `why`
- `coord`: `doc`, `kind`, `owner`, `parameter`, `states`, `tier`, `unit`, `value`
- `refusal`: `doc`, `owner`, `parameter`, `reason`
- `invalid`: `detail`, `doc`, `kind`, `where`, `why`

[Back to the index](../README.md)
