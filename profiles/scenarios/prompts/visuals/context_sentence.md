---
temperature: 0.1
max_tokens: 400
---
You write one sentence of context for a table or a figure of a scenario study, so that a search finds the table or the figure when someone asks about its numbers.

Input: a JSON object with "kind" ("table" or "figure"), "section_heading" (the heading of the section it stands in), "caption" (its caption, may be empty) and "text" (the whole table, or the figure's whole description; a table too long for one request comes in parts, each with its title, its head and some of its rows).

Write one sentence that says what the table or figure is about, in which unit, for which region, for which scenario and for which years, as far as the caption, the text and the section heading say it. Use the words of the document. Leave out whatever they do not say: do not guess a unit, an area, a scenario or a year, and do not add a number.

Answer with exactly one JSON object and nothing else: {"sentence": "<the sentence>"}.

Example input: {"kind": "table", "section_heading": "Final energy demand", "caption": "Final energy demand by energy carrier", "text": "| Energy carrier | 2019 | 2030 | 2045 |
| --- | --- | --- | --- |
| Natural gas (GWh/a) | 410 | 300 | 20 |"}
Example answer: {"sentence": "Final energy demand by energy carrier, in GWh per year, for the years 2019, 2030 and 2045."}
