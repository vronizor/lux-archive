import csv
from datetime import datetime
import hashlib
import io
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import urlencode

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape
import markdown
from PIL import Image, ImageOps
import segno
from starlette.background import BackgroundTask

from . import contact, db, desktop, frames, seasons, stats
from .db import ARCHIVE_SQL, LIFE, STAGES, get_db, now
from .version import VERSION

TRUTHY = ("1", "on", "true", "yes", "y")
PREVIEW_MAX = int(os.environ.get("LUX_PHOTO_MAX", "0"))


def when(roll, short=False):
    text = escape(seasons.span(roll, short))
    if roll["date_tbc"]:
        text += Markup(' <span class="tbc" title="Year to be confirmed">TBC</span>')
    return Markup(text)

HERE = Path(__file__).parent

app = FastAPI(title="Lux Archive", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = Jinja2Templates(directory=HERE / "templates")
templates.env.filters["fmtdate"] = lambda iso: f"{datetime.fromisoformat(iso):%d %b}".lstrip("0") if iso else ""
templates.env.globals.update(
    fid=db.format_id,
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
    where=db.where,
    asset_v=hashlib.sha256(b"".join(p.read_bytes() for p in sorted((HERE / "static").iterdir()))).hexdigest()[:10],
)

EXPORT_COLS = [
    "id", "start_year", "start_season", "end_year", "end_season", "date_tbc", "contents", "binder", "sleeve",
    "sleeves", "stock", "process", "camera", "scan_ref", "notes", "photo", "filed_at", "photographed_at",
    "photographed_skipped", "scanned_at", "linked_at", "picks", "scans", "picked_at",
    "ei", "lab", "loaded_at", "shot_at", "sent_at", "back_at", "created_at", "updated_at",
]

SHEETS_SQL = "(CASE WHEN photo IS NULL OR photo = '' THEN 0 ELSE length(photo) - length(replace(photo, ' ', '')) + 1 END)"
DONE_SQL = "filed_at IS NOT NULL AND photographed_at IS NOT NULL AND linked_at IS NOT NULL AND picked_at IS NOT NULL"
FILTERS = {
    "all": ("All", "1=1"),
    "todo": ("Not done", f"{ARCHIVE_SQL} AND NOT ({DONE_SQL})"),
    "need-photo": ("Contact sheet", f"{ARCHIVE_SQL} AND photographed_at IS NULL"),
    "need-sheet": ("Missing a sheet", f"{SHEETS_SQL} > 0 AND {SHEETS_SQL} < COALESCE(sleeves, 1)"),
    "need-link": ("To link", "photographed_at IS NOT NULL AND linked_at IS NULL"),
    "need-review": ("To review", "photographed_at IS NOT NULL AND picked_at IS NULL"),
    "need-scan": ("To scan", "picks NOT IN ('', 'none') AND scanned_at IS NULL"),
    "done": ("Done", DONE_SQL),
    "tbc": ("Year TBC", "date_tbc=1"),
    "out": ("Not back yet", f"NOT {ARCHIVE_SQL}"),
}
GAPS = [
    ("not back from the lab", FILTERS["out"][1]),
    ("not filed", f"{ARCHIVE_SQL} AND filed_at IS NULL"),
    ("missing a sheet", FILTERS["need-sheet"][1]),
    ("without a contact sheet", FILTERS["need-photo"][1]),
    ("not in {catalog}", FILTERS["need-link"][1]),
    ("to review", FILTERS["need-review"][1]),
    ("to scan", FILTERS["need-scan"][1]),
]


@app.middleware("http")
async def guard(request: Request, call_next):
    if db.DESKTOP:
        if desktop.cross_site(request):
            return HTMLResponse("Cross-site request refused.", 403)
        if not desktop.is_local(request):
            path = request.url.path
            conn = db.connect()
            try:
                ok = db.setting("lan") == "1" and (path == "/pair" or desktop.paired(request, conn))
                conn.commit()
            finally:
                conn.close()
            if not ok or path.startswith(desktop.LOCAL_ONLY):
                return templates.TemplateResponse(
                    request, "blocked.html", {"app_name": db.setting("name"), "paired": ok}, status_code=403
                )
    return await call_next(request)


@app.on_event("startup")
def startup():
    if db.DESKTOP:
        desktop.safety_copy()
    db.init()
    if db.DESKTOP:
        desktop.start_background()
    with db.connect() as conn:
        row = conn.execute("SELECT value FROM meta WHERE key='positive_version'").fetchone()
        if not row or row["value"] != contact.VERSION:
            for suffix in db.DERIVED:
                for path in db.PHOTO_DIR.glob(f"*{suffix}.jpg"):
                    path.unlink(missing_ok=True)
            conn.execute(
                "INSERT INTO meta(key, value) VALUES('positive_version', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (contact.VERSION,),
            )


def shooting():
    with db.connect() as conn:
        return conn.execute("SELECT 1 FROM rolls WHERE loaded_at IS NOT NULL LIMIT 1").fetchone() is not None


def render(request, name, **ctx):
    ctx.setdefault("shooting", shooting())
    ctx.update(cfg=db.settings(), app_name=db.setting("name"), desktop=db.DESKTOP, update=None)
    if db.DESKTOP:
        with db.connect() as conn:
            ctx["update"] = desktop.update_notice(conn)
        ctx["on_computer"] = desktop.is_local(request)
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

    sleeve, sleeves = intval(form.get("sleeve")), intval(form.get("sleeves")) or 1

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
        "sleeve": sleeve,
        "sleeves": sleeves if sleeve else 1,
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


def setup_steps(request, conn):
    if not db.DESKTOP or not desktop.is_local(request) or db.get_meta(conn, "setup_done"):
        return None
    has_rolls = rolls_exist(conn)
    steps = [
        {"label": "Choose your roll letter", "hint": f"Rolls will be numbered {db.format_id(1)}, {db.format_id(2)}… It can't change later.", "href": "/settings", "done": has_rolls or db.get_meta(conn, "set.prefix") is not None},
        {"label": "File your first roll", "hint": "Or load one in a camera.", "href": "/add", "done": has_rolls},
        {"label": "Set a backup folder", "hint": "Until then the only copy is on this computer.", "href": "/settings#backup", "done": bool(db.setting("backup_dir"))},
        {"label": "Pair your phone", "hint": "Optional: shoot contact sheets straight into a roll.", "href": "/settings#phone", "done": db.setting("lan") == "1"},
    ]
    return None if all(s["done"] for s in steps) else steps


def backup_nudge(request, conn):
    if not db.DESKTOP or not desktop.is_local(request) or not conn.execute("SELECT 1 FROM rolls LIMIT 1").fetchone():
        return None
    if db.get_meta(conn, "backup_error"):
        return "The last backup failed."
    return None if db.setting("backup_dir") else "No backup yet: the only copy of this archive is on this computer."


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
        sheets_left=len(sheet_queue(conn)),
        setup=setup_steps(request, conn),
        nudge=backup_nudge(request, conn),
    )


