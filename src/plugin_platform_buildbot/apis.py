"""What the Buildbot plugin attaches to (plugin API 2.2; the user, 2026-11-11: "each plugin should reflect the the API
its attached to, and present links that provide documentation ... it should also expose more of what the API is
about"): a Buildbot master's REST API, the data API version 2 its own web UI reads, with the two parts of its web server
beside it that the plugin asks (/config, /auth/login). Each part of the API is named with what the plugin does with it,
each call it makes with what it makes it for, and the notable calls it does not make; every address was read on
docs.buildbot.net (its latest documentation, Buildbot 4.3 and 4.4) and github.com on 2026-11-22
(liminal_libs.sources.apis.dead_links checks them, LIMINAL_VENDOR_PAGES=1)."""
from __future__ import annotations

from liminal_libs.sources.apis import Api, Area, Call, Link

VERIFIED = "2026-11-22"
REST = "Buildbot REST API (data API v2)"

_DOCS = "https://docs.buildbot.net/latest/"
_REST = _DOCS + "developer/rest.html"
_WWW = _DOCS + "developer/www-server.html"
_SERVER = _DOCS + "manual/configuration/www/server.html"
_AUTH = _DOCS + "manual/configuration/www/index.html"
_INSTALL = _DOCS + "manual/installation/"


def _raml(kind: str) -> str:
    """A resource type's page of the REST API's specification."""
    return f"{_DOCS}developer/raml/{kind}.html"


