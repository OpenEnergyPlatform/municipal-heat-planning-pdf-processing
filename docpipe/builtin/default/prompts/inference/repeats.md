You are given the task ("task") and a numbered list of statements ("statements"), all already checked against their sources. They come from different places in a document, so the same thing can appear in them more than once.

Name every statement that only repeats what an earlier statement of the list already says.

Rules:
- A repeat says the same about the same thing: same value, same year, same reference. Different words change nothing about that.
- If a value, a year, a unit or the reference differs, it is not a repeat, even if the statements sound alike.
- If the later statement says more than the earlier one, it is not a repeat.
- When in doubt, it is not a repeat.

Respond with ONLY a JSON object: {"repeats": [{"statement": <number of the later statement>, "of": <number of the earlier statement>}]}
If there is no repeat, the list is empty.
