"""Nothing in these tests installs, downloads, starts or asks anything for real: every request is a stand-in master's
(stand_ins.py, answering as Buildbot's documentation says a master does), and no program is found on PATH. While a
test runs, a process started, a connection made, a datagram sent or a name looked up is refused, whichever way it is
reached: an audit hook (sys.addaudithook) refuses Python's own events for them (EVENTS: socket.connect and the name
lookups, subprocess.Popen and asyncio's Popen with it, os.system, the os.exec, os.spawn and os.posix_spawn families,
os.startfile, os.fork, and _winapi.CreateProcess, multiprocessing's on Windows), beside the docker plugin's patches of
the usual ones. Each raises `Reached`, a BaseException no `except Exception` swallows, and is noted in REACHED, which
fails the test at its end as well; the stand-in master asked at another address does the same. The settings'
variables are taken out of this process's environment."""
from __future__ import annotations

import shutil
import socket
import subprocess
import sys

import pytest

from stand_ins import REACHED, Reached

SETTINGS = ("BUILDBOT_URL", "BUILDBOT_USER", "BUILDBOT_PASSWORD")
EVENTS = frozenset({"socket.connect", "socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyaddr",
                    "socket.getnameinfo", "socket.sendto", "subprocess.Popen", "os.system", "os.exec", "os.spawn",
                    "os.posix_spawn", "os.startfile", "os.fork", "_winapi.CreateProcess"})
_GUARD = {"on": False}  # the audit hook refuses while a test runs (an audit hook cannot be taken away once added)


def _audit(event: str, args) -> None:  # noqa: ARG001 - the audit hook's own signature
    if _GUARD["on"] and event in EVENTS:
        REACHED.append(event)
        raise Reached(f"a test reached {event} for real: give the plugin a stand-in")


sys.addaudithook(_audit)


class Guard:
    """One test's guard, as the fixture yields it: `off()` for the one test that reaches the makers' pages."""

    @staticmethod
    def off() -> None:
        _GUARD["on"] = False


@pytest.fixture(autouse=True)
def nothing_runs(monkeypatch):
    REACHED.clear()

    def refuse(what):
        def refused(*a, **k):
            __tracebackhide__ = True  # its arguments (a request's headers, with a password's token) never printed
            REACHED.append(what)
            raise Reached(f"a test reached {what} for real: give the plugin a stand-in")
        return refused

    monkeypatch.setattr(subprocess, "run", refuse("subprocess.run"))
    monkeypatch.setattr(subprocess, "Popen", refuse("subprocess.Popen"))
    monkeypatch.setattr(socket, "create_connection", refuse("socket.create_connection"))
    monkeypatch.setattr(socket, "getaddrinfo", refuse("socket.getaddrinfo"))
    monkeypatch.setattr(socket.socket, "connect", refuse("socket.connect"))
    monkeypatch.setattr(socket.socket, "connect_ex", refuse("socket.connect_ex"))
    monkeypatch.setattr(shutil, "which", lambda name, *a, **k: None)
    for name in SETTINGS:
        monkeypatch.delenv(name, raising=False)
    _GUARD["on"] = True
    try:
        yield Guard()
    finally:
        _GUARD["on"] = False
    assert not REACHED, f"the test reached {', '.join(REACHED)} for real"
