"""Local web editor for correcting the layout pre-annotations.

Adapted from CSGOAimAssistant/scripts/editor.py. The pre-annotation happens at
workspace build time (sample_and_preannotate.py, on the GPU host), so this
editor never loads a model: labels/*.txt already exist, confirming a correct
page costs one keystroke (space bar).

Workspace layout: see sample_and_preannotate.py. Deleting moves a page and its
sidecars into <root>/deleted/ instead of unlinking.

Usage:
    python -m scripts.annotation.editor --dir data/annotation/kwp250
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.annotation.common import (
    CLASS_COLORS,
    CLASS_NAMES,
    DEFAULT_COLOR,
    EDITOR_CLASS_IDS,
    read_labels,
    write_labels,
)

EXIT_OK = 0
EXIT_USAGE = 1
EXIT_DEPENDENCY = 3

IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg")
TRASH_DIRNAME = "deleted"

STATUS_PREDICTED = "predicted"
STATUS_CONFIRMED = "confirmed"
STATUS_UNLABELED = "unlabeled"

try:
    from pydantic import BaseModel
except ImportError:  # pragma: no cover – only so --help works without install
    BaseModel = object  # type: ignore[assignment, misc]


class BoxModel(BaseModel):
    """A box in normalized YOLO coordinates."""
    cls: int
    cx: float
    cy: float
    w: float
    h: float


class SaveRequest(BaseModel):
    """Body of PUT /api/labels/{stem}."""
    boxes: list[BoxModel]
    confirm: bool = False


@dataclass
class Workspace:
    """A workspace directory with its subfolders."""
    root: Path
    index: int = 0
    label: str = ""

    @property
    def images(self) -> Path:
        return self.root / "images"

    @property
    def labels(self) -> Path:
        return self.root / "labels"

    @property
    def preds(self) -> Path:
        return self.root / "preds"

    @property
    def preann(self) -> Path:
        """Frozen pre-annotation — evaluate.py scores it against labels/."""
        return self.root / "preann"

    @property
    def meta(self) -> Path:
        return self.root / "meta"

    @property
    def trash(self) -> Path:
        return self.root / TRASH_DIRNAME

    @property
    def state_file(self) -> Path:
        return self.root / "editor_state.json"

    def image_files(self) -> list[Path]:
        if not self.images.is_dir():
            return []
        return sorted(
            (p for p in self.images.iterdir()
             if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES),
            key=lambda p: natural_key(p.stem),
        )

    def label_path(self, stem: str) -> Path:
        return self.labels / f"{stem}.txt"

    def pred_path(self, stem: str) -> Path:
        return self.preds / f"{stem}.json"

    def delete(self, image: Path) -> list[str]:
        """Move an image + all sidecars into deleted/ — a misclick must be recoverable."""
        stem = image.stem
        moved: list[str] = []
        pairs = [(image, "images"), (self.label_path(stem), "labels"),
                 (self.pred_path(stem), "preds"),
                 (self.preann / f"{stem}.txt", "preann"),
                 (self.meta / f"{stem}.json", "meta")]
        for source, sub in pairs:
            if not source.is_file():
                continue
            target_dir = self.trash / sub
            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / source.name
            if target.exists():
                counter = 1
                while (target_dir / f"{source.stem}_{counter}{source.suffix}").exists():
                    counter += 1
                target = target_dir / f"{source.stem}_{counter}{source.suffix}"
            source.replace(target)
            moved.append(sub)
        return moved


def natural_key(stem: str) -> tuple[int, str]:
    match = re.search(r"(\d+)$", stem)
    return (int(match.group(1)) if match else -1, stem)


class State:
    """Confirmation status, read and written thread-safely and atomically."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._confirmed: set[str] = set()
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                self._confirmed = set(data.get("confirmed", []))
            except (OSError, ValueError) as error:
                print(f"WARNING: {path} not readable ({error}), starting empty")

    def is_confirmed(self, stem: str) -> bool:
        with self._lock:
            return stem in self._confirmed

    def set(self, stem: str, confirmed: bool) -> None:
        with self._lock:
            if confirmed:
                self._confirmed.add(stem)
            else:
                self._confirmed.discard(stem)
            tmp = self._path.with_suffix(".tmp")
            try:
                tmp.write_text(
                    json.dumps({"confirmed": sorted(self._confirmed)}, indent=2) + "\n",
                    encoding="utf-8")
                tmp.replace(self._path)
            except OSError as error:
                print(f"ERROR: status not saveable: {error}", file=sys.stderr)


def status_for(ws: Workspace, state: State, stem: str) -> str:
    if state.is_confirmed(stem):
        return STATUS_CONFIRMED
    if ws.label_path(stem).is_file():
        return STATUS_PREDICTED
    return STATUS_UNLABELED


