from datetime import date, datetime, timedelta
from html import escape

from . import frames
from .db import STAGES, is_done

SESSION_GAP = timedelta(minutes=45)
STAGE_LABEL = {"filed": "Filed", "photographed": "Contact sheet", "linked": "Linked", "picked": "Scans"}
LINE_LABEL = {"filed": "filed", "photographed": "contact sheets", "linked": "linked", "picked": "reviewed"}
KIND_LABEL = {**LINE_LABEL, "scanned": "scanned"}


def counts(rolls):
    out = {s: sum(1 for r in rolls if r[f"{s}_at"]) for s in STAGES}
    out["total"] = len(rolls)
    out["done"] = sum(1 for r in rolls if is_done(r))
    out["need_photo"] = sum(1 for r in rolls if not r["photographed_at"])
    out["need_link"] = sum(1 for r in rolls if r["photographed_at"] and not r["linked_at"])
    out["need_review"] = sum(1 for r in rolls if r["photographed_at"] and not r["picked_at"])
    out["tbc"] = sum(1 for r in rolls if r["date_tbc"])
    with_picks = [r for r in rolls if r["picks"] not in ("", frames.NONE)]
    open_ = [r for r in with_picks if not r["scanned_at"]]
    out["need_scan"] = len(open_)
    out["scan_rolls"] = len(with_picks)
    out["scan_complete"] = len(with_picks) - len(open_)
    out["frames_left"] = sum(len(frames.remaining(frames.load(r["picks"]), frames.load(r["scans"]))) for r in open_)
    out["whole_left"] = sum(1 for r in open_ if r["picks"] == frames.ALL)
    return out


def sessions(events):
    groups = []
    for e in events:
        ts = datetime.fromisoformat(e["ts"])
        if groups and ts - groups[-1]["end"] <= SESSION_GAP:
            g = groups[-1]
            g["end"] = ts
        else:
            g = {"start": ts, "end": ts, "touched": {k: set() for k in KIND_LABEL}, "rolls": set()}
            groups.append(g)
        g["rolls"].add(e["roll_id"])
        if e["kind"] in KIND_LABEL:
            g["touched"][e["kind"]].add(e["roll_id"])
    return groups


def describe(session):
    if not session:
        return None
    parts = [f"{len(ids)} {KIND_LABEL[k]}" for k, ids in session["touched"].items() if ids]
    if not parts:
        parts = [f"{len(session['rolls'])} rolls edited"]
    minutes = int((session["end"] - session["start"]).total_seconds() // 60)
    when = session["start"].strftime("%a %d %b")
    dur = f"{minutes} min" if minutes >= 1 else "a quick one"
    return {"when": when, "what": " · ".join(parts), "duration": dur}


def strip(groups, weeks=12):
    days = {}
    for g in groups:
        d = g["start"].date()
        days[d] = days.get(d, 0) + len(g["rolls"])
    today = date.today()
    start = today - timedelta(days=today.weekday() + 7 * (weeks - 1))
    cols = []
    for w in range(weeks):
        col = []
        for i in range(7):
            d = start + timedelta(days=7 * w + i)
            col.append({"date": d, "rolls": days.get(d, 0), "future": d > today})
        cols.append(col)
    return cols


def _series(rolls, stage, first, last):
    dates = sorted(datetime.fromisoformat(r[f"{stage}_at"]).date() for r in rolls if r[f"{stage}_at"])
    out, i, n = [], 0, 0
    d = first
    while d <= last:
        while i < len(dates) and dates[i] <= d:
            n += 1
            i += 1
        out.append(n)
        d += timedelta(days=1)
    return out


def burnup_svg(rolls):
    stamps = [
        datetime.fromisoformat(r[f"{s}_at"]).date()
        for r in rolls for s in STAGES if r[f"{s}_at"]
    ]
    if not stamps:
        return ""
    last = date.today()
    first = min(min(stamps), last - timedelta(days=6))
    series = {s: _series(rolls, s, first, last) for s in STAGES}
    days = (last - first).days or 1
    top = max(max(v[-1] for v in series.values()), 4)
    step = 10 if top > 20 else 2
    top = -(-top // step) * step

    W, H, L, R, T, B = 440, 190, 26, 124, 10, 22
    pw, ph = W - L - R, H - T - B

    def x(i):
        return L + pw * i / days

    def y(v):
        return T + ph * (1 - v / top)

    out = [f'<svg class="burnup" viewBox="0 0 {W} {H}" role="img" aria-label="Rolls per stage over time">']
    for v in (0, top // 2, top):
        out.append(f'<line class="grid" x1="{L}" x2="{L + pw}" y1="{y(v):.1f}" y2="{y(v):.1f}"/>')
        out.append(f'<text class="tick" x="{L - 6}" y="{y(v) + 3.5:.1f}" text-anchor="end">{v}</text>')
    out.append(f'<text class="tick" x="{L}" y="{H - 6}">{first.strftime("%d %b %y")}</text>')
    out.append(f'<text class="tick" x="{L + pw}" y="{H - 6}" text-anchor="end">today</text>')

    ends = []
    for s in reversed(STAGES):
        vals = series[s]
        pts = [f"{x(0):.1f},{y(vals[0]):.1f}"]
        for i in range(1, len(vals)):
            if vals[i] != vals[i - 1]:
                pts.append(f"{x(i):.1f},{y(vals[i - 1]):.1f}")
                pts.append(f"{x(i):.1f},{y(vals[i]):.1f}")
        pts.append(f"{x(len(vals) - 1):.1f},{y(vals[-1]):.1f}")
        out.append(f'<polyline class="line s-{s}" points="{" ".join(pts)}"/>')
        ends.append([y(vals[-1]), s, vals[-1]])

    ends.sort()
    for i in range(1, len(ends)):
        if ends[i][0] - ends[i - 1][0] < 13:
            ends[i][0] = ends[i - 1][0] + 13
    limit = T + ph
    for e in reversed(ends):
        e[0] = min(e[0], limit)
        limit = e[0] - 13
    for ly, s, v in ends:
        out.append(
            f'<text class="end s-{s}" x="{L + pw + 6}" y="{ly + 4:.1f}">'
            f'<tspan class="n">{v}</tspan> {escape(LINE_LABEL[s])}</text>'
        )
    out.append("</svg>")
    return "".join(out)
