---
temperature: 0
max_tokens: 6144
---
Finde in anderen Passagen des Plans jede Angabe unter "coordinates", die dem Wert in "rows" in seiner eigenen Passage fehlt, und antworte aus den Passagen, die dir gezeigt wurden.
Antworte mit genau einem JSON-Objekt in einer Zeile, ohne Text oder Codeblock davor oder danach. No Backticks!
{"rows":[{"row":"R1","year":{"value":2022,"quote":"..."},"scenario":{"value":"out:unstated"}}],"more":[{"get":"hit","id":"H2"}]}

* "rows" enthält einen Eintrag mit der "row" des Werts und jeder Angabe aus "coordinates". "value" ist bei einer Liste ("options") genau einer ihrer Schlüssel, sonst die Angabe selbst, "value_raw" das Wort des Plans, wo es nicht der Schlüssel ist, und "quote" eine zusammenhängende Stelle, Zeichen für Zeichen, die die Angabe enthält und über diesen Wert spricht.
* Eine Angabe, die keine gezeigte Stelle nennt oder die nicht unter "open" steht, ist {"value":"out:unstated"} ohne "quote". Rate nicht: Was du nicht gelesen hast, ist "out:unstated".
* Steht beim Wert statt einer Jahreszahl nur das Wort des Plans für seinen eigenen Stand ("Basisjahr", "Bilanzjahr", "Ist-Zustand", "Status quo", "IST", "Bestand", "aktuell") oder für sein Ziel ("Zieljahr", "Zielzustand", "Zielszenario", "Ziel"), nimm das Jahr aus "base_years" oder "target_years", auf das dieses Wort verweist: "value" ist die Jahreszahl, "value_raw" das Wort, Zeichen für Zeichen, und "quote" die Stelle mit dem Wort. Bei mehreren "target_years" ist es das Jahr, das der Plan selbst Zieljahr nennt oder in dem sein Ziel erreicht ist, kein Zwischenziel.
* "more" nennt, was du lesen willst, bevor du antwortest. Du bekommst dann dieselbe Frage noch einmal, das Nachgeforderte unter "more" und "hits". Schick immer deine ganze Antwort mit allem, was du schon weißt; ohne neue Anfrage in "more" gilt sie.
  - {"get":"hit","id":"..."}: die Passage eines Treffers;
  - {"get":"next"} oder {"get":"previous"}: der Abschnitt nach oder vor der Passage des Werts, beim nächsten Mal der danach oder davor;
  - {"get":"item","id":"..."}: die Tabelle oder Abbildung, deren Platzhalter in eckigen Klammern in einem Text steht;
  - {"get":"search","pattern":"..."}: Treffer für einen regulären Ausdruck, ohne Unterschied von Groß- und Kleinschreibung;
  - {"get":"similar","text":"..."}: Treffer zu einem Satz, wie der Plan die Angabe zu diesem Wert drucken würde; er darf erdacht sein.
* "hits" nennt je Treffer "id", Art, Titel und eine Zeile, bei einer Suche die passende. Die erste Liste, wo es sie gibt, enthält die Passagen, die den Sätzen unter "query" am nächsten sind, geschrieben, als dieser Wert gelesen wurde; gibt es keine, such mit "similar". "not_found" nennt, was sich nicht holen ließ: "end" (in diese Richtung kein Abschnitt mehr), "unknown" (kein oder mehr als ein Platzhalter oder Treffer dieses Namens), "invalid_pattern" oder "timeout".
* Gibt es "corrections", antworte vollständig neu und behebe jeden Punkt unter "what".
