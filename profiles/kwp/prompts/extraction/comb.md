---
temperature: 0
max_tokens: 6144
---
Du suchst in einem deutschen kommunalen Wärmeplan ("Kommunale Wärmeplanung") Angaben zu Werten EINER Kennzahl, die in der Passage der Werte selbst nicht stehen.

Du bekommst:
- "passage": woher die Werte stammen, mit Art, Titel und Abschnitt.
- "parameter": die Kennzahl mit ihrer Definition.
- "rows": die Werte, je mit "row", Zahl, Einheit und Zitat, dazu, was zu ihnen schon gelesen ist ("known", im Wortlaut des Plans), und die Angaben, die noch offen sind ("open").
- "coordinates": die offenen Angaben, je mit Frage und, wo es eine gibt, mit Liste ("options").
- "hits": Trefferlisten, je Treffer mit "id", Art, Titel und erster Zeile. Die erste Liste sind die Passagen des Plans, die zu diesen Werten am besten passen; danach kommen die Treffer deiner eigenen Suchen.
- "more", "not_found": die Passagen, die du nachgefordert hast, je mit "id", und was sich nicht finden ließ, mit Grund ("end": in diese Richtung gibt es keinen Abschnitt mehr, "unknown": kein oder mehr als ein Platzhalter oder Treffer dieses Namens, "invalid_pattern" oder "timeout": das Muster ging nicht).
- "base_years" und "target_years", nur wenn der Plan sie nennt: die Jahre, für die er seinen eigenen Stand erhoben oder bilanziert hat, und die Jahre seines Ziels, als Jahreszahlen.
- "corrections": nur bei einer zweiten Anfrage. Was an deiner ersten Antwort nicht stimmte, je Wert ("row") und Angabe unter "what".

Du antwortest mit:
1. "rows": für JEDEN Wert aus "rows" ein Eintrag mit seiner "row" und JEDER Angabe aus "coordinates", je mit "value" (bei einer Liste genau einer ihrer Schlüssel, sonst die Angabe selbst), "value_raw" (das Wort des Plans, wo es nicht der Schlüssel ist) und "quote": EINE zusammenhängende Stelle aus "more" oder aus dem Zitat des Werts, Zeichen für Zeichen abgeschrieben, die die Angabe enthält und über DIESEN Wert spricht. Steht sie in keiner gezeigten Stelle, ist ihr Eintrag "out:unstated", ohne "quote". Eine Angabe, die bei einem Wert nicht unter "open" steht, ist schon gelesen: ihr Eintrag ist "out:unstated".
   Steht bei einem Wert statt einer Jahreszahl nur das Wort des Plans für seinen eigenen Stand ("Basisjahr", "Bilanzjahr", "Ist-Zustand", "Status quo", "IST", "Bestand", "aktuell") oder für sein Ziel ("Zieljahr", "Zielzustand", "Zielszenario", "Ziel"), wähl das Jahr aus "base_years" oder "target_years", auf das dieses Wort verweist: "value" ist die Jahreszahl, "value_raw" das Wort des Plans, Zeichen für Zeichen, und "quote" die Stelle, an der das Wort steht. Nennt "target_years" mehrere Jahre, ist das Zieljahr das, das der Plan selbst so nennt oder in dem sein Ziel erreicht ist, kein Zwischenziel.
2. "more": was du lesen willst, bevor du antwortest. Eine Liste von Anfragen:
   - {"get": "hit", "id": "<<id eines Treffers>>"}: die Passage dieses Treffers;
   - {"get": "next"} oder {"get": "previous"}: den Abschnitt nach oder vor der Passage der Werte, beim nächsten Mal den danach oder davor;
   - {"get": "item", "id": "<<Platzhalter>>"}: die Tabelle oder Abbildung, deren Platzhalter in eckigen Klammern im Text steht;
   - {"get": "search", "pattern": "<<regulärer Ausdruck>>"}: eine Trefferliste der Passagen des Plans, deren Text das Muster enthält, ohne Unterschied von Groß- und Kleinschreibung.
   Du bekommst dann dieselbe Frage noch einmal, das Nachgeforderte unter "more" und "hits". Gib auch beim Nachfordern deine ganze Antwort mit allem, was du schon weißt; ohne neue Anfrage in "more" gilt sie. Rate nicht: was du nicht gelesen hast, ist "out:unstated".

Bei einer zweiten Anfrage antwortest du noch einmal vollständig und behebst die Punkte aus "corrections".

Antworte mit genau einem JSON-Objekt, in einer Zeile, ohne Text davor oder danach. Die Zitate unten sind Beschreibungen in << >> und stehen in keinem Plan:
{"rows": [{"row": "R1", "year": {"value": 2022, "quote": "<<Satz aus einer nachgeforderten Passage, der das Jahr dieses Werts nennt>>"}, "scenario": {"value": "out:unstated"}}], "more": [{"get": "hit", "id": "H2"}]}
