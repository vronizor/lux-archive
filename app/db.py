import os
import sqlite3
from datetime import datetime
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
DB_PATH = DATA_DIR / "lux.db"
PHOTO_DIR = DATA_DIR / "photos"

STAGES = ["filed", "photographed", "scanned", "linked"]

FIELDS = [
    "start_year", "start_season", "end_year", "end_season", "date_tbc", "contents",
    "binder", "sleeve", "stock", "process", "camera", "scan_ref", "notes",
]

ADDED_COLUMNS = {"date_tbc": "INTEGER DEFAULT 0", "process": "TEXT"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS rolls (
    id TEXT PRIMARY KEY,
    num INTEGER UNIQUE NOT NULL,
    start_year INTEGER, start_season TEXT,
    end_year INTEGER, end_season TEXT,
    date_tbc INTEGER DEFAULT 0,
    sort_key INTEGER,
    contents TEXT DEFAULT '',
    binder TEXT DEFAULT '', sleeve INTEGER,
    stock TEXT DEFAULT '', process TEXT, camera TEXT DEFAULT '',
    scan_ref TEXT DEFAULT '', notes TEXT DEFAULT '',
    photo TEXT,
    filed_at TEXT, photographed_at TEXT, photographed_skipped INTEGER DEFAULT 0,
    scanned_at TEXT, linked_at TEXT,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    roll_id TEXT NOT NULL,
    kind TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE INDEX IF NOT EXISTS events_ts ON events(ts);
"""


def now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def connect():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PHOTO_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init():
    with connect() as conn:
        conn.executescript(SCHEMA)
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(rolls)")}
        for col, decl in ADDED_COLUMNS.items():
            if col not in cols:
                conn.execute(f"ALTER TABLE rolls ADD COLUMN {col} {decl}")


def get_db():
    conn = connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def format_id(num):
    return f"V{num:03d}"


def parse_id(text):
    text = (text or "").strip().upper()
    if text.startswith("V"):
        text = text[1:]
    return int(text) if text.isdigit() and int(text) > 0 else None


def next_num(conn):
    row = conn.execute("SELECT COALESCE(MAX(num), 0) AS m FROM rolls").fetchone()
    issued = conn.execute("SELECT value FROM meta WHERE key='last_issued'").fetchone()
    return max(row["m"], int(issued["value"]) if issued else 0) + 1


def mark_issued(conn, num):
    conn.execute(
        "INSERT INTO meta(key, value) VALUES('last_issued', ?) "
        "ON CONFLICT(key) DO UPDATE SET value=MAX(CAST(value AS INTEGER), excluded.value)",
        (str(num),),
    )


def log(conn, roll_id, kind, ts=None):
    conn.execute("INSERT INTO events(ts, roll_id, kind) VALUES(?,?,?)", (ts or now(), roll_id, kind))


def is_done(r):
    return bool(r["filed_at"] and r["photographed_at"] and r["scanned_at"] and r["linked_at"])


def stage_state(r, stage):
    if stage == "photographed" and r["photographed_skipped"]:
        return "skip"
    return "done" if r[f"{stage}_at"] else "todo"


def set_stage(conn, roll_id, stage, value):
    ts = now()
    if stage not in STAGES:
        raise ValueError(stage)
    if value in (True, "done"):
        conn.execute(
            f"UPDATE rolls SET {stage}_at=COALESCE({stage}_at, ?), updated_at=?"
            + (", photographed_skipped=0" if stage == "photographed" else "")
            + " WHERE id=?",
            (ts, ts, roll_id),
        )
        log(conn, roll_id, stage, ts)
    elif value == "skip" and stage == "photographed":
        conn.execute(
            "UPDATE rolls SET photographed_at=?, photographed_skipped=1, updated_at=? WHERE id=?",
            (ts, ts, roll_id),
        )
        log(conn, roll_id, "photographed", ts)
    else:
        conn.execute(
            f"UPDATE rolls SET {stage}_at=NULL, updated_at=?"
            + (", photographed_skipped=0" if stage == "photographed" else "")
            + " WHERE id=?",
            (ts, roll_id),
        )
        log(conn, roll_id, "edit", ts)
