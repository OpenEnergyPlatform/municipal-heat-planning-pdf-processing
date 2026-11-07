---
temperature: 0
max_tokens: 6144
---
Finde in anderen Passagen des Plans jede Angabe unter "coordinates", die dem Wert unter "row" in seiner eigenen Passage fehlt, und antworte aus den Passagen, die dir gezeigt wurden.
Prüfe vor der Antwort, was die Definition ausschließt.
Antworte mit genau einem JSON-Objekt in einer Zeile, ohne Text oder Codeblock davor oder danach. No Backticks! In dieser Form:
{{example}}

* Die Antwort enthält jede Angabe aus "coordinates", die du gefunden hast. "value" ist bei einer Liste ("options") genau einer ihrer Schlüssel, sonst die Angabe selbst, "value_raw" das Wort des Plans, wo es nicht der Schlüssel ist, und "quote" eine zusammenhängende Stelle, Zeichen für Zeichen, die die Angabe enthält und über diesen Wert spricht.
* Eine Angabe, die du nicht gefunden hast, lässt du weg. Rate nicht: Nenne nur, was du gelesen hast.
* Nennt eine Stelle für den Wert mehrere Einträge einer Liste ("Gas-BHKW + Gas-Brennwert"), ist die Antwort der Eintrag, in den alle fallen; fallen sie in verschiedene, ist sie "Summe", und das Wort des Plans steht in "value_raw".
* "more" nennt, was du lesen willst, bevor du antwortest. Schick immer deine ganze Antwort mit allem, was du schon weißt; ohne neue Anfrage in "more" gilt sie.
  - {"get":"hit","id":"..."}: die Passage eines Treffers;
  - {"get":"next"} oder {"get":"previous"}: der Abschnitt nach oder vor der Passage des Werts, beim nächsten Mal der danach oder davor;
  - {"get":"item","id":"..."}: die Tabelle oder Abbildung, deren Platzhalter in eckigen Klammern in einem Text steht;
  - {"get":"search","pattern":"..."}: Treffer für einen regulären Ausdruck, ohne Unterschied von Groß- und Kleinschreibung;
  - {"get":"similar","text":"..."}: Treffer zu einem Satz, wie der Plan die Angabe zu diesem Wert drucken würde; er darf erdacht sein.

<!-- with: base_years target_years -->
* Steht beim Wert statt einer Jahreszahl nur das Wort des Plans für seinen eigenen Stand ("Basisjahr", "Bilanzjahr", "Ist-Zustand", "Status quo", "IST", "Bestand", "aktuell") oder für sein Ziel ("Zieljahr", "Zielzustand", "Zielszenario", "Ziel"), nimm das Jahr aus "base_years" oder "target_years", auf das dieses Wort verweist: "value" ist die Jahreszahl, "value_raw" das Wort, Zeichen für Zeichen, und "quote" die Stelle mit dem Wort. Bei mehreren "target_years" ist es das Jahr, das der Plan selbst Zieljahr nennt oder in dem sein Ziel erreicht ist, kein Zwischenziel.

<!-- with: whole_table -->
* "whole_table" heißt: Die Tabelle des Werts druckt Szenario und Jahr weder im Kopf noch in den Zeilen, und deine Antwort gilt für jeden ihrer Werte. Such, was der Plan für die ganze Tabelle sagt.

<!-- with: hits -->
* "hits" nennt je Treffer "id", Art, Titel und eine Zeile. Die Liste enthält die Passagen, die dem am nächsten kommen, wie der Plan die offenen Angaben zu diesem Wert drucken würde.

<!-- follow-up: more hits not_found -->
Hier ist, was neu dazukommt: unter "more" die Passagen, die du angefordert hast, unter "hits" neue Trefferlisten, je Treffer "id", Art, Titel und eine Zeile, bei einer Suche die passende. Hast du nichts angefordert, solange eine Angabe fehlt, sind es die nächsten Passagen, die den offenen Angaben am nächsten kommen, gab es keine Rangfolge, die nächsten in der Reihenfolge des Plans. Unter "not_found" steht, was sich nicht holen ließ: "end" (in diese Richtung kein Abschnitt mehr), "unknown" (kein oder mehr als ein Platzhalter oder Treffer dieses Namens), "invalid_pattern" oder "timeout". Schick wieder deine ganze Antwort, mit allem, was du schon weißt.

<!-- follow-up: corrections -->
Deine letzte Antwort hat Fehler, je Angabe unter "what". Antworte noch einmal vollständig und behebe jeden Punkt.
