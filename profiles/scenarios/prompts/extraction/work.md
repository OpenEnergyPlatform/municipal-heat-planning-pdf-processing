---
temperature: 0
max_tokens: 1024
---
Say whose results the lines under "passage" state: under "found" each shown line that names another work than this publication whose results lines of the piece state, with the work's name; under "own" the shown line that shows the other lines state this publication's own results.

* "field" says what counts as a work ("means"): a study, report, model run or publication this publication presents, compares, reviews or cites, such as each row of a table that compares studies, or a section about one study.
* Each line starts with its address, a line of another block with the block's letter before it. A line that "|" divides has cells, counted from 1, wherever it stands: 12.2 is the second cell of line 12.
* "found": "at" is the cell or line that names the work, or the stretch of lines whose results belong to it, such as 4-6; "words" are the work's name as a line of it prints it, character for character. A heading, or a table's title or head, that names one work speaks for every line of the piece: name it once, at its own address. Name each work once per line or stretch.
* "own": "at" is the address of a shown line that shows the results are this publication's own, such as a heading of its own results, words such as "this study", "we" or "our scenarios", or the title page where the piece stands on the first page; "words" are those words, character for character. Where no shown line shows it, "at" is 0.
* Name nothing on a guess: a line no shown line attributes stays unnamed, and where nothing shows whose results the lines are, "found" is empty and "at" of "own" is 0.

Answer with exactly one JSON object on one line, with no text or code block before or after it. No Backticks! Where lines state results of another work, in this form:
{{example}}
Where the lines state this publication's own results, in this form:
{{nothing}}

<!-- with: headings -->
"headings" are the publication's headings up to this piece, its own last, under the letter H.

<!-- with: title_page -->
"title_page" are the first lines of the publication's first page, under the letter T.
