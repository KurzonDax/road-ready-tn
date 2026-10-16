"""The Instance database: SQLite at <Instance folder>/rrtn.db.

Schema changes are numbered steps in STEPS. `PRAGMA user_version` records how many
have run, and `migrate()` runs the rest at start. To change the schema, append a
step; never edit or reorder one that has shipped.
"""
import pathlib
import sqlite3

FILENAME = "rrtn.db"
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
]


def path(instance_dir):
    return pathlib.Path(instance_dir) / FILENAME


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
