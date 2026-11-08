---
temperature: 0
max_tokens: 6144
---
You look in a scientific publication on climate and energy scenarios for what belongs to ONE value of ONE field but was left open in the reading of the value's own passage: which work the value belongs to, whether a year is part of the time a scenario investigates, or the scenario the value refers to. Each further open coordinate comes as a message of its own.
Before you answer, check what the definition excludes.

You get:
- "passage": where the value comes from, with kind, title and section.
- "parameter": the field with its definition.
- "value": the value with its quote, and "read": what is already read about it, each with its quote.
- "coordinates": the open coordinate, with its question; "where": where a publication usually prints it.

You answer with:
1. The coordinate from "coordinates", if you found it, with "value" and "quote": ONE contiguous place from what you were shown, copied character for character, that contains the answer and speaks about THIS value. For a coordinate with "options" only, "value" is one of its entries, chosen by what it means ("means"), and "value_raw" holds the words of the quote that show it. For the scenario, "value" is the scenario's name as the publication prints it, copied character for character; where the question says so, it is an entry of the coordinate's "options" instead of a name, such as "status quo", with "value_raw" as above. Beside a name, "value_raw" repeats the name. If the publication states the value for several scenarios, give their names as a list under "value" with one quote that contains each of them; names that stand in different places are entries of a list, each with its quote. A list of names has no "value_raw". If you have not found the coordinate after hits ("hits") or passages you fetched ("more"), leave it out. Otherwise its entry is {"value": "out:unstated"}, without "quote", and under "probe" one short sentence as the publication would print the coordinate for this value; what it says may be made up, it is only used to search the rest of the publication.
2. "more", where your answer has it: what you want to read before you answer. A list of requests:
   - {"get": "hit", "id": "<<id of a hit>>"}: the passage of this hit;
   - {"get": "next"} or {"get": "previous"}: the section after or before the passage of the value, next time the one after or before that;
   - {"get": "item", "id": "<<placeholder>>"}: the table or figure whose placeholder stands in square brackets in the text;
   - {"get": "search", "pattern": "<<regular expression>>"}: a hit list of the passages whose text contains the pattern, regardless of case;
   - {"get": "similar", "text": "<<a sentence as the publication would print the coordinate for this value>>"}: a hit list of the passages nearest to that sentence; what it says may be made up.
   Give your whole answer with everything you already know when you ask for more as well; without a new request in "more" it stands. Where a hit list comes, take from it first what you want to read; you may search yourself from the next message on. Where you are shown no hit list, search yourself with "similar". Do not guess: name only what you have read.

Answer with exactly one JSON object on one line, with no text or code block before or after it. No Backticks! In this form:
{{example}}
Where the publication states the value for several scenarios (the quotes below are descriptions in << >> and stand in no publication):
{"scenario": {"value": ["<<the first scenario's name>>", "<<the second scenario's name>>"], "quote": "<<a sentence that names both>>"}}
Where it names them in different places:
{"scenario": [{"value": ["<<the first scenario's name>>", "<<the second scenario's name>>"], "quote": "<<a sentence that names both>>"}, {"value": "<<a third scenario's name>>", "quote": "<<a sentence that names it>>"}]}

<!-- with: before after -->
"before" and "after" are the sections before and after the value's place. They count where they speak about THIS value, and a quote may stand in them.

<!-- with: table_before -->
"table_before" is the title and head of the table right before the value's table. If the value's table continues it, its title and head speak about the value too, and a quote may stand in them.

<!-- with: sections -->
"sections" are the titles of the publication's last sections up to the value's place, its own last. A quote may stand in them.

<!-- with: settings -->
"settings" are what the publication settles for all its values, each with its quote. They hold for this value too where they speak about it, and a quote may stand in them.

<!-- with: names -->
"names" lists the scenario names read in this publication so far, each once. Where the value holds for several of them, give every one of them; each needs a quote you were shown that contains it.

<!-- with: hits -->
"hits" holds a hit list, each hit with "id", kind, title and its first line: the passages of the publication that come nearest to how it would print the open coordinate of this value.

<!-- with: more not_found -->
"more" holds passages of the publication you were shown already, each with "id"; "not_found" is what could not be fetched.

<!-- follow-up: coordinates -->
Asked now is the coordinate under "coordinates" of the same value, in this form:
{{example}}

<!-- follow-up: more hits not_found -->
Here is what is new: under "more" the passages you asked for, each with "id"; under "hits" new hit lists, each hit with "id", kind, title and one line, for a "search" the line that matches. Where you asked for nothing new while the coordinate is still missing, they are the next passages of the ranking or, where there was none, the next passages in the order of the publication. Under "not_found" stands what could not be found, with its reason ("end": there is no section in that direction any more, "unknown": no or more than one placeholder or hit of that name, "invalid_pattern" or "timeout": the pattern did not work). Give your whole answer again, with everything you already know.

<!-- follow-up: plan_years -->
No year was found for this value. Under "plan_years" stand the years the publication takes its own state in ("base_years") and its target years ("target_years"). Where the value's place prints, instead of a year, only the publication's word for its own state or for its target, take the year of the list that word refers to: "value" is the year, "value_raw" the word, character for character, and "quote" the place with the word. Otherwise the year is "out:unstated".

<!-- follow-up: corrections -->
Your last answer has mistakes, per coordinate ("coordinate") under "what". Answer once more in full and fix these points. Corrections that name a "value" are each about the scenario of that name: for that coordinate, give those scenarios alone.
