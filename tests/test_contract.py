"""Every plugin here conforms to the class contract (plugin API 2.2): liminal_libs.sources.conformance, read from the
plugin alone (nothing runs); the platform finds it by its entry point and draws it under its Continuous Integration
plugins; what it shares on its Internal API tab is sound; and its CI gives the code it installs nothing to push with."""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

import plugin_platform_buildbot as module
from liminal_libs.sources.conformance import assert_module_conforms, problems
from liminal_libs.ui import STATIC

ROOT = Path(__file__).resolve().parent.parent
SHA = re.compile(r"^[0-9a-f]{40}$")


def test_every_plugin_here_conforms_to_the_class_contract():
    found = assert_module_conforms(module)
    assert found and all(p.api == "2.2" and not p.is_record and problems(p) == [] for p in found)
    assert {p.SYSTEM for p in found} == {"platform"} and {p.KIND for p in found} == {"machine"}
    assert {p.name for p in found} == {"buildbot"} and {p.ICON for p in found} == {"buildbot"}


def test_it_is_drawn_under_the_platforms_continuous_integration_plugins():
    """Its section of the platform's list (the user, 2026-11-22: a Continuous Integration class of plugins, Jenkins,
    GoCD and Buildbot): "ci"; a platform that does not draw that section yet draws it under Machine plugins."""
    assert {p.SECTION for p in assert_module_conforms(module)} == {"ci"}


def test_what_it_shares_on_its_internal_api_tab_is_sound():
    """Its Internal API tab (liminal-libs 1.63.0's internal.py, newer than this plugin's 1.49.0 floor: skipped on a
    library before it): its words sound (each hook's docstring its line there, INTERNAL_NOTES lines of 400 characters
    at most, READ_HOOKS among its HOOKS), refresh asked as a read, and force never taken for one."""
    internal = pytest.importorskip("liminal_libs.internal")
    assert internal.problems(module.MACHINE) == []
    reads = internal.reads_of(module.MACHINE, ("present", "status"))
    assert "refresh" in reads and "force" not in reads
    assert module.MACHINE.READ_HOOKS == ("refresh",)


def test_its_icon_is_one_the_platforms_page_draws():
    """The tray and the page draw a plugin's icon by its name in the library's icons.js, and the plug for a name it does
    not have. Until Buildbot's mark is added there this fails as expected; once it is, it passes, its strict xfail
    says so, and the mark goes."""
    drawn = set(re.findall(r"^\s*([a-z]+):\s*'", (STATIC / "icons.js").read_text(encoding="utf-8"), re.M))
    assert module.MACHINE.ICON in drawn


def test_the_platform_finds_it_by_its_entry_point():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["entry-points"]["liminal.providers"] == {"buildbot": "plugin_platform_buildbot"}
    assert project["name"] == "plugin-platform-buildbot" and project["version"] == module.__version__ == "0.2.0"
    assert project["dependencies"] == ["liminal-libs>=1.94.0"]  # ContainedService, the base it is built on


def test_its_ci_gives_the_code_it_runs_no_token_and_nothing_that_moves():
    """Its workflow reads the repository and no more (permissions: contents: read), keeps no token in the checkout
    (persist-credentials: false), and runs no third-party action that moves under it: each at a commit. The library,
    first-party, is followed on its release branch, as every plugin's CI follows it."""
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert re.search(r"^permissions:\n  contents: read$", text, re.M)
    assert re.search(r"^\s+persist-credentials: false$", text, re.M)
    uses = re.findall(r"uses: ([\w./-]+)@(\S+)", text)
    assert uses and all(SHA.match(ref) for _, ref in uses), uses
    ref = re.search(r"^\s+LIMINAL_LIB_REF: (\S+)", text, re.M)
    assert ref and ref.group(1) == "release/0.2.0"
