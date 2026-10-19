---
template: field
without: [base_years, target_years, year_value, no_guessing, closed_out, by_meaning, found_next]
temperature: 0
max_tokens: 5120
---
<!-- part: subject -->
values that have already been extracted from a scientific publication

<!-- part: rows_more -->
If the header row names a scenario for each column, this number decides which one applies.

<!-- part: example_reply -->
{"fields": {"scenario": {"groups": [{"rows": ["R1", "R2"], "value": "EN_NPi2020_400", "value_raw": "the NDC scenario", "quote": "In the NDC scenario, emissions peak before 2030 and the remaining budget is 400 GtCO2."}], "answers": {"R3": {"value": "scenario family", "value_raw": "NPi", "quote": "Results for the NPi scenarios are shown in Figure 4."}}}}}

<!-- part: groups_note -->
one paragraph introduces a scenario and backs the assignment for all values that come from it.

<!-- part: value_raw_is -->
the words of the document you took the answer from, character for character as they stand in the quote: a scenario name such as "Current Policies" or "the NDC scenario", a label such as "Scenario name", a phrase such as "supported by"; where the document does not name the field as such, as with the name of a person or an institute, the value itself as it stands in the quote

<!-- part: value_raw_more -->
"the first scenario" is not a name from the document and not a valid answer. Neither is a name from "options", unless it stands exactly so in the quote: a list name copied in its place is discarded with the answer.

<!-- part: quote_more -->
Keep it short: the clause that carries the answer, not the whole paragraph. Copy it character for character, including numbers that stand in the middle of the text, such as the line numbers of a manuscript ("Horizon 311 2020"): they belong to the string. Invented or smoothed passages are discarded, and with them the answer.

<!-- part: domain_rule_1 -->
The identifiers are run identifiers such as "EN_INDCi2030_300f". They almost never stand in the text; there the same scenario is called "Current Policies", "the NDC scenario" or "our 1.5-degree pathway". Matching the description in the text with the identifier is exactly your task. Clues are the level of ambition, the target year, the climate target and the order in which the publication introduces its scenarios.

<!-- part: domain_rule_2 -->
Many identifiers share a beginning: EN_NPi2020_400, EN_NPi2020_1000 and EN_NPi2020_3000 are THREE different runs. If the document names only the family ("NPi", "NDC", "the NPi scenario"), then NO single identifier is determined, and you must not pick one. For that case the list carries the entry "scenario family" — CHOOSE IT. You set an identifier only if the text makes it distinguishable, for example through the budget, the temperature target or the year it carries in its name.
   If the publication describes a scenario that does not occur in its AR6 list at all, that is the entry "not in AR6".

<!-- part: need_more_example -->
   RIGHT: "The NDC scenario assumes that pledges are implemented by 2030."
   WRONG: "scenario" — too short, finds everything and nothing.

<!-- part: rows_carry -->
the values, each with an identifier ("id": "R1", "R2", …), its source and the passage it stands in.

<!-- part: unstated_when -->
If the passages shown name no scenario at all
