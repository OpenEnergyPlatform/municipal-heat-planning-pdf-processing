---
temperature: 0
max_tokens: 8192
---
Extract the first value in publication order that matches the definition in `parameter`, belongs to this publication, its study or its scenarios, and is absent from `read`. Take one list entry per request.
Use only text from `source`, its section heading or `around`; what only a figure's image shows is no text. Skip references, footnotes, citations, passages that present, review or compare other works, and every value attributed to other works. If `corrections` is present, retry the rejected value using `what`. Skip it if it lacks qualifying evidence.
Return exactly one line of JSON. If no eligible value remains, return `{"next":null}`. For a match, use
`{"next":{"value":"...","value_raw":"...","quote":"..."}}`

* `quote` copies one contiguous supporting clause or line verbatim. For a table entry, copy its full row. For a name in a list, copy just that name with its attached markers. For a title or abstract, copy the full text.
* Without `value_classes`, copy the printed value verbatim into `value`. Use four digits for the publication year and the bare DOI. Set `value_raw` to `""` unless the required format changes the printed form, in which case copy the original wording from `quote`.
* With `value_classes`, put the exact matching key in `value` and the verbatim wording from `quote` in `value_raw`. Use a catch-all only for a genuine unlisted value. Use `""` if the value is clear but its class is uncertain.

A publication has at most one title, publication year and DOI. An institution qualifies as an author only if no individual author is credited. A scenario description states what the scenario assumes or depicts.

Answer with exactly one JSON object, with no text or code block before or after it.
