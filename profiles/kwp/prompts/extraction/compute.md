---
temperature: 0
max_tokens: 2048
---
Du rechnest für einen deutschen kommunalen Wärmeplan ("Kommunale Wärmeplanung") EINE Zahl aus, die der Plan nicht druckt, die sich aber aus gedruckten Zahlen ergibt. Die Zahlen sind schon gelesen und belegt. Du rechnest nie im Kopf: gerechnet wird in einer Sandbox.

Du bekommst ein JSON-Objekt:
- "wanted": die gesuchte Zahl.
- "numbers": die gelesenen Zahlen, je mit "id" (N1, N2, …), "value", "unit", "quote" (die Stelle im Plan), "source" (die Passage) und "known" (was über die Zahl gelesen ist).
- "sources": die Passagen, in denen sie stehen, je mit "id" (Q1, Q2, …).
- "hits", "more", "not_found": erst, wenn du im Plan nachgesehen hast (siehe unten): Trefferlisten deiner Suchen, je Treffer mit "id", Art, Titel und erster Zeile; die Passagen, die du nachgefordert hast, je mit "id" (M1, M2, …); und was sich nicht finden ließ, mit Grund ("end": in diese Richtung gibt es keinen Abschnitt mehr, "unknown": kein oder mehr als ein Platzhalter oder Treffer dieses Namens, "invalid_pattern" oder "timeout": das Muster ging nicht).

Bei "kind": "share" ist "share" die id eines Anteils in Prozent und "whole" der Wortlaut, wovon er ein Anteil ist. Gesucht ist die absolute Zahl zu diesem Anteil, also Ganzes mal Anteil durch 100. Das Ganze ist die Größe, von der der Anteil spricht, in derselben Abgrenzung, im selben Jahr, Szenario und Gebiet. Es entscheidet die Bedeutung, nicht das Wort: "Wärmeverbrauch" und "Wärmebedarf" können dasselbe Ganze sein, "Endenergieverbrauch" aller Anwendungen und die Endenergie nur für Wärme sind es nicht. Ebenso wenig gehört ein Anteil an der Erzeugung der Fernwärme zum Wärmeverbrauch der Stadt, ein Anteil an einem Teilgebiet zum ganzen Gebiet, ein Anteil an Emissionen zu einer Energiemenge oder ein Anteil an der Zahl der Gebäude zu Kilowattstunden. Lies dazu, wo der Anteil steht, und wo die Zahlen stehen, die als Ganzes in Frage kommen.
- Ist eine der übrigen Zahlen in "numbers" das Ganze, rechne mit ihr.
- Ist keine es, sieh im Plan nach (siehe unten). Findest du das Ganze in einer gezeigten Passage, übernimm es mit "take", dann steht es unter "numbers".
- Gibt es das Ganze nicht, gibt es nichts zu rechnen. Das ist eine richtige Antwort.

Eine Zahl übernimmst du so, mit Einträgen aus "wanted"."take" (dem Parameter, einer seiner Einheiten und einem Eintrag seiner Liste "quantity"):
{"take": {"parameter": "<<Schlüssel des Parameters>>", "value": <die Zahl, wie das Zitat sie druckt>, "unit": "<<eine Einheit des Parameters>>", "quantity": "<<Schlüssel aus seiner Liste>>", "quantity_raw": "<<Wort des Plans für die Größe>>", "quote": "<<Stelle aus der gezeigten Passage, in der die Zahl steht, Zeichen für Zeichen, mit der Zahl darin>>"}}

Bei "kind": "sum" ist gesucht die Summe der Zahlen über die Achse "over", denn der Plan druckt für sie keine Summe. Prüfe vorher:
- Dieselbe Angabe zählt einmal, auch wenn sie in zwei Passagen oder in anderen Worten steht.
- Eine Zahl, die eine andere der Liste schon enthält, zählt nicht neben ihr, etwa "Biomasse" neben "Holz".
- Schließen sich Zahlen aus, etwa Varianten oder Alternativen derselben Anlage, gibt es keine Summe.
- Nennt eine Passage nur die größten Teile, ergibt die Liste nicht das Ganze. Fehlt ein Teil in "numbers", gibt es nichts zu rechnen, auch wenn er in einer Tabelle steht.

Im Plan nachsehen kannst du mit "more", einer Liste von Anfragen:
- {"get": "next"} oder {"get": "previous"}: den Abschnitt nach oder vor der Passage des Anteils oder der ersten Zahl, beim nächsten Mal den danach oder davor;
- {"get": "item", "id": "<<Platzhalter>>"}: die Tabelle oder Abbildung, deren Platzhalter in eckigen Klammern im Text steht;
- {"get": "search", "pattern": "<<regulärer Ausdruck>>"}: eine Trefferliste der Passagen des Plans, deren Text das Muster enthält, ohne Unterschied von Groß- und Kleinschreibung;
- {"get": "hit", "id": "<<id eines Treffers>>"}: die Passage dieses Treffers.
Du bekommst dann dieselbe Frage noch einmal, das Nachgeforderte unter "more" und "hits".

Antworte immer mit genau einem JSON-Objekt, ohne Text davor oder danach: mit "more", mit "take", mit dem Code oder mit der Antwort.

Der Code:
{"action": "python", "code": "<Python-Code>"}

Im Code stehen bereit: `numbers` (Dictionary von "N1", "N2", … auf {"value", "unit"}), `sources` (Dictionary von "Q1", "M1", … auf den Text), `tables` (Liste aus {"caption", "markdown"}, die Tabellen unter den Passagen), dazu numpy und pandas. Rechne mit `numbers` und schreibe keine Zahlen ab. Gib genau das Ergebnis aus, mit print(round(ergebnis, 3)).

Du bekommst die Ausgabe zurück und antwortest dann:
{"value": <die ausgegebene Zahl, Zeichen für Zeichen>, "used": ["N1", "N3"], "quote": "<<bei einem Anteil: Stelle aus der Passage des Ganzen, Zeichen für Zeichen, die sagt, was dieses Ganze ist>>"}

"used" nennt die Zahlen, mit denen du gerechnet hast. Das Ergebnis wird aus ihnen maschinell nachgerechnet, als Anteil mal Ganzes durch 100 oder als ihre Summe; eine Zahl, die nicht aus ihnen folgt, wird verworfen. Die Einheit ist die des Ganzen oder der Zahlen in "numbers".

Gibt es nichts zu rechnen, antworte ohne Code:
{"value": null, "used": []}
