"""Accounts, passwords and sign-in sessions, and the routes that sign in and out.

A route that needs someone signed in uses `require`:

    @route("GET", "/api/records")
    @auth.require("learner")
    def records(req):
        ... req.account is the signed-in account (a sqlite3.Row: id, role, name)

Signed out gets 401 {"error": "signed-out"}; the wrong role gets 403 {"error": "wrong-role"}.
"""
import contextlib
import functools
import hashlib
import hmac
import secrets
import sqlite3
import threading

from . import db, limits
from .app import HTTPError, Response, json_response, route

ROLES = ("helper", "learner")
NAME_MAX = 64
PASSWORD_MIN = 8
PASSWORD_MAX = 128

# scrypt settings for new hashes. Each hash stores its own, so raising these re-hashes
# a password at its next sign-in.
SCRYPT_N = 2 ** 15
SCRYPT_R = 8
SCRYPT_P = 3
SALT_BYTES = 16
KEY_BYTES = 32
# Each check takes about 0.16 s and 32 MB. Waitress runs 4 threads; at most 2 hash at once,
# so a burst of sign-ins can't take every thread or more than 64 MB.
SCRYPT_AT_ONCE = threading.BoundedSemaphore(2)
THROWAWAY_SALT = bytes(SALT_BYTES)  # for the check an unknown name still runs

COOKIE = "__Host-rrtn"
DAY = 86400
LIFETIME = {"learner": 400 * DAY, "helper": 30 * DAY}
EXTEND_EVERY = DAY  # a session's expiry moves forward at most this often


class AccountError(ValueError):
    """A name or password that breaks the rules. `code` is a short word for API answers."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


# Names and passwords

def name_key(name):
    """What names are matched on: spaces at the start and end trimmed, capitals ignored."""
    return name.strip().lower()


def check_name(name):
    """The name as it is stored (trimmed), or AccountError."""
    name = name.strip()
    if not 1 <= len(name) <= NAME_MAX:
        raise AccountError("name-length", f"A name must be 1 to {NAME_MAX} characters.")
    return name


def check_password(password):
    if not PASSWORD_MIN <= len(password) <= PASSWORD_MAX:
        raise AccountError("password-length",
                           f"A password must be {PASSWORD_MIN} to {PASSWORD_MAX} characters.")
    return password


def _scrypt(password, salt, n, r, p):
    # OpenSSL's default memory cap (32 MB) is just under what N=2^15, r=8 needs.
    with SCRYPT_AT_ONCE:
        return hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p,
                              maxmem=2 * 128 * n * r, dklen=KEY_BYTES)


def hash_password(password, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P):
    """A stored hash: `scrypt$N$r$p$<salt hex>$<hash hex>`."""
    salt = secrets.token_bytes(SALT_BYTES)
    return f"scrypt${n}${r}${p}${salt.hex()}${_scrypt(password, salt, n, r, p).hex()}"


def _parse(stored):
    kind, n, r, p, salt, key = stored.split("$")
    if kind != "scrypt":
        raise ValueError(f"unknown hash kind {kind!r}")
    return int(n), int(r), int(p), bytes.fromhex(salt), bytes.fromhex(key)


def verify_password(password, stored):
    n, r, p, salt, key = _parse(stored)
    return hmac.compare_digest(_scrypt(password, salt, n, r, p), key)


def needs_rehash(stored):
    return _parse(stored)[:3] != (SCRYPT_N, SCRYPT_R, SCRYPT_P)


# Accounts

@contextlib.contextmanager
def _name_free():
    """Turns the database refusing a second account with the same name_key into AccountError."""
    try:
        yield
    except sqlite3.IntegrityError:
        raise AccountError("name-taken", "That name is already taken.") from None


def create_account(conn, role, name, password, now):
    """Add an account and return its id. AccountError if the name or password breaks the rules."""
    if role not in ROLES:
        raise ValueError(f"role must be one of {ROLES}")
    name = check_name(name)
    check_password(password)
    with _name_free():
        cur = conn.execute(
            "INSERT INTO accounts (role, name, name_key, password_hash, created_at) VALUES (?, ?, ?, ?, ?)",
            (role, name, name_key(name), hash_password(password), int(now)))
    return cur.lastrowid


def find_account(conn, name):
    """The account with this name (matched by name_key), or None."""
    return conn.execute("SELECT * FROM accounts WHERE name_key = ?", (name_key(name),)).fetchone()


def get_account(conn, account_id):
    return conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()


def rename_account(conn, account_id, name):
    """Give an account a new name and return it as stored. AccountError if it breaks the rules."""
    name = check_name(name)
    with _name_free():
        conn.execute("UPDATE accounts SET name = ?, name_key = ? WHERE id = ?", (name, name_key(name), account_id))
    return name


def set_password(conn, account_id, password):
    """Give an account a new password, end all of its sessions and clear its name's sign-in pause."""
    check_password(password)
    password_hash = hash_password(password)
    with db.transaction(conn):
        conn.execute("UPDATE accounts SET password_hash = ? WHERE id = ?", (password_hash, account_id))
        end_all_sessions(conn, account_id)
        account = get_account(conn, account_id)
        if account is not None:
            limits.clear_name(conn, account["name_key"])


def delete_account(conn, account_id):
    """Remove an account. Its sessions (and later its other rows) go with it."""
    conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))


def helper_exists(conn):
    return conn.execute("SELECT 1 FROM accounts WHERE role = 'helper' LIMIT 1").fetchone() is not None


