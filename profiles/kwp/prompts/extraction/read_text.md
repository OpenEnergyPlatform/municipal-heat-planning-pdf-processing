---
temperature: 0
max_tokens: 6144
---
Du liest EINE Passage aus einem deutschen kommunalen Wärmeplan ("Kommunale Wärmeplanung") und sagst für EINEN Wert EINER Kennzahl die gefragten Angaben.

Du bekommst:
- "parameter": die Kennzahl mit ihrer Definition.
- "coordinates": die gefragten Angaben, je mit Frage und, wo es eine gibt, mit Liste ("options"); "where": wo ein Plan sie meist druckt.
- "source": die Passage, "text" eines Abschnitts, einer ganzen Tabelle mit Titel, Kopf und allen Zeilen oder die Beschreibung einer Abbildung (zu einer Abbildung kommt ihr Bild), und der Abschnitt, in dem sie steht.
- "around", nur bei einer Tabelle oder Abbildung: der Text ihres Abschnitts direkt vor und nach ihr, oft mit dem Satz, der sie ankündigt. Sie steht darin als Platzhalter in eckigen Klammern.
- "value": der Wert mit "value", "quote" und, bei einer Zahl in einer Tabelle, dem Kopf ihrer Spalte ("head"). "read", wo zu ihm schon etwas gelesen ist: diese Angaben im Wortlaut des Plans.
- "corrections", nur bei einer zweiten Anfrage: was an deiner ersten Antwort nicht stimmte, je Angabe ("coordinate") unter "what". Du antwortest dann noch einmal vollständig und behebst diese Punkte.

Für JEDE Angabe aus "coordinates" ein Eintrag mit "value" (bei einer Liste genau einer ihrer Schlüssel, sonst die Angabe selbst), "value_raw" (das Wort des Plans, wo es nicht der Schlüssel ist) und "quote": EINE zusammenhängende Stelle aus "text", der Überschrift unter "section" oder "around", Zeichen für Zeichen abgeschrieben, die die Angabe enthält und über DIESEN Wert spricht. Über eine Zahl in einer Tabelle sprechen ihre Zeile, der Kopf ihrer Spalte und der Titel der Tabelle. Aus "around" gilt nur, was über DIESE Tabelle oder Abbildung spricht, nicht über eine andere desselben Abschnitts. Sagt der Plan eine Angabe nicht, ist ihr Eintrag "out:unstated", ohne "quote". Schreib dann unter "probe" einen kurzen Satz, wie der Plan diese Angabe zu diesem Wert drucken würde; was er nennt, darf erdacht sein, mit ihm wird nur im übrigen Plan nach ihr gesucht.

Zitiert wird aus Text, der dir gezeigt wurde: aus der Passage und der Überschrift ihres Abschnitts, also auch aus den Zeilen einer Tabelle oder der Beschreibung einer Abbildung, oder aus dem Text um sie. Was nur das Bild zeigt und die Beschreibung nicht, ist kein Zitat.

<!-- group: frame -->
Gefragt sind Szenario und Jahr dieses Werts. Dazu bekommst du "known": die Paare aus Szenario und Jahr, die der Plan für diese Passage nennt, und "base_years" und "target_years": die Jahre seines eigenen Stands und seines Ziels.

Szenario und Jahr nennst du nur, wo die Passage, ihre Überschrift oder der Text um sie sie nennt; sonst ist ihr Eintrag "out:unstated", und es gilt das Paar aus "known". Steht bei einer Zahl statt einer Jahreszahl nur das Wort des Plans für seinen eigenen Stand ("Basisjahr", "Bilanzjahr", "Ist-Zustand", "Status quo", "IST", "Bestand", "aktuell") oder für sein Ziel ("Zieljahr", "Zielzustand", "Zielszenario", "Ziel"), wähl das Jahr aus "base_years" oder "target_years", auf das dieses Wort verweist: "value" ist die Jahreszahl, "value_raw" das Wort des Plans, Zeichen für Zeichen, und "quote" die Stelle, an der das Wort für deine Zahl steht. Nennt "target_years" mehrere Jahre, ist das Zieljahr das, das der Plan selbst so nennt oder in dem sein Ziel erreicht ist, kein Zwischenziel. Fehlt die Liste oder passt keins ihrer Jahre, ist der Eintrag "out:unstated". Rate das Jahr nicht aus dem Erscheinungsjahr des Plans.

Antworte mit genau einem JSON-Objekt, in einer Zeile, ohne Text davor oder danach. Die Zitate unten sind Beschreibungen in << >> und stehen in keinem Plan:
{"scenario": {"value": "<<Schlüssel der Liste>>", "value_raw": "<<Wort des Plans für das Szenario>>", "quote": "<<Titel oder Satz, der das Szenario nennt>>"}, "year": {"value": 2022, "value_raw": "<<Wort des Plans für seinen eigenen Stand, wo keine Jahreszahl steht>>", "quote": "<<Stelle mit der Jahreszahl oder diesem Wort>>"}}

<!-- group: number -->
Gefragt sind die Einheit dieser Zahl und ihr Bezug.

Antworte mit genau einem JSON-Objekt, in einer Zeile, ohne Text davor oder danach. Die Zitate unten sind Beschreibungen in << >> und stehen in keinem Plan:
{"unit": {"value": "<<Schlüssel der Liste>>", "quote": "<<Satz oder Zeile mit der Einheit>>"}, "subject": {"value": "out:unstated", "probe": "<<Satz, wie der Plan den Bezug dieses Werts drucken würde>>"}}

<!-- group: context -->
Gefragt ist die Einordnung dieser Zahl. Jede Liste nennt zu ihren Einträgen, was sie bedeuten ("means"), und wie Pläne sie schreiben ("spellings").

Antworte mit genau einem JSON-Objekt, in einer Zeile, ohne Text davor oder danach. Die Zitate unten sind Beschreibungen in << >> und stehen in keinem Plan:
{"quantity": {"value": "<<Schlüssel der Liste>>", "value_raw": "<<Wort des Plans für die Größe>>", "quote": "<<Zeile, Spaltenkopf oder Titel mit diesem Wort>>"}, "sector": {"value": "out:unstated", "probe": "<<Satz, wie der Plan den Sektor dieses Werts drucken würde>>"}}
