---
temperature: 0
max_tokens: 6144
---
Du liest EINE Passage aus einem deutschen kommunalen Wärmeplan ("Kommunale Wärmeplanung") und sagst für Werte EINER Kennzahl, die in ihr stehen, die gefragten Angaben zu jedem Wert.

Du bekommst:
- "source": die Passage, "text" eines Abschnitts oder einer Tabelle oder die Beschreibung einer Abbildung (zu einer Abbildung kommt ihr Bild), und der Abschnitt, in dem sie steht.
- "around", nur bei einer Tabelle oder Abbildung: der Text ihres Abschnitts um sie, mit dem Satz, der sie ankündigt.
- "parameter": die Kennzahl mit ihrer Definition.
- "values": die Werte der Kennzahl in dieser Passage, je mit "row", Wert und Zitat.
- "coordinates": die gefragten Angaben, je mit Frage und, wo es eine gibt, mit Liste ("options"); "where": wo ein Plan sie meist druckt.
- "known", "base_years" und "target_years", nur wenn nach Szenario oder Jahr gefragt ist: die Paare aus Szenario und Jahr, die der Plan für diese Passage nennt, und die Jahre seines eigenen Stands und seines Ziels.
- "more", "hits" und "not_found", nur nachdem du nachgefordert hast (siehe unten).
- "corrections", nur bei einer zweiten Anfrage: was an deiner ersten Antwort nicht stimmte, je Wert ("row") und Angabe unter "what". Du antwortest dann noch einmal vollständig und behebst diese Punkte.

Für JEDEN Wert aus "values" ein Eintrag in "values" mit seiner "row" und JEDER Angabe aus "coordinates", je mit "value" (bei einer Liste genau einer ihrer Schlüssel, sonst die Angabe selbst), "value_raw" (das Wort des Plans, wo es nicht der Schlüssel ist) und "quote": EINE zusammenhängende Stelle aus "text" oder "around", Zeichen für Zeichen abgeschrieben, die die Angabe enthält und über DIESEN Wert spricht. Aus "around" gilt nur, was über DIESE Tabelle oder Abbildung spricht, nicht über eine andere desselben Abschnitts. Sagt die Passage eine Angabe nicht, ist ihr Eintrag "out:unstated", ohne "quote".

Szenario und Jahr nennst du nur, wo die Passage oder der Text um sie sie nennt; sonst ist ihr Eintrag "out:unstated", und es gilt das Paar aus "known". Steht bei einer Zahl statt einer Jahreszahl nur das Wort des Plans für seinen eigenen Stand ("Basisjahr", "Bilanzjahr", "Ist-Zustand", "Status quo", "IST", "Bestand", "aktuell") oder für sein Ziel ("Zieljahr", "Zielzustand", "Zielszenario", "Ziel"), wähl das Jahr aus "base_years" oder "target_years", auf das dieses Wort verweist: "value" ist die Jahreszahl, "value_raw" das Wort des Plans, Zeichen für Zeichen, und "quote" die Stelle, an der das Wort für deine Zahl steht. Nennt "target_years" mehrere Jahre, ist das Zieljahr das, das der Plan selbst so nennt oder in dem sein Ziel erreicht ist, kein Zwischenziel. Fehlt die Liste oder passt keins ihrer Jahre, ist der Eintrag "out:unstated". Rate das Jahr nicht aus dem Erscheinungsjahr des Plans.

Steht eine Angabe weder in der Passage noch in "around", darfst du statt "out:unstated" unter "more" nachfordern: {"get": "next"} oder {"get": "previous"} (den nächsten oder den vorigen Abschnitt), {"get": "item", "id": "<<Platzhalter>>"} (die Tabelle oder Abbildung, deren Platzhalter in eckigen Klammern im Text steht), {"get": "search", "pattern": "<<regulärer Ausdruck>>"} (eine Trefferliste der Passagen, deren Text das Muster enthält, ohne Unterschied von Groß- und Kleinschreibung, je mit "id", Titel und passender Zeile) oder {"get": "hit", "id": "<<id eines Treffers>>"} (die Passage dieses Treffers). Du bekommst dann dieselbe Frage noch einmal, das Nachgeforderte unter "more" und "hits" und unter "not_found", was sich nicht finden ließ, mit Grund. Gib auch beim Nachfordern deine ganze Antwort; ohne neue Anfrage in "more" gilt sie. Das Zitat einer Angabe darf aus "more" stammen.

Was nur das Bild einer Abbildung zeigt, ist kein Zitat: zitiert wird aus "text".

Antworte mit genau einem JSON-Objekt, in einer Zeile, ohne Text davor oder danach. Die Zitate unten sind Beschreibungen in << >> und stehen in keinem Plan:
{"values": [{"row": "R1", "unit": {"value": "<<Schlüssel der Liste>>", "quote": "<<Satz mit der Einheit>>"}, "subject": {"value": "out:unstated"}}]}
