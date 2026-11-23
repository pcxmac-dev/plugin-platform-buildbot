"""Buildbot for Liminal (the user, 2026-11-22: a new class of platform plugins, Continuous Integration, with three
plugins in it: Jenkins, GoCD and Buildbot): a Buildbot master's builders, recent builds, workers and force schedulers,
read from its web server's REST API (the data API, version 2); whether Buildbot is installed on this machine; and a
build forced through a force scheduler once the platform's page has confirmed it. Drawn under the platform's
Continuous Integration plugins (SECTION "ci"; a platform that does not know the section draws it under Machine
plugins).

- Where (settings.py): the master's web address, BUILDBOT_URL (http://127.0.0.1:8010 unless set: the tutorial's master
  on this machine), with BUILDBOT_USER and BUILDBOT_PASSWORD for a master whose web UI asks a sign-in, each read through
  the plugin's login. The password goes to the master's /auth/login alone, never over plain http to another machine,
  and is never said, logged or kept (client.py).
- Installed here (finders.py): its files alone say it: the buildbot command, a master's folder holding its buildbot.tac,
  the buildbot-worker command and a worker's folder, and on Linux a systemd unit named buildbot; nothing is run to know
  it.
- What it reads: one GET each of the web server's /config (the versions its About page shows, Buildbot's among them),
  /api/v2/builders, /api/v2/builds (the 20 newest), /api/v2/workers and /api/v2/forceschedulers, after a sign-in when a
  user is set; kept READ_S, so the page's refreshes do not ask again; a failure said in words on the page, never raised.
- What it changes: a force scheduler's force (one JSON-RPC POST, sent once), confirmed on the page first. Nothing is
  installed, started or stopped by this release: when no master answers, the page says how to install and start one
  (a virtual environment, pip install 'buildbot[bundle]', buildbot create-master, buildbot-worker for the workers), with
  the documentation's addresses.

Nothing runs on its own: the plugin reads when the platform asks, holds no process, thread or connection between asks,
and forgets what it read when its settings change and when it is detached."""
from __future__ import annotations

import json
import platform
import re
import threading
import time
from dataclasses import dataclass, field
from urllib.parse import quote

from liminal_libs.machines.plugin import MachinePlugin

from . import apis as cards
from .client import API, FORCE_S, LOOK_S, BuildbotError, Master
from .finders import Finder, Found
from .settings import KEYS, Settings
from .settings import read as read_settings

__version__ = "0.1.0"
READ_S = 30.0  # what was read is kept this long: the platform's page asks every few seconds; a force reads again
BUILDS = 20  # the newest builds read
ROWS = 200  # a table's rows at most
FORMS = 20  # the force schedulers given a form each, at most
LISTINGS = (("builders", None), ("builds", {"order": "-buildid", "limit": BUILDS}), ("workers", None),
            ("forceschedulers", None))  # what a read asks under /api/v2, in this order, one GET each
LABELS = {"builders": "builders", "builds": "recent builds", "workers": "workers",
          "forceschedulers": "force schedulers"}
RESULTS = {0: "success", 1: "warnings", 2: "failure", 3: "skipped", 4: "exception", 5: "retry", 6: "cancelled"}
SCHEDULER = re.compile(r"^(?!\d)[\w-]{1,100}$")  # a force scheduler's name: an identifier (letters, digits, _ and -)
TEXT_MOST = 200  # characters of a builder's name, a reason, a branch or a revision typed on the page, at most
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


def typed(value, what: str, spaces: bool = True) -> str:
    """A field typed on the page: "" for none; ValueError in words for one too long, holding a line break or a control
    character, or a space where none goes (a branch, a revision)."""
    said = str(value if value is not None else "").strip()
    if not said:
        return ""
    if len(said) > TEXT_MOST:
        raise ValueError(f"{what} is {TEXT_MOST} characters at most")
    if any(ord(c) < 32 or ord(c) == 127 for c in said):
        raise ValueError(f"{what} holds a line break or a control character")
    if not spaces and any(c.isspace() for c in said):
        raise ValueError(f"{what} holds no space")
    return said


