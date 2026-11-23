"""Whether Buildbot is on this machine, said by its files alone: nothing is run to know it (`buildbot --version` would
start a process) and nothing is asked over the network.

- The commands: `buildbot` (the master's) and `buildbot-worker`, on PATH (shutil.which) and where a pip install puts
  them: a virtual environment's bin/ (Scripts\\ on Windows) under a folder named buildbot* in the home folder (the
  tutorial's ~/buildbot-test/master_root/sandbox), ~/.local/bin (pip --user, pipx, uv), Python's own Scripts\\ folders
  on Windows (%APPDATA%\\Python\\Python3*, %LOCALAPPDATA%\\Programs\\Python\\Python3*), /usr/bin and /usr/local/bin
  elsewhere (a distribution's package), Homebrew's /opt/homebrew/bin on macOS.
- A master's or a worker's folder: one holding buildbot.tac (what `buildbot create-master` and `buildbot-worker
  create-worker` write), told apart by what the file imports (a worker's imports buildbot_worker, or buildslave before
  Buildbot 0.9; a master's makes a BuildMaster); under the home folder's buildbot* folders, and on Linux and macOS
  /var/lib/buildbot (where Debian's and Ubuntu's packages keep their masters), /srv/buildbot* and /opt/buildbot*; on
  Windows the system drive's buildbot* folders too.
- On Linux, a systemd unit named buildbot*.service (a distribution's buildbot@.service, an instance of it enabled, a
  unit of the user's own) in the system's and the user's unit folders: its file alone; systemctl is never run.

Every walk is bounded (DEPTH folders down, VISITS folders at most), skips hidden folders and a virtual environment's
library folders, and enters no link to a folder. A test's Finder is given a system, a home folder, the environment, its
`which`, and a root folder that stands in for / (and the drives on Windows)."""
from __future__ import annotations

import os
import platform
import re
import shutil
from collections import deque
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path

DEPTH = 4  # folders down from where a walk starts (~/buildbot-test/master_root/sandbox/bin is four)
VISITS = 2000  # folders a walk enters at most
TAC = "buildbot.tac"
TAC_BYTES = 16 << 10  # read of a buildbot.tac to tell a master's from a worker's
SKIP = frozenset({"node_modules", "__pycache__", "site-packages", "lib", "lib64", "include", "share", "libs", "tcl",
                  "dlls", "doc", "docs", "man"})  # never entered: a virtual environment's library, a project's packages
UNIT_FOLDERS = ("etc/systemd/system", "run/systemd/system", "usr/local/lib/systemd/system", "usr/lib/systemd/system",
                "lib/systemd/system")
WORKER_TAC = re.compile(r"\bbuildbot_worker\b|\bbuildslave\b")
COMMANDS = ("buildbot", "buildbot-worker")


@dataclass(frozen=True)
class Found:
    """What of Buildbot is on this machine: the buildbot commands (their files), the masters' folders, the
    buildbot-worker commands, the workers' folders, the systemd units (Linux), where it looked (in words), and why the
    look failed when it did."""

    commands: tuple[str, ...] = ()
    masters: tuple[str, ...] = ()
    worker_commands: tuple[str, ...] = ()
    workers: tuple[str, ...] = ()
    units: tuple[str, ...] = ()
    looked: tuple[str, ...] = ()
    trouble: str = ""

    @property
    def any(self) -> bool:
        """Anything of Buildbot's here: a command, a master's or a worker's folder, a unit."""
        return bool(self.commands or self.masters or self.worker_commands or self.workers or self.units)

    def rows(self) -> list[tuple[str, str]]:
        """Each thing found, as (what, where)."""
        return ([("buildbot command", p) for p in self.commands] + [("master", p) for p in self.masters]
                + [("buildbot-worker command", p) for p in self.worker_commands]
                + [("worker", p) for p in self.workers] + [("systemd unit", p) for p in self.units])

    def words(self) -> str:
        """What was found, in a line."""
        parts = [f"{len(v)} {what}{'' if len(v) == 1 else 's'}" for what, v in (
            ("buildbot command", self.commands), ("master folder", self.masters),
            ("buildbot-worker command", self.worker_commands), ("worker folder", self.workers),
            ("systemd unit", self.units)) if v]
        return ", ".join(parts) if parts else "nothing of Buildbot's"


def tac_kind(path: Path) -> str:
    """What a buildbot.tac is for: "worker" when it imports buildbot_worker (buildslave before Buildbot 0.9), else
    "master"."""
    try:
        with open(path, "rb") as f:
            text = f.read(TAC_BYTES).decode("utf-8", "replace")
    except OSError:
        return "master"
    return "worker" if WORKER_TAC.search(text) else "master"


def _is_folder(entry: os.DirEntry) -> bool:
    """A folder of its own: not a link to one, nor a junction (Windows)."""
    try:
        if entry.is_symlink() or getattr(entry, "is_junction", lambda: False)():
            return False
        return entry.is_dir(follow_symlinks=False)
    except OSError:
        return False


def walk(start: Path, depth: int = DEPTH, visits: int = VISITS) -> Iterator[Path]:
    """`start` and the folders under it, breadth first, `depth` down and `visits` in all at most; hidden folders, the
    SKIP ones and links to folders are not entered."""
    if not start.is_dir():
        return
    queue = deque([(start, 0)])
    seen = 0
    while queue and seen < visits:
        folder, level = queue.popleft()
        seen += 1
        yield folder
        if level >= depth:
            continue
        try:
            with os.scandir(folder) as entries:
                inner = sorted((e for e in entries if not e.name.startswith(".") and e.name.lower() not in SKIP
                                and _is_folder(e)), key=lambda e: e.name.lower())
        except OSError:
            continue
        queue.extend((Path(e.path), level + 1) for e in inner)


