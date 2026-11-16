---
required: [role, example_reply]
optional: [language_note]
blocks: [corpus_language]
omittable: [corpus_language]
---
{{role}}

You receive ONE node that has already been read from a document, and you check it.

Under "node" stands the node: the field it belongs to, its "value" and each dimension that was read, each with its wording ("_raw") and its quote ("_quote").

Under "quotes" stands each quote of the node with "around": the text of the document around it, the quote among it. That text is all you see of the document.

For "value" and for each dimension of the node, decide whether the text around its quote carries what the node says:

- "holds": true when the text says it, also in other words or as a row of a table with its heading,
- "holds": false when the text says something else, or does not say it, or the quote is not in its text,
- "why": one short sentence, for false what the text says instead.

Check what is there. Do not read a value again and do not correct it.

<!-- block: corpus_language -->
{{language_note}}

<!-- /block -->
Answer with exactly one JSON object on one line, with no text or code block before or after it. No Backticks! In this form:
{{example_reply}}
