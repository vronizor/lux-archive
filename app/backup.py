import csv
import json
import os
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

from PIL import Image

from . import contact, db
from .main import EXPORT_COLS, import_rows, write_positive


BACKUP_MAX = 3200
PORTABLE = ("name", "prefix", "catalog", "binder")
NOTES = ("docs.md", "field.md")


def sync(src_dir, dst_dir, shrink=False):
    dst_dir.mkdir(parents=True, exist_ok=True)
    keep = set()
    for src in src_dir.glob("*.jpg"):
        if src.stem.endswith(db.DERIVED):
            continue
        keep.add(src.name)
        dst = dst_dir / src.name
        mtime = int(src.stat().st_mtime)
        if dst.exists() and int(dst.stat().st_mtime) == mtime:
            continue
        with Image.open(src) as img:
            big = shrink and max(img.size) > BACKUP_MAX
            if big:
                small = img.convert("RGB")
                small.thumbnail((BACKUP_MAX, BACKUP_MAX), Image.LANCZOS)
                dst.write_bytes(contact.to_jpeg(small, 85))
        if not big:
            shutil.copy2(src, dst)
        os.utime(dst, (mtime, mtime))
    for old in dst_dir.glob("*.jpg"):
        if old.name not in keep:
            old.unlink()


def export(target, originals=False):
    target = Path(target)
    target.mkdir(parents=True, exist_ok=True)
    conn = db.connect()
    with open(target / "rolls.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(EXPORT_COLS)
        for r in conn.execute("SELECT * FROM rolls ORDER BY num"):
            w.writerow([r[c] if r[c] is not None else "" for c in EXPORT_COLS])
    with open(target / "events.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ts", "roll_id", "kind"])
        for e in conn.execute("SELECT ts, roll_id, kind FROM events ORDER BY id"):
            w.writerow(list(e))
    conn.close()
    (target / "settings.json").write_text(
        json.dumps({k: db.setting(k) for k in PORTABLE}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    for name in NOTES:
        src = db.DATA_DIR / name
        if src.exists():
            (target / "notes").mkdir(exist_ok=True)
            shutil.copy2(src, target / "notes" / name)
    sync(db.PHOTO_DIR, target / "photos", shrink=True)
    if originals:
        sync(db.ORIG_DIR, target / "photos" / "originals")
    print(f"exported to {target}")


def make_zip(path):
    with tempfile.TemporaryDirectory() as tmp:
        export(tmp)
        with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as z:
            for f in sorted(Path(tmp).rglob("*")):
                if f.is_file():
                    z.write(f, f.relative_to(tmp).as_posix())


def restore(source):
    source = Path(source).expanduser()
    if source.is_file() and source.suffix.lower() == ".zip":
        with tempfile.TemporaryDirectory() as tmp:
            with zipfile.ZipFile(source) as z:
                z.extractall(tmp)
            return restore(tmp)
    if not (source / "rolls.csv").exists():
        raise RuntimeError(f"no rolls.csv in {source}")
    db.init()
    conn = db.connect()
    if conn.execute("SELECT COUNT(*) FROM rolls").fetchone()[0]:
        conn.close()
        raise RuntimeError("refusing to restore: the database already has rolls")
    with open(source / "rolls.csv", newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    saved = {}
    if (source / "settings.json").exists():
        saved = {k: v for k, v in json.loads((source / "settings.json").read_text(encoding="utf-8")).items() if k in PORTABLE}
    elif rows:
        m = re.match(r"[A-Za-z]{1,4}", rows[0].get("id") or "")
        if m:
            saved = {"prefix": m.group().upper()}
    db.save_settings(conn, saved)
    for src in (source / "photos").glob("*.jpg"):
        shutil.copy2(src, db.PHOTO_DIR / src.name)
    for src in (source / "photos" / "originals").glob("*.jpg"):
        shutil.copy2(src, db.ORIG_DIR / src.name)
    for name in NOTES:
        if (source / "notes" / name).exists():
            shutil.copy2(source / "notes" / name, db.DATA_DIR / name)
    added, skipped, errors = import_rows(conn, rows)
    for r in conn.execute("SELECT id, process, photo FROM rolls WHERE photo IS NOT NULL AND photo != ''").fetchall():
        for n in db.sheet_nums(r["photo"]):
            if db.sheet_paths(r["id"], n)["preview"].exists():
                write_positive(r["id"], n, r["process"])
    conn.execute("DELETE FROM events")
    events = source / "events.csv"
    if events.exists():
        with open(events, newline="", encoding="utf-8-sig") as f:
            conn.executemany(
                "INSERT INTO events(ts, roll_id, kind) VALUES(?,?,?)",
                [(e["ts"], e["roll_id"], e["kind"]) for e in csv.DictReader(f)],
            )
    conn.commit()
    conn.close()
    print(f"restored {len(added)} rolls; {len(errors)} errors")
    for e in errors:
        print(" ", e)
    return added, errors


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in ("export", "restore"):
        sys.exit("usage: python -m app.backup export|restore <dir>")
    try:
        (export if sys.argv[1] == "export" else restore)(sys.argv[2])
    except RuntimeError as e:
        sys.exit(str(e))
