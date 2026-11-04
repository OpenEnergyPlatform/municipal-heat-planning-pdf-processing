---
temperature: 0
max_tokens: 6144
---
You read ONE passage of a scientific publication on climate and energy scenarios and give, for values of ONE field of its metadata that stand in it, the coordinates asked about each value.

You get:
- "source": the passage, the "text" of a section or a table or the description of a figure (a figure comes with its image), and the section it stands in.
- "around", only for a table or a figure: the text of its section around it, with the sentence that announces it.
- "parameter": the field with its definition.
- "values": the values of the field in this passage, each with "row", value and quote.
- "coordinates": the coordinates asked, each with its question and its list ("options"); "where": where a publication usually prints them.
- "known": empty for publications.
- "more", "hits" and "not_found", only after you asked for more (see below).
- "corrections", only in a second request: what was wrong with your first answer, per value ("row") and coordinate under "what". You then answer once more in full and fix these points.

For EVERY value from "values" one entry in "values" with its "row" and EVERY coordinate from "coordinates", each with "value" (exactly one key of its list), "value_raw" (the publication's own words, where they are not the key) and "quote": ONE contiguous place from "text" or "around", copied character for character, that contains the coordinate and speaks about THIS value. From "around" only what speaks about THIS table or figure counts. If neither the passage nor the text around it names the coordinate, its entry is "out:unstated", without "quote".

The scenarios of the list are run identifiers of the AR6 database, such as "EN_INDCi2030_300f". They almost never stand in the text; there the same scenario is called "Current Policies", "the NDC scenario" or "our 1.5-degree pathway". Matching the text's name with the identifier is your task: clues are the level of ambition, the target year, the climate target, the budget and the order in which the publication introduces its scenarios. Identifiers that differ in one part only, such as EN_NPi2020_400 and EN_NPi2020_1000, are different runs. Pick an identifier only where the text's name, with what the passage says about it, fits exactly one run of the list. A name that fits several runs and none of them exactly names a family, and the answer is "scenario family", whatever the runs share: their beginning ("NPi", "the NDC scenarios"), their climate target ("the 1.5 °C scenarios", where several runs carry that target) or their variant alone ("the reference case", where the list holds it with several targets). A scenario the list does not hold at all is "not in AR6".

If a coordinate stands neither in the passage nor in "around", you may ask for more under "more" instead of answering "out:unstated": {"get": "next"} or {"get": "previous"} (the next or the previous section), {"get": "item", "id": "<<placeholder>>"} (the table or figure whose placeholder stands in square brackets in the text), {"get": "search", "pattern": "<<regular expression>>"} (a hit list of the passages whose text contains the pattern, regardless of case, each with "id", title and matching line) or {"get": "hit", "id": "<<id of a hit>>"} (the passage of this hit). You then get the same question once more, with what you asked for under "more" and "hits" and under "not_found" what could not be found, with its reason. Give your whole answer when you ask for more as well; without a new request in "more" it stands. The quote of a coordinate may come from "more".

What only the image of a figure shows is no quote: quotes come from "text".

Answer with exactly one JSON object, on one line, with no text before or after it. The quotes below are descriptions in << >> and stand in no publication:
{"values": [{"row": "R1", "scenario": {"value": "<<one key of the scenario list>>", "value_raw": "<<the scenario's name in the text>>", "quote": "<<the clause that names the scenario>>"}}]}
