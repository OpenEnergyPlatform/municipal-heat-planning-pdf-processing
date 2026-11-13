You get the task ("task") and a numbered list of statements ("statements"), all already checked against their sources. They come from different places in a document, so the same thing can appear more than once.

Name every statement that only repeats what an earlier statement of the list already says.

- A repeat says the same about the same thing: same value, same year, same unit, same reference. Different words change nothing.
- If a value, a year, a unit or the reference differs, or the later statement says more than the earlier one, it is not a repeat, even if the statements sound alike. In doubt, it is not a repeat.

Reply with ONLY a JSON object: {"repeats": [{"statement": <number of the later statement>, "of": <number of the earlier statement>}]}
If there is no repeat, the list is empty.
