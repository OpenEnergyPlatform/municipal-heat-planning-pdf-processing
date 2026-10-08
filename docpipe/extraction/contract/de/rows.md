---
required: [role, asked_afterwards, example_reply, partial_when]
optional: [example_more, completeness_example, empty_list_more, front_page, number_examples, value_more, unit_examples, unit_heading, line_number_example, footnote_example, quote_more, quote_lines, per_value_text, citations_text, choice_entries, choice_reason, choice_more, choice_examples, status_more, sandbox_more]
blocks: [source_kinds, quantities_units, quantities_choice, quantities_text, frame_keys, place_example_more, completeness, frame_empty, normal_case, no_guessing, place_front_page, value_text, value_number, unit_raw, source_every, quote_whole_row, quote_one_source, quote_narrow, quote_copy, quote_inner_numbers, examples_foreign, per_value, citations, choice, status_frame, invent_knowledge, invent_figures, invent_chart, sandbox]
omittable: [quantities_units, quantities_choice, quantities_text, frame_keys, place_example_more, completeness, frame_empty, normal_case, no_guessing, place_front_page, value_number, unit_raw, source_every, quote_whole_row, quote_one_source, quote_narrow, quote_copy, quote_inner_numbers, examples_foreign, per_value, citations, choice, status_frame, invent_knowledge, invent_chart, sandbox]
---
{{role}}

Deine Aufgabe in diesem Schritt ist EINE: jeden Wert der gesuchten Felder finden und die Passage zitieren, in der er steht. {{asked_afterwards}} Du musst hier nichts davon zuordnen und sollst es auch nicht.

Du bekommst ein JSON-Objekt mit diesen Feldern:

- "quantities": die gesuchten Felder, jedes mit Label und Beschreibung<!-- block: quantities_units -->, bei einem Zahlenfeld auch mit den akzeptierten Einheiten ("units_accepted")<!-- /block -->. Ein Wert gehört hierher, wenn er zu MINDESTENS EINEM davon passt. Welches es ist, entscheidest du hier nicht.<!-- block: quantities_choice --> Steht bei einem Feld "value_classes", ist die Antwort eine Auswahl aus dieser Liste und keine freie Formulierung.<!-- /block --><!-- block: quantities_text --> Ein Feld OHNE "units_accepted" ist ein Textfeld: sein Wert ist eine Bezeichnung aus dem Dokument, keine Zahl.<!-- /block -->
- "sources": MEHRERE Quellen aus DEMSELBEN Dokument, jede mit einer Kennung ("id": "Q1", "Q2", …) — <!-- block: source_kinds -->Tabellen (Markdown-Transkription), Textabschnitte oder Diagrammbeschreibungen<!-- /block -->.
<!-- block: frame_keys -->
- "frame" (optional): Szenario und Jahr DIESER Anfrage. Keine Frage an dich, sondern die Grenze. Eine Quelle gehört nur dann hierher, wenn sie dieses Szenario und dieses Jahr selbst nennt, in ihrem Titel, in einer Spalte oder im Text. Eine Tabelle eines anderen Jahres gehört NICHT hierher, auch nicht teilweise: sie wird in ihrer eigenen Anfrage geholt. Hat eine Tabelle mehrere Jahresspalten, gehört nur die Spalte des Frames hierher. Was aus einer Quelle kommt, die das Jahr des Frames nicht nennt, wird maschinell verworfen.
- "anchors" (optional): die Sätze, mit denen diese Quellen gesucht wurden. Sie sagen in den Wörtern des Dokuments, wonach diese Anfrage fragt.
<!-- /block -->
- "prior" (optional): Werte, die aus diesem Dokument schon geholt sind. Gib denselben Wert aus derselben Passage NICHT noch einmal aus.

Gib ausschließlich ein JSON-Objekt in dieser Form zurück, in EINER Zeile, OHNE Einrückung:

{{example_reply}}

<!-- block: place_example_more -->
{{example_more}}

<!-- /block -->
<!-- block: completeness -->
Ein Wert pro Eintrag, und innerhalb des Frames vollständig: JEDER Wert des Frames in JEDER Quelle, die zum Frame gehört, bekommt seinen Eintrag, jede Zeile einzeln. {{completeness_example}}

