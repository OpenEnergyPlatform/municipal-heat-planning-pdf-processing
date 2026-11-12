# docpipe.extraction.mend

`docpipe/extraction/mend.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

mend.py: The two second ways of reading a reply that the owner decided
against on 2026-09-12 ("no JSON is repaired") and that a flow may choose
again: `repair_replies` (what is taken off or put right in a reply before it
is read) and `cut_off` (the complete entries of a list a reply was cut off
in). Both are off: a reply is read as it is, or asked again. Every reply
that went through either is noted in the request log by the caller, with
the rule's name.

## Functions

### close_brackets

```python
def close_brackets(text: str) -> str
```

The closers a reply stopped short of, appended. Delimiters only: a
bracket inside a string is text, a reply that stops inside a string is
left as it is, and a closer that does not match what is open is
somebody else's shape.

### repaired

```python
def repaired(text: str, kinds, closes: bool = True) -> tuple
```

(the object, what was done) of a reply that is no JSON object as it
stands, read after the repairs *kinds* name: `think` (a think block is
taken off), `fences` (code fences are taken off), `cut_out` (the one
object that starts at the first brace is read out of the text around
it), `close` (the brackets a reply stopped short of are closed, where
*closes*: a reply cut off at its ceiling is never closed). The object is
None where no repair made one; the list is what was done to get it.

### rescued

```python
def rescued(text: str, key: str) -> Optional[dict]
```

{key: the complete entries} of the list *key* of a reply that was cut
off, or None where the reply has no such list or no entry of it is
complete. An entry that was cut is not kept, nor anything after it.

[Back to the index](../README.md)
