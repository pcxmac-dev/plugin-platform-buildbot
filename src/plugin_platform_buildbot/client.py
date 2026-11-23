"""A Buildbot master's web server, asked over its REST API (the data API, version 2) and the configuration it gives its
own web UI.

Buildbot's REST API documentation (https://docs.buildbot.net/latest/developer/rest.html) says the whole of it:

- getting: a GET of a path under /api/v2; the answer's list is named by its type's plural, even when one object is
  asked ({"builders": [...], "meta": {"total": 12}}), filtered, ordered and paged by the query (name=runtests,
  order=-buildid, limit=20);
- controlling: a POST of a JSON-RPC 2.0 call to the object's path, its content type application/json
  ({"jsonrpc": "2.0", "method": "force", "params": {...}, "id": 1}), answered with its "result" or an "error"
  ({"code", "message"});
- authentication: as the web UI's own: a GET of /auth/login with HTTP basic credentials sets a session cookie, which
  every later request sends. A master answers a good one with a redirect to its web UI (buildbotURL + "#/") carrying
  two session cookies, the anonymous session's and then the signed-in one's: the last of each name is kept.

The web server's /config (https://docs.buildbot.net/latest/developer/www-server.html) is the configuration it gives its
own web UI (implementation-defined, the documentation says): among it the versions its About page shows, to which
Buildbot adds Python's, Twisted's and its own, and the sign-in it takes (`auth`: its class's name, with oauth2 true for
one through an OAuth2 provider). Only UserPasswordAuth, HTPasswdAuth and CustomAuth take a user and a password at
/auth/login (`no_basic` says why the others do not).

How it is asked:

- Only at the address set (BUILDBOT_URL): every request is that address and one of the plugin's fixed paths. No
  redirect is followed (an answer sending the request on elsewhere is said in words, its address never asked), no
  proxy is taken from the environment or the system's settings, and no cookie is kept but the session's, for as long
  as the client lives (one read, or one force).
- A request has `timeout` seconds in all, its connection, a TLS handshake, its answer's status line, headers and body
  together (`urllib_transport`: a timer shuts its socket down once they have passed, and the body is read a part at a
  time), and an answer is read to MOST bytes at most. The name's lookup comes before any socket and is the system's.
- The password goes to /auth/login alone, as the basic credentials, and never over plain http to another machine:
  only the name localhost itself and a loopback address are this machine (settings.py refuses the rest before
  anything is sent, and `Master.sign_in` again). It, the credentials' token and the session's cookie are taken out of
  every word the client says (`scrub`): out of the whole of what the master says, before anything is made of it.
- A failure is a BuildbotError in words: its `status` the answer's HTTP status, 0 when no answer came (nothing listens
  there, nothing in time, a connection that broke off).

`transport(method, url, headers, body, timeout) -> (status, headers, body)` is a test's stand-in (its headers a mapping
or (name, value) pairs); else `urllib_transport`, the standard library's urllib through an opener that follows no
redirect and takes no proxy."""
from __future__ import annotations

import base64
import html
import ipaddress
import json as jsonlib
import re
import socket
import ssl
import threading
import time
import urllib.error
import urllib.request
from array import array
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from http.client import HTTPConnection, HTTPException, HTTPSConnection
from http.cookies import CookieError, SimpleCookie
from itertools import accumulate
from urllib.parse import quote, quote_plus, urlencode, urlsplit

DEFAULT_URL = "http://127.0.0.1:8010"  # the tutorial's master on this machine (its web UI at localhost:8010)
API = "/api/v2"
LOOK_S = 5.0  # seconds a read's request has in all: the page's look at a master is short
FORCE_S = 15.0  # seconds a force has for its answer (sent once: a force that got no answer may have been done)
MOST = 4 << 20  # bytes read of one answer at most
CHUNK = 64 << 10  # bytes asked of an answer at a time: its deadline is looked at between them
DEPTH_MOST = 512  # levels of arrays and objects an answer's JSON may nest; past this it is no JSON (as jsonread's)
SAID = 300  # characters kept of a master's own words in an error's
SECRET_LEAST = 4  # characters a secret has at least to be taken out of words (a shorter password is not sent)
AGENT = "Liminal platform plugin (Buildbot)"  # a fixed name: nothing of the user's or of the machine's
BASIC = ("UserPasswordAuth", "HTPasswdAuth", "CustomAuth")  # the sign-ins that take basic credentials at /auth/login


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
    """Whether a host is this machine: the name localhost itself, or a loopback address (127.0.0.0/8, ::1). A name
    under .localhost is not: a resolver is only asked to keep those on this machine, and one that sends them to its DNS
    server (on another network, someone else's) can be answered with another machine."""
    name = str(host or "").strip("[]").rstrip(".").lower()
    if name == "localhost":
        return True
    try:
        return ipaddress.ip_address(name).is_loopback
    except ValueError:
        return False


