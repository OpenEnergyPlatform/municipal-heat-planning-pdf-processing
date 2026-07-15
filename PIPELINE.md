# KWP PDF-Processing-Pipeline – Zusammenfassung

**Felix Vossel, 14.04.2026**

---

## Überblick

Die Pipeline baut aus kommunalen Wärmeplänen (Roh-PDFs) eine semantisch durchsuchbare Wissensbasis auf, um die Entwicklung der MHPO zu unterstützen. Sie besteht aus **fünf Modulen** (`fileprocessing` → `preprocessing` → `textrefinement` → `imageprocessing` → `chunkingandembedding`), auf die sich sechs logische Verarbeitungsstufen verteilen (`preprocessing` umfasst Layout-Erkennung und Strukturaufbau). Ergebnis sind strukturierte Daten, angereicherte Metadaten und multimodale Embeddings in einem FAISS-Index.

Alle KI-Modelle laufen lokal – die LLM- und Vision-Language-Stufen über **vLLM** (OpenAI-kompatibler Server), das Embedding direkt über HuggingFace Transformers.

---

## Pipeline-Architektur

### Stufe 1 – Dateiverwaltung (`fileprocessing`)

Ausgangspunkt ist die Excel-Tabelle der KWW mit den Metadaten aller veröffentlichten Wärmepläne: Gemeindename, Organisationseinheit, Bundesland, Veröffentlichungsdatum und PDF-Download-Link. Für jeden abgeschlossenen Wärmeplan mit gültigem PDF-Link lädt die Pipeline das Dokument herunter, extrahiert die Seitenanzahl und legt Dokument-, Organisations- und Gemeindeeinträge in einer SQLite-Datenbank an.

### Stufe 2 – Layout-Erkennung (`preprocessing`)

Jede PDF-Seite wird als hochauflösendes PNG gerendert und von **PP-DocLayoutV3** analysiert. Das Modell klassifiziert die Struktur jeder Seite – Tabellen, Abbildungen, Überschriften, Textblöcke, Kopf-/Fußzeilen, Seitenzahlen, Bildunterschriften – jeweils mit Bounding Box und Confidence Score.

### Stufe 3 – Textextraktion und Strukturaufbau (`preprocessing`)

PyMuPDF extrahiert Text auf Zeichenebene; der Rohtext wird mit den Layout-Ergebnissen aus Stufe 2 abgeglichen und zu einer strukturierten JSON-Repräsentation des Dokuments zusammengebaut.

Jedes Dokument wird in Abschnitte mit Titel, Seitenzahl, Textinhalt und Referenzen auf Tabellen/Abbildungen zerlegt. Tabellen und Abbildungen werden anhand ihrer Bounding Boxes aus den Seitenbildern ausgeschnitten und als PNG gespeichert; Platzhalter-Tokens (z.B. `[p13_tbl0]`) halten die Lesereihenfolge im Abschnittstext aufrecht. Kopf-/Fußzeilen, Firmentitel und Texte aus Tabellen oder Bildern werden über die Bounding Boxes entfernt, sodass Abschnitte nur noch Fließtext enthalten.

Ausgabe: `structured_output.json` pro PDF.

### Stufe 4 – LLM-Verfeinerung (`textrefinement`)

Deterministisch erkennbare Fälle (wiederkehrende Kopf-/Fußzeilen, Verzeichnislisten, Titel-Normalisierung) werden bereits in `preprocessing` bereinigt; den Rest übernimmt **Qwen3.5-122B-A10B-FP8** über vLLM.

Das Modell normalisiert Abschnittstitel, korrigiert oder ergänzt fehlende Bildunterschriften, entfernt verbleibende Verzeichnisseiten und konvertiert Literaturverzeichnisse ins BibTeX-Format. Es operiert in gleitenden Fenstern auf dem Abschnittskontext (inkl. Vorgänger-Kontext für fensterübergreifende Merges) und kann Abschnitte zusammenführen, aufteilen, entfernen oder ersetzen.

Ausgabe: `structured_output_final.json`.

### Stufe 5 – Bildverarbeitung (`imageprocessing`)

Dasselbe Qwen3.5-122B-A10B-FP8-Modell wie in Stufe 4 reichert jedes visuelle Element über seine Vision-Language-Fähigkeiten an – allerdings über eine **eigene** vLLM-Serverinstanz. Die Stufe läuft parallel zu Stufe 4, muss aber vor Stufe 6 abgeschlossen sein.

