# plugin-platform-buildbot

Buildbot for Liminal: a Buildbot master's builders, recent builds, workers and force schedulers, read from its REST API;
whether Buildbot is installed on this machine; and a build forced through a force scheduler once the platform's page
has confirmed it.

The user's words (2026-11-22): a new class of platform plugins, Continuous Integration, with three plugins in it:
Jenkins, GoCD and Buildbot.

## What it does

A machine plugin of the platform (`liminal_libs.machines.MachinePlugin`, plugin API 2.2), drawn under the platform's
**Continuous Integration plugins** (`SECTION = "ci"`; a platform that does not draw that section yet keeps it under
Machine plugins). Its icon is `buildbot`, which the library's icons.js does not draw yet.

- **The master**, at `BUILDBOT_URL` (`http://127.0.0.1:8010` unless set: the tutorial's master on this machine; a WSL
  distribution's master answers there too, through WSL's localhost). One GET each of the web server's `/config` (the
  versions its About page shows: Buildbot's, Twisted's and Python's), `/api/v2/builders`, `/api/v2/builds` (the 20
  newest: `?order=-buildid&limit=20`), `/api/v2/workers` and `/api/v2/forceschedulers`, each waiting 5 s at most;
  what was read is kept 30 s (the page asks every few seconds; Read again asks now; a force reads again at once).
- **The tables**: Builders (each one's description and tags, its last build among those read, its workers connected,
  a Force… where a force scheduler starts it), Recent builds (builder and number, result in words, when it started,
  how long it took or has run, its worker), Workers (connected or not, paused or graceful, its host and version, how
  many builders it is configured on), Force schedulers (each one's builders and a Force…), and Buildbot here.
- **Buildbot here**, by its files alone (nothing is run to know it: `buildbot --version` would start a process): the
  `buildbot` and `buildbot-worker` commands on PATH and where a pip install puts them (a virtual environment under a
  `~/buildbot*` folder, as the tutorial's `~/buildbot-test/master_root/sandbox`; `~/.local/bin`; Python's own Scripts
  folders on Windows; `/usr/bin`, `/usr/local/bin`, Homebrew's `/opt/homebrew/bin`), a master's or a worker's folder
  holding `buildbot.tac` (told apart by what it imports) under `~/buildbot*`, `/var/lib/buildbot`, `/srv/buildbot*`,
  `/opt/buildbot*` or the system drive's `buildbot*` folders, and on Linux a systemd unit named `buildbot*.service`
  (its file; `systemctl` is never run). Every walk is bounded: four folders down, 2,000 folders at most, no hidden or
  library folder and no link entered.
- **Force…**: a form per force scheduler, confirmed on the page first: the builder (one it starts, or every one), the
  reason, the branch and the revision (each left empty takes the scheduler's own). The scheduler is read from the
  master again (and the builder, for its id, as the master's own web UI sends it), then one JSON-RPC call is sent,
  once: `POST /api/v2/forceschedulers/<name>` with `{"jsonrpc": "2.0", "method": "force", "params": {...}, "id": 1}`.
  A name that is none, a scheduler or a builder the master has not, is refused before anything is sent.
- **How to install and start it**, said and not done (no install, start or stop in this release): when no master
  answers, the page lists the documentation's steps as this system's shell types them (a virtual environment,
  `pip install 'buildbot[bundle]'`, `buildbot create-master`, the sample's `master.cfg`, `buildbot start`; the workers
  with `buildbot-worker`), what of each it found here, and each step's page on docs.buildbot.net.

It is present when Buildbot is installed here or a web server answers at the address, and valid when the master's
builders are read. Otherwise its page says why: nothing answers there; something answers that is not Buildbot's REST
API; the master refuses its builders to anyone not signed in (HTTP 403), or to the user signed in as.

## Its settings

Kept through the platform's login (the plugin reads them with `self.login.variables(...)` and writes them nowhere):

- `BUILDBOT_URL`: the master's web address, as its web UI is opened (the path it is served under, behind a proxy).
- `BUILDBOT_USER` and `BUILDBOT_PASSWORD` (hidden): a user of the master's web sign-in (UserPasswordAuth, HTPasswdAuth),
  when it asks one; none when it asks none (NoAuth, Buildbot's default). As the REST API's documentation says, the
  plugin signs in with a GET of `/auth/login` with HTTP basic credentials and sends the session cookie it sets with the
  requests after it, for that read or that force alone. A master signing in through OAuth2 is not reached this way.

The password goes to `/auth/login` alone and never over plain http to another machine (an https address sends it); it,
its basic token and the session's cookie are taken out of every word the plugin says, and are never printed, logged,
returned or kept. Every request goes to the address set and nowhere else: no redirect is followed (one is said in words,
its address never asked), no proxy is taken from the environment or the system's settings, an answer is read to 4 MB at
most. The standard library's urllib does the requests (`client.py`): the plugin needs no package beyond liminal-libs.

## Its API

What it attaches to, as its page shows it (plugin API 2.2: `apis.py`, read from docs.buildbot.net on 2026-11-22):
**Buildbot REST API (data API v2)**: the [REST API](https://docs.buildbot.net/latest/developer/rest.html), its
[specification](https://docs.buildbot.net/latest/developer/raml/index.html) (26 resource types), the
[build result codes](https://docs.buildbot.net/latest/developer/results.html), the
[web server's design](https://docs.buildbot.net/latest/developer/www-server.html) (`/config`), the
[web server's configuration](https://docs.buildbot.net/latest/manual/configuration/www/server.html), its
[authentication and authorization](https://docs.buildbot.net/latest/manual/configuration/www/index.html), the
[ForceScheduler](https://docs.buildbot.net/latest/manual/configuration/schedulers.html#forcescheduler-scheduler), the
[tutorial's first run](https://docs.buildbot.net/latest/tutorial/firstrun.html) and the
[installation](https://docs.buildbot.net/latest/manual/installation/index.html) pages, the
[release notes](https://docs.buildbot.net/latest/relnotes/index.html) and
[its source](https://github.com/buildbot/buildbot). 25 parts, 6 of them used; 24 calls, the 9 it makes each named with
what it makes it for, the force marked as the one change.

`api_facts()` says what it learned while it ran, asking nothing: the master as last read (its address, its Buildbot
version, who it signed in as and the sign-in the master names, when), the requests made, the last answer and the last
trouble. `LIMINAL_VENDOR_PAGES=1 pytest tests/test_apis.py` checks that every address on the card still answers.

## Its hooks

`present` (installed here, or a web server answers at the address), `status` (the summary, the facts, `tables`,
`forms`, `actions`), `refresh()` (the master read again now: a read), `force(scheduler, builder, reason, branch,
revision)` (a change, confirmed on the page). `settings_changed()` forgets what was read, so the next look asks the
address and the user now set; `detach()` forgets it too.

## Tests

```
PYTHONPATH="<liminal>/common/src;src" PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider
```

Nothing in them runs a process or reaches the network (`tests/conftest.py` refuses both, and finds no program on PATH):
the master is a stand-in answering as Buildbot's documentation says a master does (`tests/stand_ins.py`), and this
machine's files are each test's own tree.
