import csv
import shutil
import sys
from pathlib import Path

from . import db
from .main import EXPORT_COLS, import_rows


def export(target):
    target = Path(target)
    photos = target / "photos"
    photos.mkdir(parents=True, exist_ok=True)
    conn = db.connect()
    with open(target / "rolls.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(EXPORT_COLS)
        for r in conn.execute("SELECT * FROM rolls ORDER BY num"):
            w.writerow([r[c] if r[c] is not None else "" for c in EXPORT_COLS])
    with open(target / "events.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ts", "roll_id", "kind"])
        for e in conn.execute("SELECT ts, roll_id, kind FROM events ORDER BY id"):
            w.writerow(list(e))
    keep = set()
    for src in db.PHOTO_DIR.glob("*.jpg"):
        keep.add(src.name)
        dst = photos / src.name
        if not dst.exists() or (dst.stat().st_size, int(dst.stat().st_mtime)) != (src.stat().st_size, int(src.stat().st_mtime)):
            shutil.copy2(src, dst)
    for old in photos.glob("*.jpg"):
        if old.name not in keep:
            old.unlink()
    conn.close()
    print(f"exported to {target}")


def restore(source):
    source = Path(source)
    db.init()
    conn = db.connect()
    if conn.execute("SELECT COUNT(*) FROM rolls").fetchone()[0]:
        sys.exit("refusing to restore: the database already has rolls")
    for src in (source / "photos").glob("*.jpg"):
        shutil.copy2(src, db.PHOTO_DIR / src.name)
    with open(source / "rolls.csv", newline="") as f:
        added, skipped, errors = import_rows(conn, csv.DictReader(f))
    conn.execute("DELETE FROM events")
    events = source / "events.csv"
    if events.exists():
        with open(events, newline="") as f:
            conn.executemany(
                "INSERT INTO events(ts, roll_id, kind) VALUES(?,?,?)",
                [(e["ts"], e["roll_id"], e["kind"]) for e in csv.DictReader(f)],
            )
    conn.commit()
    conn.close()
    print(f"restored {len(added)} rolls; {len(errors)} errors")
    for e in errors:
        print(" ", e)


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in ("export", "restore"):
        sys.exit("usage: python -m app.backup export|restore <dir>")
    (export if sys.argv[1] == "export" else restore)(sys.argv[2])
