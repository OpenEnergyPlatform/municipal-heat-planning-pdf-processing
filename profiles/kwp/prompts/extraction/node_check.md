---
template: node_check
without: [corpus_language]
---
<!-- part: role -->
Du liest deutsche kommunale Wärmepläne ("Kommunale Wärmeplanung").

<!-- part: example_reply -->
{"checks": [{"field": "value", "holds": true, "why": "Die Zeile Erdgas druckt 241 unter MWh p.a."}, {"field": "carrier", "holds": false, "why": "Die Zeile nennt Heizöl, nicht Erdgas."}]}
