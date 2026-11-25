"""0.2.0: a Buildbot master and its worker in containers, through a container plugin's plans (the library's
ContainedService, 1.94.0), on the library's stand-ins alone (machines/servicestandins.py) and the master as the tests'
stand-in Master: no docker, no process, no socket. Its sign-in is seeded as a PBKDF2 hash, it runs on this PC alone
until that sign-in answers, its usage data is never sent, and Force… is its page's alone."""
from __future__ import annotations

import sys
import time
import types

import pytest

from liminal_libs.apps.asking import AskRefused
from liminal_libs.instances import Refusal
from liminal_libs.machines.containedservice import UNREAD, Pace
from liminal_libs.machines.servicestandins import ServiceWorld

from plugin_platform_buildbot import BuildbotPlugin, recipe
from stand_ins import Master, found

DIG = "sha256:" + "d" * 64
PASSWORD = "correct-horse-battery-7"


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, s):
        self.now += s
        time.sleep(0.002)


def pins(digest=DIG):
    return {system: {part: {**pin, "digest": digest} for part, pin in parts.items()}
            for system, parts in recipe.PINS.items()}


def world(tmp_path, pairs=None, master=None, digest=DIG):
    c = Clock()
    m = master or Master(auth="LiminalAuth")
    p = BuildbotPlugin(http=m, find=found(), clock=c, system="linux", pace=Pace(clock=c, sleep=c.sleep),
                       pins=pins(digest))
    w = ServiceWorld(p, pairs={"BUILDBOT_ADMIN_PASSWORD": PASSWORD} if pairs is None else pairs, folder=tmp_path)
    return w, p, m


def test_its_shipped_pins_are_unread_and_refused(tmp_path):
    assert all(pin["digest"] == UNREAD for parts in recipe.PINS.values() for pin in parts.values())
    w, p, _ = world(tmp_path, digest=UNREAD)
    w.grant()
    with pytest.raises(Refusal, match="not pinned by digest yet"):
        w.ask("service_install", w.HOST, w.TARGET, "ci", "no")


def test_it_is_never_installed_open_nor_on_your_network_first(tmp_path):
    w, p, _ = world(tmp_path, pairs={})
    w.grant()
    with pytest.raises(Refusal, match="set BUILDBOT_ADMIN_PASSWORD"):
        w.ask("service_install", w.HOST, w.TARGET, "ci", "no")
    w.login.env["BUILDBOT_ADMIN_PASSWORD"] = PASSWORD
    with pytest.raises(Refusal, match="this PC alone first"):
        w.ask("service_install", w.HOST, w.TARGET, "ci", "yes")


def test_its_install_seeds_a_hash_and_its_worker_signs_in_with_a_secret_by_environment_alone(tmp_path):
    w, p, m = world(tmp_path)
    end = w.install("ci", "no")
    assert end["ok"], end
    files = w.fake.volumes["liminal-buildbot-ci-base"]["files"]
    cfg, auth = files["master.cfg"].decode(), files[recipe.AUTH_FILE].decode()
    assert 'c["buildbotNetUsageData"] = None' in cfg and "LiminalAuth" in cfg
    assert auth.startswith("admin:pbkdf2_sha256$") and PASSWORD not in auth and PASSWORD not in cfg
    worker = w.login.env["BUILDBOT_WORKER_PASSWORD"]
    assert len(worker) >= 24 and worker not in cfg  # made once, kept through the login
    made = w.fake.argv_of("create")
    assert [a[a.index("--name") + 1] for a in made] == ["liminal-buildbot-ci-master", "liminal-buildbot-ci-worker"]
    assert "-p 127.0.0.1:8010:8010/tcp" in " ".join(made[0])
    assert all(worker not in " ".join(a) and PASSWORD not in " ".join(a) for a in made)
    assert w.fake.containers["liminal-buildbot-ci-worker"]["secret_values"] == {"WORKERPASS": worker}
    assert "BUILDMASTER=liminal-buildbot-ci-master" in " ".join(made[1])
    assert "GET /config" in m.paths  # its readiness, asked at its here


