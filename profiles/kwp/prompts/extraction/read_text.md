---
temperature: 0
max_tokens: 6144
---
Gib für den Wert unter "value" die Angabe unter "coordinates" an, so wie der Plan sie für DIESEN Wert nennt. Jede weitere Angabe zu diesem Wert kommt als eigene Nachricht.
Prüfe vor der Antwort, was die Definition ausschließt.
Nimm nur Text aus dem, was dir gezeigt wurde: "source" und der Überschrift ihres Abschnitts. Was nur das Bild einer Abbildung zeigt, ist kein Text. Über eine Zahl in einer Tabelle sprechen ihre Zeile, der Kopf ihrer Spalte und der Titel der Tabelle.
Antworte mit genau einer Zeile JSON:
* "value" ist bei einer Liste ("options") genau einer ihrer Schlüssel, nach dem, was er bedeutet ("means"), sonst die Angabe selbst. "value_raw" ist das Wort des Plans, wo es nicht der Schlüssel ist.
* "quote" kopiert eine zusammenhängende Stelle Zeichen für Zeichen, die die Angabe enthält und über diesen Wert spricht.
* Nennt der Plan die Angabe nicht, ist ihr Eintrag {"value":"out:unstated","probe":"..."} ohne "quote". "probe" ist ein kurzer Satz, wie der Plan diese Angabe zu diesem Wert drucken würde. Er darf erdacht sein: Mit ihm wird nur im übrigen Plan gesucht.

<!-- with: title_page -->
"title_page" ist die Zeile des Titelblatts, die die Gemeinde des Plans nennt. Auch daraus darfst du zitieren.

<!-- with: settings -->
"settings" sind Festlegungen, die der Plan für alle seine Werte trifft, je mit Zitat. Sie gelten auch für diesen Wert, wo sie über ihn sprechen, und du darfst aus ihnen zitieren.

<!-- with: around -->
"around" ist der Text des Abschnitts um die Tabelle oder Abbildung. Auch daraus darfst du zitieren.

<!-- with: table_before -->
"table_before" sind Titel und Kopf der Tabelle direkt davor, auf derselben Seite oder der Seite davor; setzt "source" diese Tabelle fort, sprechen sie auch über die Zahl, und du darfst aus ihnen zitieren.

<!-- group: number -->
Gefragt ist eine Angabe zu dieser Zahl selbst.
Antworte mit genau einem JSON-Objekt in einer Zeile, ohne Text oder Codeblock davor oder danach. No Backticks! In dieser Form:
{{example}}

<!-- group: frame -->
Gefragt ist eine Angabe zum Rahmen des Werts. "known" sind die Paare aus Szenario und Jahr, die der Plan für diese Passage nennt, "base_years" und "target_years" die Jahre seines eigenen Stands und seines Ziels.
Antworte mit genau einem JSON-Objekt in einer Zeile, ohne Text oder Codeblock davor oder danach. No Backticks! In dieser Form:
{{example}}

* Nenne Szenario und Jahr nur, wo eine gezeigte Stelle sie für diesen Wert nennt. Sonst sind sie "out:unstated", und es gilt das Paar aus "known".
* Steht bei der Zahl statt einer Jahreszahl nur das Wort des Plans für seinen eigenen Stand ("Basisjahr", "Bilanzjahr", "Ist-Zustand", "Status quo", "IST", "Bestand", "aktuell") oder für sein Ziel ("Zieljahr", "Zielzustand", "Zielszenario", "Ziel"), nimm das Jahr aus "base_years" oder "target_years", auf das dieses Wort verweist: "value" ist die Jahreszahl, "value_raw" das Wort, Zeichen für Zeichen, und "quote" die Stelle mit dem Wort. Bei mehreren "target_years" ist es das Jahr, das der Plan selbst Zieljahr nennt oder in dem sein Ziel erreicht ist, kein Zwischenziel. Fehlt die Liste oder passt keins ihrer Jahre, ist das Jahr "out:unstated".
* Leite das Jahr nie aus dem Erscheinungsjahr des Plans ab.

<!-- group: context -->
Gefragt ist eine Einordnung dieser Zahl. Jeder Listeneintrag nennt, was er bedeutet ("means"); die Antwort ist der genaueste Eintrag, den die Wörter des Plans für diese Zahl bedeuten.
Antworte mit genau einem JSON-Objekt in einer Zeile, ohne Text oder Codeblock davor oder danach. No Backticks! In dieser Form:
{{example}}

* Nennt die Stelle für die Zahl mehrere Einträge einer Liste ("Gas-BHKW + Gas-Brennwert"), ist die Antwort der Eintrag, in den alle fallen; fallen sie in verschiedene, ist sie "Summe", und das Wort des Plans steht in "value_raw".

<!-- follow-up: corrections -->
Deine letzte Antwort hat Fehler, je Angabe unter "what". Antworte noch einmal vollständig in derselben Form und behebe jeden Punkt.
