"""Buildbot: a master read as its REST API answers (the stand-in's, tests/stand_ins.py), the page the platform draws
(summary, facts, tables, forms), Buildbot found here by its files on each system, a build forced once confirmed (its
fields the scheduler's own, as its all_fields say them) and the refusals before it, the password kept out of every
answer, a redirect refused, the settings read through the login, the sign-in only where it is taken and never again
once refused, a read under way never waited on long and never kept once forgotten. Nothing here runs a process or
reaches the network (conftest.py)."""
from __future__ import annotations

import base64
import email.message
import functools
import html
import http.client
import inspect
import io
import json
import os
import socket
import threading
import urllib.error
import urllib.request

import pytest

import plugin_platform_buildbot as bb
from plugin_platform_buildbot import BuildbotPlugin, clock
from plugin_platform_buildbot import client as cl
from plugin_platform_buildbot.finders import Finder, Found
from plugin_platform_buildbot.settings import read as read_settings
from stand_ins import (ANONYMOUS, BASE, MASTER_TAC, NOW, PASSWORD, REACHED, SESSION, WORKER_TAC, Master, Reached,
                       codebase, force_fields, found, login, param)

TOKEN = base64.b64encode(f"homer:{PASSWORD}".encode()).decode()  # the basic credentials' token, never said either
DEFAULT_FIELDS = "username, reason, priority, branch, project, repository, revision"  # Buildbot's default form's


class Clock:
    """A monotonic clock the test moves."""

    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def plugin(master=None, finds=None, system="linux", **settings) -> BuildbotPlugin:
    p = BuildbotPlugin(http=master if master is not None else Master(), find=finds or found(), clock=Clock(),
                       wall=lambda: NOW, system=system)
    p.login = login(**settings)
    return p


def table(status: dict, title: str) -> dict:
    return next(t for t in status["tables"] if t["title"] == title)


def shown(c) -> str:
    """A cell as the page shows its first line: its text, or a button's title."""
    return c if isinstance(c, str) else c.get("text", c.get("title"))


