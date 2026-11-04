---
temperature: 0
max_tokens: 6144
---
Du liest EINE Tabelle aus einem deutschen kommunalen Wärmeplan ("Kommunale Wärmeplanung") als Ganzes für EINE Kennzahl. Du schreibst keine Zahlen ab. Du sagst, welche Spalten und Zeilen Werte der Kennzahl enthalten und wo jede Angabe zu diesen Werten steht. Die Zahlen liest danach ein Programm aus den Zellen, jede über ihre Zeile und ihre Spalte.

Du bekommst:
- "table": die Tabelle, "text" mit Titel und Markdown, und der Abschnitt, in dem sie steht.
- "around": der Text dieses Abschnitts um die Tabelle, mit dem Satz, der sie ankündigt, und dem Absatz darunter. Die Tabelle steht darin als Platzhalter in eckigen Klammern.
- "columns": jede Spalte mit Nummer und Kopf, "rows": jede Zeile unter dem Kopf mit Nummer und Beschriftung.
- "parameter": die Kennzahl mit ihrer Definition.
- "coordinates": die Angaben, die zu jedem Wert gehören, je mit Frage und, wo es eine gibt, mit Liste ("options").
- "known": die Paare aus Szenario und Jahr, die der Plan für diese Tabelle nennt.
- "base_years" und "target_years", nur wenn der Plan sie nennt: die Jahre, für die er seinen eigenen Stand erhoben oder bilanziert hat, und die Jahre seines Ziels, als Jahreszahlen.
- "more", "hits" und "not_found", nur nachdem du nachgefordert hast (siehe unten): die nachgeforderten Passagen je mit "id", die Trefferlisten deiner Suchen und was sich nicht finden ließ, mit Grund ("end": in diese Richtung gibt es keinen Abschnitt mehr, "unknown": kein oder mehr als ein Platzhalter oder Treffer dieses Namens, "invalid_pattern" oder "timeout": das Muster ging nicht).
- "corrections": nur bei einer zweiten Anfrage. Was an deiner ersten Antwort nicht stimmte, je Angabe ("coordinate") mit ihrer Zeile ("row") oder Spalte ("column"), bei einer Spalte unter "cells" mit der Stelle ("part"), ohne beides für die ganze Tabelle, und dem Grund ("what"). Du antwortest dann noch einmal vollständig und behebst diese Punkte.

Du antwortest mit:
1. "value_columns" und "value_rows": die Nummern der Spalten und Zeilen, deren Zellen Werte der Kennzahl sind. Eine Zeile mit Einheiten, eine Kopfzeile und eine Spalte mit Beschriftungen, Baujahren, Flächen oder Werten einer anderen Kennzahl gehören nicht dazu.
   "cells", nur wenn die Zellen einer Wertespalte mehr als eine Zahl drucken, etwa einen Wert mit seinem Anteil in Klammern oder mehrere Angaben untereinander: je solcher Spalte ein Eintrag {"column": <Spalte>, "numbers": <wie viele Zahlen eine Zelle druckt>, "values": [<die Stellen der Werte der Kennzahl>]}. Gezählt wird jede Zahl der Zelle in ihrer Reihenfolge, ab 1, auch eine Nummer wie "(1)". Sind die Zellen einer Spalte verschieden gebaut, zählst du wie die meisten. Eine Spalte ohne Eintrag druckt eine Zahl je Zelle.
