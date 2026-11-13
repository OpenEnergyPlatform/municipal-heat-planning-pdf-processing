"""A branch archive yields the files under the asked folders with the asked
suffix, each with its bytes, AND a member that is absolute or climbs out with
`..` is refused, never returned."""
import io
import tarfile

import pytest

from docpipe.upstream import UpstreamError, tree_members


def archive(files: dict) -> bytes:
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return out.getvalue()


PATHS = ["definitions/region/", "mappings/"]


def test_files_under_the_paths_with_the_suffix_are_taken_with_their_bytes():
    body = archive({"top/definitions/region/b/y.yaml": b"y",
                    "top/mappings/x.yaml": b"x",
                    "top/README.md": b"r",
                    "top/other/x.yaml": b"o",
                    "top/definitions/region/z.txt": b"z"})
    assert tree_members(body, PATHS, ".yaml") == [
        ("definitions/region/b/y.yaml", b"y"), ("mappings/x.yaml", b"x")]


def test_a_member_climbing_out_is_refused():
    body = archive({"top/definitions/region/../../evil.yaml": b"e"})
    with pytest.raises(UpstreamError):
        tree_members(body, PATHS, ".yaml")


def test_an_absolute_member_is_refused():
    body = archive({"/etc/evil.yaml": b"e"})
    with pytest.raises(UpstreamError):
        tree_members(body, PATHS, ".yaml")
