"""What the plugin attaches to (plugin API 2.2; the user, 2026-11-11: "each plugin should reflect the the API its
attached to, and present links that provide documentation"): its card is sound; it names every call the plugin makes
(each request the stand-in master is sent, read as the plugin sends it) and claims none it does not make; its facts ask
nothing; and, with LIMINAL_VENDOR_PAGES=1 alone, every address on it answers (the only test here that reaches the
network)."""
from __future__ import annotations

import json
import os
import re
from urllib.parse import urlsplit

import pytest

import plugin_platform_buildbot as bb
from liminal_libs.sources import apis as A
from liminal_libs.sources.conformance import problems
from plugin_platform_buildbot import apis as cards
from stand_ins import NOW, PASSWORD, Master, found, login


def pattern(call: A.Call) -> tuple[str, re.Pattern, str]:
    """A call's method, its path as a pattern ({a placeholder} one step of a path), and its JSON-RPC method ("" for
    none): "POST /api/v2/forceschedulers/{schedulername} (force)"."""
    method, _, rest = call.name.partition(" ")
    rpc = re.fullmatch(r"(.*) \((\w+)\)", rest)
    path, method_of = (rpc.group(1), rpc.group(2)) if rpc else (rest, "")
    rx = re.sub(r"\\\{[^}]*\\\}", "[^/]+", re.escape(path.split("?", 1)[0]))
    return method, re.compile(rx + r"\Z"), method_of


def named(card: A.Api, method: str, url: str, body) -> A.Call | None:
    """The card's call a request is."""
    path = urlsplit(url).path
    said = json.loads(body).get("method", "") if body else ""
    for c in card.calls:
        m, rx, rpc = pattern(c)
        if m == method and rx.match(path) and rpc == said:
            return c
    return None


def flows() -> tuple[bb.BuildbotPlugin, Master]:
    """The plugin doing everything it does, against a stand-in master that asks a sign-in: read, read again, a build
    forced of one builder and of every builder a scheduler starts. Every request, as sent."""
    m = Master(users={"homer": PASSWORD}, private=True)
    p = bb.BuildbotPlugin(http=m, find=found(), wall=lambda: NOW, system="linux")
    p.login = login(BUILDBOT_USER="homer", BUILDBOT_PASSWORD=PASSWORD)
    p.status()
    p.refresh()
    p.force("force", "runtests", "nightly")
    p.force("release")
    return p, m


def test_its_card_is_sound_and_written_for_plugin_api_2_2():
    p = bb.MACHINE
    assert p.api == "2.2" and problems(p) == [] and A.problems(p.apis) == []
    assert [a.name for a in p.apis] == [cards.REST] and p.interface()["apis"] == [cards.REST]
    for a in p.apis:
        assert a.verified == "2026-11-22" and a.docs == "https://docs.buildbot.net/latest/developer/rest.html"
        assert a.used and a.covered and a.kind == "rest"
        assert all(c.area in {x.name for x in a.areas} for c in a.calls)  # every call in one of its parts
        assert len(a.areas) > len(a.covered) and len(a.calls) > len(a.used)  # more of the API than the plugin uses
        assert all(x.url.startswith(("https://docs.buildbot.net/latest/", "https://github.com/buildbot/"))
                   for x in a.links)


def test_the_card_names_every_call_the_plugin_makes_and_no_other():
    p, m = flows()
    card = p.apis[0]
    made = set()
    for method, url, _, body, _ in m.asked:
        c = named(card, method, url, body)
        assert c is not None and c.used, f"{method} {url}: not on the card as a call it makes"
        made.add(c.name)
    assert made == {c.name for c in card.used}  # each call it says it makes, made
    builds = next(url for method, url, *_ in m.asked if urlsplit(url).path == "/api/v2/builds")
    assert urlsplit(builds).query == "order=-buildid&limit=20"  # as the card says it


def test_the_force_is_the_one_write_and_nothing_costs():
    card = bb.MACHINE.apis[0]
    assert {c.name for c in card.used if c.writes} == {"POST /api/v2/forceschedulers/{schedulername} (force)"}
    assert not any(c.costs for c in card.calls)


def test_its_facts_say_what_it_learned_and_ask_nothing():
    assert bb.BuildbotPlugin().api_facts() == {}  # nothing read yet, nothing asked
    p, m = flows()
    p.status()  # the platform's page reads again after a force
    before = len(m.asked)
    facts = A.facts_of(p)
    assert len(m.asked) == before  # asked nothing to answer
    said = facts[cards.REST]
    assert set(facts) == {cards.REST}
    assert said["Master"] == "http://127.0.0.1:8010" and said["Buildbot"] == "4.3.0"
    assert said["Signed in"] == "as homer" and said["Its sign-in"] == "UserPasswordAuth"
    assert said["Requests"] == f"{before:,} made" and said["Last answer"].startswith("HTTP 200 in ")
    assert PASSWORD not in json.dumps(facts)


@pytest.mark.skipif(os.environ.get("LIMINAL_VENDOR_PAGES") != "1",
                    reason="reaches the makers' pages: LIMINAL_VENDOR_PAGES=1")
def test_every_address_on_its_card_answers(monkeypatch):
    monkeypatch.undo()  # this test alone reaches the network (conftest refuses it to every other)
    assert A.dead_links(bb.MACHINE.apis) == []
