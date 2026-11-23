"""What the tests give the plugin in place of the world: a Buildbot master's web server (`Master`, a transport answering
as Buildbot's documentation and code say a master does: its REST API under /api/v2, its /config, its /auth/login, a
force scheduler's force as ForceScheduler.force takes it), a login holding the settings (`login`), and a look at this
machine finding what it is told (`found`). Nothing here sends, starts or reads anything outside the test: what reaches
for the world is refused with `Reached` (conftest.py's guard, and the stand-in master asked at another address) and
noted in REACHED, which every test's end checks."""
from __future__ import annotations

import base64
import html
import json
from urllib.parse import parse_qs, unquote, urlsplit

from liminal_libs.apps import EnvironmentLogin
from plugin_platform_buildbot.finders import Found

NOW = 1_795_000_000.0  # the tests' wall clock (November 2026), seconds since the epoch
BASE = "http://127.0.0.1:8010"
PASSWORD = "doh!-c0rrect-h0rse"  # a password no answer, table or word may hold
SESSION = "eyJhbGciOiJIUzI1NiJ9.eyJ1c2VyIjoiaG9tZXIifQ.c2lnbmVk"  # the signed-in session's cookie the master sets
ANONYMOUS = "eyJhbGciOiJIUzI1NiJ9.eyJhbm9ueW1vdXMiOnRydWV9.YW5vbg"  # the anonymous session's, set first
WEB_UI = "http://localhost:8010/#/"  # where a good sign-in is sent on: its buildbotURL and "#/"
MASTER_TAC = ("import os\n\nfrom twisted.application import service\nfrom buildbot.master import BuildMaster\n\n"
              "basedir = '.'\napplication = service.Application('buildmaster')\n"
              "m = BuildMaster(basedir, 'master.cfg', umask=None)\nm.setServiceParent(application)\n")
WORKER_TAC = ("import os\n\nfrom buildbot_worker.bot import Worker\nfrom twisted.application import service\n\n"
              "basedir = '.'\napplication = service.Application('buildbot-worker')\n"
              "s = Worker('localhost', 9989, 'example-worker', 'pass', basedir, 600, umask=None)\n")
REACHED: list[str] = []  # what a test reached for real (cleared and checked by conftest.py's guard)


class Reached(BaseException):
    """A test reached for real what it must stand in for (a BaseException: no `except Exception` swallows it)."""


def login(**values) -> EnvironmentLogin:
    """A login furnishing these settings (BUILDBOT_URL=..., BUILDBOT_USER=..., BUILDBOT_PASSWORD=...)."""
    return EnvironmentLogin(env={k: v for k, v in values.items() if v is not None})


def found(**parts):
    """A look at this machine that finds these (commands=("/usr/bin/buildbot",), masters=(...), ...)."""
    return lambda: Found(**{k: tuple(v) for k, v in parts.items()}, looked=("PATH", "~/buildbot*"))


# -- a force scheduler's all_fields, as Buildbot's getSpec gives them (master/buildbot/schedulers/forcesched.py) -------
def param(name: str, kind: str = "text", label: str | None = None, default="", parent: str | None = None,
          **more) -> dict:
    """A parameter's spec: its name, its fullName (its nest's, an underscore and its own when both are set, else
    whichever is), its label (its name unless given), its type, its default and the rest of BaseParameter's own."""
    full = f"{parent}_{name}" if parent and name else (name or parent)
    shown = name if label is None else label
    spec = {"name": name, "fullName": full, "label": shown, "tablabel": shown, "type": kind, "default": default,
            "required": False, "multiple": False, "regex": None, "hide": kind == "fixed", "maxsize": None,
            "autopopulate": None, "tooltip": ""}
    if kind in ("text", "int", "username"):
        spec["size"] = 30 if kind == "username" else 10
    if kind == "username":
        spec["need_email"] = True
    if kind == "list":
        spec.update(choices=[], strict=True)
    spec.update(more)
    return spec


def nest(name: str, fields: list[dict], label: str | None = None, **more) -> dict:
    """A NestedParameter's spec, its fields' own (each built with parent= this nest's fullName)."""
    return {**param(name, "nested", label=label), "layout": "vertical", "columns": 1, "fields": fields, **more}


