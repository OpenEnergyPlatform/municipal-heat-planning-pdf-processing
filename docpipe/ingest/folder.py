"""
folder.py: A folder of PDFs as a document source.

The source of a corpus that has no register: every PDF in a folder is one
document. A file is known by its name, so two files of one name in different
subfolders are refused and named. The subfolder a file lies in travels as
its `folder`, which a profile may offer as a filter. What the PDF says about
itself (its title, its creation date) travels as `title` and `created`; a
PDF that says nothing has the file name for a title and no date. It is read
for a document that is not registered yet, and a database made before the
date was kept gets its column on the first run.

The folder may be the data directory itself. Then only what lies directly
in it is read, because the stages keep their own output underneath. Any
other folder is read with its subfolders, and each file is copied into the
data directory once: the corpus is then complete in one place and does not
change when the folder does.

Author: Felix Vossel
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path

from ..store import documents as docs
from ..store import schema
from . import pdf_info
from .models import Source, SourceDoc

log = logging.getLogger(__name__)
PDF_SUFFIX = ".pdf"
# The DocumentMeta column of a PDF's creation date.
CREATED = "created"


class FolderSource(Source):
    def __init__(self, folder: Path):
        self.folder = Path(folder).expanduser()
        self._files: list = []
        self._read = False

    @classmethod
    def default_location(cls, data_dir):
        return Path(data_dir)

    def _load(self, data_dir: Path = None) -> list:
        if self._read:
            return self._files
        if not self.folder.is_dir():
            raise SystemExit(f"{self.folder} is not a folder")
        inside = data_dir is not None and _same(self.folder, data_dir)
        found = self.folder.iterdir() if inside else self.folder.rglob("*")
        files = sorted(path for path in found
                       if path.is_file()
                       and path.suffix.lower() == PDF_SUFFIX)
        by_name: dict = {}
        for path in files:
            by_name.setdefault(path.name, []).append(path)
        twice = {name: paths for name, paths in by_name.items()
                 if len(paths) > 1}
        if twice:
            lines = [f"  {name}: " + ", ".join(
                str(p.parent.relative_to(self.folder)) for p in paths)
                for name, paths in sorted(twice.items())]
            raise SystemExit(
                "a document is known by its file name, and these names "
                "occur more than once under " + str(self.folder) + ":\n"
                + "\n".join(lines))
        self._files, self._read = files, True
        return files

    def prepare(self, data_dir) -> None:
        data_dir = Path(data_dir)
        files = self._load(data_dir)
        if _same(self.folder, data_dir):
            return
        copied = 0
        for path in files:
            target = data_dir / path.name
            if not target.exists():
                shutil.copy2(path, target)
                copied += 1
        log.info("%d PDF(s) under %s, %d copied into %s", len(files),
                 self.folder, copied, data_dir)

    def __len__(self) -> int:
        return len(self._load())

    def documents(self, connection):
        if connection is not None and schema.add_missing_column(
                connection, "DocumentMeta", CREATED, "TEXT"):
            log.info("DocumentMeta of this database had no %s column; added",
                     CREATED)
        for path in self._load():
            folder = path.parent.relative_to(self.folder).as_posix()
            # A document that is registered keeps the row it has, so its
            # file is not opened again for what that row would not take.
            known = connection is not None and docs.document_exists(
                path.name, connection)
            said = {} if known else pdf_info.read(path)
            meta = {"title": said.get("title") or path.stem,
                    "folder": None if folder == "." else folder}
            if CREATED in said:
                meta[CREATED] = said[CREATED]
            yield SourceDoc(
                external_id=path.name,
                filename=path.name,
                # copied in by `prepare`, or lying in the data directory
                url=None,
                meta=meta,
            )


def _same(one: Path, other: Path) -> bool:
    try:
        return Path(one).resolve() == Path(other).resolve()
    except OSError:
        return False