<!-- /block -->
Eine leere Liste {"tuples": []} ist das richtige Ergebnis, wenn <!-- block: frame_empty -->keine der Quellen zum Frame gehört oder <!-- /block -->keine der Quellen einen gesuchten Wert enthält<!-- block: normal_case --> — und das ist der Normalfall<!-- /block -->.{{empty_list_more}}<!-- block: no_guessing --> Rate nicht, nur weil gefragt wurde.<!-- /block -->

<!-- block: place_front_page -->
{{front_page}}

<!-- /block -->
Jeder Eintrag wird maschinell und wörtlich gegen die Quelle geprüft; was die Prüfung nicht besteht, wird verworfen. Deshalb gelten diese Regeln:

<!-- rule: value --> "value": <!-- block: value_text -->der gesuchte Wert, wörtlich aus der Quelle abgeschrieben. Ein Text muss ZEICHEN FÜR ZEICHEN in "quote" vorkommen. Nichts ergänzen, nichts vereinheitlichen, nichts übersetzen, nichts ausschreiben, was abgekürzt dasteht.<!-- /block --><!-- block: value_number --> Eine Zahl steht EXAKT wie gedruckt da, nur ohne Tausendertrennzeichen und mit Dezimalpunkt{{number_examples}}. Rechne NICHT im Kopf: weder addieren noch runden noch umrechnen. Eine im Kopf gerechnete Zahl hat keinen Beleg und wird verworfen.<!-- block: sandbox --> Wenn gerechnet werden MUSS, gibt es dafür die Sandbox, siehe Regel {{rule:sandbox}}.<!-- /block --><!-- /block -->
{{value_more}}

<!-- block: unit_raw -->
<!-- rule: unit_raw --> "unit_raw": die Einheit EXAKT so, wie sie in der Quelle steht, mit allem, was dazugehört{{unit_examples}}. Steht sie nur im Spaltenkopf, in einer Blocküberschrift{{unit_heading}} oder in der Caption, gilt sie für alle zugehörigen Zellen. Welcher Eintrag der Listen das ist, wird DANACH gefragt, mit eigenem Beleg; hier ordnest du nichts zu und rechnest nichts um. Die "units_accepted" sagen dir nur, welche Art von Zahl gesucht ist.
   Steht in der Quelle eine Einheit, die in keiner der Listen vorkommt, gib sie trotzdem wörtlich an.
   Nur Zahlen ganz ohne erkennbare Einheit lässt du weg. Bei einem Textfeld bleibt "unit_raw" leer — dort gibt es keine.

<!-- /block -->
<!-- rule: source --> "source": die Kennung der Quelle, in der der WERT steht — "Q1", "Q2" und so weiter. Das Feld entscheidet, gegen welchen Text dein "quote" geprüft wird.<!-- block: source_every --> JEDER Eintrag trägt "source".<!-- /block -->

<!-- rule: quote --> "quote": eine wörtliche, zusammenhängende Zeichenkette aus dem Text GENAU DIESER Quelle (mindestens {{min_quote_chars}} Zeichen), die den Wert EXAKT wie gedruckt enthält.<!-- block: quote_whole_row --> Bei einer Zahl in einer Tabelle ist das Stück, das sie trägt, die ganze Tabellenzeile.<!-- /block --><!-- block: quote_one_source --> Nicht aus zwei Quellen zusammensetzen.<!-- /block --><!-- block: quote_narrow --> Zitier nur das Stück, das DEINEN Wert trägt: den Satzteil, den Listeneintrag, die Tabellenzelle mit ihrer Beschriftung, nicht den ganzen Absatz und nicht die ganze Liste.<!-- /block --><!-- block: quote_inner_numbers --> Schreib es Zeichen für Zeichen ab, auch Zahlen, die mitten im Text stehen, etwa Zeilennummern eines Manuskripts{{line_number_example}} oder Fußnotenzeichen{{footnote_example}}: sie gehören zur Zeichenkette, und ohne sie steht das Zitat nicht in der Quelle.<!-- /block --><!-- block: quote_copy --> Zeichen für Zeichen kopieren, nichts umformatieren, nichts auslassen.<!-- /block --><!-- block: examples_foreign --> Die Namen und Zahlen in den Beispielen oben stammen aus einem anderen Dokument: übernimm sie nie, sondern nur, was in DIESEN Quellen steht.<!-- /block -->{{quote_more}}
{{quote_lines}}

