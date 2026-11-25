"""Buildbot for Liminal (the user, 2026-11-22: a new class of platform plugins, Continuous Integration, with three
plugins in it: Jenkins, GoCD and Buildbot): a Buildbot master's builders, recent builds, workers and force schedulers,
read from its web server's REST API (the data API, version 2); whether Buildbot is installed on this machine; and a
build forced through a force scheduler once the platform's page has confirmed it. Drawn under the platform's
Continuous Integration plugins (SECTION "ci"; a platform that does not know the section draws it under Machine
plugins).

- Where (settings.py): the master's web address, BUILDBOT_URL (http://127.0.0.1:8010 unless set: the tutorial's master
  on this machine), with BUILDBOT_USER and BUILDBOT_PASSWORD for a master whose web UI asks a sign-in, each read through
  the plugin's login. The password goes to the master's /auth/login alone, never over plain http to another machine
  (only the name localhost itself and a loopback address are this machine), and is never said, logged or kept
  (client.py).
- Installed here (finders.py): its files alone say it: the buildbot command, a master's folder holding its buildbot.tac,
  the buildbot-worker command and a worker's folder; on Linux a systemd unit named buildbot*, an init script and the
  folders /etc/default's files name; on Windows Buildbot's own service (BuildBot), by its registry key; nothing is run
  to know it.
- What it reads: one GET of the web server's /config first (the versions its About page shows, Buildbot's among them,
  and the sign-in it takes), then the sign-in when a user is set and that sign-in takes a user and a password
  (UserPasswordAuth, HTPasswdAuth, CustomAuth; never NoAuth, RemoteUserAuth or an OAuth2 provider's) and /config again
  as that user, then one GET each of /api/v2/builders, /api/v2/builds (the 20 newest), /api/v2/workers and
  /api/v2/forceschedulers; kept READ_S, so the page's refreshes do not ask again, and never queued behind: while a read
  is under way another ask waits WAIT_S at most, then takes what was read before. A sign-in the master refused is not
  sent again until the settings change or Read again asks. A failure is said in words on the page, never raised.
- What it changes: a force scheduler's force (one JSON-RPC POST, sent once), confirmed on the page first: its fields
  are the scheduler's own, as its all_fields say them (fields.py), each value sent under the name the force takes it
  by, and every builder it starts is the list the page showed. Nothing is installed, started or stopped by this
  release: when no master answers, the page says how to install and start one (a virtual environment, activated, pip
  install 'buildbot[bundle]', buildbot create-master, buildbot-worker for the workers), with the documentation's
  addresses.

Nothing runs on its own: the plugin reads when the platform asks, holds no process, thread or connection between asks,
and forgets what it read when its settings change, after a force and when it is detached; a read under way then keeps
nothing of what it read (its generation is gone), though its asker gets it.

0.2.0 (Monday list item 34; service-containers-design §5.4, the user's answers of 2026-11-25: "Containers only",
"Containers too", "Seeded, PC-only first"): built on the library's ContainedService. A master and a worker beside it are
installed, started, stopped, updated and removed only as containers, through the container plugin you pick, in its
plans you approve on the page (recipe.py). Its sign-in is seeded before the first start (a PBKDF2 hash of
BUILDBOT_ADMIN_PASSWORD, never the password); it runs on this PC alone until that sign-in answers, then Expose… opens
it to your network. Its usage data is never sent. Force… is asked from its page alone (PAGE_ONLY_HOOKS). A master you
installed yourself is still found and read; how to install one natively is a line, not a table."""
from __future__ import annotations

import hashlib
import json
import secrets as _secrets
import os
import platform
import re
import threading
import time
from dataclasses import dataclass, field
from urllib.parse import quote

from liminal_libs.instances import Refusal
from liminal_libs.machines.containedservice import ContainedService, Pace

from . import apis as cards
from . import recipe
from .client import API, FORCE_S, LOOK_S, BuildbotError, Master, address, no_basic
from .fields import FIELDS_MOST, TEXT_MOST, fields_of, form_field, offered, typed, typed_fields, unfillable
from .finders import Finder, Found
from .settings import KEYS, Settings
from .settings import read as read_settings

__version__ = "0.2.0"
READ_S = 30.0  # what was read is kept this long: the platform's page asks every few seconds; a force reads again
WAIT_S = 2.0  # seconds an ask waits for a read under way, at most: then it takes what was read before
BUILDS = 20  # the newest builds read
ROWS = 200  # a table's rows at most
FORMS = 20  # the force schedulers given a form each, at most
LISTINGS = (("builders", None), ("builds", {"order": "-buildid", "limit": BUILDS}), ("workers", None),
            ("forceschedulers", None))  # what a read asks under /api/v2, in this order, one GET each
LABELS = {"builders": "builders", "builds": "recent builds", "workers": "workers",
          "forceschedulers": "force schedulers"}
RESULTS = {0: "success", 1: "warnings", 2: "failure", 3: "skipped", 4: "exception", 5: "retry", 6: "cancelled"}
# a force scheduler's name as the master's REST API takes it in an address (/forceschedulers/i:schedulername: ASCII
# letters, digits, _ and -); Buildbot's own names take more letters, but such a one cannot be asked by its address
SCHEDULER = re.compile(r"^[A-Za-z_-][A-Za-z0-9_-]{0,99}$")
DOCS = "https://docs.buildbot.net/latest/"
FIRST_RUN = DOCS + "tutorial/firstrun.html"
BUILDMASTER = DOCS + "manual/installation/buildmaster.html"
WORKER = DOCS + "manual/installation/worker.html"
LAUNCHING = DOCS + "manual/installation/misc.html#launching-the-daemons"


def cell(text, sub=None):
    return {"text": text, "sub": sub} if sub else text


def plural(n: int, word: str) -> str:
    return f"{n:,} {word}{'' if n == 1 else 's'}"


def number(value) -> float | None:
    """A number of JSON's (an int or a float, never a bool); None for anything else."""
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def line(value, most: int = 80) -> str:
    """A value the master gave, as a line of text (a string or a number), cut to `most` characters."""
    if value is None or isinstance(value, (bool, dict, list)):
        return ""
    said = " ".join(str(value).split())
    return said if len(said) <= most else said[:most - 1] + "…"


def clock(seconds) -> str:
    """A moment (seconds since the epoch) at this machine's local time: Nov 22 21:04."""
    t = number(seconds)
    if not t or t <= 0:
        return "–"
    try:
        return time.strftime("%b %d %H:%M", time.localtime(t))
    except (OverflowError, OSError, ValueError):
        return "–"


