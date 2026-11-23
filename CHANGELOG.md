# Changelog

## 0.1.0 (2026-11-23)

The first release (the user, 2026-11-22: a Continuous Integration class of platform plugins, with Jenkins, GoCD and
Buildbot in it). Needs liminal-libs>=1.49.0 (plugin API 2.2).

- **A Buildbot master read** at `BUILDBOT_URL` (`http://127.0.0.1:8010` unless set) over its REST API, the data API
  version 2: one GET each of `/config` (Buildbot's version, as the web server gives its own UI), `/api/v2/builders`,
  `/api/v2/builds?order=-buildid&limit=20`, `/api/v2/workers` and `/api/v2/forceschedulers`, 5 s each at most, kept
  30 s. The Builders, Recent builds, Workers and Force schedulers tables; a failure said in words on the page (nothing
  answers there, something that is not Buildbot's API, a sign-in wanted, the master stopping mid-read), never raised.
- **Buildbot here** by its files alone, nothing run: the `buildbot` and `buildbot-worker` commands, a master's or a
  worker's folder holding `buildbot.tac`, and on Linux the systemd units named `buildbot*.service`, on Windows, Linux
  and macOS alike, each walk bounded.
- **Force…** through a force scheduler, confirmed on the page first: of one builder it starts, or of every one, with a
  reason, a branch and a revision when they are given; the scheduler and the builder read again first, then one
  JSON-RPC call (`POST /api/v2/forceschedulers/<name>`, method `force`), sent once.
- **How to install and start Buildbot**, said and not done when no master answers: the documentation's steps (a
  virtual environment, `pip install 'buildbot[bundle]'`, `buildbot create-master`, `buildbot start`, `buildbot-worker`
  for the workers) as this system's shell types them, with docs.buildbot.net's pages.
- **Its settings** through the platform's login: the address, and a user and password for a master whose web UI asks a
  sign-in (`/auth/login` with HTTP basic credentials, its session cookie sent after it). The password goes to the
  sign-in alone and never over plain http to another machine, and is taken out of every word said; no redirect is
  followed and no proxy taken from the environment.
- **Its API on its page**: the Buildbot REST API card (`apis.py`, read from docs.buildbot.net on 2026-11-22) and
  `api_facts()` (the master as last read, the requests made, the last answer), asking nothing.
- Drawn under the platform's Continuous Integration plugins (`SECTION = "ci"`); its icon name is `buildbot`, which the
  library's icons.js does not draw yet.
- Tests: every request a stand-in master's, no process and no network (the guard fails a test that reaches either).
