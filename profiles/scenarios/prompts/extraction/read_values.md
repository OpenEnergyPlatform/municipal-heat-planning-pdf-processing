---
temperature: 0
max_tokens: 8192
---
Extract the first value in publication order that matches the definition in "parameter" and belongs to this publication, its study or its scenarios. Take one list entry per request.
Before you answer, check what the definition excludes.
Use only text from "source" and its section heading; what only a figure's image shows is no text. Skip references, footnotes, citations, passages that present, review or compare other works, and every value attributed to other works.
Answer with exactly one JSON object on one line, with no text or code block before or after it. No Backticks! If no eligible value remains, return {"value":null}. For a match, answer in this form:
{{example}}

* "quote" copies one contiguous supporting clause or line verbatim that stands only once in what you were shown and contains the value once. For a table entry, copy its row. For a name in a list, copy that name with its attached markers, and with the words beside it where the name alone stands more than once. For a title or abstract, copy the full text.
* Without "value_classes", copy the printed value verbatim into "value"; use four digits for the publication year and the bare DOI.
* With "value_classes", put the exact matching key in "value" and the verbatim wording from "quote" in "value_raw". Use a catch-all only for a genuine unlisted value. Use "" if the value is clear but its class is uncertain.

A publication has at most one title, publication year and DOI. A scenario description states what the scenario assumes or depicts.

<!-- with: image -->
The figure's image comes with this request. "drawn" is true where the image only shows the value, as a label, a bar, an area or a point of a curve, and false where text prints it. Where no text you were shown prints the value, read it off the image: in place of "quote", "reading" says what you read, with the legend entry, the category and the unit of the axis, for instance:
{"value":"<<the value as the image shows it>>","drawn":true,"reading":"<<what you read off the image, with legend entry and category>>"}
Where the figure's description prints the value, quote it like any other.

<!-- with: around -->
"around" is the text of the section around the table or figure; a value may also be taken from it.

<!-- with: table_before -->
"table_before" is the title and head of the table right before it, on its page or the page before: if "source" continues that table, its head heads "source" too.

<!-- with: read -->
"read" lists the values you have already named in this passage: name the first one that is not among them.

<!-- follow-up: next -->
Name the next value in this passage that you have not named yet, in the same form. If no eligible value remains, return {"value":null}.

<!-- follow-up: wrong -->
The value under "wrong" is no value of "parameter"; why stands under "what". Name the next value in this passage that matches the definition and that you have not named yet, in the same form. If no eligible value remains, return {"value":null}.

<!-- follow-up: corrections -->
Your last value was not taken; why, and what to do, stands under "what". Skip it if it lacks qualifying evidence.
