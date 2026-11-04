---
temperature: 0
max_tokens: 6144
---
Du liest EINE Tabelle oder einen Teil einer Tabelle aus einem deutschen kommunalen Wärmeplan ("Kommunale Wärmeplanung") und nennst jede Zelle, die einen Wert EINER Kennzahl enthält. Du schreibst keine Zahlen ab: Ein Programm liest sie aus den Zellen, die du nennst.

Du bekommst:
- "table": die Tabelle oder ihr Teil, "text" mit Titel und Markdown, und der Abschnitt, in dem sie steht.
- "around": der Text dieses Abschnitts um die Tabelle. Die Tabelle steht darin als Platzhalter in eckigen Klammern.
- "columns": jede Spalte mit Nummer und Kopf, "rows": jede Zeile dieses Teils mit ihrer Nummer in der ganzen Tabelle und ihrer Beschriftung.
- "part", nur wenn die Tabelle in Teilen gelesen wird: welche ihrer Zeilen dieser Teil zeigt ("rows": die erste und die letzte Nummer, "of": wie viele Zeilen die Tabelle hat) und ob es der erste Teil ist ("first"). Ein späterer Teil zeigt über seinen Zeilen die Kopfzeilen, die der erste Teil genannt hat; aus ihnen nennst du keine Werte.
- "parameter": die Kennzahl mit ihrer Definition.

Du antwortest mit, in dieser Reihenfolge:
1. "head_rows", nur im ersten Teil einer Tabelle, die in Teilen gelesen wird: die Nummern der Zeilen unter dem Markdown-Trennstrich, die noch zum Kopf gehören, etwa eine Zeile mit Einheiten oder Jahren.
2. "faulty", nur wenn die Tabelle als Markdown kaputt aussieht (verrutschte Spalten, zusammengelegte Köpfe, Zeilen mit falscher Zahl von Zellen): kurz, was nicht stimmt.
3. "values": jede Zelle der gezeigten Zeilen, die einen Wert der Kennzahl enthält, mit "row" und "column". Druckt die Zelle mehr als eine Zahl, etwa einen Wert mit seinem Anteil in Klammern oder mehrere Angaben untereinander, gibst du dazu "parts" (wie viele Zahlen die Zelle druckt, in ihrer Reihenfolge gezählt, auch eine Nummer wie "(1)") und "part" (welche davon der Wert ist, ab 1). Ist mehr als eine davon ein Wert der Kennzahl, bekommt jede einen eigenen Eintrag. Eine Zeile mit Einheiten, eine Kopfzeile und eine Spalte mit Beschriftungen, Baujahren, Flächen oder Werten einer anderen Kennzahl gehören nicht dazu.

Antworte mit genau einem JSON-Objekt, in einer Zeile, ohne Text davor oder danach:
{"values": [{"row": 1, "column": 2}, {"row": 1, "column": 3}, {"row": 2, "column": 2, "parts": 2, "part": 1}]}
