"""
stage_chunks.py: the rules of stage 6 (pieces and vectors), the decisions the stage
used to hold as fixed values in its code (owner request 2026-11-19, A1:
"Die festen Werte werden Regeln mit dem heutigen Wert als Standard"). Their
values stand in the default profile's rules.json; a profile that decides
otherwise says so in its own. The stage reads each where it decides, when it
runs (`rules.get`), so that a changed value is the next run's.

Author: Felix Vossel
"""
from .kit import rule

# The group of these rules on the tab "stages".
GROUP = "Stage 6: pieces and vectors"

RULES: tuple = (
    rule('join_continued_tables', "stages", GROUP, 'switch',
         'On: a table that stage 5 found to continue the table before it is joined to that table (its rows under the rows of the first). Off: each part stays a table of its own. Takes effect when stage 6 builds a document again.',
         where='merge.py (merge_single)',
         title='Join continued tables'),
    rule('embed_picture_max_pixels', "stages", GROUP, 'whole',
         "The most pixels a table or figure picture may have when it is embedded; a larger picture is scaled down to it. A larger value keeps more detail in the picture vector and costs more of the embedder's window. A changed value makes pictures embedded before differ from new ones; takes effect when stage 6 embeds again.",
         least=65536, most=16777216, where='qwen3_vl_embedding.py, embedding.py (window_of), api.py, rerank.py',
         title='Most pixels of an embedded picture'),
    rule('embed_instruction', "stages", GROUP, 'text',
         'The instruction given to the embedding model together with each section, table or figure text it turns into a vector. The questions of the chat are embedded with the same sentence, so it must stay the same on both sides. A changed sentence makes every stored vector stale: the corpus has to be embedded again.',
         where='qwen3_vl_embedding.py (Qwen3VLEmbedder), api.py (conversation)',
         title='Embedding instruction'),
    rule('embed_section_titles', "stages", GROUP, 'switch',
         'On: the title of every section gets a vector of its own, beside the vectors of its text. Off: titles are found only through the text vectors. A change adds or removes vectors; takes effect when stage 6 builds or syncs the index again.',
         where='chunking.py (build_embedding_inputs)',
         title='Embed section titles'),
    rule('embed_item_texts', "stages", GROUP, 'texts',
         'Which kinds of items get vectors from their text, from table and figure: the transcription of a table, the description of a figure. A kind left out is found only through its picture vector or not at all. A change adds or removes vectors; takes effect when stage 6 builds or syncs the index again.',
         choices=('table', 'figure'), empty=True, where='chunking.py (build_embedding_inputs)',
         title='Items embedded as text'),
    rule('embed_item_pictures', "stages", GROUP, 'texts',
         'Which kinds of items get vectors from their picture, from table and figure. A picture vector shows the picture with the text of its piece. A kind left out has no picture vector; an embedder that takes text only has none anyway. A change adds or removes vectors; takes effect when stage 6 builds or syncs the index again.',
         choices=('table', 'figure'), empty=True, where='chunking.py (build_embedding_inputs)',
         title='Items embedded as pictures'),
    rule('page_locate_probe_chars', "stages", GROUP, 'map',
         "The numbers of letters and digits (each at least 1) of the beginning of a line that are looked for in the PDF's text of its section to find the page the line stands on: long first, then medium, then short. A line with fewer letters than the shortest is not placed and stands where the line before it stands. A smaller short value places shorter lines, and sooner places them wrongly. Takes effect when stage 6 builds a document again.",
         of='whole', where='pieces.py (line_pages)',
         title='Probe lengths for placing a line'),
    rule('context_default_max_tokens', "stages", GROUP, 'whole',
         'The most tokens the reply of a request for the context sentence of a table or figure may have, where the header of its prompt gives none. Takes effect when stage 6 asks for context sentences again.',
         least=32, most=8192, where='context.py (make_ask)',
         title='Default reply room of context sentences'),
    rule('context_default_temperature', "stages", GROUP, 'number',
         'The sampling temperature of the request for a context sentence, where the header of its prompt gives none. A higher value gives freer sentences. Takes effect when stage 6 asks for context sentences again.',
         least=0, most=2, where='context.py (make_ask)',
         title='Default temperature of context sentences'),
)