def test_the_seeded_sign_in_takes_its_password_and_no_other():
    """master.cfg's LiminalAuth run on a stand-in of buildbot.plugins: its check is the library's PBKDF2 hash's."""
    from liminal_libs.machines.containedservice import pbkdf2_hash

    class CustomAuth:
        pass

    stub = types.SimpleNamespace(util=types.SimpleNamespace(
        CustomAuth=CustomAuth, BuildFactory=lambda steps: steps, BuilderConfig=lambda **k: k,
        Authz=lambda **k: k, AnyControlEndpointMatcher=lambda **k: k, RolesFromUsername=lambda **k: k),
        worker=types.SimpleNamespace(Worker=lambda *a: a), schedulers=types.SimpleNamespace(ForceScheduler=lambda **k: k),
        steps=types.SimpleNamespace(ShellCommand=lambda **k: k))
    sys.modules.setdefault("buildbot", types.ModuleType("buildbot"))
    plugins = types.ModuleType("buildbot.plugins")
    plugins.__dict__.update(vars(stub))
    old = sys.modules.get("buildbot.plugins")
    sys.modules["buildbot.plugins"] = plugins
    import os
    import tempfile

    folder = tempfile.mkdtemp()
    try:
        with open(os.path.join(folder, recipe.AUTH_FILE), "w", encoding="utf-8") as f:
            f.write(f"admin:{pbkdf2_hash(PASSWORD, rounds=1000)}\n")
        scope = {"__file__": os.path.join(folder, "master.cfg")}
        os.environ["WORKERPASS"] = "x" * 24
        exec(compile(recipe.master_cfg(), "master.cfg", "exec"), scope)
        check = scope["c"]["www"]["auth"].check_credentials
        assert check(b"admin", PASSWORD.encode()) is True and check("admin", PASSWORD) is True
        assert check("admin", "wrong") is False and check("root", PASSWORD) is False
        assert scope["c"]["buildbotNetUsageData"] is None
    finally:
        os.environ.pop("WORKERPASS", None)
        if old is None:
            sys.modules.pop("buildbot.plugins", None)
        else:
            sys.modules["buildbot.plugins"] = old


def test_expose_opens_it_only_once_its_sign_in_answers(tmp_path):
    m = Master(auth="NoAuth")
    w, p, _ = world(tmp_path, master=m)
    assert w.install("ci", "no")["ok"]
    with pytest.raises(Refusal, match="names no sign-in"):
        w.ask("service_change", "expose", "ci", "on")
    m.auth = "LiminalAuth"
    assert w.through(w.ask("service_change", "expose", "ci", "on"))["ok"]
    assert p.placement("ci")["lan"] is True


def test_its_reads_sign_in_as_the_seeded_admin_unless_yours_are_set(tmp_path):
    w, p, _ = world(tmp_path, master=Master(base="http://127.0.0.1:8011", auth="LiminalAuth"))
    assert w.install("ci", "no", "no", 1024, 8011)["ok"]
    s = p._settings()
    assert s.where.base == "http://127.0.0.1:8011" and s.user == "admin" and s.sign_in
    w.login.env.update(BUILDBOT_USER="homer", BUILDBOT_PASSWORD="doh-doh-doh")
    assert p._settings().user == "homer"


def test_force_is_asked_from_its_page_alone(tmp_path):
    w, p, _ = world(tmp_path)
    assert "force" in p.PAGE_ONLY_HOOKS
    with pytest.raises(AskRefused):
        w.host.ask_plugin("buildbot", "force", "force")


def test_on_windows_containers_it_is_not_yet():
    with pytest.raises(Refusal, match="not yet, decision 14"):
        recipe.spec("windows", "ci", {}, PASSWORD, pins())
