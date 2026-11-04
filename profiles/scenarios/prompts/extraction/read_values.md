---
temperature: 0
max_tokens: 8192
---
You read ONE passage of a scientific publication on climate and energy scenarios and name every value of ONE field of its metadata that stands in it. What belongs to each value, such as the scenario it refers to, later requests ask.

You get:
- "source": the passage, the "text" of a section or a table or the description of a figure (a figure comes with its image), and the section it stands in.
- "around", only for a table or a figure: the text of its section around it. The table or figure stands in it as a placeholder in square brackets.
- "parameter": the field with its definition; a field with a list carries it as "value_classes", each entry with its meaning and the other spellings the list knows.
- "corrections", only in a second request: the values of your first answer the check refused, each with "row", "value", "quote" and the reason ("what").

For each value one entry in "values":
- "value": the value as the publication prints it, character for character: the whole title, one author's name (a person, or the institution where the publication names no person), the year with its four digits, the DOI without "doi:" and without the URL before it, the abstract word for word and complete. The value is always what the field asks for by its definition and never what a coordinate asks: the description of a scenario is what the publication says the scenario assumes or depicts, not the scenario's name. Complete, spell out and translate nothing: "JRC" stays "JRC", "Keramidas K." stays "Keramidas K.". For a field with "value_classes", "value" is exactly one key of that list, the entry whose meaning the passage states, or "" if you are unsure which entry it is; the publication's own words then go into "value_raw".
- "value_raw": for a field with "value_classes", the words of the publication you took the entry from, character for character as they stand in the quote; for any other field only where the passage writes the value differently from "value".
- "quote": ONE contiguous place from "text", copied character for character, that contains the value: its clause, its line or its table row. For a title, a name or an abstract the quote may be exactly as long as the value; that is right and not a mistake.

Where "value_classes" are scenarios, they are run identifiers of the AR6 database, such as "EN_INDCi2030_300f". They almost never stand in the text; there the same scenario is called "Current Policies", "the NDC scenario" or "our 1.5-degree pathway". Matching the text's name with the identifier is your task: clues are the level of ambition, the target year, the climate target, the budget and the order in which the publication introduces its scenarios. Identifiers that differ in one part only, such as EN_NPi2020_400 and EN_NPi2020_1000, are different runs. Pick an identifier only where the text's name, with what the passage says about it, fits exactly one run of the list. A name that fits several runs and none of them exactly names a family, and the answer is "scenario family", whatever the runs share: their beginning ("NPi", "the NDC scenarios"), their climate target ("the 1.5 °C scenarios", where several runs carry that target) or their variant alone ("the reference case", where the list holds it with several targets). A scenario the list does not hold at all is "not in AR6".

One entry per value. An author list with six names gives six entries, each with its own short quote: the name as it stands there, with the characters attached to it, so "Keywan Riahi1,2*" and not the whole line of names. The same holds for institutes, funders, projects, keywords, sectors and technologies. A publication has exactly one title, one year of publication and at most one DOI: if the passage states more than one, take the one of THIS publication.

A reference list, a footnote and a citation in running text ("as shown by Riahi et al. (2017)") name OTHER works: no value is taken from them. What only the image of a figure shows is no quote: quotes come from "text". Name every value once.

In a second request you answer only for the values in "corrections": one entry each with its "row", the points named fixed.

Answer with exactly one JSON object, on one line, with no text before or after it. The quotes below are descriptions in << >> and stand in no publication:
{"values": [{"value": "<<one entry of value_classes>>", "value_raw": "<<the publication's words for it>>", "quote": "<<the clause that names it>>"}]}