def write(path, text: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def builder(bid: int, name: str) -> dict:
    return {"builderid": bid, "name": name, "description": None, "tags": [], "masterids": [1], "projectid": None}


def args_of(form: dict, values: dict) -> list:
    """The force hook's arguments as the platform's page sends a form (its argsOf): each field's value in order, a
    fixed field's own, one left empty None."""
    out = []
    for f in form["fields"]:
        v = f.get("value") if f["type"] == "fixed" else values.get(f["name"], f.get("value"))
        out.append(None if v in (None, "") else v)
    return out


# -- the guard -------------------------------------------------------------------------------------------------------
def test_the_guard_refuses_a_name_looked_up_a_program_started_and_another_host():
    """conftest.py's guard (its audit hook, beside its patches) refuses each way out, in Python's own words for it: a
    name looked up by gethostbyname and getnameinfo (which nothing patches), a program spawned (one that is not there,
    so that nothing could run were the guard gone), and the stand-in master asked at another address; each noted, so
    the test's end would fail too."""
    reaches = [lambda: socket.gethostbyname("localhost"), lambda: socket.getnameinfo(("127.0.0.1", 0), 0),
               lambda: Master()("GET", "http://elsewhere.example.org/config", {}, None, 5.0)]
    missing = os.path.join(os.path.dirname(os.path.abspath(__file__)), "no-such-program")
    if os.name == "nt":
        reaches.append(lambda: os.spawnv(os.P_NOWAIT, missing + ".exe", ["no-such-program"]))
    elif hasattr(os, "posix_spawn"):
        reaches.append(lambda: os.posix_spawn(missing, ["no-such-program"], {}))
    for reach in reaches:
        with pytest.raises(Reached):
            reach()
    assert len(REACHED) == len(reaches)
    REACHED.clear()  # this test's own reaching, on purpose


# -- a master read --------------------------------------------------------------------------------------------------
def test_status_reads_the_masters_builders_builds_workers_and_force_schedulers():
    m = Master()
    s = plugin(m).status()
    assert s["present"] is True and s["valid"] is True and s["why"] == "" and "problem" not in s
    assert s["summary"] == f"Buildbot 4.3.0 at {BASE} · 3 builders · 1 of 2 workers connected · last build: running"
    # one GET each, only at the address set, each with its time; the builds the 20 newest
    assert m.paths == ["GET /config", "GET /api/v2/builders", "GET /api/v2/builds", "GET /api/v2/workers",
                       "GET /api/v2/forceschedulers"]
    assert m.asked[2][1] == f"{BASE}/api/v2/builds?order=-buildid&limit=20"
    assert all(url.startswith(BASE + "/") and body is None and wait == cl.LOOK_S for _, url, _, body, wait in m.asked)
    assert all("Authorization" not in h and "Cookie" not in h for _, _, h, *_ in m.asked)  # no sign-in asked: none sent
    assert [t["title"] for t in s["tables"]] == ["Builders", "Recent builds", "Workers", "Force schedulers",
                                                 "Buildbot here"]

    builders = table(s, "Builders")
    assert [shown(r[0]) for r in builders["rows"]] == ["docs", "old-release", "runtests"]
    docs, old, tests = builders["rows"]
    assert docs[1:4] == ["–", {"text": "#3 failure", "sub": "2 h 00 min ago"}, "1 of 1 connected"]
    assert old[0] == {"text": "old-release", "sub": "on no master now"} and old[2:4] == ["–", "none"]
    assert tests[0] == {"text": "runtests", "sub": "the project's tests"}
    assert tests[1:4] == ["py", {"text": "#13 running", "sub": "1 min 30 s ago"}, "1 of 2 connected"]
    assert tests[4] == {"form": "force:force", "title": "Force…", "values": {"builder": "runtests"},
                        "label": "Force a build of runtests", "note": "through force"}
    assert old[4]["form"] == "force:release"

    built = table(s, "Recent builds")
    assert built["note"] == f"the 3 newest on {BASE}"
    assert [[shown(c) for c in r] for r in built["rows"]] == [
        ["runtests #13", "running", clock(NOW - 90), "running for 1 min 30 s", "example-worker"],
        ["runtests #12", "success", clock(NOW - 600), "2 min", "example-worker"],
        ["docs #3", "failure", clock(NOW - 7200), "1 min 40 s", "example-worker"]]
    assert built["rows"][0][1] == {"text": "running", "sub": "running 'pytest'"}

    w = table(s, "Workers")
    assert w["rows"] == [[{"text": "example-worker", "sub": "buildbox"}, "connected", "4.3.0", "2"],
                         ["windows-worker", {"text": "not connected", "sub": "paused: disk full"}, "–", "1"]]
    assert "admin@example.org" not in json.dumps(s)  # a worker's admin's address is the master's, not the page's

    f = table(s, "Force schedulers")
    assert [[shown(c) for c in r] for r in f["rows"]] == [["force", "runtests, docs", "Force…"],
                                                          ["release", "old-release", "Force…"]]
    assert f["rows"][0][0] == {"text": "force", "sub": "Force a build"}

    assert s["address"] == BASE and s["version"] == "Buildbot 4.3.0 (Python 3.12.3, Twisted 24.11.0)"
    assert s["title"] == "Hello World CI" and s["signIn"] == "none: read as anyone (the master's: NoAuth)"
    assert s["here"] == "nothing of Buildbot's"
    assert s["actions"] == [{"hook": "refresh", "args": [], "title": "Read again",
                             "note": "asks the master again now (what was read is kept 30 s)"}]


def test_what_was_read_is_kept_and_read_again_asks_now():
    m = Master()
    p = plugin(m)
    p.status()
    p.status()
    assert p.present() is True and len(m.asked) == 5  # kept: the page's next looks ask nothing
    p._clock.t += bb.READ_S + 1
    p.status()
    assert len(m.asked) == 10  # kept no longer
    answer = p.refresh()
    assert len(m.asked) == 15 and answer["ok"] is True and answer["said"] == f"read the master at {BASE} again now"
    assert answer["lines"] == ["3 builders, 3 recent builds, 2 workers (1 connected), 2 force schedulers"]


def test_the_version_is_what_the_masters_config_says():
    assert plugin(Master(version="4.4.0rc1")).status()["summary"].startswith(f"Buildbot 4.4.0rc1 at {BASE} · ")
    s = plugin(Master(version=None)).status()  # a master with no /config: read all the same, its version not said
    assert s["valid"] is True and s["summary"].startswith(f"Buildbot at {BASE} · 3 builders")
    assert s["version"] == "not said (GET /config: HTTP 404: No Such Resource)" and "problem" not in s


def test_a_master_that_stops_answering_leaves_the_rest_not_asked():
    m = Master(broken_after=2)  # /config and the builders answered, then nothing
    s = plugin(m).status()
    assert len(m.asked) == 3 and s["valid"] is True
    assert s["problem"] == (
        "its recent builds could not be read: GET /api/v2/builds: nothing answers there (the connection was refused); "
        "its workers could not be read: not asked: the master stopped answering (GET /api/v2/builds: nothing answers "
        "there (the connection was refused)); its force schedulers could not be read: not asked: the master stopped "
        "answering (GET /api/v2/builds: nothing answers there (the connection was refused))")
    assert table(s, "Recent builds")["empty"].startswith("Not read: GET /api/v2/builds: nothing answers there")
    assert s["forms"] == []  # no force scheduler read, no force offered


def test_something_that_is_not_buildbot_is_said_as_such():
    s = plugin(Master(other=True)).status()
    assert s["present"] is True and s["valid"] is False  # a web server answers there, not Buildbot's API
    assert s["why"] == (f"something answers at {BASE}, but not Buildbot's REST API (GET /api/v2/builders: HTTP 404: "
                        "No Such Resource): is BUILDBOT_URL the master's web address, as its web UI is opened?")
    assert s["summary"] == f"Buildbot at {BASE} could not be read"


@pytest.mark.parametrize("levels", [600, 100_000])
def test_an_answer_too_long_or_too_deep_is_not_read(levels):
    long = cl.Master(cl.address(""), transport=lambda *a: (200, {}, b"x" * (cl.MOST + 1)))
    with pytest.raises(cl.BuildbotError, match=r"GET /config: its answer is longer than 4 MB: not read"):
        long.get("/config")
    # a balanced document, JSON at any depth: past DEPTH_MOST levels it is none here, on every Python (600 levels
    # Python's own reader reads everywhere; 100,000 it reads on 3.15 on Linux, and not on Windows)
    balanced = b"[" * levels + b"]" * levels
    assert cl.too_deep(balanced) and not cl.too_deep(b"[" * 512 + b"]" * 512)
    assert not cl.too_deep(b'["' + b"[" * 2000 + b'"]')  # brackets in a string are text
    deep = cl.Master(cl.address(""), transport=lambda *a: (200, {"Content-Type": "application/json"}, balanced))
    with pytest.raises(cl.BuildbotError, match="its answer is not JSON"):
        deep.get("/config")
    assert cl.Answer(200, [], b"[" * 200_000).json() is None  # one never closed is none either


# -- Buildbot here, by its files -------------------------------------------------------------------------------------
def test_present_on_windows_by_the_tutorials_files(tmp_path):
    home = tmp_path / "Users" / "me"
    tree = home / "buildbot-test"
    write(tree / "master_root" / "sandbox" / "Scripts" / "buildbot.exe", "MZ")
    write(tree / "master_root" / "my_master" / "buildbot.tac", MASTER_TAC)
    write(tree / "worker_root" / "sandbox" / "Scripts" / "buildbot-worker.exe", "MZ")
    write(tree / "worker_root" / "my_worker" / "buildbot.tac", WORKER_TAC)
    appdata = tmp_path / "AppData" / "Roaming"
    write(appdata / "Python" / "Python312" / "Scripts" / "buildbot.exe", "MZ")
    drive = tmp_path / "C"
    write(drive / "buildbot" / "master" / "buildbot.tac", MASTER_TAC)
    look = Finder(system="windows", home=home, env={"APPDATA": str(appdata)}, which=lambda name: None, drives=[drive],
                  registry=lambda path: None, service_state=lambda name: ("", ""))
    got = look.find()
    assert got.commands == (str(appdata / "Python" / "Python312" / "Scripts" / "buildbot.exe"),
                            str(tree / "master_root" / "sandbox" / "Scripts" / "buildbot.exe"))
    assert got.masters == (str(tree / "master_root" / "my_master"), str(drive / "buildbot" / "master"))
    assert got.worker_commands == (str(tree / "worker_root" / "sandbox" / "Scripts" / "buildbot-worker.exe"),)
    assert got.workers == (str(tree / "worker_root" / "my_worker"),) and got.units == () and got.services == ()

    m = Master(down=True)
    p = plugin(m, finds=look.find, system="windows")
    assert p.present() is True  # installed here, though no master answers
    s = p.status()
    assert s["present"] is True and s["valid"] is False and s["forms"] == []
    assert s["summary"] == f"Buildbot is installed here; nothing answers at {BASE}"
    assert s["why"] == f"nothing answers at {BASE}: GET /config: nothing answers there (the connection was refused)"
    assert m.paths == ["GET /config"]  # the first request got no answer: nothing more is asked
    assert s["here"] == "2 buildbot commands, 2 master folders, 1 buildbot-worker command, 1 worker folder"
    assert [r[0] for r in table(s, "Buildbot here")["rows"]] == ["buildbot command"] * 2 + ["master"] * 2 + [
        "buildbot-worker command", "worker"]
    steps = table(s, "How to install and start Buildbot")
    assert [r[1] for r in steps["rows"]] == [  # typed in the home folder: the Command Prompt's way, PowerShell's under
        "git --version",
        r"py -m venv buildbot\sandbox",
        {"text": r"buildbot\sandbox\Scripts\activate.bat",
         "sub": r"in PowerShell: .\buildbot\sandbox\Scripts\Activate.ps1 (where PowerShell refuses to run it, the "
                "Command Prompt's way)"},
        'pip install "buildbot[bundle]"',
        r"buildbot create-master buildbot\master",
        r"copy buildbot\master\master.cfg.sample buildbot\master\master.cfg",
        r"buildbot start buildbot\master",
        "pip install buildbot-worker",
        r"buildbot-worker create-worker buildbot\worker localhost example-worker pass",
        r"buildbot-worker start buildbot\worker"]
    here = [r[2] for r in steps["rows"]]
    assert here[3] == {"text": f"found: {got.commands[0]}", "sub": "and 1 more"}
    assert here[4] == {"text": f"found: {got.masters[0]}", "sub": "and 1 more"}
    assert here[6] == f"nothing answers at {BASE}" and here[0] == "–"
    assert all(r[3].startswith("https://docs.buildbot.net/latest/") for r in steps["rows"])
    assert "the Command Prompt's way, with PowerShell's under it where it differs" in steps["note"]


def test_present_on_linux_by_a_package_and_its_systemd_units(tmp_path):
    root = tmp_path / "root"
    home = root / "home" / "me"
    write(root / "usr" / "bin" / "buildbot", "#!/usr/bin/python3\n")
    write(root / "var" / "lib" / "buildbot" / "masters" / "ci" / "buildbot.tac", MASTER_TAC)
    write(root / "lib" / "systemd" / "system" / "buildbot@.service", "[Unit]\n")
    write(root / "lib" / "systemd" / "system" / "buildbot-worker@.service", "[Unit]\n")
    write(root / "lib" / "systemd" / "system" / "ssh.service", "[Unit]\n")
    write(root / "etc" / "systemd" / "system" / "multi-user.target.wants" / "buildbot@ci.service", "[Unit]\n")
    write(home / ".config" / "systemd" / "user" / "buildbot-mine.service", "[Unit]\n")
    look = Finder(system="linux", home=home, env={}, which=lambda name: None, root=root)
    got = look.find()
    assert got.commands == (str(root / "usr" / "bin" / "buildbot"),)
    assert got.masters == (str(root / "var" / "lib" / "buildbot" / "masters" / "ci"),)
    assert got.units == (str(root / "etc" / "systemd" / "system" / "multi-user.target.wants" / "buildbot@ci.service"),
                         str(root / "lib" / "systemd" / "system" / "buildbot-worker@.service"),
                         str(root / "lib" / "systemd" / "system" / "buildbot@.service"),
                         str(home / ".config" / "systemd" / "user" / "buildbot-mine.service"))
    assert "systemd's unit folders (buildbot*.service)" in got.looked
    p = plugin(Master(down=True), finds=look.find, system="linux")
    assert p.present() is True
    steps = table(p.status(), "How to install and start Buildbot")
    assert [r[1] for r in steps["rows"]][:7] == [
        "git --version", "python3 -m venv ~/buildbot/sandbox", "source ~/buildbot/sandbox/bin/activate",
        {"text": "pip install 'buildbot[bundle]'",
         "sub": "on Linux pip may need these first (the tutorial's): sudo apt-get install build-essential python3-dev "
                "libssl-dev libffi-dev on Debian and Ubuntu, sudo yum install gcc python3-devel openssl-devel "
                "libffi-devel on RHEL, CentOS and Fedora"},
        "buildbot create-master ~/buildbot/master",
        "mv ~/buildbot/master/master.cfg.sample ~/buildbot/master/master.cfg",
        "buildbot start ~/buildbot/master"]
    assert "as a Linux or macOS shell types them" in steps["note"]


@pytest.mark.parametrize("system", ["linux", "darwin", "windows"])
def test_the_worker_is_started_with_its_sandbox_on_path(system):
    """The tutorial's way: its sandbox activated once, every step after it typed in that shell. Walked as the shell
    walks them: the worker is started after the activation, by its name alone (found on the PATH the activation set,
    which its builds inherit: the sample's runtests runs trial from it), and no later step names the sandbox's own
    folder (a program run by its path leaves the sandbox off PATH). Git, which the sample's build checks out with, is
    asked first."""
    steps = bb.install_steps(system)
    commands = [c if isinstance(c, str) else c["text"] for _, c, _, _ in steps]
    on_path = False
    for (what, _, page, _), command in zip(steps, commands):
        if "activate" in command.lower():
            on_path = True
            assert page == bb.FIRST_RUN
            continue
        if what.startswith("Start the worker"):
            assert on_path and command.split()[:2] == ["buildbot-worker", "start"]
        if on_path:
            assert "sandbox" not in command, command
    assert on_path and commands[0] == "git --version" and steps[0][2] == bb.FIRST_RUN
    if system == "windows":  # the Command Prompt's activation, and PowerShell's under it
        sub = next(c["sub"] for _, c, _, _ in steps if isinstance(c, dict))
        assert "Activate.ps1" in sub
    if system == "linux":  # the build tools pip may need, as the tutorial lists them
        bundle = next(c for what, c, _, _ in steps if what.startswith("Buildbot in it"))
        assert "build-essential" in bundle["sub"] and "libffi-devel" in bundle["sub"]


def test_present_on_macos_by_homebrew_and_never_a_unit(tmp_path):
    root = tmp_path / "root"
    write(root / "opt" / "homebrew" / "bin" / "buildbot", "#!/opt/homebrew/bin/python3\n")
    write(root / "lib" / "systemd" / "system" / "buildbot@.service", "[Unit]\n")  # not a Mac's: never looked at
    write(root / "etc" / "init.d" / "buildbot", "#!/bin/sh\n")  # nor this
    (root / "Users" / "me").mkdir(parents=True)
    got = Finder(system="darwin", home=root / "Users" / "me", env={}, which=lambda name: None, root=root).find()
    assert got.commands == (str(root / "opt" / "homebrew" / "bin" / "buildbot"),) and got.units == ()
    assert got.scripts == () and "/opt/homebrew/bin" in got.looked


def test_present_by_path_and_by_a_master_answering_alone():
    on_path = Finder(system="linux", home="/nowhere", env={}, root="/nowhere",
                     which=lambda name: f"/opt/ci/bin/{name}").find()
    assert on_path.commands == ("/opt/ci/bin/buildbot",) and on_path.worker_commands == ("/opt/ci/bin/buildbot-worker",)
    p = plugin(Master(), finds=found())  # nothing installed here: a master answering at its address is enough
    assert p.present() is True and p.status()["here"] == "nothing of Buildbot's"


def test_not_present_when_nothing_is_installed_and_nothing_answers():
    m = Master(down=True)
    p = plugin(m, finds=found())
    assert p.present() is False
    s = p.status()
    assert s["present"] is False and s["valid"] is False
    assert s["summary"] == f"Buildbot is not installed here; nothing answers at {BASE}"
    assert table(s, "Buildbot here")["empty"] == "Nothing of Buildbot's on this machine."
    steps = table(s, "How to install and start Buildbot")
    assert [r[2] for r in steps["rows"]] == ["–", "–", "–", "not found here", "not found here", "–",
                                             f"nothing answers at {BASE}", "not found here", "not found here", "–"]
    assert steps["rows"][3][3] == "https://docs.buildbot.net/latest/tutorial/firstrun.html"
    assert m.paths == ["GET /config"]  # nothing installed, started or asked again: it is said, never done


def test_a_look_that_fails_is_said():
    def failing():
        raise PermissionError("denied")
    s = plugin(Master(), finds=failing).status()
    assert s["valid"] is True and s["problem"] == "the look for Buildbot here failed: PermissionError: denied"


# -- the sign-in and the password ----------------------------------------------------------------------------------
def test_a_master_that_asks_a_sign_in_is_signed_in_to_and_read():
    m = Master(users={"homer": PASSWORD}, private=True)
    p = plugin(m, BUILDBOT_USER="homer", BUILDBOT_PASSWORD=PASSWORD)
    s = p.status()
    assert s["valid"] is True and s["signIn"] == "as homer (the master's: UserPasswordAuth)" and "problem" not in s
    # /config first, as anyone (the sign-in it takes), then the sign-in, then /config again as homer, then the rest
    assert m.paths[:3] == ["GET /config", "GET /auth/login", "GET /config"]
    assert "Cookie" not in m.asked[0][2] and m.asked[1][2]["Authorization"] == f"Basic {TOKEN}"
    for _, _, headers, *_ in m.asked[2:]:  # the signed-in session's cookie after it, the last the master set (never
        # the anonymous one it set first), and the credentials never again
        assert headers["Cookie"] == f"TWISTED_SESSION={SESSION}" and "Authorization" not in headers
        assert ANONYMOUS not in headers["Cookie"]
    assert p.api_facts()[bb.cards.REST]["Requests"] == "7 made"  # its redirect to the web UI is no failure


def test_a_sign_in_refused_is_said_and_the_master_read_as_anyone():
    m = Master(users={"homer": "another"}, private=True)
    s = plugin(m, BUILDBOT_USER="homer", BUILDBOT_PASSWORD=PASSWORD).status()
    assert s["valid"] is False
    assert s["why"] == (f"the master at {BASE} refuses its builders to anyone not signed in (HTTP 403): the master "
                        "refused the sign-in as homer (HTTP 401): BUILDBOT_USER or BUILDBOT_PASSWORD is not one it "
                        "knows; read as anyone")
    s = plugin(Master(private=True)).status()  # no user set
    assert s["why"].endswith("(HTTP 403): set BUILDBOT_USER and BUILDBOT_PASSWORD (a user it knows)")
    # a sign-in of the master's own (a CustomAuth of its master.cfg, named as its class is): asked, and its refusal
    # said without blaming the user and the password alone
    m = Master(users={"homer": "another"}, private=True, auth="LdapAuth")
    s = plugin(m, BUILDBOT_USER="homer", BUILDBOT_PASSWORD=PASSWORD).status()
    assert "GET /auth/login" in m.paths and "not one it knows" not in s["why"]
    assert ("the master refused the sign-in as homer (HTTP 401): its sign-in (LdapAuth) may take no user and password "
            "at /auth/login; read as anyone") in s["why"]


@pytest.mark.parametrize("given, words", [
    ({}, "the master asks no sign-in (NoAuth, Buildbot's default): BUILDBOT_USER and BUILDBOT_PASSWORD are not sent"),
    ({"auth": "RemoteUserAuth"}, "the master takes its user from the web server in front of it (RemoteUserAuth), "
                                 "never from a user and a password"),
    ({"auth": "GitHub", "oauth2": True},
     "the master signs in through OAuth2 (GitHub), which takes no user and password here"),
])
def test_a_master_whose_sign_in_takes_no_password_is_never_sent_one(given, words):
    m = Master(**given)
    p = plugin(m, BUILDBOT_USER="homer", BUILDBOT_PASSWORD=PASSWORD)
    s = p.status()
    assert "GET /auth/login" not in m.paths and all("Authorization" not in h for _, _, h, *_ in m.asked)
    assert s["valid"] is True and s["problem"].startswith(words) and "not one it knows" not in s["problem"]
    assert p.api_facts()[bb.cards.REST]["Requests"] == "5 made"  # no sign-in failed to count


def test_a_refused_sign_in_is_not_sent_again_until_the_settings_change_or_read_again():
    m = Master(users={"homer": "another"}, private=True)
    p = plugin(m, BUILDBOT_USER="homer", BUILDBOT_PASSWORD=PASSWORD)
    p.status()
    assert m.paths.count("GET /auth/login") == 1
    for _ in range(3):  # the page open: a read every READ_S, the sign-in not sent with any of them
        p._clock.t += bb.READ_S + 1
        s = p.status()
    assert m.paths.count("GET /auth/login") == 1
    assert ("the master refused the sign-in as homer before: it is not sent again until the settings change or Read "
            "again asks; read as anyone") in s["why"] and PASSWORD not in json.dumps(s)
    with pytest.raises(cl.BuildbotError, match=r"HTTP 403: .*; the master refused the sign-in as homer before: it is "
                                               r"not sent again"):  # nor a force's (the master refuses it as anyone's)
        p.force("force", "runtests")
    assert m.paths.count("GET /auth/login") == 1
    p.refresh()  # Read again: sent once more
    assert m.paths.count("GET /auth/login") == 2
    p._clock.t += bb.READ_S + 1
    p.status()
    assert m.paths.count("GET /auth/login") == 2
    m.users["homer"] = PASSWORD  # the password set right: the settings kept anew
    p.settings_changed()
    assert p.status()["valid"] is True and m.paths.count("GET /auth/login") == 3


def test_the_password_is_in_no_answer_table_fact_or_word():
    m = Master(users={"homer": PASSWORD}, private=True)
    p = plugin(m, BUILDBOT_USER="homer", BUILDBOT_PASSWORD=PASSWORD)
    said = [p.status(), p.refresh(), p.force("force", "runtests", None, "reason", "nightly"), p.api_facts(),
            p.interface(), repr(read_settings(p.login))]
    blob = json.dumps(said, default=str)
    for secret in (PASSWORD, TOKEN, SESSION):
        assert secret not in blob
    # a master (a proxy) that says back what it was sent: its words are said with the secrets taken out
    echo = plugin(Master(echo=True), BUILDBOT_USER="homer", BUILDBOT_PASSWORD=PASSWORD)
    s = echo.status()
    assert "could not check Basic ••• (homer:•••)" in s["problem"]
    assert PASSWORD not in json.dumps([s, echo.api_facts()]) and TOKEN not in json.dumps([s, echo.api_facts()])
    with pytest.raises(cl.BuildbotError) as e:  # an error raised carries none either
        cl.Master(cl.address(""), user="homer", password=PASSWORD,
                  transport=lambda *a: (500, {}, f"oops {PASSWORD} {TOKEN}".encode())).get("/config")
    assert PASSWORD not in str(e.value) and TOKEN not in str(e.value) and "oops ••• •••" in str(e.value)


@pytest.mark.parametrize("password", ["doh!<x>c0rrect", "doh!  c0rrect", "a&b<c"])
@pytest.mark.parametrize("echo", ["text", "html", "far", "json"])
def test_a_password_said_back_in_any_form_is_never_said(password, echo):
    """The secrets come out of the whole of what the master says before anything is made of it: a password holding
    a tag, two spaces or an ampersand, said back as it came, escaped in a page, after a tag so long that its token
    is cut at byte 4,000, or in a JSON error."""
    p = plugin(Master(echo=echo), BUILDBOT_USER="homer", BUILDBOT_PASSWORD=password)
    s = p.status()
    blob = json.dumps([s, p.api_facts()], ensure_ascii=False)
    token = base64.b64encode(f"homer:{password}".encode()).decode()
    for secret in (password, " ".join(password.split()), html.escape(password), html.escape(password, quote=False),
                   token, token[:12], password.replace("<x>", " ")):
        assert secret not in blob, secret
    assert "could not check Basic ••• (homer:•••)" in s["problem"]


def test_each_layer_keeps_a_secret_out_on_its_own(monkeypatch):
    """Two layers keep a secret out of the master's words, and each holds on its own: scrub knows a secret's forms
    (as given, quoted, its spaces made one, HTML-escaped); and the words are scrubbed before anything is made of them
    (a JSON error's message before its spaces are made one, a page's text before its tags and escapes are read) and
    again after, so a scrub that knew a secret as given alone would do."""
    for secret, said in (("doh!  c0rrect", "doh!  c0rrect"), ("doh!  c0rrect", "doh! c0rrect"),
                         ("a&b<c", "a&amp;b&lt;c"), ('a"b&c', "a&quot;b&amp;c"),
                         ("doh!  c0rrect", "doh%21%20%20c0rrect"), ("doh!  c0rrect", "doh%21++c0rrect")):
        assert cl.scrub(f"was {said} here", [secret]) == "was ••• here", (secret, said)
    assert cl.scrub("abc and abcd", ["abc"]) == "abc and abcd"  # one too short to be told apart is not taken out

    def given_alone(text, secrets):
        return functools.reduce(lambda t, x: t.replace(x, "•••"), [x for x in secrets if len(x) >= 4], str(text))

    monkeypatch.setattr(cl, "scrub", given_alone)
    for password, kind, body in (  # a JSON error's message, its spaces as typed; a page's, escaped
            ("doh!  c0rrect", "application/json", json.dumps({"error": {"message": "bad doh!  c0rrect"}}).encode()),
            ("a&b<cd", "text/html", b"<p>bad a&amp;b&lt;cd</p>")):
        m = cl.Master(cl.address(""), user="homer", password=password,
                      transport=lambda *a, said=body, kind=kind: (500, {"Content-Type": kind}, said))
        with pytest.raises(cl.BuildbotError) as e:
            m.get("/config")
        words = str(e.value)
        assert "bad •••" in words and password not in words and " ".join(password.split()) not in words
        assert html.escape(password) not in words and "c0rrect" not in words and "cd" not in words


def test_a_password_too_short_to_be_kept_out_of_words_is_not_sent():
    m = Master(users={"homer": "abc"}, private=True)
    s = plugin(m, BUILDBOT_USER="homer", BUILDBOT_PASSWORD="abc").status()
    assert "GET /auth/login" not in m.paths
    assert ("BUILDBOT_PASSWORD is shorter than 4 characters, too short to be kept out of what the master says back: it "
            "is not sent; read without signing in") in s["why"]


def test_the_password_never_goes_over_plain_http_to_another_machine():
    m = Master(base="http://ci.example.org:8010", users={"homer": PASSWORD})
    s = plugin(m, BUILDBOT_URL="http://ci.example.org:8010", BUILDBOT_USER="homer", BUILDBOT_PASSWORD=PASSWORD).status()
    assert s["valid"] is True and "GET /auth/login" not in m.paths
    assert all("Authorization" not in h for _, _, h, *_ in m.asked)
    assert s["problem"] == ("the password would go to ci.example.org over plain http, where anyone on the way can read "
                            "it: it is not sent (an https address in BUILDBOT_URL sends it); read without signing in")
    tls = Master(base="https://ci.example.org", users={"homer": PASSWORD})
    plugin(tls, BUILDBOT_URL="https://ci.example.org/", BUILDBOT_USER="homer", BUILDBOT_PASSWORD=PASSWORD).status()
    assert tls.paths[:2] == ["GET /config", "GET /auth/login"]  # over https it goes, to the sign-in alone


def test_a_name_under_localhost_is_not_this_machine():
    assert all(cl.is_local(h) for h in ("localhost", "LOCALHOST", "127.0.0.1", "127.8.9.10", "::1", "[::1]"))
    assert not any(cl.is_local(h) for h in ("ci.localhost", "a.b.localhost", "localhost.example.org", "10.0.0.1"))
    m = Master(base="http://ci.localhost:8010", users={"homer": PASSWORD})
    s = plugin(m, BUILDBOT_URL="http://ci.localhost:8010", BUILDBOT_USER="homer", BUILDBOT_PASSWORD=PASSWORD).status()
    assert "GET /auth/login" not in m.paths and all("Authorization" not in h for _, _, h, *_ in m.asked)
    assert s["problem"].startswith("the password would go to ci.localhost over plain http")
    sent = []  # and the client refuses it itself, whoever asks it
    said = cl.Master(cl.address("http://ci.localhost:8010"), user="homer", password=PASSWORD,
                     transport=lambda *a: sent.append(a)).sign_in()
    assert sent == [] and said.startswith("the password would go to ci.localhost over plain http, where anyone on the "
                                          "way can read it: it is not sent")


# -- a force --------------------------------------------------------------------------------------------------------
def test_force_is_confirmed_on_the_page_then_posts_one_json_rpc_call():
    m = Master()
    p = plugin(m)
    s = p.status()
    assert [f["id"] for f in s["forms"]] == ["force:force", "force:release"]
    form = s["forms"][0]
    assert form["hook"] == "force" and form["confirm"]["yes"] == "Force it" and form["submit"] == "Review"
    assert form["confirm"]["title"] == "Force a build of {builder} through {scheduler}?"
    names = [f["name"] for f in form["fields"]]
    hook = list(inspect.signature(p.force).parameters.values())
    assert names[:4] == [x.name for x in hook[:4]] == ["scheduler", "builder", "starts", "fields"]  # its arguments
    assert hook[4].name == "values" and hook[4].kind is inspect.Parameter.VAR_POSITIONAL  # then one per field
    assert names[4:] == ["field:" + n for n in DEFAULT_FIELDS.split(", ")]
    assert form["fields"][0] == {"name": "scheduler", "label": "Force scheduler", "type": "fixed", "value": "force"}
    assert [c["value"] for c in form["fields"][1]["choices"]] == ["", "runtests", "docs"]
    assert form["fields"][1]["empty"] == "every builder it starts (runtests, docs)"
    assert form["fields"][2] == {"name": "starts", "label": "Builders it starts", "type": "fixed",
                                 "value": "runtests, docs"}
    assert form["fields"][3]["value"] == DEFAULT_FIELDS
    by = {f["name"]: f for f in form["fields"]}
    assert [by[f"field:{n}"]["label"] for n in DEFAULT_FIELDS.split(", ")] == [
        "Your name", "Reason", "Priority", "Branch", "Project", "Repository", "Revision"]
    assert by["field:reason"]["placeholder"] == "the scheduler's own (force build)"
    assert by["field:priority"]["type"] == "number" and by["field:branch"]["note"] == "sent as branch"
    assert "force" in p.interface()["hooks"] and "force" not in p.READ_HOOKS  # a change, never taken for a read

    m.asked.clear()
    answer = p.force(*args_of(form, {"builder": "runtests", "field:reason": "nightly check", "field:branch": "main"}))
    assert answer == {"said": f"a build of runtests asked of the master at {BASE}", "ok": True,
                      "lines": ["buildset 77, build request 101", "with reason, branch as typed, the rest the "
                                "scheduler's own", "it runs once a worker is free: Read again shows it under Recent "
                                "builds"]}
    # /config (the sign-in it takes), the scheduler read again, the builder by its name for its id, then the call
    assert m.paths == ["GET /config", "GET /api/v2/forceschedulers/force", "GET /api/v2/builders",
                       "POST /api/v2/forceschedulers/force"]
    assert m.asked[2][1] == f"{BASE}/api/v2/builders?name=runtests"
    method, url, headers, body, wait = m.asked[-1]
    assert url == f"{BASE}/api/v2/forceschedulers/force" and wait == cl.FORCE_S
    assert headers["Content-Type"] == "application/json"
    assert json.loads(body) == {"jsonrpc": "2.0", "method": "force", "id": 1,
                                "params": {"reason": "nightly check", "branch": "main", "builderid": 1}}
    assert m.built[-1] == ("force", {"username": "", "reason": "nightly check", "priority": 0, "branch": "main",
                                     "project": "", "repository": "", "revision": ""}, ["runtests"])
    assert m.ignored == []  # nothing sent that the scheduler does not take
    m.asked.clear()
    p.status()  # what was read before it is forgotten: the page shows the build asked
    assert m.paths[0] == "GET /config"

    m.asked.clear()
    every = p.force(*args_of(form, {}))  # no builder: every one it starts, the scheduler's own fields
    assert every["said"] == f"a build of every builder force starts (runtests, docs) asked of the master at {BASE}"
    assert every["lines"][:2] == ["buildset 77, build requests 101, 102", "with the scheduler's own values"]
    assert m.paths == ["GET /config", "GET /api/v2/forceschedulers/force", "POST /api/v2/forceschedulers/force"]
    assert json.loads(m.asked[-1][3])["params"] == {"builderNames": ["runtests", "docs"]}


def test_a_named_codebases_fields_are_sent_under_their_own_names():
    """ForceScheduler(name="force", builderNames=["app-tests"], codebases=["app"]): its codebase's fields are
    app_branch, app_revision ...; a branch typed is sent as app_branch, and never as a plain branch it would let go
    of."""
    m = Master()
    m.builders.append(builder(4, "app-tests"))
    m.schedulers = [{"name": "force", "button_name": "force", "label": "force", "builder_names": ["app-tests"],
                     "enabled": True, "all_fields": force_fields(codebase("app"))}]
    p = plugin(m)
    form = p.status()["forms"][0]
    by = {f["name"]: f for f in form["fields"]}
    assert form["fields"][3]["value"] == "username, reason, priority, app_branch, app_project, app_repository, " \
                                         "app_revision"
    assert by["field:app_branch"]["label"] == "Codebase: app · Branch" and "field:branch" not in by
    answer = p.force(*args_of(form, {"builder": "app-tests", "field:app_branch": "release-2.0"}))
    assert answer["ok"] is True
    params = m.forced[-1][1]
    assert params == {"app_branch": "release-2.0", "builderid": 4} and "branch" not in params
    assert m.built[-1][1]["app_branch"] == "release-2.0" and m.ignored == []
    with pytest.raises(ValueError, match=r"^force takes no field branch: review it again"):
        p.force("force", "app-tests", None, "branch", "release-2.0")  # a plain branch: refused, never let go of
    assert len(m.forced) == 1


def test_the_documentations_scheduler_is_offered_as_its_fields_say():
    """The documentation's ForceScheduler ("pushMe!"): its branch one of master and hest, its revision, repository and
    project fixed (never offered, a value for one refused), its reason needed, its Build Options' pull url a text
    and its make clean yes or no; each refusal before anything is sent."""
    m = Master()
    p = plugin(m)
    form = p.status()["forms"][1]
    assert form["id"] == "force:release" and "pushMe!" in form["note"]
    assert form["fields"][3]["value"] == "username, reason, priority, branch, options_pull_url, " \
                                         "options_force_build_clean"
    by = {f["name"]: f for f in form["fields"]}
    assert by["field:reason"]["required"] is True and by["field:reason"]["label"] == "Reason"
    branch = by["field:branch"]
    assert branch["type"] == "choice" and branch["label"] == "Main repository · Branch"
    assert [c["value"] for c in branch["choices"]] == ["", "master", "hest"]
    assert branch["choices"][0]["title"] == "the scheduler's own (master)"
    assert by["field:options_pull_url"]["label"] == "Build Options · Optionally give a public Git pull url"
    clean = by["field:options_force_build_clean"]
    assert clean["type"] == "choice" and [c["value"] for c in clean["choices"]] == ["", "true", "false"]
    assert not any(n in by for n in ("field:revision", "field:repository", "field:project"))  # fixed

    for args, words in (
            (("release", None, "old-release", "revision", "abc123"),
             "release's Main repository · Revision (revision) takes no value from this page: the scheduler fixes its "
             "value"),
            (("release", None, "old-release"), "release needs its Reason (reason): give it"),
            (("release", None, "old-release", "reason, branch", "a release", "main"),
             "Main repository · Branch (branch) is one of its choices: master, hest"),
            (("release", None, "old-release", "reason, priority", "a release", "soon"),
             "Priority (priority) is a whole number"),
            (("release", None, "old-release", "reason, branch", "a release", "my branch"),
             "Main repository · Branch (branch) holds no space")):
        with pytest.raises(ValueError) as e:
            p.force(*args)
        assert str(e.value) == words
    assert m.forced == [] and not any(path.startswith("POST") for path in m.paths)

    answer = p.force(*args_of(form, {"field:reason": "a release", "field:branch": "hest",
                                     "field:options_force_build_clean": "true", "field:priority": 2.0}))
    assert answer["ok"] is True
    assert m.forced[-1][1] == {"reason": "a release", "priority": 2, "branch": "hest",
                               "options_force_build_clean": True, "builderNames": ["old-release"]}
    assert m.built[-1][1]["revision"] == "" and m.built[-1][1]["options_force_build_clean"] is True


def test_a_scheduler_this_page_cannot_fill_gets_no_form_and_is_refused():
    m = Master()
    m.schedulers += [
        {"name": "patched", "button_name": "Try", "label": "Try a patch", "builder_names": ["runtests"],
         "all_fields": force_fields(properties=(param("patch_body", "file", label="Patch body:", required=True),))},
        {"name": "café", "button_name": "Force", "label": "café", "builder_names": ["runtests"],
         "all_fields": force_fields()}]
    p = plugin(m)
    s = p.status()
    assert [f["id"] for f in s["forms"]] == ["force:force", "force:release"]
    rows = {shown(r[0]): r[2] for r in table(s, "Force schedulers")["rows"]}
    assert rows["patched"] == {"text": "–", "sub": (
        "it needs its Patch body (patch_body), which this page cannot fill (a field of type file is not filled from "
        "this page): force it from the master's web UI")}
    assert rows["café"] == {"text": "–", "sub": (
        "its name is not one the master's REST API takes in an address (ASCII letters, digits, _ and -): force it "
        "from the master's web UI")}
    m.asked.clear()
    with pytest.raises(ValueError, match=r"^patched needs its Patch body \(patch_body\), which this page cannot fill"):
        p.force("patched", "runtests")
    with pytest.raises(ValueError, match=r"^not a force scheduler's name: 'café' \(ASCII letters, digits, _ and -\)$"):
        p.force("café", "runtests")
    assert not any(path.startswith("POST") for path in m.paths)


@pytest.mark.parametrize("args, words", [
    (("no such!",), "not a force scheduler's name: 'no such!'"),
    (("9lives",), "not a force scheduler's name: '9lives'"),
    (("",), "not a force scheduler's name: ''"),
    (("force", "runtests", None, "reason", "x" * 201), "the value for reason is 200 characters at most"),
    (("force", "runtests", None, "reason", "two\nlines"),
     "the value for reason holds a line break or a control character"),
    (("force", "run\x00tests"), "a builder's name holds a line break or a control character"),
    (("force", None, None, "reason, reason", "a", "b"), "the field reason is named twice"),
    (("force", None, None, "reason", "a", "b"), "2 values for 1 fields named: one value each, in their order"),
    (("force", None, None, "no such!", "a"), "the fields are named as the scheduler names them"),
    (("force", None, None, "reason", ["a"]), "the value for reason is a text, a number, or true or false"),
])
def test_force_refuses_what_cannot_be_sent_before_asking_anything(args, words):
    m = Master()
    with pytest.raises(ValueError, match="^" + words.replace("(", r"\(").replace(")", r"\)").replace("?", r"\?")):
        plugin(m).force(*args)
    assert m.asked == []


def test_force_refuses_a_scheduler_or_a_builder_the_master_has_not():
    m = Master()
    p = plugin(m)
    with pytest.raises(ValueError, match=f"^the master at {BASE} has no force scheduler named nightly$"):
        p.force("nightly")
    with pytest.raises(ValueError, match="^force does not start old-release: it starts runtests, docs$"):
        p.force("force", "old-release")
    m.builders = [b for b in m.builders if b["name"] != "docs"]  # listed by the scheduler, gone from the master
    with pytest.raises(ValueError, match=f"^the master at {BASE} has no builder named docs$"):
        p.force("force", "docs")
    assert m.forced == [] and not any(path.startswith("POST") for path in m.paths)


@pytest.mark.parametrize("name", ["2024", "..", "."])
def test_a_builder_is_looked_up_by_its_name_never_by_an_address_built_of_it(name):
    """A builder named of digits alone (the master's /builders/n:builderid takes it for an id), or . and .. (a proxy in
    front of the master makes another path of them): asked of the builders by their name filter."""
    m = Master()
    m.builders.append(builder(7, name))
    m.schedulers[0]["builder_names"].append(name)
    answer = plugin(m).force("force", name)
    assert answer["said"] == f"a build of {name} asked of the master at {BASE}"
    assert m.forced[-1][1] == {"builderid": 7} and m.built[-1][2] == [name]
    assert f"{BASE}/api/v2/builders?name={name}" in [url for _, url, *_ in m.asked]
    assert not any(path.startswith("GET /api/v2/builders/") for path in m.paths)


def test_every_builder_is_the_list_the_page_confirmed():
    m = Master()
    p = plugin(m)
    starts = p.status()["forms"][0]["fields"][2]["value"]
    assert starts == "runtests, docs"
    m.builders.append(builder(9, "deploy-prod"))
    m.schedulers[0]["builder_names"].append("deploy-prod")  # the master reconfigured while the page's form was open
    with pytest.raises(ValueError, match=r"^force now starts deploy-prod too: review it again \(Read again shows what "
                                         r"it starts\)$"):
        p.force("force", None, starts)
    assert m.forced == []
    m.schedulers[0]["builder_names"] = ["runtests"]
    with pytest.raises(ValueError, match="^force no longer starts docs: review it again"):
        p.force("force", None, starts)
    m.schedulers[0]["builder_names"] = ["runtests", "docs"]

    def reconfigured(method, url, headers, body, timeout):  # once more, as the force is sent: the master adds none
        if method == "POST":
            m.schedulers[0]["builder_names"].append("deploy-prod")
        return m(method, url, headers, body, timeout)

    p._http = reconfigured
    p.force("force", None, starts)
    assert m.forced[-1][1] == {"builderNames": ["runtests", "docs"]} and m.built[-1][2] == ["docs", "runtests"]


def test_force_says_the_masters_refusal_and_a_force_unanswered(monkeypatch):
    m = Master()
    m.refuse_force = "you need to have role 'admins'"
    with pytest.raises(cl.BuildbotError, match=r"^POST /api/v2/forceschedulers/force \(force\): HTTP 403: you need to "
                                               r"have role 'admins'$"):
        plugin(m).force("force", "runtests")
    gone = Master(broken_after=3)  # /config, the scheduler and the builder read, the call unanswered
    with pytest.raises(cl.BuildbotError, match="no answer came, so it may have been done"):
        plugin(gone).force("force", "runtests")
    assert len(gone.asked) == 4  # sent once: never again
    # the master's own refusals, by field (its JSON-RPC error's message): as if this page had not checked the reason
    monkeypatch.setattr(BuildbotPlugin, "_params", staticmethod(lambda sched, given, name: {}))
    with pytest.raises(cl.BuildbotError, match=r"^POST /api/v2/forceschedulers/release \(force\): HTTP 400: reason: "
                                               r"'reason:' needs to be specified$"):
        plugin(Master()).force("release")


# -- a read under way --------------------------------------------------------------------------------------------------
def test_the_page_never_waits_behind_a_read_under_way(monkeypatch):
    monkeypatch.setattr(bb, "WAIT_S", 0.0)
    m = Master()
    p = plugin(m)
    inner: dict = {}

    def slow(method, url, headers, body, timeout):  # the first read's first request: the page asks meanwhile
        if not inner:
            inner["asking"] = True
            before = len(m.asked)
            asker = threading.Thread(target=lambda: inner.update(status=p.status(), present=p.present()), daemon=True)
            asker.start()
            asker.join(10)
            inner["waited"] = asker.is_alive()
            inner["asked"] = len(m.asked) - before
        return m(method, url, headers, body, timeout)

    p._http = slow
    s = p.status()
    assert s["valid"] is True and inner["waited"] is False and inner["asked"] == 0
    assert inner["status"]["valid"] is False
    assert inner["status"]["summary"] == f"Buildbot at {BASE}: a read is under way"
    assert inner["status"]["why"] == f"a read of the master at {BASE} is under way: its answer is not in yet"
    assert [t["title"] for t in inner["status"]["tables"]] == ["Buildbot here"] and inner["present"] is False
    # once a reading is kept, an ask during the next read gets it, kept, without waiting
    p._clock.t += bb.READ_S + 1
    inner.clear()
    assert p.status()["valid"] is True and inner["status"] == s and inner["asked"] == 0


def test_a_read_under_way_keeps_nothing_once_the_settings_change():
    old, new = Master(), Master(base="http://127.0.0.1:9010")
    p = plugin(old)
    first: list = []

    def transport(method, url, headers, body, timeout):  # the user keeps another address while the read is under way
        if not first:
            first.append(url)
            p.login = login(BUILDBOT_URL="http://127.0.0.1:9010")
            p.settings_changed()
        return (new if url.startswith(new.base) else old)(method, url, headers, body, timeout)

    p._http = transport
    assert p.status()["address"] == BASE  # its asker gets what it read
    s = p.status()  # and the next look asks the address now set, at once
    assert s["address"] == "http://127.0.0.1:9010" and new.paths[0] == "GET /config" and s["valid"] is True


def test_a_read_under_way_keeps_nothing_once_detached_or_forced():
    m = Master()
    p = plugin(m)

    def detached(method, url, headers, body, timeout):
        if len(m.asked) == 0:
            p.detach()
        return m(method, url, headers, body, timeout)

    p._http = detached
    p.status()
    assert p.api_facts() == {}  # nothing of the read under way kept, nor its requests counted

    m = Master()
    p = plugin(m)
    forced: list = []

    def forcing(method, url, headers, body, timeout):  # a force asked while the page's read is under way
        if not forced and method == "GET" and url.endswith("/api/v2/builders"):
            forced.append(p.force("force", "runtests"))
        return m(method, url, headers, body, timeout)

    p._http = forcing
    p.status()
    before = len(m.asked)
    p.status()  # what was read before the force is not kept: the page reads the build asked
    assert forced and len(m.asked) == before + 5


# -- the address ----------------------------------------------------------------------------------------------------
def test_a_redirect_is_said_and_never_followed():
    m = Master(redirect="https://ci.example.org")
    s = plugin(m).status()
    assert s["present"] is True and s["valid"] is False
    assert s["why"] == (f"the master at {BASE} could not be read: GET /api/v2/builders: the master sent it on to "
                        "https://ci.example.org/api/v2/builders (HTTP 302), which is not followed: only "
                        f"{BASE} is asked")
    assert all(url.startswith(BASE + "/") for _, url, *_ in m.asked)  # never the address it was sent on to


def test_the_standard_transport_follows_no_redirect_and_takes_no_proxy(monkeypatch):
    handlers = []

    class Opener:
        def open(self, request, timeout):
            assert (request.full_url, request.get_method(), timeout) == (f"{BASE}/config", "GET", 5.0)
            headers = email.message.Message()
            headers["Location"] = "https://elsewhere.example.org/config"
            raise urllib.error.HTTPError(request.full_url, 302, "Found", headers, io.BytesIO(b""))

    def opener(*given):
        handlers.extend(given)
        return Opener()

    monkeypatch.setattr(urllib.request, "build_opener", opener)
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):  # a proxy the environment names: not taken
        monkeypatch.setenv(name, "http://proxy.example.org:3128")
    assert cl.urllib_transport("GET", f"{BASE}/config", {"Accept": "application/json"}, None, 5.0) == (
        302, [("Location", "https://elsewhere.example.org/config")], b"")
    proxies = [h for h in handlers if isinstance(h, urllib.request.ProxyHandler)]
    assert len(proxies) == 1 and proxies[0].proxies == {}
    redirects = [h for h in handlers if isinstance(h, urllib.request.HTTPRedirectHandler)]
    assert len(redirects) == 1
    assert redirects[0].redirect_request(None, None, 302, "Found", {}, "https://x.example") is None


