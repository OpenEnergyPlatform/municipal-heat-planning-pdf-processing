---
temperature: 0
max_tokens: 4096
---
Du gehst einen deutschen kommunalen Wärmeplan ("Kommunale Wärmeplanung") Passage für Passage durch und legst fest, welche Passage für welche Kennzahl gelesen wird. Du liest dabei KEINE Werte ab.

Du bekommst:
- "sources": Passagen des Plans in seiner Reihenfolge, je mit "id" (P1, P2, …), Art ("section" Abschnitt, "table" Tabelle, "figure" Abbildung), Abschnittstitel, Seite und "text". Zu einer Abbildung kommt ihr Bild; lies es mit.
- "parameters": die Kennzahlen, die gelesen werden, je Schlüssel mit Bezeichnung und Definition.
- "groups": Angaben, die meist für eine ganze Tabelle, eine ganze Abbildung oder einen ganzen Abschnitt gelten, je Gruppe mit "where" (wo ein Plan sie druckt) und ihren Angaben. Eine Angabe mit Liste beantwortest du mit einem Schlüssel der Liste, "number" ist eine Jahreszahl mit vier Ziffern.
- "corrections", nur bei einer Rückfrage: was an deiner letzten Antwort zu diesen Passagen nicht stimmte, je mit der id der Passage. Antworte dann für alle Passagen neu.

Für JEDE Passage gibst du unter ihrer id an:
1. "parameters": die Schlüssel der Kennzahlen, deren Werte in genau dieser Passage stehen. Es zählt die Art der Zahl, nicht ihr Bezug: eine Energiemenge gehört zum Energieverbrauch, ob sie für die ganze Gemeinde, ein Teilgebiet, ein einzelnes Gebäude oder eine Maßnahme gilt und ob der Plan sie Verbrauch, Bedarf, Potenzial, Erzeugung oder Einsparung nennt; ebenso jede Emission, jede Leistung, jeder Anteil und jede Gebäudezahl. Druckt eine Tabellenzelle mehrere Zahlen, etwa einen Wert und seinen Anteil, zählt jede für ihre eigene Kennzahl. Was die Zahl genau ist, wird danach gelesen. Eine Abbildung zählt, wenn ihr Bild oder ihre Beschreibung solche Werte zeigt. Das Planungsbüro zählt, wo sein Name steht. Steht kein solcher Wert darin, dann genau ["out:none"].
2. "quote": bei einer Kennzahl EINE zusammenhängende Stelle aus dem "text" genau dieser Passage, Zeichen für Zeichen abgeschrieben, ohne Auslassungen und ohne Stücke aus verschiedenen Zeilen, mindestens einige Wörter. Was nur das Bild zeigt, ist kein Zitat.
3. Unter dem Namen jeder Gruppe (etwa "frame") jedes Tupel, das für die Werte dieser Passage gilt und in den gezeigten Passagen steht. Zu jeder Angabe gehört "<angabe>_quote": eine Stelle aus den gezeigten Passagen, Zeichen für Zeichen abgeschrieben, die die Antwort enthält. Bei einer Liste enthält sie den Namen des Eintrags oder eine seiner Schreibweisen, oder das eigene Wort des Plans, das du dann in "<angabe>_raw" schreibst. Bei einer Jahreszahl enthält sie die Zahl. Ein Tupel, dessen Angaben die gezeigten Passagen nicht alle drucken, lässt du weg.

Nenne eine Kennzahl im Zweifel lieber einmal zu viel als einmal zu wenig: eine Passage mit "out:none" wird für keine Kennzahl gelesen.

Antworte mit genau einem JSON-Objekt, in einer Zeile, ohne Text davor oder danach. Die Zitate unten sind Beschreibungen in << >> und stehen in keinem Plan:
{"passages": {"P1": {"parameters": ["out:none"]}, "P2": {"parameters": ["emission"], "quote": "<<Tabellentitel, wörtlich>>", "frame": [{"scenario": "Bestand", "scenario_quote": "<<Stelle mit dem Wort des Plans für seinen Ist-Zustand>>", "scenario_raw": "<<dieses Wort>>", "year": 2022, "year_quote": "<<Stelle mit der Jahreszahl>>"}]}}}
