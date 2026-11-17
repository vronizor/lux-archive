import argparse
import json
import os
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

NAME = "Lux Archive"
LOCAL = urllib.request.build_opener(urllib.request.ProxyHandler({}))
PORTS = range(8410, 8420)


def default_data_dir():
    home = Path.home()
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / NAME
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA") or home / "AppData" / "Roaming") / NAME
    return Path(os.environ.get("XDG_DATA_HOME") or home / ".local" / "share") / "lux-archive"


def ping(port):
    try:
        with LOCAL.open(f"http://127.0.0.1:{port}/api/ping", timeout=1) as res:
            return json.load(res).get("app") == "lux-archive"
    except Exception:
        return False


def free(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def open_when_up(port):
    for _ in range(100):
        if ping(port):
            webbrowser.open(f"http://localhost:{port}/")
            return
        time.sleep(0.2)


def serve(port, data_dir):
    os.environ["DATA_DIR"] = str(data_dir)
    os.environ["LUX_DESKTOP"] = "1"
    if not getattr(sys, "frozen", False):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

    import uvicorn

    from app import db, desktop
    from app.main import app

    desktop.state.port = port
    while True:
        host = "0.0.0.0" if db.setting("lan") == "1" else "127.0.0.1"
        server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, access_log=False, use_colors=False))
        desktop.state.server, desktop.state.restart = server, False
        print(f"{NAME} on {host}:{port}, data in {data_dir}")
        server.run()
        if not desktop.state.restart:
            break


def main():
    parser = argparse.ArgumentParser(prog=NAME)
    parser.add_argument("--data-dir", default=os.environ.get("LUX_DATA_DIR"))
    parser.add_argument("--port", type=int)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--no-tray", action="store_true")
    args, _ = parser.parse_known_args()
    frozen = getattr(sys, "frozen", False)
    here = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent)) / "desktop"

    data_dir = Path(args.data_dir).expanduser() if args.data_dir else default_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    if frozen or sys.stdout is None:
        sys.stdout = sys.stderr = open(data_dir / "lux.log", "a", buffering=1, encoding="utf-8")
    print(f"launch {time.strftime('%Y-%m-%d %H:%M:%S')}")

    port = args.port
    for candidate in ([port] if port else PORTS):
        if ping(candidate):
            if not args.no_browser:
                webbrowser.open(f"http://localhost:{candidate}/")
            return
        if port or free(candidate):
            port = candidate
            break
    else:
        sys.exit("no free port")

    def open_page():
        print("open page")
        if not args.no_browser:
            webbrowser.open(f"http://localhost:{port}/")

    def quit_app():
        from app import desktop

        desktop.stop_server(delay=0)

    if not args.no_browser:
        threading.Thread(target=open_when_up, args=(port,), daemon=True).start()

    if sys.platform == "darwin" and not args.no_tray:
        def worker():
            try:
                serve(port, data_dir)
            finally:
                sys.stdout.flush()
                os._exit(0)

        threading.Thread(target=worker, daemon=True).start()
        try:
            sys.path.insert(0, str(here))
            import tray

            tray.run_mac(NAME, here / "tray.png", open_page, quit_app)
        except Exception as e:
            print("no menu bar icon:", e)
        threading.Event().wait()

    icon = None
    if sys.platform == "win32" and not args.no_tray:
        try:
            sys.path.insert(0, str(here))
            import tray

            icon = tray.start_windows(NAME, here / "tray.png", open_page, quit_app)
        except Exception as e:
            print("no tray icon:", e)
    serve(port, data_dir)
    if icon:
        try:
            icon.stop()
        except Exception:
            pass


if __name__ == "__main__":
    main()
