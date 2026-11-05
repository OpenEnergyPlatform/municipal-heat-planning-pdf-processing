Answer the user's task exclusively from the numbered excerpts ("excerpt": a list, each with "index", source and text) of an English-language publication behind the IPCC AR6 scenario database. "prior" lists statements already worked out and checked from earlier excerpts (or is null). Information spread over several excerpts becomes separate statements.

Reply with ONE JSON object:
{"statements": [<statement>, ...], "complete": <true if "prior" + these excerpts answer the task COMPLETELY, otherwise false>}

A statement is ONE claim that ONE place in ONE excerpt supports:
{"statement": "<the claim in English, one short sentence>", "basis": "text", "index": <int of the excerpt used from THESE excerpts>, "quote": "<verbatim, complete sentence from EXACTLY this excerpt that supports the claim>"}

