---
template: rows
without: [quantities_units, quantities_text, frame_keys, completeness, frame_empty, value_number, unit_raw, quote_whole_row, quote_copy, examples_foreign, status_frame, invent_chart, sandbox]
temperature: 0
max_tokens: 6144
---
<!-- part: role -->
Du liest Metadaten aus wissenschaftlichen Publikationen zu Klima- und Energieszenarien für einen Knowledge Graph.

<!-- part: asked_afterwards -->
WELCHES Feld ein Wert ist, wird DANACH gefragt, in einer eigenen Anfrage mit eigenem Beleg. Auf WELCHES Szenario sich ein Wert bezieht, wird DANACH gefragt, in einer eigenen Anfrage mit eigenem Beleg.

<!-- part: example_reply -->
{"tuples": [{"source": "Q1", "value": "Keramidas, K.", "quote": "Keramidas, K.,"}], "status": "complete", "need_more": []}

<!-- part: example_more -->
Ein Wert darf so lang sein wie eine ganze Zeile. Beim Titel ist er es fast immer, und dann ist "quote" der Titel selbst, genau so lang wie "value" — das ist die richtige Antwort und kein Fehler:

{"tuples": [{"source": "Q1", "value": "Carbon dioxide removal technologies are not born equal", "quote": "Carbon dioxide removal technologies are not born equal"}], "status": "complete", "need_more": []}

Felder mit einer Auswahlliste tragen zusätzlich "value_raw":

{"tuples": [{"source": "Q3", "value": "Germany", "value_raw": "Deutschland", "quote": "Das Szenario betrachtet Deutschland bis 2050."}], "status": "complete", "need_more": []}

<!-- part: empty_list_more -->
 Die allermeisten Abschnitte einer Publikation enthalten weder Titel noch DOI noch Autorenliste.

<!-- part: front_page -->
Eine Quelle ist davon ausgenommen: die Vorderseite. Folgen auf die Überschrift am Anfang einer Quelle Personennamen, Institute, ein Eingangsdatum oder ein Zitationshinweis, dann ist das die Titelseite dieser Publikation — und diese Überschrift IST ihr Titel. Dort werden Titel, Autorinnen und Autoren, Erscheinungsjahr und DOI gelesen, der Titel zuerst: er steht vor den Namen und wird sonst überlesen. Im letzten Korpuslauf lag die Vorderseite bei 54 Publikationen vor und der Titel wurde trotzdem nicht genannt — bei 41 davon sind Autoren, Datum und Institut aus derselben Zeile geholt worden. Diese 54 fehlen im Graphen vollständig.

Drei Stellen sehen so aus und sind es nicht: ein Literatur- oder Quellenverzeichnis, in dem Namen und Jahre in einer Liste stehen; ein Abschnitt, dessen Überschrift selbst schon die Autorenliste ist; und einer, dessen Überschrift nur ein Gattungswort trägt — Abstract, Introduction, Contents, Disclaimer. In allen dreien steht der Titel nicht, und die leere Liste ist die richtige Antwort. Der Titel ist die Zeile ÜBER den Namen, nie die Zeile MIT den Namen.

<!-- part: value_more -->
   FALSCH: aus "JRC" das ausgeschriebene "Joint Research Centre" machen, wenn nur "JRC" dasteht.
   FALSCH: "Keramidas K." zu "Kimon Keramidas" ergänzen.
   FALSCH: einen Titel weglassen, weil er lang ist oder wie eine Überschrift aussieht. Eine Überschrift ist genau die Form, in der ein Titel dasteht.

<!-- part: line_number_example -->
 („Horizon 311 2020“)

<!-- part: footnote_example -->
 („Riahi1,2*“)

<!-- part: quote_more -->
 Die Überschrift einer Quelle steht am Anfang ihres "text" und ist zitierbar wie jede andere Zeile.

<!-- part: per_value_text -->
Ein Eintrag je Wert. Eine Autorenliste mit sechs Namen ergibt sechs Einträge, jeder mit seinem eigenen kurzen Zitat: dem Namen, wie er dort steht, samt der Zeichen, die direkt daran hängen, also "Keywan Riahi1,2*" und nicht die ganze Namenszeile. Dasselbe gilt für Institute, Geldgeber und Projekte. Die ganze Liste in jedem Eintrag zu wiederholen, macht die Antwort so lang, dass sie abgeschnitten wird und alle Einträge verloren gehen. Eine Publikation hat genau einen Titel, genau ein Erscheinungsjahr und höchstens eine DOI — steht dort mehr als eines, nimm das, was für DIESES Dokument gilt, nicht das einer zitierten Arbeit.

<!-- part: citations_text -->
Zitate sind keine Fundstellen. Ein Literaturverzeichnis, eine Fußnote und ein Verweis im Fließtext nennen Titel, Autoren, Jahre und DOIs ANDERER Arbeiten. Aus solchen Stellen extrahierst du nichts. Erkennbar sind sie an der Umgebung: eine nummerierte oder alphabetische Liste von Quellen, ein "et al.", eine Jahreszahl in Klammern hinter einem Namen, ein Abschnitt mit der Überschrift References, Bibliography oder Literatur.
   Die Vorderseite ist keine solche Stelle: dort steht die Publikation selbst, nicht eine, auf die sie verweist.
   FALSCH: aus "as shown by Riahi et al. (2017)" das Jahr 2017 als Erscheinungsjahr melden.

<!-- part: choice_entries -->
 — bei der Region "global", "mehrere Regionen" und "andere Region"

<!-- part: choice_reason -->
: die Regionsliste kennt nur Länder, und die meisten Szenarien dieser Publikationen sind global

<!-- part: choice_more -->
Eine Quelle, die viele Länder aufzählt — eine Ländergruppe, ein Regionenschlüssel, ein Länderanhang — beschreibt EINEN Betrachtungsraum und nicht fünfzig. Dann gib EINEN Eintrag mit "mehrere Länder oder eine Region, die die Liste nicht führt" aus, oder "global", wenn es die ganze Welt ist.

<!-- part: choice_examples -->
FALSCH: "value": "Deutschland", wenn die Liste "Germany" führt.
   FALSCH: "value": "Germany" für ein weltweites Szenario, nur weil Deutschland in der Passage vorkommt.

<!-- part: partial_when -->
nur, wenn hier ein Wert steht, den du nicht abschreiben kannst, weil die Passage abbricht. Ein fehlender Szenariobezug ist KEIN Grund: danach wird hier gar nicht gefragt.

<!-- part: invent_figures -->
 Das gilt auch für Abbildungsbeschreibungen — was dort nicht steht, existiert nicht.

<!-- part: source_kinds -->
Textabschnitte, Tabellen (Markdown-Transkription) oder Abbildungsbeschreibungen
