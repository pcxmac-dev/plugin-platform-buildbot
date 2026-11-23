"""A Buildbot master's web server, asked over its REST API (the data API, version 2) and the configuration it gives its
own web UI.

Buildbot's REST API documentation (https://docs.buildbot.net/latest/developer/rest.html) says the whole of it:

- getting: a GET of a path under /api/v2; the answer's list is named by its type's plural, even when one object is
  asked ({"builders": [...], "meta": {"total": 12}}), filtered, ordered and paged by the query (order=-buildid,
  limit=20);
- controlling: a POST of a JSON-RPC 2.0 call to the object's path, its content type application/json
  ({"jsonrpc": "2.0", "method": "force", "params": {...}, "id": 1}), answered with its "result" or an "error"
  ({"code", "message"});
- authentication: as the web UI's own: a GET of /auth/login with HTTP basic credentials sets a session cookie, which
  every later request sends.

The web server's /config (https://docs.buildbot.net/latest/developer/www-server.html) is the configuration it gives its
own web UI (implementation-defined, the documentation says): among it the versions its About page shows, to which
Buildbot adds Python's, Twisted's and its own.

How it is asked:

- Only at the address set (BUILDBOT_URL): every request is that address and one of the plugin's fixed paths. No
  redirect is followed (an answer sending the request on elsewhere is said in words, its address never asked), no
  proxy is taken from the environment or the system's settings, and no cookie is kept but the session's, for as long
  as the client lives (one read, or one force).
- A request waits `timeout` seconds at most, and an answer is read to MOST bytes at most.
- The password goes to /auth/login alone, as the basic credentials, and never over plain http to another machine
  (settings.py refuses that before anything is sent); it, the credentials' token and the session's cookie are taken
  out of every word the client says (`scrub`), before any is cut.
- A failure is a BuildbotError in words: its `status` the answer's HTTP status, 0 when no answer came (nothing listens
  there, nothing in time, a connection that broke off).

`transport(method, url, headers, body, timeout) -> (status, headers, body)` is a test's stand-in (its headers a mapping
or (name, value) pairs); else `urllib_transport`, the standard library's urllib through an opener that follows no
redirect and takes no proxy."""
from __future__ import annotations

import base64
import ipaddress
import json as jsonlib
import re
import socket
import ssl
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from http.client import HTTPException
from http.cookies import CookieError, SimpleCookie
from urllib.parse import quote, quote_plus, urlencode, urlsplit

DEFAULT_URL = "http://127.0.0.1:8010"  # the tutorial's master on this machine (its web UI at localhost:8010)
API = "/api/v2"
LOOK_S = 5.0  # seconds a read waits for each answer: the page's look at a master is short
FORCE_S = 15.0  # seconds a force waits for its answer (sent once: a force that got no answer may have been done)
MOST = 4 << 20  # bytes read of one answer at most
SAID = 300  # characters kept of a master's own words in an error's
AGENT = "Liminal platform plugin (Buildbot)"  # a fixed name: nothing of the user's or of the machine's


class BuildbotError(Exception):
    """A request that failed, in words (its secrets taken out). `status`: the answer's HTTP status; 0 when no answer
    came."""

    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status

    @property
    def answered(self) -> bool:
        """An answer came, whatever its status: a web server is at the address."""
        return self.status > 0

    @property
    def refused(self) -> bool:
        """The master refused who asked (401, 403): a sign-in it wants, or a right the user has not."""
        return self.status in (401, 403)


# -- the address -----------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Address:
    """A master's web address as set: its base (the scheme, the host, its port, the path its web server is served
    under, without a last slash), its host, whether it is https, and whether it is this machine."""

    base: str
    host: str
    tls: bool
    local: bool


def is_local(host: str) -> bool:
    """Whether a host is this machine: localhost (a name under .localhost too), or a loopback address."""
    name = str(host or "").strip("[]").rstrip(".").lower()
    if name == "localhost" or name.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(name).is_loopback
    except ValueError:
        return False


