"""The Instance server: a small WSGI app served by the vendored waitress."""

# Load the app (and, through it, every route module) first, whichever module is
# imported: server.auth and server.records import from server.app, and app imports
# them at its end, so starting from auth would meet a half-loaded auth.
from . import app  # noqa: E402,F401
