import csv
from datetime import datetime
import hashlib
import io
import os
from pathlib import Path
from urllib.parse import urlencode

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape
import markdown
from PIL import Image, ImageOps

from . import contact, db, frames, seasons, stats
from .db import ARCHIVE_SQL, LIFE, STAGES, get_db, now

APP_NAME = os.environ.get("APP_NAME", "Lux Archive")
TRUTHY = ("1", "on", "true", "yes", "y")
PREVIEW_MAX = int(os.environ.get("LUX_PHOTO_MAX", "3200"))


def when(roll, short=False):
    text = escape(seasons.span(roll, short))
    if roll["date_tbc"]:
        text += Markup(' <span class="tbc" title="Year to be confirmed">TBC</span>')
    return Markup(text)

HERE = Path(__file__).parent

app = FastAPI(title=APP_NAME, docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = Jinja2Templates(directory=HERE / "templates")
templates.env.filters["fmtdate"] = lambda iso: datetime.fromisoformat(iso).strftime("%-d %b") if iso else ""
templates.env.globals.update(
    app_name=APP_NAME,
    seasons=seasons.SEASONS,
    processes=seasons.PROCESSES,
    span=seasons.span,
    when=when,
    stages=STAGES,
    stage_state=db.stage_state,
    is_done=db.is_done,
    stage_label=stats.STAGE_LABEL,
    phase=db.phase,
    phase_label=stats.PHASE_LABEL,
    scan_summary=frames.summary,
    asset_v=hashlib.sha256(b"".join(p.read_bytes() for p in sorted((HERE / "static").iterdir()))).hexdigest()[:10],
)

EXPORT_COLS = [
    "id", "start_year", "start_season", "end_year", "end_season", "date_tbc", "contents", "binder", "sleeve",
    "stock", "process", "camera", "scan_ref", "notes", "photo", "filed_at", "photographed_at",
    "photographed_skipped", "scanned_at", "linked_at", "picks", "scans", "picked_at",
    "ei", "lab", "loaded_at", "shot_at", "sent_at", "back_at", "created_at", "updated_at",
]

DONE_SQL = "filed_at IS NOT NULL AND photographed_at IS NOT NULL AND linked_at IS NOT NULL AND picked_at IS NOT NULL"
FILTERS = {
    "all": ("All", "1=1"),
    "todo": ("Not done", f"{ARCHIVE_SQL} AND NOT ({DONE_SQL})"),
    "need-photo": ("Contact sheet", f"{ARCHIVE_SQL} AND photographed_at IS NULL"),
    "need-link": ("To link", "photographed_at IS NOT NULL AND linked_at IS NULL"),
    "need-review": ("To review", "photographed_at IS NOT NULL AND picked_at IS NULL"),
    "need-scan": ("To scan", "picks NOT IN ('', 'none') AND scanned_at IS NULL"),
    "done": ("Done", DONE_SQL),
    "tbc": ("Year TBC", "date_tbc=1"),
    "out": ("Not back yet", f"NOT {ARCHIVE_SQL}"),
}


@app.on_event("startup")
def startup():
    db.init()


def shooting():
    with db.connect() as conn:
        return conn.execute("SELECT 1 FROM rolls WHERE loaded_at IS NOT NULL LIMIT 1").fetchone() is not None


def render(request, name, **ctx):
    ctx.setdefault("shooting", shooting())
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

    extra = {}
    if "ei" in form:
        extra["ei"] = intval(form.get("ei"))
    if "lab" in form:
        extra["lab"] = (form.get("lab") or "").strip()

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
        "process": seasons.norm_process(form.get("process")),
        "camera": (form.get("camera") or "").strip(),
        "scan_ref": (form.get("scan_ref") or "").strip(),
        "notes": (form.get("notes") or "").strip(),
        **extra,
    }


def insert_roll(conn, num, fields, filed=True, ts=None, event=None):
    ts = ts or now()
    roll_id = db.format_id(num)
    cols = ["id", "num", *fields.keys(), "created_at", "updated_at", "filed_at"]
    vals = [roll_id, num, *fields.values(), ts, ts, ts if filed else None]
    conn.execute(f"INSERT INTO rolls({','.join(cols)}) VALUES({','.join('?' * len(cols))})", vals)
    db.mark_issued(conn, num)
    db.log(conn, roll_id, event or ("filed" if filed else "created"), ts)
    return roll_id


