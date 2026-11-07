---
temperature: 0
max_tokens: 6144
---
Gib für den Wert unter "value" die Angabe unter "coordinates" an, so wie der Plan sie für DIESEN Wert nennt. In der Lesung seiner eigenen Stelle blieb sie offen; "read" sind die Angaben, die dort schon gelesen sind, je mit Zitat, und "passage" sagt, wo der Wert steht. Jede weitere offene Angabe kommt als eigene Nachricht.
Prüfe vor der Antwort, was die Definition ausschließt.
Antworte mit genau einem JSON-Objekt in einer Zeile, ohne Text oder Codeblock davor oder danach. No Backticks! In dieser Form:
{{example}}

* "value" ist bei einer Liste ("options") genau einer ihrer Schlüssel, nach dem, was er bedeutet ("means"), sonst die Angabe selbst, "value_raw" das Wort des Plans, wo es nicht der Schlüssel ist, und "quote" eine zusammenhängende Stelle aus dem, was dir gezeigt wurde, Zeichen für Zeichen, die die Angabe enthält und über diesen Wert spricht.
* Nennt eine Stelle für den Wert mehrere Einträge einer Liste ("Gas-BHKW + Gas-Brennwert"), ist die Antwort der Eintrag, in den alle fallen; fallen sie in verschiedene, ist sie "Summe", und das Wort des Plans steht in "value_raw".
* Stehen bei der Angabe "base_years" oder "target_years" und steht beim Wert statt einer Jahreszahl nur das Wort des Plans für seinen eigenen Stand ("Basisjahr", "Bilanzjahr", "Ist-Zustand", "Status quo", "IST", "Bestand", "aktuell") oder für sein Ziel ("Zieljahr", "Zielzustand", "Zielszenario", "Ziel"), nimm das Jahr aus der Liste, auf das dieses Wort verweist: "value" ist die Jahreszahl, "value_raw" das Wort, Zeichen für Zeichen, und "quote" die Stelle mit dem Wort. Bei mehreren "target_years" ist es das Jahr, das der Plan selbst Zieljahr nennt oder in dem sein Ziel erreicht ist, kein Zwischenziel.
* Rate nicht: Nenne nur, was du gelesen hast. Hast du die Angabe nach Treffern ("hits") oder geholten Passagen ("more") nicht gefunden, lass sie weg. Sonst ist ihr Eintrag {"value":"out:unstated","probe":"..."} ohne "quote": "probe" ist ein kurzer Satz, wie der Plan diese Angabe zu diesem Wert drucken würde; er darf erdacht sein, mit ihm wird nur im übrigen Plan gesucht.
* Hat die Antwort "more", nennt es, was du lesen willst, bevor du antwortest. Schick immer deine ganze Antwort mit allem, was du schon weißt; ohne neue Anfrage in "more" gilt sie. Kommt eine Trefferliste, hol dir zuerst daraus, was du lesen willst; selbst suchen darfst du ab der nächsten Nachricht.
  - {"get":"hit","id":"..."}: die Passage eines Treffers;
  - {"get":"next"} oder {"get":"previous"}: der Abschnitt nach oder vor der Passage des Werts, beim nächsten Mal der danach oder davor;
  - {"get":"item","id":"..."}: die Tabelle oder Abbildung, deren Platzhalter in eckigen Klammern in einem Text steht;
  - {"get":"search","pattern":"..."}: Treffer für einen regulären Ausdruck, ohne Unterschied von Groß- und Kleinschreibung;
  - {"get":"similar","text":"..."}: Treffer zu einem Satz, wie der Plan die Angabe zu diesem Wert drucken würde; er darf erdacht sein.

<!-- with: before after -->
"before" und "after" sind die Abschnitte vor und nach der Stelle des Werts. Sie zählen, wo sie über diesen Wert sprechen, und du darfst aus ihnen zitieren.

<!-- with: whole_table -->
"source" ist die Tabelle des Werts mit Titel, Kopf und allen Zeilen. "whole_table" heißt: Die Tabelle druckt die Angabe weder im Kopf noch in den Zeilen, und deine Antwort gilt für jeden ihrer Werte. Nenne, was ihr Titel, der Satz, der sie ankündigt, oder ihr Abschnitt für die ganze Tabelle sagt.

<!-- with: title_page -->
"title_page" ist die Zeile des Titelblatts, die die Gemeinde des Plans nennt. Auch daraus darfst du zitieren.

<!-- with: table_before -->
"table_before" sind Titel und Kopf der Tabelle direkt vor der Tabelle des Werts; setzt diese sie fort, sprechen sie auch über den Wert, und du darfst aus ihnen zitieren.

<!-- with: settings -->
"settings" sind Festlegungen, die der Plan für alle seine Werte trifft, je mit Zitat. Sie gelten auch für diesen Wert, wo sie über ihn sprechen, und du darfst aus ihnen zitieren.

<!-- with: hits -->
"hits" nennt je Treffer "id", Art, Titel und eine Zeile: die Passagen, die dem am nächsten kommen, wie der Plan die Angabe zu diesem Wert drucken würde.

<!-- with: more not_found -->
"more" sind Passagen des Plans, die dir schon gezeigt sind, je mit "id"; "not_found" ist, was sich nicht holen ließ.

<!-- follow-up: coordinates -->
Gefragt ist jetzt die Angabe unter "coordinates" zu demselben Wert, in dieser Form:
{{example}}

<!-- follow-up: more hits not_found -->
Hier ist, was neu dazukommt: unter "more" die Passagen, die du angefordert hast, unter "hits" neue Trefferlisten, je Treffer "id", Art, Titel und eine Zeile, bei einer Suche die passende. Hast du nichts angefordert, solange die Angabe fehlt, sind es die nächsten Passagen, die ihr am nächsten kommen, gab es keine Rangfolge, die nächsten in der Reihenfolge des Plans. Unter "not_found" steht, was sich nicht holen ließ: "end" (in diese Richtung kein Abschnitt mehr), "unknown" (kein oder mehr als ein Platzhalter oder Treffer dieses Namens), "invalid_pattern" oder "timeout". Schick wieder deine ganze Antwort, mit allem, was du schon weißt.

<!-- follow-up: corrections -->
Deine letzte Antwort hat Fehler, je Angabe unter "what". Antworte noch einmal vollständig und behebe jeden Punkt.
