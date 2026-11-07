---
temperature: 0
max_tokens: 4096
---
Finde in diesem kommunalen Wärmeplan die Passagen, die einen Wert der Kennzahl unter "parameter" nennen, und nenne jede mit ihrer "id".
Prüfe vor der Antwort, was die Definition ausschließt.
Antworte mit genau einem JSON-Objekt in einer Zeile, ohne Text oder Codeblock davor oder danach. No Backticks! In dieser Form:
{{example}}

* "walked" sind Passagen, in denen die Kennzahl schon gesucht wurde, ohne dass ein Wert kam: Such woanders, etwa mit den Worten, mit denen ein Plan sie nennt ("im Auftrag", "erstellt von" beim Planungsbüro).
* "places" nennt jede Passage, die einen Wert der Kennzahl nennt, mit der "id", unter der sie dir gezeigt wurde: ein Treffer ("H…") oder eine Passage, die du geholt hast. Eine leere Liste ist eine Antwort.
* "more" nennt, was du lesen willst, bevor du antwortest. Schick immer deine ganze Antwort mit allem, was du schon weißt; ohne neue Anfrage in "more" gilt sie.
  - {"get":"hit","id":"..."}: die Passage eines Treffers;
  - {"get":"item","id":"..."}: die Tabelle oder Abbildung, deren Platzhalter in eckigen Klammern in einem Text steht;
  - {"get":"search","pattern":"..."}: Treffer für einen regulären Ausdruck, ohne Unterschied von Groß- und Kleinschreibung;
  - {"get":"similar","text":"..."}: Treffer zu einem Satz, wie der Plan einen Wert der Kennzahl drucken würde; er darf erdacht sein.

<!-- follow-up: more hits not_found -->
Hier ist, was neu dazukommt: unter "more" die Passagen, die du angefordert hast, je mit "id", unter "hits" neue Trefferlisten, je Treffer "id", Art, Titel und eine Zeile, bei einer Suche die passende. Unter "not_found" steht, was sich nicht holen ließ: "end", "unknown" (kein oder mehr als ein Platzhalter oder Treffer dieses Namens), "invalid_pattern" oder "timeout". Schick wieder deine ganze Antwort, mit allem, was du schon weißt.

<!-- follow-up: corrections -->
Deine letzte Antwort hat Fehler, je Passage unter "what". Antworte noch einmal vollständig und behebe jeden Punkt.
