"""Start the Instance: `python -m server`.

Reads its settings from environment variables, checks them, sets up the database
and serves the app with waitress. Exits with a one-line message if a setting is wrong.

    RRTN_DIR            the Instance folder (default /var/lib/rrtn)
    RRTN_PORT           the port to listen on (default 8080)
    RRTN_TRUSTED_PROXY  required: the reverse proxy's IP, or *
    RRTN_ORIGIN         required: the public address, e.g. https://permit.example.org
"""
import logging
import os
import pathlib
import sqlite3
import sys
import tempfile
import urllib.parse
from dataclasses import dataclass


class ConfigError(Exception):
    """A setting is missing or wrong. The message is one line naming the problem."""


@dataclass(frozen=True)
class Config:
    dir: pathlib.Path
    port: int
    trusted_proxy: str
    origin: str


def load_config(environ):
    """Read and check the settings. Raises ConfigError naming the first problem found."""
    for name in ("RRTN_TRUSTED_PROXY", "RRTN_ORIGIN"):
        if not environ.get(name, "").strip():
            raise ConfigError(f"{name} is not set")

    origin = environ["RRTN_ORIGIN"].strip().rstrip("/")
    parts = urllib.parse.urlsplit(origin)
    if parts.scheme not in ("http", "https") or not parts.netloc or parts.path or parts.query or parts.fragment:
        raise ConfigError(f"RRTN_ORIGIN must be a scheme and host only, like https://permit.example.org (got {origin!r})")

    raw_port = environ.get("RRTN_PORT", "").strip() or "8080"
    if not raw_port.isdigit() or not 0 < int(raw_port) < 65536:
        raise ConfigError(f"RRTN_PORT must be a port number (got {raw_port!r})")

    folder = pathlib.Path(environ.get("RRTN_DIR", "").strip() or "/var/lib/rrtn")
    try:
        with tempfile.TemporaryFile(dir=folder):
            pass
    except OSError as e:
        raise ConfigError(f"RRTN_DIR {folder} can't be written to ({e.strerror or e})") from None

    return Config(dir=folder, port=int(raw_port),
                  trusted_proxy=environ["RRTN_TRUSTED_PROXY"].strip(), origin=origin)


ROOT = pathlib.Path(__file__).resolve().parent.parent
VENDOR = ROOT / "vendor"
DIST = ROOT / "dist"


def fail(message):
    print(f"rrtn: {message}", file=sys.stderr)
    sys.exit(2)


def warn_if_no_helper(folder):
    """Helpers are made only with server.manage, so until one exists the log says how."""
    from . import auth, db
    conn = db.connect(folder)
    try:
        if not auth.helper_exists(conn):
            logging.getLogger("rrtn").warning("No Helper account exists. Run: python -m server.manage add <name>")
    finally:
        conn.close()


def main():
    try:
        config = load_config(os.environ)
    except ConfigError as e:
        fail(e)

    from . import app, db

    try:
        db.migrate(config.dir)
    except sqlite3.Error as e:
        fail(f"can't open the database {db.path(config.dir)} ({e})")

    # waitress is vendored, never installed: see vendor/README.md.
    sys.path.insert(0, str(VENDOR))
    import waitress

    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    warn_if_no_helper(config.dir)
    waitress.serve(
        app.make_app(dist=DIST, instance_dir=config.dir, origin=config.origin),
        host="0.0.0.0",
        port=config.port,
        trusted_proxy=config.trusted_proxy,
        trusted_proxy_headers={"x-forwarded-for", "x-forwarded-proto"},
        ident="rrtn",
    )


if __name__ == "__main__":
    main()
