"""The Instance database: SQLite at <Instance folder>/rrtn.db.

Times are kept as whole seconds since 1970 (UTC); `iso_time` writes one out for answers and logs.

Schema changes are numbered steps in STEPS. `PRAGMA user_version` records how many
have run, and `migrate()` runs the rest at start. To change the schema, append a
step; never edit or reorder one that has shipped.
"""
import datetime
import pathlib
import sqlite3

FILENAME = "rrtn.db"
DEFAULT_DIR = "/var/lib/rrtn"  # the Instance folder when RRTN_DIR is not set
BUSY_TIMEOUT_MS = 5000

# Each step is a script run in one transaction. Step n is STEPS[n - 1].
STEPS = [
    # 1: a place for Instance-wide values.
    """
    CREATE TABLE meta (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL
    ) STRICT;
    """,
    # 2: accounts and their sign-in sessions. Times are whole seconds since 1970 (UTC).
    """
    CREATE TABLE accounts (
        id            INTEGER PRIMARY KEY,
        role          TEXT NOT NULL CHECK (role IN ('helper', 'learner')),
        name          TEXT NOT NULL,
        name_key      TEXT NOT NULL UNIQUE,  -- the name trimmed and lowercased
        password_hash TEXT NOT NULL,         -- scrypt$N$r$p$salt$hash, see server/auth.py
        created_at    INTEGER NOT NULL
    ) STRICT;
    CREATE TABLE sessions (
        token_hash       TEXT PRIMARY KEY,   -- SHA-256 of the cookie's token, never the token
        account_id       INTEGER NOT NULL REFERENCES accounts (id) ON DELETE CASCADE,
        expires_at       INTEGER NOT NULL,
        last_extended_at INTEGER NOT NULL
    ) STRICT;
    CREATE INDEX sessions_by_account ON sessions (account_id);
    """,
    # 3: each Learner's records (a list that only grows) and their one unfinished Set.
    # The record is kept as the JSON the device sent; see server/records.py for its shape.
    """
    CREATE TABLE records (
        id          TEXT PRIMARY KEY,         -- made on the device, so a record sent twice is stored once
        account_id  INTEGER NOT NULL REFERENCES accounts (id) ON DELETE CASCADE,
        kind        TEXT NOT NULL CHECK (kind IN ('set', 'reset', 'move', 'imported')),
        record      TEXT NOT NULL,            -- the record as JSON: id, kind, reset, at, data
        seq         INTEGER NOT NULL UNIQUE,  -- arrival number, increasing across the Instance
        received_at INTEGER NOT NULL
    ) STRICT;
    CREATE INDEX records_by_account ON records (account_id, seq);
    CREATE TABLE unfinished_sets (
        account_id INTEGER PRIMARY KEY REFERENCES accounts (id) ON DELETE CASCADE,
        set_json   TEXT NOT NULL,
        saved_at   INTEGER NOT NULL
    ) STRICT;
    """,
    # 4: sign-in limits, one row per name or client IP with failed sign-ins. See server/limits.py.
    """
    CREATE TABLE sign_in_limits (
        key          TEXT PRIMARY KEY,   -- 'name:<name_key>' or 'ip:<client ip>'
        failures     INTEGER NOT NULL,   -- failed tries counted since window_start
        window_start INTEGER NOT NULL,
        paused_until INTEGER,            -- NULL when not paused
        level        INTEGER NOT NULL,   -- pauses so far with no successful sign-in between
        updated_at   INTEGER NOT NULL    -- the last failed try
    ) STRICT;
    """,
]


def instance_dir(environ):
    """The Instance folder named by RRTN_DIR in `environ`, or DEFAULT_DIR."""
    return pathlib.Path(environ.get("RRTN_DIR", "").strip() or DEFAULT_DIR)


def path(instance_dir):
    return pathlib.Path(instance_dir) / FILENAME


def iso_time(seconds):
    """A time the database keeps (whole seconds) as ISO 8601 UTC."""
    return datetime.datetime.fromtimestamp(int(seconds), datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _open(instance_dir, mode):
    uri = path(instance_dir).resolve().as_uri() + f"?mode={mode}"
    conn = sqlite3.connect(uri, uri=True, timeout=BUSY_TIMEOUT_MS / 1000,
                           isolation_level=None, check_same_thread=False)
    try:
        conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
    except BaseException:
        conn.close()
        raise
    return conn


def connect(instance_dir):
    """Open a connection to an existing database. The app opens one per request.

    Autocommit mode: use `with transaction(conn):` around writes that belong together.
    Raises sqlite3.Error if the database file is missing or can't be opened.
    """
    return _open(instance_dir, "rw")


class transaction:
    """`with transaction(conn):` runs the block in BEGIN IMMEDIATE ... COMMIT, or rolls back."""

    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        self.conn.execute("BEGIN IMMEDIATE")
        return self.conn

    def __exit__(self, exc_type, exc, tb):
        self.conn.execute("ROLLBACK" if exc_type else "COMMIT")
        return False


def migrate(instance_dir):
    """Create the database if needed, switch it to WAL and run any schema steps not yet run.

    Returns the schema version afterwards.
    """
    conn = _open(instance_dir, "rwc")
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        for number, script in enumerate(STEPS, start=1):
            if number <= version:
                continue
            # executescript() commits first, so wrap the step and its version bump ourselves.
            conn.executescript(f"BEGIN IMMEDIATE;\n{script}\nPRAGMA user_version = {number};\nCOMMIT;")
            version = number
        return version
    finally:
        conn.close()
