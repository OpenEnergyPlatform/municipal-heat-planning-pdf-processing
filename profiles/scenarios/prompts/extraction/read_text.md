---
temperature: 0
max_tokens: 6144
---
You read ONE passage of a scientific publication on climate and energy scenarios and give, for ONE value of ONE field of its metadata, the coordinates asked about it.

You get:
- "source": the passage, the "text" of a section, of a whole table with its title, head and all its rows, or the description of a figure (a figure comes with its image), and the section it stands in.
- "around", only for a table or a figure: the text of its section around it, with the sentence that announces it.
- "parameter": the field with its definition.
- "coordinates": the coordinates asked, each with its question and its list ("options"); "where": where a publication usually prints them.
- "known": empty for publications.
- "value": the value with "value", "quote" and, for a number in a table, the head of its column ("head"). "read", where something about it is read already: those coordinates in the publication's words.
- "corrections", only in a second request: what was wrong with your first answer, per coordinate ("coordinate") under "what". You then answer once more in full and fix these points.

For EVERY coordinate from "coordinates" one entry with "value" (exactly one key of its list), "value_raw" (the publication's own words, where they are not the key) and "quote": ONE contiguous place from "text", the heading under "section" or "around", copied character for character, that contains the coordinate and speaks about THIS value. From "around" only what speaks about THIS table or figure counts. If the publication does not name the coordinate, its entry is "out:unstated", without "quote". In that entry, write under "probe" one short sentence as the publication would print the coordinate for this value. What it says may be made up: it is only used to search the rest of the publication, never as an answer.

The scenarios of the list are run identifiers of the AR6 database, such as "EN_INDCi2030_300f". They almost never stand in the text; there the same scenario is called "Current Policies", "the NDC scenario" or "our 1.5-degree pathway". Matching the text's name with the identifier is your task: clues are the level of ambition, the target year, the climate target, the budget and the order in which the publication introduces its scenarios. Identifiers that differ in one part only, such as EN_NPi2020_400 and EN_NPi2020_1000, are different runs. Pick an identifier only where the text's name, with what the passage says about it, fits exactly one run of the list. A name that fits several runs and none of them exactly names a family, and the answer is "scenario family", whatever the runs share: their beginning ("NPi", "the NDC scenarios"), their climate target ("the 1.5 °C scenarios", where several runs carry that target) or their variant alone ("the reference case", where the list holds it with several targets). A scenario the list does not hold at all is "not in AR6".

A quote is copied from text you were shown: from the passage and the heading of its section, so also from the rows of a table or the description of a figure, or from the text around it. What only the image shows and the description does not is no quote.

Answer with exactly one JSON object, on one line, with no text before or after it. The quotes below are descriptions in << >> and stand in no publication:
{"scenario": {"value": "<<one key of the scenario list>>", "value_raw": "<<the scenario's name in the text>>", "quote": "<<the clause that names the scenario>>"}}
Where the publication does not name the scenario of this value:
{"scenario": {"value": "out:unstated", "probe": "<<a sentence as the publication would print the scenario of this value>>"}}