@app.get("/last")
def last_touched(conn=Depends(get_db)):
    r = conn.execute("SELECT id FROM rolls ORDER BY updated_at DESC LIMIT 1").fetchone()
    return RedirectResponse(f"/rolls/{r['id']}" if r else "/", 303)


@app.get("/add", response_class=HTMLResponse)
def add_form(request: Request, saved: str = "", error: str = "", conn=Depends(get_db)):
    last = conn.execute("SELECT * FROM rolls WHERE filed_at IS NOT NULL ORDER BY num DESC LIMIT 1").fetchone()
    defaults = {
        "id": db.format_id(db.next_num(conn)),
        "start_year": (last["end_year"] or last["start_year"]) if last else "",
        "start_season": (last["end_season"] or last["start_season"]) if last else "",
        "binder": last["binder"] if last else db.setting("binder"),
        "sleeve": db.after_slot(last) if last else 1,
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
    filed = bool(form.get("filed"))
    fields = clean_fields(form)
    if not filed:
        fields.update(binder="", sleeve=None, sleeves=1)
    roll_id = insert_roll(conn, num, fields, filed=filed)
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
    field = "notes" if form.get("to") == "notes" else "contents"
    if note:
        joined = ("\n" if field == "notes" else ", ").join(x for x in (r[field], note) if x)
        conn.execute(f"UPDATE rolls SET {field}=?, updated_at=? WHERE id=?", (joined, now(), r["id"]))
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

    if re.fullmatch(rf"(?:{db.setting('prefix')})?\d{{1,4}}", q.strip(), re.I):
        hit = conn.execute("SELECT id FROM rolls WHERE num=?", (db.parse_id(q),)).fetchone()
        if hit:
            return RedirectResponse(f"/rolls/{hit['id']}", 303)
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
    sheets = []
    for n in db.sheet_nums(r["photo"]):
        paths = db.sheet_paths(r["id"], n)
        if paths["preview"].exists():
            sheets.append({"n": n, "has_original": paths["original"].exists()})
    nav = conn.execute(
        "SELECT (SELECT id FROM rolls WHERE num<? ORDER BY num DESC LIMIT 1) AS prev, "
        "(SELECT id FROM rolls WHERE num>? ORDER BY num LIMIT 1) AS next",
        (r["num"], r["num"]),
    ).fetchone()
    gap = None
    for label, sql in GAPS:
        if conn.execute(f"SELECT 1 FROM rolls WHERE id=? AND {sql}", (r["id"],)).fetchone():
            gap = conn.execute(
                f"SELECT ? AS label, (SELECT id FROM rolls WHERE num<? AND {sql} ORDER BY num DESC LIMIT 1) AS prev, "
                f"(SELECT id FROM rolls WHERE num>? AND {sql} ORDER BY num LIMIT 1) AS next",
                (label.format(catalog=db.setting("catalog")), r["num"], r["num"]),
            ).fetchone()
            break
    prefetch = []
    for rid in (nav["next"], nav["prev"]):
        row = rid and conn.execute("SELECT id, photo, updated_at FROM rolls WHERE id=?", (rid,)).fetchone()
        if row:
            prefetch += [(row["id"], n, view_version(row)) for n in db.sheet_nums(row["photo"])]
    return render(
        request, "roll.html", r=r, d=dict(r), nav=nav, gap=gap, saved=saved, error=error,
        sheets=sheets, missing=db.missing_sheets(r), ver=view_version(r), prefetch=prefetch,
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
    if fields["binder"] and not r["filed_at"]:
        db.set_stage(conn, r["id"], "filed", "done")
    tick_if_complete(conn, r["id"])
    if fields["process"] != r["process"]:
        for n in db.sheet_nums(r["photo"]):
            write_positive(r["id"], n, fields["process"])
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
    for n in db.sheet_nums(r["photo"]):
        for path in db.sheet_paths(r["id"], n).values():
            path.unlink(missing_ok=True)
    return RedirectResponse("/rolls", 303)


VIEW_MAX = 2000


def write_atomic(path, data):
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def shrink(img):
    img = img.copy()
    img.thumbnail((VIEW_MAX, VIEW_MAX), Image.LANCZOS)
    return img


def write_positive(roll_id, n, process):
    paths = db.sheet_paths(roll_id, n)
    with Image.open(paths["preview"]) as img:
        img.load()
        pos = contact.positive(img, process)
        write_atomic(paths["positive"], contact.to_jpeg(pos, 85))
        write_atomic(paths["view"], contact.to_jpeg(shrink(pos), 82))
        write_atomic(paths["vneg"], contact.to_jpeg(shrink(img.convert("RGB")), 82))


def preview_edge(original):
    with Image.open(original) as img:
        edge = max(img.size)
    return min(edge, PREVIEW_MAX) if PREVIEW_MAX else edge


def write_preview(roll_id, n):
    paths = db.sheet_paths(roll_id, n)
    with Image.open(paths["original"]) as img:
        preview = ImageOps.exif_transpose(img).convert("RGB")
    if PREVIEW_MAX:
        preview.thumbnail((PREVIEW_MAX, PREVIEW_MAX), Image.LANCZOS)
    write_atomic(paths["preview"], contact.to_jpeg(preview, 85))


def refresh_sheet(roll_id, n, process):
    paths = db.sheet_paths(roll_id, n)
    if paths["original"].exists():
        with Image.open(paths["preview"]) as img:
            stale = abs(max(img.size) - preview_edge(paths["original"])) > 2
        if stale:
            write_preview(roll_id, n)
            for k in ("positive", "view", "vneg"):
                paths[k].unlink(missing_ok=True)
    if not all(paths[k].exists() for k in ("positive", "view", "vneg")):
        write_positive(roll_id, n, process)


def save_photo(conn, roll_id, data, sheet=None):
    r = conn.execute("SELECT photo, process, photographed_at, sleeves FROM rolls WHERE id=?", (roll_id,)).fetchone()
    nums = db.sheet_nums(r["photo"])
    n = sheet if sheet in nums else max(nums, default=0) + 1
    paths = db.sheet_paths(roll_id, n)
    img = Image.open(io.BytesIO(data))
    if img.format == "JPEG":
        paths["original"].write_bytes(data)
    else:
        paths["original"].write_bytes(contact.to_jpeg(ImageOps.exif_transpose(img).convert("RGB"), 95))
    write_preview(roll_id, n)
    write_positive(roll_id, n, r["process"])
    db.set_sheets(conn, roll_id, set(nums) | {n})
    tick_if_complete(conn, roll_id)


def tick_if_complete(conn, roll_id):
    r = conn.execute("SELECT photo, sleeves, photographed_at FROM rolls WHERE id=?", (roll_id,)).fetchone()
    if r["photo"] and not r["photographed_at"] and not db.missing_sheets(r):
        db.set_stage(conn, roll_id, "photographed", "done")


def remove_sheet(conn, roll_id, n):
    for path in db.sheet_paths(roll_id, n).values():
        path.unlink(missing_ok=True)
    r = conn.execute("SELECT photo FROM rolls WHERE id=?", (roll_id,)).fetchone()
    db.set_sheets(conn, roll_id, set(db.sheet_nums(r["photo"])) - {n})


def view_version(r):
    return f"{r['updated_at']}.{contact.VERSION}.{PREVIEW_MAX}"


@app.get("/rolls/{roll_id}/view-{n}.jpg")
def sheet_view(roll_id: str, n: int, neg: int = 0, v: str = "", conn=Depends(get_db)):
    r = fetch_roll(conn, roll_id)
    paths = db.sheet_paths(r["id"], n)
    if n not in db.sheet_nums(r["photo"]) or not paths["preview"].exists():
        raise HTTPException(404, "No such contact sheet")
    refresh_sheet(r["id"], n, r["process"])
    cache = "private, max-age=31536000, immutable" if v == view_version(r) else "no-cache"
    return FileResponse(paths["vneg" if neg else "view"], headers={"Cache-Control": cache})


@app.get("/rolls/{roll_id}/contact-{n}.jpg")
def contact_download(roll_id: str, n: int, negative: int = 0, conn=Depends(get_db)):
    r = fetch_roll(conn, roll_id)
    if n not in db.sheet_nums(r["photo"]):
        raise HTTPException(404, "No such contact sheet")
    paths = db.sheet_paths(r["id"], n)
    src = paths["original"] if paths["original"].exists() else paths["preview"]
    if not src.exists():
        raise HTTPException(404, "No such contact sheet")
    name = f"{r['id']}_contact-{n}"
    if negative:
        return FileResponse(src, filename=f"{name}_neg.jpg", headers={"Cache-Control": "no-cache"})
    with Image.open(src) as img:
        data = contact.to_jpeg(contact.positive(img, r["process"]), 92)
    return Response(
        data, media_type="image/jpeg",
        headers={"Content-Disposition": f'attachment; filename="{name}.jpg"', "Cache-Control": "no-cache"},
    )


@app.post("/rolls/{roll_id}/photo")
async def upload_photo(roll_id: str, photo: UploadFile = File(...), sheet: int = Form(0), conn=Depends(get_db)):
    r = fetch_roll(conn, roll_id)
    try:
        save_photo(conn, r["id"], await photo.read(), sheet or None)
    except Exception:
        return RedirectResponse(f"/rolls/{r['id']}?error=photo", 303)
    return RedirectResponse(f"/rolls/{r['id']}#sheets", 303)


@app.post("/rolls/{roll_id}/sheets/{n}/delete")
def delete_sheet(roll_id: str, n: int, conn=Depends(get_db)):
    r = fetch_roll(conn, roll_id)
    remove_sheet(conn, r["id"], n)
    return RedirectResponse(f"/rolls/{r['id']}#sheets", 303)


SHEET_QUEUE_SQL = f"{ARCHIVE_SQL} AND (photographed_at IS NULL OR ({SHEETS_SQL} > 0 AND {SHEETS_SQL} < COALESCE(sleeves, 1)))"


def sheet_queue(conn):
    return conn.execute(
        f"SELECT * FROM rolls WHERE {SHEET_QUEUE_SQL} ORDER BY binder = '', lower(binder), sleeve IS NULL, sleeve, num"
    ).fetchall()


def sheets_url(binder="", at="", done="", error=""):
    query = urlencode({k: v for k, v in (("binder", binder), ("at", at), ("done", done), ("error", error)) if v})
    return "/sheets" + (f"?{query}" if query else "")


@app.get("/sheets", response_class=HTMLResponse)
def sheets_page(request: Request, binder: str = "", at: str = "", done: str = "", error: str = "", conn=Depends(get_db)):
    everything = sheet_queue(conn)
    binders = {}
    for r in everything:
        binders[r["binder"] or "-"] = binders.get(r["binder"] or "-", 0) + 1
    if binder not in binders:
        binder = ""
    queue = [r for r in everything if not binder or (r["binder"] or "-") == binder]
    pos = next((i for i, r in enumerate(queue) if r["id"] == at.upper()), 0)
    current = queue[pos] if queue else None
    after = queue[pos + 1]["id"] if pos + 1 < len(queue) else ""
    shot = conn.execute("SELECT * FROM rolls WHERE id=?", (done.upper(),)).fetchone() if done else None
    shot_n = max(db.sheet_nums(shot["photo"]), default=0) if shot else 0
    total = conn.execute(f"SELECT COUNT(*) FROM rolls WHERE {ARCHIVE_SQL}").fetchone()[0]
    return render(
        request, "sheets.html", binder=binder, binders=binders, queue=queue, current=current, after=after,
        have=len(db.sheet_nums(current["photo"])) if current else 0, error=error,
        shot=shot if shot_n else None, shot_n=shot_n, shot_v=view_version(shot) if shot else "",
        total=total, left=len(everything), url=sheets_url,
    )


@app.post("/sheets/shoot/{roll_id}")
async def sheets_shoot(
    roll_id: str, photo: UploadFile = File(...), sheet: int = Form(0), binder: str = Form(""),
    after: str = Form(""), stay: str = Form(""), conn=Depends(get_db),
):
    r = fetch_roll(conn, roll_id)
    try:
        save_photo(conn, r["id"], await photo.read(), sheet or None)
    except Exception:
        return RedirectResponse(sheets_url(binder, stay or r["id"], error=r["id"]), 303)
    pending = any(q["id"] == r["id"] for q in sheet_queue(conn))
    return RedirectResponse(sheets_url(binder, stay or (r["id"] if pending else after), done=r["id"]), 303)


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
        "binder": r["binder"], "sleeve": r["sleeve"], "sleeves": r["sleeves"] or 1, "where": db.where(r),
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


@app.post("/api/rolls/{roll_id}/pick")
async def api_pick(roll_id: str, request: Request, conn=Depends(get_db)):
    body = await request.json()
    r = fetch_roll(conn, roll_id)
    try:
        frame = frames.parse(str(body.get("frame", "")))
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not isinstance(frame, list) or len(frame) != 1:
        raise HTTPException(400, "One frame number, like 14 or 14A")
    frame = frame[0]
    picks, scans = frames.load(r["picks"]), frames.load(r["scans"])
    if picks == frames.ALL:
        raise HTTPException(409, "The whole roll is already picked")
    if scans == frames.ALL or (isinstance(scans, list) and frame in scans):
        raise HTTPException(409, f"{frame} is already scanned")
    new, added = frames.toggle(picks, frame)
    db.set_scans(conn, r["id"], frames.fmt(new), r["scans"])
    after = fetch_roll(conn, r["id"])
    return JSONResponse({**stage_json(after), "frame": frame, "added": added, "picks": after["picks"]})


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


OVERLAP_SQL = "binder=? AND sleeve <= ? AND sleeve + COALESCE(sleeves, 1) - 1 >= ?"


def slot_clashes(conn):
    slots = {}
    for r in conn.execute("SELECT id, binder, sleeve, sleeves FROM rolls WHERE binder != '' AND sleeve IS NOT NULL ORDER BY num"):
        for k in range(r["sleeve"], r["sleeve"] + (r["sleeves"] or 1)):
            slots.setdefault((r["binder"], k), []).append(r["id"])
    return [
        {"binder": b, "sleeve": k, "ids": ", ".join(ids)}
        for (b, k), ids in sorted(slots.items(), key=lambda x: (x[0][0].lower(), x[0][1])) if len(ids) > 1
    ]


@app.get("/refile", response_class=HTMLResponse)
def refile_page(request: Request, binder: str = "", show: str = "all", conn=Depends(get_db)):
    binder = binder.strip()
    show = show if show in REFILE_SHOWS else "all"
    held = conn.execute(
        "SELECT COUNT(*) AS n, COALESCE(MAX(sleeve + COALESCE(sleeves, 1) - 1), 0) AS top FROM rolls WHERE binder=? AND ?!=''",
        (binder, binder),
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
    sleeves = body.get("sleeves")
    sleeves = int(sleeves) if str(sleeves or "").isdigit() and int(sleeves) > 0 else 1
    undo = bool(body.get("undo"))
    if not binder and not undo:
        raise HTTPException(400, "Pick a binder first")
    before = {
        "binder": r["binder"], "sleeve": r["sleeve"], "sleeves": r["sleeves"] or 1,
        "filed": bool(r["filed_at"]), "where": db.where(r),
    }
    conn.execute(
        "UPDATE rolls SET binder=?, sleeve=?, sleeves=?, updated_at=? WHERE id=?",
        (binder, sleeve, sleeves if sleeve else 1, now(), r["id"]),
    )
    db.log(conn, r["id"], "edit")
    if undo and body.get("unfile"):
        db.set_stage(conn, r["id"], "filed", False)
    elif not undo and not r["filed_at"]:
        db.set_stage(conn, r["id"], "filed", "done")
    after = fetch_roll(conn, r["id"])
    clash = [x["id"] for x in conn.execute(
        f"SELECT id FROM rolls WHERE {OVERLAP_SQL} AND id!=? AND ?!=''",
        (binder, (sleeve or 0) + after["sleeves"] - 1, sleeve, r["id"], binder),
    )] if sleeve else []
    return JSONResponse({
        "id": r["id"], "binder": binder, "sleeve": sleeve, "sleeves": after["sleeves"],
        "where": db.where(after), "next": db.after_slot(after), "before": before, "clash": clash,
    })


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
        for k in ("loaded_at", "shot_at", "sent_at", "back_at"):
            if row.get(k):
                updates[k] = row[k]
        if "picks" in row:
            for k in ("picks", "scans", "picked_at", "scanned_at"):
                updates[k] = row.get(k) or ("" if k in ("picks", "scans") else None)
        else:
            val = row.get("scanned_at") or row.get("scanned", "")
            if val and val.lower() not in ("0", "no", "n", "false"):
                ts = val if "T" in val else filed
                updates.update(picks=frames.ALL, scans=frames.ALL, picked_at=ts, scanned_at=ts)
        photos = [n for n in (row.get("photo") or "").split() if (db.PHOTO_DIR / n).exists()]
        if photos:
            updates["photo"] = " ".join(photos)
        if updates:
            conn.execute(
                f"UPDATE rolls SET {', '.join(f'{k}=?' for k in updates)} WHERE id=?",
                [*updates.values(), roll_id],
            )
        added.append(roll_id)
    db.migrate_sheets(conn)
    return added, skipped, errors


@app.post("/import", response_class=HTMLResponse)
async def import_csv(request: Request, file: UploadFile = File(...), conn=Depends(get_db)):
    text = (await file.read()).decode("utf-8-sig")
    if not conn.execute("SELECT 1 FROM rolls LIMIT 1").fetchone() and not db.get_meta(conn, "set.prefix"):
        m = re.search(r"^\s*([A-Za-z]{1,4})\d+\s*[,;\t]", text.split("\n", 1)[-1], re.M)
        if m:
            db.save_settings(conn, {"prefix": m.group(1).upper()})
    dialect = csv.Sniffer().sniff(text.splitlines()[0], delimiters=",;\t") if text.strip() else csv.excel
    added, skipped, errors = import_rows(conn, csv.DictReader(io.StringIO(text), dialect=dialect))
    return render(request, "import.html", result={"added": added, "skipped": skipped, "errors": errors})


NOTES = {"docs": "Docs", "field": "Field"}


def note_text(name):
    custom = db.DATA_DIR / f"{name}.md"
    if custom.exists():
        return custom.read_text(encoding="utf-8"), True
    if not db.DESKTOP:
        return (HERE / f"{name}.md").read_text(encoding="utf-8"), False
    text = (HERE / "starter" / f"{name}.md").read_text(encoding="utf-8")
    for token, value in (("%PREFIX%", db.setting("prefix")), ("%CATALOG%", db.setting("catalog")), ("%APP%", db.setting("name"))):
        text = text.replace(token, value)
    return text, False


def md_page(request, name):
    text, custom = note_text(name)
    html = markdown.markdown(text, extensions=["tables", "toc"], extension_configs={"toc": {"toc_depth": "2-3"}})
    return render(request, "docs.html", body=Markup(html), doc=name, title=NOTES[name], custom=custom)


@app.get("/docs", response_class=HTMLResponse)
def docs_page(request: Request):
    return md_page(request, "docs")


@app.get("/field", response_class=HTMLResponse)
def field_page(request: Request):
    return md_page(request, "field")


def editable_note(name):
    if not db.DESKTOP or name not in NOTES:
        raise HTTPException(404)
    return name


@app.get("/notes/{name}/edit", response_class=HTMLResponse)
def note_edit(request: Request, name: str):
    text, custom = note_text(editable_note(name))
    return render(request, "note_edit.html", doc=name, title=NOTES[name], text=text, custom=custom)


@app.post("/notes/{name}")
async def note_save(request: Request, name: str):
    form = await request.form()
    path = db.DATA_DIR / f"{editable_note(name)}.md"
    if form.get("action") == "reset":
        path.unlink(missing_ok=True)
    else:
        write_atomic(path, (form.get("text") or "").replace("\r\n", "\n").encode("utf-8"))
    return RedirectResponse(f"/{name}", 303)


@app.get("/api/ping")
def ping():
    return {"app": "lux-archive", "version": VERSION}


def rolls_exist(conn):
    return conn.execute("SELECT 1 FROM rolls LIMIT 1").fetchone() is not None or db.get_meta(conn, "last_issued") is not None


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, saved: int = 0, error: str = "", conn=Depends(get_db)):
    ctx = {"locked": rolls_exist(conn), "saved": saved, "error": error, "version": VERSION}
    if db.DESKTOP:
        ip = desktop.lan_ip()
        link = f"http://{ip}:{desktop.state.port}/pair?k={desktop.pair_token(conn)}" if ip else None
        ctx.update(
            pair_link=link,
            qr=Markup(segno.make(link, error="m").svg_inline(scale=5, border=3, dark="#000", light="#fff")) if link else None,
            lan_on=db.setting("lan") == "1",
            backup_at=db.get_meta(conn, "backup_at"),
            backup_error=db.get_meta(conn, "backup_error"),
            update_checked=db.get_meta(conn, "update_checked"),
            update_latest=db.get_meta(conn, "update_latest"),
            data_dir=str(db.DATA_DIR),
            empty=not conn.execute("SELECT 1 FROM rolls LIMIT 1").fetchone(),
        )
    return render(request, "settings.html", **ctx)


def settings_redirect(error="", anchor=""):
    query = urlencode({"error": error}) if error else "saved=1"
    return RedirectResponse(f"/settings?{query}{anchor}", 303)


@app.post("/settings")
async def settings_save(request: Request, conn=Depends(get_db)):
    form = await request.form()
    values, error = {}, ""
    for key, limit in (("name", 40), ("catalog", 30), ("binder", 20)):
        value = (form.get(key) or "").strip()[:limit]
        if value:
            values[key] = value
    prefix = (form.get("prefix") or "").strip().upper()
    if prefix and (prefix != db.setting("prefix") or not rolls_exist(conn)):
        if rolls_exist(conn):
            error = "The prefix can't change once a roll has a number."
        elif not re.fullmatch(r"[A-Z]{1,4}", prefix):
            error = "The prefix is 1 to 4 letters."
        else:
            values["prefix"] = prefix
    db.save_settings(conn, values)
    return settings_redirect(error)


def desktop_only():
    if not db.DESKTOP:
        raise HTTPException(404)


@app.get("/pair")
def pair(k: str = "", conn=Depends(get_db)):
    desktop_only()
    if not desktop.token_ok(conn, k):
        raise HTTPException(403, "This pairing link is no longer valid. Scan the code in Settings again.")
    res = RedirectResponse("/", 303)
    res.set_cookie(desktop.COOKIE, k, max_age=400 * 86400, httponly=True, samesite="lax")
    return res


@app.post("/desktop/phone")
async def desktop_phone(request: Request, conn=Depends(get_db)):
    desktop_only()
    form = await request.form()
    if form.get("action") == "forget":
        desktop.pair_token(conn, renew=True)
        return settings_redirect(anchor="#phone")
    db.save_settings(conn, {"lan": "1" if form.get("action") == "on" else "0"})
    desktop.stop_server(restart=True)
    return render(request, "pause.html", restarting=True)


@app.post("/desktop/backup")
async def desktop_backup(request: Request, conn=Depends(get_db)):
    desktop_only()
    form = await request.form()
    if "backup_dir" in form:
        folder = (form.get("backup_dir") or "").strip()
        if folder:
            try:
                Path(folder).expanduser().mkdir(parents=True, exist_ok=True)
            except OSError as e:
                return settings_redirect(f"Can't use that folder: {e}", "#backup")
        db.save_settings(conn, {"backup_dir": folder})
    conn.commit()
    error = desktop.run_backup(conn) if db.setting("backup_dir") else ""
    return settings_redirect(error and f"Backup failed: {error}", "#backup")


@app.get("/desktop/backup.zip")
def desktop_backup_zip():
    desktop_only()
    from . import backup

    fd, tmp = tempfile.mkstemp(suffix=".zip")
    os.close(fd)
    backup.make_zip(tmp)
    return FileResponse(
        tmp, filename=f"lux-archive-backup-{datetime.now():%Y-%m-%d}.zip", media_type="application/zip",
        background=BackgroundTask(os.unlink, tmp),
    )


@app.post("/desktop/restore")
async def desktop_restore(request: Request):
    desktop_only()
    from . import backup

    form = await request.form()
    try:
        added, errors = backup.restore((form.get("source") or "").strip())
    except (RuntimeError, OSError, ValueError) as e:
        return settings_redirect(f"Restore failed: {e}", "#backup")
    return RedirectResponse("/", 303)


@app.post("/desktop/updates")
async def desktop_updates(request: Request, conn=Depends(get_db)):
    desktop_only()
    form = await request.form()
    db.save_settings(conn, {"updates": "1" if form.get("updates") else "0"})
    if form.get("updates") and not desktop.check_update(conn):
        return settings_redirect("Couldn't reach GitHub to check for updates.", "#updates")
    return settings_redirect(anchor="#updates")


@app.post("/desktop/setup-done")
def desktop_setup_done(conn=Depends(get_db)):
    desktop_only()
    db.set_meta(conn, "setup_done", now())
    return RedirectResponse("/", 303)


@app.post("/desktop/pick")
def desktop_pick(kind: str = "folder"):
    desktop_only()
    try:
        return {"path": desktop.pick("zip" if kind == "zip" else "folder")}
    except Exception as e:
        return JSONResponse({"path": None, "error": str(e)})


@app.post("/desktop/quit")
def desktop_quit(request: Request):
    desktop_only()
    desktop.stop_server()
    return render(request, "pause.html", restarting=False)


@app.get("/sw.js")
def service_worker():
    return FileResponse(HERE / "static" / "sw.js", media_type="text/javascript", headers={"Cache-Control": "no-cache"})
