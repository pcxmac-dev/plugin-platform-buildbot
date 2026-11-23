"""Buildbot: a master read as its REST API answers (the stand-in's, tests/stand_ins.py), the page the platform draws
(summary, facts, tables, forms), Buildbot found here by its files on each system, a build forced once confirmed and the
refusals before it, the password kept out of every answer, a redirect refused, the settings read through the login.
Nothing here runs a process or reaches the network (conftest.py)."""
from __future__ import annotations

import base64
import email.message
import inspect
import io
import json
import urllib.error
import urllib.request

import pytest

import plugin_platform_buildbot as bb
from plugin_platform_buildbot import BuildbotPlugin, clock
from plugin_platform_buildbot import client as cl
from plugin_platform_buildbot.finders import Finder, Found
from plugin_platform_buildbot.settings import read as read_settings
from stand_ins import BASE, MASTER_TAC, NOW, PASSWORD, SESSION, WORKER_TAC, Master, found, login

TOKEN = base64.b64encode(f"homer:{PASSWORD}".encode()).decode()  # the basic credentials' token, never said either


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


# -- a master read --------------------------------------------------------------------------------------------------
def test_status_reads_the_masters_builders_builds_workers_and_force_schedulers():
    m = Master()
    s = plugin(m).status()
    assert s["present"] is True and s["valid"] is True and s["why"] == "" and "problem" not in s
    assert s["summary"] == f"Buildbot 4.3.0 at {BASE} · 3 builders · 1 of 2 workers connected · last build: running"
    # one GET each, only at the address set, each with its wait; the builds the 20 newest
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


def test_an_answer_too_long_or_too_deep_is_not_read():
    long = cl.Master(cl.address(""), transport=lambda *a: (200, {}, b"x" * (cl.MOST + 1)))
    with pytest.raises(cl.BuildbotError, match=r"GET /config: its answer is longer than 4 MB: not read"):
        long.get("/config")
    deep = cl.Master(cl.address(""), transport=lambda *a: (200, {"Content-Type": "application/json"}, b"[" * 200_000))
    with pytest.raises(cl.BuildbotError, match="its answer is not JSON"):
        deep.get("/config")


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
    look = Finder(system="windows", home=home, env={"APPDATA": str(appdata)}, which=lambda name: None, drives=[drive])
    got = look.find()
    assert got.commands == (str(appdata / "Python" / "Python312" / "Scripts" / "buildbot.exe"),
                            str(tree / "master_root" / "sandbox" / "Scripts" / "buildbot.exe"))
    assert got.masters == (str(tree / "master_root" / "my_master"), str(drive / "buildbot" / "master"))
    assert got.worker_commands == (str(tree / "worker_root" / "sandbox" / "Scripts" / "buildbot-worker.exe"),)
    assert got.workers == (str(tree / "worker_root" / "my_worker"),) and got.units == ()

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
    assert [r[1] for r in steps["rows"]] == [  # typed in the home folder, alike in cmd and PowerShell
        r"py -m venv buildbot\sandbox",
        r'.\buildbot\sandbox\Scripts\pip install "buildbot[bundle]"',
        r".\buildbot\sandbox\Scripts\buildbot create-master buildbot\master",
        r"copy buildbot\master\master.cfg.sample buildbot\master\master.cfg",
        r".\buildbot\sandbox\Scripts\buildbot start buildbot\master",
        r".\buildbot\sandbox\Scripts\pip install buildbot-worker",
        r".\buildbot\sandbox\Scripts\buildbot-worker create-worker buildbot\worker localhost example-worker pass",
        r".\buildbot\sandbox\Scripts\buildbot-worker start buildbot\worker"]
    here = [r[2] for r in steps["rows"]]
    assert here[1] == {"text": f"found: {got.commands[0]}", "sub": "and 1 more"}
    assert here[2] == {"text": f"found: {got.masters[0]}", "sub": "and 1 more"}
    assert here[4] == f"nothing answers at {BASE}" and here[0] == "–"
    assert all(r[3].startswith("https://docs.buildbot.net/latest/") for r in steps["rows"])
    assert "typed in your home folder, in the Command Prompt or PowerShell alike" in steps["note"]


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
    assert [r[1] for r in steps["rows"]][:5] == [
        "python3 -m venv ~/buildbot/sandbox", "~/buildbot/sandbox/bin/pip install 'buildbot[bundle]'",
        "~/buildbot/sandbox/bin/buildbot create-master ~/buildbot/master",
        "mv ~/buildbot/master/master.cfg.sample ~/buildbot/master/master.cfg",
        "~/buildbot/sandbox/bin/buildbot start ~/buildbot/master"]
    assert "as a Linux or macOS shell types them" in steps["note"]


