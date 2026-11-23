"""Nothing in these tests installs, downloads, starts or asks anything for real: every request is a stand-in master's
(stand_ins.py, answering as Buildbot's documentation says a master does), a process started, a connection made or a
name looked up is refused, and no program is found on PATH. The guard is the docker plugin's, raising `Reached`, a
BaseException no `except Exception` swallows, and failing the test at its end as well; the settings' variables are taken
out of this process's environment."""
from __future__ import annotations

import shutil
import socket
import subprocess

import pytest

SETTINGS = ("BUILDBOT_URL", "BUILDBOT_USER", "BUILDBOT_PASSWORD")


class Reached(BaseException):
    """A test reached for real what it must stand in for."""


@pytest.fixture(autouse=True)
def nothing_runs(monkeypatch):
    reached: list[str] = []

    def refuse(what):
        def refused(*a, **k):
            __tracebackhide__ = True  # its arguments (a request's headers, with a password's token) never printed
            reached.append(what)
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
    yield
    assert not reached, f"the test reached {', '.join(reached)} for real"
