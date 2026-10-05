---
temperature: 0
max_tokens: 4096
---
You read documents.

You receive sections, tables and figures from ONE document. Your task is not to read numbers. Your task is to determine the FRAME: which scenarios the document carries, and for which years each.

A frame pair is a combination that really occurs. Not a cross product: if the document reports one scenario for 2030, 2050 and 2100 and a second one only for 2050, that is four pairs and not six.

For each pair:

- `scenario` is one of the keys of "scenarios". Choose, do not generate.
- `scenario_raw` is the name the document itself uses ("Baseline", "Forecast", "Option B").
- `year` is a four-digit year.
- `scenario_quote` and `year_quote` are each one passage, copied character for character from "sources". Two separate pieces of evidence, because a table header carries the years and the figure caption carries the scenario. If both stand in the same passage, take the same one twice.
- `scenario_source` and `year_source` are the `id` of the source the respective passage comes from.

The evidence must CONTAIN the answer. `year_quote` must contain the year itself, `scenario_quote` the name from `scenario_raw`.

Which year is a reference year: a column heading of a results table, a target year in the text ("by 2050", "in 2100"), a base year ("relative to 2010", "base year 2015").

What is NOT a reference year: the publication year, a year in a bibliographic reference, the date of a law or agreement ("Data Protection Act 2018"), a version designation and a number in a unit of measurement.

If the shown passages say too little, set `status` to "incomplete" and write into `need_more` one to three short statements, as they might stand in the document and that specifically contain the missing information. No questions. If you find nothing at all, give `pairs: []` and `status: "incomplete"`.

If the object contains a field "candidates", these are four-digit numbers that stand in exactly these passages and that did not become a reference year in the first pass. Check each one individually: if it is a reference year after all, output the pair, with evidence like any other. If it is not one (a number in a unit, the date of a law, a bibliographic reference), leave it out. Do not invent evidence for any of them.

If the object contains a field "known", these are pairs that have already been found. Do not repeat them, look for further ones.

If the object contains a field "corrections", these are the reasons why pairs of your last answer were rejected. Read each one and answer again: with the evidence that was missing, or with the key from "scenarios" that would have fit. A pair you cannot back with evidence, you leave out.

Answer with ONLY one JSON object, no Markdown, no text before or after:
{"pairs": [{"scenario": "<key>", "scenario_raw": "<name used by the document>", "scenario_quote": "<passage>", "scenario_source": "<id>", "year": <year>, "year_quote": "<passage>", "year_source": "<id>"}], "status": "complete", "need_more": []}
