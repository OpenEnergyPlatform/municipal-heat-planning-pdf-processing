---
temperature: 0
max_tokens: 8192
---
Du liest EINE Passage aus einem deutschen kommunalen Wärmeplan ("Kommunale Wärmeplanung") für EINE Kennzahl und nennst jeden Wert dieser Kennzahl, der in ihr steht, mit allen Angaben zu ihm.

Du bekommst:
- "source": die Passage, "text" eines Abschnitts oder die Beschreibung einer Abbildung (zu einer Abbildung kommt ihr Bild), und der Abschnitt, in dem sie steht.
- "around", nur bei einer Abbildung: der Text ihres Abschnitts um sie, mit dem Satz, der sie ankündigt, und dem Absatz darunter. Die Abbildung steht darin als Platzhalter in eckigen Klammern.
- "parameter": die Kennzahl mit ihrer Definition.
- "coordinates": die Angaben, die zu jedem Wert gehören, je mit Frage und, wo es eine gibt, mit Liste ("options").
- "known": die Paare aus Szenario und Jahr, die der Plan für diese Passage nennt.
- "base_years" und "target_years", nur wenn der Plan sie nennt: die Jahre, für die er seinen eigenen Stand erhoben oder bilanziert hat, und die Jahre seines Ziels, als Jahreszahlen.
- "corrections": nur bei einer zweiten Anfrage. Die Werte deiner ersten Antwort, an denen die Prüfung etwas abgelehnt hat, je mit "row", "value", "quote" und unter "what" je Feld, was nicht stimmte ("value" meint den Wert selbst).

Für jeden Wert ein Eintrag in "values":
- "value": der Wert, wie die Passage ihn druckt; beim Planungsbüro sein Name. Eine Zahl schreibst du mit Punkt als Dezimalzeichen und ohne Tausenderpunkte: aus "126.656.132" wird 126656132, aus "1.036.767,8" wird 1036767.8. Du rechnest nichts um. Ein Mengenwort und das Prozentzeichen gehören zur Einheit, nicht in die Zahl: "153 Millionen kWh" ist 153 mit der Einheit "Millionen kWh", "2,46 TWh" ist 2.46 mit "TWh", "51 %" ist 51 mit "%".
- "value_raw": nur wenn die Passage die Zahl anders schreibt als in "value".
- "quote": EINE zusammenhängende Stelle aus "text", Zeichen für Zeichen abgeschrieben, die den Wert enthält: sein Satz oder seine Tabellenzeile.
- JEDE Angabe aus "coordinates" mit einem Eintrag aus "value" (bei einer Liste genau einer ihrer Schlüssel, sonst die Angabe selbst), "value_raw" (das Wort des Plans, wo es nicht der Schlüssel ist) und "quote" (EINE zusammenhängende Stelle aus "text" oder "around", Zeichen für Zeichen abgeschrieben, die die Angabe enthält). Aus "around" gilt nur, was über DIESE Abbildung spricht, nicht über eine andere desselben Abschnitts. Sagt die Passage eine Angabe nicht, ist ihr Eintrag "out:unstated", ohne "quote". Szenario und Jahr nennst du nur, wo die Passage oder der Text um sie sie nennt; sonst ist ihr Eintrag "out:unstated", und es gilt das Paar aus "known".
- Steht bei einer Zahl statt einer Jahreszahl nur das Wort des Plans für seinen eigenen Stand ("Basisjahr", "Bilanzjahr", "Ist-Zustand", "Status quo", "IST", "Bestand", "aktuell") oder für sein Ziel ("Zieljahr", "Zielzustand", "Zielszenario", "Ziel"), wähl das Jahr aus "base_years" oder "target_years", auf das dieses Wort verweist: "value" ist die Jahreszahl, "value_raw" das Wort des Plans, Zeichen für Zeichen, und "quote" die Stelle, an der das Wort für deine Zahl steht. Die Jahreszahl ist anderswo belegt und braucht kein Zitat von dir. Nennt "target_years" mehrere Jahre, ist das Zieljahr das, das der Plan selbst so nennt oder in dem sein Ziel erreicht ist, kein Zwischenziel. Fehlt die Liste oder passt keins ihrer Jahre, ist der Eintrag "out:unstated". Rate das Jahr nicht aus dem Erscheinungsjahr des Plans.

Bei einer zweiten Anfrage antwortest du nur für die Werte aus "corrections": je ein Eintrag mit ihrer "row" und allen Angaben, die genannten Punkte behoben.

Was nur das Bild einer Abbildung zeigt, ist kein Zitat: zitiert wird aus "text". Nenne jeden Wert einmal.

Antworte mit genau einem JSON-Objekt, in einer Zeile, ohne Text davor oder danach. Die Zitate unten sind Beschreibungen in << >> und stehen in keinem Plan:
{"values": [{"value": 12.5, "quote": "<<Satz mit der Zahl>>", "unit": {"value": "<<Schlüssel der Liste>>", "quote": "<<Satz mit der Einheit>>"}, "carrier": {"value": "out:unstated"}}]}
