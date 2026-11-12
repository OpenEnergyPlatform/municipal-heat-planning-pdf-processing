Answer the question under "question" from what this request shows.

Answer with exactly one JSON object on one line, with no text or code block before or after it. No Backticks! In this form:
{{example}}

<!-- with: passage -->
"passage" shows lines of the document, each with its address before it. A line that "|" divides has cells, counted from 1: 19.2 is the second cell of line 19.

<!-- with: passages -->
"passages" are pieces of the document, each under its letter, with its kind, page and title. The address of a line carries the letter of its piece, such as A3 or B12.2.

<!-- with: field -->
"field" is a field of the Spec with what it means ("means").

<!-- with: list -->
"list" holds entries, each under its number, with what each means.

<!-- with: headings -->
"headings" are the document's headings up to the shown lines, the nearest last, under the letter H.

<!-- with: title_page -->
"title_page" are the first lines of the document's first page, under the letter T.

<!-- with: settings -->
"settings" are what this document settles for all its values.

<!-- with: more -->
"more" fetches pieces a shown line points to or that you still need, such as "see figure 12": {"get":"next"} the piece after the one shown, {"get":"previous"} the one before, {"get":"item","id":"p17_img1"} the table or figure a line names as "[p17_img1 ...]", {"get":"search","pattern":"total"} the pieces a pattern stands in, {"get":"similar","text":"..."} the pieces closest to a sentence, written as the document would print it, never as a question. What you fetch is shown to you in the next request.

<!-- with: get_image -->
{"get":"image"} under "more" asks for the picture of the figure shown, {"get":"image","id":"B"} for the picture of the figure under letter B. The request is then asked again with the picture.

<!-- with: image -->
The picture of the figure under "image" is attached. Read in it what its lines do not say.
