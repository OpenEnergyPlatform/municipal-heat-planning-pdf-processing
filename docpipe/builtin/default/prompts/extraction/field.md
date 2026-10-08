---
template: field
without: [no_guessing, closed_out, found_next]
temperature: 0
max_tokens: 5120
---
<!-- part: subject -->
values that have already been extracted from a document

<!-- part: rows_more -->
If the header row names something different for each column, this number decides which one applies.

<!-- part: example_reply -->
{"fields": {"scenario": {"groups": [{"rows": ["R1", "R2"], "value": "FC_2030_400", "value_raw": "the Forecast scenario", "quote": "In the Forecast scenario, spending peaks before 2030 and the remaining budget is 400 million."}], "answers": {"R3": {"value": "several scenarios", "value_raw": "Option B", "quote": "Results for the Option B scenarios are shown in Figure 4."}}}}}

<!-- part: groups_note -->
one paragraph introduces what the field asks about and backs the assignment for all values that come from it.

<!-- part: value_raw_is -->
the name as the document writes it — "Baseline", "the Forecast scenario", "our five-year plan"

<!-- part: value_raw_more -->
"the first scenario" is not a name from the document and not a valid answer.

<!-- part: quote_more -->
For a year, the year stands in it too (except under rule {{rule:need_more}}). Keep it short: the clause that carries the answer, not the whole paragraph. Copy it character for character, including numbers that stand in the middle of the text, such as the line numbers of a manuscript ("Annual Report 311 2020"): they belong to the string. Invented or smoothed passages are discarded, and with them the answer.

<!-- part: domain_rule_1 -->
The names in "options" are often internal codes such as "FC_2030_300f". They almost never stand in the text; there the same thing is called "Baseline", "the Forecast scenario" or "our five-year plan". Matching the description in the text with the code is exactly your task. Clues are the level of ambition, the target year, the target and the order in which the document introduces its items.

<!-- part: domain_rule_2 -->
Many codes share a beginning: "OB_2030_400", "OB_2030_1000" and "OB_2030_3000" are THREE different entries. If the document names only the family ("OB", "Option B", "the Option B scenario"), then NO single code is determined, and you must not pick one. If the list has an entry meant for that case — CHOOSE IT. You set a code only if the text makes it distinguishable, for example through the budget, the target or the year it carries in its name.
   If the document describes something that none of the options covers at all, choose the entry the list has for that case, if it has one.

<!-- part: need_more_example -->
   RIGHT: "The Forecast scenario assumes that the new wing is completed by 2030."
   WRONG: "scenario" — too short, finds everything and nothing.

<!-- part: base_years_rule -->
   If a column, row or heading of a value carries, instead of a year, only the document's word for its own state ("base year", "reporting year", "current state", "status quo", "actual", "existing", "current"), its year is usually stated ONCE elsewhere in the document. If "base_years" is in the input object, choose from it the year that this word refers to: "value" is the year, "value_raw" the word of the document, character for character, and "quote" the place where the word stands for your value. Your quote backs the word, the quote from "base_years" backs the year.
   RIGHT, with "base_years": [{"year": 2022, "quote": "The annual figures were prepared for the base year 2022."}]: "value": 2022, "value_raw": "base year", "quote": "Administration accounted for 4 % of all employees in the base year."
   If "base_years" is missing or none of its years fits, and the year is not in the passages either, answer "{{unstated}}" and search for it with "need_more" ("The annual figures were prepared for the base year."). Do not guess the year from the year the document was published.

<!-- part: target_years_rule -->
   The same holds for the document's word for its target ("target year", "target state", "goal"): if "target_years" is in the input object, choose from it the year that this word refers to. "value" is the year, "value_raw" the word of the document, character for character, and "quote" the place where the word stands for your value. If "target_years" names several years, the target year is the one the document itself calls so or by which its target is reached, not an interim target. If that cannot be decided, answer "{{unstated}}".
   RIGHT, with "target_years": [{"year": 2045, "quote": "The plan is to be carried out in full by the target year 2045."}]: "value": 2045, "value_raw": "target year", "quote": "Administration is to account for 2 % of all employees in the target year."
   If "target_years" is missing or none of its years fits, and the year is not in the passages either, answer "{{unstated}}" and search for it with "need_more".
