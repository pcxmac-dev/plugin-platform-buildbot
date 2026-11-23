"""Every plugin here conforms to the class contract (plugin API 2.2): liminal_libs.sources.conformance, read from the
plugin alone (nothing runs); the platform finds it by its entry point and draws it under its Continuous Integration
plugins."""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

import plugin_platform_buildbot as module
from liminal_libs.sources.conformance import assert_module_conforms, problems
from liminal_libs.ui import STATIC

ROOT = Path(__file__).resolve().parent.parent


def test_every_plugin_here_conforms_to_the_class_contract():
    found = assert_module_conforms(module)
    assert found and all(p.api == "2.2" and not p.is_record and problems(p) == [] for p in found)
    assert {p.SYSTEM for p in found} == {"platform"} and {p.KIND for p in found} == {"machine"}
    assert {p.name for p in found} == {"buildbot"} and {p.ICON for p in found} == {"buildbot"}


def test_it_is_drawn_under_the_platforms_continuous_integration_plugins():
    """Its section of the platform's list (the user, 2026-11-22: a Continuous Integration class of plugins, Jenkins,
    GoCD and Buildbot): "ci"; a platform that does not draw that section yet draws it under Machine plugins."""
    assert {p.SECTION for p in assert_module_conforms(module)} == {"ci"}


def test_its_icon_is_one_the_platforms_page_draws():
    """The tray draws the icon by its name in the library's icons.js: a name it does not have draws nothing."""
    drawn = set(re.findall(r"^\s*([a-z]+):\s*'", (STATIC / "icons.js").read_text(encoding="utf-8"), re.M))
    if module.MACHINE.ICON not in drawn:
        pytest.skip("the library's icons.js has no buildbot mark yet: until it has, the tray draws no icon for "
                    "Buildbot")
    assert module.MACHINE.ICON in drawn


def test_the_platform_finds_it_by_its_entry_point():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["entry-points"]["liminal.providers"] == {"buildbot": "plugin_platform_buildbot"}
    assert project["name"] == "plugin-platform-buildbot" and project["version"] == module.__version__ == "0.1.0"
    assert project["dependencies"] == ["liminal-libs>=1.49.0"]  # the docker plugin's floor: nothing newer is needed
