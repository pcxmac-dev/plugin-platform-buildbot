"""Whether Buildbot is on this machine, said by its files alone: nothing is run to know it (`buildbot --version` would
start a process) and nothing is asked over the network.

- The commands: `buildbot` (the master's) and `buildbot-worker`, on PATH (shutil.which) and where a pip install puts
  them: a virtual environment's bin/ (Scripts\\ on Windows) under a folder named buildbot* in the home folder (the
  tutorial's ~/buildbot-test/master_root/sandbox), ~/.local/bin (pip --user, pipx, uv), Python's own Scripts\\ folders
  on Windows (%APPDATA%\\Python\\Python3*, %LOCALAPPDATA%\\Programs\\Python\\Python3*), /usr/bin and /usr/local/bin
  elsewhere (a distribution's package), Homebrew's /opt/homebrew/bin on macOS. Each folder is looked in once, as its
  real path (one linked to another is the other).
- A master's or a worker's folder: one holding buildbot.tac (what `buildbot create-master` and `buildbot-worker
  create-worker` write), told apart by what the file imports (a worker's imports buildbot_worker or its Worker, or
  buildslave before Buildbot 0.9, as Buildbot's own Windows service tells them; a master's makes a BuildMaster); under
  the home folder's buildbot* folders, and on Linux and macOS /var/lib/buildbot (where Debian's and Ubuntu's packages
  keep their masters), /srv/buildbot* and /opt/buildbot*; on Windows the system drive's buildbot* folders too.
- On Linux, a systemd unit named buildbot*.service (a distribution's buildbot@.service, an instance of it enabled, a
  unit of the user's own) in the system's and the user's unit folders, each folder walked once as its real path (with
  /usr merged, /lib is /usr/lib): its file alone, systemctl is never run; an init script (/etc/init.d/buildbot,
  buildbot-worker, buildmaster: a package's or Buildbot's contrib's), and the folders /etc/default's buildbot,
  buildmaster and buildbot-worker name (their MASTER_BASEDIR[n] and WORKER_BASEDIR[n]), each looked at for its
  buildbot.tac: plain text, read, never run.
- On Windows, Buildbot's own service (BuildBot: what buildbot_windows_service and buildbot_worker_windows_service
  install), by its registry key under HKEY_LOCAL_MACHINE\\SYSTEM\\CurrentControlSet\\Services, read with the rights
  any user holds (KEY_READ): its start, the Python it runs from (its ImagePath, whose environment's commands are looked
  for), whose service it is (its PythonClass: buildbot's or buildbot_worker's), and the folders it runs (its
  Parameters' directories, ; between them), each told a master's or a worker's by its buildbot.tac; its state is the
  service control manager's (QueryServiceStatus), asked with the rights any user holds. No process either.

Every walk is bounded (DEPTH folders down, VISITS folders at most), skips hidden folders and a virtual environment's
library folders, and enters no link to a folder. A test's Finder is given a system, a home folder, the environment, its
`which`, a root folder that stands in for / (and the drives on Windows), and the registry and the service manager."""
from __future__ import annotations

import os
import platform
import re
import shutil
from collections import deque
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

DEPTH = 4  # folders down from where a walk starts (~/buildbot-test/master_root/sandbox/bin is four)
VISITS = 2000  # folders a walk enters at most
TAC = "buildbot.tac"
TAC_BYTES = 16 << 10  # read of a buildbot.tac to tell a master's from a worker's
TEXT_BYTES = 64 << 10  # read of a defaults file at most
SKIP = frozenset({"node_modules", "__pycache__", "site-packages", "lib", "lib64", "include", "share", "libs", "tcl",
                  "dlls", "doc", "docs", "man"})  # never entered: a virtual environment's library, a project's packages
UNIT_FOLDERS = ("etc/systemd/system", "run/systemd/system", "usr/local/lib/systemd/system", "usr/lib/systemd/system",
                "lib/systemd/system")
