

<table_before>
The table right before this one in the document, as transcribed: its caption and its head.
Caption: {previous_caption}
{previous_head}
</table_before>

<between>
{between}
</between>

The table in the image may continue the table before it: a page break or the page layout can cut one table into parts, and a part often prints no caption and no head of its own. Decide from the image, the table before it and what stands between them (often only a page footer, or nothing). If the table in the image continues it, write the head lines above unchanged as your first rows, then every row of the image (a head row the image repeats is not written again), and give no caption. Otherwise transcribe it as its own table.

Your JSON object has a third key here, "continues": true if the table in the image continues the table before it, false if it does not.
