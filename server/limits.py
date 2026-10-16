"""Sign-in limits: too many failed sign-ins pause sign-in for a name or a client IP.

Counted in the sign_in_limits table, one row per key (`name:<name_key>` or `ip:<address>`):

- A name: 10 failed tries pause it for 15 minutes. Each further pause, with no
  successful sign-in in between, doubles, up to 24 hours. Names that no account has
  are counted the same way. A successful sign-in clears the name's row.
- A client IP: 50 failed tries within an hour pause it for 1 hour. A success does
  not clear it.
- During a pause the password is not checked and the try is not counted. Sessions
  already signed in keep working: a pause only blocks new sign-ins.
- Every pause ends by itself. Reset sign-in (a Learner) and `server.manage password`
  (a Helper) clear one name; `server.manage unlock` clears every row.
- Rows with no activity for 24 hours are deleted, at most once an hour, during a sign-in.

Times are whole seconds since 1970 (UTC). Every function takes `now`, so tests use a fake clock.
"""
import logging

from . import db

NAME_FAILURES = 10
NAME_PAUSE = 15 * 60          # the first pause; each further one doubles
NAME_PAUSE_MAX = 24 * 3600
IP_FAILURES = 50
IP_WINDOW = 3600              # an IP's failures are counted within this long
IP_PAUSE = 3600
IDLE = 24 * 3600              # a row with no activity this long is deleted
PRUNE_EVERY = 3600
PRUNED_AT = "sign_in_limits_pruned_at"  # meta key: when rows were last pruned
# No account name is over 64 characters, so a longer one is cut to 65 for its key:
# its row stays small, and it never shares a row with a real name.
NAME_KEY_CHARS = 65

log = logging.getLogger("rrtn.sign-in")


def key_for_name(name_key):
    """The row key for a name, given its name_key (see auth.name_key)."""
    return "name:" + name_key[:NAME_KEY_CHARS]


def key_for_ip(address):
    """The row key for a client IP."""
    return "ip:" + (address or "unknown")


def log_text(value, limit=None):
    """`value` cut to `limit` characters, in quotes, with quotes, backslashes and control characters escaped."""
    out = []
    for ch in value[:limit]:
        if ch in '"\\':
            out.append("\\" + ch)
        elif ch.isprintable() or ch == " ":
            out.append(ch)
        elif ord(ch) < 0x100:
            out.append(f"\\x{ord(ch):02x}")
        elif ord(ch) < 0x10000:
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(f"\\U{ord(ch):08x}")
    return '"' + "".join(out) + '"'


def seconds_left(conn, keys, now):
    """Whole seconds until every pause on these keys has ended, or 0 if none is paused.

    Never more than the pause left: a pause with under a second to go counts as ended.
    """
    marks = ", ".join("?" * len(keys))
    until = conn.execute(f"SELECT MAX(paused_until) FROM sign_in_limits WHERE key IN ({marks})",
                         list(keys)).fetchone()[0]
    left = 0 if until is None else int(until - now)
    return max(left, 0)


def _count(conn, key, now, limit, first_pause, max_pause, window=None):
    """Count one failure for a key. Returns the length of the pause it started, or None.

    The first pause is `first_pause` long; each further one doubles, up to `max_pause`.
    """
    row = conn.execute("SELECT failures, window_start, paused_until, level FROM sign_in_limits WHERE key = ?",
                       (key,)).fetchone()
    failures, start, paused_until, level = (0, now, None, 0) if row is None else tuple(row)
    if window is not None and now - start >= window:
        failures, start = 0, now
    failures += 1
    pause = None
    if failures >= limit:
        pause = min(first_pause * 2 ** min(level, 16), max_pause)
        failures, start, paused_until, level = 0, now, now + pause, level + 1
    conn.execute(
        "INSERT INTO sign_in_limits (key, failures, window_start, paused_until, level, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (key) DO UPDATE SET failures = excluded.failures, "
        "window_start = excluded.window_start, paused_until = excluded.paused_until, "
        "level = excluded.level, updated_at = excluded.updated_at",
        (key, failures, start, paused_until, level, now))
    if pause is not None:
        log.info("%s pause key=%s seconds=%d until=%s", db.iso_time(now), log_text(key), pause, db.iso_time(now + pause))
    return pause


def failed(conn, name_key, address, now):
    """Count a failed sign-in for a name and a client IP, pausing either that reaches its limit."""
    now = int(now)
    with db.transaction(conn):
        _count(conn, key_for_name(name_key), now, NAME_FAILURES, NAME_PAUSE, NAME_PAUSE_MAX)
        _count(conn, key_for_ip(address), now, IP_FAILURES, IP_PAUSE, IP_PAUSE, window=IP_WINDOW)


def clear_name(conn, name_key):
    """Forget a name's failures, pause and pause level (a successful sign-in, Reset sign-in, a new password)."""
    conn.execute("DELETE FROM sign_in_limits WHERE key = ?", (key_for_name(name_key),))


def clear_all(conn):
    """Forget every name's and IP's failures and pauses. Returns how many rows were deleted."""
    return conn.execute("DELETE FROM sign_in_limits").rowcount


def paused_names(conn, now):
    """{name key: paused_until} for every name paused now."""
    rows = conn.execute("SELECT key, paused_until FROM sign_in_limits WHERE key LIKE 'name:%' "
                        "AND paused_until - ? >= 1", (now,)).fetchall()
    return {row["key"]: row["paused_until"] for row in rows}


def prune(conn, now):
    """Delete rows with no activity for IDLE seconds, if that wasn't done in the last PRUNE_EVERY."""
    now = int(now)
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (PRUNED_AT,)).fetchone()
    if row is not None and now - int(row[0]) < PRUNE_EVERY:
        return
    with db.transaction(conn):
        conn.execute("DELETE FROM sign_in_limits WHERE MAX(updated_at, COALESCE(paused_until, 0)) <= ?",
                     (now - IDLE,))
        conn.execute("INSERT INTO meta (key, value) VALUES (?, ?) "
                     "ON CONFLICT (key) DO UPDATE SET value = excluded.value", (PRUNED_AT, str(now)))