INIT_SCRIPTS = ("buildbot", "buildbot-worker", "buildmaster")  # in /etc/init.d: a package's, or Buildbot's contrib's
DEFAULTS = ("buildbot", "buildmaster", "buildbot-worker")  # in /etc/default: the folders their init scripts start
BASEDIR = re.compile(r"""^[ \t]*(?:export[ \t]+)?(?:MASTER|WORKER|SLAVE)_BASEDIR\[[ \t]*\w+[ \t]*\][ \t]*=[ \t]*"""
                     r"""(?:"([^"\n]*)"|'([^'\n]*)'|([^\s#;"']*))""", re.M)
WORKER_TAC = re.compile(r"\bbuildbot_worker\b|\bbuildslave\b|\bimport (?:Worker|BuildSlave)\b")
COMMANDS = ("buildbot", "buildbot-worker")
SERVICE = "BuildBot"  # the Windows service buildbot_windows_service and buildbot_worker_windows_service make
SERVICE_KEY = "SYSTEM\\CurrentControlSet\\Services\\" + SERVICE  # under HKEY_LOCAL_MACHINE
STARTS = {0: "started at boot", 1: "started with the system", 2: "started automatically", 3: "started by hand",
          4: "disabled"}  # its key's Start
STATES = {1: "stopped", 2: "starting", 3: "stopping", 4: "running", 5: "continuing", 6: "pausing", 7: "paused"}
SC_MANAGER_CONNECT, SERVICE_QUERY_STATUS = 0x0001, 0x0004
ERROR_SERVICE_DOES_NOT_EXIST = 1060
VALUES_MOST = 64  # values read of a registry key at most
FOLDERS_MOST = 20  # the service's folders looked at, at most
SITE = re.compile(r"[\\/]lib[\\/]site-packages[\\/]", re.I)  # where a Python environment's packages are, in a path


@dataclass(frozen=True)
class Found:
    """What of Buildbot is on this machine: the buildbot commands (their files), the masters' folders, the
    buildbot-worker commands, the workers' folders, the systemd units and the init scripts (Linux), Buildbot's own
    Windows service (each in words), where it looked (in words), and why the look failed when it did."""

    commands: tuple[str, ...] = ()
    masters: tuple[str, ...] = ()
    worker_commands: tuple[str, ...] = ()
    workers: tuple[str, ...] = ()
    units: tuple[str, ...] = ()
    scripts: tuple[str, ...] = ()
    services: tuple[str, ...] = ()
    looked: tuple[str, ...] = ()
    trouble: str = ""

    @property
    def any(self) -> bool:
        """Anything of Buildbot's here: a command, a master's or a worker's folder, a unit, an init script, a
        service."""
        return bool(self.commands or self.masters or self.worker_commands or self.workers or self.units
                    or self.scripts or self.services)

    def rows(self) -> list[tuple[str, str]]:
        """Each thing found, as (what, where)."""
        return ([("buildbot command", p) for p in self.commands] + [("master", p) for p in self.masters]
                + [("buildbot-worker command", p) for p in self.worker_commands]
                + [("worker", p) for p in self.workers] + [("systemd unit", p) for p in self.units]
                + [("init script", p) for p in self.scripts] + [("Windows service", s) for s in self.services])

    def words(self) -> str:
        """What was found, in a line."""
        parts = [f"{len(v)} {what}{'' if len(v) == 1 else 's'}" for what, v in (
            ("buildbot command", self.commands), ("master folder", self.masters),
            ("buildbot-worker command", self.worker_commands), ("worker folder", self.workers),
            ("systemd unit", self.units), ("init script", self.scripts), ("Windows service", self.services)) if v]
        return ", ".join(parts) if parts else "nothing of Buildbot's"


def tac_kind(path: Path) -> str:
    """What a buildbot.tac is for: "worker" when it imports buildbot_worker or its Worker (buildslave before Buildbot
    0.9), as Buildbot's own Windows service tells them; else "master"."""
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


