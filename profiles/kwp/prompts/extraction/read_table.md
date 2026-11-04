---
temperature: 0
max_tokens: 6144
---
Du liest EINE Tabelle oder einen Teil einer Tabelle aus einem deutschen kommunalen Wärmeplan ("Kommunale Wärmeplanung") und sagst für die Werte EINER Kennzahl, wo die gefragten Angaben zu ihnen stehen.

Du bekommst:
- "table": die Tabelle oder ihr Teil, "text" mit Titel und Markdown, und der Abschnitt, in dem sie steht; "around": der Text dieses Abschnitts um die Tabelle, mit dem Satz, der sie ankündigt.
- "columns": jede Spalte mit Nummer und Kopf, "rows": jede Zeile mit Nummer und Beschriftung, "part", nur wenn die Tabelle in Teilen gelesen wird: welche Zeilen dieser Teil zeigt.
- "parameter": die Kennzahl mit ihrer Definition.
- "values": die Zellen mit Werten der Kennzahl, je mit "row" und "column" und, wo die Zelle mehrere Zahlen druckt, der Stelle des Werts ("part").
- "coordinates": die gefragten Angaben, je mit Frage und, wo es eine gibt, mit Liste ("options"); "where": wo ein Plan sie meist druckt.
- "known", "base_years" und "target_years", nur wenn nach Szenario oder Jahr gefragt ist: die Paare aus Szenario und Jahr, die der Plan für diese Tabelle nennt, und die Jahre seines eigenen Stands und seines Ziels.
- "more", "hits" und "not_found", nur nachdem du nachgefordert hast (siehe unten).
- "corrections", nur bei einer zweiten Anfrage: was an deiner ersten Antwort nicht stimmte, je Angabe ("coordinate") mit ihrem Ort und dem Grund ("what"). Du antwortest dann noch einmal vollständig und behebst diese Punkte.

Du antwortest unter "coordinates" für jede gefragte Angabe, wo sie steht, in dieser Reihenfolge:
- "rows": für jede Zeile, deren Beschriftung die Angabe nennt (etwa den Energieträger "Erdgas"), ein Eintrag mit "row";
- "columns": für jede Spalte, deren Kopf die Angabe nennt (etwa einen Sektor oder ein Jahr), ein Eintrag mit "column"; gilt sie nur für eine Stelle der Zellen dieser Spalte, etwa die Einheit der zweiten Zahl, dazu "part";
- "cells": für einen Wert, für den die Angabe allein gilt, etwa eine Einheit oder einen Energieträger in seiner eigenen Zelle, ein Eintrag mit "row", "column" und, wo nötig, "part";
- "table": für JEDE Angabe ein Eintrag: ihr Wert, wenn er für die ganze Tabelle gilt (etwa die Einheit im Titel oder in einer Einheitenzeile, das Gebiet im Titel, das Jahr im Satz, der die Tabelle ankündigt), sonst "out:unstated" ohne "quote".
Ein Eintrag an der Zelle gilt vor dem an der Zeile, der vor dem an der Spalte und der vor dem an der Tabelle.

Jeder Eintrag hat "value" (bei einer Liste genau einer ihrer Schlüssel, sonst die Angabe selbst), "value_raw" (das Wort des Plans, wo es nicht der Schlüssel ist) und "quote": EINE zusammenhängende Stelle aus "table" oder "around", Zeichen für Zeichen abgeschrieben, die die Angabe enthält, etwa die Kopfzeile, die Zeile, der Titel oder der Satz, der die Tabelle ankündigt. Aus "around" gilt nur, was über DIESE Tabelle spricht. Eine Zeile oder Spalte, die die Summe oder das Gesamte nennt ("Summe", "gesamt"), beantwortest du mit dem Eintrag der Liste, der das sagt.

Szenario und Jahr nennst du nur, wo die Tabelle oder der Text um sie sie nennt; sonst ist ihr Eintrag unter "table" "out:unstated", und es gilt das Paar aus "known". Trägt eine Spalte, eine Zeile oder der Titel statt einer Jahreszahl nur das Wort des Plans für seinen eigenen Stand ("Basisjahr", "Bilanzjahr", "Ist-Zustand", "Status quo", "IST", "Bestand", "aktuell") oder für sein Ziel ("Zieljahr", "Zielzustand", "Zielszenario", "Ziel"), wähl das Jahr aus "base_years" oder "target_years", auf das dieses Wort verweist: "value" ist die Jahreszahl, "value_raw" das Wort des Plans, Zeichen für Zeichen, und "quote" die Stelle, an der das Wort steht. Nennt "target_years" mehrere Jahre, ist das Zieljahr das, das der Plan selbst so nennt oder in dem sein Ziel erreicht ist, kein Zwischenziel. Fehlt die Liste oder passt keins ihrer Jahre, ist der Eintrag "out:unstated".

Steht eine Angabe weder in der Tabelle noch in "around", darfst du statt "out:unstated" unter "more" nachfordern: {"get": "next"} oder {"get": "previous"} (den nächsten oder den vorigen Abschnitt), {"get": "item", "id": "<<Platzhalter>>"} (eine Tabelle oder Abbildung, deren Platzhalter in eckigen Klammern im Text steht), {"get": "search", "pattern": "<<regulärer Ausdruck>>"} (eine Trefferliste der Passagen, deren Text das Muster enthält, ohne Unterschied von Groß- und Kleinschreibung, je mit "id", Titel und passender Zeile) oder {"get": "hit", "id": "<<id eines Treffers>>"} (die Passage dieses Treffers). Du bekommst dann dieselbe Frage noch einmal, das Nachgeforderte unter "more" und "hits" und unter "not_found", was sich nicht finden ließ, mit Grund. Gib auch beim Nachfordern deine ganze Antwort; ohne neue Anfrage in "more" gilt sie. Das Zitat einer Angabe darf aus "more" stammen.

Antworte mit genau einem JSON-Objekt, in einer Zeile, ohne Text davor oder danach. Die Zitate unten sind Beschreibungen in << >> und stehen in keinem Plan:
{"coordinates": {"carrier": {"rows": [{"row": 1, "value": "<<Schlüssel der Liste>>", "value_raw": "<<Beschriftung der Zeile>>", "quote": "<<die ganze Zeile 1>>"}], "table": {"value": "out:unstated"}}, "unit": {"cells": [{"row": 2, "column": 3, "value": "<<Schlüssel der Liste>>", "quote": "<<die ganze Zeile 2>>"}], "table": {"value": "<<Schlüssel der Liste>>", "quote": "<<Titel oder Einheitenzeile>>"}}}}
