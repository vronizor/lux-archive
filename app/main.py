import csv
import io
import os
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape
from PIL import Image, ImageOps

from . import db, seasons, stats
from .db import STAGES, get_db, now

APP_NAME = os.environ.get("APP_NAME", "Lux Archive")
TRUTHY = ("1", "on", "true", "yes", "y")


def when(roll, short=False):
    text = escape(seasons.span(roll, short))
    if roll["date_tbc"]:
        text += Markup(' <span class="tbc" title="Year to be confirmed">TBC</span>')
    return Markup(text)

HERE = Path(__file__).parent

app = FastAPI(title=APP_NAME, docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = Jinja2Templates(directory=HERE / "templates")
templates.env.globals.update(
    app_name=APP_NAME,
    seasons=seasons.SEASONS,
    span=seasons.span,
    when=when,
    stages=STAGES,
    stage_state=db.stage_state,
    is_done=db.is_done,
    stage_label=stats.STAGE_LABEL,
)

EXPORT_COLS = [
    "id", "start_year", "start_season", "end_year", "end_season", "date_tbc", "contents", "binder", "sleeve",
    "stock", "camera", "scan_ref", "notes", "photo", "filed_at", "photographed_at",
    "photographed_skipped", "scanned_at", "linked_at", "created_at", "updated_at",
]

FILTERS = {
    "all": ("All", "1=1"),
    "todo": ("Not done", "NOT (filed_at IS NOT NULL AND photographed_at IS NOT NULL AND scanned_at IS NOT NULL AND linked_at IS NOT NULL)"),
    "need-photo": ("To photograph", "filed_at IS NOT NULL AND photographed_at IS NULL"),
    "need-scan": ("To scan", "scanned_at IS NULL"),
    "need-link": ("To link", "scanned_at IS NOT NULL AND linked_at IS NULL"),
    "done": ("Done", "filed_at IS NOT NULL AND photographed_at IS NOT NULL AND scanned_at IS NOT NULL AND linked_at IS NOT NULL"),
    "tbc": ("Year TBC", "date_tbc=1"),
}


@app.on_event("startup")
def startup():
    db.init()


def render(request, name, **ctx):
    return templates.TemplateResponse(request, name, ctx)


def fetch_roll(conn, roll_id):
    row = conn.execute("SELECT * FROM rolls WHERE id=?", (roll_id.upper(),)).fetchone()
    if not row:
        raise HTTPException(404, "No such roll")
    return row


def distinct(conn, col):
    rows = conn.execute(
        f"SELECT {col}, COUNT(*) c FROM rolls WHERE {col} != '' GROUP BY {col} ORDER BY c DESC LIMIT 30"
    ).fetchall()
    return [r[col] for r in rows]


def clean_fields(form):
    def intval(v):
        v = (v or "").strip()
        return int(v) if v.isdigit() else None

    start_year, end_year = intval(form.get("start_year")), intval(form.get("end_year"))
    start_season = seasons.norm_season(form.get("start_season")) if start_year else None
    end_season = seasons.norm_season(form.get("end_season")) if end_year else None
    return {
        "start_year": start_year,
        "start_season": start_season,
        "end_year": end_year,
        "end_season": end_season,
        "date_tbc": int(str(form.get("date_tbc") or "").strip().lower() in TRUTHY),
        "sort_key": seasons.sort_key(start_year, start_season),
        "contents": (form.get("contents") or "").strip(),
        "binder": (form.get("binder") or "").strip(),
        "sleeve": intval(form.get("sleeve")),
        "stock": (form.get("stock") or "").strip(),
        "camera": (form.get("camera") or "").strip(),
        "scan_ref": (form.get("scan_ref") or "").strip(),
        "notes": (form.get("notes") or "").strip(),
    }


def insert_roll(conn, num, fields, filed=True, ts=None):
    ts = ts or now()
    roll_id = db.format_id(num)
    cols = ["id", "num", *fields.keys(), "created_at", "updated_at", "filed_at"]
    vals = [roll_id, num, *fields.values(), ts, ts, ts if filed else None]
    conn.execute(f"INSERT INTO rolls({','.join(cols)}) VALUES({','.join('?' * len(cols))})", vals)
    db.mark_issued(conn, num)
    db.log(conn, roll_id, "filed" if filed else "created", ts)
    return roll_id


@app.get("/", response_class=HTMLResponse)
def home(request: Request, conn=Depends(get_db)):
    rolls = conn.execute("SELECT * FROM rolls").fetchall()
    events = conn.execute("SELECT * FROM events ORDER BY ts").fetchall()
    groups = stats.sessions(events)
    return render(
        request, "home.html",
        counts=stats.counts(rolls),
        chart=Markup(stats.burnup_svg(rolls)),
        last=stats.describe(groups[-1] if groups else None),
        strip=stats.strip(groups),
        n_sessions=len(groups),
        recent=conn.execute("SELECT * FROM rolls ORDER BY updated_at DESC LIMIT 5").fetchall(),
    )


@app.get("/add", response_class=HTMLResponse)
def add_form(request: Request, saved: str = "", error: str = "", conn=Depends(get_db)):
    last = conn.execute("SELECT * FROM rolls ORDER BY num DESC LIMIT 1").fetchone()
    defaults = {
        "id": db.format_id(db.next_num(conn)),
        "start_year": (last["end_year"] or last["start_year"]) if last else "",
        "start_season": (last["end_season"] or last["start_season"]) if last else "",
        "binder": last["binder"] if last else "B1",
        "sleeve": (last["sleeve"] + 1) if last and last["sleeve"] else 1,
        "camera": last["camera"] if last else "",
    }
    return render(
        request, "add.html", d=defaults, saved=saved, error=error,
        stocks=distinct(conn, "stock"), cameras=distinct(conn, "camera"), binders=distinct(conn, "binder"),
    )


@app.post("/rolls")
async def create_roll(request: Request, conn=Depends(get_db)):
    form = await request.form()
    num = db.parse_id(form.get("id")) or db.next_num(conn)
    if conn.execute("SELECT 1 FROM rolls WHERE num=?", (num,)).fetchone():
        return RedirectResponse(f"/add?error={db.format_id(num)}+already+exists", 303)
    roll_id = insert_roll(conn, num, clean_fields(form), filed=bool(form.get("filed")))
    upload = form.get("photo")
    if upload is not None and getattr(upload, "filename", ""):
        save_photo(conn, roll_id, await upload.read())
    if form.get("action") == "open":
        return RedirectResponse(f"/rolls/{roll_id}", 303)
    return RedirectResponse(f"/add?saved={roll_id}", 303)


@app.get("/rolls", response_class=HTMLResponse)
def index(request: Request, sort: str = "id", stage: str = "all", q: str = "", conn=Depends(get_db)):
    label, where = FILTERS.get(stage, FILTERS["all"])
    params = []
    if q.strip():
        like = f"%{q.strip()}%"
        where += " AND (id LIKE ? OR contents LIKE ? OR notes LIKE ? OR stock LIKE ? OR camera LIKE ? OR scan_ref LIKE ? OR binder LIKE ?)"
        params = [like] * 7
    order = "sort_key IS NULL, sort_key, num" if sort == "date" else "num"
    rows = conn.execute(f"SELECT * FROM rolls WHERE {where} ORDER BY {order}", params).fetchall()
    all_rolls = conn.execute("SELECT * FROM rolls").fetchall()
    return render(
        request, "index.html", rolls=rows, sort=sort, stage=stage, q=q,
        filters=FILTERS, counts=stats.counts(all_rolls),
    )


@app.get("/rolls/{roll_id}", response_class=HTMLResponse)
def roll_page(request: Request, roll_id: str, saved: int = 0, conn=Depends(get_db)):
    r = fetch_roll(conn, roll_id)
    nav = conn.execute(
        "SELECT (SELECT id FROM rolls WHERE num<? ORDER BY num DESC LIMIT 1) AS prev, "
        "(SELECT id FROM rolls WHERE num>? ORDER BY num LIMIT 1) AS next",
        (r["num"], r["num"]),
    ).fetchone()
    return render(
        request, "roll.html", r=r, d=dict(r), nav=nav, saved=saved,
        stocks=distinct(conn, "stock"), cameras=distinct(conn, "camera"), binders=distinct(conn, "binder"),
    )


@app.post("/rolls/{roll_id}")
async def update_roll(request: Request, roll_id: str, conn=Depends(get_db)):
    r = fetch_roll(conn, roll_id)
    fields = clean_fields(await request.form())
    sets = ", ".join(f"{k}=?" for k in fields)
    conn.execute(f"UPDATE rolls SET {sets}, updated_at=? WHERE id=?", [*fields.values(), now(), r["id"]])
    db.log(conn, r["id"], "edit")
    return RedirectResponse(f"/rolls/{r['id']}?saved=1", 303)


@app.post("/rolls/{roll_id}/delete")
def delete_roll(roll_id: str, conn=Depends(get_db)):
    r = fetch_roll(conn, roll_id)
    conn.execute("DELETE FROM rolls WHERE id=?", (r["id"],))
    conn.execute("DELETE FROM events WHERE roll_id=?", (r["id"],))
    if r["photo"]:
        (db.PHOTO_DIR / r["photo"]).unlink(missing_ok=True)
    return RedirectResponse("/rolls", 303)


def save_photo(conn, roll_id, data):
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    img.thumbnail((1600, 1600))
    name = f"{roll_id}.jpg"
    img.save(db.PHOTO_DIR / name, "JPEG", quality=82, optimize=True)
    conn.execute("UPDATE rolls SET photo=?, updated_at=? WHERE id=?", (name, now(), roll_id))
    row = conn.execute("SELECT photographed_at, photographed_skipped FROM rolls WHERE id=?", (roll_id,)).fetchone()
    if not row["photographed_at"] or row["photographed_skipped"]:
        db.set_stage(conn, roll_id, "photographed", "done")


@app.post("/rolls/{roll_id}/photo")
async def upload_photo(roll_id: str, photo: UploadFile = File(...), conn=Depends(get_db)):
    r = fetch_roll(conn, roll_id)
    try:
        save_photo(conn, r["id"], await photo.read())
    except Exception:
        raise HTTPException(400, "Could not read that image")
    return RedirectResponse(f"/rolls/{r['id']}", 303)


@app.get("/photos/{name}")
def photo_file(name: str):
    path = (db.PHOTO_DIR / name).resolve()
    if path.parent != db.PHOTO_DIR.resolve() or not path.exists():
        raise HTTPException(404)
    return FileResponse(path, headers={"Cache-Control": "no-cache"})


def stage_json(r):
    return {"id": r["id"], "done": db.is_done(r), "stages": {s: db.stage_state(r, s) for s in STAGES}}


@app.post("/api/rolls/{roll_id}/stage")
async def api_stage(roll_id: str, request: Request, conn=Depends(get_db)):
    body = await request.json()
    r = fetch_roll(conn, roll_id)
    try:
        db.set_stage(conn, r["id"], body.get("stage"), body.get("value"))
    except ValueError:
        raise HTTPException(400, "Unknown stage")
    return JSONResponse(stage_json(fetch_roll(conn, r["id"])))


@app.post("/api/bulk")
async def api_bulk(request: Request, conn=Depends(get_db)):
    body = await request.json()
    stage, value = body.get("stage"), body.get("value")
    if stage not in STAGES:
        raise HTTPException(400, "Unknown stage")
    target = "todo" if value is False else "skip" if value == "skip" else "done"
    out = []
    for roll_id in body.get("ids", []):
        r = conn.execute("SELECT * FROM rolls WHERE id=?", (roll_id,)).fetchone()
        if not r or db.stage_state(r, stage) == target:
            continue
        db.set_stage(conn, r["id"], stage, value)
        out.append(stage_json(fetch_roll(conn, r["id"])))
    return JSONResponse({"updated": out})


@app.get("/export.csv")
def export_csv(conn=Depends(get_db)):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(EXPORT_COLS)
    for r in conn.execute("SELECT * FROM rolls ORDER BY num"):
        w.writerow([r[c] if r[c] is not None else "" for c in EXPORT_COLS])
    return Response(
        buf.getvalue(), media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="lux-archive-rolls.csv"'},
    )


@app.get("/import", response_class=HTMLResponse)
def import_form(request: Request):
    return render(request, "import.html", result=None)


def import_rows(conn, rows):
    added, skipped, errors = [], [], []
    for i, row in enumerate(rows, start=2):
        row = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}
        num = db.parse_id(row.get("id"))
        if not num:
            errors.append(f"line {i}: missing or bad id")
            continue
        if conn.execute("SELECT 1 FROM rolls WHERE num=?", (num,)).fetchone():
            skipped.append(db.format_id(num))
            continue
        if "start_year" in row:
            form = row
        else:
            sy, ss = seasons.parse(row.get("start"))
            ey, es = seasons.parse(row.get("end"))
            unsure = "?" in row.get("start", "") + row.get("end", "") or row.get("tbc", "").lower() in TRUTHY
            form = {
                **row, "start_year": str(sy or ""), "start_season": ss, "end_year": str(ey or ""), "end_season": es,
                "date_tbc": "1" if unsure else "",
            }
        fields = clean_fields(form)
        is_filed = bool(row.get("filed_at")) if "filed_at" in row else True
        filed = row.get("filed_at") or now()
        roll_id = insert_roll(conn, num, fields, filed=is_filed, ts=row.get("created_at") or filed)
        if is_filed and row.get("filed_at"):
            conn.execute("UPDATE rolls SET filed_at=? WHERE id=?", (row["filed_at"], roll_id))
        updates = {}
        for s in ("photographed", "scanned", "linked"):
            val = row.get(f"{s}_at") or ("" if f"{s}_at" in row else row.get(s, ""))
            if val and val.lower() not in ("0", "no", "n", "false"):
                updates[f"{s}_at"] = val if "T" in val else filed
        if row.get("photographed_skipped") in ("1", "true", "yes"):
            updates["photographed_skipped"] = 1
        if row.get("photo") and (db.PHOTO_DIR / row["photo"]).exists():
            updates["photo"] = row["photo"]
        if updates:
            conn.execute(
                f"UPDATE rolls SET {', '.join(f'{k}=?' for k in updates)} WHERE id=?",
                [*updates.values(), roll_id],
            )
        added.append(roll_id)
    return added, skipped, errors


@app.post("/import", response_class=HTMLResponse)
async def import_csv(request: Request, file: UploadFile = File(...), conn=Depends(get_db)):
    text = (await file.read()).decode("utf-8-sig")
    dialect = csv.Sniffer().sniff(text.splitlines()[0], delimiters=",;\t") if text.strip() else csv.excel
    added, skipped, errors = import_rows(conn, csv.DictReader(io.StringIO(text), dialect=dialect))
    return render(request, "import.html", result={"added": added, "skipped": skipped, "errors": errors})