def address(text) -> Address:
    """BUILDBOT_URL read (DEFAULT_URL when it is empty; http when it names no scheme). ValueError in words for anything
    but an http or https address of a host, with its port and the path its web server is served under if any: an @
    anywhere in it (a user name or a password typed into it; refused before anything else is read of it, as a
    master's path never needs one), a space or a line break, another scheme, a query, a port or a host that is none,
    a . or .. in its path. The words say what is wrong and never hold what was typed, which may hold a password. A
    fragment (#/builders, the web UI's own) is let go: a browser never sends it either."""
    typed = str(text if text is not None else "").strip() or DEFAULT_URL
    if "@" in typed:
        raise ValueError("BUILDBOT_URL carries no user name and no password (it holds an @): set BUILDBOT_USER and "
                         "BUILDBOT_PASSWORD instead (the password goes to the master's sign-in alone)")
    if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in typed):
        raise ValueError("BUILDBOT_URL holds a space or a line break: give the master's address alone "
                         f"(as {DEFAULT_URL})")
    if "://" not in typed:
        typed = "http://" + typed
    try:
        parts = urlsplit(typed)
        port = parts.port
    except ValueError:
        raise ValueError("BUILDBOT_URL is no address: its host or its port cannot be read (a port is a number up to "
                         f"65535; as {DEFAULT_URL})") from None
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        raise ValueError(f"BUILDBOT_URL is an http or https address (as {DEFAULT_URL}), not {scheme[:20] or 'none'}")
    if parts.query:
        raise ValueError("BUILDBOT_URL carries no query (?): the master's address, and the path its web server is "
                         "served under if any")
    host = (parts.hostname or "").rstrip(".").lower()
    if not host:
        raise ValueError(f"BUILDBOT_URL names no host (as {DEFAULT_URL})")
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
    """`text` with each secret of SECRET_LEAST characters or more taken out, the longest first: as given (without its
    surrounding spaces), as an address would quote it, with its runs of spaces made one (as words are said), and each
    of these as HTML escapes it (as a page says it back)."""
    parts: set[str] = set()
    for s in secrets:
        s = str(s or "").strip()
        if len(s) < SECRET_LEAST:
            continue
        for form in (s, quote(s, safe=""), quote_plus(s, safe=""), " ".join(s.split())):
            parts |= {form, html.escape(form), html.escape(form, quote=False)}
    out = str(text)
    for s in sorted((p for p in parts if len(p) >= SECRET_LEAST), key=len, reverse=True):
        out = out.replace(s, "•••")
    return out


def no_basic(auth) -> str:
    """Why the sign-in a master's /config names ({"name": ..., "oauth2": ...}) takes no user and password at
    /auth/login, in words; "" when it takes them, and when its /config names none (an older master's: it is asked)."""
    if not isinstance(auth, Mapping):
        return ""
    name = " ".join(str(auth.get("name") or "").split())[:40]
    if auth.get("oauth2") is True:
        return (f"the master signs in through OAuth2 ({name or 'a provider'}), which takes no user and password here: "
                "BUILDBOT_USER and BUILDBOT_PASSWORD are not sent; read as anyone")
    if name == "NoAuth":
        return ("the master asks no sign-in (NoAuth, Buildbot's default): BUILDBOT_USER and BUILDBOT_PASSWORD are not "
                "sent; read as anyone")
    if name == "RemoteUserAuth":
        return ("the master takes its user from the web server in front of it (RemoteUserAuth), never from a user and "
                "a password: BUILDBOT_USER and BUILDBOT_PASSWORD are not sent; read as anyone")
    return ""


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


def _shut(sock) -> None:
    """A socket shut down and closed, whatever it is doing (a read waiting in another thread ends at once)."""
    for step in (lambda: sock.shutdown(socket.SHUT_RDWR), sock.close):
        try:
            step()
        except OSError:
            pass


