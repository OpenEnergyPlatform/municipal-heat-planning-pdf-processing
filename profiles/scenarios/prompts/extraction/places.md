---
temperature: 0
max_tokens: 4096
---
You read passages of a scientific publication on climate and energy scenarios and draw a map: which passage says something to what. You do NOT read off any values.

You get:
- "sources": the passages, each with an "id" (P1, P2, …) and its "text", in the order of the publication.
- "parameters": facts that may be stated in the publication, each with key and name.
- "axes": questions about a value, each with key and question.

For every passage that contains any of this, give one entry in "hits":
- "passage": its id.
- "parameters": the keys of the facts that are stated in exactly this passage.
- "axes": the keys of the questions this passage answers. A passage also answers a question when it does so for a whole table, figure or section: as a heading, table or figure caption, column or row header, footnote or introductory sentence.
- "quote": a place from exactly this passage, copied character by character, that shows it. At least a few words.

Leave out passages that say nothing to any fact or question. Rather report one passage too many than one too few: what you leave out is not read again for that question.

Answer with exactly one JSON object, on one line, with no text before or after it. The quotes below are descriptions in << >> and stand in no publication:
{"hits": [{"passage": "P2", "parameters": ["scenario_label", "scenario_year"], "axes": ["scenario"], "quote": "<<table caption, verbatim, naming the scenarios and the years it reports>>"}, {"passage": "P5", "parameters": ["study_funder"], "axes": [], "quote": "<<acknowledgement sentence, verbatim, naming the funding body>>"}]}
