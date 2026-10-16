"""Manage Helper accounts: `python -m server.manage add|password|remove <name>`.

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

from . import auth, db

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
    auth.set_password(conn, account["id"], new_password())
    return f"Set a new password for {account['name']!r}. Their sign-ins have ended."


def remove(conn, name, new_password):
    account = find_helper(conn, name)
    auth.delete_account(conn, account["id"])
    return f"Removed the Helper {account['name']!r}."


COMMANDS = {
    "add": (add, "make a Helper"),
    "password": (password, "set a new password for a Helper and end their sign-ins"),
    "remove": (remove, "delete a Helper"),
}


def main(argv=None, environ=None):
    """Run the command. Returns the exit status: 0 done, 1 refused, 2 the database can't be opened."""
    environ = os.environ if environ is None else environ
    parser = argparse.ArgumentParser(prog=PROG, description="Manage Helper accounts.")
    sub = parser.add_subparsers(dest="command", required=True)
    for command, (_, help_text) in COMMANDS.items():
        command_parser = sub.add_parser(command, help=help_text)
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
        print(COMMANDS[args.command][0](conn, args.name, new_password))
        return 0
    except Refused as e:
        print(f"{PROG}: {e}", file=sys.stderr)
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