def _key(path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


def _real(path) -> str:
    """A folder's real path, its links (a junction on Windows) followed, as a key."""
    try:
        return os.path.normcase(os.path.realpath(str(path)))
    except (OSError, ValueError):
        return _key(path)


def _once(folders) -> list[Path]:
    """Each folder once: the first of those that are one folder, by its real path (a link to another is the other)."""
    out: dict[str, Path] = {}
    for f in folders:
        out.setdefault(_real(f), Path(f))
    return list(out.values())


def _unique(paths) -> tuple[str, ...]:
    out: dict[str, str] = {}
    for p in paths:
        out.setdefault(_key(p), str(p))
    return tuple(out.values())


def _text(path: Path, most: int = TEXT_BYTES) -> str:
    try:
        with open(path, "rb") as f:
            return f.read(most).decode("utf-8", "replace")
    except OSError:
        return ""


# -- the real registry and service manager (Windows) ---------------------------------------------------------------
def registry(path: str) -> dict | None:
    """The values of HKEY_LOCAL_MACHINE\\`path` by name ("" its own), VALUES_MOST at most, read with KEY_READ (a
    standard user's right on a service's key); None when the key is not there, or this is not Windows. PermissionError
    when it is there and this user may not read it."""
    try:
        import winreg
    except ImportError:
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path, 0, winreg.KEY_READ) as key:
            out: dict = {}
            for i in range(VALUES_MOST):
                try:
                    name, value, _kind = winreg.EnumValue(key, i)
                except OSError:
                    break
                out[name] = value
            return out
    except FileNotFoundError:
        return None


def service_state(name: str) -> tuple[str, str]:
    """A Windows service's state in words, asked of the service control manager with the rights any signed-in user
    holds (SC_MANAGER_CONNECT, SERVICE_QUERY_STATUS): OpenSCManagerW, OpenServiceW, QueryServiceStatus,
    CloseServiceHandle, as the Jenkins and GoCD plugins ask theirs. ("", why) when it cannot say."""
    try:
        import ctypes
        from ctypes import wintypes

        adv = ctypes.WinDLL("advapi32", use_last_error=True)
    except (ImportError, OSError, AttributeError) as e:
        return "", f"the service control manager could not be reached ({type(e).__name__})"

    class ServiceStatus(ctypes.Structure):  # SERVICE_STATUS, as winsvc.h lays it out
        _fields_ = [("dwServiceType", wintypes.DWORD), ("dwCurrentState", wintypes.DWORD),
                    ("dwControlsAccepted", wintypes.DWORD), ("dwWin32ExitCode", wintypes.DWORD),
                    ("dwServiceSpecificExitCode", wintypes.DWORD), ("dwCheckPoint", wintypes.DWORD),
                    ("dwWaitHint", wintypes.DWORD)]

    adv.OpenSCManagerW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
    adv.OpenSCManagerW.restype = wintypes.HANDLE
    adv.OpenServiceW.argtypes = [wintypes.HANDLE, wintypes.LPCWSTR, wintypes.DWORD]
    adv.OpenServiceW.restype = wintypes.HANDLE
    adv.QueryServiceStatus.argtypes = [wintypes.HANDLE, ctypes.POINTER(ServiceStatus)]
    adv.QueryServiceStatus.restype = wintypes.BOOL
    adv.CloseServiceHandle.argtypes = [wintypes.HANDLE]
    adv.CloseServiceHandle.restype = wintypes.BOOL
    manager = adv.OpenSCManagerW(None, None, SC_MANAGER_CONNECT)
    if not manager:
        return "", f"the service control manager could not be asked (error {ctypes.get_last_error()})"
    try:
        service = adv.OpenServiceW(manager, name, SERVICE_QUERY_STATUS)
        if not service:
            error = ctypes.get_last_error()
            return "", "" if error == ERROR_SERVICE_DOES_NOT_EXIST else f"its state could not be asked (error {error})"
        try:
            status = ServiceStatus()
            if not adv.QueryServiceStatus(service, ctypes.byref(status)):
                return "", f"its state could not be read (error {ctypes.get_last_error()})"
            state = int(status.dwCurrentState)
            return STATES.get(state, f"in state {state}"), ""
        finally:
            adv.CloseServiceHandle(service)
    finally:
        adv.CloseServiceHandle(manager)


def _program(image) -> str:
    """The program a service's ImagePath runs: its first word, or what its quotes hold."""
    text = str(image or "").strip()
    if text.startswith('"'):
        return text[1:].split('"', 1)[0]
    low = text.lower()
    end = low.find(".exe")
    return text[:end + 4] if end >= 0 else text.split(" ", 1)[0]


