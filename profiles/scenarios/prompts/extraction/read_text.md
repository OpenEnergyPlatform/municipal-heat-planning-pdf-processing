---
temperature: 0
max_tokens: 6144
---
For the value under `value`, give every coordinate in `coordinates` as the publication states it for THIS value.
Use only text from `source`, its section heading or `around`. What only a figure's image shows is no text. If `corrections` is present, answer in full again and fix each point under `what`.
Return exactly one line of JSON with one entry per coordinate:
`{"scenario":{"value":"...","quote":"..."}}`

* `value` is the scenario's name as the publication prints it, copied verbatim.
* `quote` copies one contiguous clause or line verbatim that contains the name and speaks about this value.
* If the publication does not state the coordinate, its entry is `{"value":"out:unstated","probe":"..."}` without `quote`. `probe` is one short sentence as the publication would print the coordinate for this value. It may be made up: it is only used to search the rest of the publication, never as an answer.

Answer with exactly one JSON object, with no text or code block before or after it.
