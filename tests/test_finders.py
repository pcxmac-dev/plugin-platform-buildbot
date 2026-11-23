"""The look at this machine (finders.py): a buildbot.tac told a master's from a worker's, the walks' bounds (how far
down, how many folders, the folders and links never entered), and what was found said in words. Each tree is a test's
own, under its tmp_path; nothing is run."""
from __future__ import annotations

import os

import pytest

from plugin_platform_buildbot.finders import DEPTH, Finder, Found, tac_kind, walk
from stand_ins import MASTER_TAC, WORKER_TAC


def write(path, text: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_a_tac_is_told_a_masters_or_a_workers(tmp_path):
    for name, text, kind in (("master", MASTER_TAC, "master"), ("worker", WORKER_TAC, "worker"),
                             ("slave", "from buildslave.bot import BuildSlave\n", "worker"), ("bare", "", "master")):
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