def address(text) -> Address:
    """BUILDBOT_URL read (DEFAULT_URL when it is empty; http when it names no scheme). ValueError in words for anything
    but an http or https address of a host, with its port and the path its web server is served under if any: another
    scheme, a user name or a password in it (said before anything of it is shown back), a query, a port or a host that
    is none, a space or a line break, a . or .. in its path. A fragment (#/builders, the web UI's own) is let go: a
    browser never sends it either."""
    typed = str(text if text is not None else "").strip() or DEFAULT_URL
    if "@" in typed.split("://", 1)[-1].split("/", 1)[0]:
        raise ValueError("BUILDBOT_URL carries no user name and no password: set BUILDBOT_USER and BUILDBOT_PASSWORD "
                         "instead (the password goes to the master's sign-in alone)")
    if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in typed):
        raise ValueError("BUILDBOT_URL holds a space or a line break: give the master's address alone "
                         f"(as {DEFAULT_URL})")
    if "://" not in typed:
        typed = "http://" + typed
    shown = repr(typed[:80])
    try:
        parts = urlsplit(typed)
        port = parts.port
    except ValueError:
        raise ValueError(f"BUILDBOT_URL is no address: {shown} (as {DEFAULT_URL})") from None
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        raise ValueError(f"BUILDBOT_URL is an http or https address (as {DEFAULT_URL}), not {shown}")
    if parts.query:
        raise ValueError("BUILDBOT_URL carries no query (?): the master's address, and the path its web server is "
                         "served under if any")
    host = (parts.hostname or "").rstrip(".").lower()
    if not host:
        raise ValueError(f"BUILDBOT_URL names no host: {shown} (as {DEFAULT_URL})")
    path = parts.path.rstrip("/")
    if any(step in (".", "..") for step in path.split("/")):
        raise ValueError("BUILDBOT_URL's path holds no . and no ..: the path the master's web server is served under, "
                         "as it is")
    where = f"[{host}]" if ":" in host else host
    if port is not None:
        where += f":{port}"
    return Address(f"{scheme}://{where}{path}", host, scheme == "https", is_local(host))


# -- words -------------------------------------------------------------------------------------------------------------
def scrub(text: str, secrets: Iterable[str]) -> str:
    """`text` with each secret of four characters or more taken out (as given, without its surrounding spaces, and as
    an address would quote it), the longest first."""
    parts: set[str] = set()
    for s in secrets:
        s = str(s or "").strip()
        if len(s) >= 4:
            parts |= {s, quote(s, safe=""), quote_plus(s, safe="")}
    out = str(text)
    for s in sorted(parts, key=len, reverse=True):
        out = out.replace(s, "•••")
    return out


def trouble(e: BaseException, wait: float) -> str:
    """A connection's trouble in words: nothing listening, nothing in time, a name not known, a certificate not
    trusted, a connection broken off."""
    if isinstance(e, urllib.error.URLError) and not isinstance(e, urllib.error.HTTPError) \
            and isinstance(e.reason, BaseException):
        return trouble(e.reason, wait)
    if isinstance(e, ConnectionRefusedError):
        return "nothing answers there (the connection was refused)"
    if isinstance(e, TimeoutError):
        return f"no answer in {wait:g} s"
    if isinstance(e, socket.gaierror):
        return f"its host's name is not known here ({e.strerror or e})"
    if isinstance(e, ssl.SSLCertVerificationError):
        return f"its certificate is not trusted here ({e.verify_message or e})"
    if isinstance(e, ssl.SSLError):
        return f"its https failed ({e.reason or e})"
    if isinstance(e, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, HTTPException)):
        return f"the connection broke off ({type(e).__name__})"
    return f"{type(e).__name__}: {e}"


# -- sending -----------------------------------------------------------------------------------------------------------
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """No redirect is followed: the answer that would send a request on comes back as it is."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ARG002 - urllib's own signature
        return None


def urllib_transport(method: str, url: str, headers: Mapping[str, str], body: bytes | None, timeout: float):
    """One request through the standard library's urllib: no proxy (none taken from the environment or the system's
    settings), no redirect followed, no cookie kept. The answer's status, its headers as (name, value) pairs (each
    Set-Cookie its own), and its body, MOST + 1 bytes at most (one more says it was longer)."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    request = urllib.request.Request(url, data=body, headers=dict(headers), method=method)
    try:
        answer = opener.open(request, timeout=timeout)
    except urllib.error.HTTPError as e:  # a 3xx, a 4xx or a 5xx: an answer all the same
        answer = e
    with answer:
        return int(answer.getcode() or 0), list((answer.headers or {}).items()), answer.read(MOST + 1)


def _pairs(headers) -> list[tuple[str, str]]:
    if isinstance(headers, Mapping):
        return [(str(k), str(v)) for k, v in headers.items()]
    return [(str(k), str(v)) for k, v in headers or ()]


