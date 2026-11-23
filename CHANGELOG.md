# Changelog

## 0.1.0 (2026-11-22)

The first release (the user, 2026-11-22: a Continuous Integration class of platform plugins, with Jenkins, GoCD and
Buildbot in it). Needs liminal-libs>=1.49.0 (plugin API 2.2).

- **A Buildbot master read** at `BUILDBOT_URL` (`http://127.0.0.1:8010` unless set) over its REST API, the data API
  version 2: one GET of `/config` first (Buildbot's version, as the web server gives its own UI, and the sign-in it
  takes), then one each of `/api/v2/builders`, `/api/v2/builds?order=-buildid&limit=20`, `/api/v2/workers` and
  `/api/v2/forceschedulers`, 5 s each in all (the connection, the status line, the headers and the body together),
  kept 30 s, and never queued behind: an ask while a read is under way takes what was read before. The Builders,
  Recent builds, Workers and Force schedulers tables; a failure said in words on the page (nothing answers there,
  something that is not Buildbot's API, a sign-in wanted, the master stopping mid-read), never raised.
- **Buildbot here** by its files alone, nothing run: the `buildbot` and `buildbot-worker` commands, a master's or a
  worker's folder holding `buildbot.tac`, on Linux the systemd units named `buildbot*.service`, the init scripts and
  the folders `/etc/default`'s files name, on Windows Buildbot's own `BuildBot` service by its registry key; on
  Windows, Linux and macOS alike, each folder looked in once, each walk bounded.
- **Force…** through a force scheduler, confirmed on the page first: its fields the scheduler's own, as its
  `all_fields` say them (a named codebase's `app_branch`, a choice's choices, nothing it fixes or hides), each value
  sent under its field's name; of one builder it starts (looked up by name), or of every one it starts as the page
  listed them (`builderNames`); the scheduler read again first, then one JSON-RPC call
  (`POST /api/v2/forceschedulers/<name>`, method `force`), sent once. A value the scheduler would let go of is refused
  before anything is sent.
- **How to install and start Buildbot**, said and not done when no master answers: the documentation's steps (git, a
  virtual environment activated as the tutorial does, `pip install 'buildbot[bundle]'` with the build tools Linux may
  need, `buildbot create-master`, `buildbot start`, `buildbot-worker` for the workers, started in that shell so their
  builds find the sandbox's programs) as this system's shell types them (the Command Prompt's and PowerShell's on
  Windows), with docs.buildbot.net's pages.
- **Its settings** through the platform's login: the address (no `@` in it, and never shown back when it is refused),
  and a user and password for a master whose web UI asks a sign-in (`/auth/login` with HTTP basic credentials, the last
  session cookie it sets sent after it), never sent to a master whose `/config` names a sign-in that takes none
  (NoAuth, RemoteUserAuth, OAuth2), and not sent again once refused until the settings change or Read again asks. The
  password goes to the sign-in alone, never over plain http to another machine (only `localhost` itself and a
  loopback address are this one), is 4 characters at least, and is taken out of every word said, before anything is
  made of the master's; no redirect is followed and no proxy taken from the environment.
- **Its API on its page**: the Buildbot REST API card (`apis.py`, read from docs.buildbot.net on 2026-11-22) and
  `api_facts()` (the master as last read, the requests made, the last answer), asking nothing.
- Drawn under the platform's Continuous Integration plugins (`SECTION = "ci"`), after GoCD and Jenkins; its icon name
  is `buildbot`, which the library's icons.js does not draw yet (the plug is drawn meanwhile).
- Tests: every request a stand-in master's (its force schedulers' real `all_fields`, its sign-in's redirect and two
  cookies), no process and no network (an audit hook and patches refuse both, and fail a test that reaches either).
  Its CI reads the repository and no more, keeps no token in its checkout, and pins its actions and the library to
  commits.
