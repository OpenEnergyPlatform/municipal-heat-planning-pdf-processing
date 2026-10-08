---
required: [role, example_reply]
optional: [language_note]
blocks: [row_note, field_raw, field_unit, corpus_language]
omittable: [field_raw, corpus_language]
---
{{role}}

You receive ONE value that has already been read, and the passages it may come from. You read it a second time.

There are at most two passages, and they are the only ones you may quote from:

- `Q1` is the value's own source: the table, the figure or the section it stands in.
- `Q2` carries `"via": "parent"` and is the section `Q1` stands in. For a value whose own source is already a section, there is no `Q2`.

A quote from anything else is discarded, even if it is correct.

Under `row` stands what the first reading produced: `value`, `unit`, the quote, and if the row has several columns, in which one the value stands (`column` of `columns`). <!-- block: row_note -->That is an indication, not a specification. **Read the passage and return what stands THERE. Do not repeat what you are shown.** If the two passages say something different, write the different thing.<!-- /block -->

Under `fields` stands what is asked. `value` is always included, plus the coordinates that are disputed.

For each field:

- the answer itself under the name of the field,
- a quote under `<name>_quote`: at least {{min_quote_chars}} characters, copied character for character from `Q1` or `Q2`, and the answer must stand IN it,
<!-- block: field_raw -->
- `<name>_raw`, as soon as the source writes the thing differently than the list names it: the wording of the document, character for character. Without it the quote is checked against the name from the list, which the source does not write, and the answer fails,
<!-- /block -->
<!-- block: field_unit -->
- for a number additionally `unit`: exactly ONE entry from `units_accepted` under `row`, the one the source means (a statement "per year" turns MWh into the entry MWh/a), plus `unit_raw` in the spelling of the document. Never convert,
<!-- /block -->
- for a choice list (`options`) exactly one key from that list, character for character. Do not invent one.

<!-- block: corpus_language -->
{{language_note}}

<!-- /block -->
If the two passages do not carry a field, then `{{unstated}}` is the right answer. That is a result and not an error, and it is better than an answer for which you have no quote from these two passages.

Output ONLY one JSON object, on one line, with no text before or after:

```json
{{example_reply}}
```
