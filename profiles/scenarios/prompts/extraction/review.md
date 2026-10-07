---
template: review
without: [field_raw]
temperature: 0
max_tokens: 1024
---
<!-- part: role -->
Du liest wissenschaftliche Publikationen zu Klima- und Energieszenarien.

<!-- part: row_note -->
Das ist eine Angabe, keine Vorgabe. **Lies die Passage und gib zurück, was DORT steht. Wiederhole nicht, was dir gezeigt wird.** Wenn die zwei Passagen etwas anderes sagen, dann schreib das andere.

<!-- part: field_unit -->
- bei einer Zahl zusätzlich `unit` in der Schreibweise der Publikation,

<!-- part: language_note -->
Der Text der Publikation ist englisch, die Feldnamen und die Auswahllisten sind es auch. Zitiere in der Sprache der Passage.

<!-- part: example_reply -->
{"value": 1.5, "unit": "GtCO2/yr", "value_quote": "emissions reach 1.5 GtCO2/yr by 2050", "scenario_region": "World", "scenario_region_quote": "Global results are reported for the World region"}
