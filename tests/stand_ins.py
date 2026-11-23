"""What the tests give the plugin in place of the world: a Buildbot master's web server (`Master`, a transport answering
as Buildbot's documentation says a master does: its REST API under /api/v2, its /config, its /auth/login), a login
holding the settings (`login`), and a look at this machine finding what it is told (`found`). Nothing here sends,
starts or reads anything outside the test."""
from __future__ import annotations

import base64
import json
from urllib.parse import parse_qs, unquote, urlsplit

from liminal_libs.apps import EnvironmentLogin
from plugin_platform_buildbot.finders import Found

NOW = 1_795_000_000.0  # the tests' wall clock (November 2026), seconds since the epoch
BASE = "http://127.0.0.1:8010"
PASSWORD = "doh!-c0rrect-h0rse"  # a password no answer, table or word may hold
SESSION = "eyJhbGciOiJIUzI1NiJ9.eyJ1c2VyIjoiaG9tZXIifQ.c2lnbmVk"  # the session cookie's value the master sets
MASTER_TAC = ("import os\n\nfrom twisted.application import service\nfrom buildbot.master import BuildMaster\n\n"
              "basedir = '.'\napplication = service.Application('buildmaster')\n"
              "m = BuildMaster(basedir, 'master.cfg', umask=None)\nm.setServiceParent(application)\n")
WORKER_TAC = ("import os\n\nfrom buildbot_worker.bot import Worker\nfrom twisted.application import service\n\n"
              "basedir = '.'\napplication = service.Application('buildbot-worker')\n"
              "s = Worker('localhost', 9989, 'example-worker', 'pass', basedir, 600, umask=None)\n")


def login(**values) -> EnvironmentLogin:
    """A login furnishing these settings (BUILDBOT_URL=..., BUILDBOT_USER=..., BUILDBOT_PASSWORD=...)."""
    return EnvironmentLogin(env={k: v for k, v in values.items() if v is not None})


def found(**parts):
    """A look at this machine that finds these (commands=("/usr/bin/buildbot",), masters=(...), ...)."""
    return lambda: Found(**{k: tuple(v) for k, v in parts.items()}, looked=("PATH", "~/buildbot*"))


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
    return [
        {"name": "force", "button_name": "Force", "label": "Force a build", "builder_names": ["runtests", "docs"],
         "all_fields": []},
        {"name": "release", "button_name": "Release", "label": "Release", "builder_names": ["old-release"],
         "all_fields": []},
    ]


class Master:
    """A Buildbot master's web server at `base`, as the plugin's transport: (method, url, headers, body, timeout) ->
    (status, headers, body). `users` ({user: password}): its web sign-in (UserPasswordAuth; none: NoAuth); `private`:
    its REST API refused (403) to anyone not signed in; `down`: nothing listens there; `redirect`: every request sent
    on to that address (HTTP 302); `version`: what its /config says Buildbot's is (None: it has no /config, as an
    older master); `other`: not Buildbot at all (every path a 404 page); `echo`: its sign-in's failure says back what
    it was sent (a careless proxy's 500); `broken_after`: requests answered before the connection is refused (0:
    never). Every request is kept (`asked`: method, url, headers, body, timeout), each force too (`forced`)."""

    def __init__(self, base: str = BASE, users=None, private: bool = False, down: bool = False, redirect: str = "",
                 version: str | None = "4.3.0", other: bool = False, echo: bool = False, broken_after: int = 0):
        self.base, self.users, self.private, self.down = base, dict(users or {}), private, down
        self.redirect, self.version, self.other = redirect, version, other
        self.echo, self.broken_after = echo, broken_after
        self.builders, self.builds, self.workers, self.schedulers = builders(), builds(), workers(), schedulers()
        self.asked: list[tuple] = []
        self.forced: list[tuple[str, dict]] = []
        self.refuse_force = ""  # the words of a force the master refuses (403), when set
        self.session_user = ""  # who the session cookie it set is for

    @property
    def paths(self) -> list[str]:
        """Each request as its method and its path."""
        return [f"{m} {urlsplit(u).path}" for m, u, *_ in self.asked]

    def _user(self, headers: dict) -> str:
        return self.session_user if headers.get("Cookie") == f"TWISTED_SESSION={SESSION}" else ""

    def __call__(self, method, url, headers, body, timeout):
        self.asked.append((method, url, dict(headers), body, timeout))
        if self.down or (self.broken_after and len(self.asked) > self.broken_after):
            raise ConnectionRefusedError(10061, "No connection could be made because the target machine actively "
                                                "refused it")
        assert url.startswith(self.base + "/"), f"asked {url}, not at {self.base}"
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
            return 500, [("Content-Type", "text/plain")], f"could not check {given} ({typed})".encode()
        if not self.users:  # NoAuth: no sign-in to answer
            return 501, [("Content-Type", "text/plain")], b"not implemented"
        for user, password in self.users.items():
            if given == "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode():
                self.session_user = user
                return 200, [("Set-Cookie", f"TWISTED_SESSION={SESSION}; Path=/; HttpOnly; SameSite=Lax"),
                             ("Content-Length", "0")], b""
        return 401, [("WWW-Authenticate", 'Basic realm="buildbot"'), ("Content-Type", "text/html")], b"Unauthorized"

    def _config(self, headers: dict) -> tuple:
        if self.version is None:
            return 404, [("Content-Type", "text/html")], b"<html><body>No Such Resource</body></html>"
        user = self._user(headers)
        return self._json(200, {
            "title": "Hello World CI", "titleURL": "https://buildbot.github.io/hello-world/",
            "buildbotURL": "http://localhost:8010/", "multiMaster": False, "port": 8010,
            "versions": [["Python", "3.12.3"], ["Buildbot", self.version], ["Twisted", "24.11.0"]],
            "auth": {"name": "UserPasswordAuth" if self.users else "NoAuth"},
            "user": {"username": user} if user else {"anonymous": True}})

    def _get(self, steps: list[str], query: dict) -> tuple:
        kind = steps[0]
        rows = {"builders": self.builders, "builds": self.builds, "workers": self.workers,
                "forceschedulers": self.schedulers}.get(kind)
        if rows is None or len(steps) > 2:
            return self._json(404, {"error": f"Invalid path: {'/'.join(steps)}"})
        rows = list(rows)
        if len(steps) == 2:
            key = {"builders": "builderid", "builds": "buildid", "workers": "workerid"}.get(kind, "name")
            rows = [r for r in rows if steps[1] in (str(r.get(key)), str(r.get("name")))]
            if not rows:
                return self._json(404, {"error": "not found"})
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
        self.forced.append((steps[1], call["params"]))
        bid = call["params"].get("builderid")
        names = [b["name"] for b in self.builders if b["builderid"] == bid] if bid else sched["builder_names"]
        ids = [b["builderid"] for b in self.builders if b["name"] in names]
        return self._json(200, {**reply, "result": [77, {str(i): 100 + i for i in ids}]})
