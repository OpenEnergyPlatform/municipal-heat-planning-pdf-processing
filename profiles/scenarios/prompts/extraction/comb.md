---
temperature: 0
max_tokens: 6144
---
You look in a scientific publication on climate and energy scenarios for what belongs to values of ONE field but does not stand in the values' own passage: the scenario each value refers to.

You get:
- "passage": where the values come from, with kind, title and section.
- "parameter": the field with its definition.
- "rows": the values, each with "row", value and quote, what is already read about them ("known", in the publication's words) and what is still open ("open").
- "coordinates": the open coordinates, each with its question and its list ("options"); "where": where a publication usually prints them.
- "hits": hit lists, each hit with "id", kind, title and first line. The first list holds the passages of the publication that fit these values best; after it come the hits of your own searches.
- "more", "not_found": the passages you asked for, each with "id", and what could not be found, with its reason ("end": there is no section in that direction any more, "unknown": no or more than one placeholder or hit of that name, "invalid_pattern" or "timeout": the pattern did not work).
- "corrections": only in a second request. What was wrong with your first answer, per value ("row") and coordinate under "what".

You answer with:
1. "rows": for EVERY value from "rows" one entry with its "row" and EVERY coordinate from "coordinates", each with "value" (exactly one key of its list), "value_raw" (the publication's own words, where they are not the key) and "quote": ONE contiguous place from "more" or from the value's quote, copied character for character, that contains the answer and speaks about THIS value. If it stands in no place shown, its entry is "out:unstated", without "quote". A coordinate that is not under "open" for a value is read already: its entry is "out:unstated".
   The scenarios of the list are run identifiers of the AR6 database, such as "EN_INDCi2030_300f". They almost never stand in the text; there the same scenario is called "Current Policies", "the NDC scenario" or "our 1.5-degree pathway". Matching the text's name with the identifier is your task: clues are the level of ambition, the target year, the climate target, the budget and the order in which the publication introduces its scenarios. Pick an identifier only where the text's name, with what the passage says about it, fits exactly one run of the list. A name that fits several runs and none of them exactly names a family, and the answer is "scenario family", whatever the runs share: their beginning ("NPi", "the NDC scenarios"), their climate target ("the 1.5 °C scenarios", where several runs carry that target) or their variant alone ("the reference case", where the list holds it with several targets). A scenario the list does not hold at all is "not in AR6".
2. "more": what you want to read before you answer. A list of requests:
   - {"get": "hit", "id": "<<id of a hit>>"}: the passage of this hit;
   - {"get": "next"} or {"get": "previous"}: the section after or before the passage of the values, next time the one after or before that;
   - {"get": "item", "id": "<<placeholder>>"}: the table or figure whose placeholder stands in square brackets in the text;
   - {"get": "search", "pattern": "<<regular expression>>"}: a hit list of the passages whose text contains the pattern, regardless of case.
   You then get the same question once more, with what you asked for under "more" and "hits". Give your whole answer with everything you already know when you ask for more as well; without a new request in "more" it stands. Do not guess: what you have not read is "out:unstated".

In a second request you answer once more in full and fix the points from "corrections".

Answer with exactly one JSON object, on one line, with no text before or after it. The quotes below are descriptions in << >> and stand in no publication:
{"rows": [{"row": "R1", "scenario": {"value": "<<one key of the list>>", "value_raw": "<<the scenario's name in the text>>", "quote": "<<a sentence from a passage asked for that names the scenario of this value>>"}}], "more": [{"get": "hit", "id": "H2"}]}
