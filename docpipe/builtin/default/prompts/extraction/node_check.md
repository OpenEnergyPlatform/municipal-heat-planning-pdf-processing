---
template: node_check
---
<!-- part: role -->
You read documents.

<!-- part: language_note -->
The text of the document is English, and so are the field names. Write "why" in English.

<!-- part: example_reply -->
{"checks": [{"field": "value", "holds": true, "why": "The row Sales dept. prints 12.4 under EUR m."}, {"field": "department", "holds": false, "why": "The text names the Sales dept., not Marketing."}]}
