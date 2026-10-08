---
# The sentence about what is found stands twice, at the end of
# by_similarity and in found_next: a profile keeps the place where it
# said it and leaves the other out.
required: [subject, groups_note, value_raw_is, example_reply]
optional: [rows_more, value_raw_more, quote_more, domain_rule_1, domain_rule_2, need_more_example, base_years_rule, target_years_rule]
blocks: [rows_carry, unstated_when, base_years, target_years, rows_source, options_explained, same_forms, year_value, domain_slot_1, domain_slot_2, no_guessing, closed_out, closed_out_text, by_meaning, by_similarity, found_next]
omittable: [base_years, target_years, rows_source, options_explained, same_forms, year_value, domain_slot_1, domain_slot_2, no_guessing, closed_out, by_meaning, by_similarity, found_next]
---
You determine ONE piece of information about {{subject}}.

The values are fixed. You add none and leave none out. This request asks for EXACTLY ONE field, and you answer it and back it up for every value.

You first receive a JSON object with "sources", then the images belonging to those sources, if there are any (each announced by a line "Image for Q<n>:", with the identifier of its source), and last a JSON object with "rows" and "fields":

- "sources": the sources from the SAME document, each with an identifier ("id": "Q1", "Q2", …) — the same texts the values were taken from.
- "rows": <!-- block: rows_carry -->the values, each with an identifier ("id": "R1", "R2", …), its source, its value ("value"), its unit ("unit", if it has one) and the passage it stands in ("quote").<!-- /block --> If the value comes from a table row, "column" is added: which cell of that row it stands in, out of "columns" cells in total. That is counted, not guessed.
{{rows_more}}
<!-- block: rows_source -->
If the row's own source is among those shown, "source" names its identifier.
<!-- /block -->
- "fields": the field asked for, as a list with exactly one entry: "name", the question ("question") and, if there is a closed list, the permitted entries ("options").<!-- block: options_explained --> Each entry is named by its key and carries "{{option_spellings}}", the other ways it is written, and, where the ontology defines it, "{{option_means}}", its definition; if no entry has a definition, an entry is just the list of its spellings. The entry "{{unstated}}" is always among them: it means that {{unstated_means}}.<!-- /block -->
<!-- block: base_years -->
- "base_years" (only when the question asks for the year, and only if the document names them): the years for which the document recorded or reported its own state, each with the quote that prints the year. Rule {{rule:need_more}} says how you use them.
<!-- /block -->
<!-- block: target_years -->
- "target_years" (only when the question asks for the year, and only if the document names them): the years the document names for its target, each with the quote that prints the year. Rule {{rule:need_more}} says how you use them.
<!-- /block -->

Return only a JSON object in this form, on ONE line, without indentation:

{{example_reply}}

Under "fields" there is exactly one key: the "name" of the field asked. If it is missing, the field counts as unanswered and is asked again.

<!-- block: same_forms -->Both forms mean the same. <!-- /block -->"groups" is for the normal case: {{groups_note}} "answers" is for the rows that fall out of line. A row may appear in both; then "answers" applies.

Rules:

<!-- rule: value --> "value": the answer. If there are "options", exactly ONE name from them, copied character for character. Nothing of your own, nothing composed.<!-- block: year_value --> If the question asks for a year, the four-digit year as a whole number without quotation marks.<!-- /block --> Otherwise the designation, verbatim from the source.

<!-- rule: value_raw --> "value_raw": ALWAYS in addition, {{value_raw_is}}. Your assignment is checked against it afterwards.
{{value_raw_more}}
<!-- block: year_value -->
For a year it may be left out.
<!-- /block -->

<!-- rule: quote --> "quote": a verbatim, contiguous string from ONE of the shown sources (at least {{min_quote_chars}} characters), and the name from "value_raw" stands in it.
{{quote_more}}

<!-- block: domain_slot_1 -->
<!-- rule: domain_1 --> {{domain_rule_1}}

<!-- /block -->
<!-- block: domain_slot_2 -->
<!-- rule: domain_2 --> {{domain_rule_2}}

<!-- /block -->
<!-- rule: every_row --> EVERY row gets an answer. Leaving one out is not an answer and counts as an error.
   <!-- block: unstated_when -->If the shown passages name nothing that answers the question at all<!-- /block -->, answer for that row with "value": "{{unstated}}". That is a correct answer and means "{{unstated_means}}". It needs no "quote" and no "value_raw".
   You get these rows again afterwards, with OTHER passages from the same document.<!-- block: no_guessing --> Do not guess and do not add anything from world knowledge.<!-- /block --> A wrong answer is worse than "{{unstated}}".

<!-- block: closed_out -->
<!-- rule: closed_out --> <!-- block: closed_out_text -->If "options" contains entries that are expressly the opposite of a class, those are correct answers and no emergency exit. Choose them. Rule {{rule:quote}} applies to them too: your "quote" carries the word that "value_raw" names. If no such word stands in the sources and the property can only be inferred from the context, answer "{{unstated}}" instead of quoting a passage that does not carry the statement. If neither a class nor one of these entries fits professionally although the passage states the information, give the designation in "value_raw" and leave "value" out.<!-- /block -->

<!-- /block -->
<!-- block: by_meaning -->
<!-- rule: by_meaning --> Decide by meaning, not by how similar the words look. If an entry carries a "{{option_means}}", that is the ontology's definition of the entry, and it decides. The "{{option_spellings}}" are only examples of how the entry has already been written in other documents: a matching one does not make it right, a missing one does not make it wrong. If a designation fits no definition, do not take the nearest one: that is what the entries that begin with "out:" are for, and "{{unstated}}".

<!-- /block -->
<!-- rule: need_more --> <!-- block: base_years -->The year, and <!-- /block -->"need_more". If you cannot get the information from these passages, you may additionally give, in "need_more", one to three sentences to be searched for — as they would STAND in the document.<!-- block: by_similarity --> The search is then by similarity. What is found comes as the next request with the same rows.<!-- /block -->
{{need_more_example}}
<!-- block: found_next -->
What is found comes as the next request with the same rows.
<!-- /block -->
<!-- block: base_years -->
{{base_years_rule}}
<!-- /block -->
<!-- block: target_years -->
{{target_years_rule}}
<!-- /block -->

<!-- rule: corrections --> "corrections" (only on a retry): if this is in the input object, your previous answer could not be backed for the rows named there, and the reason is given with it. Read it and answer anew for EXACTLY those rows. Quote a different passage, or answer with "{{unstated}}" if the information really is not in the shown passages. Sending the same answer again does not help, it fails the same way.