def build_app(ws: Workspace, state: State) -> Any:
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import FileResponse, HTMLResponse

    app = FastAPI(title="KWP layout editor")
    web_dir = Path(__file__).resolve().parent / "web"

    def resolve(stem: str) -> Path:
        image = next((p for p in ws.image_files() if p.stem == stem), None)
        if image is None:
            raise HTTPException(404, f"Image not found: {stem}")
        return image

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        page = web_dir / "index.html"
        if not page.is_file():
            raise HTTPException(500, f"Frontend missing: {page}")
        return page.read_text(encoding="utf-8")

    @app.get("/api/config")
    def api_config() -> dict[str, Any]:
        return {
            "class_names": list(CLASS_NAMES),
            "class_colors": {str(i): CLASS_COLORS.get(i, DEFAULT_COLOR)
                             for i in range(len(CLASS_NAMES))},
            "editor_class_ids": list(EDITOR_CLASS_IDS),
            "directory": str(ws.root),
            "sources": [{"index": 0, "label": ws.label, "root": str(ws.root)}],
            "multi_source": False,
            "model_loaded": False,
            "trash_dirname": TRASH_DIRNAME,
        }

    @app.get("/api/images")
    def api_images() -> dict[str, Any]:
        entries = []
        counts = {STATUS_UNLABELED: 0, STATUS_PREDICTED: 0, STATUS_CONFIRMED: 0}
        for p in ws.image_files():
            s = status_for(ws, state, p.stem)
            counts[s] += 1
            entries.append({
                "key": f"0/{quote(p.stem)}",
                "img": f"/api/image/0/{quote(p.name)}",
                "ws": 0, "source": ws.label,
                "name": p.name, "stem": p.stem, "status": s,
            })
        return {"images": entries, "total": len(entries), "counts": counts,
                "confirmed": counts[STATUS_CONFIRMED]}

    @app.get("/api/image/{ws_index}/{name}")
    def api_image(ws_index: int, name: str) -> FileResponse:
        path = ws.images / name
        if not path.resolve().is_relative_to(ws.images.resolve()) or not path.is_file():
            raise HTTPException(404, f"Image not found: {name}")
        return FileResponse(path)

    @app.get("/api/labels/{ws_index}/{stem}")
    def api_labels(ws_index: int, stem: str) -> dict[str, Any]:
        image = resolve(stem)
        boxes = read_labels(ws.label_path(stem))
        confs: list[float] = []
        if ws.pred_path(stem).is_file():
            try:
                confs = json.loads(ws.pred_path(stem).read_text(encoding="utf-8")).get("conf", [])
            except (OSError, ValueError):
                confs = []
        return {"stem": stem, "name": image.name, "source": ws.label,
                "boxes": boxes, "conf": confs[: len(boxes)],
                "status": status_for(ws, state, stem), "just_predicted": False}

    @app.put("/api/labels/{ws_index}/{stem}")
    def api_save(ws_index: int, stem: str, req: SaveRequest) -> dict[str, Any]:
        resolve(stem)
        write_labels(ws.label_path(stem), [b.model_dump() for b in req.boxes])
        if req.confirm:
            state.set(stem, True)
        return {"ok": True, "status": status_for(ws, state, stem)}

    @app.delete("/api/image/{ws_index}/{stem}")
    def api_delete(ws_index: int, stem: str) -> dict[str, Any]:
        image = resolve(stem)
        moved = ws.delete(image)
        state.set(stem, False)
        return {"ok": True, "moved": moved, "trash": str(ws.trash)}

    @app.get("/api/progress")
    def api_progress() -> dict[str, Any]:
        files = ws.image_files()
        confirmed = sum(1 for p in files if state.is_confirmed(p.stem))
        return {"total": len(files), "confirmed": confirmed,
                "percent": round(100.0 * confirmed / len(files), 1) if files else 0.0}

    return app


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Local web editor for correcting layout pre-annotations.")
    p.add_argument("--dir", type=Path, required=True,
                   help="Workspace directory (with an images/ subfolder)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8017)
    args = p.parse_args(argv)

    try:
        import uvicorn
    except ImportError:
        print("ERROR: uvicorn missing. Install: pip install fastapi uvicorn pydantic",
              file=sys.stderr)
        return EXIT_DEPENDENCY

    root = args.dir.resolve()
    if not (root / "images").is_dir():
        print(f"ERROR: no images/ subfolder in {root}", file=sys.stderr)
        return EXIT_USAGE

    ws = Workspace(root=root, index=0, label=root.name)
    state = State(ws.state_file)
    files = ws.image_files()
    done = sum(1 for p in files if state.is_confirmed(p.stem))

    app = build_app(ws, state)
    print("=" * 70)
    print(f"KWP layout editor – {root}")
    print(f"Pages: {len(files)}, confirmed: {done}")
    print(f"Deleting moves into {TRASH_DIRNAME}/, nothing is unlinked")
    print(f"http://{args.host}:{args.port}")
    print("=" * 70)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
