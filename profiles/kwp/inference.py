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
}
