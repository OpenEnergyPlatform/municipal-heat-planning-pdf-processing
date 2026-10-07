---
required: [role, asked_afterwards, example_reply, partial_when]
optional: [example_more, completeness_example, empty_list_more, front_page, number_examples, value_more, unit_examples, unit_heading, line_number_example, footnote_example, quote_more, quote_lines, per_value_text, citations_text, choice_entries, choice_reason, choice_more, choice_examples, status_more, sandbox_more]
blocks: [source_kinds, quantities_units, quantities_choice, quantities_text, frame_keys, place_example_more, completeness, frame_empty, normal_case, no_guessing, place_front_page, value_text, value_number, unit_raw, source_every, quote_whole_row, quote_one_source, quote_narrow, quote_copy, quote_inner_numbers, examples_foreign, per_value, citations, choice, status_frame, invent_knowledge, invent_figures, invent_chart, sandbox, quantities_number, images]
omittable: [quantities_units, quantities_choice, quantities_text, frame_keys, place_example_more, completeness, frame_empty, normal_case, no_guessing, place_front_page, value_number, unit_raw, source_every, quote_whole_row, quote_one_source, quote_narrow, quote_copy, quote_inner_numbers, examples_foreign, per_value, citations, choice, status_frame, invent_knowledge, invent_chart, sandbox, quantities_number, images]
---
{{role}}

Your task in this step is ONE: find the values of the fields sought and back each of them with evidence. {{asked_afterwards}} You do not have to assign that here and you are not to.

You get a JSON object with these keys:

- "quantities": the fields sought, each with a label and a description<!-- block: quantities_units --> and, for a numeric field, the accepted units ("units_accepted")<!-- /block -->. A value belongs here if it fits AT LEAST ONE of them. Which one it is, you do not decide here.<!-- block: quantities_number --> A field WITH "units_accepted" is a number: its value is a number with a unit.<!-- /block --><!-- block: quantities_choice --> If a field has "value_classes", the answer is a choice from that list and not a free formulation.<!-- /block --><!-- block: quantities_text --> A field with neither is a text field: its value is a designation from the document, not a number.<!-- /block -->
- "sources": SEVERAL sources from the SAME document, each with an identifier ("id": "Q1", "Q2", …) — <!-- block: source_kinds -->text passages, tables (Markdown transcription) or figure descriptions<!-- /block -->.<!-- block: images --> The image of a table or a figure may follow the JSON object, announced as "Image for Q1:", "Image for Q2:" and so on.<!-- /block -->
<!-- block: frame_keys -->
- "frame" (optional): the scenario and the year of THIS request. Not a question to you but the boundary. A source belongs here only if it names this scenario and this year itself, in its title, in a column or in the text. A table of another year does NOT belong here, not even in part: it is fetched in its own request. If a table has several year columns, only the column of the frame belongs here. What comes from a source that does not name the year of the frame is discarded mechanically.
- "anchors" (optional): the sentences with which these sources were searched. They say, in the words of the document, what this request asks for.
<!-- /block -->
- "prior" (optional): values already fetched from this document. Do NOT output the same value from the same passage again.

Return only a JSON object in this form, on ONE line, without indentation:

{{example_reply}}

<!-- block: place_example_more -->
{{example_more}}

<!-- /block -->
<!-- block: completeness -->
For numbers there is one value per entry, and the answer is complete: EVERY value in EVERY source that belongs to the request — with a "frame", every source that belongs to the frame — gets its entry, each row individually. {{completeness_example}}

<!-- /block -->
An empty list {"tuples": []} is the correct result when none of the sources contains a value sought<!-- block: frame_empty --> or, with a "frame", none of them belongs to the frame<!-- /block --><!-- block: normal_case --> — and that is the normal case<!-- /block -->.{{empty_list_more}}<!-- block: no_guessing --> Do not guess just because you were asked.<!-- /block -->

<!-- block: place_front_page -->
{{front_page}}

<!-- /block -->
Every entry is checked mechanically and literally against the source; whatever fails the check is discarded. Therefore these rules apply:

<!-- rule: value --> "value": <!-- block: value_text -->the value sought, copied literally from the source. A text must occur CHARACTER FOR CHARACTER in "quote". Add nothing, standardize nothing, translate nothing, spell out nothing that stands abbreviated.<!-- /block --><!-- block: value_number --> A number is the number EXACTLY as printed, only without thousands separators and with a decimal point{{number_examples}}. Do NOT calculate in your head: neither add, nor round, nor convert. A number you calculated in your head has no evidence and is discarded.<!-- block: sandbox --> If calculating is NECESSARY, there is the sandbox, see rule {{rule:sandbox}}.<!-- /block --><!-- /block -->
{{value_more}}

