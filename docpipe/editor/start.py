"""
start.py: `docpipe edit` itself: it starts the server, and starts it again
with the profile the page switches to.

A process runs on one profile. A stage binds part of what its profile says
when it is imported, and `profile.resolve_profile` refuses to name another
profile after that rather than run on a mix of both. So the page does not
switch the profile inside the server. The command runs the server as a
process of its own (`python -m docpipe --profile NAME edit ... --switch-file
NOTE`, `server.serve_one`). A switch writes the profile and the server's
port into the note and ends the server with `RESTART` once its answer is
sent; the command then starts the server with that profile at the same port
and does not open the page again: the page waits for the server and loads
itself anew. A harvest given with `--harvest` belongs to the profile the
command was started with: the server is given it whenever it runs with that
profile, and never with another.

The server ends with the command. Ctrl+C reaches both, and a server whose
command is gone stops by itself: its standard input is a pipe the command
holds, and that pipe ends when the command does, also a command that was
killed.

Author: Felix Vossel
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable, Optional, Sequence

RESTART = 75            # the exit status of a server that ends for a switch
NOTE = "switch.json"    # in a temporary folder of the command's own
WAIT = 0.5              # seconds between two looks at the running server
STOP = 10               # seconds a server has to end after Ctrl+C


def parser() -> argparse.ArgumentParser:
    """The arguments of `docpipe edit`, of the command and of each server it
    starts."""
    made = argparse.ArgumentParser(
        prog="docpipe edit",
        description="A profile's extraction spec, its prompts, the "
                    "sentences beside them and the numbers of its flow in "
                    "the browser, on a local "
                    "page (127.0.0.1 only). It writes only inside the "
                    "profile's folder. The head of the page switches to "
                    "another profile: the server starts again with it at "
                    "the same address. Nothing leaves this machine but "
                    "the requests of a click on Try, which go to the "
                    "model the installation names for it "
                    "(EDIT_TRY_BASE_URL).")
    made.add_argument("--harvest", metavar="DIR",
                      help="a folder with a harvest, its stamps and "
                           "traces (a local copy), of the profile the "
                           "command starts with: an edit of the spec "
                           "then says which documents it makes stale, "
                           "a prompt is shown with the requests "
                           "recorded there, and the flow says beside its "
                           "numbers what that run measured")
    made.add_argument("--port", type=int, default=8765,
                      help="default 8765; a free one if it is taken")
    made.add_argument("--no-browser", action="store_true",
                      help="do not open the page")
    # given by the command to each server it starts: where the server says
    # the profile and the port it is to be started again with
    made.add_argument("--switch-file", metavar="FILE",
                      help=argparse.SUPPRESS)
    return made


def note_bytes(name: str, port: int) -> bytes:
    """What a server writes into the note for a switch to profile *name*."""
    return json.dumps({"profile": name, "port": port}).encode("utf-8")


def read_note(note: Path) -> tuple:
    """(profile, port) the server wrote into *note*."""
    said = json.loads(note.read_text(encoding="utf-8"))
    return str(said["profile"]), int(said["port"])


def line(name: str, port: int, harvest: Optional[Path], browser: bool,
         note: Path) -> list:
    """The command line of one server: profile *name* at *port*."""
    out = [sys.executable, "-m", "docpipe", "--profile", name, "edit",
           "--port", str(port), "--switch-file", str(note)]
    if harvest is not None:
        out += ["--harvest", str(harvest)]
    if not browser:
        out.append("--no-browser")
    return out


def _run(command: list) -> int:
    """Run one server to its end; its exit status. Its standard input is a
    pipe this process holds open, so it ends when this process does."""
    child = subprocess.Popen(command, stdin=subprocess.PIPE)
    try:
        while True:
            try:
                return child.wait(WAIT)
            except subprocess.TimeoutExpired:
                continue
    except KeyboardInterrupt:
        # Ctrl+C reached the server as well, and it ends by itself
        try:
            child.wait(STOP)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()
        raise
    finally:
        if child.stdin is not None:
            child.stdin.close()


def loop(name: str, port: int, harvest: Optional[Path], browser: bool,
         run: Callable[[list], int] = _run) -> int:
    """Run the server with profile *name*, and again with each profile it
    ends for, until it ends for no switch; the exit status of the last."""
    harvests = {name: harvest} if harvest is not None else {}
    with tempfile.TemporaryDirectory(prefix="docpipe-edit-") as folder:
        note = Path(folder) / NOTE
        while True:
            status = run(line(name, port, harvests.get(name), browser, note))
            if status != RESTART:
                return status
            try:
                name, port = read_note(note)
                note.unlink()
            except (OSError, ValueError, KeyError, TypeError):
                print("docpipe edit: the server ended to switch the profile "
                      "but did not say to which one", file=sys.stderr)
                return 1
            browser = False
            print(f"docpipe edit: starting again with profile {name}",
                  flush=True)


def main(rest: Sequence[str]) -> int:
    """`docpipe edit`: the command, or one server it started."""
    made = parser()
    args = made.parse_args(list(rest))
    if args.switch_file:
        from . import server
        return server.serve_one(args)
    from ..profile import ENV_VAR
    harvest = None
    if args.harvest:
        harvest = Path(args.harvest).expanduser()
        if not harvest.is_dir():
            made.error(f"--harvest {args.harvest}: no such folder")
    name = os.environ.get(ENV_VAR)
    if not name:
        raise SystemExit(f"docpipe edit needs a profile: pass --profile "
                         f"NAME (or set ${ENV_VAR})")
    try:
        return loop(name, args.port, harvest, not args.no_browser)
    except KeyboardInterrupt:
        return 0