def test_present_on_macos_by_homebrew_and_never_a_unit(tmp_path):
    root = tmp_path / "root"
    write(root / "opt" / "homebrew" / "bin" / "buildbot", "#!/opt/homebrew/bin/python3\n")
    write(root / "lib" / "systemd" / "system" / "buildbot@.service", "[Unit]\n")  # not a Mac's: never looked at
    (root / "Users" / "me").mkdir(parents=True)
    got = Finder(system="darwin", home=root / "Users" / "me", env={}, which=lambda name: None, root=root).find()
    assert got.commands == (str(root / "opt" / "homebrew" / "bin" / "buildbot"),) and got.units == ()
    assert "/opt/homebrew/bin" in got.looked


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
    assert [r[2] for r in steps["rows"]] == ["–", "not found here", "not found here", "–", f"nothing answers at {BASE}",
                                             "not found here", "not found here", "–"]
    assert steps["rows"][1][3] == "https://docs.buildbot.net/latest/tutorial/firstrun.html"
    assert m.paths == ["GET /config"]  # nothing installed, started or asked again: it is said, never done


def test_a_look_that_fails_is_said():
    def failing():
        raise PermissionError("denied")
    s = plugin(Master(), finds=failing).status()
    assert s["valid"] is True and s["problem"] == "the look for Buildbot here failed: PermissionError: denied"


# -- the sign-in and the password ----------------------------------------------------------------------------------
def test_a_master_that_asks_a_sign_in_is_signed_in_to_and_read():
    m = Master(users={"homer": PASSWORD}, private=True)
    s = plugin(m, BUILDBOT_USER="homer", BUILDBOT_PASSWORD=PASSWORD).status()
    assert s["valid"] is True and s["signIn"] == "as homer (the master's: UserPasswordAuth)"
    assert m.paths[0] == "GET /auth/login" and m.asked[0][2]["Authorization"] == f"Basic {TOKEN}"
    for _, _, headers, *_ in m.asked[1:]:  # the session's cookie after it, the credentials never again
        assert headers["Cookie"] == f"TWISTED_SESSION={SESSION}" and "Authorization" not in headers


def test_a_sign_in_refused_is_said_and_the_master_read_as_anyone():
    m = Master(users={"homer": "another"}, private=True)
    s = plugin(m, BUILDBOT_USER="homer", BUILDBOT_PASSWORD=PASSWORD).status()
    assert s["valid"] is False
    assert s["why"] == (f"the master at {BASE} refuses its builders to anyone not signed in (HTTP 403): the master "
                        "refused the sign-in as homer (HTTP 401): BUILDBOT_USER or BUILDBOT_PASSWORD is not one it "
                        "knows; read as anyone")
    s = plugin(Master(private=True)).status()  # no user set
    assert s["why"].endswith("(HTTP 403): set BUILDBOT_USER and BUILDBOT_PASSWORD (a user it knows)")
    s = plugin(Master(), BUILDBOT_USER="homer", BUILDBOT_PASSWORD=PASSWORD).status()  # a master asking none (NoAuth)
    assert s["valid"] is True and s["problem"].startswith("the master's sign-in answered HTTP 501 (not implemented)")


def test_the_password_is_in_no_answer_table_fact_or_word():
    m = Master(users={"homer": PASSWORD}, private=True)
    p = plugin(m, BUILDBOT_USER="homer", BUILDBOT_PASSWORD=PASSWORD)
    said = [p.status(), p.refresh(), p.force("force", "runtests", "nightly"), p.api_facts(), p.interface(),
            repr(read_settings(p.login))]
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


def test_the_password_never_goes_over_plain_http_to_another_machine():
    m = Master(base="http://ci.example.org:8010", users={"homer": PASSWORD})
    s = plugin(m, BUILDBOT_URL="http://ci.example.org:8010", BUILDBOT_USER="homer", BUILDBOT_PASSWORD=PASSWORD).status()
    assert s["valid"] is True and "GET /auth/login" not in m.paths
    assert all("Authorization" not in h for _, _, h, *_ in m.asked)
    assert s["problem"] == ("the password would go to ci.example.org over plain http, where anyone on the way can read "
                            "it: it is not sent (an https address in BUILDBOT_URL sends it); read without signing in")
    tls = Master(base="https://ci.example.org", users={"homer": PASSWORD})
    plugin(tls, BUILDBOT_URL="https://ci.example.org/", BUILDBOT_USER="homer", BUILDBOT_PASSWORD=PASSWORD).status()
    assert tls.paths[0] == "GET /auth/login"  # over https it goes, to the sign-in alone


