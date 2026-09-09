Every public function, class and method of the packages the chapters
describe, with its signature as written in the code and its docstring.
One page per module that has a docstring or a public name, grouped by
package. A function, class, method or field whose name starts with an
underscore is left out, `__init__` excepted, and where a module states
`__all__`, that list decides what is public.

Nothing here is imported: the pages are read with Python's `ast` module,
so a docstring reaches the site without OpenCV, PyMuPDF or torch. The
signature is the `def` line as written, a dataclass field carries the
comment above it, and the prose of a docstring is rendered as the
Markdown it is written in. The chapters under `stages/` say what a module
is for and what it hands to what; this is the reference.