BUILDBOT_REST = Api(
    name=REST, maker="the Buildbot project", kind="rest",
    about=("Buildbot's REST API, the data API's version 2, which its own web UI reads: a master's builders, builds, "
           "build requests, workers, schedulers, changes, steps, logs and the rest as collections under /api/v2 (each "
           "answer's list named by its type's plural, with meta.total), selected, filtered, ordered and paged by the "
           "query (field, {field}__{operator}, order, offset, limit); its controls (a force scheduler's force, a "
           "build's stop or rebuild, a build request's cancel, a worker's pause) are JSON-RPC 2.0 calls POSTed to the "
           "object's path. Beside it the master's web server gives its UI its configuration (/config: the versions of "
           "Buildbot, Twisted and Python among it) and its sign-in (/auth/login). The plugin reads four collections "
           "and /config, signs in when a user is set, and asks a force scheduler's force once the page has confirmed "
           "it."),
    base="http://127.0.0.1:8010/api/v2 (BUILDBOT_URL with /api/v2 after it; the tutorial's master serves its web UI at "
         "localhost:8010)",
    version="REST API version 2 (the data API's), read against Buildbot 4.3 and 4.4's documentation",
    auth=("the master's web sign-in, whatever it is: none unless its master.cfg sets one (NoAuth is the default); with "
          "UserPasswordAuth or HTPasswdAuth, a GET of /auth/login with HTTP basic credentials sets a session cookie, "
          "which every later request sends (the REST API documentation's way); a master signing in through OAuth2 "
          "(GitHub, GitLab, Google, Bitbucket, Keycloak) is not reached this way. What a user may read and control is "
          "the master's authz rules (allowRules: AnyEndpointMatcher, ForceBuildEndpointMatcher, ...); by default "
          "everyone may do everything. The plugin sends the password to /auth/login alone, never over plain http to "
          "another machine, and keeps the cookie only for the read or the force it signed in for"),
    limits="none: the master is the user's own",
    costs="none: Buildbot is free software (GPL-2.0)",
    links=(
        Link("REST API", _REST, "docs"),
        Link("REST API specification (its resource types)", _raml("index"), "reference"),
        Link("Build result codes", _DOCS + "developer/results.html", "reference"),
        Link("The web server's design (its URLs, /config, the message API)", _WWW, "reference"),
        Link("Web server configuration (c['www'])", _SERVER, "guide"),
        Link("ForceScheduler", _DOCS + "manual/configuration/schedulers.html#forcescheduler-scheduler", "guide"),
        Link("First run (the tutorial)", _DOCS + "tutorial/firstrun.html", "guide"),
        Link("Installation", _INSTALL + "index.html", "guide"),
        Link("Installing the code", _INSTALL + "installation.html", "guide"),
        Link("Buildmaster setup", _INSTALL + "buildmaster.html", "guide"),
        Link("Worker setup", _INSTALL + "worker.html", "guide"),
        Link("Launching the daemons", _INSTALL + "misc.html#launching-the-daemons", "guide"),
        Link("Authentication and authorization", _AUTH, "auth"),
        Link("UserPasswordAuth", _DOCS + "manual/configuration/www/auth/user_password_auth.html", "auth"),
        Link("HTPasswdAuth", _DOCS + "manual/configuration/www/auth/htpasswd_auth.html", "auth"),
        Link("Release notes", _DOCS + "relnotes/index.html", "changelog"),
        Link("Command-line tool (buildbot, buildbot-worker)", _DOCS + "manual/cmdline.html", "tool"),
        Link("buildbot/buildbot", "https://github.com/buildbot/buildbot", "source"),
    ),
    areas=(
        Area("Builders", "builder: each builder's id, name, description, tags, project and the masters it runs on",
             _raml("builder"), covered=("the Builders table: each one's name, description and tags, its last build "
                                        "among those read, its workers, and a Force… where a force scheduler starts "
                                        "it")),
        Area("Builds", "build: each build's builder, number, worker, start and end, state and result (SUCCESS 0, "
                       "WARNINGS 1, FAILURE 2, SKIPPED 3, EXCEPTION 4, RETRY 5, CANCELLED 6); stopped or rebuilt by "
                       "JSON-RPC", _raml("build"), covered="the Recent builds table: the 20 newest, by build id"),
        Area("Workers", "worker: each worker's name, the masters it is connected to, the builders it is configured on, "
                        "paused or graceful, its workerinfo; stopped, killed, paused or unpaused by JSON-RPC",
             _raml("worker"),
             covered="the Workers table: connected or not, paused, its host and version, its builders"),
        Area("Force schedulers", "forcescheduler: the schedulers that force a build (name, label, button_name, "
                                 "builder_names, all_fields); force by JSON-RPC", _raml("forcescheduler"),
             covered="the Force schedulers table, and Force… once confirmed"),
        Area("Frontend configuration", "/config: the web server's configuration for its own UI "
                                       "(implementation-defined: the versions its About page shows, Buildbot's, "
                                       "Twisted's and Python's among them, its title, buildbotURL)", _WWW,
             covered="the master's Buildbot version and its title"),
        Area("Sign-in", "/auth/login with HTTP basic credentials (UserPasswordAuth, HTPasswdAuth) sets the session "
                        "cookie the REST API is asked with", _REST,
             covered="when BUILDBOT_USER and BUILDBOT_PASSWORD are set: one sign-in before each read and each force"),
        Area("Build requests", "buildrequest: what waits for a worker, claimed or not; cancelled or given a priority "
                               "by JSON-RPC", _raml("buildrequest")),
        Area("Buildsets", "buildset: the build requests made together (by a force, a change, a schedule)",
             _raml("buildset")),
        Area("Build data", "build_data: data a build's steps attach to it", _raml("build_data")),
        Area("Steps", "step: a build's steps, their state, results and links", _raml("step")),
        Area("Logs", "log and logchunk: a step's logs and their lines", _raml("log")),
        Area("Test results", "test_result_set and test_result: a step's test results", _raml("test_result_set")),
        Area("Changes", "change: the commits the change sources and hooks saw", _raml("change")),
        Area("Change sources", "changesource: what watches the repositories", _raml("changesource")),
        Area("Codebases", "codebase, codebase_branch and codebase_commit: a project's repositories, branches and "
                          "commits", _raml("codebase")),
        Area("Source stamps", "sourcestamp: the revision, branch and repository a build is of", _raml("sourcestamp")),
        Area("Properties", "sourcedproperties: a build's or a build request's properties, and where each came from",
             _raml("sourcedproperties")),
        Area("Schedulers", "scheduler: every scheduler and the master it runs on", _raml("scheduler")),
        Area("Masters", "master: the masters (several in a multi-master setup), active or not, when last seen",
             _raml("master")),
        Area("Projects", "project: the projects builders belong to", _raml("project")),
        Area("Patches", "patch: a patch a source stamp carries (a try build's)", _raml("patch")),
        Area("The API's own description", "rootlink and spec: the API's root links and its endpoints' specification",
             _raml("spec")),
        Area("Raw endpoints", "a log's whole text and other answers that are not JSON collections",
             _raml("raw-endpoints")),
        Area("Messages", "the master's events as they happen (a build started, a step done) over WebSocket (/ws) or "
                         "Server-Sent Events (/sse)", _WWW),
        Area("Change hooks", "/change_hook/<dialect>: changes posted by GitHub, GitLab, Bitbucket and others",
             _DOCS + "manual/configuration/wwwhooks.html"),
    ),
    calls=(
        Call("GET /auth/login", "a sign-in with HTTP basic credentials: the session cookie it sets is sent with the "
             "requests after it", "Sign-in",
             used="before a read and a force when BUILDBOT_USER and BUILDBOT_PASSWORD are set", docs=_REST),
        Call("GET /config", "the configuration the web server gives its UI: the versions of Buildbot, Twisted and "
             "Python (before the www versions option's own), the title, buildbotURL", "Frontend configuration",
             used="the master's Buildbot version and its title", docs=_WWW),
        Call("GET /api/v2/builders", "every builder", "Builders", used="the Builders table", docs=_raml("builder")),
        Call("GET /api/v2/builds?order=-buildid&limit=20", "the newest builds, newest first", "Builds",
             used="the Recent builds table", docs=_raml("build")),
        Call("GET /api/v2/workers", "every worker", "Workers", used="the Workers table", docs=_raml("worker")),
        Call("GET /api/v2/forceschedulers", "every force scheduler", "Force schedulers",
             used="the Force schedulers table and its Force… forms", docs=_raml("forcescheduler")),
        Call("GET /api/v2/forceschedulers/{schedulername}", "one force scheduler", "Force schedulers",
             used="Force…: the scheduler read again before it is asked", docs=_raml("forcescheduler")),
        Call("GET /api/v2/builders/{builderid_or_buildername}", "one builder, by its id or its name", "Builders",
             used="Force… of one builder: its builder id, as the web UI's force sends it", docs=_raml("builder")),
        Call("POST /api/v2/forceschedulers/{schedulername} (force)", "a build forced: JSON-RPC method force, with the "
             "scheduler's fields (reason, branch, revision ...) and the builder", "Force schedulers",
             used=("Force… once confirmed: a build request for the builder chosen, or for every one the scheduler "
                   "starts"), docs=_raml("forcescheduler"), writes=True),
        Call("GET /api/v2/builders/{builderid_or_buildername}/builds", "one builder's builds", "Builds",
             docs=_raml("build")),
        Call("GET /api/v2/builds/{buildid}", "one build", "Builds", docs=_raml("build")),
        Call("POST /api/v2/builds/{buildid} (stop)", "a build stopped, with its reason", "Builds", docs=_raml("build"),
             writes=True),
        Call("POST /api/v2/builds/{buildid} (rebuild)", "a build run again", "Builds", docs=_raml("build"),
             writes=True),
        Call("GET /api/v2/builds/{buildid}/steps", "a build's steps", "Steps", docs=_raml("step")),
        Call("GET /api/v2/steps/{stepid}/logs", "a step's logs", "Logs", docs=_raml("log")),
        Call("GET /api/v2/logs/{logid}", "one log", "Logs", docs=_raml("log")),
        Call("GET /api/v2/buildrequests", "the build requests, waiting and claimed", "Build requests",
             docs=_raml("buildrequest")),
        Call("POST /api/v2/buildrequests/{buildrequestid} (cancel)", "a build request cancelled, with its reason",
             "Build requests", docs=_raml("buildrequest"), writes=True),
        Call("POST /api/v2/buildrequests/{buildrequestid} (set_priority)", "a build request given a priority",
             "Build requests", docs=_raml("buildrequest"), writes=True),
        Call("GET /api/v2/workers/{name_or_id}", "one worker", "Workers", docs=_raml("worker")),
        Call("POST /api/v2/builders/{builderid_or_buildername}/workers/{workerid} (pause)", "a worker paused, with its "
             "reason (unpause, stop and kill alike)", "Workers", docs=_raml("worker"), writes=True),
        Call("GET /api/v2/builders/{builderid_or_buildername}/forceschedulers", "the force schedulers of one builder",
             "Force schedulers", docs=_raml("forcescheduler")),
        Call("GET /api/v2/schedulers", "every scheduler and the master it runs on", "Schedulers",
             docs=_raml("scheduler")),
        Call("GET /api/v2/masters", "the masters, active or not", "Masters", docs=_raml("master")),
    ),
    verified=VERIFIED)

APIS = (BUILDBOT_REST,)