def install_steps(system: str) -> list[tuple[str, str, str, str]]:
    """The documentation's steps to install and start Buildbot (its tutorial's First run), each (what, the command as
    this system's shell types it, its page, what of it the look here finds: "commands", "masters", "worker_commands",
    "workers", or "" for a step it cannot see). On Windows each is typed in the home folder, alike in the Command
    Prompt and in PowerShell."""
    if system == "windows":
        home = "buildbot"
        tools = ".\\buildbot\\sandbox\\Scripts\\"
        master, worker = home + "\\master", home + "\\worker"
        made = f"py -m venv {home}\\sandbox"
        bundle = f'{tools}pip install "buildbot[bundle]"'
        sample = f"copy {master}\\master.cfg.sample {master}\\master.cfg"
    else:
        home = "~/buildbot"
        tools = home + "/sandbox/bin/"
        master, worker = home + "/master", home + "/worker"
        made = f"python3 -m venv {home}/sandbox"
        bundle = f"{tools}pip install 'buildbot[bundle]'"
        sample = f"mv {master}/master.cfg.sample {master}/master.cfg"
    return [
        ("A virtual environment for it", made, FIRST_RUN, ""),
        ("Buildbot in it, its web UI with it (the bundle)", bundle, FIRST_RUN, "commands"),
        ("A master", f"{tools}buildbot create-master {master}", BUILDMASTER, "masters"),
        ("Its configuration, from the sample (its web UI on port 8010)", sample, BUILDMASTER, ""),
        ("Start it", f"{tools}buildbot start {master}", LAUNCHING, ""),
        ("A worker's code", f"{tools}pip install buildbot-worker", WORKER, "worker_commands"),
        ("A worker, as the sample's master knows it",
         f"{tools}buildbot-worker create-worker {worker} localhost example-worker pass", WORKER, "workers"),
        ("Start the worker", f"{tools}buildbot-worker start {worker}", LAUNCHING, ""),
    ]


@dataclass(frozen=True)
class Reading:
    """One read: when (monotonic, for keeping it; the wall's, for the page), the address read ("" when BUILDBOT_URL is
    none), what is installed here, whether a web server answered there (`reachable`: any HTTP status) and whether
    Buildbot's REST API did (`answering`: its builders read), why not in words, what /config said (the versions by
    name, the title, the sign-in it names), the user signed in as, the four listings (None: not read) with the totals
    the master counts and why one was not read, and the settings' and the sign-in's words."""

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
    reading, and what its requests came to (its API facts)."""

    def __init__(self):
        self.lock = threading.Lock()
        self.reading_lock = threading.Lock()  # one read at a time: a second asker waits, then takes it
        self.reading: Reading | None = None
        self.seen = _seen()


def versions_of(config) -> dict:
    """The versions a master's /config names ([[name, version], ...]: Python's, Buildbot's, Twisted's, then the www
    versions option's), by name, the first of each name."""
    out: dict[str, str] = {}
    given = config.get("versions") if isinstance(config, dict) else None
    for pair in given if isinstance(given, list) else ():
        if isinstance(pair, (list, tuple)) and len(pair) == 2 and all(isinstance(x, str) for x in pair):
            out.setdefault(line(pair[0], 40), line(pair[1], 40))
    return out


