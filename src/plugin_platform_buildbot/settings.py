"""The plugin's settings, read through the library's Login interface and nothing else (as every platform plugin's: the
user, 2026-11-08: "again, all the settings are stored on a login-app db"). Each is a pair named by its variable
(BUILDBOT_URL is the pair `buildbot-url`: apps.authorization.pair_name), asked of the login of the app the plugin is
attached to (the platform lends its own), else of an EnvironmentLogin of its own. No settings file: the plugin writes a
value nowhere, and the password is never shown, said, logged or kept past the request it goes with.

- BUILDBOT_URL: the master's web address, as its web UI is opened (http://127.0.0.1:8010 unless set: the tutorial's
  master on this machine; the path its web server is served under, behind a proxy).
- BUILDBOT_USER and BUILDBOT_PASSWORD: a user of the master's web sign-in (UserPasswordAuth, HTPasswdAuth,
  CustomAuth), when it asks one; none when it asks none (NoAuth, Buildbot's default), and never sent to a master whose
  /config names a sign-in that takes none (RemoteUserAuth, OAuth2's). The password goes to the master's /auth/login
  alone, and never over plain http to another machine, where anyone on the way could read it: only the name localhost
  itself and a loopback address are this machine (a name under .localhost is not, as a resolver may ask its DNS server
  for it). A password shorter than SECRET_LEAST characters is not sent either: it could not be told apart in what the
  master says back, so it could not be kept out of the words said."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace

from liminal_libs.apps import EnvironmentLogin
from liminal_libs.sources.keys import KeyVar

from .client import DEFAULT_URL, SECRET_LEAST, Address, address

URL = "BUILDBOT_URL"
USER = "BUILDBOT_USER"
PASSWORD = "BUILDBOT_PASSWORD"

KEYS = (
    KeyVar(URL, label="Master's address", secret=False,
           hint=("optional: the master's web address, as its web UI is opened (its master.cfg's c['www'] port; the "
                 f"path it is served under, behind a proxy); {DEFAULT_URL} unless set")),
    KeyVar(USER, label="User", secret=False,
           hint=("optional: a user of the master's web sign-in (UserPasswordAuth, HTPasswdAuth, CustomAuth), when it "
                 "asks one; none when it asks none (NoAuth, Buildbot's default)")),
    KeyVar(PASSWORD, label="Password",
           hint=(f"optional: that user's password ({SECRET_LEAST} characters at least), sent to the master's sign-in "
                 "(/auth/login) alone, and never over plain http to another machine")),
)
NAMES = tuple(k.name for k in KEYS)


def _bad(text: str) -> bool:
    return any(ord(c) < 32 or ord(c) == 127 for c in text)


@dataclass(frozen=True)
class Settings:
    """The settings as read: the master's address (None when BUILDBOT_URL is none: `problems` says why), the user and
    the password (never shown: repr=False), whether they go to the master's sign-in (`sign_in`: both set, sound, the
    password SECRET_LEAST characters at least, and over https or to this machine), and what is wrong with them, in
    words that never hold the password."""

    where: Address | None
    user: str = ""
    password: str = field(default="", repr=False)
    sign_in: bool = False
    problems: tuple[str, ...] = ()


def parse(values: Mapping[str, str], default: str = "", admin: tuple[str, str] | None = None) -> Settings:
    """The settings from their values by variable (those not set left out or empty). 0.2.0: `default` is the master's
    address when BUILDBOT_URL is not set (its container's port), and `admin` the seeded sign-in's (user, password),
    taken when neither BUILDBOT_USER nor BUILDBOT_PASSWORD is set."""
    url, user, password = (str(values.get(n) or "").strip() for n in NAMES)
    url = url or default
    if admin and not user and not password:
        user, password = admin
    try:
        where = address(url)
    except ValueError as e:
        return Settings(where=None, problems=(str(e),))
    problems: list[str] = []
    if user and (_bad(user) or ":" in user):
        problems.append(f"{USER} holds a colon, a line break or a control character, which no sign-in takes: read "
                        "without signing in")
    if password and _bad(password):
        problems.append(f"{PASSWORD} holds a line break or a control character: enter it again, alone (it is not "
                        "sent); read without signing in")
    elif password and len(password) < SECRET_LEAST:
        problems.append(f"{PASSWORD} is shorter than {SECRET_LEAST} characters, too short to be kept out of what the "
                        "master says back: it is not sent; read without signing in")
    if user and not password:
        problems.append(f"{USER} is set but {PASSWORD} is not: read without signing in")
    elif password and not user:
        problems.append(f"{PASSWORD} is set but {USER} is not: read without signing in")
    sign_in = bool(user and password) and not problems
    if sign_in and not where.tls and not where.local:
        problems.append(f"the password would go to {where.host} over plain http, where anyone on the way can read "
                        f"it: it is not sent (an https address in {URL} sends it); read without signing in")
        sign_in = False
    return Settings(where, user, password, sign_in, tuple(problems))


def read(login=None, default: str = "", admin: tuple[str, str] | None = None) -> Settings:
    """The settings as `login` furnishes them (the login of the app the plugin is attached to), else an
    EnvironmentLogin's; a login that cannot be asked furnishes none, and says so (the defaults are used)."""
    asked = login if login is not None else EnvironmentLogin()
    try:
        values = asked.variables(NAMES) or {}
    except Exception as e:  # noqa: BLE001 - a login that cannot be asked: the defaults, and why
        s = parse({}, default)
        return replace(s, problems=(f"the settings could not be read from the login ({type(e).__name__}): the defaults "
                                    "are used", *s.problems))
    return parse(values, default, admin)