def _named(folder: Path, prefix: str) -> list[Path]:
    """The folders in `folder` whose names start with `prefix`, in any case."""
    try:
        with os.scandir(folder) as entries:
            return sorted((Path(e.path) for e in entries if e.name.lower().startswith(prefix) and _is_folder(e)),
                          key=lambda p: p.name.lower())
    except OSError:
        return []


def _unique(paths) -> tuple[str, ...]:
    out: dict[str, str] = {}
    for p in paths:
        out.setdefault(os.path.normcase(os.path.abspath(str(p))), str(p))
    return tuple(out.values())


class Finder:
    """The look at this machine (module docstring). `system`: "windows", "linux" or "darwin" (this machine's unless
    given); `home`: the home folder; `env`: the variables read (APPDATA, LOCALAPPDATA, SystemDrive); `which(name)`:
    a program's file on PATH (shutil.which's unless given); `root`: the folder / stands for on Linux and macOS (a test's
    tree); `drives`: the drives' roots on Windows (the system drive's unless given)."""

    def __init__(self, system: str | None = None, home=None, env: Mapping[str, str] | None = None,
                 which: Callable[[str], str | None] | None = None, root=None, drives=None):
        self.system = str(system or platform.system() or "").lower()
        self.windows = self.system == "windows"
        self.home = Path(home) if home is not None else Path.home()
        self.env = os.environ if env is None else env
        self._which = which
        self.root = Path(root) if root is not None else Path(os.path.abspath(os.sep))
        if drives is not None:
            self.drives = tuple(Path(d) for d in drives)
        else:
            self.drives = (Path(str(self.env.get("SystemDrive") or "C:") + "\\"),) if self.windows else ()

    def which(self, name: str) -> str | None:
        try:
            return (self._which or shutil.which)(name)
        except OSError:
            return None

    def _script(self, folder: Path, name: str) -> Path:
        return folder / "Scripts" / f"{name}.exe" if self.windows else folder / "bin" / name

    def _spots(self) -> list[tuple[Path, str]]:
        """The places a pip install or a package puts the commands, each (file, command)."""
        out: list[tuple[Path, str]] = []
        if self.windows:
            folders = [self.home / ".local" / "bin"]
            for var, under in (("APPDATA", ("Python",)), ("LOCALAPPDATA", ("Programs", "Python"))):
                if self.env.get(var):
                    folders += [p / "Scripts" for p in _named(Path(self.env[var]).joinpath(*under), "python3")]
            return [(f / f"{name}.exe", name) for f in folders for name in COMMANDS]
        folders = [self.root / "usr" / "bin", self.root / "usr" / "local" / "bin", self.home / ".local" / "bin"]
        if self.system == "darwin":
            folders.append(self.root / "opt" / "homebrew" / "bin")
        return [(f / name, name) for f in folders for name in COMMANDS]

    def _tops(self) -> list[Path]:
        """Where the walks start: the home folder's buildbot* folders, and the system's own places."""
        tops = _named(self.home, "buildbot")
        if self.windows:
            for drive in self.drives:
                tops += _named(drive, "buildbot")
            return tops
        tops.append(self.root / "var" / "lib" / "buildbot")
        for under in ("srv", "opt"):
            tops += _named(self.root / under, "buildbot")
        return tops

    def _units(self) -> list[Path]:
        """The systemd units named buildbot*.service: in the system's unit folders and the user's, and those enabled
        (a link in a .wants folder)."""
        found: dict[str, Path] = {}
        for folder in [self.root / f for f in UNIT_FOLDERS] + [self.home / ".config" / "systemd" / "user"]:
            if not folder.is_dir():
                continue
            for pattern in ("buildbot*.service", "*.wants/buildbot*.service"):
                try:
                    for p in sorted(folder.glob(pattern)):
                        found.setdefault(os.path.normcase(os.path.abspath(str(p))), p)
                except OSError:
                    continue
        return list(found.values())

    def looked(self) -> tuple[str, ...]:
        """Where it looks, in words."""
        if self.windows:
            return ("PATH", r"~\.local\bin", r"%APPDATA%\Python\Python3*\Scripts",
                    r"%LOCALAPPDATA%\Programs\Python\Python3*\Scripts", r"~\buildbot* (four folders down)",
                    *(str(d / "buildbot*") for d in self.drives))
        places = ["PATH", "/usr/bin", "/usr/local/bin", "~/.local/bin", "~/buildbot* (four folders down)",
                  "/var/lib/buildbot", "/srv/buildbot*", "/opt/buildbot*"]
        if self.system == "darwin":
            places.insert(4, "/opt/homebrew/bin")
        else:
            places.append("systemd's unit folders (buildbot*.service)")
        return tuple(places)

    def find(self) -> Found:
        """What of Buildbot is here (module docstring)."""
        commands: list[str] = []
        workers_cmd: list[str] = []
        masters: list[str] = []
        workers: list[str] = []
        into = {"buildbot": commands, "buildbot-worker": workers_cmd}
        for name in COMMANDS:
            got = self.which(name)
            if got:
                into[name].append(str(got))
        for spot, name in self._spots():
            if spot.is_file():
                into[name].append(str(spot))
        for top in self._tops():
            for folder in walk(top):
                for name in COMMANDS:
                    script = self._script(folder, name)
                    if script.is_file():
                        into[name].append(str(script))
                tac = folder / TAC
                if tac.is_file():
                    (workers if tac_kind(tac) == "worker" else masters).append(str(folder))
        units = [str(p) for p in self._units()] if self.system == "linux" else []
        return Found(_unique(commands), _unique(masters), _unique(workers_cmd), _unique(workers), _unique(units),
                     self.looked())