class BuildbotPlugin(MachinePlugin):
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
    order = 772  # the Continuous Integration plugins, after the cloud's (760-765): Jenkins, GoCD, Buildbot, as named
    ICON = "buildbot"
    SECTION = "ci"  # drawn under the platform's Continuous Integration plugins; "machine" on a platform before it
    HOOKS = (*MachinePlugin.HOOKS, "refresh", "force")
    READ_HOOKS = ("refresh",)  # its own read beside its bases' (force changes the master: a build is asked of it)
    INTERNAL_NOTES = (
        "force sends one JSON-RPC call (POST /api/v2/forceschedulers/<name>, method force) once its scheduler and its "
        "builder are read from the master again; refresh reads the master again now. Every request goes to "
        "BUILDBOT_URL alone, the password to its /auth/login alone.",
    )
    keys = KEYS  # its settings, kept through the platform's login: the master's address, a user and its password

    def __init__(self, http=None, find=None, clock=None, wall=None, system=None):
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

    def _noted(self, status: int, seconds: float, error: str) -> None:
        """What one request came to, for its API facts: counted, the last kept (its words hold no secret)."""
        with self._rt.lock:
            seen = self._rt.seen
            seen["requests"] += 1
            seen["failed"] += 1 if (status == 0 or error) else 0
            seen.update(status=status, ms=seconds * 1000.0, at=self._wall(), error=error)

    def _master(self, s: Settings, timeout: float) -> Master:
        return Master(s.where, user=s.user if s.sign_in else "", password=s.password if s.sign_in else "",
                      transport=self._http, timeout=timeout, note=self._noted, clock=self._clock)

    def _read(self, fresh: bool = False) -> Reading:
        """The master and this machine read, kept READ_S (`fresh`: read now)."""
        with self._rt.reading_lock:
            with self._rt.lock:
                kept = self._rt.reading
            if kept is not None and not fresh and self._clock() - kept.at < READ_S:
                return kept
            reading = self._ask(read_settings(self.login), self._found())
            with self._rt.lock:
                self._rt.reading = reading
            return reading

    def _ask(self, s: Settings, found: Found) -> Reading:
        """One read of the master (the module docstring's GETs, in order): a request that gets no answer before any
        has means nothing answers there; one that gets none after leaves the rest not asked."""
        at, when = self._clock(), self._wall()
        notes = list(s.problems)
        if s.where is None:
            return Reading(at, when, "", found, why=s.problems[0], notes=tuple(notes))
        url = s.where.base
        master = self._master(s, LOOK_S)

        def nobody(e: BuildbotError) -> Reading:
            return Reading(at, when, url, found, why=f"nothing answers at {url}: {e}", notes=tuple(notes))

        try:
            said = master.sign_in() if s.sign_in else ""
        except BuildbotError as e:
            return nobody(e)
        if said:
            notes.append(said)
        asks = [("config", lambda: master.get("/config"))]
        asks += [(kind, lambda k=kind, p=params: master.listing(f"{API}/{k}", k, p)) for kind, params in LISTINGS]
        got: dict = {}
        problems: dict = {}
        statuses: dict = {}
        stopped = ""
        for kind, ask in asks:
            if stopped:
                problems[kind] = f"not asked: {stopped}"
                continue
            try:
                got[kind] = ask()
            except BuildbotError as e:
                if not e.answered and not master.answered:
                    return nobody(e)
                problems[kind], statuses[kind] = str(e), e.status
                if not e.answered:
                    stopped = f"the master stopped answering ({e})"
        config = got.get("config") if isinstance(got.get("config"), dict) else {}
        if "config" in got and not config:
            problems["config"] = "GET /config: its answer is no configuration"
        auth, user = config.get("auth"), config.get("user")
        signed_in = master.signed_in
        if signed_in and isinstance(user, dict) and user.get("anonymous") is True:  # its config.user: the session's
            notes.append(f"the master set a session cookie for {signed_in}, but its /config says no one is signed in: "
                         "read as anyone")
            signed_in = ""
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
        with self._rt.lock:
            self._rt.reading = None

    def settings_changed(self) -> None:
        """Its settings kept anew on the platform's page: what was read is forgotten, so the next look asks the address
        now set, as the user now set."""
        self._forget()

    def detach(self) -> None:
        """Detached (the platform ending, the plugin turned off): what it read goes, and what its requests came to;
        nothing of its own was running."""
        with self._rt.lock:
            self._rt.reading = None
            self._rt.seen = _seen()
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
        out: dict = {"present": r.present, "summary": self._summary(r), "valid": r.answering,
                     "why": "" if r.answering else r.why or "the master was not read"}
        out.update(self._facts(r))
        out["tables"] = self._tables(r)
        out["forms"] = self._forms(r) if r.answering else []
        out["actions"] = [{"hook": "refresh", "args": [], "title": "Read again",
                           "note": f"asks the master again now (what was read is kept {READ_S:g} s)"}]
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
        """The master read again now (what was read is kept READ_S otherwise)."""
        r = self._read(fresh=True)
        if not r.answering:
            return {"said": f"read again: {r.why}", "ok": False, "lines": list(r.notes)}
        workers = r.workers or ()
        lines = [f"{plural(len(r.builders), 'builder')}, {plural(len(r.builds or ()), 'recent build')}, "
                 f"{plural(len(workers), 'worker')} ({sum(1 for w in workers if connected(w))} connected), "
                 f"{plural(len(r.schedulers or ()), 'force scheduler')}"]
        lines += [f"its {LABELS[kind]} could not be read: {why}" for kind, why in r.problems.items() if kind in LABELS]
        return {"said": f"read the master at {r.url} again now", "ok": True, "lines": lines + list(r.notes)}

    def force(self, scheduler, builder=None, reason=None, branch=None, revision=None) -> dict:
        """A build forced through the force scheduler named, as its button in the master's web UI forces one: of the
        builder named (one the scheduler starts), or of every builder it starts when none is; with `reason`, `branch`
        and `revision` when they are given (the scheduler's own otherwise). The scheduler is read from the master again
        first (and the builder, for its id, as the web UI sends it), then one JSON-RPC call is sent, once:
        POST /api/v2/forceschedulers/<name> {"method": "force"}. Refused in words before anything is sent for a name
        that is none, a field that cannot be one, and a scheduler or a builder the master does not have."""
        name = str(scheduler if scheduler is not None else "").strip()
        if not SCHEDULER.match(name):
            raise ValueError(f"not a force scheduler's name: {name[:60]!r} (letters, digits, _ and -)")
        chosen = typed(builder, "a builder's name")
        params: dict = {}
        for key, value, spaces in (("reason", reason, True), ("branch", branch, False), ("revision", revision, False)):
            said = typed(value, f"the {key}", spaces)
            if said:
                params[key] = said
        s = read_settings(self.login)
        if s.where is None:
            raise ValueError(s.problems[0])
        url = s.where.base
        master = self._master(s, LOOK_S)
        path = f"{API}/forceschedulers/{quote(name, safe='')}"
        signed = master.sign_in() if s.sign_in else ""
        try:
            found, _ = master.listing(path, "forceschedulers")
        except BuildbotError as e:
            if e.status == 404:
                raise ValueError(f"the master at {url} has no force scheduler named {name}") from None
            raise
        sched = next((x for x in found if x.get("name") == name), None)
        if sched is None:
            raise ValueError(f"the master at {url} has no force scheduler named {name}")
        starts = [b for b in sched.get("builder_names") or () if isinstance(b, str)]
        if chosen:
            if chosen not in starts:
                raise ValueError(f"{name} does not start {chosen}: it starts {', '.join(starts) or 'no builder'}")
            params["builderid"] = self._builder_id(master, chosen, url)
        try:
            result = master.control(path, "force", params, timeout=FORCE_S)
        except BuildbotError as e:
            if not e.answered:
                raise BuildbotError(f"{e}: no answer came, so it may have been done (Read again shows it under Recent "
                                    "builds)") from None
            raise
        finally:
            self._forget()
        what = chosen or f"every builder {name} starts ({', '.join(starts) or 'none'})"
        lines = self._made(result)
        if signed:
            lines.append(signed)
        lines.append("it runs once a worker is free: Read again shows it under Recent builds")
        return {"said": f"a build of {what} asked of the master at {url}", "lines": lines, "ok": True}

    @staticmethod
    def _builder_id(master: Master, name: str, url: str) -> int:
        """A builder's id, read from the master by its name."""
        try:
            rows, _ = master.listing(f"{API}/builders/{quote(name, safe='')}", "builders")
        except BuildbotError as e:
            if e.status == 404:
                raise ValueError(f"the master at {url} has no builder named {name}") from None
            raise
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
        if not r.answering:
            return [self._here_table(r), self._install_table(r)]
        forcing = self._forcing(r)
        return [self._builders_table(r, forcing), self._builds_table(r), self._workers_table(r),
                self._schedulers_table(r), self._here_table(r)]

    @staticmethod
    def _schedulers(r: Reading) -> list[dict]:
        """The force schedulers given a form: those whose name is one, by name, FORMS at most."""
        named = [s for s in r.schedulers or () if isinstance(s.get("name"), str) and SCHEDULER.match(s["name"])]
        return sorted(named, key=lambda s: s["name"].lower())[:FORMS]

    def _forcing(self, r: Reading) -> dict[str, str]:
        """Each builder a force scheduler starts, by name: the first such scheduler's name (by name)."""
        out: dict[str, str] = {}
        for s in self._schedulers(r):
            for b in s.get("builder_names") or ():
                if isinstance(b, str):
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
            name, bid = line(b.get("name"), TEXT_MOST), b.get("builderid")
            sub = " · ".join(x for x in (line(b.get("description"), 120),
                                         "" if b.get("masterids") else "on no master now") if x)
            newest = last.get(bid)
            started = number(newest.get("started_at")) if newest else None
            built = (cell(f"#{line(newest.get('number'))} {result_of(newest)}",
                          f"{span(r.when - started)} ago" if started else None) if newest else "–")
            up, all_ = on.get(bid, (0, 0))
            tags = ", ".join(line(t, 40) for t in b.get("tags") or () if isinstance(t, str)) or "–"
            via = forcing.get(name)
            force = ({"form": f"force:{via}", "title": "Force…", "values": {"builder": name},
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
            name = line(s.get("name"), 100)
            label = line(s.get("label"), 120)
            starts = ", ".join(line(b, TEXT_MOST) for b in s.get("builder_names") or () if isinstance(b, str))
            force = ({"form": f"force:{name}", "title": "Force…", "values": {},
                      "label": f"Force a build through {name}"} if name in formed else "–")
            rows.append([cell(name, label if label and label != name else None), starts or "–", force])
        rows, note = capped(rows, f"on {r.url}: each forces a build as its button in the master's web UI does")
        return {"title": "Force schedulers", "note": note, "rows": rows,
                "columns": [{"title": "Force scheduler"}, {"title": "Builders"}, {"title": "Force"}],
                "empty": self._not_read(r, "forceschedulers",
                                        "The master has no force scheduler: its master.cfg adds one "
                                        "(schedulers.ForceScheduler).")}

    @staticmethod
    def _here_table(r: Reading) -> dict:
        note = "Found by its files alone (nothing is run to know it): " + ", ".join(r.found.looked) + "."
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
        shell = ("typed in your home folder, in the Command Prompt or PowerShell alike" if windows else
                 "as a Linux or macOS shell types them")
        note = (f"Nothing is installed or started by this plugin: these are Buildbot's documentation's steps (its "
                f"tutorial's First run), {shell}; the tutorial is written for Unix and adapts to Windows, and inside "
                "WSL its Linux steps hold. Once the master runs, its web UI and REST API answer at "
                "http://localhost:8010 (BUILDBOT_URL when they answer elsewhere).")
        return {"title": "How to install and start Buildbot", "note": note, "rows": rows,
                "columns": [{"title": "Step"}, {"title": "Command"}, {"title": "Here"}, {"title": "Documentation"}]}

    def _forms(self, r: Reading) -> list[dict]:
        """The forms the platform's page draws (liminal-platform 0.6.0, status.forms): one Force… per force scheduler,
        its fields the force hook's arguments in order (the scheduler fixed), asked once the user has confirmed it."""
        out = []
        for s in self._schedulers(r):
            name = s["name"]
            starts = [line(b, TEXT_MOST) for b in s.get("builder_names") or () if isinstance(b, str)]
            label = line(s.get("label"), 120) or name
            every = f"every builder it starts ({', '.join(starts)})" if starts else "every builder it starts"
            own = "the scheduler's own"
            button = line(s.get("button_name"), 60) or "Force"
            out.append({
                "id": f"force:{name}", "hook": "force", "title": f"Force a build: {label}",
                "note": (f"On the master at {r.url}, as its web UI's {button} button does. A field left empty takes "
                         "the scheduler's own value."),
                "fields": [
                    {"name": "scheduler", "label": "Force scheduler", "type": "fixed", "value": name},
                    {"name": "builder", "label": "Builder", "type": "choice", "value": "", "empty": every,
                     "choices": [{"value": "", "title": "every builder it starts", "note": ", ".join(starts) or "none"},
                                 *({"value": b, "title": b} for b in starts)]},
                    {"name": "reason", "label": "Reason", "type": "text", "empty": own, "note": "optional",
                     "placeholder": "the scheduler's own (force build, unless its master.cfg says another)"},
                    {"name": "branch", "label": "Branch", "type": "text", "empty": own, "note": "optional",
                     "placeholder": "the scheduler's own"},
                    {"name": "revision", "label": "Revision", "type": "text", "empty": own, "note": "optional",
                     "placeholder": "the scheduler's own (the newest)"}],
                "submit": "Review",
                "confirm": {"title": "Force a build of {builder} through {scheduler}?",
                            "words": (f"The master at {r.url} is asked to build {{builder}} now, as its force "
                                      "scheduler {scheduler} does from its web UI: a build request for each, run once "
                                      "a worker is free. Reason: {reason}; branch: {branch}; revision: {revision}. "
                                      "Sent once."),
                            "yes": "Force it"}})
        return out


MACHINE = BuildbotPlugin()