<!-- block: per_value -->
<!-- rule: per_value --> {{per_value_text}}

<!-- /block -->
<!-- block: citations -->
<!-- rule: citations --> {{citations_text}}

<!-- /block -->
<!-- block: choice -->
<!-- rule: choice --> Auswahl statt Formulierung. Nennt der Parameter unter "value_classes" eine Liste, dann ist "value" GENAU einer der dort links stehenden Klassennamen, Zeichen für Zeichen. Die Liste rechts daneben zeigt Schreibweisen, unter denen dieselbe Klasse in Texten auftaucht — sie ist eine Lesehilfe, keine Antwortmöglichkeit. Was das Dokument an der Stelle wörtlich schreibt, kommt zusätzlich nach "value_raw".
   Für diese Felder gilt Regel {{rule:value}} nicht: "value" muss NICHT in der "quote" vorkommen. Das gilt aber NUR, wenn du "value_raw" füllst — daran erkennt die Prüfung, dass "value" eine Wahl aus der Liste ist und kein abgeschriebener Text. "value_raw" ist deshalb bei JEDER Auswahlantwort Pflicht, auch bei einer, die genau passt.
   Manche Listen führen Einträge, die ausdrücklich KEINE Klasse sind, sondern sagen, dass keine passt{{choice_entries}}. Trifft einer davon zu, dann WÄHLE IHN. Das ist die richtige Antwort und keine Notlösung{{choice_reason}}.
   {{choice_more}}
   Passt weder eine Klasse noch einer dieser Einträge, lässt du "value" weg und füllst nur "value_raw".
   {{choice_examples}}

<!-- /block -->
<!-- rule: status --> "status" und "need_more":
   - "complete": alles, was diese Quellen zu den gesuchten Feldern hergeben, steht in "tuples"<!-- block: status_frame -->, innerhalb des Frames<!-- /block -->. Auch dann, wenn "tuples" leer ist. Das ist der Normalfall.
   - "partial": {{partial_when}}
   - "need_more": bei "partial" ein bis drei Sätze, nach denen gesucht werden soll, wie sie im Dokument STEHEN würden. Kein Stichwort.
{{status_more}}

<!-- block: sandbox -->
<!-- rule: sandbox --> Rechnen lassen statt rechnen. Steht der gesuchte Wert nicht gedruckt da, sondern ergibt sich erst aus gedruckten Zahlen, dann gib STATT der Einträge EIN Aktions-Objekt zurück:
   {"action": "python", "code": "<Python-Code>"}
   Verfügbar sind numpy und pandas, die Quelltexte liegen als Dictionary `sources` vor (Schlüssel "Q1", "Q2", …), der Titel als `title`. Gib jedes Ergebnis mit print() aus. Du bekommst die Ausgabe zurück und antwortest DANN mit den Einträgen.
{{sandbox_more}}
   Jeder so entstandene Eintrag trägt "computed": true, sein "quote" ist die Passage mit den EINGANGSZAHLEN.

<!-- /block -->
<!-- rule: invent --> Nichts erfinden: nur Werte, die wörtlich in einer der Quellen stehen.<!-- block: invent_knowledge --> Was du aus Vorwissen über das Dokument ergänzen müsstest, gehört nicht in die Liste.<!-- /block --><!-- block: invent_figures --> Das gilt auch für Diagrammbeschreibungen — was dort nicht beziffert ist, existiert nicht.<!-- /block --><!-- block: invent_chart --> Eine Zahl, die du nur im Bild eines Diagramms abliest, steht in keinem Text, den dein "quote" zitieren kann, und wird verworfen: lass sie weg.<!-- /block -->
