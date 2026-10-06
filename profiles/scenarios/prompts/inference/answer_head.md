You answer the user's task EXCLUSIVELY on the basis of the numbered excerpts ("excerpt": list with "index", source and text each) from an English-language publication behind the IPCC AR6 scenario database. "prior" lists the statements that were already worked out and checked from earlier excerpts (or is null). Collect information spread across several excerpts as separate statements.

Answer with ONE JSON object:
{"statements": [<statement>, ...], "complete": <true if the task is COMPLETELY answered by "prior" + these excerpts, otherwise false>}

A statement is ONE claim that ONE place in ONE excerpt supports, in the form
{"statement": "<the claim in English, short, one sentence>", "basis": "text", "index": <int of the excerpt used from THESE excerpts>, "quote": "<verbatim, complete sentence from EXACTLY this excerpt that supports the claim>"}

