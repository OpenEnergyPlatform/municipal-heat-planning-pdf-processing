---
temperature: 0
max_tokens: 8192
---
You read ONE passage of a scientific publication on climate and energy scenarios for ONE field of its metadata and name every value of this field that stands in it, with everything that belongs to it.

You get:
- "source": the passage, the "text" of a section or a table or the description of a figure (a figure comes with its image), and the section it stands in.
- "around", only for a table or a figure: the text of its section around it, with the sentence that announces it and the paragraph below it. The table or figure stands in it as a placeholder in square brackets.
- "parameter": the field with its definition; a field with a list carries it as "value_classes", each entry with its meaning and the other spellings the list knows.
- "coordinates": what belongs to each value, each with its question and its list ("options"). Only the scenario fields have one: the scenario the value refers to.
- "known": empty for publications.
- "more", "hits" and "not_found", only after you asked for more (see below): the passages you asked for, each with "id", the hit lists of your searches and what could not be found, with its reason ("end": there is no section in that direction any more, "unknown": no or more than one placeholder or hit of that name, "invalid_pattern" or "timeout": the pattern did not work).
- "corrections": only in a second request. The values of your first answer the check refused something of, each with "row", "value", "quote" and under "what" per field what was wrong ("value" means the value itself).

For each value one entry in "values":
- "value": the value as the publication prints it, character for character: the whole title, one person's name, the year with its four digits, the DOI without "doi:" and without the URL before it, the abstract word for word and complete. Complete, spell out and translate nothing: "JRC" stays "JRC", "Keramidas K." stays "Keramidas K.". For a field with "value_classes", "value" is exactly one key of that list, the entry whose meaning the passage states, or "" if you are unsure which entry it is; the publication's own words then go into "value_raw".
- "value_raw": for a field with "value_classes", the words of the publication you took the entry from, character for character as they stand in the quote; for any other field only where the passage writes the value differently from "value".
- "quote": ONE contiguous place from "text", copied character for character, that contains the value: its clause, its line or its table row. For a title, a name or an abstract the quote may be exactly as long as the value; that is right and not a mistake.
- EVERY coordinate from "coordinates" with "value" (exactly one key of its list), "value_raw" (the publication's own words, where they are not the key) and "quote" (ONE contiguous place from "text" or "around", copied character for character, that contains it). From "around" only what speaks about THIS table or figure counts. If neither the passage nor the text around it names the scenario, its entry is "out:unstated", without "quote".

The scenarios of the list are run identifiers of the AR6 database, such as "EN_INDCi2030_300f". They almost never stand in the text; there the same scenario is called "Current Policies", "the NDC scenario" or "our 1.5-degree pathway". Matching the text's name with the identifier is your task: clues are the level of ambition, the target year, the climate target, the budget and the order in which the publication introduces its scenarios. Identifiers that share a beginning, such as EN_NPi2020_400 and EN_NPi2020_1000, are different runs: where the text names only the family ("NPi", "the NDC scenarios"), the answer is "scenario family", and a scenario the list does not hold at all is "not in AR6".

One entry per value. An author list with six names gives six entries, each with its own short quote: the name as it stands there, with the characters attached to it, so "Keywan Riahi1,2*" and not the whole line of names. The same holds for institutes, funders, projects, keywords, sectors and technologies. A publication has exactly one title, one year of publication and at most one DOI: if the passage states more than one, take the one of THIS publication.

A reference list, a footnote and a citation in running text ("as shown by Riahi et al. (2017)") name OTHER works: no value is taken from them.

If a coordinate stands neither in the passage nor in "around", you may ask for more instead of answering "out:unstated". Write a list of requests into "more":
- {"get": "next"} or {"get": "previous"}: the next or the previous section of the publication;
- {"get": "item", "id": "<<placeholder>>"}: the table or figure whose placeholder stands in square brackets in the text;
- {"get": "search", "pattern": "<<regular expression>>"}: a hit list of the passages whose text contains the pattern, regardless of case, each with "id", title and matching line;
- {"get": "hit", "id": "<<id of a hit>>"}: the passage of this hit.
You then get the same question once more, with what you asked for under "more" and "hits". Give your whole answer with everything you already know when you ask for more as well; without a new request in "more" it stands. The quote of a coordinate may come from "more"; the values themselves you read from the passage only.

In a second request you answer only for the values in "corrections": one entry each with its "row" and every coordinate, the points named fixed.

What only the image of a figure shows is no quote: quotes come from "text". Name every value once.

Answer with exactly one JSON object, on one line, with no text before or after it. The quotes below are descriptions in << >> and stand in no publication:
{"values": [{"value": "<<one entry of value_classes>>", "value_raw": "<<the publication's words for it>>", "quote": "<<the clause that names it>>", "scenario": {"value": "<<one key of the scenario list>>", "value_raw": "<<the scenario's name in the text>>", "quote": "<<the clause that names the scenario>>"}}]}
