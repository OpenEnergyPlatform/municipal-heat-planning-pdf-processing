---
temperature: 0
max_tokens: 6144
---
Find, in other passages of the publication, every coordinate under `coordinates` that the value in `rows` lacks in its own passage, and answer from the passages you were shown.
Return exactly one line of JSON:
`{"rows":[{"row":"R1","scenario":{"value":"...","value_raw":"...","quote":"..."}}],"more":[{"get":"hit","id":"H2"}]}`

* `rows` holds one entry with the value's `row` and every coordinate of `coordinates`. `value` is exactly one key of its `options`, `value_raw` the publication's own wording where it is not the key, and `quote` one contiguous place from `more` or from the value's quote, copied verbatim, that contains the answer and speaks about this value.
* A coordinate that no place shown states, or that is not under `open`, is `{"value":"out:unstated"}` without `quote`. Do not guess: what you have not read is "out:unstated".
* `more` lists what you want to read before you answer. You then get the same question again, with it under `more` and `hits`. Always send your whole answer with what you know so far; without a new request in `more`, it stands.
  - `{"get":"hit","id":"..."}`: the passage of a hit;
  - `{"get":"next"}` or `{"get":"previous"}`: the section after or before the value's passage, next time the one after or before that;
  - `{"get":"item","id":"..."}`: the table or figure whose placeholder stands in square brackets in a text;
  - `{"get":"search","pattern":"..."}`: hits for a regular expression, regardless of case;
  - `{"get":"similar","text":"..."}`: hits nearest to a sentence as the publication would print the coordinate for this value; it may be made up.
* `hits` gives each hit with `id`, kind, title and one line, for a `search` the matching line. The first list, where there is one, holds the passages nearest to the sentences under `query`, written when this value was read; where there is none, search with `similar`. `not_found` names what could not be fetched: "end" (no section in that direction any more), "unknown" (no or more than one placeholder or hit of that name), "invalid_pattern" or "timeout".
* If `corrections` is present, answer in full again and fix each point under `what`.

The `options` of `scenario` are run identifiers of the AR6 database, such as "EN_INDCi2030_300f". The text almost never prints them; it calls the same scenario "Current Policies", "the NDC scenario" or "our 1.5-degree pathway". Match by the level of ambition, the target year, the climate target, the budget and the order in which the publication introduces its scenarios. Identifiers that differ in one part only, such as EN_NPi2020_400 and EN_NPi2020_1000, are different runs. Use a run ID only when the name and passage details uniquely identify it. Use "scenario family" when several listed runs fit and "not in AR6" for a clearly unlisted scenario.
