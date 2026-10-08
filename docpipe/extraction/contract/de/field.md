---
# The sentence about what is found stands twice, at the end of
# by_similarity and in found_next: a profile keeps the place where it
# said it and leaves the other out.
required: [subject, groups_note, value_raw_is, example_reply]
optional: [rows_more, value_raw_more, quote_more, domain_rule_1, domain_rule_2, need_more_example, base_years_rule, target_years_rule]
blocks: [rows_carry, unstated_when, base_years, target_years, rows_source, same_forms, year_value, domain_slot_1, domain_slot_2, no_guessing, closed_out, closed_out_text, by_meaning, by_similarity, found_next]
omittable: [base_years, target_years, rows_source, same_forms, year_value, domain_slot_1, domain_slot_2, no_guessing, closed_out, by_meaning, by_similarity, found_next]
---
Du bestimmst EINE Angabe zu {{subject}}. Die Werte stehen fest: du fügst keine hinzu und lässt keine weg. Gefragt ist GENAU EIN Feld, und du beantwortest und belegst es für jeden Wert.

Du bekommst zuerst ein JSON-Objekt mit "sources", danach die Bilder dazu, zuletzt ein JSON-Objekt mit "rows" und "fields":

- "sources": Quellen aus DEMSELBEN Dokument, je mit Kennung ("id": "Q1", "Q2", …): die Texte, aus denen die Werte stammen.
- "rows": <!-- block: rows_carry -->die Werte, je mit Kennung ("id": "R1", "R2", …), Quelle, Wert, Einheit und Passage.<!-- /block --> Aus einer Tabellenzeile dazu "column": ihre Zelle in der Zeile, von "columns" Zellen, ausgezählt, nicht geraten.
{{rows_more}}
<!-- block: rows_source -->
Steht die eigene Quelle der Zeile unter den gezeigten, nennt "source" ihre Kennung.
<!-- /block -->
- "fields": das gesuchte Feld, eine Liste mit genau einem Eintrag: "name", "question" und, bei einer geschlossenen Liste, "options" (je Eintrag ein Name und die Schreibweisen, unter denen er im Korpus schon vorkam).
<!-- block: base_years -->
- "base_years" (nur bei der Frage nach dem Jahr, und nur wenn das Dokument sie nennt): die Jahre, für die das Dokument seinen eigenen Stand erhoben oder bilanziert hat, je mit dem Zitat, das die Jahreszahl druckt. Regel {{rule:need_more}} sagt, wie du sie benutzt.
<!-- /block -->
<!-- block: target_years -->
- "target_years" (nur bei der Frage nach dem Jahr, und nur wenn das Dokument sie nennt): die Jahre, die das Dokument für sein Ziel nennt, je mit dem Zitat, das die Jahreszahl druckt. Regel {{rule:need_more}} sagt, wie du sie benutzt.
<!-- /block -->

Gib ausschließlich ein JSON-Objekt in dieser Form zurück, in EINER Zeile, OHNE Einrückung:

{{example_reply}}

Unter "fields" steht genau ein Schlüssel: der "name" des gefragten Feldes. Fehlt er, gilt das Feld als nicht beantwortet und wird noch einmal gefragt.<!-- block: same_forms --> Beide Formen bedeuten dasselbe.<!-- /block --> "groups" ist der Normalfall: {{groups_note}} "answers" ist für Zeilen, die aus der Reihe fallen. Steht eine Zeile in beiden, gilt "answers".

Regeln:

<!-- rule: value --> "value": die Antwort. Gibt es "options", genau EIN Name daraus, Zeichen für Zeichen abgeschrieben, nichts Eigenes, nichts Zusammengesetztes.<!-- block: year_value --> Ist "field.name" gleich "year", die vierstellige Jahreszahl als Zahl ohne Anführungszeichen.<!-- /block --> Sonst die Bezeichnung wörtlich aus der Quelle.

<!-- rule: value_raw --> "value_raw": IMMER zusätzlich {{value_raw_is}}. Daran wird deine Zuordnung geprüft.<!-- block: year_value --> Bei "year" darf es fehlen.<!-- /block -->
{{value_raw_more}}

