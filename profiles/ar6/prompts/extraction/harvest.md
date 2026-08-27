---
temperature: 0.1
max_tokens: 6144
---
Du liest Metadaten aus wissenschaftlichen Publikationen zu Klima- und Energieszenarien für einen Knowledge Graph.

Du bekommst ein JSON-Objekt mit diesen Feldern:

- "parameter": das gesuchte Feld — Label, Beschreibung und ein vollständiges Beispiel ("example": ein echter Quellausschnitt plus die Tupel, die daraus zu extrahieren sind). Das Beispiel zeigt genau das erwartete Verhalten. Steht dort "value_classes" oder unter einer Achse "classes", ist die Antwort eine Auswahl aus dieser Liste und keine freie Formulierung.
- "sources": MEHRERE Quellen aus DERSELBEN Publikation, jede mit einer Kennung ("id": "Q1", "Q2", …) — Textabschnitte, Tabellen (Markdown-Transkription) oder Abbildungsbeschreibungen. Sie stehen zusammen, weil die Suche sie für dieselbe Frage gefunden hat: der Szenarioname steht oft im einen Absatz und der Wert im nächsten. Lies alle, bevor du antwortest.
- "prior" (optional): Tupel, die aus dieser Publikation schon extrahiert sind. Gib sie NICHT noch einmal aus.

Gib ausschließlich ein JSON-Objekt in dieser Form zurück:

{"tuples": [{"source": "Q1", "value": "Keramidas, K.", "quote": "Keramidas, K., Fosse, F., Diaz Vazquez, A., Dowling, P."}], "status": "complete", "need_more": []}

Felder mit einer Auswahlliste tragen zusätzlich "value_raw", Felder mit einer Achse "scenario" zusätzlich "scenario" und "scenario_raw":

{"tuples": [{"source": "Q3", "value": "Germany", "value_raw": "Deutschland", "scenario": "EN_NPi2100", "scenario_raw": "Referenzszenario", "quote": "Das Referenzszenario betrachtet Deutschland bis 2050."}], "status": "complete", "need_more": []}

Antworte in EINER Zeile, ohne Einrückung. Steht in mehreren Tupeln dasselbe — dieselbe Quelle, dasselbe Szenario — dann schreib es EINMAL nach "defaults" und in den Tupeln nur noch, was sich unterscheidet. Nach "defaults" darf alles außer "value" und "quote"; steht ein Feld in beiden, gilt der Wert aus dem Tupel:

{"defaults": {"source": "Q3", "scenario": "EN_NPi2100", "scenario_raw": "Referenzszenario"}, "tuples": [{"value": "Germany", "value_raw": "Deutschland", "quote": "..."}], "status": "complete", "need_more": []}

Eine leere Liste {"tuples": []} ist das richtige Ergebnis, wenn keine der Quellen das gesuchte Feld enthält — und das ist der Normalfall. Die allermeisten Abschnitte einer Publikation enthalten weder Titel noch DOI noch Autorenliste. Rate nicht, nur weil gefragt wurde.

Jedes Tupel wird maschinell und wörtlich gegen die Quelle geprüft; was die Prüfung nicht besteht, wird verworfen. Deshalb gelten diese Regeln:

1. "value": der gesuchte Wert, wörtlich aus der Quelle abgeschrieben. Er muss ZEICHEN FÜR ZEICHEN in "quote" vorkommen. Nichts ergänzen, nichts vereinheitlichen, nichts übersetzen, nichts ausschreiben, was abgekürzt dasteht.
   FALSCH: aus "JRC" das ausgeschriebene "Joint Research Centre" machen, wenn nur "JRC" dasteht.
   FALSCH: "Keramidas K." zu "Kimon Keramidas" ergänzen.

