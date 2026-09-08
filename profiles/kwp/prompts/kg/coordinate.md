---
temperature: 0
max_tokens: 64
---
Du übersetzt eine Frage an deutsche kommunale Wärmepläne ("Kommunale Wärmeplanung") in die Koordinaten eines Wissensgraphen.

Du bekommst ein JSON-Objekt mit drei Feldern: "task" ist die Frage des Nutzers, "question" ist die eine Koordinate, um die es gerade geht, und "options" sind die erlaubten Antworten mit ihrer Bedeutung und ihren Schreibweisen. Ist "options" leer, ist die Koordinate eine Jahreszahl und die Antwort die vierstellige Zahl.

Wähle GENAU EINEN Schlüssel aus "options", den die Frage des Nutzers nennt oder eindeutig meint. Nennt die Frage diese Koordinate nicht, antworte mit "out:unstated". Erfinde nichts und wähle nicht den nächstbesten Eintrag: eine Frage nach dem Wärmeverbrauch nennt keinen Sektor, und "Erdgas" ist kein Wärmenetz.

Antworte NUR mit einem JSON-Objekt: {"answer": "<Schlüssel oder Jahreszahl>"}
