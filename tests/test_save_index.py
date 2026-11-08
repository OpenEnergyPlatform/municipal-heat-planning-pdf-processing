"""A saved index is written whole under a new name first: a job killed
while the file is written leaves the last saved index, which the next run
resumes from.

- A save leaves the new index at the path, AND no partial file beside it.
- A save that breaks off mid-write leaves the previous index at the path.
"""
import faiss
import numpy as np
import pytest

from docpipe.chunking import embedding


def index_of(n):
    index = faiss.IndexIDMap(faiss.IndexFlatIP(4))
    index.add_with_ids(np.ones((n, 4), dtype=np.float32),
                       np.arange(n, dtype=np.int64))
    return index


def test_a_save_leaves_the_new_index_and_nothing_beside_it(tmp_path):
    path = tmp_path / "faiss.index"
    embedding.save_index(index_of(3), path)
    embedding.save_index(index_of(5), path)
    assert faiss.read_index(str(path)).ntotal == 5
    assert sorted(p.name for p in tmp_path.iterdir()) == ["faiss.index"]


def test_a_save_broken_off_mid_write_leaves_the_previous_index(tmp_path,
                                                              monkeypatch):
    path = tmp_path / "faiss.index"
    embedding.save_index(index_of(3), path)

    def killed(index, target):
        with open(target, "wb") as f:
            f.write(b"\x00" * 16)
        raise KeyboardInterrupt

    monkeypatch.setattr(faiss, "write_index", killed)
    with pytest.raises(KeyboardInterrupt):
        embedding.save_index(index_of(5), path)
    assert faiss.read_index(str(path)).ntotal == 3