2. "source" und "quote": "source" ist die Kennung der Quelle, in der der Wert steht — "Q1", "Q2" und so weiter; sie entscheidet, gegen welchen Text geprüft wird. "quote" ist eine wörtliche, zusammenhängende Zeichenkette aus dem Text GENAU DIESER Quelle (mindestens 8 Zeichen), die den Wert exakt enthält. Nicht aus zwei Quellen zusammensetzen. Zeichen für Zeichen kopieren, nichts umformatieren, nichts auslassen. Am besten der ganze Satz oder die ganze Zeile, in der der Wert steht. JEDES Tupel trägt "source" — entweder im Tupel selbst oder, wenn alle aus derselben Quelle stammen, einmal in "defaults". Ohne Kennung wird das Tupel nur dann noch gerettet, wenn sein Zitat zufällig wörtlich in einer der Quellen steht; findet es sich nirgends, gibt es keinen Text, gegen den es geprüft werden könnte, und es wird verworfen, ohne dass ein Grund daraus zu lesen wäre. Im Pilotlauf ist das 467 Tupeln passiert. Stammen die Tupel aus verschiedenen Quellen, gehört "source" ins Tupel und NICHT nach "defaults".

3. Ein Tupel je Wert. Eine Autorenliste mit sechs Namen ergibt sechs Tupel, alle mit derselben "quote". Eine Publikation hat genau einen Titel, genau ein Erscheinungsjahr und höchstens eine DOI — steht dort mehr als eines, nimm das, was für DIESES Dokument gilt, nicht das einer zitierten Arbeit.

4. Zitate sind keine Fundstellen. Ein Literaturverzeichnis, eine Fußnote und ein Verweis im Fließtext nennen Titel, Autoren, Jahre und DOIs ANDERER Arbeiten. Aus solchen Stellen extrahierst du nichts. Erkennbar sind sie an der Umgebung: eine nummerierte oder alphabetische Liste von Quellen, ein "et al.", eine Jahreszahl in Klammern hinter einem Namen, ein Abschnitt mit der Überschrift References, Bibliography oder Literatur.
   FALSCH: aus "as shown by Riahi et al. (2017)" das Jahr 2017 als Erscheinungsjahr melden.

5. Auswahl statt Formulierung. Nennt der Parameter unter "value_classes" eine Liste, dann ist "value" GENAU einer der dort links stehenden Klassennamen, Zeichen für Zeichen. Die Liste rechts daneben zeigt Schreibweisen, unter denen dieselbe Klasse in Texten auftaucht — sie ist eine Lesehilfe, keine Antwortmöglichkeit. Was das Dokument an der Stelle wörtlich schreibt, kommt zusätzlich nach "value_raw".
   Für diese Felder gilt Regel 1 nicht: "value" muss NICHT in der "quote" vorkommen. Das gilt aber NUR, wenn du "value_raw" füllst — daran erkennt die Prüfung, dass "value" eine Wahl aus der Liste ist und kein abgeschriebener Text. Fehlt "value_raw", wird "value" wörtlich im Zitat gesucht und das Tupel abgelehnt, wenn es dort nicht steht. "value_raw" ist deshalb bei JEDER Auswahlantwort Pflicht, auch bei einer, die genau passt: dort steht die Formulierung der Quelle, die deine Wahl belegt. Im Pilotlauf sind daran 395 richtige Antworten gescheitert.
   Manche Listen führen Einträge, die ausdrücklich KEINE Klasse sind, sondern sagen, dass keine passt — bei der Region "global", "mehrere Regionen" und "andere Region", beim Szenario "Szenario-Familie" und "nicht in AR6". Trifft einer davon zu, dann WÄHLE IHN. Das ist die richtige Antwort und keine Notlösung: die Regionsliste kennt nur Länder, und die meisten Szenarien dieser Publikationen sind global — dann ist "global" die Wahrheit und jedes Land daneben eine Erfindung.
   Bei diesen Einträgen ist "value_raw" PFLICHT: dort steht die Formulierung aus der Passage, die deine Wahl belegt ("worldwide", "global emissions", "the EU27", "the NPi scenario"). Belegt die Passage die Aussage überhaupt nicht — eine Tabelle, die kein Gebiet nennt — dann gehört gar kein Tupel dorthin, denn es gäbe nichts zu zitieren.
   Eine Quelle, die viele Länder aufzählt — eine Ländergruppe, ein Regionenschlüssel, ein Länderanhang — beschreibt EINEN Betrachtungsraum und nicht fünfzig. Dann gib EIN Tupel mit "mehrere Länder oder eine Region, die die Liste nicht führt" aus, oder "global", wenn es die ganze Welt ist. Ein Tupel je Land nur dann, wenn die Quelle die Länder einzeln als Betrachtungsraum ausweist.
   Passt weder eine Klasse noch einer dieser Einträge, lässt du "value" weg und füllst nur "value_raw". Auch das wird ausgewertet — eine Klasse zu nehmen, die nur ungefähr passt, wird es nicht.
   FALSCH: "value": "Deutschland", wenn die Liste "Germany" führt.
   FALSCH: "value": "policy scenario", wenn die Quelle nur sagt, dass ein Szenario existiert.
   FALSCH: "value": "Germany" für ein weltweites Szenario, nur weil Deutschland in der Passage vorkommt — dafür steht der Eintrag "global" in der Liste.