@dataclass
class Answer:
    """An answer: its status, its headers as (name, value) pairs, its body."""

    status: int
    headers: list[tuple[str, str]] = field(default_factory=list)
    body: bytes = b""

    def header(self, name: str) -> str:
        n = name.lower()
        return next((v for k, v in self.headers if k.lower() == n), "")

    def every(self, name: str) -> list[str]:
        n = name.lower()
        return [v for k, v in self.headers if k.lower() == n]

    def json(self):
        """Its body's JSON; None when it has none, or none that can be read (a nesting too deep among them)."""
        if not self.body:
            return None
        try:
            return jsonlib.loads(self.body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, RecursionError):
            return None


def cookie_of(values: Iterable[str]) -> str:
    """The Cookie header a sign-in's Set-Cookie headers make: each cookie's name=value as it was set, one being removed
    (set empty) left out."""
    jar: dict[str, str] = {}
    for value in values:
        c = SimpleCookie()
        try:
            c.load(value)
        except CookieError:
            continue
        for name, morsel in c.items():
            if morsel.value:
                jar[name] = morsel.coded_value
            else:
                jar.pop(name, None)
    return "; ".join(f"{k}={v}" for k, v in jar.items())


class Master:
    """One master's web server at `where` (an Address), asked by this plugin: reads (`get`, `listing`), the sign-in
    (`sign_in`) and a control (`control`). `user` and `password`: the master's web sign-in, when it asks one (the
    password is held for the sign-in alone and never said); `transport`: a test's stand-in; `timeout`: each request's
    wait unless it says its own; `note(status, seconds, error)`: told what each request came to (the plugin's facts).
    Making one sends nothing."""

    def __init__(self, where: Address, *, user: str = "", password: str = "", transport: Callable | None = None,
                 timeout: float = LOOK_S, note: Callable | None = None, clock: Callable[[], float] = time.monotonic):
        self.where = where
        self.user = user if user and password else ""
        self._password = password if user and password else ""
        self._token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii") if self.user else ""
        self._transport = transport or urllib_transport
        self.timeout = float(timeout)
        self._note = note
        self._clock = clock
        self._cookie = ""
        self.answered = False  # an answer came at all (whatever its status): a web server is at the address
        self.signed_in = ""  # the user it signed in as ("" when it did not)

    def _secrets(self) -> tuple[str, ...]:
        cookie = self._cookie
        values = [p.split("=", 1)[-1] for p in cookie.split("; ")] if cookie else []
        return tuple(x for x in (self._password, self._token, cookie, *values) if x)

    def words(self, text: str) -> str:
        """`text` with the password, the credentials' token and the session's cookie taken out."""
        return scrub(text, self._secrets())

    def _noted(self, status: int, started: float, error: str) -> None:
        if self._note is not None:
            self._note(status, max(0.0, self._clock() - started), error)

    def _send(self, method: str, path: str, *, params: Mapping | None = None, body: bytes | None = None,
              headers: Mapping[str, str] | None = None, timeout: float | None = None, moved: bool = False) -> Answer:
        """One request to the master's address and `path` (one of the plugin's own, `params` its query), and its answer
        whatever its status but a redirect's: that one is refused in words unless `moved` (the sign-in's, whose cookie
        is taken and whose address is never asked). BuildbotError with status 0 when no answer came."""
        url = self.where.base + path
        query = {k: v for k, v in (params or {}).items() if v is not None}
        if query:
            url += "?" + urlencode(query, doseq=True)
        sent = {"User-Agent": AGENT, "Accept": "application/json", **(headers or {})}
        if self._cookie:
            sent["Cookie"] = self._cookie
        wait = self.timeout if timeout is None else float(timeout)
        lead = f"{method} {path}"
        started = self._clock()
        try:
            status, got, raw = self._transport(method, url, sent, body, wait)
        except (OSError, HTTPException, ValueError) as e:  # the connection's trouble (a test's guard is no Exception)
            words = self.words(trouble(e, wait))
            self._noted(0, started, words)
            raise BuildbotError(f"{lead}: {words}") from None
        answer = Answer(int(status), _pairs(got), bytes(raw or b""))
        self.answered = True
        if len(answer.body) > MOST:
            words = f"its answer is longer than {MOST >> 20} MB: not read"
            self._noted(answer.status, started, words)
            raise BuildbotError(f"{lead}: {words}", answer.status)
        if 300 <= answer.status < 400 and not moved:
            to = self.words(answer.header("location"))[:200] or "another address"
            words = (f"the master sent it on to {to} (HTTP {answer.status}), which is not followed: only "
                     f"{self.where.base} is asked")
            self._noted(answer.status, started, words)
            raise BuildbotError(f"{lead}: {words}", answer.status)
        self._noted(answer.status, started, "" if answer.status < 400 else f"{lead}: HTTP {answer.status}")
        return answer

    def _said(self, answer: Answer) -> str:
        """What the master said of a failure: a JSON error's message, else its body's text (a page's words alone),
        its secrets taken out before it is cut."""
        data = answer.json()
        if isinstance(data, Mapping):
            error = data.get("error")
            if isinstance(error, Mapping):
                error = error.get("message")
            for value in (error, data.get("message")):
                if isinstance(value, str) and value.strip():
                    return self.words(" ".join(value.split()))[:SAID]
        text = answer.body[:4000].decode("utf-8", "replace")
        text = " ".join(re.sub(r"<[^>]*>", " ", text).split())
        return self.words(text)[:SAID] or "no words came back"

    # -- what the plugin asks ----------------------------------------------------------------------------------------
    def get(self, path: str, params: Mapping | None = None):
        """A GET's JSON: BuildbotError for any status but 200, and for an answer that is not JSON."""
        answer = self._send("GET", path, params=params)
        if answer.status != 200:
            raise BuildbotError(f"GET {path}: HTTP {answer.status}: {self._said(answer)}", answer.status)
        data = answer.json()
        if data is None:
            raise BuildbotError(f"GET {path}: its answer is not JSON (is a Buildbot master's web server at "
                                f"{self.where.base}?)", answer.status)
        return data

    def listing(self, path: str, kind: str, params: Mapping | None = None) -> tuple[list[dict], int | None]:
        """A collection's objects (its answer's list named `kind`, the type's plural, one object's too) and the total
        the master counts (its meta.total; None when it says none)."""
        data = self.get(path, params)
        rows = data.get(kind) if isinstance(data, Mapping) else None
        if not isinstance(rows, list) or not all(isinstance(r, Mapping) for r in rows):
            raise BuildbotError(f"GET {path}: its answer holds no list of {kind} (is a Buildbot master's web server at "
                                f"{self.where.base}?)", 200)
        meta = data.get("meta")
        total = meta.get("total") if isinstance(meta, Mapping) else None
        return [dict(r) for r in rows], total if isinstance(total, int) and not isinstance(total, bool) else None

    def sign_in(self) -> str:
        """Signed in at the master's /auth/login with the basic credentials, as its REST API documentation does it: the
        session cookie it sets goes with every later request of this client, and nowhere else. "" when it signed in
        (or there is nothing to sign in with); else why not, in words, and the reads go on as anyone's. BuildbotError
        when no answer came."""
        if not self._token:
            return ""
        answer = self._send("GET", "/auth/login", headers={"Authorization": f"Basic {self._token}"}, moved=True)
        if answer.status in (401, 403):
            return (f"the master refused the sign-in as {self.user} (HTTP {answer.status}): BUILDBOT_USER or "
                    "BUILDBOT_PASSWORD is not one it knows; read as anyone")
        if answer.status >= 400:
            return (f"the master's sign-in answered HTTP {answer.status} ({self._said(answer)}): it may ask none "
                    "(NoAuth, Buildbot's default); read as anyone")
        cookie = cookie_of(answer.every("set-cookie"))
        if not cookie:
            return "the master answered the sign-in but set no session cookie: read as anyone"
        self._cookie = cookie
        self.signed_in = self.user
        return ""

    def control(self, path: str, method: str, params: Mapping, timeout: float = FORCE_S):
        """A control in the REST API's JSON-RPC 2.0 form: `method` with `params` POSTed to `path`, its content type
        application/json, sent once. Its result; BuildbotError in the master's words for an error, for any status but
        200, and for an answer without a result."""
        body = jsonlib.dumps({"jsonrpc": "2.0", "method": method, "params": dict(params), "id": 1},
                             separators=(",", ":")).encode("utf-8")
        answer = self._send("POST", path, body=body, headers={"Content-Type": "application/json"}, timeout=timeout)
        data = answer.json()
        if answer.status != 200 or (isinstance(data, Mapping) and data.get("error") is not None):
            raise BuildbotError(f"POST {path} ({method}): HTTP {answer.status}: {self._said(answer)}", answer.status)
        if not isinstance(data, Mapping) or "result" not in data:
            raise BuildbotError(f"POST {path} ({method}): its answer holds no result", answer.status)
        return data["result"]
