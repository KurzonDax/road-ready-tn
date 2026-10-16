"""Manage Helper accounts: `python -m server.manage add|password|remove <name>`,
end every sign-in pause: `python -m server.manage unlock`, and copy the database:
`python -m server.manage backup`.

Run it inside the container, where RRTN_DIR names the Instance folder (default
/var/lib/rrtn). Passwords are typed at a prompt, twice, and never taken as an
argument. Learner accounts are managed from the Helper's view, not here.

`--password-stdin` (hidden, for tests) reads the password as one line from
standard input instead of asking for it.
"""
import argparse
import getpass
import os
import pathlib
import sqlite3
import sys
import time

from . import auth, db, limits

PROG = "python -m server.manage"


class Refused(Exception):
    """Something the command won't do. The message is printed and the command exits 1."""


def checked(password):
    try:
        return auth.check_password(password)
    except auth.AccountError as e:
        raise Refused(f"{e} Nothing was changed.") from None


def ask_password():
    first = getpass.getpass("New password: ")
    second = getpass.getpass("Type it again: ")
    if first != second:
        raise Refused("The two passwords are not the same. Nothing was changed.")
    return checked(first)


def read_password():
    """The password as one line from standard input (`--password-stdin`, for tests)."""
    return checked(sys.stdin.readline().rstrip("\r\n"))


def find_helper(conn, name):
    account = auth.find_account(conn, name)
    if account is None:
        raise Refused(f"There is no Helper named {name.strip()!r}.")
    if account["role"] != "helper":
        raise Refused(f"{account['name']!r} is a Learner. Manage Learners from the Helper's view.")
    return account


def add(conn, name, new_password):
    try:
        name = auth.check_name(name)
    except auth.AccountError as e:
        raise Refused(str(e)) from None
    if auth.find_account(conn, name) is not None:
        raise Refused("That name is already taken.")
    try:
        auth.create_account(conn, "helper", name, new_password(), now=time.time())
    except auth.AccountError as e:
        raise Refused(str(e)) from None
    return f"Added the Helper {name!r}."


def password(conn, name, new_password):
    account = find_helper(conn, name)
    auth.set_password(conn, account["id"], new_password())  # also clears a sign-in pause on the name
    return f"Set a new password for {account['name']!r}. Their sign-ins have ended."


def remove(conn, name, new_password):
    account = find_helper(conn, name)
    auth.delete_account(conn, account["id"])
    return f"Removed the Helper {account['name']!r}."


def unlock(conn, name, new_password):
    cleared = limits.clear_all(conn)
    what = "1 name or IP" if cleared == 1 else f"{cleared} names and IPs"
    return f"Cleared the sign-in counts and pauses for {what}."


def backup(conn, name, new_password):
    """Copy the database to <Instance folder>/backups/<YYYY-MM-DD-HHMMSS>.db and return its path.

    sqlite3's backup() takes a consistent copy while the server keeps running. The copy is
    written under a temporary name first, so a half-written file is never left with a real name.
    """
    folder = pathlib.Path(conn.execute("PRAGMA database_list").fetchone()["file"]).parent
    backups = folder / "backups"
    backups.mkdir(exist_ok=True)
    stamp = time.strftime("%Y-%m-%d-%H%M%S", time.gmtime(time.time()))
    target, n = backups / f"{stamp}.db", 1
    while target.exists():
        n += 1
        target = backups / f"{stamp}-{n}.db"
    partial = target.with_name(target.name + ".part")
    copy = sqlite3.connect(partial)
    try:
        conn.backup(copy)
        copy.execute("PRAGMA journal_mode = DELETE")  # one self-contained file, no -wal beside it
    finally:
        copy.close()
    os.replace(partial, target)
    return str(target)


# command: (function, help, takes a name)
COMMANDS = {
    "add": (add, "make a Helper", True),
    "password": (password, "set a new password for a Helper and end their sign-ins", True),
    "remove": (remove, "delete a Helper", True),
    "unlock": (unlock, "end every sign-in pause, for names and IPs", False),
    "backup": (backup, "copy the database to backups/ in the Instance folder", False),
}


def main(argv=None, environ=None):
    """Run the command. Returns the exit status: 0 done, 1 refused, 2 the database can't be opened."""
    environ = os.environ if environ is None else environ
    parser = argparse.ArgumentParser(prog=PROG, description="Manage Helper accounts and sign-in pauses, and back up the database.")
    sub = parser.add_subparsers(dest="command", required=True)
    for command, (_, help_text, takes_name) in COMMANDS.items():
        command_parser = sub.add_parser(command, help=help_text)
        if takes_name:
            command_parser.add_argument("name")
        command_parser.add_argument("--password-stdin", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    folder = pathlib.Path(environ.get("RRTN_DIR", "").strip() or "/var/lib/rrtn")
    try:
        db.migrate(folder)
        conn = db.connect(folder)
    except sqlite3.Error as e:
        print(f"{PROG}: can't open the database {db.path(folder)} ({e})", file=sys.stderr)
        return 2
    try:
        new_password = read_password if args.password_stdin else ask_password
        print(COMMANDS[args.command][0](conn, getattr(args, "name", None), new_password))
        return 0
    except Refused as e:
        print(f"{PROG}: {e}", file=sys.stderr)
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
