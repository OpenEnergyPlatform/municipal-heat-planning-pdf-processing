---
temperature: 0
max_tokens: 8192
---
Extract the first value in publication order that matches the definition in "parameter" and belongs to this publication, its study or its scenarios. Take one list entry per request.
Before you answer, check what the definition excludes.
Use only text from "source" and its section heading; what only a figure's image shows is no text. Skip references, footnotes, citations, passages that present, review or compare other works, and every value attributed to other works.
Answer with exactly one JSON object on one line, with no text or code block before or after it. No Backticks! If no eligible value remains, return {"value":null}. For a match, answer in this form:
{{example}}

* "quote" copies one contiguous supporting clause or line verbatim. For a table entry, copy its full row. For a name in a list, copy just that name with its attached markers. For a title or abstract, copy the full text.
* Without "value_classes", copy the printed value verbatim into "value"; use four digits for the publication year and the bare DOI.
* With "value_classes", put the exact matching key in "value" and the verbatim wording from "quote" in "value_raw". Use a catch-all only for a genuine unlisted value. Use "" if the value is clear but its class is uncertain.

A publication has at most one title, publication year and DOI. An institution qualifies as an author only if no individual author is credited. A scenario description states what the scenario assumes or depicts.

<!-- with: around -->
"around" is the text of the section around the table or figure; a value may also be taken from it.

<!-- with: table_before -->
"table_before" is the title and head of the table right before it, on its page or the page before: if "source" continues that table, its head heads "source" too.

<!-- with: read -->
"read" lists the values you have already named in this passage: name the first one that is not among them.

<!-- follow-up: next -->
Name the next value in this passage that you have not named yet, in the same form. If no eligible value remains, return {"value":null}.

<!-- follow-up: corrections -->
Your last value was not taken; why, and what to do, stands under "what". Skip it if it lacks qualifying evidence.
