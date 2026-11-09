---
temperature: 0
max_tokens: 4096
---
Schreibe die Abbildung im Bild in Zeilen ab, sodass sie sich ohne das Bild lesen lässt: zuerst ihren Titel, dann je eine Zeile für jede Achse mit ihrer Einheit, für jeden Eintrag der Legende und für jede Zahl mit dem, wofür sie steht.

* Schreibe jede gedruckte Zahl und jedes gedruckte Wort Zeichen für Zeichen ab, wie das Bild es zeigt. Rechne nichts um.
* Eine Zahlenzeile nennt, wofür die Zahl steht: Kategorie, Eintrag der Legende, Jahr und Einheit, wie das Bild sie zeigt, etwa „2019 | Erdgas | 245 GWh“.
* Eine Zahl, die das Bild nicht druckt, sondern nur als Balken, Fläche oder Punkt zeichnet, liest du an ihrer Achse ab und schreibst „abgelesen“ dazu, etwa „2030 | Erdgas | etwa 120 GWh (abgelesen)“.
* "figure" bringt Titel und Beschreibung der Abbildung aus dem Plan. Sie helfen, die Zeilen zu benennen; was nur sie sagen und das Bild nicht zeigt, schreibst du nicht ab.

Antworte mit genau einem JSON-Objekt in einer Zeile, ohne Text oder Codeblock davor oder danach. No Backticks! In dieser Form:
{{example}}
