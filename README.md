# plugin-platform-buildbot

Buildbot for Liminal: a Buildbot master's builders, recent builds, workers and force schedulers, read from its REST API;
whether Buildbot is installed on this machine; and a build forced through a force scheduler once the platform's page
has confirmed it.

The user's words (2026-11-22): a new class of platform plugins, Continuous Integration, with three plugins in it:
Jenkins, GoCD and Buildbot.

## What it does

A machine plugin of the platform (`liminal_libs.machines.MachinePlugin`, plugin API 2.2), drawn under the platform's
**Continuous Integration plugins** (`SECTION = "ci"`; a platform that does not draw that section yet keeps it under
Machine plugins), after GoCD and Jenkins (`order = 811`). Its icon is `buildbot`, which the library's icons.js does not
draw yet: the tray and the page draw the plug for it meanwhile.

- **The master**, at `BUILDBOT_URL` (`http://127.0.0.1:8010` unless set: the tutorial's master on this machine; a WSL
  distribution's master answers there too, through WSL's localhost). One GET of the web server's `/config` first (the
  versions its About page shows: Buildbot's, Twisted's and Python's; and the sign-in it takes), the sign-in where one
  is set and taken (below), then one GET each of `/api/v2/builders`, `/api/v2/builds` (the 20 newest:
  `?order=-buildid&limit=20`), `/api/v2/workers` and `/api/v2/forceschedulers`. Each request has 5 s in all, its
  connection, its answer's status line, headers and body together (a timer shuts its socket down once they have
  passed), so an answer given a byte at a time ends in time too. What was read is kept 30 s (the page asks every few
  seconds; Read again asks now; a force reads again at once), and the page never queues behind a slow read: while one
  is under way, another ask waits 2 s at most, then takes what was read before.
