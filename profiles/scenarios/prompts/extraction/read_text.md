---
temperature: 0
max_tokens: 6144
---
You read ONE passage of a scientific publication on climate and energy scenarios and give, for ONE value of ONE field of its metadata, the coordinates asked about it.

You get:
- "source": the passage, the "text" of a section, of a whole table with its title, head and all its rows, or the description of a figure (a figure comes with its image), and the section it stands in.
- "around", only for a table or a figure: the text of its section around it, with the sentence that announces it.
- "parameter": the field with its definition.
- "coordinates": the coordinates asked, each with its question; "where": where a publication usually prints them.
- "known": empty for publications.
- "value": the value with "value", "quote" and, for a number in a table, the head of its column ("head"). "read", where something about it is read already: those coordinates in the publication's words.
- "corrections", only in a second request: what was wrong with your first answer, per coordinate ("coordinate") under "what". You then answer once more in full and fix these points. A correction that names a "value" asks for that scenario alone.

For EVERY coordinate from "coordinates" one entry with "value", the scenario's name as the publication prints it, copied character for character, and "quote": ONE contiguous place from "text", the heading under "section" or "around", copied character for character, that contains the name and speaks about THIS value. From "around" only what speaks about THIS table or figure counts. If the publication states this value for several scenarios, give each of them as its own entry of a list, each with its own quote. If the publication does not name the coordinate, its entry is "out:unstated", without "quote". In that entry, write under "probe" one short sentence as the publication would print the coordinate for this value. What it says may be made up: it is only used to search the rest of the publication, never as an answer.

A quote is copied from text you were shown: from the passage and the heading of its section, so also from the rows of a table or the description of a figure, or from the text around it. What only the image shows and the description does not is no quote.

Answer with exactly one JSON object on one line, with no text or code block before or after it. No Backticks! In this form:
{{example}}
Where the publication states the value for several scenarios (the quotes in the two forms below are descriptions in << >> and stand in no publication):
{"scenario": [{"value": "<<the first scenario's name>>", "quote": "<<the clause that names it>>"}, {"value": "<<the second scenario's name>>", "quote": "<<the clause that names it>>"}]}
Where the publication does not name the scenario of this value:
{"scenario": {"value": "out:unstated", "probe": "<<a sentence as the publication would print the scenario of this value>>"}}