def in_flight(conn):
    out = {p: [] for p in ("camera", "batch", "lab")}
    for r in conn.execute(f"SELECT * FROM rolls WHERE NOT {ARCHIVE_SQL} ORDER BY num"):
        out[db.phase(r)].append(r)
    return out


@app.get("/", response_class=HTMLResponse)
def home(request: Request, conn=Depends(get_db)):
    rolls = conn.execute(f"SELECT * FROM rolls WHERE {ARCHIVE_SQL}").fetchall()
    events = conn.execute("SELECT * FROM events ORDER BY ts").fetchall()
    groups = stats.sessions([e for e in events if e["kind"] not in LIFE])
    return render(
        request, "home.html",
        counts=stats.counts(rolls),
        flight=in_flight(conn),
        labs=distinct(conn, "lab"),
        chart=Markup(stats.burnup_svg(rolls)),
        last=stats.describe(groups[-1] if groups else None),
        strip=stats.strip(groups),
        n_sessions=len(groups),
        recent=conn.execute("SELECT * FROM rolls ORDER BY updated_at DESC LIMIT 5").fetchall(),
    )


@app.get("/add", response_class=HTMLResponse)
def add_form(request: Request, saved: str = "", error: str = "", conn=Depends(get_db)):
    last = conn.execute("SELECT * FROM rolls WHERE filed_at IS NOT NULL ORDER BY num DESC LIMIT 1").fetchone()
    defaults = {
        "id": db.format_id(db.next_num(conn)),
        "start_year": (last["end_year"] or last["start_year"]) if last else "",
        "start_season": (last["end_season"] or last["start_season"]) if last else "",
        "binder": last["binder"] if last else "B1",
        "sleeve": (last["sleeve"] + 1) if last and last["sleeve"] else 1,
        "camera": last["camera"] if last else "",
        "process": last["process"] if last else None,
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
        try:
            save_photo(conn, roll_id, await upload.read())
        except Exception:
            return RedirectResponse(f"/rolls/{roll_id}?error=photo", 303)
    if form.get("action") == "open":
        return RedirectResponse(f"/rolls/{roll_id}", 303)
    return RedirectResponse(f"/add?saved={roll_id}", 303)


@app.get("/load", response_class=HTMLResponse)
def load_form(request: Request, saved: str = "", conn=Depends(get_db)):
    last = conn.execute("SELECT camera FROM rolls WHERE loaded_at IS NOT NULL OR shot_at IS NOT NULL ORDER BY num DESC LIMIT 1").fetchone()
    cameras = distinct(conn, "camera")
    camera = last["camera"] if last else (cameras[0] if cameras else "")
    return render(
        request, "load.html", saved=saved, camera=camera, next_id=db.format_id(db.next_num(conn)),
        stocks=distinct(conn, "stock"), cameras=cameras,
    )


@app.post("/load")
async def load_roll(request: Request, conn=Depends(get_db)):
    form = await request.form()
    ts = now()
    year, season = seasons.from_date(datetime.fromisoformat(ts).date())
    stock = (form.get("stock") or "").strip()
    guess = conn.execute(
        "SELECT process FROM rolls WHERE stock=? AND process IS NOT NULL GROUP BY process ORDER BY COUNT(*) DESC LIMIT 1",
        (stock,),
    ).fetchone() if stock else None
    ei = (form.get("ei") or "").strip()
    fields = {
        "start_year": year, "start_season": season, "sort_key": seasons.sort_key(year, season),
        "stock": stock, "camera": (form.get("camera") or "").strip(),
        "ei": int(ei) if ei.isdigit() else None,
        "process": seasons.norm_process(form.get("process")) or (guess["process"] if guess else None),
    }
    unloaded = bool(form.get("unloaded"))
    if unloaded:
        fields.update(end_year=year, end_season=season, shot_at=ts)
    else:
        fields["loaded_at"] = ts
    roll_id = insert_roll(conn, db.next_num(conn), fields, filed=False, ts=ts, event="shot" if unloaded else "loaded")
    return RedirectResponse(f"/load?saved={roll_id}", 303)


@app.post("/rolls/{roll_id}/life/{step}")
async def life_step(request: Request, roll_id: str, step: str, conn=Depends(get_db)):
    r = fetch_roll(conn, roll_id)
    form = await request.form()
    try:
        db.set_life(conn, r["id"], step, lab=(form.get("lab") or "").strip() if "lab" in form else None)
    except ValueError:
        raise HTTPException(400, "Unknown step")
    target = form.get("next") or "/"
    return RedirectResponse(target if target.startswith("/") and not target.startswith("//") else "/", 303)


@app.post("/rolls/{roll_id}/note")
async def add_note(request: Request, roll_id: str, conn=Depends(get_db)):
    r = fetch_roll(conn, roll_id)
    form = await request.form()
    note = (form.get("note") or "").strip()
    if note:
        contents = ", ".join(x for x in (r["contents"], note) if x)
        conn.execute("UPDATE rolls SET contents=?, updated_at=? WHERE id=?", (contents, now(), r["id"]))
        db.log(conn, r["id"], "edit")
    return RedirectResponse("/", 303)


@app.post("/batch/send")
async def send_batch(request: Request, conn=Depends(get_db)):
    form = await request.form()
    lab = (form.get("lab") or "").strip()
    for r in in_flight(conn)["batch"]:
        db.set_life(conn, r["id"], "sent", lab=lab)
    return RedirectResponse("/", 303)


@app.post("/batch/back")
def batch_back(conn=Depends(get_db)):
    for r in in_flight(conn)["lab"]:
        db.set_life(conn, r["id"], "back")
    return RedirectResponse("/", 303)


NONE = "_none"
FACETS = {"process": "Film", "camera": "Camera", "binder": "Binder"}


def facet_value(r, facet):
    return r[facet] or NONE


def year_ok(r, y0, y1):
    if y0 is None and y1 is None:
        return True
    start = r["start_year"]
    if start is None:
        return False
    end = r["end_year"] or start
    return (y1 is None or start <= y1) and (y0 is None or end >= y0)


def to_year(value):
    value = (value or "").strip()
    return int(value) if value.isdigit() else None


@app.get("/rolls", response_class=HTMLResponse)
def index(request: Request, sort: str = "id", dir: str = "asc", stage: str = "all", q: str = "", y0: str = "", y1: str = "", conn=Depends(get_db)):
    sort = sort if sort in ("id", "date") else "id"
    dir = dir if dir in ("asc", "desc") else "asc"
    stage = stage if stage in FILTERS else "all"
    chosen = {f: [v for v in request.query_params.getlist(f) if v] for f in FACETS}
    if chosen["process"] == ["unset"]:
        chosen["process"] = [NONE]
    ys = (to_year(y0), to_year(y1))
    if None not in ys and ys[0] > ys[1]:
        ys = (ys[1], ys[0])

    where, params = FILTERS[stage][1], []
    if q.strip():
        like = f"%{q.strip()}%"
        where += " AND (id LIKE ? OR contents LIKE ? OR notes LIKE ? OR stock LIKE ? OR camera LIKE ? OR scan_ref LIKE ? OR binder LIKE ?)"
        params += [like] * 7
    hits = {r["id"] for r in conn.execute(f"SELECT id FROM rolls WHERE {where}", params)}
    everything = conn.execute("SELECT * FROM rolls ORDER BY num").fetchall()

    def match(r, skip=None):
        return year_ok(r, *ys) and all(
            not chosen[f] or facet_value(r, f) in chosen[f] for f in FACETS if f != skip
        )

    rows = [r for r in everything if r["id"] in hits and match(r)]
    if sort == "date":
        dated = sorted((r for r in rows if r["sort_key"] is not None), key=lambda r: (r["sort_key"], r["num"]), reverse=dir == "desc")
        rows = dated + [r for r in rows if r["sort_key"] is None]
    elif dir == "desc":
        rows.reverse()

    options = {}
    for f in FACETS:
        pool = [r for r in everything if r["id"] in hits and match(r, skip=f)]
        values = list(seasons.PROCESSES) if f == "process" else sorted({r[f] for r in everything if r[f]}, key=str.lower)
        if f == "process" or NONE in chosen[f] or any(not r[f] for r in everything):
            values = values + [NONE]
        options[f] = [(v, sum(1 for r in pool if facet_value(r, f) == v)) for v in values]

    state = {"stage": stage, "sort": sort, "dir": dir, "q": q.strip(), "y0": ys[0] or "", "y1": ys[1] or "", **chosen}

    def link(**changes):
        merged = {**state, **changes}
        pairs = [(k, v) for k, v in merged.items() if k not in FACETS and v not in ("", None)]
        pairs += [(f, v) for f in FACETS for v in merged[f]]
        return "?" + urlencode(pairs)

    def without(facet, value):
        return link(**{facet: [v for v in chosen[facet] if v != value]})

    def sort_link(key):
        return link(sort=key, dir="desc" if sort == key and dir == "asc" else "asc")

    label = lambda f, v: "Not set" if v == NONE else seasons.PROCESSES.get(v, v) if f == "process" else v
    active = sum(len(v) for v in chosen.values()) + (1 if any(ys) else 0)
    return render(
        request, "index.html", rolls=rows, sort=sort, dir=dir, stage=stage, q=q.strip(), ys=ys,
        filters=FILTERS, counts=stats.counts([r for r in everything if match(r)]),
        facets=FACETS, options=options, chosen=chosen, active=active, state=state,
        link=link, without=without, sort_link=sort_link, facet_label=label,
    )


@app.get("/rolls/{roll_id}", response_class=HTMLResponse)
def roll_page(request: Request, roll_id: str, saved: int = 0, error: str = "", conn=Depends(get_db)):
    r = fetch_roll(conn, roll_id)
    if r["photo"] and (db.PHOTO_DIR / r["photo"]).exists() and not photo_paths(r["id"])["positive"].exists():
        write_positive(r["id"], r["process"])
    nav = conn.execute(
        "SELECT (SELECT id FROM rolls WHERE num<? ORDER BY num DESC LIMIT 1) AS prev, "
        "(SELECT id FROM rolls WHERE num>? ORDER BY num LIMIT 1) AS next",
        (r["num"], r["num"]),
    ).fetchone()
    return render(
        request, "roll.html", r=r, d=dict(r), nav=nav, saved=saved, error=error,
        has_original=(db.ORIG_DIR / f"{r['id']}.jpg").exists(),
        stocks=distinct(conn, "stock"), cameras=distinct(conn, "camera"), binders=distinct(conn, "binder"),
    )


@app.post("/rolls/{roll_id}")
async def update_roll(request: Request, roll_id: str, conn=Depends(get_db)):
    r = fetch_roll(conn, roll_id)
    form = await request.form()
    fields = clean_fields(form)
    sets = ", ".join(f"{k}=?" for k in fields)
    conn.execute(f"UPDATE rolls SET {sets}, updated_at=? WHERE id=?", [*fields.values(), now(), r["id"]])
    db.log(conn, r["id"], "edit")
    if r["photo"] and fields["process"] != r["process"]:
        write_positive(r["id"], fields["process"])
    return RedirectResponse(f"/rolls/{r['id']}?saved=1", 303)


@app.post("/rolls/{roll_id}/scans")
async def update_scans(request: Request, roll_id: str, conn=Depends(get_db)):
    r = fetch_roll(conn, roll_id)
    form = await request.form()
    try:
        db.set_scans(conn, r["id"], form.get("picks"), form.get("scans"))
    except ValueError as e:
        return RedirectResponse(f"/rolls/{r['id']}?" + urlencode({"error": str(e)}) + "#scans", 303)
    return RedirectResponse(f"/rolls/{r['id']}?saved=1#scans", 303)


@app.post("/rolls/{roll_id}/delete")
def delete_roll(roll_id: str, conn=Depends(get_db)):
    r = fetch_roll(conn, roll_id)
    conn.execute("DELETE FROM rolls WHERE id=?", (r["id"],))
    conn.execute("DELETE FROM events WHERE roll_id=?", (r["id"],))
    for path in photo_paths(r["id"]).values():
        path.unlink(missing_ok=True)
    return RedirectResponse("/rolls", 303)


def photo_paths(roll_id):
    return {
        "original": db.ORIG_DIR / f"{roll_id}.jpg",
        "preview": db.PHOTO_DIR / f"{roll_id}.jpg",
        "positive": db.PHOTO_DIR / f"{roll_id}_pos.jpg",
    }


def write_positive(roll_id, process):
    paths = photo_paths(roll_id)
    with Image.open(paths["preview"]) as img:
        paths["positive"].write_bytes(contact.to_jpeg(contact.positive(img, process), 85))


def save_photo(conn, roll_id, data):
    paths = photo_paths(roll_id)
    img = Image.open(io.BytesIO(data))
    if img.format == "JPEG":
        paths["original"].write_bytes(data)
    else:
        paths["original"].write_bytes(contact.to_jpeg(ImageOps.exif_transpose(img).convert("RGB"), 95))
    preview = ImageOps.exif_transpose(img).convert("RGB")
    preview.thumbnail((PREVIEW_MAX, PREVIEW_MAX), Image.LANCZOS)
    paths["preview"].write_bytes(contact.to_jpeg(preview, 85))
    process = conn.execute("SELECT process FROM rolls WHERE id=?", (roll_id,)).fetchone()["process"]
    write_positive(roll_id, process)
    conn.execute("UPDATE rolls SET photo=?, updated_at=? WHERE id=?", (paths["preview"].name, now(), roll_id))
    if not conn.execute("SELECT photographed_at FROM rolls WHERE id=?", (roll_id,)).fetchone()["photographed_at"]:
        db.set_stage(conn, roll_id, "photographed", "done")


@app.get("/rolls/{roll_id}/contact.jpg")
def contact_download(roll_id: str, negative: int = 0, conn=Depends(get_db)):
    r = fetch_roll(conn, roll_id)
    paths = photo_paths(r["id"])
    src = paths["original"] if paths["original"].exists() else paths["preview"]
    if not src.exists():
        raise HTTPException(404, "No contact sheet yet")
    if negative:
        return FileResponse(src, filename=f"{r['id']}_contact_neg.jpg", headers={"Cache-Control": "no-cache"})
    with Image.open(src) as img:
        data = contact.to_jpeg(contact.positive(img, r["process"]), 92)
    return Response(
        data, media_type="image/jpeg",
        headers={"Content-Disposition": f'attachment; filename="{r["id"]}_contact.jpg"', "Cache-Control": "no-cache"},
    )


@app.post("/rolls/{roll_id}/photo")
async def upload_photo(roll_id: str, photo: UploadFile = File(...), conn=Depends(get_db)):
    r = fetch_roll(conn, roll_id)
    try:
        save_photo(conn, r["id"], await photo.read())
    except Exception:
        return RedirectResponse(f"/rolls/{r['id']}?error=photo", 303)
    return RedirectResponse(f"/rolls/{r['id']}", 303)


@app.get("/photos/{name}")
def photo_file(name: str):
    path = (db.PHOTO_DIR / name).resolve()
    if path.parent != db.PHOTO_DIR.resolve() or not path.exists():
        raise HTTPException(404)
    return FileResponse(path, headers={"Cache-Control": "no-cache"})


def stage_json(r):
    return {
        "id": r["id"], "done": db.is_done(r), "stages": {s: db.stage_state(r, s) for s in STAGES},
        "scans": frames.summary(r["picks"], r["scans"]),
    }


@app.post("/api/rolls/{roll_id}/stage")
async def api_stage(roll_id: str, request: Request, conn=Depends(get_db)):
    body = await request.json()
    r = fetch_roll(conn, roll_id)
    try:
        db.set_stage(conn, r["id"], body.get("stage"), body.get("value"))
    except ValueError:
        raise HTTPException(400, "Unknown stage or value")
    return JSONResponse(stage_json(fetch_roll(conn, r["id"])))


@app.post("/api/bulk")
async def api_bulk(request: Request, conn=Depends(get_db)):
    body = await request.json()
    stage, value = body.get("stage"), body.get("value")
    if stage not in STAGES:
        raise HTTPException(400, "Unknown stage")
    if stage != "picked" and value not in ("done", False):
        raise HTTPException(400, "Unknown value")
    out = []
    for roll_id in body.get("ids", []):
        r = conn.execute("SELECT * FROM rolls WHERE id=?", (roll_id,)).fetchone()
        if not r or (stage != "picked" and db.stage_state(r, stage) == ("todo" if value is False else "done")):
            continue
        try:
            db.set_stage(conn, r["id"], stage, value)
        except ValueError:
            raise HTTPException(400, "Unknown value")
        after = fetch_roll(conn, r["id"])
        if (after["picks"], after["scans"], after[f"{stage}_at"]) != (r["picks"], r["scans"], r[f"{stage}_at"]):
            out.append(stage_json(after))
    return JSONResponse({"updated": out})


REFILE_SHOWS = {"all": "All", "unfiled": "Not filed", "elsewhere": "Not in this binder"}


def slot_clashes(conn):
    return conn.execute(
        "SELECT binder, sleeve, GROUP_CONCAT(id, ', ') AS ids FROM rolls "
        "WHERE binder != '' AND sleeve IS NOT NULL GROUP BY binder, sleeve HAVING COUNT(*) > 1 ORDER BY binder, sleeve"
    ).fetchall()


@app.get("/refile", response_class=HTMLResponse)
def refile_page(request: Request, binder: str = "", show: str = "all", conn=Depends(get_db)):
    binder = binder.strip()
    show = show if show in REFILE_SHOWS else "all"
    held = conn.execute(
        "SELECT COUNT(*) AS n, COALESCE(MAX(sleeve), 0) AS top FROM rolls WHERE binder=? AND ?!=''", (binder, binder)
    ).fetchone()
    where = {"all": "1=1", "unfiled": "filed_at IS NULL", "elsewhere": "binder != ?"}[show]
    rolls = conn.execute(f"SELECT * FROM rolls WHERE {where} ORDER BY num", (binder,) if show == "elsewhere" else ()).fetchall()
    return render(
        request, "refile.html", binder=binder, show=show, shows=REFILE_SHOWS, rolls=rolls,
        held=held["n"], next_sleeve=held["top"] + 1, binders=distinct(conn, "binder"), clashes=slot_clashes(conn),
    )


@app.post("/api/rolls/{roll_id}/place")
async def api_place(roll_id: str, request: Request, conn=Depends(get_db)):
    body = await request.json()
    r = fetch_roll(conn, roll_id)
    binder = str(body.get("binder") or "").strip()
    sleeve = body.get("sleeve")
    sleeve = int(sleeve) if str(sleeve or "").isdigit() else None
    undo = bool(body.get("undo"))
    if not binder and not undo:
        raise HTTPException(400, "Pick a binder first")
    before = {"binder": r["binder"], "sleeve": r["sleeve"], "filed": bool(r["filed_at"])}
    conn.execute("UPDATE rolls SET binder=?, sleeve=?, updated_at=? WHERE id=?", (binder, sleeve, now(), r["id"]))
    db.log(conn, r["id"], "edit")
    if undo and body.get("unfile"):
        db.set_stage(conn, r["id"], "filed", False)
    elif not undo and not r["filed_at"]:
        db.set_stage(conn, r["id"], "filed", "done")
    clash = [x["id"] for x in conn.execute(
        "SELECT id FROM rolls WHERE binder=? AND sleeve=? AND id!=? AND ?!=''", (binder, sleeve, r["id"], binder)
    )]
    return JSONResponse({"id": r["id"], "binder": binder, "sleeve": sleeve, "before": before, "clash": clash})


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
        for s in ("photographed", "linked"):
            val = row.get(f"{s}_at") or ("" if f"{s}_at" in row else row.get(s, ""))
            if val and val.lower() not in ("0", "no", "n", "false"):
                updates[f"{s}_at"] = val if "T" in val else filed
        if row.get("photographed_skipped") in ("1", "true", "yes"):
            updates.pop("photographed_at", None)
        if "picks" in row:
            for k in ("picks", "scans", "picked_at", "scanned_at"):
                updates[k] = row.get(k) or ("" if k in ("picks", "scans") else None)
        else:
            val = row.get("scanned_at") or row.get("scanned", "")
            if val and val.lower() not in ("0", "no", "n", "false"):
                ts = val if "T" in val else filed
                updates.update(picks=frames.ALL, scans=frames.ALL, picked_at=ts, scanned_at=ts)
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


@app.get("/docs", response_class=HTMLResponse)
def docs_page(request: Request):
    html = markdown.markdown((HERE / "docs.md").read_text(), extensions=["tables", "toc"], extension_configs={"toc": {"toc_depth": "2-3"}})
    return render(request, "docs.html", body=Markup(html))
