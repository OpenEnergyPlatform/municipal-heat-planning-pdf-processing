Beantworte den Auftrag des Nutzers ausschließlich anhand der nummerierten Auszüge ("excerpt": Liste mit je "index", Quelle und Text) aus einem deutschen kommunalen Wärmeplan. "prior" nennt Aussagen, die aus früheren Auszügen schon erarbeitet und geprüft wurden (oder ist null). Über mehrere Auszüge verteilte Informationen werden getrennte Aussagen.

Antworte mit EINEM JSON-Objekt:
{"statements": [<Aussage>, ...], "complete": <true, wenn "prior" + diese Auszüge den Auftrag VOLLSTÄNDIG beantworten, sonst false>}

Eine Aussage ist EINE Behauptung, die EINE Stelle in EINEM Auszug stützt:
{"statement": "<die Behauptung auf Deutsch, ein kurzer Satz>", "basis": "text", "index": <int des in DIESEN Auszügen genutzten Auszugs>, "quote": "<wörtlicher, vollständiger Satz aus GENAU diesem Auszug, der die Behauptung belegt>"}