# -- a force --------------------------------------------------------------------------------------------------------
def test_force_is_confirmed_on_the_page_then_posts_one_json_rpc_call():
    m = Master()
    p = plugin(m)
    s = p.status()
    assert [f["id"] for f in s["forms"]] == ["force:force", "force:release"]
    form = s["forms"][0]
    assert form["hook"] == "force" and form["confirm"]["yes"] == "Force it" and form["submit"] == "Review"
    assert form["confirm"]["title"] == "Force a build of {builder} through {scheduler}?"
    assert [f["name"] for f in form["fields"]] == list(inspect.signature(p.force).parameters)  # the hook's arguments
    assert form["fields"][0] == {"name": "scheduler", "label": "Force scheduler", "type": "fixed", "value": "force"}
    assert [c["value"] for c in form["fields"][1]["choices"]] == ["", "runtests", "docs"]
    assert form["fields"][1]["empty"] == "every builder it starts (runtests, docs)"
    assert "force" in p.interface()["hooks"] and "force" not in p.READ_HOOKS  # a change, never taken for a read

    m.asked.clear()
    answer = p.force("force", "runtests", "nightly check", "main", None)
    assert answer == {"said": f"a build of runtests asked of the master at {BASE}", "ok": True,
                      "lines": ["buildset 77, build request 101",
                                "it runs once a worker is free: Read again shows it under Recent builds"]}
    # the scheduler read again, the builder for its id, then the call, sent once
    assert m.paths == ["GET /api/v2/forceschedulers/force", "GET /api/v2/builders/runtests",
                       "POST /api/v2/forceschedulers/force"]
    method, url, headers, body, wait = m.asked[-1]
    assert url == f"{BASE}/api/v2/forceschedulers/force" and wait == cl.FORCE_S
    assert headers["Content-Type"] == "application/json"
    assert json.loads(body) == {"jsonrpc": "2.0", "method": "force", "id": 1,
                                "params": {"reason": "nightly check", "branch": "main", "builderid": 1}}
    assert m.forced == [("force", {"reason": "nightly check", "branch": "main", "builderid": 1})]
    m.asked.clear()
    p.status()  # what was read before it is forgotten: the page shows the build asked
    assert m.paths[0] == "GET /config"

    m.asked.clear()
    every = p.force("force")  # no builder: every one it starts, the scheduler's own fields
    assert every["said"] == f"a build of every builder force starts (runtests, docs) asked of the master at {BASE}"
    assert every["lines"][0] == "buildset 77, build requests 101, 102"
    assert m.paths == ["GET /api/v2/forceschedulers/force", "POST /api/v2/forceschedulers/force"]
    assert json.loads(m.asked[-1][3])["params"] == {}


@pytest.mark.parametrize("args, words", [
    (("no such!",), "not a force scheduler's name: 'no such!'"),
    (("9lives",), "not a force scheduler's name: '9lives'"),
    (("",), "not a force scheduler's name: ''"),
    (("force", "runtests", "x" * 201), "the reason is 200 characters at most"),
    (("force", "runtests", "two\nlines"), "the reason holds a line break or a control character"),
    (("force", "runtests", None, "my branch"), "the branch holds no space"),
    (("force", "run\x00tests"), "a builder's name holds a line break or a control character"),
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


def test_force_says_the_masters_refusal_and_a_force_unanswered():
    m = Master()
    m.refuse_force = "you need to have role 'admins'"
    with pytest.raises(cl.BuildbotError, match=r"^POST /api/v2/forceschedulers/force \(force\): HTTP 403: you need to "
                                               r"have role 'admins'$"):
        plugin(m).force("force", "runtests")
    gone = Master(broken_after=2)  # the scheduler and the builder read, the call unanswered
    with pytest.raises(cl.BuildbotError, match="no answer came, so it may have been done"):
        plugin(gone).force("force", "runtests")
    assert len(gone.asked) == 3  # sent once: never again


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


@pytest.mark.parametrize("typed, base, tls, local", [
    ("", BASE, False, True),
    ("localhost:8010", "http://localhost:8010", False, True),
    ("HTTPS://CI.Example.org:8443/bb/", "https://ci.example.org:8443/bb", True, False),
    ("http://[::1]:8010/#/builders", "http://[::1]:8010", False, True),
    ("http://buildbot.example.org", "http://buildbot.example.org", False, False),
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
    (f"http://homer:{PASSWORD}@ci.example.org:notaport", "BUILDBOT_URL carries no user name and no password"),
])
def test_an_address_that_is_none_is_refused_in_words(typed, words):
    with pytest.raises(ValueError) as e:
        cl.address(typed)
    assert str(e.value).startswith(words) and PASSWORD not in str(e.value)


def test_the_settings_come_through_the_login():
    m = Master(base="https://example.org/buildbot")
    plugin(m, BUILDBOT_URL="https://example.org/buildbot/#/builders").status()  # a master served under a path
    assert m.asked[0][1] == "https://example.org/buildbot/config"
    nobody = Master()
    s = plugin(nobody, BUILDBOT_URL=f"http://homer:{PASSWORD}@ci.example.org").status()
    assert s["valid"] is False and nobody.asked == [] and PASSWORD not in json.dumps(s)
    assert s["why"].startswith("BUILDBOT_URL carries no user name and no password") and s["address"].startswith("none")
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
    assert Found().any is False
