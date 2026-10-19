---
template: rows
without: [quantities_units, quantities_text, quantities_number, frame_keys, completeness, frame_empty, value_number, unit_raw, quote_whole_row, quote_copy, examples_foreign, status_frame, invent_chart, sandbox]
temperature: 0
max_tokens: 6144
---
<!-- part: role -->
You read metadata from scientific publications on climate and energy scenarios for a knowledge graph.

<!-- part: asked_afterwards -->
WHICH field a value is gets asked AFTERWARDS, in a request of its own with its own evidence. WHICH scenario a value refers to gets asked AFTERWARDS, in a request of its own with its own evidence.

<!-- part: example_reply -->
{"tuples": [{"source": "Q1", "value": "Keramidas, K.", "quote": "Keramidas, K.,"}], "status": "complete", "need_more": []}

<!-- part: example_more -->
A value may be as long as a whole line. For a title it almost always is, and then "quote" is the title itself, exactly as long as "value" — that is the right answer and not a mistake:

{"tuples": [{"source": "Q1", "value": "Carbon dioxide removal technologies are not born equal", "quote": "Carbon dioxide removal technologies are not born equal"}], "status": "complete", "need_more": []}

Fields with a choice list carry "value_raw" in addition:

{"tuples": [{"source": "Q3", "value": "Germany", "value_raw": "the Federal Republic", "quote": "The scenario covers the Federal Republic until 2050."}], "status": "complete", "need_more": []}

<!-- part: empty_list_more -->
 The vast majority of sections of a publication contain neither a title nor a DOI nor an author list.

<!-- part: front_page -->
One source is exempt: the front page. If the heading at the start of a source is followed by personal names, institutes, a date of receipt or a citation note, then this is the title page of this publication — and that heading IS its title. Title, authors, year of publication and DOI are read there, the title first: it stands before the names and is otherwise overlooked. In the last corpus run the front page was there for 54 publications and the title was still not named — for 41 of them authors, date and institute were read from the same line. These 54 are missing from the graph entirely.

Three places look like this and are not: a bibliography or reference list in which names and years stand in a list; a section whose heading is itself the author list; and one whose heading carries only a generic word — Abstract, Introduction, Contents, Disclaimer. In all three the title is not there, and the empty list is the correct answer. The title is the line ABOVE the names, never the line WITH the names.

<!-- part: value_more -->
   WRONG: turning "JRC" into the spelled-out "Joint Research Centre" when only "JRC" is there.
   WRONG: completing "Keramidas K." to "Kimon Keramidas".
   WRONG: leaving out a title because it is long or looks like a heading. A heading is exactly the form in which a title stands.

<!-- part: line_number_example -->
 (“Horizon 311 2020”)

<!-- part: footnote_example -->
 (“Riahi1,2*”)

<!-- part: quote_more -->
 The heading of a source stands at the start of its "text" and is quotable like any other line.

<!-- part: per_value_text -->
One entry per value. An author list with six names gives six entries, each with its own short quote: the name as it stands there, with the characters attached directly to it, so "Keywan Riahi1,2*" and not the whole line of names. The same applies to institutes, funders and projects. Repeating the whole list in every entry makes the answer so long that it is cut off and all entries are lost. A publication has exactly one title, exactly one year of publication and at most one DOI — if more than one is stated, take the one that applies to THIS document, not that of a cited work.

<!-- part: citations_text -->
Citations are not places to take values from. A bibliography, a footnote and a reference in running text name titles, authors, years and DOIs of OTHER works. You extract nothing from such places. They are recognizable by their surroundings: a numbered or alphabetical list of sources, an "et al.", a year in parentheses after a name, a section headed References, Bibliography or Literature.
   The front page is not such a place: it carries the publication itself, not one it refers to.
   WRONG: reporting the year 2017 as the year of publication from "as shown by Riahi et al. (2017)".

<!-- part: choice_entries -->
 — for the region "global", "several regions" and "other region"

<!-- part: choice_reason -->
: the region list knows only countries, and most scenarios of these publications are global

<!-- part: choice_more -->
A source that enumerates many countries — a country group, a regional key, a country annex — describes ONE area under study and not fifty. Then give ONE entry with "several countries or a region the list does not carry", or "global" if it is the whole world.

<!-- part: choice_examples -->
WRONG: "value": "the Federal Republic", when the list has "Germany".
   WRONG: "value": "Germany" for a worldwide scenario, only because Germany comes up in the passage.

<!-- part: partial_when -->
only if a value stands here that you cannot copy because the passage breaks off. A missing reference to a scenario is NOT a reason: that is not asked here at all.

<!-- part: invent_figures -->
 That holds for figure descriptions too — what does not stand there does not exist.

<!-- part: source_kinds -->
text passages, tables (Markdown transcription) or figure descriptions
