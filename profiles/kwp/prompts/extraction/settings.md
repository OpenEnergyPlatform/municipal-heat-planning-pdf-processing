---
temperature: 0
max_tokens: 4096
---
Finde, was dieser kommunale Wärmeplan für alle seine Werte festlegt, jede Festlegung mit einer Stelle, die sie druckt: etwa das Jahr seiner Bilanz, dass Emissionen in CO2-Äquivalenten angegeben sind, oder die Einheit aller Zahlen einer Tabelle.
Antworte mit genau einem JSON-Objekt in einer Zeile, ohne Text oder Codeblock davor oder danach. No Backticks! In dieser Form:
{{example}}

* Unter "settings" hat jede Festlegung "about", wofür sie gilt, und "value", was sie festlegt, beides im Wortlaut des Plans, und "quote", eine zusammenhängende Stelle, Zeichen für Zeichen, die beides enthält.
* Es zählen nur Festlegungen des Plans selbst, die für mehr als einen Wert gelten: keine einzelne Zahl, keine Vorgabe aus Gesetz, Förderrichtlinie oder einer anderen Studie, außer der Plan macht sie zu seiner eigenen.
* Nenne nur, was du gelesen hast. Eine leere Liste ist eine Antwort.
* "hits" nennt je Passage des Plans "id", Art, Titel und eine Zeile, in der Reihenfolge des Plans.
* "more" nennt, was du lesen willst, bevor du antwortest. Schick immer deine ganze Antwort mit allem, was du schon weißt; ohne neue Anfrage in "more" gilt sie.
  - {"get":"hit","id":"..."}: die Passage eines Treffers;
  - {"get":"next"} oder {"get":"previous"}: der Abschnitt nach oder vor der ersten Passage, beim nächsten Mal der danach oder davor;
  - {"get":"item","id":"..."}: die Tabelle oder Abbildung, deren Platzhalter in eckigen Klammern in einem Text steht;
  - {"get":"search","pattern":"..."}: Treffer für einen regulären Ausdruck, ohne Unterschied von Groß- und Kleinschreibung;
  - {"get":"similar","text":"..."}: Treffer zu einem Satz, wie der Plan eine Festlegung drucken würde; er darf erdacht sein.

<!-- follow-up: more hits not_found -->
Hier ist, was neu dazukommt: unter "more" die Passagen, die du angefordert hast, unter "hits" neue Trefferlisten, je Treffer "id", Art, Titel und eine Zeile, bei einer Suche die passende. Hast du nichts angefordert, sind es die nächsten Passagen des Plans, bis jede gelistet war. Unter "not_found" steht, was sich nicht holen ließ: "end" (in diese Richtung kein Abschnitt mehr), "unknown" (kein oder mehr als ein Platzhalter oder Treffer dieses Namens), "invalid_pattern" oder "timeout". Schick wieder deine ganze Antwort, mit allem, was du schon weißt.

<!-- follow-up: corrections -->
Deine letzte Antwort hat Fehler, je Festlegung unter "what". Antworte noch einmal vollständig und behebe jeden Punkt.
