# docpipe.ingest.folder

`docpipe/ingest/folder.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

folder.py: A folder of PDFs as a document source.

The source of a corpus that has no register: every PDF in a folder is one
document. A file is known by its name, so two files of one name in different
subfolders are refused and named. The subfolder a file lies in travels as
its `folder`, which a profile may offer as a filter.

The folder may be the data directory itself. Then only what lies directly
in it is read, because the stages keep their own output underneath. Any
other folder is read with its subfolders, and each file is copied into the
data directory once: the corpus is then complete in one place and does not
change when the folder does.

Author: Felix Vossel

## Classes

### FolderSource

```python
class FolderSource(Source)
```

#### FolderSource.\_\_init\_\_

```python
def __init__(self, folder: Path)
```

#### FolderSource.default_location

```python
@classmethod
def default_location(cls, data_dir)
```

#### FolderSource.prepare

```python
def prepare(self, data_dir) -> None
```

#### FolderSource.documents

```python
def documents(self, connection)
```

[Back to the index](../README.md)
