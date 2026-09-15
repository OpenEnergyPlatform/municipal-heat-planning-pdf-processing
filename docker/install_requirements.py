"""
install_requirements.py: Installs requirements.txt on top of the vLLM base
image without touching what the base image already brings.

The base image is the serving stack vLLM was tested with: torch, its CUDA
wheels, transformers, pydantic, starlette. requirements.txt is a freeze of a
workstation and pins some of the same packages to other versions. Installed
as it stands, pip would swap vLLM's torch and transformers for the pinned
ones. So a package the base image already has is skipped and its base version
wins, every base package is passed as a constraint so nothing new drags one
along, and the build fails if a base package changed anyway.

Usage (inside the image build): python3 install_requirements.py requirements.txt

Author: Felix Vossel
"""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from importlib import metadata
from pathlib import Path

# One import name, several distributions: the base image's headless OpenCV
# and requirements.txt's full one both install cv2, and the second would
# overwrite the first with a build that needs libGL.
SAME_MODULE = [{"opencv-python", "opencv-python-headless",
                "opencv-contrib-python", "opencv-contrib-python-headless"}]
# And where the base has none, the headless build of the same version: the
# full one links libGL, which this image does not carry, and docpipe opens
# no window.
HEADLESS = {"opencv-python": "opencv-python-headless",
            "opencv-contrib-python": "opencv-contrib-python-headless"}


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def installed() -> dict:
    """Every distribution in this interpreter, normalized name -> version."""
    return {normalize(d.metadata["Name"]): d.version
            for d in metadata.distributions() if d.metadata["Name"]}


def requirement_name(line: str) -> str:
    """The distribution a requirements line names, '' for none."""
    line = line.split("#", 1)[0].strip() if " @ " not in line else line.strip()
    if not line or line.startswith("-"):
        return ""
    return normalize(re.split(r"[\s<>=!~;\[@]", line, 1)[0])


def split(lines: list, base: dict) -> tuple:
    """(lines to install, [(name, pinned line, base version)] skipped)."""
    keep, skipped = [], []
    for raw in lines:
        name = requirement_name(raw)
        if not name:
            continue
        family = next((s for s in SAME_MODULE if name in s), {name})
        held = [n for n in family if n in base]
        if held:
            skipped.append((name, raw.strip(), base[held[0]]))
        elif name in HEADLESS:
            keep.append(HEADLESS[name] + raw.strip()[len(name):])
        else:
            keep.append(raw.strip())
    return keep, skipped


def pip_command() -> list:
    try:
        import pip  # noqa: F401
        return [sys.executable, "-m", "pip", "install", "--no-cache-dir"]
    except ImportError:
        return ["uv", "pip", "install", "--python", sys.executable]


def main(argv: list) -> int:
    requirements = Path(argv[0])
    base = installed()
    keep, skipped = split(requirements.read_text().splitlines(), base)
    print(f"base image: {len(base)} distribution(s)")
    for name, pinned, version in skipped:
        print(f"  skip {pinned:<45} base has {name} {version}")
    print(f"installing {len(keep)} of {len(keep) + len(skipped)} requirement(s)")

    with tempfile.TemporaryDirectory() as tmp:
        wanted = Path(tmp) / "requirements.txt"
        wanted.write_text("\n".join(keep) + "\n")
        constraints = Path(tmp) / "constraints.txt"
        # Local version labels (+cu129) are what the base installed; a
        # constraint on them holds as long as nothing asks for a change.
        constraints.write_text("".join(f"{n}=={v}\n" for n, v in sorted(base.items())))
        subprocess.run(pip_command() + ["-r", str(wanted), "-c", str(constraints)],
                       check=True)

    after = installed()
    changed = sorted(f"{n} {v} -> {after.get(n, 'removed')}"
                     for n, v in base.items() if after.get(n) != v)
    if changed:
        print("FAIL: the install changed base image package(s):")
        for line in changed:
            print("  " + line)
        return 1
    print(f"PASS: {len(after) - len(base)} distribution(s) added, base unchanged")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