Für **Tabellen** entsteht eine strukturierte Markdown-Transkription, für **Abbildungen** eine textuelle Beschreibung; fehlende Bildunterschriften werden aus Bildinhalt und umgebendem Kontext erzeugt. Ein Retry-Mechanismus mit Konversations-Feedback behandelt JSON-Parse-Fehler, ein QA-Gate (Coverage-/Dedup-Check mit gezieltem Retry) sichert die Tabellenextraktion ab. Elemente ohne Markdown bzw. Beschreibung behalten ihr Vision-Language-Embedding und verlieren lediglich das Text-Embedding.

Ausgabe: `structured_output_images.json`.

### Stufe 6 – Chunking, Embedding und Datenbankpopulation (`chunkingandembedding`)

**Schritt 1 – Merge:** Die Abschnittsstruktur aus Stufe 4 dient als Basis; Tabellen und Abbildungen werden per ID-Matching mit den angereicherten Versionen aus Stufe 5 zusammengeführt. Ergebnis: `output.json`.

**Schritt 2 – Datenbankpopulation:** Abschnitte, Tabellen und Bilder werden mit Fremdschlüssel-Referenzen auf die bestehenden Dokumenteinträge in die SQLite-Datenbank eingetragen.

**Schritt 3 – Embedding-Erstellung:** Sechs Embedding-Typen, erzeugt mit **Qwen3-VL-Embedding-8B** (4096-dimensionale Vektoren) über HuggingFace Transformers in bfloat16, datenparallel (eine Modell-Replica pro GPU). Die Eingaben aller Dokumente werden gesammelt und in dokumentübergreifenden Batches verarbeitet:

| Embedding-Typ | Inhalt | DB-Spalte |
|---|---|---|
| `section_text` | Titel + vollständiger Abschnittsinhalt (Platzhalter ersetzt durch Tabellen-Markdown / Abbildungsbeschreibungen) | Sections.text_embedding |
| `section_title` | Abschnittstitel einzeln | Sections.title_embedding |
| `table_text` | Tabelltitel + Markdown-Transkription | Tables.text_embedding |
| `table_vl` | Tabellenbild + Tabellentitel + Markdown (Vision-Language-Embedding) | Tables.image_embedding |
| `figure_text` | Bildunterschrift + textuelle Beschreibung | Images.text_embedding |
| `figure_vl` | Abbildungsbild + Bildunterschrift + Beschreibung (Vision-Language-Embedding) | Images.image_embedding |

Alle Embeddings werden L2-normalisiert und in einem globalen FAISS-Index gespeichert. Die Datenbank ist die Single Source of Truth dafür, welche Elemente bereits embedded sind – bei Wiederholungsläufen werden nur fehlende Embeddings erstellt.

---

## Genutzte Modelle und Bibliotheken

### Modelle

| Modell | Anbieter | Parameter | Einsatz |
|---|---|---|---|
| PP-DocLayoutV3 | PaddlePaddle | — | Layout-Erkennung (Stufe 2) |
| Qwen3.5-122B-A10B-FP8 | Alibaba / Qwen | 122B MoE (FP8) | LLM-Verfeinerung **und** Bildverarbeitung (Stufen 4 & 5), via vLLM |
| Qwen3-VL-Embedding-8B | Alibaba / Qwen | 8B | Multimodales Embedding (Stufe 6) |

### Zentrale Bibliotheken

| Bibliothek | Zweck |
|---|---|
| PyMuPDF (fitz) | PDF-Textextraktion und Seitenrendering |
| Transformers | Modellbetrieb für Layout-Erkennung und Embedding |
| vLLM | Inference-Runtime (OpenAI-kompatibel) für LLM und VLM |
| FAISS | Vektorsuchindex für semantische Suche |
| SQLite | Metadaten- und Embedding-ID-Speicherung |
| spaCy | NLP-Verarbeitung und Entitätserkennung |

---

## Offene Punkte zur Diskussion

- Gibt es zusätzliche Metadatenfelder oder Strukturelemente, die wir extrahieren sollten?
- Sollten wir alternative Chunking-Strategien jenseits von Abschnitts-Level-Chunks in Betracht ziehen?
- Gibt es bestimmte Abfragemuster oder Suchszenarien, für die wir die Embedding-Strategie optimieren sollten?
