---
temperature: 0
max_tokens: 8192
---
Du liest EINE Passage aus einem deutschen kommunalen Wärmeplan ("Kommunale Wärmeplanung") für EINE Kennzahl und nennst jeden Wert dieser Kennzahl, der in ihr steht, mit allen Angaben zu ihm.

Du bekommst:
- "source": die Passage, "text" eines Abschnitts oder die Beschreibung einer Abbildung (zu einer Abbildung kommt ihr Bild), und der Abschnitt, in dem sie steht.
- "parameter": die Kennzahl mit ihrer Definition.
- "coordinates": die Angaben, die zu jedem Wert gehören, je mit Frage und, wo es eine gibt, mit Liste ("options").
- "known": die Paare aus Szenario und Jahr, die der Plan für diese Passage nennt.

Für jeden Wert ein Eintrag in "values":
- "value": der Wert, wie die Passage ihn nennt; eine Zahl als Zahl, beim Planungsbüro sein Name.
- "value_raw": nur wenn die Passage die Zahl anders schreibt als in "value".
- "quote": EINE zusammenhängende Stelle aus "text", Zeichen für Zeichen abgeschrieben, die den Wert enthält: sein Satz oder seine Tabellenzeile.
- je Angabe aus "coordinates" ein Eintrag mit "value" (bei einer Liste genau einer ihrer Schlüssel, sonst die Angabe selbst), "value_raw" (das Wort des Plans, wo es nicht der Schlüssel ist) und "quote" (EINE zusammenhängende Stelle aus "text", Zeichen für Zeichen abgeschrieben, die die Angabe enthält). Sagt die Passage eine Angabe nicht, antwortest du mit "out:unstated" und ohne "quote". Szenario und Jahr nennst du nur, wo die Passage sie selbst druckt; sonst gilt das Paar aus "known".

Was nur das Bild einer Abbildung zeigt, ist kein Zitat: zitiert wird aus "text". Nenne jeden Wert einmal.

Antworte mit genau einem JSON-Objekt, in einer Zeile, ohne Text davor oder danach. Die Zitate unten sind Beschreibungen in << >> und stehen in keinem Plan:
{"values": [{"value": 12.5, "quote": "<<Satz mit der Zahl>>", "unit": {"value": "<<Schlüssel der Liste>>", "quote": "<<Satz mit der Einheit>>"}, "carrier": {"value": "out:unstated"}}]}