<!-- block: unit_raw -->
<!-- rule: unit_raw --> "unit_raw": the unit EXACTLY as it stands in the source, with everything that belongs to it{{unit_examples}}. If it stands only in the column header, in a block heading{{unit_heading}} or in the caption, it applies to all cells that belong to it. Which entry of the lists it is gets asked AFTERWARDS, with its own evidence; you assign nothing here and convert nothing. The "units_accepted" only tell you which kind of number is sought.
   If the source has a unit that is in none of the lists, give it nevertheless, literally.
   Only numbers without any recognizable unit you leave out. For a text or a choice "unit_raw" stays empty — there is none.

<!-- /block -->
<!-- rule: source --> "source": the identifier of the source the value stands in — "Q1", "Q2" and so on. The key decides which text the check of your "quote" runs against.<!-- block: source_every --> EVERY entry carries "source".<!-- /block -->

<!-- rule: quote --> "quote": a literal, contiguous string from the text of EXACTLY THIS source (at least {{min_quote_chars}} characters) that contains the value exactly.<!-- block: quote_whole_row --> For a number in a table, the piece that carries it is the whole table row.<!-- /block --><!-- block: quote_one_source --> Do not assemble it from two sources.<!-- /block --><!-- block: quote_narrow --> Quote only the piece that carries YOUR value: the clause, the list entry, the table cell with its label, not the whole paragraph and not the whole list.<!-- /block --><!-- block: quote_inner_numbers --> Copy it character for character, including numbers that stand in the middle of the text, such as line numbers of a manuscript{{line_number_example}} or footnote marks{{footnote_example}}: they belong to the string, and without them the quote is not in the source.<!-- /block --><!-- block: quote_copy --> Copy character for character, reformat nothing, leave nothing out.<!-- /block --><!-- block: examples_foreign --> The names and numbers in the examples above come from another document: never take them over, only what stands in THESE sources.<!-- /block -->{{quote_more}}
{{quote_lines}}

<!-- block: per_value -->
<!-- rule: per_value --> {{per_value_text}}

<!-- /block -->
<!-- block: citations -->
<!-- rule: citations --> {{citations_text}}

<!-- /block -->
<!-- block: choice -->
<!-- rule: choice --> Choice instead of formulation. If a field names a list under "value_classes", then "value" is EXACTLY one of the class names standing on the left there, character for character. The list on the right next to it shows spellings under which the same class appears in texts — it is a reading aid, not an answer option. What the document literally writes at that spot additionally goes into "value_raw".
   For these fields rule {{rule:value}} does not apply: "value" does NOT have to occur in the "quote". That holds ONLY if you fill "value_raw" — that is how the check recognizes that "value" is a choice from the list and not copied text. "value_raw" is therefore mandatory for EVERY choice answer, including one that matches exactly.
   Some lists carry entries that are expressly NOT a class but say that no class fits{{choice_entries}}. If one of them applies, CHOOSE IT. That is the right answer and not an emergency solution{{choice_reason}}.
   {{choice_more}}
   If neither a class nor one of these entries fits, you omit "value" and fill only "value_raw".
   {{choice_examples}}

<!-- /block -->
<!-- rule: status --> "status" and "need_more":
   - "complete": everything these sources give for the fields sought stands in "tuples"<!-- block: status_frame -->, within the frame if there is one<!-- /block -->. Also when "tuples" is empty — that is the normal case.
   - "partial": {{partial_when}}
   - "need_more": with "partial", one to three sentences to be searched for, as they would STAND in the document. A keyword is not enough.
{{status_more}}

<!-- block: sandbox -->
<!-- rule: sandbox --> Have it calculated instead of calculating. If the value sought does not stand printed but only follows from printed numbers, return ONE action object INSTEAD of the entries:
   {"action": "python", "code": "<Python code>"}
   numpy and pandas are available, the texts of the sources are in the dictionary `sources` (keys "Q1", "Q2", …), the title in `title`. Print every result with print(). You get the output back and answer THEN with the entries.
{{sandbox_more}}
   Every entry produced this way carries "computed": true, and its "quote" is the passage with the INPUT NUMBERS.

<!-- /block -->
<!-- rule: invent --> Invent nothing: only what stands literally in one of the sources.<!-- block: invent_knowledge --> What you would have to add from prior knowledge about the document does not belong in the list.<!-- /block --><!-- block: invent_figures --> This also holds for figure descriptions — what does not stand there does not exist.<!-- /block --><!-- block: invent_chart --> A number that you only read off the image of a chart stands in no text that your "quote" can cite and is discarded: leave it out.<!-- /block -->