class Finder:
    """The look at this machine (module docstring). `system`: "windows", "linux" or "darwin" (this machine's unless
    given); `home`: the home folder; `env`: the variables read (APPDATA, LOCALAPPDATA, SystemDrive); `which(name)`:
    a program's file on PATH (shutil.which's unless given); `root`: the folder / stands for on Linux and macOS (a test's
    tree); `drives`: the drives' roots on Windows (the system drive's unless given); `registry(path)`: a key's values
    under HKEY_LOCAL_MACHINE (winreg's unless given); `service_state(name)`: a service's state in words and why it
    could not be said (the service control manager's unless given)."""

    def __init__(self, system: str | None = None, home=None, env: Mapping[str, str] | None = None,
                 which: Callable[[str], str | None] | None = None, root=None, drives=None,
                 registry: Callable[[str], Mapping | None] | None = None,
                 service_state: Callable[[str], tuple[str, str]] | None = None):
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
        self._registry = registry
        self._service_state = service_state

    def which(self, name: str) -> str | None:
        try:
            return (self._which or shutil.which)(name)
        except OSError:
            return None

    def _script(self, folder: Path, name: str) -> Path:
        return folder / "Scripts" / f"{name}.exe" if self.windows else folder / "bin" / name

    def _spots(self) -> list[tuple[Path, str]]:
        """The places a pip install or a package puts the commands, each (file, command), each folder once."""
        if self.windows:
            folders = [self.home / ".local" / "bin"]
            for var, under in (("APPDATA", ("Python",)), ("LOCALAPPDATA", ("Programs", "Python"))):
                if self.env.get(var):
                    folders += [p / "Scripts" for p in _named(Path(self.env[var]).joinpath(*under), "python3")]
            return [(f / f"{name}.exe", name) for f in _once(folders) for name in COMMANDS]
        folders = [self.root / "usr" / "bin", self.root / "usr" / "local" / "bin", self.home / ".local" / "bin"]
        if self.system == "darwin":
            folders.append(self.root / "opt" / "homebrew" / "bin")
        return [(f / name, name) for f in _once(folders) for name in COMMANDS]

    def _tops(self) -> list[Path]:
        """Where the walks start: the home folder's buildbot* folders, and the system's own places."""
        tops = _named(self.home, "buildbot")
        if self.windows:
            for drive in self.drives:
                tops += _named(drive, "buildbot")
            return _once(tops)
        tops.append(self.root / "var" / "lib" / "buildbot")
        for under in ("srv", "opt"):
            tops += _named(self.root / under, "buildbot")
        return _once(tops)

    def _units(self) -> list[Path]:
        """The systemd units named buildbot*.service: in the system's unit folders and the user's, and those enabled
        (a link in a .wants folder). Each folder is walked once, as its real path (with /usr merged, /lib is /usr/lib,
        and its units are said under the first that names them); a unit file is not followed, so an enabled
        instance's link is its own row."""
        found: dict[str, Path] = {}
        folders = _once([self.root / f for f in UNIT_FOLDERS] + [self.home / ".config" / "systemd" / "user"])
        for folder in folders:
            if not folder.is_dir():
                continue
            for pattern in ("buildbot*.service", "*.wants/buildbot*.service"):
                try:
                    for p in sorted(folder.glob(pattern)):
                        found.setdefault(_key(p), p)
                except OSError:
                    continue
        return list(found.values())

    def _at(self, posix: str) -> Path | None:
        """A Linux path (absolute) under this look's root; None for one that is not absolute."""
        parts = PurePosixPath(posix).parts
        return self.root.joinpath(*parts[1:]) if parts and parts[0] == "/" and len(parts) > 1 else None

    def _scripts(self) -> list[Path]:
        """The init scripts of Buildbot's in /etc/init.d."""
        return [p for p in (self.root / "etc" / "init.d" / n for n in INIT_SCRIPTS) if p.is_file()]

    def _basedirs(self) -> list[Path]:
        """The folders /etc/default's buildbot, buildmaster and buildbot-worker name (MASTER_BASEDIR[n],
        WORKER_BASEDIR[n], SLAVE_BASEDIR[n] before Buildbot 0.9): what their init scripts start."""
        out: list[Path] = []
        for name in DEFAULTS:
            text = _text(self.root / "etc" / "default" / name)
            for m in BASEDIR.finditer(text):
                given = next((g for g in m.groups() if g), "").strip()
                folder = self._at(given) if given else None
                if folder is not None:
                    out.append(folder)
        return _once(out)

    def _service(self, into: dict, masters: list, workers: list) -> list[str]:
        """Buildbot's own Windows service, in words (none when it is not there): its start and state, whose it is, the
        Python it runs from and the folders it runs; those folders go into `masters` and `workers` (told by their
        buildbot.tac), the commands of the Python it runs from into `into`."""
        read = self._registry or registry
        try:
            key = read(SERVICE_KEY)
        except PermissionError:
            return [f"{SERVICE}: its registry key is there but this user may not read it"]
        except OSError as e:
            return [f"{SERVICE}: its registry key could not be read ({type(e).__name__})"]
        if key is None:
            return []

        def values(sub: str) -> Mapping:
            try:
                return read(f"{SERVICE_KEY}\\{sub}") or {}
            except OSError:
                return {}

        cls = str(values("PythonClass").get("") or "")
        whose = ("Buildbot's worker service" if "buildbot_worker" in cls.lower() else
                 "Buildbot's master service" if "buildbot" in cls.lower() else "a service named as Buildbot's")
        start = key.get("Start")
        state, why = (self._service_state or service_state)(SERVICE)
        said = ", ".join(x for x in (whose, STARTS.get(start, "") if isinstance(start, int) else "",
                                     state or (f"its state not known: {why}" if why else "")) if x)
        program = _program(key.get("ImagePath"))
        for where in (program, cls):  # the environment it runs from (its program's or its class file's): commands
            site = SITE.search(where)
            if site:
                scripts = Path(where[:site.start()]) / "Scripts"
                for name in COMMANDS:
                    if (scripts / f"{name}.exe").is_file():
                        into[name].append(str(scripts / f"{name}.exe"))
                break
        given = str(values("Parameters").get("directories") or "")
        folders = [d.strip().strip('"') for d in given.split(";") if d.strip()][:FOLDERS_MOST]
        shown = []
        for d in folders:
            tac = Path(d) / TAC
            if tac.is_file():
                kind = tac_kind(tac)
                (workers if kind == "worker" else masters).append(d)
                shown.append(f"{d} (a {kind}'s)")
            else:
                shown.append(f"{d} (no {TAC}: the service runs none there)")
        runs = f"; it runs {', '.join(shown)}" if shown else "; it names no folder to run (its Parameters' directories)"
        return [f"{SERVICE}: {said}" + (f"; from {program}" if program else "") + runs]

    def looked(self) -> tuple[str, ...]:
        """Where it looks, in words."""
        if self.windows:
            return ("PATH", r"~\.local\bin", r"%APPDATA%\Python\Python3*\Scripts",
                    r"%LOCALAPPDATA%\Programs\Python\Python3*\Scripts", r"~\buildbot* (four folders down)",
                    *(str(d / "buildbot*") for d in self.drives),
                    f"the Windows service {SERVICE} (its registry key, the folders it runs)")
        places = ["PATH", "/usr/bin", "/usr/local/bin", "~/.local/bin", "~/buildbot* (four folders down)",
                  "/var/lib/buildbot", "/srv/buildbot*", "/opt/buildbot*"]
        if self.system == "darwin":
            places.insert(4, "/opt/homebrew/bin")
        else:
            places += ["systemd's unit folders (buildbot*.service)",
                       "/etc/init.d (buildbot, buildbot-worker, buildmaster)",
                       "the folders /etc/default's buildbot, buildmaster and buildbot-worker name"]
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
        units: list[str] = []
        scripts: list[str] = []
        services: list[str] = []
        if self.system == "linux":
            units = [str(p) for p in self._units()]
            scripts = [str(p) for p in self._scripts()]
            for folder in self._basedirs():
                tac = folder / TAC
                if tac.is_file():
                    (workers if tac_kind(tac) == "worker" else masters).append(str(folder))
        if self.windows:
            services = self._service(into, masters, workers)
        return Found(commands=_unique(commands), masters=_unique(masters), worker_commands=_unique(workers_cmd),
                     workers=_unique(workers), units=_unique(units), scripts=_unique(scripts),
                     services=tuple(services), looked=self.looked())
