---
temperature: 0.1
max_tokens: 4096
---
You transcribe one page of a German municipal heat plan ("Kommunale Wärmeplanung") that has no text layer; its text can only be read from the rendered page image. Read the page, nothing more: do not improve, shorten, explain or summarise it. A later stage does the cleanup and can only work on what you read.

1. Vollständigkeit: jeder Fließtext der Seite in Leserichtung; bei mehrspaltigem Satz zuerst die linke Spalte vollständig, dann die rechte.
2. Wörtlich: Wortlaut, Rechtschreibung, Zahlen, Einheiten und Schreibweisen exakt wie auf der Seite. Korrigiere nichts, auch keine offensichtlichen Fehler; erfinde nichts.
3. Überschriften als Markdown-Überschrift mit der Ebene, die die Seite nahelegt (`#` Kapitel, `##` Abschnitt, `###` darunter); vorhandene Nummerierung bleibt Teil der Überschrift ("## 3.2 Bestandsanalyse").
4. Absätze durch eine Leerzeile trennen. Trennstriche am Zeilenende zusammenführen ("Wärme-\nplanung" wird "Wärmeplanung"), Zeilenumbrüche innerhalb eines Absatzes nicht übernehmen.
5. Aufzählungen als Markdown-Liste (`- ` beziehungsweise `1. `).
6. Tabellen und Abbildungen nicht transkribieren; sie werden separat aus ihrem eigenen Bildausschnitt gelesen. Lass sie aus und schreibe nichts an ihre Stelle, keine Beschreibung, keinen Platzhalter. Eine Beschriftung wie "Abbildung 12: Wärmedichte" ist Text und wird übernommen.
7. Kopf- und Fußzeilen weglassen: Seitenzahlen, Dokumenttitel in der Kopfzeile, Bürologos, Dateipfade, Datumsstempel am Seitenrand. Auf der Titelseite sind Herausgeber, Datum und Copyright-Zeile Teil des Dokuments und werden übernommen.
8. Eine Seite ohne lesbaren Fließtext (etwa eine ganzseitige Karte) ergibt einen leeren String. Das ist ein zulässiges Ergebnis und besser als ein erfundenes.
9. Schreibe nichts über deine eigene Arbeit: keine Einleitung, keine Anmerkung, keine Entschuldigung für Unlesbares.

Reply with ONLY one JSON object, no fences, no other text, with exactly one key:
{"markdown": "the page text as described above, or an empty string if the page has no readable running text"}
