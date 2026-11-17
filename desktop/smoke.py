"""Start the built app (or the launcher) and exercise it over HTTP. Usage: smoke.py <command...>"""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile

from PIL import Image

PORT = 8499
BASE = f"http://127.0.0.1:{PORT}"


class Quiet(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


opener = urllib.request.build_opener(Quiet, urllib.request.ProxyHandler({}))


def call(path, data=None, headers=None, expect=(200, 303)):
    req = urllib.request.Request(BASE + path, data=data, headers=headers or {})
    try:
        res = opener.open(req, timeout=60)
        status, body = res.status, res.read()
    except urllib.error.HTTPError as e:
        status, body = e.code, e.read()
    assert status in expect, f"{path}: {status}\n{body[:800].decode(errors='replace')}"
    return body


def form(path, **fields):
    return call(path, urllib.parse.urlencode(fields).encode(), {"Content-Type": "application/x-www-form-urlencoded"})


def upload(path, name, filename, content):
    boundary = uuid.uuid4().hex
    body = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
        "Content-Type: image/jpeg\r\n\r\n"
    ).encode() + content + f"\r\n--{boundary}--\r\n".encode()
    return call(path, body, {"Content-Type": f"multipart/form-data; boundary={boundary}"})


def main():
    data_dir = tempfile.mkdtemp(prefix="lux-smoke-")
    proc = subprocess.Popen([*sys.argv[1:], "--no-browser", "--port", str(PORT), "--data-dir", data_dir])
    try:
        for _ in range(150):
            try:
                assert json.loads(call("/api/ping"))["app"] == "lux-archive"
                break
            except Exception:
                assert proc.poll() is None, "the app exited during startup"
                time.sleep(0.4)
        else:
            raise AssertionError("the app never answered")

        form("/settings", name="Smoke Archive", prefix="q", catalog="Lightroom", binder="A")
        assert b"Q001" in call("/")
        form("/rolls", id="", contents="Été à Cadaqués", start_year="2019", start_season="Summer", binder="A", sleeve="1", filed="1")
        form("/load", camera="OM-10", stock="HP5+", ei="800")
        img = Image.new("RGB", (1200, 800), (200, 120, 60))
        buf = io.BytesIO()
        img.save(buf, "JPEG")
        upload("/rolls/Q001/photo", "photo", "sheet.jpg", buf.getvalue())
        page = call("/rolls/Q001").decode()
        assert "Été à Cadaqués" in page and "Lightroom" in page
        call("/rolls/Q001/view-1.jpg")
        call("/rolls/Q001/contact-1.jpg")
        home = call("/").decode()
        assert "OM-10" in home and "Smoke Archive" in home
        for path in ("/rolls", "/docs", "/field", "/settings", "/add", "/load", "/refile", "/import", "/notes/field/edit", "/export.csv"):
            call(path)
        assert "Q012" in call("/docs").decode()
        form("/notes/field", text="# Mes notes\n\nÉté, 1/60 s — f/8")
        assert "Mes notes" in call("/field").decode()
        z = zipfile.ZipFile(io.BytesIO(call("/desktop/backup.zip")))
        names = set(z.namelist())
        assert {"rolls.csv", "events.csv", "settings.json", "photos/Q001-1.jpg", "notes/field.md"} <= names, names
        assert "Été à Cadaqués" in z.read("rolls.csv").decode("utf-8")
        form("/desktop/backup", backup_dir=data_dir + "/backup-copy")
        call("/desktop/backup.zip", headers={"Host": "evil.example"}, expect=(403,))
        for path in ("/sheets", "/field", "/docs"):
            call(path)
        form("/desktop/quit")
        proc.wait(timeout=30)
        log = Path(data_dir, "lux.log")
        if log.exists():
            print(log.read_text(encoding="utf-8", errors="replace"))
            if os.environ.get("RUNNER_TEMP"):
                Path(os.environ["RUNNER_TEMP"], "lux-smoke-log.txt").write_text(log.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
        print("smoke test passed")
    finally:
        if proc.poll() is None:
            proc.kill()


if __name__ == "__main__":
    main()
