---
temperature: 0
max_tokens: 6144
---
For the value under `value`, give every coordinate in `coordinates` as the publication states it for THIS value.
Use only text from `source`, its section heading or `around`; from `around`, only what speaks about THIS table or figure. What only a figure's image shows is no text. If `corrections` is present, answer in full again and fix each point under `what`.
Return exactly one line of JSON with one entry per coordinate:
`{"scenario":{"value":"...","value_raw":"...","quote":"..."}}`

* `value` is exactly one key of the coordinate's `options`. `value_raw` is the publication's own wording where it is not the key.
* `quote` copies one contiguous clause or line verbatim that contains the coordinate and speaks about this value.
* If the publication does not state the coordinate, its entry is `{"value":"out:unstated","probe":"..."}` without `quote`. `probe` is one short sentence as the publication would print the coordinate for this value. It may be made up: it is only used to search the rest of the publication, never as an answer.

The `options` of `scenario` are run identifiers of the AR6 database, such as "EN_INDCi2030_300f". The text almost never prints them; it calls the same scenario "Current Policies", "the NDC scenario" or "our 1.5-degree pathway". Match by the level of ambition, the target year, the climate target, the budget and the order in which the publication introduces its scenarios. Identifiers that differ in one part only, such as EN_NPi2020_400 and EN_NPi2020_1000, are different runs. Use a run ID only when the name and passage details uniquely identify it. Use "scenario family" when several listed runs fit and "not in AR6" for a clearly unlisted scenario.
