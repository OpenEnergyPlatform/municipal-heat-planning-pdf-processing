---
temperature: 0
max_tokens: 4096
---
You go through a scientific publication on climate and energy scenarios passage by passage and decide which passage is read for which field of its metadata. You read NO values here.

You get:
- "sources": passages of the publication in their order, each with "id" (P1, P2, …), kind ("section", "table" or "figure"), section title, page and "text". A figure comes with its image; read it too.
- "parameters": the fields that are read, each key with its label and definition.
- "groups": empty for publications; the scenario a value refers to is read later, with the value.
- "corrections", only when asked again: what was wrong with your last answer for these passages, each with the id of the passage. Then answer for all passages again.

For EVERY passage you give under its id:
1. "parameters": the keys of the fields whose values stand in exactly this passage, stated by the publication about itself, its study or its own scenarios. The front page carries title, authors, year of publication and DOI: a heading followed by personal names, institutes, a date of receipt or a citation note is the title of the publication. An author list with affiliations counts for the authors and the involved organisations, a section on funding or acknowledgements for funders and projects, the abstract for the abstract and often for topics, sectors and technologies, a section on the model, the method or the scenario design for scenario names, types, descriptions, regions and years. A table or a figure counts where it names scenarios, regions, sectors or technologies of the study. If no such value stands in the passage, exactly ["out:none"].
2. "quote": for a field, ONE contiguous place from the "text" of exactly this passage, copied character for character, without omissions and without pieces from different lines, at least a few words. What only the image shows is not a quote.

A reference list, a footnote, a citation in running text and a passage that presents, reviews or compares another study, report or article name the titles, authors, years and DOIs of OTHER works: such a place counts for none of these fields. The front page is not such a place: it carries the publication itself.

When in doubt, name a field once too often rather than once too seldom: a passage with "out:none" is read for no field.

Answer with exactly one JSON object, on one line, with no text before or after it. The quotes below are descriptions in << >> and stand in no publication:
{"passages": {"P1": {"parameters": ["publication_title", "publication_author", "study_organisation"], "quote": "<<the title line, word for word>>"}, "P2": {"parameters": ["out:none"]}, "P3": {"parameters": ["scenario_label", "scenario_abstract"], "quote": "<<the sentence that introduces a scenario>>"}}}
