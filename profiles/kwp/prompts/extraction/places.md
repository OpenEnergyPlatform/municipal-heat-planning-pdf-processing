---
temperature: 0
max_tokens: 4096
---
Du liest Passagen aus einem deutschen kommunalen Wärmeplan ("Kommunale Wärmeplanung") und legst eine Karte an: welche Passage sagt etwas wozu. Du liest dabei KEINE Werte ab.

Du bekommst:
- "sources": die Passagen, je mit "id" (P1, P2, …) und "text", in der Reihenfolge des Plans.
- "parameters": Kennzahlen, deren Zahlen im Plan stehen können, je Schlüssel und Bezeichnung.
- "axes": Fragen zu den Angaben einer Zahl, je Schlüssel und Frage.

Für jede Passage, die etwas davon enthält, gibst du einen Eintrag in "hits":
- "passage": ihre id.
- "parameters": die Schlüssel der Kennzahlen, deren ZAHLEN in genau dieser Passage stehen.
- "axes": die Schlüssel der Fragen, die diese Passage beantwortet. Eine Passage beantwortet eine Frage auch dann, wenn sie es für eine ganze Tabelle oder einen ganzen Abschnitt tut: als Überschrift, Tabellentitel, Caption, Spalten- oder Zeilenkopf, Fußnote oder einleitender Satz.
- "quote": eine Stelle aus genau dieser Passage, Zeichen für Zeichen abgeschrieben, an der man das sieht. Mindestens einige Wörter.

Passagen, die zu keiner Kennzahl und keiner Frage etwas sagen, lässt du weg. Melde lieber eine Passage zu viel als eine zu wenig: was du weglässt, wird für diese Frage nicht mehr gelesen.

Antworte mit genau einem JSON-Objekt, in einer Zeile, ohne Text davor oder danach. Die Zitate unten sind Beschreibungen in << >> und stehen in keinem Plan:
{"hits": [{"passage": "P2", "parameters": ["energy_consumption"], "axes": ["year", "sector", "carrier"], "quote": "<<Tabellentitel, wörtlich, mit Jahr und Gliederung nach Sektoren und Energieträgern>>"}, {"passage": "P5", "parameters": [], "axes": ["scenario"], "quote": "<<Abschnittsüberschrift, wörtlich, die das Zielszenario benennt>>"}]}
