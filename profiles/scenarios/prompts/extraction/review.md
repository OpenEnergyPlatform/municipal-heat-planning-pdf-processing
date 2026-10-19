---
template: review
without: [field_raw]
temperature: 0
max_tokens: 1024
---
<!-- part: role -->
You read scientific publications on climate and energy scenarios.

<!-- part: row_note -->
That is an indication, not a specification. **Read the passage and return what stands THERE. Do not repeat what you are shown.** If the two passages say something different, write the different thing.

<!-- part: field_unit -->
- for a number, also `unit` as the publication writes it,

<!-- part: language_note -->
The text of the publication is English, and so are the field names and the choice lists. Quote in the language of the passage.

<!-- part: example_reply -->
{"value": 1.5, "unit": "GtCO2/yr", "value_quote": "emissions reach 1.5 GtCO2/yr by 2050", "scenario_region": "World", "scenario_region_quote": "Global results are reported for the World region"}