def codebase(name: str = "", label: str | None = None, **given) -> dict:
    """A CodebaseParameter's spec: its branch, project, repository and revision, sorted as Buildbot sorts them, each a
    text unless given (a str: a FixedParameter of that value; a dict: that spec; None: left out); labelled "Codebase:
    <name>" when it has a name, unless given another label."""
    shown = label if label is not None else (f"Codebase: {name}" if name else "")
    fields = []
    for key in ("branch", "project", "repository", "revision"):
        own = given.get(key, ...)
        if own is None:
            continue
        if own is ...:
            spec = param(key, label=key.capitalize() + ":", parent=name or None)
        elif isinstance(own, str):
            spec = param(key, "fixed", default=own, parent=name or None)
        else:
            spec = {**own, "fullName": f"{name}_{key}" if name else key}
        fields.append(spec)
    return nest(name, fields, label=shown)


def force_fields(*codebases: dict, reason: dict | None = None, username: dict | None = None,
                 priority: dict | None = None, properties: tuple = ()) -> list[dict]:
    """A ForceScheduler's all_fields as its master gives them: its first nest, unnamed (the user's name, the reason,
    the priority), then each codebase's (the unnamed one unless given), then its properties."""
    first = nest("", [username or param("username", "username", label="Your name:"),
                      reason or param("reason", default="force build", size=20),
                      priority or param("priority", "int", default=0)], label="")
    return [first, *(codebases or (codebase(),)), *properties]


def docs_fields() -> list[dict]:
    """The all_fields of the ForceScheduler Buildbot's documentation configures (schedulers.html, its "pushMe!"
    example): a branch to choose of master and hest, the revision, the repository and the project fixed, a reason
    needed, and its Build Options (a pull url, a make clean)."""
    return force_fields(
        codebase("", label="Main repository",
                 branch=param("branch", "list", default="master", choices=["master", "hest"]),
                 revision="", repository="", project=""),
        reason=param("reason", label="reason:", required=True, size=80),
        username=param("username", "username", label="your name:", size=80),
        properties=(nest("options", [param("pull_url", label="optionally give a public Git pull url:", default="",
                                           size=80, parent="options"),
                                     param("force_build_clean", "bool", label="force a make clean", default=False,
                                           parent="options")], label="Build Options"),))


def leaves(all_fields) -> list[dict]:
    """The fields of all_fields that hold a value (its nests' leaves), in order."""
    out = []
    for f in all_fields or ():
        out += leaves(f.get("fields")) if f.get("type") == "nested" else [f]
    return out


def builders() -> list[dict]:
    return [
        {"builderid": 1, "name": "runtests", "description": "the project's tests", "tags": ["py"], "masterids": [1],
         "projectid": None},
        {"builderid": 2, "name": "docs", "description": None, "tags": [], "masterids": [1], "projectid": None},
        {"builderid": 3, "name": "old-release", "description": None, "tags": ["release"], "masterids": [],
         "projectid": None},
    ]


def builds() -> list[dict]:
    def build(buildid, number, builderid, workerid, started, ended, results, state):
        return {"buildid": buildid, "number": number, "builderid": builderid, "buildrequestid": buildid + 10,
                "workerid": workerid, "masterid": 1, "started_at": started, "complete_at": ended,
                "complete": ended is not None, "results": results, "state_string": state, "locks_duration_s": 0}
    return [
        build(40, 3, 2, 1, NOW - 7200, NOW - 7100, 2, "failed sphinx"),
        build(41, 12, 1, 1, NOW - 600, NOW - 480, 0, "build successful"),
        build(42, 13, 1, 1, NOW - 90, None, None, "running 'pytest'"),
    ]