def authenticate(conn, name, password):
    """(account, "signed-in") if the name and password match, else (None, "unknown-name" or "wrong-password").

    An unknown name still runs one throwaway check, so the time taken doesn't say whether
    the name exists. A name or password longer than any account's is refused unhashed.
    """
    if len(name.strip()) > NAME_MAX:
        return None, "unknown-name"
    account = find_account(conn, name)
    if len(password) > PASSWORD_MAX:
        return None, "unknown-name" if account is None else "wrong-password"
    if account is None:
        _scrypt(password, THROWAWAY_SALT, SCRYPT_N, SCRYPT_R, SCRYPT_P)
        return None, "unknown-name"
    if not verify_password(password, account["password_hash"]):
        return None, "wrong-password"
    if needs_rehash(account["password_hash"]):
        conn.execute("UPDATE accounts SET password_hash = ? WHERE id = ?",
                     (hash_password(password), account["id"]))
    return account, "signed-in"


# Sessions

def _token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def start_session(conn, account, now):
    """A new session token for the account. Only its SHA-256 is stored."""
    token = secrets.token_urlsafe(32)
    now = int(now)
    conn.execute("INSERT INTO sessions (token_hash, account_id, expires_at, last_extended_at) VALUES (?, ?, ?, ?)",
                 (_token_hash(token), account["id"], now + LIFETIME[account["role"]], now))
    return token


def end_session(conn, token):
    conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))


def end_all_sessions(conn, account_id):
    conn.execute("DELETE FROM sessions WHERE account_id = ?", (account_id,))


def session_account(conn, token, now):
    """(account, extended) for a live session token, or (None, False).

    An expired session is deleted. A live one has its expiry pushed forward if it was
    last pushed a day or more ago; `extended` says so, so the cookie can be renewed too.
    """
    now = int(now)
    row = conn.execute(
        "SELECT s.expires_at, s.last_extended_at, a.id, a.role, a.name FROM sessions s "
        "JOIN accounts a ON a.id = s.account_id WHERE s.token_hash = ?", (_token_hash(token),)).fetchone()
    if row is None:
        return None, False
    if row["expires_at"] <= now:
        end_session(conn, token)
        return None, False
    extended = now - row["last_extended_at"] >= EXTEND_EVERY
    if extended:
        conn.execute("UPDATE sessions SET expires_at = ?, last_extended_at = ? WHERE token_hash = ?",
                     (now + LIFETIME[row["role"]], now, _token_hash(token)))
    return row, extended


def cookie(token, max_age):
    return f"{COOKIE}={token}; Max-Age={max_age}; Path=/; Secure; HttpOnly; SameSite=Lax"


def cleared_cookie():
    return cookie("", 0)


def request_token(req):
    """The session token from the request's Cookie header, or None."""
    for part in (req.header("Cookie") or "").split(";"):
        key, _, value = part.strip().partition("=")
        if key == COOKIE and value:
            return value
    return None


_UNSET = object()


def current_account(req):
    """The signed-in account for this request, or None. Renews the cookie when the session is extended."""
    cached = getattr(req, "_account", _UNSET)
    if cached is not _UNSET:
        return cached
    account = None
    token = request_token(req)
    if token is not None:
        account, extended = session_account(req.db, token, req.now())
        if account is None:
            req.set_cookie(cleared_cookie())
        elif extended:
            req.set_cookie(cookie(token, LIFETIME[account["role"]]))
    req._account = account
    return account


def require(*roles):
    """Decorate a route handler so it runs only for a signed-in account, of one of `roles` if given."""
    def wrap(handler):
        @functools.wraps(handler)
        def checked(req):
            account = current_account(req)
            if account is None:
                raise HTTPError(401, "signed-out")
            if roles and account["role"] not in roles:
                raise HTTPError(403, "wrong-role")
            req.account = account
            return handler(req)
        return checked
    return wrap


# Routes

def _log_sign_in(now, address, name, outcome):
    """One line per sign-in: time, client IP, name and outcome. Never the password."""
    limits.log.info("%s sign-in ip=%s name=%s outcome=%s", db.iso_time(now), limits.log_text(address or "unknown"),
                    limits.log_text(name, NAME_MAX), outcome)


@route("POST", "/api/sign-in")
def sign_in(req):
    body = req.json()
    name = body.get("name") if isinstance(body, dict) else None
    password = body.get("password") if isinstance(body, dict) else None
    if not isinstance(name, str) or not isinstance(password, str):
        raise HTTPError(400, "send a name and a password")
    conn, now, address, key = req.db, req.now(), req.environ.get("REMOTE_ADDR"), name_key(name)
    limits.prune(conn, now)
    wait = limits.seconds_left(conn, (limits.name(key), limits.ip(address)), now)
    if wait:
        _log_sign_in(now, address, name, "paused")
        return json_response({"error": "paused", "retry_after": wait}, 429)
    account, outcome = authenticate(conn, name, password)
    _log_sign_in(now, address, name, outcome)
    if account is None:
        limits.failed(conn, key, address, now)
        raise HTTPError(401, "mismatch")
    now = int(now)
    with db.transaction(conn):
        limits.clear_name(conn, key)
        conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
        token = start_session(conn, account, now)
    req.set_cookie(cookie(token, LIFETIME[account["role"]]))
    return json_response({"role": account["role"], "name": account["name"]})


@route("POST", "/api/sign-out")
def sign_out(req):
    token = request_token(req)
    if token is not None:
        end_session(req.db, token)
    req.set_cookie(cleared_cookie())
    return Response(204)


@route("GET", "/api/me")
@require()
def me(req):
    a = req.account
    return json_response({"id": a["id"], "role": a["role"], "name": a["name"]})
