---
template: rows
without: [quantities_choice, no_guessing, normal_case, place_example_more, place_front_page, source_every, quote_one_source, quote_narrow, quote_inner_numbers, per_value, citations, choice, invent_knowledge, quote_whole_row]
temperature: 0
max_tokens: 6144
---
<!-- part: role -->
Du findest Zahlen in deutschen kommunalen Wärmeplänen für einen Knowledge Graph.

<!-- part: asked_afterwards -->
Die meisten Felder sind Zahlen mit einer Einheit; ein Feld OHNE "units_accepted" ist ein Textfeld, und sein Wert ist eine Bezeichnung. Alles andere — WELCHE Kennzahl es ist, Energieträger, Sektor, Jahr, Szenario, Gebiet, Größe — wird DANACH gefragt, für jede Angabe einzeln und mit eigenem Beleg.

<!-- part: example_reply -->
{"tuples": [{"source": "Q2", "value": 126656132, "unit_raw": "kWh/a", "quote": "| Gas H | 126.656.132 | 520.465.057 | 1.036.767.833 |"}, {"source": "Q5", "value": "endura kommunal", "unit_raw": "", "quote": "Bearbeitung durch das Projektkonsortium: endura kommunal GmbH Emmy-Noether-Str. 2 79110 Freiburg"}], "status": "complete", "need_more": []}

<!-- part: completeness_example -->
Unterscheiden die Spalten einer Tabelle Jahre oder Szenarien, gehört nur die Spalte des Frames dazu: 13 Zeilen mit den Jahresspalten 2022, 2030 und 2045 ergeben im Frame 2030 genau 13 Einträge, alle aus der Spalte 2030. Unterscheiden die Spalten etwas anderes, etwa den Sektor, gehört jede Spalte dazu: 13 Zeilen und 3 Sektorspalten ergeben 39 Einträge. Eine Tabelle eines anderen Jahres ergibt keinen.

<!-- part: value_text -->
bei einem Textfeld die Bezeichnung, wie das Dokument sie schreibt, ohne Rechtsform: aus "endura kommunal GmbH" wird "endura kommunal".

<!-- part: number_examples -->
 (aus "126.656.132" wird 126656132, aus "1.036.767,8" wird 1036767.8)

<!-- part: value_more -->
   FALSCH: 126.656.132 und 520.465.057 addieren und die Summe ausgeben.
   FALSCH: 126.656.132 kWh/a in 126656.132 MWh/a umrechnen — die Umrechnung macht die Prüfung anhand der Einheit, die danach bestimmt wird.
   FALSCH: "2,46 TWh" als 2460 mit "unit_raw": "GWh/a" ausgeben. Die Zahl bleibt 2.46 und "unit_raw" ist "TWh".
   FALSCH: "153 Millionen kWh" als 153000000 mit "unit_raw": "kWh" ausgeben. Das Mengenwort gehört zur Einheit, nicht in die Zahl: 153 mit "unit_raw": "Millionen kWh".

<!-- part: unit_examples -->
 ("kWh Hi p.a.", "t CO₂ eq/a", "Millionen kWh")

<!-- part: unit_heading -->
 wie "Endenergieverbrauch [MWh/a]"

<!-- part: quote_more -->
 Bei einem Textfeld wird das MASCHINELL geprüft: steht die Bezeichnung nicht wörtlich in deinem "quote", wird der Eintrag sofort verworfen. Zitiert wird bei einem Textfeld die Bezeichnung samt Rechtsform, also die Zeile, in der sie steht — am besten die komplette Tabellenzeile.

<!-- part: quote_lines -->
   FALSCH: "Erdgas: 126656132 kWh/a" — umformatiert, steht so nicht in der Quelle.
   RICHTIG: "| Erdgas | 126.656.132 | 520.465.057 | 1.036.767.833 |"
   Steht dieselbe Zahl mehrfach in derselben Zeile, zitier die ganze Zeile: welche Spalte gemeint ist, wird im nächsten Schritt geklärt.
   Nennt ein Satz mehrere Zahlen für mehrere Jahre oder Szenarien ("1.769.800 MWh für 2020, 1.483.300 MWh für das Trendszenario 2045"), dann zitier nur den Teil mit DEINER Zahl und dem, was sie datiert: "1.769.800 MWh für 2020". Der ganze Satz nennt auch die anderen, und die Zahl bekommt dann ein fremdes Jahr oder Szenario.

<!-- part: partial_when -->
in einer der Quellen steht eine Zahl, deren EINHEIT du nicht bestimmen kannst, weil sie anderswo im Plan steht. Nur dafür. Fehlende Kennzahl, Träger oder Gebiete sind hier kein Grund, danach wird gar nicht gefragt, und ein anderes Jahr ist keiner, weil es seine eigene Anfrage hat.

<!-- part: status_more -->
     RICHTIG: "Die Endenergiebilanz ist in MWh pro Jahr angegeben."
     FALSCH: "Einheit" — zu kurz, findet alles und nichts.

<!-- part: sandbox_more -->
   Wann das richtig ist: "Der Gesamtverbrauch liegt bei 604 GWh/a, davon 40 % Fernwärme" — der Fernwärmeanteil in GWh/a steht nicht da, ist aber eindeutig bestimmt.
   Wann es falsch ist: wenn die Zahl gedruckt dasteht. Dann schreib sie ab.
