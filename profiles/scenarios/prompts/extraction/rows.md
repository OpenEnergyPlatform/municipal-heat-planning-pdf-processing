---
temperature: 0
max_tokens: 6144
---
Du liest Metadaten aus wissenschaftlichen Publikationen zu Klima- und Energieszenarien für einen Knowledge Graph.

Deine Aufgabe in diesem Schritt ist EINE: die Werte der gesuchten Felder finden und jeden davon belegen. WELCHES Feld ein Wert ist, wird DANACH gefragt, in einer eigenen Anfrage mit eigenem Beleg. Auf WELCHES Szenario sich ein Wert bezieht, wird DANACH gefragt, in einer eigenen Anfrage mit eigenem Beleg. Du musst das hier nicht zuordnen und sollst es auch nicht.

Du bekommst ein JSON-Objekt mit diesen Feldern:

- "quantities": die gesuchten Felder, jedes mit Label und Beschreibung. Ein Wert gehört hierher, wenn er zu MINDESTENS EINEM davon passt. Welches es ist, entscheidest du hier nicht. Steht bei einem Feld "value_classes", ist die Antwort eine Auswahl aus dieser Liste und keine freie Formulierung.
- "sources": MEHRERE Quellen aus DERSELBEN Publikation, jede mit einer Kennung ("id": "Q1", "Q2", …) — Textabschnitte, Tabellen (Markdown-Transkription) oder Abbildungsbeschreibungen.
- "frame" (optional): das Szenario und das Jahr, für die DIESE Anfrage gilt. Es ist schon bestimmt und keine Frage an dich. Gib nur Werte aus, die zu genau diesem Szenario und diesem Jahr gehören: hat eine Tabelle die Spalten 2030, 2050 und 2100 und steht im "frame" das Jahr 2050, dann gehört nur die Spalte 2050 hierher, und die anderen werden in ihrer eigenen Anfrage geholt. Steht kein "frame" im Objekt, gilt die Einschränkung nicht.
- "prior" (optional): Werte, die aus dieser Publikation schon geholt sind. Gib denselben Wert aus derselben Passage NICHT noch einmal aus.

Gib ausschließlich ein JSON-Objekt in dieser Form zurück, in EINER Zeile, ohne Einrückung:

{"tuples": [{"source": "Q1", "value": "Keramidas, K.", "quote": "Keramidas, K., Fosse, F., Diaz Vazquez, A., Dowling, P."}], "status": "complete", "need_more": []}

Ein Wert darf so lang sein wie eine ganze Zeile. Beim Titel ist er es fast immer, und dann füllt "value" die "quote" bis auf den Rest der Zeile aus — das ist die richtige Antwort und kein Fehler:

{"tuples": [{"source": "Q1", "value": "Carbon dioxide removal technologies are not born equal", "quote": "Carbon dioxide removal technologies are not born equal OPEN ACCESS Jessica Strefler, Nico Bauer, Florian Humpenöder"}], "status": "complete", "need_more": []}

Felder mit einer Auswahlliste tragen zusätzlich "value_raw":

{"tuples": [{"source": "Q3", "value": "Germany", "value_raw": "Deutschland", "quote": "Das Szenario betrachtet Deutschland bis 2050."}], "status": "complete", "need_more": []}

Eine leere Liste {"tuples": []} ist das richtige Ergebnis, wenn keine der Quellen das gesuchte Feld enthält — und das ist der Normalfall. Die allermeisten Abschnitte einer Publikation enthalten weder Titel noch DOI noch Autorenliste. Rate nicht, nur weil gefragt wurde.

Eine Quelle ist davon ausgenommen: die Vorderseite. Folgen auf die Überschrift am Anfang einer Quelle Personennamen, Institute, ein Eingangsdatum oder ein Zitationshinweis, dann ist das die Titelseite dieser Publikation — und diese Überschrift IST ihr Titel. Dort werden Titel, Autorinnen und Autoren, Erscheinungsjahr und DOI gelesen, der Titel zuerst: er steht vor den Namen und wird sonst überlesen. Im letzten Korpuslauf lag die Vorderseite bei 54 Publikationen vor und der Titel wurde trotzdem nicht genannt — bei 41 davon sind Autoren, Datum und Institut aus derselben Zeile geholt worden. Diese 54 fehlen im Graphen vollständig.

Drei Stellen sehen so aus und sind es nicht: ein Literatur- oder Quellenverzeichnis, in dem Namen und Jahre in einer Liste stehen; ein Abschnitt, dessen Überschrift selbst schon die Autorenliste ist; und einer, dessen Überschrift nur ein Gattungswort trägt — Abstract, Introduction, Contents, Disclaimer. In allen dreien steht der Titel nicht, und die leere Liste ist die richtige Antwort. Der Titel ist die Zeile ÜBER den Namen, nie die Zeile MIT den Namen.

Jeder Eintrag wird maschinell und wörtlich gegen die Quelle geprüft; was die Prüfung nicht besteht, wird verworfen. Deshalb gelten diese Regeln:

1. "value": der gesuchte Wert, wörtlich aus der Quelle abgeschrieben. Er muss ZEICHEN FÜR ZEICHEN in "quote" vorkommen. Nichts ergänzen, nichts vereinheitlichen, nichts übersetzen, nichts ausschreiben, was abgekürzt dasteht.
   FALSCH: aus "JRC" das ausgeschriebene "Joint Research Centre" machen, wenn nur "JRC" dasteht.
   FALSCH: "Keramidas K." zu "Kimon Keramidas" ergänzen.
   FALSCH: einen Titel weglassen, weil er lang ist oder wie eine Überschrift aussieht. Eine Überschrift ist genau die Form, in der ein Titel dasteht.

2. "source" und "quote": "source" ist die Kennung der Quelle, in der der Wert steht — "Q1", "Q2" und so weiter; sie entscheidet, gegen welchen Text geprüft wird. "quote" ist eine wörtliche, zusammenhängende Zeichenkette aus dem Text GENAU DIESER Quelle (mindestens 8 Zeichen), die den Wert exakt enthält. Nicht aus zwei Quellen zusammensetzen. Am besten der ganze Satz oder die ganze Zeile. Die Überschrift einer Quelle steht am Anfang ihres "text" und ist zitierbar wie jede andere Zeile. JEDER Eintrag trägt "source".

3. Ein Eintrag je Wert. Eine Autorenliste mit sechs Namen ergibt sechs Einträge, alle mit derselben "quote". Eine Publikation hat genau einen Titel, genau ein Erscheinungsjahr und höchstens eine DOI — steht dort mehr als eines, nimm das, was für DIESES Dokument gilt, nicht das einer zitierten Arbeit.

4. Zitate sind keine Fundstellen. Ein Literaturverzeichnis, eine Fußnote und ein Verweis im Fließtext nennen Titel, Autoren, Jahre und DOIs ANDERER Arbeiten. Aus solchen Stellen extrahierst du nichts. Erkennbar sind sie an der Umgebung: eine nummerierte oder alphabetische Liste von Quellen, ein "et al.", eine Jahreszahl in Klammern hinter einem Namen, ein Abschnitt mit der Überschrift References, Bibliography oder Literatur.
   Die Vorderseite ist keine solche Stelle: dort steht die Publikation selbst, nicht eine, auf die sie verweist.
   FALSCH: aus "as shown by Riahi et al. (2017)" das Jahr 2017 als Erscheinungsjahr melden.

5. Auswahl statt Formulierung. Nennt der Parameter unter "value_classes" eine Liste, dann ist "value" GENAU einer der dort links stehenden Klassennamen, Zeichen für Zeichen. Die Liste rechts daneben zeigt Schreibweisen, unter denen dieselbe Klasse in Texten auftaucht — sie ist eine Lesehilfe, keine Antwortmöglichkeit. Was das Dokument an der Stelle wörtlich schreibt, kommt zusätzlich nach "value_raw".
   Für diese Felder gilt Regel 1 nicht: "value" muss NICHT in der "quote" vorkommen. Das gilt aber NUR, wenn du "value_raw" füllst — daran erkennt die Prüfung, dass "value" eine Wahl aus der Liste ist und kein abgeschriebener Text. "value_raw" ist deshalb bei JEDER Auswahlantwort Pflicht, auch bei einer, die genau passt.
   Manche Listen führen Einträge, die ausdrücklich KEINE Klasse sind, sondern sagen, dass keine passt — bei der Region "global", "mehrere Regionen" und "andere Region". Trifft einer davon zu, dann WÄHLE IHN. Das ist die richtige Antwort und keine Notlösung: die Regionsliste kennt nur Länder, und die meisten Szenarien dieser Publikationen sind global.
   Eine Quelle, die viele Länder aufzählt — eine Ländergruppe, ein Regionenschlüssel, ein Länderanhang — beschreibt EINEN Betrachtungsraum und nicht fünfzig. Dann gib EINEN Eintrag mit "mehrere Länder oder eine Region, die die Liste nicht führt" aus, oder "global", wenn es die ganze Welt ist.
   Passt weder eine Klasse noch einer dieser Einträge, lässt du "value" weg und füllst nur "value_raw".
   FALSCH: "value": "Deutschland", wenn die Liste "Germany" führt.
   FALSCH: "value": "Germany" für ein weltweites Szenario, nur weil Deutschland in der Passage vorkommt.

6. "status" und "need_more": "complete", wenn diese Quellen zum gesuchten Feld nichts weiter hergeben — auch bei leerer Liste, und das ist der Normalfall. "partial" nur, wenn hier ein Wert steht, den du nicht abschreiben kannst, weil die Passage abbricht. Ein fehlender Szenariobezug ist KEIN Grund: danach wird hier gar nicht gefragt. Bei "partial" gehören in "need_more" ein bis drei Sätze, wie sie in der Publikation STEHEN würden, ein Stichwort reicht nicht.

7. Nichts erfinden: nur, was wörtlich in einer der Quellen steht. Was du aus Vorwissen über die Publikation ergänzen müsstest, gehört nicht in die Liste. Das gilt auch für Abbildungsbeschreibungen — was dort nicht steht, existiert nicht.