def workers() -> list[dict]:
    return [
        {"workerid": 1, "name": "example-worker", "paused": False, "pause_reason": None, "graceful": False,
         "workerinfo": {"host": "buildbox", "version": "4.3.0", "admin": "Your Name <admin@example.org>"},
         "connected_to": [{"masterid": 1}],
         "configured_on": [{"builderid": 1, "masterid": 1}, {"builderid": 2, "masterid": 1}]},
        {"workerid": 2, "name": "windows-worker", "paused": True, "pause_reason": "disk full", "graceful": False,
         "workerinfo": {}, "connected_to": [], "configured_on": [{"builderid": 1, "masterid": 1}]},
    ]


def schedulers() -> list[dict]:
    """Two force schedulers: the sample master.cfg's (ForceScheduler(name="force", builderNames=["runtests"]), here
    starting docs too: Buildbot's default fields) and the documentation's example's (its fields: docs_fields)."""
    return [
        {"name": "force", "button_name": "force", "label": "Force a build", "builder_names": ["runtests", "docs"],
         "enabled": True, "all_fields": force_fields()},
        {"name": "release", "button_name": "pushMe!", "label": "My nice Force form", "builder_names": ["old-release"],
         "enabled": True, "all_fields": docs_fields()},
    ]


class Master:
    """A Buildbot master's web server at `base`, as the plugin's transport: (method, url, headers, body, timeout) ->
    (status, headers, body). `users` ({user: password}): its web sign-in (UserPasswordAuth; none: NoAuth); `auth`: the
    sign-in its /config names instead (RemoteUserAuth, an OAuth2 provider's name with `oauth2`); `private`: its REST
    API refused (403) to anyone not signed in; `down`: nothing listens there; `redirect`: every request sent on to
    that address (HTTP 302); `version`: what its /config says Buildbot's is (None: it has no /config, as an older
    master); `other`: not Buildbot at all (every path a 404 page); `echo`: its sign-in's failure says back what it was
    sent (a careless proxy's 500): "text" (or True) as it came, "html" escaped in a page, "far" after a page's head of
    4,000 bytes or so (the token across its byte 4,000), "json" in a JSON error; `broken_after`: requests answered
    before the connection is refused (0: never). Every request is kept (`asked`: method, url, headers, body, timeout),
    each force too (`forced`: its scheduler and params; `built`: what the master made of it, each field's value by
    its fullName, and the builders, as ForceScheduler.force does; `ignored`: the params it let go of, unknown)."""

    def __init__(self, base: str = BASE, users=None, private: bool = False, down: bool = False, redirect: str = "",
                 version: str | None = "4.3.0", other: bool = False, echo=False, broken_after: int = 0,
                 auth: str = "", oauth2: bool = False):
        self.base, self.users, self.private, self.down = base, dict(users or {}), private, down
        self.redirect, self.version, self.other = redirect, version, other
        self.echo, self.broken_after, self.auth, self.oauth2 = echo, broken_after, auth, oauth2
        self.builders, self.builds, self.workers, self.schedulers = builders(), builds(), workers(), schedulers()
        self.asked: list[tuple] = []
        self.forced: list[tuple[str, dict]] = []
        self.built: list[tuple[str, dict, list[str]]] = []
        self.ignored: list[str] = []
        self.refuse_force = ""  # the words of a force the master refuses (403), when set
        self.session_user = ""  # who the session cookie it set is for

    @property
    def paths(self) -> list[str]:
        """Each request as its method and its path."""
        return [f"{m} {urlsplit(u).path}" for m, u, *_ in self.asked]

    def _user(self, headers: dict) -> str:
        return self.session_user if headers.get("Cookie") == f"TWISTED_SESSION={SESSION}" else ""

    def __call__(self, method, url, headers, body, timeout):
        if not str(url).startswith(self.base + "/"):  # asked elsewhere: refused before anything, and noted
            REACHED.append(f"a request to {urlsplit(str(url)).netloc}, not to the stand-in master at {self.base}")
            raise Reached(f"asked {urlsplit(str(url)).netloc}, not the stand-in master at {self.base}")
        self.asked.append((method, url, dict(headers), body, timeout))
        if self.down or (self.broken_after and len(self.asked) > self.broken_after):
            raise ConnectionRefusedError(10061, "No connection could be made because the target machine actively "
                                                "refused it")
        if self.redirect:
            return 302, [("Location", self.redirect + urlsplit(url).path), ("Content-Length", "0")], b""
        if self.other:
            return 404, [("Content-Type", "text/html")], b"<html><body><h1>No Such Resource</h1></body></html>"
        parts = urlsplit(url)
        path = unquote(parts.path[len(urlsplit(self.base).path):])
        if path == "/auth/login":
            return self._sign_in(headers)
        if path == "/config":
            return self._config(headers)
        if not path.startswith("/api/v2/"):
            return 404, [("Content-Type", "text/html")], b"<html><body>No Such Resource</body></html>"
        if self.private and not self._user(headers):
            return self._json(403, {"error": "you need to have role 'admins'"})
        steps = path[len("/api/v2/"):].split("/")
        if method == "POST":
            return self._control(steps, headers, body)
        return self._get(steps, parse_qs(parts.query))

    @staticmethod
    def _json(status: int, data, *headers) -> tuple:
        return status, [("Content-Type", "application/json"), *headers], json.dumps(data).encode()

    def _sign_in(self, headers: dict) -> tuple:
        given = headers.get("Authorization", "")
        if self.echo:
            typed = base64.b64decode(given.removeprefix("Basic ")).decode()
            said = f"could not check {given} ({typed})"
            if self.echo == "json":
                return self._json(500, {"error": {"code": 500, "message": said}})
            if self.echo == "html":
                return 500, [("Content-Type", "text/html")], f"<html><body>{html.escape(said)}</body></html>".encode()
            if self.echo == "far":  # its words after a tag so long that the token begins at byte 3,990 of the body
                lead, close = '<html><body><div class="', '">'
                pad = 3990 - len(lead) - len(close) - len("could not check Basic ")
                page = lead + "x" * pad + close + said + "</div></body></html>"
                return 500, [("Content-Type", "text/html")], page.encode()
            return 500, [("Content-Type", "text/plain")], said.encode()
        if self.auth == "RemoteUserAuth":  # its login page: refused, whoever asks
            return 403, [("Content-Type", "text/html")], (b"<html><body>URL is not supported for authentication"
                                                          b"</body></html>")
        if self.oauth2:  # sent on to its provider, no cookie set
            return 302, [("Location", "https://github.com/login/oauth/authorize?client_id=x"),
                         ("Content-Length", "0")], b""
        if not self.users:  # NoAuth: no sign-in to answer
            return 501, [("Content-Type", "text/plain")], b"not implemented"
        for user, password in self.users.items():
            if given == "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode():
                self.session_user = user
                return 302, [("Location", WEB_UI),
                             ("Set-Cookie", f"TWISTED_SESSION={ANONYMOUS}; Path=/; HttpOnly; SameSite=Lax"),
                             ("Set-Cookie", f"TWISTED_SESSION={SESSION}; Path=/; HttpOnly; SameSite=Lax"),
                             ("Content-Length", "0")], b""
        return 401, [("WWW-Authenticate", 'Basic realm="buildbot"'), ("Content-Type", "text/html")], b"Unauthorized"

    def _config(self, headers: dict) -> tuple:
        if self.version is None:
            return 404, [("Content-Type", "text/html")], b"<html><body>No Such Resource</body></html>"
        user = self._user(headers)
        name = self.auth or ("UserPasswordAuth" if self.users or self.echo else "NoAuth")
        auth = {"name": name, "oauth2": True, "fa_icon": "fa-github", "autologin": False} if self.oauth2 else {
            "name": name}
        return self._json(200, {
            "title": "Hello World CI", "titleURL": "https://buildbot.github.io/hello-world/",
            "buildbotURL": "http://localhost:8010/", "multiMaster": False, "port": 8010,
            "versions": [["Python", "3.12.3"], ["Buildbot", self.version], ["Twisted", "24.11.0"]],
            "auth": auth, "user": {"username": user} if user else {"anonymous": True}})

    def _get(self, steps: list[str], query: dict) -> tuple:
        kind = steps[0]
        rows = {"builders": self.builders, "builds": self.builds, "workers": self.workers,
                "forceschedulers": self.schedulers}.get(kind)
        if rows is None or len(steps) > 2:
            return self._json(404, {"error": f"Invalid path: {'/'.join(steps)}"})
        rows = list(rows)
        if len(steps) == 2:
            if kind == "forceschedulers":
                rows = [r for r in rows if r.get("name") == steps[1]]
            else:  # /builders/n:builderid first, as the master matches it: a step of digits alone is an id
                key = {"builders": "builderid", "builds": "buildid", "workers": "workerid"}[kind]
                by = key if steps[1].isdigit() else "name"
                rows = [r for r in rows if str(r.get(by)) == steps[1]]
            if not rows:
                return self._json(404, {"error": "not found"})
        if "name" in query:  # a field's filter: name=X
            rows = [r for r in rows if str(r.get("name")) == query["name"][0]]
        total = len(rows)
        if query.get("order") == ["-buildid"]:
            rows.sort(key=lambda r: -r["buildid"])
        if query.get("limit"):
            rows = rows[:int(query["limit"][0])]
        return self._json(200, {kind: rows, "meta": {"total": total}})

    def _control(self, steps: list[str], headers: dict, body: bytes) -> tuple:
        if headers.get("Content-Type") != "application/json":
            return self._json(400, {"jsonrpc": "2.0", "error": {"code": -32600, "message": "Invalid content-type (use "
                                                                                          "application/json)"}})
        call = json.loads(body)
        if call.get("jsonrpc") != "2.0" or not isinstance(call.get("params"), dict) or "id" not in call:
            return self._json(400, {"jsonrpc": "2.0", "error": {"code": -32600, "message": "invalid request"}})
        reply = {"jsonrpc": "2.0", "id": call["id"]}
        if steps[0] != "forceschedulers" or len(steps) != 2 or call.get("method") != "force":
            return self._json(501, {**reply, "error": {"code": -32601, "message": "invalid control action"}})
        sched = next((s for s in self.schedulers if s["name"] == steps[1]), None)
        if sched is None:
            return self._json(404, {**reply, "error": {"code": -32600, "message": "no such force scheduler"}})
        if self.refuse_force:
            return self._json(403, {**reply, "error": {"code": -32600, "message": self.refuse_force}})
        params = dict(call["params"])
        self.forced.append((steps[1], dict(params)))
        names, bid = params.pop("builderNames", None), params.pop("builderid", None)
        if names is not None:  # computeBuilderNames: those it starts, of those named
            names = sorted(set(names) & set(sched["builder_names"]))
        elif bid is not None:
            names = [b["name"] for b in self.builders if b["builderid"] == bid]
        else:
            names = list(sched["builder_names"])
        if not names:
            return self._json(500, {**reply, "error": {"code": -32603, "message": "builderNames not specified or not "
                                                                                 "supported"}})
        values, errors = {}, {}
        known = {f["fullName"] for f in leaves(sched["all_fields"])}
        for f in leaves(sched["all_fields"]):  # as each parameter's getFromKwargs reads its value
            given = params.get(f["fullName"])
            if f["type"] == "fixed":
                values[f["fullName"]] = f["default"]
            elif given in (None, "", []):
                if f.get("required"):
                    errors[f["fullName"]] = f"'{f['label']}' needs to be specified"
                values[f["fullName"]] = f["default"]
            elif f["type"] == "list" and f.get("strict", True) and given not in f.get("choices", []):
                errors[f["fullName"]] = f"'{given}' does not belong to list of available choices '{f['choices']}'"
            elif f["type"] == "int":
                values[f["fullName"]] = int(given)
            elif f["type"] == "bool":
                values[f["fullName"]] = given is True
            else:
                values[f["fullName"]] = given
        if errors:
            return self._json(400, {**reply, "error": {"code": -32602, "message": errors}})
        self.ignored += [k for k in params if k not in known and k != "owner"]
        self.built.append((steps[1], values, names))
        ids = [b["builderid"] for b in self.builders if b["name"] in names]
        return self._json(200, {**reply, "result": [77, {str(i): 100 + i for i in ids}]})