def test_an_answer_given_a_byte_at_a_time_ends_at_its_deadline(monkeypatch):
    """A request has its time in all: the body read a part at a time, the deadline looked at between them (a byte
    every 4 s came within each read's wait, and never whole), and the timer's expire shutting every socket held."""
    t = [0.0]
    real = cl.Deadline
    monkeypatch.setattr(cl, "Deadline", lambda seconds: real(seconds, clock=lambda: t[0]))

    class Drip:
        status = 200
        headers = {"Content-Type": "application/json"}

        def read1(self, n):
            t[0] += 4.0
            return b"["

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class Opener:
        def open(self, request, timeout):
            return Drip()

    monkeypatch.setattr(urllib.request, "build_opener", lambda *handlers: Opener())
    with pytest.raises(TimeoutError):
        cl.urllib_transport("GET", f"{BASE}/config", {}, None, 5.0)
    assert t[0] <= 8.0  # two reads at most: none after the deadline
    t[0] = 0.0
    with pytest.raises(cl.BuildbotError, match=r"^GET /config: no answer in 5 s$"):
        cl.Master(cl.address(""), transport=cl.urllib_transport).get("/config")

    class Sock:
        def __init__(self):
            self.done = []

        def shutdown(self, how):
            self.done.append("shutdown")

        def close(self):
            self.done.append("close")

    a, b = Sock(), Sock()
    d = real(5.0)
    d.hold(a)
    d.expire()  # the timer, once the deadline has passed: a read waiting on it ends at once
    d.hold(b)  # one connected after: shut at once
    assert a.done == b.done == ["shutdown", "close"] and d.passed and d.over()


