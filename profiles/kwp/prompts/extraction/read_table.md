---
temperature: 0
max_tokens: 6144
---
Du liest EINE Tabelle aus einem deutschen kommunalen Wärmeplan ("Kommunale Wärmeplanung") als Ganzes für EINE Kennzahl. Du schreibst keine Zahlen ab. Du sagst, welche Spalten und Zeilen Werte der Kennzahl enthalten und wo jede Angabe zu diesen Werten steht. Die Zahlen liest danach ein Programm aus den Zellen, jede über ihre Zeile und ihre Spalte.

Du bekommst:
- "table": die Tabelle, "text" mit Titel und Markdown, und der Abschnitt, in dem sie steht.
- "columns": jede Spalte mit Nummer und Kopf, "rows": jede Zeile unter dem Kopf mit Nummer und Beschriftung.
- "parameter": die Kennzahl mit ihrer Definition.
- "coordinates": die Angaben, die zu jedem Wert gehören, je mit Frage und, wo es eine gibt, mit Liste ("options").
- "known": die Paare aus Szenario und Jahr, die der Plan für diese Tabelle nennt.

Du antwortest mit:
1. "value_columns" und "value_rows": die Nummern der Spalten und Zeilen, deren Zellen Werte der Kennzahl sind. Eine Zeile mit Einheiten, eine Kopfzeile und eine Spalte mit Beschriftungen, Baujahren, Flächen oder Werten einer anderen Kennzahl gehören nicht dazu.
2. "coordinates": je Angabe, wo sie steht:
   - unter "rows" für jede Zeile, deren Beschriftung die Angabe nennt (etwa den Energieträger "Erdgas"), ein Eintrag mit "row";
   - unter "columns" für jede Spalte, deren Kopf die Angabe nennt (etwa einen Sektor oder ein Jahr), ein Eintrag mit "column";
   - unter "table" ein Eintrag, wenn die Angabe für die ganze Tabelle gilt (etwa die Einheit im Titel oder in einer Einheitenzeile, das Gebiet im Titel).
   Jeder Eintrag hat "value" (bei einer Liste genau einer ihrer Schlüssel, sonst die Angabe selbst), "value_raw" (das Wort des Plans, wo es nicht der Schlüssel ist) und "quote": EINE zusammenhängende Stelle aus "table", Zeichen für Zeichen abgeschrieben, die die Angabe enthält, etwa die Kopfzeile, die Zeile oder der Titel. Eine Zeile oder Spalte, die die Summe oder das Gesamte nennt ("Summe", "gesamt"), beantwortest du mit dem Eintrag der Liste, der das sagt. Steht eine Angabe nirgends in der Tabelle, lässt du sie weg. Szenario und Jahr nennst du nur, wo die Tabelle sie selbst druckt; sonst gilt das Paar aus "known".
3. "faulty", nur wenn die Tabelle als Markdown kaputt aussieht (verrutschte Spalten, zusammengelegte Köpfe, Zeilen mit falscher Zahl von Zellen): kurz, was nicht stimmt.

Antworte mit genau einem JSON-Objekt, in einer Zeile, ohne Text davor oder danach. Die Zitate unten sind Beschreibungen in << >> und stehen in keinem Plan:
{"value_columns": [2, 3], "value_rows": [1, 2], "coordinates": {"carrier": {"rows": [{"row": 1, "value": "<<Schlüssel der Liste>>", "value_raw": "<<Beschriftung der Zeile>>", "quote": "<<die ganze Zeile 1>>"}]}, "sector": {"columns": [{"column": 2, "value": "<<Schlüssel der Liste>>", "value_raw": "<<Kopf der Spalte>>", "quote": "<<die Kopfzeile>>"}]}, "unit": {"table": {"value": "<<Schlüssel der Liste>>", "quote": "<<Titel oder Einheitenzeile>>"}}}}
