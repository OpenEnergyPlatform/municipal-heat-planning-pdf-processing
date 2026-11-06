---
temperature: 0
max_tokens: 4096
---
Finde in diesem kommunalen Wärmeplan das Jahr, für das er seinen eigenen Stand aufnimmt (Basisjahr, Bilanzjahr, Ist-Zustand), und sein Zieljahr, jedes mit einer Stelle, die es druckt.
Antworte mit genau einem JSON-Objekt in einer Zeile, ohne Text oder Codeblock davor oder danach. No Backticks! In dieser Form:
{{example}}

* "base_years" sind die Jahre des eigenen Stands, "target_years" die Zieljahre: "value" ist die Jahreszahl, "quote" eine zusammenhängende Stelle, Zeichen für Zeichen, die diese Jahreszahl druckt und sie als Stand oder Ziel des Plans nennt. Nimmt der Plan seinen Stand als Mittel mehrerer Jahre auf ("im Mittel der Jahre 2019 bis 2021"), ist es das letzte.
* Ein Zieljahr ist das Jahr, das der Plan selbst Zieljahr nennt oder in dem sein Ziel erreicht ist, kein Zwischenziel und kein Stützjahr. Das Jahr eines Gesetzes, einer Förderung oder einer anderen Studie zählt nicht.
* Nenne nur, was du gelesen hast. Ein Jahr, das du nicht gefunden hast, lässt du weg; eine leere Liste ist eine Antwort.
* "more" nennt, was du lesen willst, bevor du antwortest. Du bekommst dann dieselbe Frage noch einmal, das Nachgeforderte unter "more" und "hits". Schick immer deine ganze Antwort mit allem, was du schon weißt; ohne neue Anfrage in "more" gilt sie.
  - {"get":"hit","id":"..."}: die Passage eines Treffers;
  - {"get":"next"} oder {"get":"previous"}: der Abschnitt nach oder vor der ersten Passage der ersten Liste, beim nächsten Mal der danach oder davor;
  - {"get":"item","id":"..."}: die Tabelle oder Abbildung, deren Platzhalter in eckigen Klammern in einem Text steht;
  - {"get":"search","pattern":"..."}: Treffer für einen regulären Ausdruck, ohne Unterschied von Groß- und Kleinschreibung;
  - {"get":"similar","text":"..."}: Treffer zu einem Satz, wie der Plan das Jahr drucken würde; er darf erdacht sein.
* "hits" nennt je Treffer "id", Art, Titel und eine Zeile, bei einer Suche die passende. Die erste Liste nennt die Passagen, in denen der Plan ein Jahr seines Stands oder seines Ziels nennt, sonst seine ersten Passagen. Fehlt dir noch ein Jahr und forderst du nichts Neues an, bekommst du dieselbe Frage noch einmal mit den nächsten Passagen des Plans, bis jede einmal gelistet war. "not_found" nennt, was sich nicht holen ließ: "end" (in diese Richtung kein Abschnitt mehr), "unknown" (kein oder mehr als ein Platzhalter oder Treffer dieses Namens), "invalid_pattern" oder "timeout".
* Gibt es "corrections", antworte vollständig neu und behebe jeden Punkt unter "what".