def test_the_deadline_times_the_whole_request_from_its_connection(monkeypatch):
    """By order, not by time: the transport arms a timer of the request's time, which shuts the request's sockets
    (each held from its connection, a TLS one before its handshake) and breaks off a wait for the status line, said as
    no answer in time; the timer is cancelled once the request has ended."""
    armed = []

    class Timer:
        daemon = False

        def __init__(self, interval, function):
            armed.append({"interval": interval, "function": function, "started": False, "cancelled": False})

        def start(self):
            armed[-1]["started"] = True

        def cancel(self):
            armed[-1]["cancelled"] = True

    monkeypatch.setattr(cl.threading, "Timer", Timer)
    handlers = []

    class Waiting:  # the status line never comes: the timer fires, its socket shut, and the wait breaks off
        def open(self, request, timeout):
            armed[-1]["function"]()
            raise urllib.error.URLError(ConnectionAbortedError(10053, "the connection was aborted"))

    monkeypatch.setattr(urllib.request, "build_opener", lambda *given: handlers.extend(given) or Waiting())
    with pytest.raises(TimeoutError, match=r"^no whole answer in 5 s$"):
        cl.urllib_transport("GET", f"{BASE}/config", {}, None, 5.0)
    assert [(t["interval"], t["started"], t["cancelled"]) for t in armed] == [(5.0, True, True)]
    plain = next(h for h in handlers if isinstance(h, cl._Plain))
    tls = next(h for h in handlers if isinstance(h, cl._Tls))
    assert plain._deadline is tls._deadline and plain._deadline.passed  # the one the timer expired

    class Sock:
        def __init__(self):
            self.done = []

        def setsockopt(self, *a):
            pass

        def shutdown(self, how):
            self.done.append("shutdown")

        def close(self):
            self.done.append("close")

    raw = Sock()
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: raw)  # a connection, as it is made
    d = cl.Deadline(5.0)
    conn = cl._watched(http.client.HTTPConnection, d)("127.0.0.1", 8010, timeout=5.0)
    conn.connect()
    assert conn.sock is raw
    order = []

    class Context:
        def wrap_socket(self, sock, **kwargs):
            order.append(("wrapped", kwargs.get("do_handshake_on_connect")))
            return Tls()

    class Tls(Sock):
        def do_handshake(self):
            order.append(("handshake", self in d._held))

    wrapped = cl._Held(Context(), d).wrap_socket(raw, server_hostname="ci.example.org")
    assert order == [("wrapped", False), ("handshake", True)]  # held before its handshake
    d.expire()
    assert raw.done == wrapped.done == ["shutdown", "close"]