<!-- rule: quote --> "quote": eine wörtliche, zusammenhängende Zeichenkette aus EINER der gezeigten Quellen (mindestens {{min_quote_chars}} Zeichen), Zeichen für Zeichen kopiert, und "value_raw" steht darin.
{{quote_more}}

<!-- block: domain_slot_1 -->
<!-- rule: domain_1 --> {{domain_rule_1}}

<!-- /block -->
<!-- block: domain_slot_2 -->
<!-- rule: domain_2 --> {{domain_rule_2}}

<!-- /block -->
<!-- rule: every_row --> JEDE Zeile bekommt eine Antwort; Auslassen zählt als Fehler. <!-- block: unstated_when -->Steht die Angabe in KEINER der gezeigten Quellen<!-- /block -->, antworte für diese Zeile "value": "{{unstated}}", ohne "quote" und "value_raw". Das ist eine richtige Antwort und heißt "{{unstated_means}}"; du bekommst die Zeile danach mit ANDEREN Passagen desselben Dokuments noch einmal.<!-- block: no_guessing --> Rate nicht und ergänze nichts aus Weltwissen.<!-- /block --> Eine falsche Angabe ist schlimmer als "{{unstated}}".

<!-- block: closed_out -->
<!-- rule: closed_out --> <!-- block: closed_out_text -->Enthält "options" Einträge, die ausdrücklich das Gegenteil einer Klasse sind, sind das richtige Antworten und keine Notlösung. Wähle sie. Regel {{rule:quote}} gilt auch für sie: dein "quote" trägt das Wort, das "value_raw" nennt. Steht kein solches Wort in den Quellen und ist die Eigenschaft nur aus dem Zusammenhang zu erschließen, antworte "{{unstated}}", statt eine Stelle zu zitieren, die die Angabe nicht trägt. Passt fachlich weder eine Klasse noch einer dieser Einträge, obwohl die Passage die Angabe nennt, gib die Bezeichnung in "value_raw" und lass "value" weg.<!-- /block -->

<!-- /block -->
<!-- block: by_meaning -->
<!-- rule: by_meaning --> Entscheide nach der Bedeutung, nicht nach der Ähnlichkeit der Wörter. Trägt ein Eintrag ein "{{option_means}}", ist das die Definition der Klasse aus der Ontologie, und sie entscheidet. Die "{{option_spellings}}" sind nur Beispiele, wie der Eintrag im Korpus schon dastand: eine passende macht ihn nicht richtig, eine fehlende nicht falsch. Passt eine Bezeichnung zu keiner Definition, nimm nicht die nächstbeste: dafür gibt es die Einträge, die mit "out:" beginnen, und "{{unstated}}".

<!-- /block -->
<!-- rule: need_more --> <!-- block: base_years -->Das Jahr, und <!-- /block -->"need_more". Bekommst du die Angabe aus diesen Passagen nicht, kannst du in "need_more" ein bis drei Sätze angeben, nach denen gesucht werden soll, so, wie sie im Dokument STEHEN würden.<!-- block: by_similarity --> Danach wird per Ähnlichkeit gesucht. Was gefunden wird, kommt als nächste Anfrage mit denselben Zeilen.<!-- /block -->
{{need_more_example}}
<!-- block: found_next -->
Was gefunden wird, kommt als nächste Anfrage mit denselben Zeilen.
<!-- /block -->
<!-- block: base_years -->
{{base_years_rule}}
<!-- /block -->
<!-- block: target_years -->
{{target_years_rule}}
<!-- /block -->

<!-- rule: corrections --> "corrections" (nur bei einer Wiederholung): deine vorige Antwort für die genannten Zeilen war nicht belegbar, und der Grund steht dabei. Antworte für GENAU diese Zeilen neu: zitier eine andere Stelle, oder antworte "{{unstated}}", wenn die Angabe in den gezeigten Passagen wirklich nicht steht. Dieselbe Antwort noch einmal fällt genauso durch.
