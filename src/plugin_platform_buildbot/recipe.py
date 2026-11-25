"""Buildbot's recipe for a container (0.2.0; service-containers-design §5.4, with the user's answers of 2026-11-25:
"Containers only", a worker container beside each master, "Seeded, PC-only first", reporting to its makers off,
images pinned by digest).

Two parts on the service's one network: `master` (its web UI and REST API on 8010; its base folder in a volume: its
master.cfg, its database and its build logs; 9989, the workers' port, only on the service's own network) and `worker`
(a Buildbot worker that signs in to the master over that network as liminal-worker). Seeded before the first start,
into the new volume alone:
- a master.cfg with Buildbot's usage data off (`c['buildbotNetUsageData'] = None`), the worker, a `hello` builder and
  its force scheduler, and its web sign-in: a CustomAuth checking `admin`'s password against a salted PBKDF2-SHA256
  hash (the standard library's, in Python inside the master), every control endpoint the admin's alone;
- that hash, in liminal.auth: never the password (BUILDBOT_ADMIN_PASSWORD, through the login).
The worker's password is a secret both parts get by environment alone (WORKERPASS), made by the plugin when none is
kept and kept through the login (BUILDBOT_WORKER_PASSWORD). The master is installed on this PC alone (127.0.0.1:8010);
Expose… opens it once its /config names the seeded sign-in.

The pins: each image by its tag and its digest; a digest still UNREAD is refused before any plan."""
from __future__ import annotations

from collections.abc import Mapping

from liminal_libs.instances import Refusal
from liminal_libs.machines.containedservice import UNREAD, pbkdf2_hash
from liminal_libs.machines.containers import ServiceSpec

OWNER = "buildbot"
ADMIN = "admin"
ADMIN_PASSWORD = "BUILDBOT_ADMIN_PASSWORD"  # the password you set, through the login: only its hash is seeded
WORKER_PASSWORD = "BUILDBOT_WORKER_PASSWORD"  # made by the plugin, kept through the login, by environment alone
WORKER = "liminal-worker"
PASSWORD_LEAST = 12
WEB_PORT = 8010
WORKER_PORT = 9989
MEMORY_MB = 1024
WORKER_MEMORY_MB = 1024
BASE = "/var/lib/buildbot"
AUTH_FILE = "liminal.auth"
HUB = "https://hub.docker.com/r/"
PINS = {
    "linux": {
        "master": dict(ref="docker.io/buildbot/buildbot-master:v4.3.0", digest="sha256:10785a6789911f98debcd4df949a169846001c264a9c36047da35b9d8c071d19", size=239258072, system="linux",
                       platforms=["linux/amd64"], version="4.3.0", licence="GPL-2.0", page=HUB + "buildbot/buildbot-master",
                       tar=True),
        "worker": dict(ref="docker.io/buildbot/buildbot-worker:v4.3.0", digest="sha256:b4ca5b1c603e816494c7ec44f7a01082bf5144aac255ed30624491fb20b38f02", size=296844832, system="linux",
                       platforms=["linux/amd64"], version="4.3.0", licence="GPL-2.0", page=HUB + "buildbot/buildbot-worker",
                       tar=True),
    },
}