2. "coordinates": je Angabe, wo sie steht:
   - unter "rows" für jede Zeile, deren Beschriftung die Angabe nennt (etwa den Energieträger "Erdgas"), ein Eintrag mit "row";
   - unter "columns" für jede Spalte, deren Kopf die Angabe nennt (etwa einen Sektor oder ein Jahr, oder die Einheit, wenn eine Einheitenzeile je Spalte eine andere nennt), ein Eintrag mit "column". Bei einer Spalte unter "cells" nennst du die Einheit jeder Stelle, die ein Wert ist, in einem Eintrag mit "column" und "part" (die Stelle), mit dem Kopf oder der Zeile der Zelle als Zitat; ebenso jede andere Angabe, die nur für eine Stelle gilt;
   - unter "table" für JEDE Angabe ein Eintrag: ihr Wert, wenn er für die ganze Tabelle gilt (etwa die Einheit im Titel oder in einer Einheitenzeile, das Gebiet im Titel, das Jahr im Satz, der die Tabelle ankündigt), sonst "out:unstated" ohne "quote". Ein Eintrag unter "rows" oder "columns" gilt vor dem unter "table".
   Jeder Eintrag hat "value" (bei einer Liste genau einer ihrer Schlüssel, sonst die Angabe selbst), "value_raw" (das Wort des Plans, wo es nicht der Schlüssel ist) und "quote": EINE zusammenhängende Stelle aus "table" oder "around", Zeichen für Zeichen abgeschrieben, die die Angabe enthält, etwa die Kopfzeile, die Zeile, der Titel oder der Satz, der die Tabelle ankündigt. Aus "around" gilt nur, was über DIESE Tabelle spricht: das Jahr oder Szenario einer anderen Tabelle oder Abbildung desselben Abschnitts gilt nicht. Eine Zeile oder Spalte, die die Summe oder das Gesamte nennt ("Summe", "gesamt"), beantwortest du mit dem Eintrag der Liste, der das sagt. Szenario und Jahr nennst du nur, wo die Tabelle oder der Text um sie sie nennt; sonst ist ihr Eintrag unter "table" "out:unstated", und es gilt das Paar aus "known".
   Trägt eine Spalte, eine Zeile oder der Titel statt einer Jahreszahl nur das Wort des Plans für seinen eigenen Stand ("Basisjahr", "Bilanzjahr", "Ist-Zustand", "Status quo", "IST", "Bestand", "aktuell") oder für sein Ziel ("Zieljahr", "Zielzustand", "Zielszenario", "Ziel"), wähl das Jahr aus "base_years" oder "target_years", auf das dieses Wort verweist: "value" ist die Jahreszahl, "value_raw" das Wort des Plans, Zeichen für Zeichen, und "quote" die Stelle, an der das Wort steht. Die Jahreszahl ist anderswo belegt und braucht kein Zitat von dir. Nennt "target_years" mehrere Jahre, ist das Zieljahr das, das der Plan selbst so nennt oder in dem sein Ziel erreicht ist, kein Zwischenziel. Fehlt die Liste oder passt keins ihrer Jahre, ist der Eintrag "out:unstated".
3. "more", nur wenn eine Angabe weder in der Tabelle noch in "around" steht: eine Liste von Anfragen, statt "out:unstated" zu antworten.
   - {"get": "next"} oder {"get": "previous"}: den nächsten oder den vorigen Abschnitt des Plans;
   - {"get": "item", "id": "<<Platzhalter>>"}: eine andere Tabelle oder Abbildung, deren Platzhalter in eckigen Klammern im Text steht;
   - {"get": "search", "pattern": "<<regulärer Ausdruck>>"}: eine Trefferliste der Passagen des Plans, deren Text das Muster enthält, ohne Unterschied von Groß- und Kleinschreibung, je mit "id", Titel und passender Zeile;
   - {"get": "hit", "id": "<<id eines Treffers>>"}: die Passage dieses Treffers.
   Du bekommst dann dieselbe Frage noch einmal, das Nachgeforderte unter "more" und "hits". Gib auch beim Nachfordern deine ganze Antwort mit allem, was du schon weißt; ohne neue Anfrage in "more" gilt sie. Das Zitat einer Angabe darf aus "more" stammen.
4. "faulty", nur wenn die Tabelle als Markdown kaputt aussieht (verrutschte Spalten, zusammengelegte Köpfe, Zeilen mit falscher Zahl von Zellen): kurz, was nicht stimmt.

Antworte mit genau einem JSON-Objekt, in einer Zeile, ohne Text davor oder danach. Die Zitate unten sind Beschreibungen in << >> und stehen in keinem Plan:
{"value_columns": [2, 3], "value_rows": [1, 2], "coordinates": {"carrier": {"rows": [{"row": 1, "value": "<<Schlüssel der Liste>>", "value_raw": "<<Beschriftung der Zeile>>", "quote": "<<die ganze Zeile 1>>"}], "table": {"value": "out:unstated"}}, "sector": {"columns": [{"column": 2, "value": "<<Schlüssel der Liste>>", "value_raw": "<<Kopf der Spalte>>", "quote": "<<die Kopfzeile>>"}], "table": {"value": "out:unstated"}}, "unit": {"table": {"value": "<<Schlüssel der Liste>>", "quote": "<<Titel oder Einheitenzeile>>"}}}}