def span(seconds) -> str:
    """A length of time in words: 45 s, 3 min 20 s, 1 h 05 min, 2 d 3 h."""
    s = int(max(0.0, number(seconds) or 0.0))
    if s < 60:
        return f"{s} s"
    m, s = divmod(s, 60)
    if m < 60:
        return f"{m} min {s:02d} s" if s else f"{m} min"
    h, m = divmod(m, 60)
    if h < 48:
        return f"{h} h {m:02d} min"
    d, h = divmod(h, 24)
    return f"{d} d {h} h"


def result_of(build: dict) -> str:
    """A build's result in words (Buildbot's result codes): success, warnings, failure ...; running while it runs."""
    code = build.get("results")
    if isinstance(code, int) and not isinstance(code, bool):
        return RESULTS.get(code, f"result {code}")
    return "running" if not build.get("complete") else "no result"


def connected(worker: dict) -> bool:
    """A worker connected to a master: its connected_to names one."""
    return bool(worker.get("connected_to"))


def builder_ids(worker: dict) -> set:
    """The builders a worker is configured on, by id."""
    return {c.get("builderid") for c in worker.get("configured_on") or () if isinstance(c, dict)}


def capped(rows: list, note: str, total: int | None = None) -> tuple[list, str]:
    if len(rows) > ROWS:
        return rows[:ROWS], f"{note} · the first {ROWS} of {max(len(rows), total or 0):,}"
    return rows, note


def starts_of(scheduler: dict) -> list[str]:
    """The builders a force scheduler starts, by name, as the master says them."""
    return [b for b in scheduler.get("builder_names") or () if isinstance(b, str)]


def told(e: BuildbotError, signed: str) -> BuildbotError:
    """A refusal (401, 403) said with why no sign-in went with the request (`signed`), when none did; else the error
    as it is."""
    return BuildbotError(f"{e}; {signed}", e.status) if signed and e.refused else e


def joined(names) -> str:
    """Builders' names as a form's fixed field holds them, ", " between them (what Force… confirmed)."""
    return ", ".join(names)


def install_steps(system: str) -> list[tuple[str, object, str, str]]:
    """The documentation's steps to install and start Buildbot (its tutorial's First run), each (what, the command as
    this system's shell types it: a cell with another shell's way, or a note, under it where one differs; its page;
    what of it the look here finds: "commands", "masters", "worker_commands", "workers", or "" for a step it cannot
    see). Git comes first (the sample's runtests build checks its code out with it); the sandbox is activated once,
    as the tutorial does, and every step after it is typed in that shell: so the worker started there runs its builds
    with the sandbox on its PATH, where they find its programs (the runtests build runs Twisted's trial). On Windows
    each is typed in the home folder, the Command Prompt's way, with PowerShell's under it where it differs."""
    if system == "windows":
        master, worker = "buildbot\\master", "buildbot\\worker"
        made = "py -m venv buildbot\\sandbox"
        activate = cell("buildbot\\sandbox\\Scripts\\activate.bat",
                        "in PowerShell: .\\buildbot\\sandbox\\Scripts\\Activate.ps1 (where PowerShell refuses to run "
                        "it, the Command Prompt's way)")
        bundle = 'pip install "buildbot[bundle]"'
        sample = f"copy {master}\\master.cfg.sample {master}\\master.cfg"
    else:
        master, worker = "~/buildbot/master", "~/buildbot/worker"
        made = "python3 -m venv ~/buildbot/sandbox"
        activate = "source ~/buildbot/sandbox/bin/activate"
        bundle = "pip install 'buildbot[bundle]'"
        if system == "linux":
            bundle = cell(bundle, "on Linux pip may need these first (the tutorial's): sudo apt-get install "
                                  "build-essential python3-dev libssl-dev libffi-dev on Debian and Ubuntu, sudo yum "
                                  "install gcc python3-devel openssl-devel libffi-devel on RHEL, CentOS and Fedora")
        sample = f"mv {master}/master.cfg.sample {master}/master.cfg"
    return [
        ("Git on PATH: the sample's runtests build checks its code out with it", "git --version", FIRST_RUN, ""),
        ("A virtual environment for it", made, FIRST_RUN, ""),
        ("It activated, as the tutorial does: the steps below are typed in this shell", activate, FIRST_RUN, ""),
        ("Buildbot in it, its web UI with it (the bundle)", bundle, FIRST_RUN, "commands"),
        ("A master", f"buildbot create-master {master}", BUILDMASTER, "masters"),
        ("Its configuration, from the sample (its web UI on port 8010)", sample, BUILDMASTER, ""),
        ("Start it", f"buildbot start {master}", LAUNCHING, ""),
        ("A worker's code", "pip install buildbot-worker", WORKER, "worker_commands"),
        ("A worker, as the sample's master knows it",
         f"buildbot-worker create-worker {worker} localhost example-worker pass", WORKER, "workers"),
        ("Start the worker, in that shell: its builds run with the sandbox on their PATH (runtests runs trial from it)",
         f"buildbot-worker start {worker}", LAUNCHING, ""),
    ]


@dataclass(frozen=True)
class Reading:
    """One read: when (monotonic, for keeping it; the wall's, for the page), the address read ("" when BUILDBOT_URL is
    none), what is installed here, whether a web server answered there (`reachable`: any HTTP status) and whether
    Buildbot's REST API did (`answering`: its builders read), why not in words, what /config said (the versions by
    name, the title, the sign-in it names), the user signed in as, the four listings (None: not read) with the totals
    the master counts and why one was not read, the settings' and the sign-in's words, and whether it only says that
    another asker's read is under way (`underway`: nothing of the master read, never kept)."""

    at: float
    when: float
    url: str
    found: Found
    reachable: bool = False
    answering: bool = False
    why: str = ""
    versions: dict = field(default_factory=dict)
    title: str = ""
    auth: str = ""
    signed_in: str = ""
    builders: tuple | None = None
    builds: tuple | None = None
    workers: tuple | None = None
    schedulers: tuple | None = None
    totals: dict = field(default_factory=dict)
    problems: dict = field(default_factory=dict)
    notes: tuple = ()
    underway: bool = False

    @property
    def present(self) -> bool:
        """Buildbot installed here, or a web server answering at its address."""
        return self.found.any or self.reachable

    @property
    def version(self) -> str:
        """Buildbot's version as the master's /config says it ("" when it says none)."""
        return next((v for k, v in self.versions.items() if k.lower() == "buildbot"), "")


def _seen() -> dict:
    return {"requests": 0, "failed": 0, "status": 0, "ms": 0.0, "at": None, "error": ""}


