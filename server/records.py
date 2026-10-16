"""A Learner's records and their one unfinished Set: storing them and handing them back.

The server checks only each record's shape and size. It holds no study rules and no
scoring: the page works Progress out from the records (docs/adr/0001-*).

A record, as the device makes it:

    {"id": "...", "kind": "set" | "reset" | "move" | "imported",
     "reset": <id of the latest Reset the device knew about, or null>,
     "at": "<ISO 8601 UTC>", "data": {...depends on kind...}}

The server adds "seq" (arrival number) and "received_at" when handing records back.
"""
import datetime
import json
import re
import secrets

from . import auth, db
from .app import HTTPError, Response, json_response, route

KINDS = ("set", "reset", "move", "imported")
LEARNER_KINDS = ("set", "imported")  # reset and move come only from a Helper
HELPER_KINDS = ("reset", "move")     # made by the server when a Helper asks (helper_record)
MAX_RECORDS = 100  # per request
MAX_UNFINISHED = 16 * 1024  # bytes of an unfinished Set's compact JSON


class RecordError(ValueError):
    """A record that breaks the shape rules, or a kind the sender may not store. `index` is its place."""

    def __init__(self, index, message):
        super().__init__(message)
        self.index = index


ID = re.compile(r"[A-Za-z0-9_-]{16,64}")
# ISO 8601 in UTC, as the page's Date.toISOString() writes it (the fraction and +00:00 are allowed too).
UTC_TIME = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d{1,6})?(Z|\+00:00)")
SET_TYPES = ("day", "redo", "review", "test")  # the page's own names for a Section, a redo, Review, a Practice test
SECTION_TYPES = ("day", "redo")                # the types that name a Section
SECTIONS = 12
MOVE_TO = SECTIONS + 1                         # a Move "to 13" sends the Learner on to Review and Practice tests
MAX_ANSWERS = 50


def _fields(value, what, names):
    """`value` must be an object with exactly these field names."""
    if not isinstance(value, dict):
        raise ValueError(f"{what} must be an object")
    if set(value) != set(names):
        raise ValueError(f"{what} must have exactly the fields {', '.join(names)}")
    return value


def _is_int(value, low, high):
    return type(value) is int and low <= value <= high


def _check_time(value, what):
    if not isinstance(value, str) or not UTC_TIME.fullmatch(value):
        raise ValueError(f"{what} must be an ISO 8601 time in UTC")
    try:
        datetime.datetime.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{what} is not a real time") from None


def _check_set(data):
    _fields(data, "a set's data", ("set_id", "type", "section", "started_at", "answers"))
    if not isinstance(data["set_id"], str) or not data["set_id"]:
        raise ValueError("set_id must be a string")
    if data["type"] not in SET_TYPES:
        raise ValueError(f"type must be one of {', '.join(SET_TYPES)}")
    if data["type"] in SECTION_TYPES:
        if not _is_int(data["section"], 1, SECTIONS):
            raise ValueError(f"section must be 1 to {SECTIONS} for {data['type']}")
    elif data["section"] is not None:
        raise ValueError(f"section must be null for {data['type']}")
    _check_time(data["started_at"], "started_at")
    answers = data["answers"]
    if not isinstance(answers, list) or not 1 <= len(answers) <= MAX_ANSWERS:
        raise ValueError(f"answers must be a list of 1 to {MAX_ANSWERS}")
    for answer in answers:
        _fields(answer, "an answer", ("q", "chosen", "right", "at"))
        if not isinstance(answer["q"], str) or not isinstance(answer["chosen"], str):
            raise ValueError("an answer's q and chosen must be strings")
        if not isinstance(answer["right"], bool):
            raise ValueError("an answer's right must be true or false")
        _check_time(answer["at"], "an answer's at")


def _check_imported(data):
    if not isinstance(_fields(data, "an imported record's data", ("state",))["state"], dict):
        raise ValueError("state must be an object")


def _check_reset(data):
    _fields(data, "a reset's data", ())


def _check_move(data):
    if not _is_int(_fields(data, "a move's data", ("to",))["to"], 1, MOVE_TO):
        raise ValueError(f"to must be 1 to {MOVE_TO}")


CHECK_DATA = {"set": _check_set, "reset": _check_reset, "move": _check_move, "imported": _check_imported}


def check_record(record, kinds=KINDS):
    """Raise ValueError unless `record` has the record shape and one of `kinds`.

    Only the shape is checked. Whether a Set moves the Learner on is the page's business.
    """
    _fields(record, "a record", ("id", "kind", "reset", "at", "data"))
    if not isinstance(record["id"], str) or not ID.fullmatch(record["id"]):
        raise ValueError("id must be 16 to 64 characters from A-Z a-z 0-9 _ -")
    if record["kind"] not in kinds:
        raise ValueError(f"kind must be one of {', '.join(kinds)}")
    if record["reset"] is not None and not (isinstance(record["reset"], str) and ID.fullmatch(record["reset"])):
        raise ValueError("reset must be a record id or null")
    _check_time(record["at"], "at")
    CHECK_DATA[record["kind"]](record["data"])