MASTER_CFG = '''# Seeded by Liminal (plugin-platform-buildbot 0.2.0) into a new volume, once: yours from then on.
import base64
import hashlib
import hmac
import os

from buildbot.plugins import schedulers, steps, util, worker

AUTH_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "{auth_file}")


class LiminalAuth(util.CustomAuth):
    """{admin}'s password checked against its salted PBKDF2-SHA256 hash: the password is kept nowhere here."""

    def check_credentials(self, user, password):
        user = user.decode("utf-8") if isinstance(user, bytes) else str(user)
        password = password.decode("utf-8") if isinstance(password, bytes) else str(password)
        try:
            with open(AUTH_FILE, encoding="utf-8") as f:
                name, hashed = f.read().strip().split(":", 1)
            kind, rounds, salt, _ = hashed.split("$", 3)
        except (OSError, ValueError):
            return False
        if kind != "pbkdf2_sha256":
            return False
        raw = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("ascii"), int(rounds))
        made = "pbkdf2_sha256$%d$%s$%s" % (int(rounds), salt, base64.b64encode(raw).decode("ascii"))
        return hmac.compare_digest(user, name) and hmac.compare_digest(made, hashed)


c = BuildmasterConfig = {{}}
c["buildbotNetUsageData"] = None  # its usage data never sent to its makers
c["title"] = "Buildbot (Liminal)"
c["titleURL"] = "https://buildbot.net/"
c["buildbotURL"] = "http://127.0.0.1:{web}/"
c["workers"] = [worker.Worker("{worker}", os.environ["WORKERPASS"])]
c["protocols"] = {{"pb": {{"port": {pb}}}}}
c["change_source"] = []
hello = util.BuildFactory([steps.ShellCommand(command=["echo", "hello from the Liminal worker"])])
c["builders"] = [util.BuilderConfig(name="hello", workernames=["{worker}"], factory=hello)]
c["schedulers"] = [schedulers.ForceScheduler(name="force", builderNames=["hello"])]
c["www"] = {{
    "port": {web},
    "auth": LiminalAuth(),
    "authz": util.Authz(allowRules=[util.AnyControlEndpointMatcher(role="admins")],
                        roleMatchers=[util.RolesFromUsername(roles=["admins"], usernames=["{admin}"])]),
}}
c["db"] = {{"db_url": "sqlite:///state.sqlite"}}
'''


def master_cfg() -> str:
    return MASTER_CFG.format(auth_file=AUTH_FILE, admin=ADMIN, worker=WORKER, web=WEB_PORT, pb=WORKER_PORT)


def spec(system: str, name: str, options: Mapping, password: str, pins: Mapping | None = None) -> ServiceSpec:
    """Buildbot's spec for a system (Linux alone: its makers publish no Windows image, decision 14). `password`: the
    admin's, hashed into the seed ("" only for reading a fit, with no seed)."""
    pins = pins if pins is not None else PINS
    if system not in pins:
        raise Refusal(f"Buildbot has no {system} image (its makers publish none: not yet, decision 14)")
    fit = bool(options.get("fit"))
    if not fit and len(password) < PASSWORD_LEAST:
        raise Refusal(f"set {ADMIN_PASSWORD} ({PASSWORD_LEAST} characters at least) in its settings first: Buildbot's "
                      "sign-in is seeded with its hash before its first start, so it never runs open")
    ports = list(options.get("ports") or [])
    host = int(ports[0]) if ports else WEB_PORT
    memory = int(options.get("memory_mb") or 0) or MEMORY_MB
    seeds = [] if fit else [
        {"volume": "base", "path": "master.cfg", "text": master_cfg(), "mode": 0o640},
        {"volume": "base", "path": AUTH_FILE, "text": f"{ADMIN}:{pbkdf2_hash(password)}\n", "mode": 0o600}]
    secret = {"variable": WORKER_PASSWORD, "env": "WORKERPASS", "about": "the worker's password on its own network"}
    master = {
        "name": "master", "image": dict(pins[system]["master"]),
        "ports": [{"name": "web", "container": WEB_PORT, "host": host, "lan": bool(options.get("lan")),
                   "about": "Buildbot's web UI and its REST API"}],
        "volumes": [{"name": "base", "path": BASE, "holds": "its master.cfg, its database and its build logs"}],
        "secrets": [secret], "seeds": seeds,
        "memory": memory << 20, "health": {"port": "web", "path": "/config", "ready_s": 300}, "stop_s": 30}
    worker = {
        "name": "worker", "image": dict(pins[system]["worker"]),
        "env": {"BUILDMASTER": f"liminal-{OWNER}-{name}-master", "BUILDMASTER_PORT": str(WORKER_PORT),
                "WORKERNAME": WORKER},
        "secrets": [secret], "memory": WORKER_MEMORY_MB << 20, "stop_s": 30}
    return ServiceSpec.of({"owner": OWNER, "name": name, "title": "Buildbot", "system": system,
                           "parts": [master, worker]})