class Deadline:
    """One request's deadline: `seconds` from now on `clock`. The sockets it holds (each as soon as it is connected,
    and a TLS one before its handshake) are shut down by `expire`, which a timer calls once it has passed; `over`
    says it has passed, as the body's reads look between them."""

    def __init__(self, seconds: float, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self.end = clock() + max(0.0, float(seconds))
        self._lock = threading.Lock()
        self._held: list = []
        self.passed = False  # expired: what was being read was cut off

    def hold(self, sock):
        """`sock` held till the request ends; shut down at once when the deadline has passed already."""
        with self._lock:
            late = self.passed
            if not late:
                self._held.append(sock)
        if late:
            _shut(sock)
        return sock

    def expire(self) -> None:
        with self._lock:
            self.passed = True
            held, self._held = self._held, []
        for sock in held:
            _shut(sock)

    def over(self) -> bool:
        return self.passed or self._clock() >= self.end


class _Held:
    """An SSL context's stand-in for one request: the context's own, but each socket it wraps is held by the deadline
    before its handshake, so a handshake given a byte at a time ends with it too."""

    def __init__(self, context: ssl.SSLContext, deadline: Deadline):
        self._context = context
        self._deadline = deadline

    def wrap_socket(self, sock, *args, **kwargs):
        kwargs["do_handshake_on_connect"] = False
        tls = self._context.wrap_socket(sock, *args, **kwargs)
        self._deadline.hold(tls)
        tls.do_handshake()
        return tls

    def __getattr__(self, name):
        return getattr(self._context, name)


def _watched(base, deadline: Deadline):
    """http.client's HTTPConnection or HTTPSConnection (`base`), its socket held by the deadline once it is
    connected."""

    class Watched(base):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            connect = self._create_connection

            def held(*a, **k):
                return deadline.hold(connect(*a, **k))

            self._create_connection = held

    return Watched


class _Plain(urllib.request.HTTPHandler):
    def __init__(self, deadline: Deadline):
        super().__init__()
        self._deadline = deadline

    def http_open(self, req):
        return self.do_open(_watched(HTTPConnection, self._deadline), req)


class _Tls(urllib.request.HTTPSHandler):
    def __init__(self, deadline: Deadline):
        context = ssl.create_default_context()  # its certificate checked, as http.client's own context does
        context.set_alpn_protocols(["http/1.1"])
        super().__init__(context=context)
        self._deadline = deadline

    def https_open(self, req):
        return self.do_open(_watched(HTTPSConnection, self._deadline), req,
                            context=_Held(self._context, self._deadline))


def read_body(answer, deadline: Deadline) -> bytes:
    """An answer's body, MOST + 1 bytes at most (one more says it was longer), read a part at a time (its read1, the
    bytes that came, never waiting for a whole part): TimeoutError once the deadline has passed, and when the timer
    cut it off."""
    out = bytearray()
    read = getattr(answer, "read1", None) or answer.read
    while len(out) <= MOST:
        if deadline.over():
            raise TimeoutError("the answer did not come whole in time")
        part = read(min(CHUNK, MOST + 1 - len(out)))
        if not part:
            break
        out += part
    if deadline.passed:
        raise TimeoutError("the answer did not come whole in time")
    return bytes(out)


def urllib_transport(method: str, url: str, headers: Mapping[str, str], body: bytes | None, timeout: float):
    """One request through the standard library's urllib: no proxy (none taken from the environment or the system's
    settings), no redirect followed, no cookie kept, and `timeout` seconds for the whole of it (its connection, a TLS
    handshake, the status line, the headers and the body: a Deadline, its timer shutting the socket down once they
    have passed), so an answer given a byte at a time ends in time too. The answer's status, its headers as (name,
    value) pairs (each Set-Cookie its own), and its body, MOST + 1 bytes at most (one more says it was longer)."""
    deadline = Deadline(timeout)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect(), _Plain(deadline),
                                         _Tls(deadline))
    request = urllib.request.Request(url, data=body, headers=dict(headers), method=method)
    timer = threading.Timer(max(0.0, float(timeout)), deadline.expire)
    timer.daemon = True
    timer.start()
    try:
        try:
            answer = opener.open(request, timeout=timeout)
        except urllib.error.HTTPError as e:  # a 3xx, a 4xx or a 5xx: an answer all the same
            answer = e
        with answer:
            status = getattr(answer, "status", None) or answer.getcode()
            return int(status or 0), list((answer.headers or {}).items()), read_body(answer, deadline)
    except (OSError, HTTPException):
        if deadline.passed:  # what broke it off was the deadline's timer
            raise TimeoutError(f"no whole answer in {timeout:g} s") from None
        raise
    finally:
        timer.cancel()


