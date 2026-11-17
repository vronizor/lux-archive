import hmac
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import sqlite3
import threading
import time
import urllib.request
from datetime import datetime, timedelta

from . import db
from .version import VERSION

REPO = os.environ.get("LUX_REPO", "vronizor/lux-archive")
COOKIE = "lux_pair"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
LOCAL_ONLY = ("/settings", "/desktop", "/notes")


class State:
    server = None
    restart = False
    port = 8410
    started = False


state = State()


def hostname(request):
    host = request.headers.get("host", "")
    if host.startswith("["):
        return host[1:].split("]")[0]
    return host.rsplit(":", 1)[0] if ":" in host else host


def is_local(request):
    client = request.client.host if request.client else ""
    return client in ("127.0.0.1", "::1") and hostname(request) in LOCAL_HOSTS


def cross_site(request):
    origin = request.headers.get("origin")
    if request.method in ("GET", "HEAD", "OPTIONS") or not origin:
        return False
    return origin.split("://", 1)[-1] != request.headers.get("host", "")


def pair_token(conn, renew=False):
    token = db.get_meta(conn, "pair_token")
    if renew or not token:
        token = secrets.token_urlsafe(16)
        db.set_meta(conn, "pair_token", token)
    return token


def token_ok(conn, given):
    return bool(given) and hmac.compare_digest(given.encode(), pair_token(conn).encode())


def paired(request, conn):
    return token_ok(conn, request.cookies.get(COOKIE, ""))


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.0.2.1", 9))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


def parse_version(text):
    nums = re.findall(r"\d+", text or "")
    return tuple(int(n) for n in nums) if nums else None


def newer(latest):
    mine, theirs = parse_version(VERSION), parse_version(latest)
    return bool(mine and theirs and theirs > mine)


def check_update(conn):
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/releases/latest",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "lux-archive"},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as res:
            data = json.load(res)
    except Exception:
        db.set_meta(conn, "update_checked", db.now())
        return False
    db.set_meta(conn, "update_latest", data.get("tag_name") or "")
    db.set_meta(conn, "update_url", data.get("html_url") or "")
    db.set_meta(conn, "update_checked", db.now())
    return True


def update_notice(conn):
    latest = db.get_meta(conn, "update_latest")
    if db.setting("updates") == "1" and newer(latest):
        return {"version": latest, "url": db.get_meta(conn, "update_url")}
    return None


def stale(conn, key, hours=24):
    last = db.get_meta(conn, key)
    if not last:
        return True
    try:
        return datetime.now().astimezone() - datetime.fromisoformat(last) > timedelta(hours=hours)
    except ValueError:
        return True


def run_backup(conn):
    from . import backup

    target = db.setting("backup_dir")
    if not target:
        return "No backup folder set"
    try:
        backup.export(os.path.expanduser(target), originals=True)
    except Exception as e:
        db.set_meta(conn, "backup_error", str(e))
        return str(e)
    db.set_meta(conn, "backup_at", db.now())
    db.set_meta(conn, "backup_error", "")
    return ""


def safety_copy():
    if not db.DB_PATH.exists():
        return
    conn = db.connect()
    try:
        before = db.get_meta(conn, "app_version")
        rolls = conn.execute("SELECT COUNT(*) FROM rolls").fetchone()[0]
        if before != VERSION and rolls:
            folder = db.DATA_DIR / "safety"
            folder.mkdir(exist_ok=True)
            dst = sqlite3.connect(folder / f"lux-{before or 'first'}-{datetime.now():%Y%m%d-%H%M%S}.db")
            conn.backup(dst)
            dst.close()
            for old in sorted(folder.glob("lux-*.db"), key=lambda p: p.stat().st_mtime)[:-5]:
                old.unlink()
        db.set_meta(conn, "app_version", VERSION)
        conn.commit()
    except sqlite3.OperationalError:
        pass
    finally:
        conn.close()


def tick():
    conn = db.connect()
    try:
        if db.setting("updates") == "1" and parse_version(VERSION) and stale(conn, "update_checked"):
            check_update(conn)
            conn.commit()
        if db.setting("backup_dir") and stale(conn, "backup_at"):
            run_backup(conn)
            conn.commit()
    finally:
        conn.close()


def loop():
    while True:
        try:
            tick()
        except Exception as e:
            print("background task failed:", e)
        time.sleep(3600)


def start_background():
    if not state.started:
        state.started = True
        threading.Thread(target=loop, daemon=True).start()


def stop_server(restart=False, delay=0.4):
    def go():
        time.sleep(delay)
        state.restart = restart
        if state.server:
            state.server.should_exit = True

    threading.Thread(target=go, daemon=True).start()


PICK_MAC = {
    "folder": 'POSIX path of (choose folder with prompt "Choose a folder")',
    "zip": 'POSIX path of (choose file with prompt "Choose a backup .zip" of type {"zip"})',
}
PICK_WIN = {
    "folder": "$d = New-Object System.Windows.Forms.FolderBrowserDialog; $d.Description = 'Choose a folder'; $d.ShowNewFolderButton = $true",
    "zip": "$d = New-Object System.Windows.Forms.OpenFileDialog; $d.Filter = 'Backup (*.zip)|*.zip'",
}


def pick(kind):
    quiet = {"stdin": subprocess.DEVNULL, "capture_output": True, "timeout": 600}
    if sys.platform == "darwin":
        res = subprocess.run(["osascript", "-e", "tell me to activate", "-e", PICK_MAC[kind]], text=True, **quiet)
    elif sys.platform == "win32":
        script = (
            "Add-Type -AssemblyName System.Windows.Forms; [Console]::OutputEncoding = [Text.Encoding]::UTF8; "
            "$f = New-Object System.Windows.Forms.Form -Property @{TopMost = $true}; "
            f"{PICK_WIN[kind]}; "
            "if ($d.ShowDialog($f) -eq [System.Windows.Forms.DialogResult]::OK) { "
            + ("$d.SelectedPath" if kind == "folder" else "$d.FileName") + " }"
        )
        res = subprocess.run(
            ["powershell", "-NoProfile", "-STA", "-Command", script], encoding="utf-8",
            creationflags=subprocess.CREATE_NO_WINDOW, **quiet,
        )
    elif shutil.which("zenity"):
        args = ["--directory"] if kind == "folder" else ["--file-filter=*.zip"]
        res = subprocess.run(["zenity", "--file-selection", *args], text=True, **quiet)
    else:
        raise RuntimeError("No folder chooser on this system: type the path instead.")
    path = (res.stdout or "").strip()
    return path.rstrip("/\\") or path if path and res.returncode == 0 else None


def disk_free(path):
    try:
        return shutil.disk_usage(path).free
    except OSError:
        return None
