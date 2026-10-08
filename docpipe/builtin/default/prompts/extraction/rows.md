---
template: rows
temperature: 0
max_tokens: 6144
---
<!-- part: role -->
You read metadata and numbers from documents for a knowledge graph.

<!-- part: asked_afterwards -->
WHICH field a value is gets asked AFTERWARDS, in a request of its own with its own evidence. WHAT a value refers to, for example which case it describes, gets asked AFTERWARDS, in a request of its own with its own evidence. For a number, the same holds for its year, its scenario and the entry of the list of units that its unit is.

<!-- part: example_reply -->
{"tuples": [{"source": "Q1", "value": "Alvarez, M.", "quote": "Alvarez, M.,"}], "status": "complete", "need_more": []}

<!-- part: example_more -->
A number is output as a number, and its unit as the source writes it goes into "unit_raw" (a text or a choice has none, as in the example above):

{"tuples": [{"source": "Q2", "value": 12.4, "unit_raw": "million EUR", "quote": "| Operating budget | 12.4 |"}, {"source": "Q4", "value": 380, "unit_raw": "employees", "quote": "The head office had 380 employees at year end."}], "status": "complete", "need_more": []}

A value may be as long as a whole line. For a title it almost always is, and then "quote" is the title itself, exactly as long as "value" — that is the right answer and not a mistake:

{"tuples": [{"source": "Q1", "value": "Annual Statistical Report on Population and Housing", "quote": "Annual Statistical Report on Population and Housing"}], "status": "complete", "need_more": []}

Fields with a choice list carry "value_raw" in addition:

{"tuples": [{"source": "Q3", "value": "Employees", "value_raw": "staff", "quote": "The survey covers all staff of the company."}], "status": "complete", "need_more": []}

<!-- part: completeness_example -->
With a "frame", if the columns of a table distinguish years or scenarios, only the column of the frame belongs here: 13 rows with the year columns 2022, 2030 and 2045 give in the frame 2030 exactly 13 entries, all from the column 2030. If the columns distinguish something else, for example the department, every column belongs here: 13 rows and 3 department columns give 39 entries. With a "frame", a table of another year gives none.

<!-- part: empty_list_more -->
 The vast majority of sections of a document contain neither a title nor a DOI nor an author list.

<!-- part: front_page -->
One source is exempt: the front page. If the heading at the start of a source is followed by personal names, institutes, a date of receipt or a citation note, then this is the title page of this document — and that heading IS its title. Title, authors, year of publication and DOI are read there, the title first: it stands before the names and is otherwise overlooked. The title of a front page is easily missed, even though authors, date and institute are read from the same line. A document whose title is missed is missing from the graph entirely.

Three places look like this and are not: a bibliography or reference list in which names and years stand in a list; a section whose heading is itself the author list; and one whose heading carries only a generic word — Abstract, Introduction, Contents, Disclaimer. In all three the title is not there, and the empty list is the correct answer. The title is the line ABOVE the names, never the line WITH the names.

<!-- part: number_examples -->
 (from "126,656,132" becomes 126656132, from "1,036,767.8" becomes 1036767.8)

<!-- part: value_more -->
   WRONG: turning "Acme Ltd" into the spelled-out "Acme Limited" when only "Acme Ltd" is there.
   WRONG: completing "Alvarez M." to "Maria Alvarez".
   WRONG: leaving out a title because it is long or looks like a heading. A heading is exactly the form in which a title stands.
   WRONG: adding 126,656,132 and 520,465,057 and outputting the sum.
   WRONG: converting 126,656,132 kWh/a into 126656.132 MWh/a — the conversion is done by the check from the unit, which is determined afterwards.
   WRONG: outputting "2.46 TWh" as 2460 with "unit_raw": "GWh". The number stays 2.46 and "unit_raw" is "TWh".
   WRONG: outputting "12.4 million EUR" as 12400000 with "unit_raw": "EUR". The quantity word belongs to the unit, not to the number: 12.4 with "unit_raw": "million EUR".

<!-- part: unit_examples -->
 ("MWh p.a.", "EUR/m²", "million EUR")

<!-- part: unit_heading -->
 such as "Energy use [MWh/a]"

<!-- part: line_number_example -->
 (“Annual Report 311 2020”)

<!-- part: footnote_example -->
 (“Alvarez1,2*”)

<!-- part: quote_more -->
 The heading of a source stands at the start of its "text" and is quotable like any other line.

<!-- part: quote_lines -->
   WRONG: "Electricity: 126656132 kWh/a" — reformatted, does not stand like that in the source.
   RIGHT: "| Electricity | 126,656,132 | 520,465,057 | 1,036,767,833 |"
   If the same number stands several times in the same row, quote the whole row: which column is meant is clarified in the next step.
   If a sentence names several numbers for several years or scenarios ("1,769,800 inhabitants in 2020, 1,483,300 inhabitants in the trend scenario for 2045"), quote only the part with YOUR number and what dates it: "1,769,800 inhabitants in 2020". The whole sentence names the others as well, and the number then gets a foreign year or scenario.

<!-- part: per_value_text -->
One entry per value. An author list with six names gives six entries, each with its own short quote: the name as it stands there, with the characters attached directly to it, so "Maria Alvarez1,2*" and not the whole line of names. The same applies to institutes, funders and projects. Repeating the whole list in every entry makes the answer so long that it is cut off and all entries are lost. A document has exactly one title, exactly one year of publication and at most one DOI — if more than one is stated, take the one that applies to THIS document, not that of a cited work.

<!-- part: citations_text -->
Citations are not places to take values from. A bibliography, a footnote and a reference in running text name titles, authors, years and DOIs of OTHER works. You extract nothing from such places. They are recognizable by their surroundings: a numbered or alphabetical list of sources, an "et al.", a year in parentheses after a name, a section headed References, Bibliography or Literature.
   The front page is not such a place: it carries the document itself, not one it refers to.
   WRONG: reporting the year 2017 as the year of publication from "as shown by Alvarez et al. (2017)".

<!-- part: choice_entries -->
, that several do, or that the whole is meant

<!-- part: choice_reason -->
: the classes name only some of what a document can describe

<!-- part: choice_more -->
A source that enumerates many of the classes — a group of them, a key, an appendix — describes ONE scope and not as many as are named. Then give ONE entry: the list's entry that stands for several, or, when the whole is meant, the entry that stands for the whole — as far as the list has such an entry.

<!-- part: choice_examples -->
WRONG: "value": "staff", when the list has "Employees".
   WRONG: "value": "North Office" for a statement about all offices, only because the passage mentions the North Office.

<!-- part: partial_when -->
only if a value stands here that you cannot copy because the passage breaks off, or a number whose UNIT you cannot determine because it stands elsewhere in the document. Only for that. A missing statement of what the value refers to is NOT a reason: that is not asked here at all. Neither, with a "frame", is another year: it has its own request.

<!-- part: status_more -->
     RIGHT: "All amounts in this table are stated in million EUR."
     WRONG: "unit" — too short, finds everything and nothing.

<!-- part: sandbox_more -->
   When this is right: "Total expenditure is 604 million EUR, of which 40 % went to personnel" — the personnel expenditure in million EUR does not stand there, but it is uniquely determined.
   When it is wrong: when the number stands printed. Then copy it.
