---
temperature: 0
max_tokens: 6144
---
You read ONE passage of a scientific publication on climate and energy scenarios and give, for ONE value of ONE field of its metadata, the coordinate asked about it. Each further coordinate of the value comes as a message of its own.
Before you answer, check what the definition excludes.

You get:
- "source": the passage, the "text" of a section, of a whole table with its title, head and all its rows, or the description of a figure (a figure comes with its image), and the section it stands in.
- "parameter": the field with its definition.
- "coordinates": the coordinate asked, with its question; "where": where a publication usually prints it.
- "known": empty for publications.
- "value": the value with "value" and "quote". "read", where something about it is read already: those coordinates in the publication's words.

For the coordinate from "coordinates" one entry with "value", the scenario's name as the publication prints it, copied character for character, and "quote": ONE contiguous place from "text" or the heading under "section", copied character for character, that contains the name and speaks about THIS value. Where the question says so, "value" is an entry of the coordinate's "options", chosen by what it means ("means"), instead of a name, such as "status quo"; "value_raw" then holds the words of the quote that show it. Beside a name, "value_raw" repeats the name. If the publication states this value for several scenarios, give their names as a list under "value" with one quote that contains each of them; names that stand in different places are entries of a list, each with its quote. A list of names has no "value_raw". If the publication does not name the coordinate, its entry is {"value": "out:unstated"}, without "quote". In that entry, write under "probe" one short sentence as the publication would print the coordinate for this value. What it says may be made up: it is only used to search the rest of the publication, never as an answer.

A quote is copied from text you were shown: from the passage and the heading of its section, so also from the rows of a table or the description of a figure. What only the image shows and the description does not is no quote.

Answer with exactly one JSON object on one line, with no text or code block before or after it. No Backticks! In this form:
{{example}}
Where the publication states the value for several scenarios (the quotes in the forms below are descriptions in << >> and stand in no publication):
{"scenario": {"value": ["<<the first scenario's name>>", "<<the second scenario's name>>"], "quote": "<<the clause that names both>>"}}
Where it names them in different places:
{"scenario": [{"value": ["<<the first scenario's name>>", "<<the second scenario's name>>"], "quote": "<<the clause that names both>>"}, {"value": "<<a third scenario's name>>", "quote": "<<the clause that names it>>"}]}
Where the publication does not name the scenario of this value:
{"scenario": {"value": "out:unstated", "probe": "<<a sentence as the publication would print the scenario of this value>>"}}

<!-- with: settings -->
"settings" are what the publication settles for all its values, each with its quote. They hold for this value too where they speak about it, and a quote may stand in them.

<!-- with: around -->
"around" is the text of the section around the table or figure, with the sentence that announces it. A quote may stand in it; of it, only what speaks about THIS table or figure counts.

<!-- with: table_before -->
"table_before" is the title and head of the table right before it, on its page or the page before. If "source" continues that table, its title and head speak about the value too, and a quote may stand in them.

<!-- follow-up: corrections -->
Your last answer has mistakes, per coordinate ("coordinate") under "what". Answer once more in full and fix these points. Corrections that name a "value" are each about the scenario of that name: for that coordinate, give those scenarios alone.