class _Runtime:
    """What the plugin keeps while it lives, shared by its copies (the registry hands out a shallow one): the last
    reading, what its requests came to (its API facts), the generation of what is read (moved on by each forget: a
    read under way keeps nothing once its generation is gone), and the sign-in the master refused (a salted digest of
    its user and password, never the password: not sent again until the settings change or Read again asks)."""

    def __init__(self):
        self.lock = threading.Lock()
        self.reading_lock = threading.Lock()  # one read at a time: another asker waits WAIT_S at most
        self.reading: Reading | None = None
        self.seen = _seen()
        self.generation = 0
        self.refused = ""
        self.salt = os.urandom(16)


def versions_of(config) -> dict:
    """The versions a master's /config names ([[name, version], ...]: Python's, Buildbot's, Twisted's, then the www
    versions option's), by name, the first of each name."""
    out: dict[str, str] = {}
    given = config.get("versions") if isinstance(config, dict) else None
    for pair in given if isinstance(given, list) else ():
        if isinstance(pair, (list, tuple)) and len(pair) == 2 and all(isinstance(x, str) for x in pair):
            out.setdefault(line(pair[0], 40), line(pair[1], 40))
    return out


class BuildbotPlugin(ContainedService):
    """A Buildbot master for the platform: present when Buildbot is installed here or a web server answers at the
    master's address, valid when its REST API is read."""

    name = "buildbot"
    title = "Buildbot"
    about = ("A Buildbot master's builders, recent builds, workers and force schedulers, read from its REST API (this "
             "machine's at http://127.0.0.1:8010, or the address set), whether Buildbot is installed here, and a build "
             "forced through a force scheduler once confirmed; how to install and start it when no master answers")
    api = "2.2"
    # what it attaches to (plugin API 2.2): the master's REST API, with its /config and /auth/login (apis.py)
    apis = cards.APIS
    # the Continuous Integration plugins, after the cloud's (760-765): Buildbot after its siblings, GoCD (780) and
    # Jenkins (810), last as the user named the three (Jenkins, GoCD, Buildbot)
    order = 772  # the Continuous Integration plugins in the user's naming: Jenkins 770, GoCD 771, Buildbot 772
    ICON = "buildbot"
    SECTION = "ci"  # drawn under the platform's Continuous Integration plugins; "machine" on a platform before it
    HOOKS = (*ContainedService.HOOKS, "refresh", "force")
    LAN_FIRST = False  # seeded sign-in, this PC alone first (the user, 2026-11-25: "Seeded, PC-only first")
    DEFAULT_MEMORY_MB = recipe.MEMORY_MB
    # a force runs whatever its builders do: asked from the platform's page alone (design §5.4), with the base's five
    PAGE_ONLY_HOOKS = ("force",)
    READ_HOOKS = ("refresh",)  # its own read beside its bases' (force changes the master: a build is asked of it)
    INTERNAL_NOTES = (
        "force sends one JSON-RPC call (POST /api/v2/forceschedulers/<name>, method force) once its scheduler is read "
        "from the master again (and its builder, by name): each value under the name its all_fields give the field, "
        "every builder as the page listed them; refresh reads the master again now.",
        "Every request goes to BUILDBOT_URL alone; the password to its /auth/login alone, and only when its /config "
        "names a sign-in that takes one. A sign-in it refused is not sent again until the settings change or Read "
        "again asks.",
    )
    keys = KEYS  # its settings, kept through the platform's login: the master's address, a user and its password

    def __init__(self, http=None, find=None, clock=None, wall=None, system=None, pace: Pace | None = None, pins=None):
        ContainedService.__init__(self, pace)
        self._pins = pins  # recipe.PINS unless a test's
        self._http = http  # (method, url, headers, body, timeout) -> (status, headers, body): urllib's unless given
        self._find = find  # () -> finders.Found: a look at this machine (finders.Finder) unless given
        self._clock = clock or time.monotonic
        self._wall = wall or time.time
        self._system = system  # "windows", "linux" or "darwin" (a test's): this machine's unless given
        self._rt = _Runtime()

    # -- reading ---------------------------------------------------------------------------------------------------
    def _system_name(self) -> str:
        return str(self._system or platform.system() or "").lower()

    def _found(self) -> Found:
        try:
            return self._find() if self._find is not None else Finder(system=self._system).find()
        except Exception as e:  # noqa: BLE001 - a look that failed: nothing found, and why
            return Found(trouble=f"{type(e).__name__}: {e}")

    def _noted(self, status: int, seconds: float, error: str, generation: int) -> None:
        """What one request came to, for its API facts: counted, the last kept (its words hold no secret); nothing of
        a generation that is gone (a request of a read under way when the plugin forgot, or was detached)."""
        with self._rt.lock:
            if generation != self._rt.generation:
                return
            seen = self._rt.seen
            seen["requests"] += 1
            seen["failed"] += 1 if (status == 0 or error) else 0
            seen.update(status=status, ms=seconds * 1000.0, at=self._wall(), error=error)

    def _master(self, s: Settings, timeout: float, generation: int) -> Master:
        return Master(s.where, user=s.user if s.sign_in else "", password=s.password if s.sign_in else "",
                      transport=self._http, timeout=timeout, clock=self._clock,
                      note=lambda status, seconds, error: self._noted(status, seconds, error, generation))

    def _key(self, s: Settings) -> str:
        """A sign-in's user and password as the runtime remembers a refused one: their salted digest."""
        return hashlib.sha256(self._rt.salt + f"{s.user}\0{s.password}".encode("utf-8", "surrogatepass")).hexdigest()

    def _sign_in(self, master: Master, s: Settings, auth, generation: int) -> str:
        """The sign-in, when a user is set and the master's /config names a sign-in that takes a user and a password
        at /auth/login (or names none it could be read for): "" when signed in; else why not, in words. One the master
        refused is not sent again (the runtime remembers it) until the settings change or Read again asks.
        BuildbotError when no answer came."""
        if not s.sign_in:
            return ""
        skip = no_basic(auth)
        if skip:
            return skip
        key = self._key(s)
        with self._rt.lock:
            refused = self._rt.refused == key
        if refused:
            return (f"the master refused the sign-in as {s.user} before: it is not sent again until the settings "
                    "change or Read again asks; read as anyone")
        said = master.sign_in(line(auth.get("name"), 40) if isinstance(auth, dict) else "")
        if master.refused:
            with self._rt.lock:
                if self._rt.generation == generation:
                    self._rt.refused = key
        return said

    def _read(self, fresh: bool = False) -> Reading:
        """The master and this machine read, kept READ_S (`fresh`: read now). While another read is under way this
        waits WAIT_S at most, then takes what was read before (or a reading saying one is under way), so the page's
        asks never queue behind a slow master. A read whose generation is gone by its end (its settings changed, a
        force, a detach) gives its asker what it read and keeps nothing of it."""
        rt = self._rt
        with rt.lock:
            kept = rt.reading
        if kept is not None and not fresh and self._clock() - kept.at < READ_S:
            return kept
        got = rt.reading_lock.acquire(timeout=WAIT_S) if WAIT_S > 0 else rt.reading_lock.acquire(blocking=False)
        if not got:
            with rt.lock:
                kept = rt.reading
            return kept if kept is not None else self._underway()
        try:
            with rt.lock:
                kept, generation = rt.reading, rt.generation
            if kept is not None and not fresh and self._clock() - kept.at < READ_S:
                return kept  # read meanwhile by the asker waited on
            reading = self._ask(self._settings(), self._found(), generation)
            with rt.lock:
                if rt.generation == generation:
                    rt.reading = reading
            return reading
        finally:
            rt.reading_lock.release()

    def _underway(self) -> Reading:
        """A reading saying another asker's read of the master is under way (never kept): this machine is looked at
        all the same."""
        s = self._settings()
        url = s.where.base if s.where is not None else ""
        why = f"a read of the master at {url} is under way: its answer is not in yet" if url else s.problems[0]
        return Reading(self._clock(), self._wall(), url, self._found(), why=why, notes=tuple(s.problems),
                       underway=bool(url))

    def _ask(self, s: Settings, found: Found, generation: int) -> Reading:
        """One read of the master (the module docstring's GETs, in order): a request that gets no answer before any
        has means nothing answers there; one that gets none after leaves the rest not asked."""
        at, when = self._clock(), self._wall()
        notes = list(s.problems)
        if s.where is None:
            return Reading(at, when, "", found, why=s.problems[0], notes=tuple(notes))
        url = s.where.base
        master = self._master(s, LOOK_S, generation)
        got: dict = {}
        problems: dict = {}
        statuses: dict = {}
        stopped = ""
        try:
            got["config"] = master.get("/config")
        except BuildbotError as e:
            if not e.answered:
                return Reading(at, when, url, found, why=f"nothing answers at {url}: {e}", notes=tuple(notes))
            problems["config"], statuses["config"] = str(e), e.status
        config = got.get("config") if isinstance(got.get("config"), dict) else {}
        if "config" in got and not config:
            problems["config"] = "GET /config: its answer is no configuration"
        auth = config.get("auth") if isinstance(config.get("auth"), dict) else None
        try:
            said = self._sign_in(master, s, auth, generation)
        except BuildbotError as e:  # its sign-in failed: answered (said, read as anyone), or no answer came
            said = f"the master's sign-in failed ({e}): read as anyone" if e.answered else ""
            stopped = "" if e.answered else f"the master stopped answering ({e})"
        if said:
            notes.append(said)
        signed_in = master.signed_in
        if signed_in and not stopped:  # who its /config says is signed in, as that user
            try:
                again = master.get("/config")
                user = again.get("user") if isinstance(again, dict) else None
                if isinstance(user, dict) and user.get("anonymous") is True:
                    notes.append(f"the master set a session cookie for {signed_in}, but its /config says no one is "
                                 "signed in: read as anyone")
                    signed_in = ""
            except BuildbotError as e:
                if not e.answered:
                    stopped = f"the master stopped answering ({e})"
        for kind, params in LISTINGS:
            if stopped:
                problems[kind] = f"not asked: {stopped}"
                continue
            try:
                got[kind] = master.listing(f"{API}/{kind}", kind, params)
            except BuildbotError as e:
                problems[kind], statuses[kind] = str(e), e.status
                if not e.answered:
                    stopped = f"the master stopped answering ({e})"
        rows = {kind: tuple(got[kind][0]) for kind, _ in LISTINGS if kind in got}
        answering = "builders" in rows
        unread = "" if answering else self._unread(url, signed_in, notes, problems.get("builders", ""),
                                                   statuses.get("builders", 0))
        return Reading(
            at, when, url, found, reachable=master.answered, answering=answering, why=unread,
            versions=versions_of(config), title=line(config.get("title")),
            auth=line(auth.get("name"), 40) if isinstance(auth, dict) else "",
            signed_in=signed_in, builders=rows.get("builders"), builds=rows.get("builds"), workers=rows.get("workers"),
            schedulers=rows.get("forceschedulers"), totals={kind: got[kind][1] for kind, _ in LISTINGS if kind in got},
            problems=problems, notes=tuple(notes))

    @staticmethod
    def _unread(url: str, signed_in: str, notes: list[str], problem: str, status: int) -> str:
        """Why a master that answers could not be read, in words, with what to do (`notes`: why it was not signed in
        to, when a user was set)."""
        if status in (401, 403):
            if signed_in:
                return (f"the master at {url} refuses its builders to {signed_in} (HTTP {status}): a user its authz "
                        "rules let read them")
            refused = f"the master at {url} refuses its builders to anyone not signed in (HTTP {status})"
            if notes:
                return f"{refused}: {'; '.join(notes)}"
            return f"{refused}: set BUILDBOT_USER and BUILDBOT_PASSWORD (a user it knows)"
        if status == 404:
            return (f"something answers at {url}, but not Buildbot's REST API ({problem}): is BUILDBOT_URL the "
                    "master's web address, as its web UI is opened?")
        return f"the master at {url} could not be read: {problem or 'its builders were not read'}"

    def _forget(self) -> None:
        """What was read is forgotten, and a read under way keeps nothing of what it reads: its generation is gone."""
        with self._rt.lock:
            self._rt.reading = None
            self._rt.generation += 1

    # -- its containers (ContainedService) ------------------------------------------------------------------------
    def _pair(self, name: str) -> str:
        try:
            got = (self.login.variables([name]) or {}) if self.login is not None else {}
        except Exception:  # noqa: BLE001 - a login that cannot be asked: none set
            return ""
        return str(got.get(name) or "")

    def _settings(self) -> Settings:
        """Its settings through its login: BUILDBOT_URL, else its container's port; with no user of yours set, the
        seeded admin's sign-in while a master of its is placed."""
        admin = None
        if self.service_present():
            password = self._pair(recipe.ADMIN_PASSWORD)
            admin = (recipe.ADMIN, password) if password else None
        return read_settings(self.login, self.address(), admin)

    def spec_for(self, system, name, options):
        """Buildbot's recipe (recipe.py): its master, its sign-in seeded as a hash, and a worker beside it. The
        worker's password is made here once, and kept through the login."""
        fit = bool(options.get("fit"))
        if not fit and not self._pair(recipe.WORKER_PASSWORD) and self.login is not None:
            self.login.save(recipe.WORKER_PASSWORD, _secrets.token_urlsafe(24))
        return recipe.spec(system, name, options, "" if fit else self._pair(recipe.ADMIN_PASSWORD), self._pins)

    def _config_at(self, hosted) -> dict:
        master = Master(address(self.address(hosted)), transport=self._http, timeout=LOOK_S, clock=self._clock)
        got = master.get("/config")
        if not isinstance(got, dict):
            raise BuildbotError("GET /config: its answer is not a master's configuration")
        return got

    def ready(self, hosted):
        """Whether the master answers at its container's port: its /config."""
        try:
            self._config_at(hosted)
        except (BuildbotError, ValueError) as e:
            return False, str(e)
        return True, ""

    def lan_ready(self, hosted):
        """Whether its seeded sign-in answers: its /config names a sign-in, not NoAuth."""
        try:
            auth = self._config_at(hosted).get("auth")
        except (BuildbotError, ValueError) as e:
            return False, str(e)
        name = str(auth.get("name") or "") if isinstance(auth, dict) else ""
        if not name or name == "NoAuth":
            return False, "its /config names no sign-in (NoAuth): it stays on this PC"
        return True, ""

    def after(self, action, hosted, line):
        """Read again after any change of its containers."""
        self._forget()
        if action == "install":
            return [f"Buildbot runs at {self.address(hosted)}: sign in as admin with {recipe.ADMIN_PASSWORD}; its "
                    "worker liminal-worker builds the hello builder"]
        return []

    def settings_changed(self) -> None:
        """Its settings kept anew on the platform's page: what was read is forgotten (a read under way keeps nothing),
        and a sign-in the master refused may be sent again, so the next look asks the address now set, as the user
        now set."""
        with self._rt.lock:
            self._rt.refused = ""
        self._forget()

    def detach(self) -> None:
        """Detached (the platform ending, the plugin turned off): what it read goes, what its requests came to and the
        sign-in it remembers refused, and a read under way keeps nothing; nothing of its own was running."""
        with self._rt.lock:
            self._rt.reading = None
            self._rt.seen = _seen()
            self._rt.refused = ""
            self._rt.generation += 1
        super().detach()

    # -- the hooks ---------------------------------------------------------------------------------------------------
    def present(self) -> bool:
        """Whether Buildbot is installed here (its files say it) or a web server answers at the master's address."""
        try:
            return self._read().present
        except Exception:  # noqa: BLE001 - one that cannot say is not there
            return False

    def status(self) -> dict:
        """What the platform's page draws (kept READ_S): present, valid and why not, the summary, the facts, the tables,
        the Force… forms (while the master is read) and Read again; what could not be read, in words (`problem`)."""
        r = self._read()
        out: dict = {"present": r.present or self.service_present(), "summary": self._summary(r),
                     "valid": r.answering or self.service_valid(), "why": ""}
        if not r.answering:
            out["note"] = r.why or "the master was not read"  # said, never invalid: it can be placed in a container
        out.update(self._facts(r))
        out["tables"] = self._tables(r)
        out["forms"] = self._forms(r) if r.answering else []
        out["actions"] = [{"hook": "refresh", "args": [], "title": "Read again",
                           "note": f"asks the master again now (what was read is kept {READ_S:g} s)"}]
        if self.app is not None:  # where it can run, asked of the container plugins through its app
            svc = self.service_status()
            out["tables"] += svc.get("tables") or []
            out["forms"] += svc.get("forms") or []
        trouble = list(r.notes)
        if r.answering:
            trouble += [f"its {LABELS[kind]} could not be read: {why}" for kind, why in r.problems.items()
                        if kind in LABELS]
        if r.found.trouble:
            trouble.append(f"the look for Buildbot here failed: {r.found.trouble}")
        if trouble:
            out["problem"] = "; ".join(trouble)
        return out

    def api_facts(self) -> dict:
        """What it learned of the master's API while it ran (plugin API 2.2), asking nothing: the master as last read
        (its address, its Buildbot version, its sign-in, when), the requests made and the last answer. Nothing asked
        yet: {}."""
        with self._rt.lock:
            r, seen = self._rt.reading, dict(self._rt.seen)
        if r is None and not seen["requests"]:
            return {}
        facts: dict[str, str] = {}
        if r is not None:
            facts["Read"] = f"{clock(r.when)} (kept {READ_S:g} s)"
            if r.url:
                facts["Master"] = r.url
            if r.version:
                facts["Buildbot"] = r.version
            if r.reachable:
                facts["Signed in"] = f"as {r.signed_in}" if r.signed_in else "no: read as anyone"
            if r.auth:
                facts["Its sign-in"] = r.auth
        facts["Requests"] = f"{seen['requests']:,} made" + (f", {seen['failed']:,} failed" if seen["failed"] else "")
        if seen["at"]:
            facts["Last answer"] = ((f"HTTP {seen['status']} in {seen['ms']:.0f} ms" if seen["status"] else
                                     "none (no connection)") + f", {clock(seen['at'])}")
        if seen["error"]:
            facts["Last trouble"] = seen["error"][:200]
        return {cards.REST: facts}

    def refresh(self) -> dict:
        """The master read again now (what was read is kept READ_S otherwise), a sign-in it refused before sent once
        more."""
        with self._rt.lock:
            self._rt.refused = ""
            before = self._rt.reading
        r = self._read(fresh=True)
        if r.underway or (before is not None and r is before):
            return {"said": "a read of the master is under way already: Read again once it has ended", "ok": False,
                    "lines": [r.why] if r.underway else []}
        if not r.answering:
            return {"said": f"read again: {r.why}", "ok": False, "lines": list(r.notes)}
        workers = r.workers or ()
        lines = [f"{plural(len(r.builders), 'builder')}, {plural(len(r.builds or ()), 'recent build')}, "
                 f"{plural(len(workers), 'worker')} ({sum(1 for w in workers if connected(w))} connected), "
                 f"{plural(len(r.schedulers or ()), 'force scheduler')}"]
        lines += [f"its {LABELS[kind]} could not be read: {why}" for kind, why in r.problems.items() if kind in LABELS]
        return {"said": f"read the master at {r.url} again now", "ok": True, "lines": lines + list(r.notes)}

    def force(self, scheduler, builder=None, starts=None, fields=None, *values) -> dict:
        """A build forced through the force scheduler named, as its button in the master's web UI forces one: of the
        builder named (one the scheduler starts), or of every builder it starts, with the values typed for its fields.
        `starts`: the builders the page listed, ", " between them (refused when the scheduler now starts others);
        `fields`: the names its all_fields give the fields typed, ", " between them; `values`: one each, in that order
        (None: the scheduler's own). The scheduler is read from the master again first (and the builder, by its name,
        for its id as the web UI sends it); then one JSON-RPC call is sent, once: POST /api/v2/forceschedulers/<name>
        {"method": "force"}, each value under its field's name, every builder by name (builderNames: the master adds
        none). Refused in words before it is sent for a name that is none, a value that cannot be one, a field the
        scheduler does not take, fixes or hides, one it needs that was not given, and a scheduler or a builder the
        master does not have."""
        name = str(scheduler if scheduler is not None else "").strip()
        if not SCHEDULER.match(name):
            raise ValueError(f"not a force scheduler's name: {name[:60]!r} (ASCII letters, digits, _ and -)")
        chosen = typed(builder, "a builder's name")
        given = typed_fields(fields, values)
        s = self._settings()
        if s.where is None:
            raise ValueError(s.problems[0])
        url = s.where.base
        with self._rt.lock:
            generation = self._rt.generation
        master = self._master(s, LOOK_S, generation)
        path = f"{API}/forceschedulers/{quote(name, safe='')}"
        try:
            config = master.get("/config")
        except BuildbotError as e:
            if not e.answered:
                raise
            config = {}
        auth = config.get("auth") if isinstance(config, dict) and isinstance(config.get("auth"), dict) else None
        signed = self._sign_in(master, s, auth, generation)
        try:
            found, _ = master.listing(path, "forceschedulers")
        except BuildbotError as e:
            if e.status == 404:
                raise ValueError(f"the master at {url} has no force scheduler named {name}") from None
            raise told(e, signed) from None
        sched = next((x for x in found if x.get("name") == name), None)
        if sched is None:
            raise ValueError(f"the master at {url} has no force scheduler named {name}")
        current = starts_of(sched)
        params = self._params(sched, given, name)
        if chosen:
            if chosen not in current:
                raise ValueError(f"{name} does not start {chosen}: it starts {joined(current) or 'no builder'}")
            params["builderid"] = self._builder_id(master, chosen, url)
        else:
            if not current:
                raise ValueError(f"{name} starts no builder: there is nothing to force")
            if starts is not None and str(starts) != joined(current):
                raise ValueError(self._moved(name, str(starts), current))
            params["builderNames"] = current
        try:
            result = master.control(path, "force", params, timeout=FORCE_S)
        except BuildbotError as e:
            if not e.answered:
                raise BuildbotError(f"{e}: no answer came, so it may have been done (Read again shows it under Recent "
                                    "builds)") from None
            raise told(e, signed) from None
        finally:
            self._forget()
        what = chosen or f"every builder {name} starts ({joined(current)})"
        lines = self._made(result)
        typed_in = [k for k in params if k not in ("builderid", "builderNames")]
        lines.append(f"with {', '.join(typed_in)} as typed, the rest the scheduler's own" if typed_in else
                     "with the scheduler's own values")
        if signed:
            lines.append(signed)
        lines.append("it runs once a worker is free: Read again shows it under Recent builds")
        return {"said": f"a build of {what} asked of the master at {url}", "lines": lines, "ok": True}

    @staticmethod
    def _moved(name: str, confirmed: str, current: list[str]) -> str:
        """The words of a force refused because the scheduler's builders are no longer those the page listed."""
        was = [n for n in confirmed.split(", ") if n]
        more = [n for n in current if n not in was]
        fewer = [n for n in was if n not in current]
        parts = ([f"now starts {joined(more)} too"] if more else []) + (
            [f"no longer starts {joined(fewer)}"] if fewer else [])
        said = " and ".join(parts) or f"now starts {joined(current)}"
        return f"{name} {said}: review it again (Read again shows what it starts)"

    @staticmethod
    def _params(sched: dict, given: dict, name: str) -> dict:
        """The force's params from the values typed, each under its field's own name (its fullName), checked against
        the scheduler as just read: ValueError in words, before anything is sent, for a field it does not take, one it
        fixes or hides or that this page cannot fill, a value that is not the field's, and a field it needs that was
        not given."""
        fields: dict = {}
        for f in fields_of(sched):
            fields.setdefault(f.full, f)
        params: dict = {}
        for full, value in given.items():
            f = fields.get(full)
            if f is None:
                raise ValueError(f"{name} takes no field {full}: review it again (Read again shows its fields)")
            why = f.not_offered()
            if why:
                raise ValueError(f"{name}'s {f.label} ({full}) takes no value from this page: {why}")
            params[full] = f.value(value)
        missing = unfillable(list(fields.values()))
        if missing is not None:
            raise ValueError(f"{name} needs its {missing.label} ({missing.full}), which this page cannot fill "
                             f"({missing.not_offered()}): force it from the master's web UI")
        needed = next((f for f in fields.values() if f.required and f.kind != "fixed" and f.full not in params), None)
        if needed is not None:
            raise ValueError(f"{name} needs its {needed.label} ({needed.full}): give it")
        return params

    @staticmethod
    def _builder_id(master: Master, name: str, url: str) -> int:
        """A builder's id, read from the master by its name: the collection filtered by it (?name=, one row or none),
        never an address built of the name (one of digits alone is taken there for an id)."""
        rows, _ = master.listing(f"{API}/builders", "builders", {"name": name})
        found = next((b for b in rows if b.get("name") == name), None)
        bid = found.get("builderid") if found else None
        if not isinstance(bid, int) or isinstance(bid, bool):
            raise ValueError(f"the master at {url} has no builder named {name}")
        return bid

    @staticmethod
    def _made(result) -> list[str]:
        """What the master made of a force, in words: its buildset and build requests ([bsid, {builderid: brid}])."""
        if isinstance(result, list) and len(result) == 2 and isinstance(result[0], int) and isinstance(result[1], dict):
            ids = [str(v) for v in result[1].values() if isinstance(v, int) and not isinstance(v, bool)]
            requests = f", build request{'' if len(ids) == 1 else 's'} {', '.join(ids)}" if ids else ""
            return [f"buildset {result[0]}{requests}"]
        return [f"the master answered: {line(json.dumps(result, default=str), 200)}"]

    # -- what the platform's page draws ------------------------------------------------------------------------------
    def _summary(self, r: Reading) -> str:
        if r.underway:
            return f"Buildbot at {r.url}: a read is under way"
        if not r.answering:
            if not r.url:
                return "BUILDBOT_URL is not an address"
            if r.reachable:
                return f"Buildbot at {r.url} could not be read"
            here = "Buildbot is installed here" if r.found.any else "Buildbot is not installed here"
            return f"{here}; nothing answers at {r.url}"
        said = f"Buildbot {r.version} at {r.url}" if r.version else f"Buildbot at {r.url}"
        said += f" · {plural(len(r.builders), 'builder')}"
        if r.workers is not None:
            said += f" · {sum(1 for w in r.workers if connected(w))} of {plural(len(r.workers), 'worker')} connected"
        if r.builds:
            said += f" · last build: {result_of(r.builds[0])}"
        return said

    def _facts(self, r: Reading) -> dict:
        out: dict = {"address": r.url or "none: BUILDBOT_URL is not an address"}
        if r.reachable:
            if r.version:
                others = ", ".join(f"{k} {v}" for k, v in r.versions.items() if k.lower() in ("twisted", "python"))
                out["version"] = f"Buildbot {r.version}" + (f" ({others})" if others else "")
            else:
                out["version"] = "not said" + (f" ({r.problems['config']})" if "config" in r.problems else
                                               " (its /config names none)")
            if r.title:
                out["title"] = r.title
            who = f"as {r.signed_in}" if r.signed_in else "none: read as anyone"
            out["signIn"] = who + (f" (the master's: {r.auth})" if r.auth else "")
        out["here"] = r.found.words()
        out["readAt"] = f"{clock(r.when)} (kept {READ_S:g} s; Read again asks now)"
        return out

    def _tables(self, r: Reading) -> list[dict]:
        if r.underway:
            return [self._here_table(r)]
        if not r.answering:
            return [self._here_table(r), self._install_table(r)]  # 0.2.0: beside Install… in a container
        forcing = self._forcing(r)
        return [self._builders_table(r, forcing), self._builds_table(r), self._workers_table(r),
                self._schedulers_table(r), self._here_table(r)]

    @staticmethod
    def _no_form(s: dict) -> str:
        """Why a force scheduler gets no Force… here, in words; "" when it gets one."""
        name = s.get("name")
        if not isinstance(name, str) or not SCHEDULER.match(name):
            return ("its name is not one the master's REST API takes in an address (ASCII letters, digits, _ and -): "
                    "force it from the master's web UI")
        if not starts_of(s):
            return "it starts no builder"
        fields = fields_of(s)
        missing = unfillable(fields)
        if missing is not None:
            return (f"it needs its {missing.label} ({missing.full}), which this page cannot fill "
                    f"({missing.not_offered()}): force it from the master's web UI")
        many = len(offered(fields))
        if many > FIELDS_MOST:
            return (f"it has {many} fields, more than a form here holds ({FIELDS_MOST}): force it from the master's "
                    "web UI")
        return ""

    def _schedulers(self, r: Reading) -> list[dict]:
        """The force schedulers given a form: those it can fill (_no_form), by name, FORMS at most."""
        named = [s for s in r.schedulers or () if not self._no_form(s)]
        return sorted(named, key=lambda s: s["name"].lower())[:FORMS]

    def _forcing(self, r: Reading) -> dict[str, str]:
        """Each builder a force scheduler starts, by name: the first such scheduler's name (by name)."""
        out: dict[str, str] = {}
        for s in self._schedulers(r):
            for b in starts_of(s):
                out.setdefault(b, s["name"])
        return out

    @staticmethod
    def _not_read(r: Reading, kind: str, none: str) -> str:
        why = r.problems.get(kind)
        return f"Not read: {why}" if why else none

    def _builders_table(self, r: Reading, forcing: dict[str, str]) -> dict:
        last: dict = {}
        for b in r.builds or ():  # newest first: each builder's first is its newest
            last.setdefault(b.get("builderid"), b)
        on: dict = {}
        for w in r.workers or ():
            for bid in builder_ids(w):
                counts = on.setdefault(bid, [0, 0])
                counts[0] += 1 if connected(w) else 0
                counts[1] += 1
        rows = []
        for b in sorted(r.builders or (), key=lambda x: line(x.get("name")).lower()):
            raw = b.get("name") if isinstance(b.get("name"), str) else ""
            name, bid = line(raw, TEXT_MOST), b.get("builderid")
            sub = " · ".join(x for x in (line(b.get("description"), 120),
                                         "" if b.get("masterids") else "on no master now") if x)
            newest = last.get(bid)
            started = number(newest.get("started_at")) if newest else None
            built = (cell(f"#{line(newest.get('number'))} {result_of(newest)}",
                          f"{span(r.when - started)} ago" if started else None) if newest else "–")
            up, all_ = on.get(bid, (0, 0))
            tags = ", ".join(line(t, 40) for t in b.get("tags") or () if isinstance(t, str)) or "–"
            via = forcing.get(raw)
            force = ({"form": f"force:{via}", "title": "Force…", "values": {"builder": raw},
                      "label": f"Force a build of {name}", "note": f"through {via}"} if via else "–")
            rows.append([cell(name, sub or None), tags, built, f"{up} of {all_} connected" if all_ else "none", force])
        rows, note = capped(rows, f"on {r.url}", r.totals.get("builders"))
        return {"title": "Builders", "note": note, "rows": rows,
                "columns": [{"title": "Builder"}, {"title": "Tags"}, {"title": "Last build"}, {"title": "Workers"},
                            {"title": "Force"}],
                "empty": "The master has no builder."}

    def _builds_table(self, r: Reading) -> dict:
        builders = {b.get("builderid"): line(b.get("name"), TEXT_MOST) for b in r.builders or ()}
        workers = {w.get("workerid"): line(w.get("name"), TEXT_MOST) for w in r.workers or ()}
        rows = []
        for b in r.builds or ():
            started, ended = number(b.get("started_at")), number(b.get("complete_at"))
            if started and ended:
                took = span(ended - started)
            elif started and not b.get("complete"):
                took = f"running for {span(r.when - started)}"
            else:
                took = "–"
            builder = builders.get(b.get("builderid")) or f"builder {line(b.get('builderid'))}"
            rows.append([cell(f"{builder} #{line(b.get('number'))}", f"build {line(b.get('buildid'))}"),
                         cell(result_of(b), line(b.get("state_string"), 120) or None),
                         cell(clock(started), f"{span(r.when - started)} ago" if started else None), took,
                         workers.get(b.get("workerid")) or "–"])
        total, n = r.totals.get("builds"), len(rows)
        note = f"the {n} newest on {r.url}" + (f" (of {total:,} the master counts)" if total and total > n else "")
        return {"title": "Recent builds", "note": note, "rows": rows,
                "columns": [{"title": "Build"}, {"title": "Result"}, {"title": "Started"}, {"title": "Took"},
                            {"title": "Worker"}],
                "empty": self._not_read(r, "builds", "No build yet.")}

    def _workers_table(self, r: Reading) -> dict:
        rows = []
        for w in sorted(r.workers or (), key=lambda x: line(x.get("name")).lower()):
            info = w.get("workerinfo") if isinstance(w.get("workerinfo"), dict) else {}
            how = ("paused" + (f": {line(w.get('pause_reason'), 120)}" if line(w.get("pause_reason")) else "")
                   if w.get("paused") else "graceful: it ends once its builds have" if w.get("graceful") else "")
            rows.append([cell(line(w.get("name"), TEXT_MOST), line(info.get("host"), 80) or None),
                         cell("connected" if connected(w) else "not connected", how or None),
                         line(info.get("version"), 40) or "–", str(len(builder_ids(w)))])
        rows, note = capped(rows, f"on {r.url}", r.totals.get("workers"))
        return {"title": "Workers", "note": note, "rows": rows,
                "columns": [{"title": "Worker"}, {"title": "State"}, {"title": "Version"},
                            {"title": "Builders", "num": True}],
                "empty": self._not_read(r, "workers", "The master has no worker.")}

    def _schedulers_table(self, r: Reading) -> dict:
        formed = {s["name"] for s in self._schedulers(r)}
        rows = []
        for s in sorted(r.schedulers or (), key=lambda x: line(x.get("name")).lower()):
            raw = s.get("name") if isinstance(s.get("name"), str) else ""
            name = line(raw, 100)
            label = line(s.get("label"), 120)
            starts = ", ".join(line(b, TEXT_MOST) for b in starts_of(s))
            if raw in formed:
                force = {"form": f"force:{raw}", "title": "Force…", "values": {},
                         "label": f"Force a build through {name}"}
            else:
                force = cell("–", self._no_form(s) or f"only the first {FORMS} by name have a form here")
            rows.append([cell(name, label if label and label != name else None), starts or "–", force])
        rows, note = capped(rows, f"on {r.url}: each forces a build as its button in the master's web UI does")
        return {"title": "Force schedulers", "note": note, "rows": rows,
                "columns": [{"title": "Force scheduler"}, {"title": "Builders"}, {"title": "Force"}],
                "empty": self._not_read(r, "forceschedulers",
                                        "The master has no force scheduler: its master.cfg adds one "
                                        "(schedulers.ForceScheduler).")}

    @staticmethod
    def _here_table(r: Reading) -> dict:
        note = ("Found by its files alone, and on Windows by its service's registry key (nothing is run to know it): "
                + ", ".join(r.found.looked) + ".")
        if r.found.trouble:
            note += f" The look failed: {r.found.trouble}."
        rows = [[what, where] for what, where in r.found.rows()][:ROWS]
        return {"title": "Buildbot here", "note": note, "rows": rows,
                "columns": [{"title": "What"}, {"title": "Where"}],
                "empty": "Nothing of Buildbot's on this machine" + (f": the master read is at {r.url}."
                                                                   if r.answering else ".")}

    def _install_table(self, r: Reading) -> dict:
        """How to install and start Buildbot, said and not done (no install, start or stop in this release): the
        documentation's steps, as this system's shell types them, with what of each the look here found."""
        rows = []
        for what, command, page, kind in install_steps(self._system_name()):
            have = list(getattr(r.found, kind, ())) if kind else []
            if have:
                here = cell(f"found: {have[0]}", f"and {plural(len(have) - 1, 'more')}" if len(have) > 1 else None)
            elif what == "Start it":
                here = (f"something answers at {r.url}, but not Buildbot's REST API" if r.reachable else
                        f"nothing answers at {r.url}" if r.url else "–")
            else:
                here = "not found here" if kind else "–"
            rows.append([what, command, here, page])
        windows = self._system_name() == "windows"
        shell = ("typed in your home folder, the Command Prompt's way, with PowerShell's under it where it differs"
                 if windows else "as a Linux or macOS shell types them")
        note = (f"Buildbot runs in a container through Install… (above); one you install yourself is found and read. "
                f"This plugin installs nothing natively: these are Buildbot's documentation's steps (its "
                f"tutorial's First run), {shell}; the tutorial is written for Unix and adapts to Windows, and inside "
                "WSL its Linux steps hold. Every step after the activation is typed in the shell it activated: a "
                "worker started from another shell runs its builds without the sandbox's programs. Once the master "
                "runs, its web UI and REST API answer at http://localhost:8010 (BUILDBOT_URL when they answer "
                "elsewhere).")
        return {"title": "Or install it yourself", "note": note, "rows": rows,
                "columns": [{"title": "Step"}, {"title": "Command"}, {"title": "Here"}, {"title": "Documentation"}]}

    def _forms(self, r: Reading) -> list[dict]:
        """The forms the platform's page draws (liminal-platform 0.6.0, status.forms): one Force… per force scheduler
        it can fill, its fields the force hook's arguments in order: the scheduler, the builder, the builders it starts
        and the names of its fields (fixed), then the fields the scheduler's all_fields offer, as its web UI offers
        them (fields.py); asked once the user has confirmed it."""
        out = []
        for s in self._schedulers(r):
            name = s["name"]
            starts = starts_of(s)
            shown = [line(b, TEXT_MOST) for b in starts]
            label = line(s.get("label"), 120) or name
            every = f"every builder it starts ({', '.join(shown)})"
            button = line(s.get("button_name"), 60) or "Force"
            fields = offered(fields_of(s))
            out.append({
                "id": f"force:{name}", "hook": "force", "title": f"Force a build: {label}",
                "note": (f"On the master at {r.url}, as its web UI's {button} button does: each field is sent under "
                         "the scheduler's own name for it, and one left empty takes the scheduler's own value."),
                "fields": [
                    {"name": "scheduler", "label": "Force scheduler", "type": "fixed", "value": name},
                    {"name": "builder", "label": "Builder", "type": "choice", "value": "", "empty": every,
                     "choices": [{"value": "", "title": "every builder it starts", "note": ", ".join(shown)},
                                 *({"value": b, "title": t} for b, t in zip(starts, shown))]},
                    {"name": "starts", "label": "Builders it starts", "type": "fixed", "value": joined(starts)},
                    {"name": "fields", "label": "Sent under the names", "type": "fixed",
                     "value": ", ".join(f.full for f in fields), "empty": "none: the scheduler's own values"},
                    *(form_field(f) for f in fields)],
                "submit": "Review",
                "confirm": {"title": "Force a build of {builder} through {scheduler}?",
                            "words": (f"The master at {r.url} is asked to build {{builder}} now, as its force "
                                      "scheduler {scheduler} does from its web UI: a build request for each, run once "
                                      "a worker is free, with the values below, each under the scheduler's own name "
                                      "for it (one left empty takes the scheduler's own). Sent once."),
                            "yes": "Force it"}})
        return out


MACHINE = BuildbotPlugin()