- **The tables**: Builders (each one's description and tags, its last build among those read, its workers connected,
  a Force… where a force scheduler starts it), Recent builds (builder and number, result in words, when it started,
  how long it took or has run, its worker), Workers (connected or not, paused or graceful, its host and version, how
  many builders it is configured on), Force schedulers (each one's builders and a Force…, or why it has none here),
  and Buildbot here.
- **Buildbot here**, by its files alone (nothing is run to know it: `buildbot --version` would start a process): the
  `buildbot` and `buildbot-worker` commands on PATH and where a pip install puts them (a virtual environment under a
  `~/buildbot*` folder, as the tutorial's `~/buildbot-test/master_root/sandbox`; `~/.local/bin`; Python's own Scripts
  folders on Windows, `%APPDATA%\Python\Python3*` and `%LOCALAPPDATA%\Programs\Python\Python3*`; `/usr/bin`,
  `/usr/local/bin`, Homebrew's `/opt/homebrew/bin`), a master's or a worker's folder holding `buildbot.tac` (told apart
  by what it imports, as Buildbot's own Windows service tells them) under `~/buildbot*`, `/var/lib/buildbot`,
  `/srv/buildbot*`, `/opt/buildbot*` or the system drive's `buildbot*` folders; on Linux a systemd unit named
  `buildbot*.service` (its file; `systemctl` is never run), an init script (`/etc/init.d/buildbot`, `buildbot-worker`,
  `buildmaster`) and the folders `/etc/default/buildbot`, `buildmaster` and `buildbot-worker` name (their
  `MASTER_BASEDIR[n]` and `WORKER_BASEDIR[n]`); on Windows Buildbot's own service, `BuildBot` (what
  `buildbot_windows_service` and `buildbot_worker_windows_service` install), by its registry key under
  `HKLM\SYSTEM\CurrentControlSet\Services` read with a standard user's rights: its start, whose it is, the Python it
  runs from and the folders it runs (its `Parameters\directories`), with its state from the service control manager.
  Every folder is looked in once, as its real path (with `/usr` merged, `/lib` is `/usr/lib`). Every walk is bounded:
  four folders down, 2,000 folders at most, no hidden or library folder and no link entered.
- **Force…**: a form per force scheduler, confirmed on the page first, its fields the scheduler's own as its
  `all_fields` say them, as the master's own web UI offers them: the user's name, the reason, the priority, each
  codebase's branch, revision, repository and project (labelled `Codebase: app` for a named codebase), and the
  properties its master.cfg adds; a choice for a list (its choices) and for yes or no, a number for an integer, none
  for a field the scheduler fixes or hides. Each value is sent under the field's own name, its fullName (a named
  codebase's `app_branch`, never a plain `branch` the master would let go of without a word), and every builder the
  scheduler starts is the list the page showed: refused when the master now starts others, and sent as `builderNames`,
  so it adds none. The scheduler is read from the master again first (and the builder, by its name with the
  `?name=` filter, for its id, as the master's own web UI sends it), then one JSON-RPC call is sent, once:
  `POST /api/v2/forceschedulers/<name>` with `{"jsonrpc": "2.0", "method": "force", "params": {...}, "id": 1}`.
  Refused before anything is sent: a name that is none, a value that is not its field's (a choice it does not offer, a
  number that is not one, a space in a branch), a field the scheduler does not take, fixes or hides, one it needs that
  was not given, and a scheduler or a builder the master has not. A scheduler this page cannot fill (one needing a
  file, or named outside ASCII letters, digits, `_` and `-`, which the REST API's address does not take) has no form,
  and the page says why.
- **How to install and start it**, said and not done (no install, start or stop in this release): when no master
  answers, the page lists the documentation's steps as this system's shell types them (git first, which the sample's
  build checks out with; a virtual environment, activated as the tutorial does, every step after it typed in that
  shell, so the worker started there runs its builds with the sandbox's programs on PATH; `pip install
  'buildbot[bundle]'`, with the build tools Linux may need; `buildbot create-master`, the sample's `master.cfg`,
  `buildbot start`; the worker with `buildbot-worker`; on Windows the Command Prompt's way, with PowerShell's under it
  where it differs), what of each it found here, and each step's page on docs.buildbot.net.

It is present when Buildbot is installed here or a web server answers at the address, and valid when the master's
builders are read. Otherwise its page says why: nothing answers there; something answers that is not Buildbot's REST
API; the master refuses its builders to anyone not signed in (HTTP 403), or to the user signed in as.

## Its settings

Kept through the platform's login (the plugin reads them with `self.login.variables(...)` and writes them nowhere):

- `BUILDBOT_URL`: the master's web address, as its web UI is opened (the path it is served under, behind a proxy). It
  holds no `@` (a user name or a password typed into it is refused before anything of it is read), and no word the
  page says of it ever shows what was typed.
- `BUILDBOT_USER` and `BUILDBOT_PASSWORD` (hidden): a user of the master's web sign-in (UserPasswordAuth,
  HTPasswdAuth, CustomAuth), when it asks one; none when it asks none (NoAuth, Buildbot's default). As the REST API's
  documentation says, the plugin signs in with a GET of `/auth/login` with HTTP basic credentials, takes the session
  cookie the master sets last (it sets the anonymous session's first) and sends it with the requests after it, for
  that read or that force alone. It signs in only when the master's `/config` names a sign-in that takes them: never
  to a master asking none, nor one taking its user from the web server in front of it (RemoteUserAuth), nor one signing
  in through OAuth2. A sign-in the master refused is not sent again, as the page says, until the settings change or
  Read again asks.

The password goes to `/auth/login` alone and never over plain http to another machine (an https address sends it):
only the name `localhost` itself and a loopback address are this machine (a name under `.localhost` is not: a
resolver may ask its DNS server for it). A password shorter than 4 characters is not sent either: it could not be told
apart in what the master says back. The password, its basic token and the session's cookie are taken out of every word
the plugin says, out of the whole of what the master says before anything is made of it (its tags, escapes and spaces),
and are never printed, logged, returned or kept. Every request goes to the address set and nowhere else: no redirect is
followed (one is said in words, its address never asked), no proxy is taken from the environment or the system's
settings, an answer is read to 4 MB at most, and its JSON to 512 levels deep. The standard library's urllib does the
requests (`client.py`): the plugin needs no package beyond liminal-libs.

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
[its source](https://github.com/buildbot/buildbot). 25 parts, 6 of them used; 25 calls, the 9 it makes each named with
what it makes it for, the force marked as the one change.

`api_facts()` says what it learned while it ran, asking nothing: the master as last read (its address, its Buildbot
version, who it signed in as and the sign-in the master names, when), the requests made, the last answer and the last
trouble. `LIMINAL_VENDOR_PAGES=1 pytest tests/test_apis.py` checks that every address on the card still answers.

## Its hooks

`present` (installed here, or a web server answers at the address), `status` (the summary, the facts, `tables`,
`forms`, `actions`), `refresh()` (the master read again now: a read), `force(scheduler, builder, starts, fields,
*values)` (a change, confirmed on the page: `starts` the builders the page listed, `fields` the names of the fields
typed and `values` one each, in the form's order). `settings_changed()` forgets what was read, so the next look asks
the address and the user now set; `detach()` forgets it too, and a force does after it is sent; a read under way then
keeps nothing of what it read.

## Tests

```
PYTHONPATH="<liminal>/common/src;src" PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider
```

Nothing in them runs a process or reaches the network (`tests/conftest.py` refuses both, however they are reached:
an audit hook refuses Python's own events for a connection, a name looked up and a program started, beside its
patches, and finds no program on PATH): the master is a stand-in answering as Buildbot's documentation and code say a
master does (`tests/stand_ins.py`: its force schedulers' real `all_fields`, its sign-in's redirect and two cookies),
and this machine's files, registry and service manager are each test's own.