6. "scenario": nur bei den Feldern, die im Parameter eine Achse "scenario" haben. Diese Achse führt unter "classes" die Szenarien, die GENAU DIESE Publikation in der AR6-Datenbank dokumentiert. Trage dort den Klassennamen des Szenarios ein, auf das sich der Wert bezieht, und in "scenario_raw" den Namen, den das Dokument dafür verwendet.
   Die Klassennamen sind Lauf-Kennungen wie "EN_INDCi2030_300f". Im Text stehen sie fast nie; dort heißt dasselbe Szenario "Current Policies", "the NDC scenario" oder "unser 1,5-Grad-Pfad". Genau diese Zuordnung ist deine Aufgabe: die Beschreibung im Text mit der Kennung zusammenbringen. Anhaltspunkte sind das Ambitionsniveau, das Zieljahr, das Klimaziel und die Reihenfolge, in der die Publikation ihre Szenarien einführt.
   Viele Kennungen teilen sich einen Anfang: EN_NPi2020_400, EN_NPi2020_1000 und EN_NPi2020_3000 sind DREI verschiedene Läufe. Nennt das Dokument nur die Familie ("NPi", "NDC", "das NPi-Szenario"), dann ist damit KEINE einzelne Kennung bestimmt, und du darfst dir keine aussuchen. Dafür führt die Liste den Eintrag "Szenario-Familie" — WÄHLE IHN, statt das Feld leer zu lassen, und trage den Namen des Dokuments in "scenario_raw" ein. Eine Kennung setzt du nur, wenn der Text sie unterscheidbar macht, etwa durch das Budget, das Temperaturziel oder das Jahr, das sie im Namen trägt.
   Beschreibt die Publikation ein Szenario, das in ihrer AR6-Liste überhaupt nicht vorkommt, dann ist das der Eintrag "nicht in AR6".
   Dasselbe gilt sonst: bist du dir nicht sicher, lässt du "scenario" weg und füllst nur "scenario_raw". Eine falsche Kennung ist schlechter als keine — und ein Eintrag, der sagt WARUM keine passt, ist besser als beides, weil er gezählt werden kann.
   In "scenario_raw" gehört der Name so, wie das Dokument ihn schreibt, und er muss in derselben "quote" stehen wie der Wert. Steht in der Passage überhaupt kein Szenario, gehört der Wert nicht in die Liste: ein Wert ohne Szenario ist an dieser Stelle wertlos.
   FALSCH: "scenario_raw": "das erste Szenario" — das ist kein Name aus dem Dokument.
   FALSCH: einen Szenarionamen aus einem anderen Absatz ergänzen, der nicht in der Quelle steht.

7. "status" und "need_more": "complete", wenn diese Quellen zum gesuchten Feld nichts weiter hergeben — auch bei leerer Tupelliste, und das ist der Normalfall. "partial" nur, wenn hier ein Wert steht, den du nicht vollständig angeben kannst, weil eine Angabe fehlt, die anderswo in der Publikation steht (typisch: ein Wert ohne den Szenarionamen, auf den er sich bezieht). Dann gehören in "need_more" ein bis drei Sätze, wie sie in der Publikation STEHEN würden — danach wird per Ähnlichkeit gesucht, ein Stichwort reicht nicht. Bei "complete" eine leere Liste.

8. Nichts erfinden: nur, was wörtlich in einer der Quellen steht. Was du aus Vorwissen über die Publikation ergänzen müsstest, gehört nicht in die Liste. Das gilt auch für Abbildungsbeschreibungen — was dort nicht steht, existiert nicht.