def iso_time(seconds):
    """A time the server keeps (whole seconds) as ISO 8601 UTC."""
    return datetime.datetime.fromtimestamp(int(seconds), datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def store_records(conn, account_id, records, now, kinds=LEARNER_KINDS):
    """Store new records for a Learner, all or none. Returns (stored, skipped).

    A record whose id is already stored is skipped, and so is a second `imported` record
    for the Learner. A `set` record clears the unfinished Set with the same set_id.
    Raises RecordError (nothing stored) if any record breaks the shape rules or has a kind
    not in `kinds`.
    """
    for index, record in enumerate(records):
        try:
            check_record(record, kinds)
        except ValueError as e:
            raise RecordError(index, str(e)) from None
    stored = skipped = 0
    with db.transaction(conn):
        for record in records:
            if record["kind"] == "set":
                _drop_unfinished(conn, account_id, record["data"]["set_id"])
            if _already_have(conn, account_id, record):
                skipped += 1
                continue
            _insert(conn, account_id, record, now)
            stored += 1
    return stored, skipped


def _insert(conn, account_id, record, now):
    """Store one record with the next arrival number, inside a transaction. Returns the seq."""
    seq = conn.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM records").fetchone()[0]
    conn.execute("INSERT INTO records (id, account_id, kind, record, seq, received_at) "
                 "VALUES (?, ?, ?, ?, ?, ?)",
                 (record["id"], account_id, record["kind"], _compact(record), seq, int(now)))
    return seq


def helper_record(conn, account_id, kind, data, now):
    """Make and store a `reset` or `move` record for a Learner, and drop their unfinished Set.

    The server makes the record itself: a new random id, `reset` naming the Learner's latest
    Reset (or null), and `at` now in the page's own time format. Returns the record as
    learner_records() hands it back. ValueError if `data` breaks the shape rules.
    """
    with db.transaction(conn):
        latest = conn.execute("SELECT id FROM records WHERE account_id = ? AND kind = 'reset' "
                              "ORDER BY seq DESC LIMIT 1", (account_id,)).fetchone()
        record = {"id": secrets.token_urlsafe(18), "kind": kind,
                  "reset": None if latest is None else latest["id"], "at": page_time(now), "data": data}
        check_record(record, HELPER_KINDS)
        seq = _insert(conn, account_id, record, now)
        save_unfinished(conn, account_id, None, now)
    return {**record, "seq": seq, "received_at": iso_time(now)}


def page_time(seconds):
    """A time as the page's Date.toISOString() writes it: UTC, to the millisecond."""
    moment = datetime.datetime.fromtimestamp(seconds, datetime.UTC)
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _already_have(conn, account_id, record):
    if conn.execute("SELECT 1 FROM records WHERE id = ?", (record["id"],)).fetchone():
        return True
    return record["kind"] == "imported" and conn.execute(
        "SELECT 1 FROM records WHERE account_id = ? AND kind = 'imported'", (account_id,)).fetchone()


def _drop_unfinished(conn, account_id, set_id):
    row = conn.execute("SELECT set_json FROM unfinished_sets WHERE account_id = ?", (account_id,)).fetchone()
    if row is not None and json.loads(row["set_json"]).get("set_id") == set_id:
        conn.execute("DELETE FROM unfinished_sets WHERE account_id = ?", (account_id,))


def _compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def save_unfinished(conn, account_id, value, now):
    """Replace the Learner's unfinished Set (the newest one wins), or clear it when value is None.

    The Set is the page's own object. It is checked only for a string set_id and a size of at
    most 16 KB as compact JSON; ValueError otherwise.
    """
    if value is None:
        conn.execute("DELETE FROM unfinished_sets WHERE account_id = ?", (account_id,))
        return
    if not isinstance(value, dict) or not isinstance(value.get("set_id"), str):
        raise ValueError("an unfinished Set is an object with a string set_id")
    text = _compact(value)
    if len(text.encode()) > MAX_UNFINISHED:
        raise ValueError(f"an unfinished Set is at most {MAX_UNFINISHED // 1024} KB")
    conn.execute("INSERT INTO unfinished_sets (account_id, set_json, saved_at) VALUES (?, ?, ?) "
                 "ON CONFLICT (account_id) DO UPDATE SET set_json = excluded.set_json, "
                 "saved_at = excluded.saved_at",
                 (account_id, text, int(now)))


def unfinished_set(conn, account_id):
    """The Learner's unfinished Set as the device sent it, or None."""
    row = conn.execute("SELECT set_json FROM unfinished_sets WHERE account_id = ?",
                       (account_id,)).fetchone()
    return None if row is None else json.loads(row["set_json"])


def learner_records(conn, account_id):
    """Every record a Learner has, in arrival (seq) order, each with seq and received_at added."""
    rows = conn.execute("SELECT record, seq, received_at FROM records WHERE account_id = ? ORDER BY seq",
                        (account_id,)).fetchall()
    return [{**json.loads(row["record"]), "seq": row["seq"], "received_at": iso_time(row["received_at"])}
            for row in rows]


# Routes

@route("GET", "/api/records")
@auth.require("learner")
def get_records(req):
    conn = req.db
    account_id = req.account["id"]
    return json_response({"records": learner_records(conn, account_id),
                          "unfinished": unfinished_set(conn, account_id)})


@route("POST", "/api/records")
@auth.require("learner")
def post_records(req):
    body = req.json()
    records = body.get("records") if isinstance(body, dict) else None
    if not isinstance(records, list):
        raise HTTPError(400, "send {\"records\": [...]}")
    if len(records) > MAX_RECORDS:
        raise HTTPError(400, f"send at most {MAX_RECORDS} records at a time")
    try:
        stored, skipped = store_records(req.db, req.account["id"], records, req.now())
    except RecordError as e:
        return json_response({"error": "bad-record", "index": e.index}, 400)
    return json_response({"stored": stored, "skipped": skipped})


@route("POST", "/api/unfinished")
@auth.require("learner")
def post_unfinished(req):
    body = req.json()
    if not isinstance(body, dict) or "set" not in body:
        raise HTTPError(400, "bad-set")
    try:
        save_unfinished(req.db, req.account["id"], body["set"], req.now())
    except ValueError:
        raise HTTPError(400, "bad-set") from None
    return Response(204)
