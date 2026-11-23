"""The look at this machine (finders.py): a buildbot.tac told a master's from a worker's, the walks' bounds (how far
down, how many folders, the folders and links never entered), every place a command or a folder is put looked in once
(a folder linked to another, /usr merged, among them), Linux's init scripts and the folders their defaults name,
Buildbot's own Windows service by its registry key, and what was found said in words. Each tree is a test's own, under
its tmp_path, with stand-ins for the registry and the service manager; nothing is run."""
from __future__ import annotations

import os

import pytest

from plugin_platform_buildbot.finders import DEPTH, SERVICE_KEY, Finder, Found, tac_kind, walk
from stand_ins import MASTER_TAC, WORKER_TAC


def write(path, text: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def link(at, to) -> None:
    """`at` a link to the folder `to`: a junction on Windows (which anyone may make), a symbolic link elsewhere; the
    test skipped where none can be made."""
    try:
        if os.name == "nt":
            import _winapi

            _winapi.CreateJunction(str(to), str(at))
        else:
            os.symlink(to, at, target_is_directory=True)
    except OSError as e:
        pytest.skip(f"no link can be made here: {e}")


def windows(tmp_path, home, env=None, which=None, registry=None, state=("", "")) -> Finder:
    """A look as Windows's at a test's tree: its drive, and stand-ins for its registry and its service manager."""
    return Finder(system="windows", home=home, env=env or {}, which=which or (lambda name: None),
                  drives=[tmp_path / "C"], registry=registry or (lambda path: None),
                  service_state=lambda name: state)


def test_a_tac_is_told_a_masters_or_a_workers(tmp_path):
    for name, text, kind in (("master", MASTER_TAC, "master"), ("worker", WORKER_TAC, "worker"),
                             ("slave", "from buildslave.bot import BuildSlave\n", "worker"), ("bare", "", "master"),
                             ("service", "from my.own.package import Worker\n", "worker")):  # as the service says
        write(tmp_path / name / "buildbot.tac", text)
        assert tac_kind(tmp_path / name / "buildbot.tac") == kind, name
    assert tac_kind(tmp_path / "none" / "buildbot.tac") == "master"  # one that cannot be read is taken as a master's


def test_a_walk_goes_so_far_down_and_enters_no_hidden_or_library_folder(tmp_path):
    top = tmp_path / "buildbot"
    write(top / "a" / "b" / "c" / "d" / "buildbot.tac", MASTER_TAC)  # DEPTH folders down: found
    write(top / "a" / "b" / "c" / "d" / "e" / "buildbot.tac", MASTER_TAC)  # one further: not
    write(top / ".cache" / "m" / "buildbot.tac", MASTER_TAC)  # hidden: not entered
    write(top / "venv" / "lib" / "m" / "buildbot.tac", MASTER_TAC)  # a virtual environment's library: not entered
    write(top / "node_modules" / "m" / "buildbot.tac", MASTER_TAC)
    got = Finder(system="linux", home=tmp_path, env={}, which=lambda name: None, root=tmp_path / "root").find()
    assert DEPTH == 4 and got.masters == (str(top / "a" / "b" / "c" / "d"),)
    assert len(list(walk(top, visits=3))) == 3  # and so many folders at most
    assert list(walk(tmp_path / "not-there")) == []


def test_a_walk_enters_no_link_to_a_folder(tmp_path):
    elsewhere = tmp_path / "elsewhere"
    write(elsewhere / "m" / "buildbot.tac", MASTER_TAC)
    top = tmp_path / "buildbot"
    top.mkdir()
    link = top / "linked"
    try:
        if os.name == "nt":
            import _winapi

            _winapi.CreateJunction(str(elsewhere), str(link))  # a junction, which Windows lets anyone make
        else:
            os.symlink(elsewhere, link, target_is_directory=True)
    except OSError as e:
        pytest.skip(f"no link can be made here: {e}")
    assert [p.name for p in walk(top)] == ["buildbot"]  # the link's folder is never entered
    got = Finder(system="linux", home=tmp_path, env={}, which=lambda name: None, root=tmp_path / "root").find()
    assert got.masters == ()


def test_what_was_found_is_said_in_words():
    assert Found().any is False and Found().words() == "nothing of Buildbot's" and Found().rows() == []
    f = Found(commands=("/usr/bin/buildbot",), units=("/lib/systemd/system/buildbot@.service",
                                                       "/etc/systemd/system/buildbot.service"))
    assert f.any is True and f.words() == "1 buildbot command, 2 systemd units"
    assert f.rows() == [("buildbot command", "/usr/bin/buildbot"),
                        ("systemd unit", "/lib/systemd/system/buildbot@.service"),
                        ("systemd unit", "/etc/systemd/system/buildbot.service")]
    assert Found(worker_commands=("/usr/bin/buildbot-worker",)).any is True  # a worker alone is Buildbot here too


def test_the_same_file_found_twice_is_said_once(tmp_path):
    write(tmp_path / "usr" / "bin" / "buildbot", "#!/usr/bin/python3\n")
    on_path = str(tmp_path / "usr" / "bin" / "buildbot")
    got = Finder(system="linux", home=tmp_path / "home", env={}, root=tmp_path,
                 which=lambda name: on_path if name == "buildbot" else None).find()
    assert got.commands == (on_path,)  # on PATH and in /usr/bin: one file


def test_every_place_a_command_or_a_folder_is_put_is_looked_in_once(tmp_path):
    r"""Each place the module docstring names, found, and each found once: on Windows python.org's per-user Python
    (this PC's own layout: %LOCALAPPDATA%\Programs\Python\Python315\Scripts) and pip --user's ~\.local\bin; on Linux
    /usr/local/bin, ~/.local/bin, /srv/buildbot* and /opt/buildbot*."""
    home = tmp_path / "Users" / "me"
    local = tmp_path / "AppData" / "Local"
    exe = local / "Programs" / "Python" / "Python315" / "Scripts" / "buildbot.exe"
    write(exe, "MZ")
    write(home / ".local" / "bin" / "buildbot-worker.exe", "MZ")
    got = windows(tmp_path, home, env={"LOCALAPPDATA": str(local)}).find()  # by its place alone, not on PATH
    assert got.commands == (str(exe),)
    assert got.worker_commands == (str(home / ".local" / "bin" / "buildbot-worker.exe"),)
    again = windows(tmp_path, home, env={"LOCALAPPDATA": str(local)},
                    which=lambda name: str(exe) if name == "buildbot" else None).find()  # on PATH too: one file
    assert again.commands == (str(exe),)

    root = tmp_path / "root"
    me = root / "home" / "me"
    write(root / "usr" / "local" / "bin" / "buildbot", "#!/usr/bin/python3\n")
    write(me / ".local" / "bin" / "buildbot-worker", "#!/usr/bin/python3\n")
    write(root / "srv" / "buildbot-ci" / "m" / "buildbot.tac", MASTER_TAC)
    write(root / "opt" / "buildbot" / "w" / "buildbot.tac", WORKER_TAC)
    write(root / "srv" / "other" / "m" / "buildbot.tac", MASTER_TAC)  # not a buildbot* folder: not walked
    got = Finder(system="linux", home=me, env={}, which=lambda name: None, root=root).find()
    assert got.commands == (str(root / "usr" / "local" / "bin" / "buildbot"),)
    assert got.worker_commands == (str(me / ".local" / "bin" / "buildbot-worker"),)
    assert got.masters == (str(root / "srv" / "buildbot-ci" / "m"),)
    assert got.workers == (str(root / "opt" / "buildbot" / "w"),)


def test_with_usr_merged_each_unit_is_found_once(tmp_path):
    """Debian 12 and later, Ubuntu 22.04 and later (WSL's among them): /lib is a link to usr/lib, so the units its
    packages install in /usr/lib/systemd/system are in /lib/systemd/system too. Each folder is walked once, as its real
    path, and an enabled instance (a link in a .wants folder) is still its own."""
    root = tmp_path / "root"
    units = root / "usr" / "lib" / "systemd" / "system"
    write(units / "buildbot.service", "[Unit]\n")
    write(units / "buildbot@.service", "[Unit]\n")
    write(root / "etc" / "systemd" / "system" / "multi-user.target.wants" / "buildbot@ci.service", "[Unit]\n")
    link(root / "lib", root / "usr" / "lib")
    assert (root / "lib" / "systemd" / "system" / "buildbot.service").is_file()  # the same file, by both names
    got = Finder(system="linux", home=root / "home" / "me", env={}, which=lambda name: None, root=root).find()
    assert got.units == (str(root / "etc" / "systemd" / "system" / "multi-user.target.wants" / "buildbot@ci.service"),
                         str(units / "buildbot.service"), str(units / "buildbot@.service"))
    assert got.words() == "3 systemd units"


def test_init_scripts_and_the_folders_their_defaults_name(tmp_path):
    """A packaged master started by /etc/init.d/buildbot on a system without systemd, or Buildbot's contrib
    /etc/init.d/buildmaster, whose /etc/default/buildmaster names its folder (under the buildbot user's home, which no
    walk enters): the scripts found, and the folders their MASTER_BASEDIR[n] and WORKER_BASEDIR[n] name looked at for
    their buildbot.tac; a relative one and one in a comment are not."""
    root = tmp_path / "root"
    write(root / "etc" / "init.d" / "buildmaster", "#!/bin/sh\n")
    write(root / "etc" / "init.d" / "buildbot-worker", "#!/bin/sh\n")
    write(root / "etc" / "init.d" / "ssh", "#!/bin/sh\n")
    write(root / "etc" / "default" / "buildmaster",
          'MASTER_RUNNER=/usr/bin/buildbot\n\nMASTER_ENABLED[1]=1\nMASTER_NAME[1]="buildmaster #1"\n'
          'MASTER_USER[1]="buildbot"\nMASTER_BASEDIR[1]="/home/buildbot/ci-master"\nMASTER_OPTIONS[1]=""\n')
    write(root / "etc" / "default" / "buildbot-worker",
          "WORKER_BASEDIR[1]='/srv/workers/one'\nWORKER_BASEDIR[2]=relative/not\n"
          '# WORKER_BASEDIR[3]="/commented"\n  export WORKER_BASEDIR[4]=/var/workers/two\n')
    write(root / "home" / "buildbot" / "ci-master" / "buildbot.tac", MASTER_TAC)
    write(root / "srv" / "workers" / "one" / "buildbot.tac", WORKER_TAC)
    write(root / "var" / "workers" / "two" / "buildbot.tac", WORKER_TAC)
    write(root / "commented" / "buildbot.tac", MASTER_TAC)
    got = Finder(system="linux", home=root / "home" / "me", env={}, which=lambda name: None, root=root).find()
    assert got.scripts == (str(root / "etc" / "init.d" / "buildbot-worker"),
                           str(root / "etc" / "init.d" / "buildmaster"))
    assert got.masters == (str(root / "home" / "buildbot" / "ci-master"),)
    assert got.workers == (str(root / "srv" / "workers" / "one"), str(root / "var" / "workers" / "two"))
    assert got.words() == "1 master folder, 2 worker folders, 2 init scripts"
    assert "/etc/init.d (buildbot, buildbot-worker, buildmaster)" in got.looked


def test_buildbots_own_windows_service_is_found_by_its_registry_key(tmp_path):
    r"""A worker installed as Buildbot's documentation says (misc.html): buildbot_worker_windows_service ... install,
    its folder C:\bbw\worker in HKLM\SYSTEM\CurrentControlSet\Services\BuildBot\Parameters' directories, its
    environment C:\bbw\sandbox. Found while the service is stopped: its key, the folder it runs (a worker's, as its
    buildbot.tac says) and the commands of the environment it runs from."""
    bbw = tmp_path / "bbw"
    write(bbw / "worker" / "buildbot.tac", WORKER_TAC)
    write(bbw / "sandbox" / "Scripts" / "buildbot-worker.exe", "MZ")
    program = bbw / "sandbox" / "Lib" / "site-packages" / "win32" / "pythonservice.exe"
    keys = {SERVICE_KEY: {"ImagePath": f'"{program}"', "Start": 2, "ObjectName": ".\\worker", "Type": 16},
            SERVICE_KEY + "\\PythonClass": {"": "buildbot_worker.scripts.windows_service.BBService"},
            SERVICE_KEY + "\\Parameters": {"directories": f"{bbw / 'worker'};{bbw / 'gone'}"}}
    asked = []
    look = windows(tmp_path, tmp_path / "home", registry=keys.get)
    look._service_state = lambda name: asked.append(name) or ("stopped", "")
    got = look.find()
    assert asked == ["BuildBot"] and got.any is True
    assert got.workers == (str(bbw / "worker"),) and got.masters == ()
    assert got.worker_commands == (str(bbw / "sandbox" / "Scripts" / "buildbot-worker.exe"),)
    assert got.services == (f"BuildBot: Buildbot's worker service, started automatically, stopped; from {program}; it "
                            f"runs {bbw / 'worker'} (a worker's), {bbw / 'gone'} (no buildbot.tac: the service runs "
                            "none there)",)
    assert got.words() == "1 buildbot-worker command, 1 worker folder, 1 Windows service"
    assert ("Windows service", got.services[0]) in got.rows()
    assert "the Windows service BuildBot (its registry key, the folders it runs)" in got.looked

    def denied(path):
        raise PermissionError(5, "Access is denied")

    shut = windows(tmp_path, tmp_path / "home", registry=denied).find()  # there, but not this user's to read
    assert shut.services == ("BuildBot: its registry key is there but this user may not read it",) and shut.any
    assert windows(tmp_path, tmp_path / "home").find().services == ()  # not there: nothing said
