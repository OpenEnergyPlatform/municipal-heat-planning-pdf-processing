---
temperature: 0
max_tokens: 4096
---
For every passage in "sources", name under its "id" each field of "parameters" that this passage gives a value for, of the publication itself, its study or its own scenarios. Only name the fields: read no values and quote nothing.
Answer with exactly one JSON object on one line, one entry for every passage, with no text or code block before or after it. No Backticks!
{"passages":{"P1":{"parameters":["publication_title","publication_author"]},"P2":{"parameters":["out:none"]}}}

* "parameters" lists the keys of these fields, or exactly ["out:none"] if the passage gives none. When in doubt, name a field once too often: a passage with "out:none" is read for no field.
* The front page carries title, authors, publication year and DOI; a heading followed by personal names, institutes, a date of receipt or a citation note is the title. An author list with affiliations counts for authors and involved organisations, a funding or acknowledgements section for funders and projects, the abstract for the abstract and often for topics, sectors and technologies, a section on the model, the method or the scenario design for scenario names, types, descriptions, regions and years. A table or figure counts where it names the study's scenarios, regions, sectors or technologies.
* A reference list, a footnote, a citation in running text and a passage that presents, reviews or compares another study, report or article name other works: such a place counts for no field. The front page is not such a place.
* If "corrections" is present, answer again for all passages and fix the points named.