@pytest.mark.parametrize("typed, base, tls, local", [
    ("", BASE, False, True),
    ("localhost:8010", "http://localhost:8010", False, True),
    ("HTTPS://CI.Example.org:8443/bb/", "https://ci.example.org:8443/bb", True, False),
    ("http://[::1]:8010/#/builders", "http://[::1]:8010", False, True),
    ("http://buildbot.example.org", "http://buildbot.example.org", False, False),
    ("http://ci.localhost:8010", "http://ci.localhost:8010", False, False),
])
def test_an_address_is_read_as_typed(typed, base, tls, local):
    assert cl.address(typed) == cl.Address(base, cl.address(typed).host, tls, local)


@pytest.mark.parametrize("typed, words", [
    ("ftp://ci.example.org", "BUILDBOT_URL is an http or https address"),
    ("http://ci.example.org/?a=1", "BUILDBOT_URL carries no query"),
    ("http://ci.example.org /", "BUILDBOT_URL holds a space or a line break"),
    ("http://ci.example.org/../x", "BUILDBOT_URL's path holds no . and no .."),
    ("http://:8010", "BUILDBOT_URL names no host"),
    ("http://ci.example.org:99999", "BUILDBOT_URL is no address"),
    ("http://ci.example.org:s3cret", "BUILDBOT_URL is no address"),
    (f"http://homer:{PASSWORD}@ci.example.org:notaport", "BUILDBOT_URL carries no user name and no password"),
    ("http://homer:s3/cret@ci.example.org", "BUILDBOT_URL carries no user name and no password"),
    ("http://homer:12/secret@ci.example.org", "BUILDBOT_URL carries no user name and no password"),
    ("ci.example.org/x@y", "BUILDBOT_URL carries no user name and no password"),
])
def test_an_address_that_is_none_is_refused_in_words_that_never_hold_it(typed, words):
    with pytest.raises(ValueError) as e:
        cl.address(typed)
    said = str(e.value)
    assert said.startswith(words) and PASSWORD not in said and typed not in said
    for part in ("ci.example.org", "homer", "cret", "s3cret", "99999", "notaport"):
        assert part not in said


