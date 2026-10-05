"""
inference.py – What the answer loop says around the kwp prompts.

German, like the plans and like the answers. See docpipe/inference/wording.py
for what each piece is used for.

Author: Felix Vossel
"""

# Why the graph route did not answer, one sentence per reason token of
# docpipe.inference.kg_route.REASONS. Held against that tuple by
# kg_route.hooks, which the app builds at start-up, so a token nobody worded
# is a finding before the first turn and not a blank caption once in a
# thousand turns. Not at import, the way kg.py checks TRUST_PROSE: the check
# lives in docpipe.inference, and importing that package imports openai and
# faiss -- a table of six sentences should not need either to load.
ROUTE_NOTES = {
    "no_graph": "Kein Wissensgraph geladen.",
    "no_plan": ("Dieser Plan hat keinen Knoten im Wissensgraphen: ohne AGS "
                "und Veröffentlichungsdatum wird keiner geprägt."),
    "no_coordinates": ("Die Frage nennt weder eine Größe noch ein Szenario "
                       "noch ein Jahr, nach denen der Graph gefragt werden "
                       "könnte."),
    "no_rows": "Der Wissensgraph hat zu diesen Koordinaten keinen Wert.",
    "no_trust": ("Ein gefundener Wert trägt keine Vertrauenszeile, deshalb "
                 "wird aus dem Graphen nichts angezeigt."),
}

READOFF_MARKER = "abgelesen"
READOFF_NOTE = ("(Hinweis: Werte teilweise aus Abbildungen abgelesen "
                "– Schätzwerte, Ablesefehler möglich.)")

PHRASES = {
    "task_heading": "Auftrag des Nutzers",
    "history_heading": ("Bisheriger Gesprächsverlauf (nutze ihn NUR, um Bezüge im "
                        "aktuellen Auftrag aufzulösen — Pronomen, \"und …\", "
                        "Auslassungen; KEINE Faktenquelle, Belege ausschließlich "
                        "aus den Auszügen)"),
    "history_task": "Frage",
    "history_phrase": "Suchanker",
    "history_answer": "Antwort",

    "empty_reply": "Deine Antwort war leer. Antworte mit gültigem JSON.",
    "parse_error": "Parse-Fehler: {error}. Antworte mit NUR einem gültigen JSON-Objekt.",

    "code_heading": "Ausgeführter Code",
    "exec_stdout": "Ausführungsergebnis (stdout)",
    "exec_empty": "(keine Ausgabe)",
    "exec_failed": "Ausführung fehlgeschlagen",
    "exec_unknown": "unbekannter Fehler",
    "exec_recover": "Korrigiere den Code ODER antworte ohne Berechnung.",

    "compute_heading": "Bereits ausgeführt",
    "compute_guide": ("Gib die finale Antwort im vorgegebenen JSON-Format — oder, nur "
                      "falls unbedingt nötig, eine weitere "
                      '{"action":"python","code":...}.'),
    "compute_guide_final": ("Gib JETZT die finale Antwort im vorgegebenen JSON-Format "
                            "(KEIN action-Objekt mehr)."),

    "image_heading": "Angeforderte Abbildungen (siehe Bilder)",
    "image_uncaptioned": "ohne Bildunterschrift",
    "image_unavailable": "Bild nicht verfügbar",
    "image_guide": ("Lies den Wert aus dem Bild ab und gib die finale Antwort — oder, "
                    'nur falls wirklich nötig, eine weitere {"action":"image","id":"..."}.'),
    "image_guide_final": ("Gib JETZT die finale Antwort im vorgegebenen JSON-Format "
                          "(KEIN action-Objekt mehr)."),
    "image_part": "Bild zum Auszug index={index}",

    "readoff_heading": "Abzulesen (laut Vorprüfung)",

    # The citation under the answer, which the model also reads as `source`.
    "citation_quotes": ("„", "“"),
    "citation_page": "Seite {page}",
    "citation_page_unknown": "Seite unbekannt",
    "citation_section": "Abschnitt",
    "citation_table": "Tabelle",
    "citation_figure": "Abbildung",

    # What the loop splices into a reading, a failed run and an image part.
    "readoff_value": "{reading} — abgelesener Wert: {value} {unit}",
    "exec_none": "kein Ergebnis",
    "image_requested": "Angefordertes Bild [{id}]: {title}",
}


