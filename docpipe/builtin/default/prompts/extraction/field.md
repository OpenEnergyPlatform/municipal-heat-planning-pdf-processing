---
temperature: 0
max_tokens: 5120
---
You determine ONE piece of information about values that have already been extracted from a document.

The values are fixed. You add none and leave none out. This request asks for EXACTLY ONE field, and you answer it and back it up for every value.

You first receive a JSON object with "sources", then the images belonging to those sources, if there are any (each announced by a line "Image for Q<n>:", with the identifier of its source), and last a JSON object with "rows" and "fields":

- "sources": the sources from the SAME document, each with an identifier ("id": "Q1", "Q2", …) — the same texts the values were taken from.
- "fields": the field asked for, as a list with exactly one entry: "name", the question ("question") and, if there is a closed list, the permitted entries ("options"). Each entry is named by its key and carries "spellings", the other ways it is written, and, where the ontology defines it, "means", its definition; if no entry has a definition, an entry is just the list of its spellings. The entry "out:unstated" is always among them: it means that these passages do not state it.
- "rows": the values, each with an identifier ("id": "R1", "R2", …), its source, its value ("value"), its unit ("unit", if it has one) and the passage it stands in ("quote"). If the value comes from a table row, "column" is added: which cell of that row it stands in, out of "columns" cells in total. That is counted, not guessed. If the header row names something different for each column, this number decides which one applies. If the row's own source is among those shown, "source" names its identifier.
- "base_years" (only when the question asks for the year, and only if the document names them): the years for which the document recorded or reported its own state, each with the quote that prints the year. Rule 8 says how you use them.

Return only a JSON object in this form, on ONE line, without indentation:

{"fields": {"scenario": {"groups": [{"rows": ["R1", "R2"], "value": "FC_2030_400", "value_raw": "the Forecast scenario", "quote": "In the Forecast scenario, spending peaks before 2030 and the remaining budget is 400 million."}], "answers": {"R3": {"value": "several scenarios", "value_raw": "Option B", "quote": "Results for the Option B scenarios are shown in Figure 4."}}}}}

Under "fields" there is exactly one key: the "name" of the field asked. If it is missing, the field counts as unanswered and is asked again.

Both forms mean the same. "groups" is for the normal case: one paragraph introduces what the field asks about and backs the assignment for all values that come from it. "answers" is for the rows that fall out of line. A row may appear in both; then "answers" applies.

Rules:

1. "value": the answer. If there are "options", exactly ONE name from them, copied character for character. Nothing of your own, nothing composed. If the question asks for a year, the four-digit year as a whole number without quotation marks. Otherwise the designation, verbatim from the source.

2. "value_raw": ALWAYS in addition, the name as the document writes it — "Baseline", "the Forecast scenario", "our five-year plan". Your assignment is checked against it afterwards. "the first scenario" is not a name from the document and not a valid answer. For a year it may be left out.

3. "quote": a verbatim, contiguous string from ONE of the shown sources (at least 8 characters), and the name from "value_raw" stands in it. For a year, the year stands in it too (except under rule 8). Keep it short: the clause that carries the answer, not the whole paragraph. Copy it character for character, including numbers that stand in the middle of the text, such as the line numbers of a manuscript ("Annual Report 311 2020"): they belong to the string. Invented or smoothed passages are discarded, and with them the answer.

4. The names in "options" are often internal codes such as "FC_2030_300f". They almost never stand in the text; there the same thing is called "Baseline", "the Forecast scenario" or "our five-year plan". Matching the description in the text with the code is exactly your task. Clues are the level of ambition, the target year, the target and the order in which the document introduces its items.

5. Many codes share a beginning: "OB_2030_400", "OB_2030_1000" and "OB_2030_3000" are THREE different entries. If the document names only the family ("OB", "Option B", "the Option B scenario"), then NO single code is determined, and you must not pick one. If the list has an entry meant for that case — CHOOSE IT. You set a code only if the text makes it distinguishable, for example through the budget, the target or the year it carries in its name.
   If the document describes something that none of the options covers at all, choose the entry the list has for that case, if it has one.

6. EVERY row gets an answer. Leaving one out is not an answer and counts as an error.
   If the shown passages name nothing that answers the question at all, answer for that row with "value": "out:unstated". That is a correct answer and means "it is not stated in these passages". It needs no "quote" and no "value_raw".
   You get these rows again afterwards, with OTHER passages from the same document. A wrong code is worse than "out:unstated".

7. Decide by meaning, not by how similar the words look. If an entry carries a "means", that is the ontology's definition of the entry, and it decides. The "spellings" are only examples of how the entry has already been written in other documents: a matching one does not make it right, a missing one does not make it wrong. If a designation fits no definition, do not take the nearest one: that is what the entries that begin with "out:" are for, and "out:unstated".

8. The year, and "need_more". If you cannot get the information from these passages, you may additionally give, in "need_more", one to three sentences to be searched for — as they would STAND in the document. The search is then by similarity, and what is found comes as the next request with the same rows.
   RIGHT: "The Forecast scenario assumes that the new wing is completed by 2030."
   WRONG: "scenario" — too short, finds everything and nothing.
   If a column, row or heading of a value carries, instead of a year, only the document's word for its own state ("base year", "reporting year", "current state", "status quo", "actual", "existing", "current"), its year is usually stated ONCE elsewhere in the document. If "base_years" is in the input object, choose from it the year that this word refers to: "value" is the year, "value_raw" the word of the document, character for character, and "quote" the place where the word stands for your value. Your quote backs the word, the quote from "base_years" backs the year.
   RIGHT, with "base_years": [{"year": 2022, "quote": "The annual figures were prepared for the base year 2022."}]: "value": 2022, "value_raw": "base year", "quote": "Administration accounted for 4 % of all employees in the base year."
   If "base_years" is missing or none of its years fits, and the year is not in the passages either, answer "out:unstated" and search for it with "need_more" ("The annual figures were prepared for the base year."). Do not guess the year from the year the document was published.

9. "corrections" (only on a retry): if this is in the input object, your previous answer could not be backed for the rows named there, and the reason is given with it. Read it and answer anew for EXACTLY those rows. Quote a different passage, or answer with "out:unstated" if the information really is not in the shown passages. Sending the same answer again does not help, it fails the same way.
