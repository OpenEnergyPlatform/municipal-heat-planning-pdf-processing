---
temperature: 0
max_tokens: 6144
---
Gib für den Wert unter "value" jede Angabe aus "coordinates" an, so wie der Plan sie für DIESEN Wert nennt.
Prüfe vor der Antwort, was die Definition ausschließt.
Nimm nur Text aus "source" und der Überschrift ihres Abschnitts. Was nur das Bild einer Abbildung zeigt, ist kein Text. Über eine Zahl in einer Tabelle sprechen ihre Zeile, der Kopf ihrer Spalte und der Titel der Tabelle.
Antworte mit genau einer Zeile JSON, mit einem Eintrag je Angabe:
* "value" ist bei einer Liste ("options") genau einer ihrer Schlüssel, sonst die Angabe selbst. "value_raw" ist das Wort des Plans, wo es nicht der Schlüssel ist.
* "quote" kopiert eine zusammenhängende Stelle Zeichen für Zeichen, die die Angabe enthält und über diesen Wert spricht.
* Nennt der Plan eine Angabe nicht, ist ihr Eintrag {"value":"out:unstated","probe":"..."} ohne "quote". "probe" ist ein kurzer Satz, wie der Plan diese Angabe zu diesem Wert drucken würde. Er darf erdacht sein: Mit ihm wird nur im übrigen Plan gesucht.

<!-- with: title_page -->
"title_page" ist die Zeile des Titelblatts, die die Gemeinde des Plans nennt. Auch daraus darfst du zitieren.

<!-- with: around -->
"around" ist der Text des Abschnitts um die Tabelle oder Abbildung. Auch daraus darfst du zitieren.

<!-- with: table_before -->
"table_before" sind Titel und Kopf der Tabelle direkt davor, auf derselben Seite oder der Seite davor; setzt "source" diese Tabelle fort, sprechen sie auch über die Zahl, und du darfst aus ihnen zitieren.

<!-- with: before after -->
"before" und "after" sind die Abschnitte vor und nach der Stelle des Werts. Sie zählen, wo sie über diesen Wert sprechen, und du darfst aus ihnen zitieren.

<!-- with: whole_table -->
"whole_table" heißt: Die Tabelle druckt Szenario und Jahr weder im Kopf noch in den Zeilen, und deine Antwort gilt für jeden ihrer Werte. Nenne, was ihr Titel, der Satz, der sie ankündigt, oder ihr Abschnitt für die ganze Tabelle sagt.

<!-- group: number -->
Gefragt sind die Einheit dieser Zahl und ihr Bezug.
Antworte mit genau einem JSON-Objekt in einer Zeile, ohne Text oder Codeblock davor oder danach. No Backticks! In dieser Form:
{{example}}

<!-- group: frame -->
Gefragt sind Szenario und Jahr des Werts. "known" sind die Paare aus Szenario und Jahr, die der Plan für diese Passage nennt, "base_years" und "target_years" die Jahre seines eigenen Stands und seines Ziels.
Antworte mit genau einem JSON-Objekt in einer Zeile, ohne Text oder Codeblock davor oder danach. No Backticks! In dieser Form:
{{example}}

* Nenne Szenario und Jahr nur, wo eine gezeigte Stelle sie für diesen Wert nennt. Sonst sind sie "out:unstated", und es gilt das Paar aus "known".
* Steht bei der Zahl statt einer Jahreszahl nur das Wort des Plans für seinen eigenen Stand ("Basisjahr", "Bilanzjahr", "Ist-Zustand", "Status quo", "IST", "Bestand", "aktuell") oder für sein Ziel ("Zieljahr", "Zielzustand", "Zielszenario", "Ziel"), nimm das Jahr aus "base_years" oder "target_years", auf das dieses Wort verweist: "value" ist die Jahreszahl, "value_raw" das Wort, Zeichen für Zeichen, und "quote" die Stelle mit dem Wort. Bei mehreren "target_years" ist es das Jahr, das der Plan selbst Zieljahr nennt oder in dem sein Ziel erreicht ist, kein Zwischenziel. Fehlt die Liste oder passt keins ihrer Jahre, ist das Jahr "out:unstated".
* Leite das Jahr nie aus dem Erscheinungsjahr des Plans ab.

<!-- group: context -->
Gefragt ist die Einordnung dieser Zahl. Jeder Listeneintrag nennt, was er bedeutet ("means"), und wie Pläne ihn schreiben ("spellings").
Antworte mit genau einem JSON-Objekt in einer Zeile, ohne Text oder Codeblock davor oder danach. No Backticks! In dieser Form:
{{example}}

* Nennt die Stelle für die Zahl mehrere Einträge einer Liste ("Gas-BHKW + Gas-Brennwert"), ist die Antwort der Eintrag, in den alle fallen; fallen sie in verschiedene, ist sie "Summe", und das Wort des Plans steht in "value_raw".

<!-- follow-up: before after coordinates -->
Unter "before" und "after" stehen die Abschnitte vor und nach der Stelle des Werts. Gib die Angaben unter "coordinates" noch einmal an: Sie zählen, wo diese Abschnitte über diesen Wert sprechen, und du darfst aus ihnen zitieren. Antworte in dieser Form:
{{example}}

<!-- follow-up: corrections -->
Deine letzte Antwort hat Fehler, je Angabe unter "what". Antworte noch einmal vollständig in derselben Form und behebe jeden Punkt.