def _pairs(headers) -> list[tuple[str, str]]:
    if isinstance(headers, Mapping):
        return [(str(k), str(v)) for k, v in headers.items()]
    return [(str(k), str(v)) for k, v in headers or ()]


_STRING = re.compile(rb'"[^"\\]*(?:\\.[^"\\]*)*"')  # a JSON string, its escapes in it: a bracket in it is text
_MARKS = bytes.maketrans(b"[{]}", b"\x01\x01\xff\xff")  # an opening one 1, a closing one -1 (read as signed bytes)
_OTHERS = bytes(c for c in range(256) if c not in b"[{]}")


def too_deep(raw: bytes, most: int = DEPTH_MOST) -> bool:
    """Whether a JSON text nests past `most` levels of arrays and objects (a bracket inside a string is text), counted
    with the bytes' own methods before anything is parsed, alike on every Python (liminal_libs.jsonread's count, from
    1.75.2): never counted when it holds no more openings than that."""
    if raw.count(b"[") + raw.count(b"{") <= most:
        return False
    if b'"' in raw:
        raw = _STRING.sub(b'""', raw)
    return max(accumulate(array("b", raw.translate(_MARKS, _OTHERS))), default=0) > most


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
        """Its body's JSON; None when it has none, or none that can be read: one nested past DEPTH_MOST levels among
        them, counted before it is parsed (Python's own reader goes far deeper on some systems than on others)."""
        if not self.body:
            return None
        try:
            if too_deep(self.body):
                return None
            return jsonlib.loads(self.body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, RecursionError):
            return None


def cookie_of(values: Iterable[str]) -> str:
    """The Cookie header a sign-in's Set-Cookie headers make: each cookie's name=value as it was set last (a master
    sets the anonymous session's, then the signed-in one's), one being removed (set empty) left out."""
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
    time unless it says its own; `note(status, seconds, error)`: told what each request came to (the plugin's facts).
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
        self.refused = False  # the master refused the sign-in's user and password (401, 403)

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
        """What the master said of a failure: a JSON error's message (a force's refusals by field: "reason: ..."),
        else its body's text (a page's words alone). Its secrets are taken out of the whole of it first, before
        anything is made of it (its tags taken out, its escapes read, its spaces made one), then again, and only then
        is it cut: a secret it says back, whole or escaped, wherever it is, is never said."""
        data = answer.json()
        if isinstance(data, Mapping):
            error = data.get("error")
            if isinstance(error, Mapping):
                error = error.get("message")
            if isinstance(error, Mapping):  # a force's refusals, by field
                error = "; ".join(f"{k}: {v}" for k, v in error.items() if isinstance(k, str) and isinstance(v, str))
            for value in (error, data.get("message")):
                if isinstance(value, str) and value.strip():
                    return self.words(" ".join(self.words(value).split()))[:SAID]
        text = self.words(answer.body.decode("utf-8", "replace"))  # the whole of it: MOST + 1 bytes at most
        text = " ".join(html.unescape(re.sub(r"<[^>]*>", " ", text)).split())
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

    def sign_in(self, auth: str = "") -> str:
        """Signed in at the master's /auth/login with the basic credentials, as its REST API documentation does it: the
        session cookie it sets (the last it sets) goes with every later request of this client, and nowhere else.
        `auth`: the sign-in its /config names, for the words of a refusal. "" when it signed in (or there is nothing to
        sign in with); else why not, in words, and the reads go on as anyone's: `refused` when the master refused the
        user and password (401, 403). Nothing is sent over plain http to another machine. BuildbotError when no answer
        came."""
        if not self._token:
            return ""
        if not self.where.tls and not self.where.local:
            return (f"the password would go to {self.where.host} over plain http, where anyone on the way can read "
                    "it: it is not sent; read as anyone")
        answer = self._send("GET", "/auth/login", headers={"Authorization": f"Basic {self._token}"}, moved=True)
        if answer.status in (401, 403):
            self.refused = True
            if not auth or auth in BASIC:
                return (f"the master refused the sign-in as {self.user} (HTTP {answer.status}): BUILDBOT_USER or "
                        "BUILDBOT_PASSWORD is not one it knows; read as anyone")
            return (f"the master refused the sign-in as {self.user} (HTTP {answer.status}): its sign-in ({auth}) may "
                    "take no user and password at /auth/login; read as anyone")
        if answer.status >= 400:
            return (f"the master's sign-in answered HTTP {answer.status} ({self._said(answer)}): it may ask none; "
                    "read as anyone")
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