# The words of the chat app's pages (docpipe/app/app.py) and of the picker's
# labels (docpipe/inference/catalog.py): what a person reads and clicks. Every
# key is used there, and `wording.UI_REQUIRED` lists them.
UI = {
    "title_fallback": "docpipe – Recherche",
    "page_chat": "Recherche",
    "page_review": "Werte prüfen",
    "selection": "Auswahl",
    "include_old": "Historische Versionen einbeziehen",
    "no_documents": "Keine Dokumente in der Datenbank gefunden.",
    "no_match": "Kein Dokument passt zu dieser Filterauswahl.",
    "whole_corpus": "Im ganzen Korpus suchen",
    "whole_corpus_help": ("Die Frage geht an alle aktuellen Dokumente "
                          "zugleich; jede Quelle nennt ihr Dokument. Die "
                          "belegten Werte darüber kommen aus allen "
                          "ausgewerteten Dokumenten, auch aus älteren "
                          "Fassungen."),
    "compare_help": ("Mehrere Auswahlen: dieselbe Frage geht an jeden Plan "
                     "einzeln, danach werden nur die Antworten verglichen."),
    "choose_one": "Bitte mindestens ein {noun} wählen.",
    "scopes": "Suchbereich",
    "scopes_help": ("Tabellen/Bilder liegen doppelt im Index: „Bild + "
                    "Beschreibung“ durchsucht das eingebettete Bild samt "
                    "Beschreibung, „nur Beschreibung“ nur den "
                    "Caption-/Beschreibungstext ohne das Bild."),
    "format": "Antwortformat",
    "format_prose": "Fließtext",
    "stub_mode": "LLM_STUB_MODE aktiv – Antworten sind Platzhalter.",
    "anchor": "🔎 Suchanker (Embedding-Phrase): {phrase}",
    "image_upload": "Optionales Bild zur Anfrage",
    "image_mode": "Bild fürs Retrieval verwenden als",
    "image_and_text": "Bild + Text",
    "image_only": "Nur Bild",
    "chat_input": "Extraktionsauftrag …",
    "choose_scope": "Bitte mindestens einen Suchbereich wählen.",
    "with_image": "_(mit Bild)_",
    "preparing": "Vorbereiten",
    "recheck": ("🔁 Wiederholungssuche – {n} bereits geprüfte Quellen "
                "übersprungen"),
    "all_examined": "Alle passenden Quellen wurden bereits geprüft.",
    "no_hits": "Keine Treffer im gewählten Suchbereich.",
    "nothing_backed": ("In den geprüften Quellen wurde keine belegbare "
                       "Information zum Auftrag gefunden."),
    "no_answer_context": "(keine belegte Antwort gefunden)",
    "compare_dropped": "Nicht abgefragt (Obergrenze {limit}): {names}",
    "compare_note": ("⚖️ Vergleich der Antworten, ohne eigene Quellen — die "
                     "Belege stehen bei den einzelnen Antworten."),
    "compare_too_few": "Zu wenige belegte Antworten für einen Vergleich.",
    "compare_failed": ("Der Vergleich konnte nicht erzeugt werden; die "
                       "Antworten der einzelnen Pläne stehen unten."),
    "column_document": "Plan",
    "column_answer": "Antwort",
    "column_citations": "Belege",
    "document_nothing": "Keine belegbare Information in diesem Plan gefunden.",
    "show_evidence": "Beleg anzeigen",
    "show_compute": "🧮 Berechnung anzeigen ({n}×)",
    "compute_no_output": "(keine Ausgabe)",
    "compute_error": "Fehler: {error}",
    "read_off": ("📷 Aus der Abbildung abgelesen – Schätzwert, Ablesefehler "
                 "möglich"),
    "open_pdf": "📄 Seite {page} im PDF öffnen",
    "show_context": "Kontext anzeigen",
    "show_page": "Seite {page} anzeigen",
    "page_not_located": ("Das Zitat konnte auf dieser Seite nicht lokalisiert "
                         "werden, es ist nichts markiert."),
    "page_no_file": ("{file} liegt nicht im PDF-Ordner dieses Servers, die "
                     "Seite kann deshalb nicht gezeigt werden."),
    "page_failed_library": ("Seite {page} konnte nicht gezeigt werden: PyMuPDF "
                            "ist auf diesem Server nicht installiert."),
    "page_failed_open": ("Seite {page} konnte nicht gezeigt werden: das PDF "
                         "lässt sich nicht öffnen."),
    "page_failed_range": ("Seite {page} konnte nicht gezeigt werden: das PDF "
                          "hat diese Seite nicht."),
    "page_failed_draw": ("Seite {page} konnte nicht gezeigt werden: sie ließ "
                         "sich nicht darstellen."),
    "download_pdf": "PDF herunterladen",
    "no_profile": ("Es ist kein Profil benannt, deshalb läuft der Chat mit "
                   "dem eingebauten Profil `default`: englische Prompts und "
                   "Texte, die für jeden Ordner passen. Für ein anderes "
                   "starten Sie den Chat mit `docpipe --profile <name> chat` "
                   "oder setzen Sie `profile = \"<name>\"` in der "
                   "docpipe.toml oder DOCPIPE_PROFILE."),
    "values_heading": "Belegte Werte aus der Auswertung der Dokumente",
    "values_note": ("Diese Zahlen wurden vorab aus den Dokumenten gelesen "
                    "und mit Zitat geprüft; sie stammen nicht aus der "
                    "Antwort unten."),
    "values_more": "{shown} von {total} Werten gezeigt.",
    "values_level": "Stufe {level}",
    "index_model_differs": ("Der Index wurde mit {built} aufgebaut, Fragen "
                            "werden mit {queried} eingebettet: die Vektoren "
                            "sind nicht vergleichbar, Treffer können falsch "
                            "sein."),
    "review_heading": "Gelesene Werte prüfen",
    "review_intro": ("Entscheiden Sie für jeden Wert, Feld für Feld, ob das "
                     "Dokument das so sagt. Die Entscheidungen werden in "
                     "einer eigenen Datei abgelegt und sind die Grundlage "
                     "für die Auswertung der Genauigkeit."),
    "review_no_harvest": ("Es ist keine Auswertung eingestellt "
                          "(INFERENCE_HARVEST_DIR)."),
    "review_by": "Ihr Name oder Kürzel",
    "review_by_missing": ("Bitte zuerst einen Namen eintragen: eine "
                          "Entscheidung ohne Namen lässt sich später nicht "
                          "zuordnen."),
    "review_progress": "{open} Werte offen.",
    "review_none_open": "Für diese Auswahl ist kein Wert mehr offen.",
    "review_parameter_filter": "Größe",
    "review_all_parameters": "Alle",
    "review_value": "Wert",
    "review_field": "Feld „{field}“: {content}",
    "review_open": "offen lassen",
    "review_correct": "stimmt",
    "review_wrong": "stimmt nicht",
    "review_expected": "Richtig wäre (optional)",
    "review_note": "Anmerkung (optional)",
    "review_save": "Speichern und weiter",
    "review_skip": "Überspringen",
    "review_nothing_decided": "Es wurde kein Feld entschieden.",
    "review_saved": "{n} Entscheidung(en) gespeichert.",
    "review_missing_heading": "Ein Wert fehlt",
    "review_missing_intro": (
        "Das Dokument nennt einen Wert, den die Auswertung nicht enthält."),
    "review_missing_document": "Dokument",
    "review_missing_parameter": "Größe",
    "review_missing_value": "Wert",
    "review_missing_unit": "Einheit (optional)",
    "review_missing_quote": "Wortlaut im Dokument",
    "review_missing_page": "Seite (optional)",
    "review_missing_save": "Fehlenden Wert eintragen",
    "review_missing_needs": "Dokument, Größe und Wert werden gebraucht.",
    "review_checked_heading": "Dokument ganz gelesen",
    "review_checked_intro": (
        "Nur für Dokumente, die jemand für eine Größe ganz gelesen hat, "
        "lässt sich sagen, was der Auswertung fehlt."),
    "review_checked_save": "Als ganz gelesen eintragen",
    "review_checked_all": "für alle Größen",
    "version_current": "(aktuell)",
    "version_old": "(alt)",
    "document_noun_fallback": "Dokument",
}
