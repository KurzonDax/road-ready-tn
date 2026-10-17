"""The routes behind the Helper's view: the Learner list, one Learner's records, and
managing a Learner (add, rename, Reset sign-in, Reset progress, Move, delete).

Every route here needs a Helper session. All Helpers are equal, and the server records
nothing about which Helper did what.
"""
import re

from . import auth, db, limits, records
from .app import HTTPError, Response, json_response, route

LEARNER_ID = re.compile(r"[1-9][0-9]{0,17}")  # an account id in a path: plain ASCII digits
# What an AccountError's code becomes in an answer: (status, error).
ACCOUNT_ERRORS = {"name-length": (400, "bad-name"), "password-length": (400, "bad-password"),
                  "name-taken": (409, "name-taken")}


def _body(req):
    """The request body, which must be a JSON object."""
    body = req.json()
    if not isinstance(body, dict):
        raise HTTPError(400, "send a JSON object")
    return body


def _string(body, field, error):
    value = body.get(field)
    if not isinstance(value, str):
        raise HTTPError(400, error)
    return value


def _account_error(e):
    status, error = ACCOUNT_ERRORS[e.code]
    return HTTPError(status, error)


def _learner(req):
    """The Learner account that the path's <id> names, or 404."""
    text = req.params["id"]
    account = None
    if LEARNER_ID.fullmatch(text):
        account = auth.get_account(req.db, int(text))
    if account is None or account["role"] != "learner":
        raise HTTPError(404, "no-learner")
    return account


@route("GET", "/api/learners")
@auth.require("helper")
def list_learners(req):
    rows = req.db.execute("SELECT id, name, name_key, created_at FROM accounts WHERE role = 'learner' "
                          "ORDER BY name_key, id").fetchall()
    paused = limits.paused_names(req.db, req.now())

    def paused_until(row):
        until = paused.get(limits.key_for_name(row["name_key"]))
        return None if until is None else db.iso_time(until)

    return json_response({"learners": [{"id": row["id"], "name": row["name"],
                                        "created_at": db.iso_time(row["created_at"]),
                                        "paused_until": paused_until(row)} for row in rows]})


@route("POST", "/api/learners")
@auth.require("helper")
def add_learner(req):
    body = _body(req)
    name = _string(body, "name", "bad-name")
    password = _string(body, "password", "bad-password")
    try:
        account_id = auth.create_account(req.db, "learner", name, password, req.now())
    except auth.AccountError as e:
        raise _account_error(e) from None
    return json_response({"id": account_id, "name": auth.get_account(req.db, account_id)["name"]}, 201)


@route("GET", "/api/learners/<id>/records")
@auth.require("helper")
def learner_records(req):
    learner_id = _learner(req)["id"]
    return json_response({"records": records.learner_records(req.db, learner_id),
                          "unfinished": records.unfinished_set(req.db, learner_id)})


@route("POST", "/api/learners/<id>/rename")
@auth.require("helper")
def rename_learner(req):
    learner_id = _learner(req)["id"]
    name = _string(_body(req), "name", "bad-name")
    try:
        name = auth.rename_account(req.db, learner_id, name)
    except auth.AccountError as e:
        raise _account_error(e) from None
    return json_response({"id": learner_id, "name": name})


@route("POST", "/api/learners/<id>/reset-sign-in")
@auth.require("helper")
def reset_sign_in(req):
    """A new password for the Learner. Every one of their sessions ends, and any sign-in pause on their name."""
    learner = _learner(req)
    password = _string(_body(req), "password", "bad-password")
    try:
        auth.set_password(req.db, learner["id"], password)
    except auth.AccountError as e:
        raise _account_error(e) from None
    return json_response({"id": learner["id"], "name": learner["name"]})


@route("POST", "/api/learners/<id>/reset-progress")
@auth.require("helper")
def reset_progress(req):
    """A Reset record: every fact is new again and new facts start at Section 1. Earlier records stay as History."""
    learner_id = _learner(req)["id"]
    _body(req)
    return json_response({"record": records.helper_record(req.db, learner_id, "reset", {}, req.now())})


@route("POST", "/api/learners/<id>/move")
@auth.require("helper")
def move(req):
    """A Move record: new facts come from Section `to` on (13 unlocks Practice tests)."""
    learner_id = _learner(req)["id"]
    body = _body(req)
    try:
        record = records.helper_record(req.db, learner_id, "move", {"to": body.get("to")}, req.now())
    except ValueError:
        raise HTTPError(400, "bad-move") from None
    return json_response({"record": record})


@route("POST", "/api/learners/<id>/delete")
@auth.require("helper")
def delete_learner(req):
    """Remove the Learner for good: the account, its sessions, records and unfinished Set.

    The body's name must match the Learner's, so a slip of the finger deletes nothing.
    """
    learner = _learner(req)
    name = _body(req).get("name")
    if not isinstance(name, str) or auth.name_key(name) != learner["name_key"]:
        raise HTTPError(400, "name-mismatch")
    auth.delete_account(req.db, learner["id"])  # the other rows go with it (ON DELETE CASCADE)
    return Response(204)
