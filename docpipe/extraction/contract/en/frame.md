---
# An optional part that joins a sentence (quote_why, scenario_raw_more,
# candidates_examples) starts with a space: a part is put in as it is written,
# and one that is left out leaves nothing behind.
required: [role, pair_example, raw_word, year_rules]
optional: [quote_why, scenario_raw_more, candidates_examples]
---
{{role}}

You receive sections, tables and figures from ONE document. Your task is not to read numbers. Your task is to determine the FRAME: which scenarios the document carries, and for which years each.

A frame pair is a combination that really occurs. Not a cross product: {{pair_example}}

For each pair:

- `scenario` is one of the keys of the list the request gives for `scenario`. Choose, do not generate.
- `scenario_raw` is {{raw_word}}{{scenario_raw_more}}
- `year` is a four-digit year.
- `scenario_quote` and `year_quote` are each one passage, copied character for character from "sources".{{quote_why}} If both stand in the same passage, take the same one twice.
- `scenario_source` and `year_source` are the `id` of the source the respective passage comes from.

The evidence must CONTAIN the answer. `year_quote` must contain the year itself, `scenario_quote` the name from `scenario_raw`.

{{year_rules}}

If the shown passages say too little, set `status` to "incomplete" and write into `need_more` one to three short statements, as they might stand in the document and that specifically contain the missing information. No questions. If you find nothing at all, give `pairs: []` and `status: "incomplete"`.

If the object contains a field "candidates", these are four-digit numbers that stand in exactly these passages and that did not become a reference year in the first pass. Check each one individually: if it is a reference year after all, output the pair, with evidence like any other. If it is not one{{candidates_examples}}, leave it out. Do not invent evidence for any of them.

If the object contains a field "known", these are pairs that have already been found. Do not repeat them, look for further ones.

If the object contains a field "corrections", these are the reasons why pairs of your last answer were rejected. Read each one and answer again: with the evidence that was missing, or with the key from that list that would have fit. A pair you cannot back with evidence, you leave out.

Answer with ONLY one JSON object, no Markdown, no text before or after:
{"pairs": [{"scenario": "<key>", "scenario_raw": "<name used by the document>", "scenario_quote": "<passage>", "scenario_source": "<id>", "year": <year>, "year_quote": "<passage>", "year_source": "<id>"}], "status": "complete", "need_more": []}
