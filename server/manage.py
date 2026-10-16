"""Manage Helper accounts: `python -m server.manage add|password|remove <name>`.

Run it inside the container, where RRTN_DIR names the Instance folder (default
/var/lib/rrtn). Passwords are typed at a prompt, twice, and never taken as an
argument. Learner accounts are managed from the Helper's view, not here.
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


def ask_password():
    first = getpass.getpass("New password: ")
    second = getpass.getpass("Type it again: ")
    if first != second:
        raise Refused("The two passwords are not the same. Nothing was changed.")
    try:
        return auth.check_password(first)
    except auth.AccountError as e:
        raise Refused(f"{e} Nothing was changed.") from None


def find_helper(conn, name):
    account = auth.find_account(conn, name)
    if account is None:
        raise Refused(f"There is no Helper named {name.strip()!r}.")
    if account["role"] != "helper":
        raise Refused(f"{account['name']!r} is a Learner. Manage Learners from the Helper's view.")
    return account


def add(conn, name):
    try:
        name = auth.check_name(name)
    except auth.AccountError as e:
        raise Refused(str(e)) from None
    if auth.find_account(conn, name) is not None:
        raise Refused("That name is already taken.")
    try:
        auth.create_account(conn, "helper", name, ask_password(), now=time.time())
    except auth.AccountError as e:
        raise Refused(str(e)) from None
    return f"Added the Helper {name!r}."


def password(conn, name):
    account = find_helper(conn, name)
    auth.set_password(conn, account["id"], ask_password())
    return f"Set a new password for {account['name']!r}. Their sign-ins have ended."


def remove(conn, name):
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
        sub.add_parser(command, help=help_text).add_argument("name")
    args = parser.parse_args(argv)

    folder = pathlib.Path(environ.get("RRTN_DIR", "").strip() or "/var/lib/rrtn")
    try:
        db.migrate(folder)
        conn = db.connect(folder)
    except sqlite3.Error as e:
        print(f"{PROG}: can't open the database {db.path(folder)} ({e})", file=sys.stderr)
        return 2
    try:
        print(COMMANDS[args.command][0](conn, args.name))
        return 0
    except Refused as e:
        print(f"{PROG}: {e}", file=sys.stderr)
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