def test_the_settings_come_through_the_login():
    m = Master(base="https://example.org/buildbot")
    plugin(m, BUILDBOT_URL="https://example.org/buildbot/#/builders").status()  # a master served under a path
    assert m.asked[0][1] == "https://example.org/buildbot/config"
    for typed in (f"http://homer:{PASSWORD}@ci.example.org", "http://homer:12/secret@ci.example.org"):
        nobody = Master()
        s = plugin(nobody, BUILDBOT_URL=typed).status()
        assert s["valid"] is False and nobody.asked == [] and PASSWORD not in json.dumps(s)
        assert "secret" not in json.dumps(s) and "homer" not in json.dumps(s)
        assert s["why"].startswith("BUILDBOT_URL carries no user name and no password") and s["address"].startswith(
            "none")
        assert s["summary"] == "BUILDBOT_URL is not an address"
    half = plugin(Master(), BUILDBOT_USER="homer").status()
    assert half["problem"] == "BUILDBOT_USER is set but BUILDBOT_PASSWORD is not: read without signing in"

    class Broken:
        def variables(self, wanted):
            raise RuntimeError("the login app is away")
    p = plugin(Master())
    p.login = Broken()
    s = p.status()
    assert s["valid"] is True
    assert s["problem"].startswith("the settings could not be read from the login (RuntimeError)")


def test_settings_changed_and_a_detach_forget_what_was_read():
    m = Master()
    p = plugin(m)
    p.status()
    p.settings_changed()
    p.status()
    assert len(m.asked) == 10  # read again at once: the address or the user may be another
    assert p.api_facts() != {}
    p.detach()
    assert p.api_facts() == {} and p.login is None


def test_the_plugin_is_one_the_platform_loads():
    assert isinstance(bb.MACHINE, BuildbotPlugin) and bb.__version__ == "0.1.0"
    assert [k.name for k in bb.MACHINE.keys] == ["BUILDBOT_URL", "BUILDBOT_USER", "BUILDBOT_PASSWORD"]
    assert [k.secret for k in bb.MACHINE.keys] == [False, False, True]
    assert all(k.hint.startswith("optional") for k in bb.MACHINE.keys)  # the page draws them as optional
    assert bb.MACHINE.STEPS == () and not bb.MACHINE.gives("setup")  # no install, start or stop in 0.1.0
    assert bb.MACHINE.order == 772  # after its siblings Jenkins (770) and GoCD (771): last, as the user named them
    assert Found().any is False
