import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

root = Path(SPECPATH).parent
sys.path.insert(0, str(root))
from app.version import VERSION

NAME = "Lux Archive"
datas = [(str(root / "app" / d), f"app/{d}") for d in ("templates", "static", "starter")]
hidden = collect_submodules("uvicorn") + collect_submodules("markdown") + ["app.main", "app.backup", "tray"]
datas.append((str(root / "desktop" / "tray.png"), "desktop"))
if sys.platform == "win32":
    hidden += ["pystray._win32"]

a = Analysis(
    [str(root / "desktop" / "launcher.py")],
    pathex=[str(root), str(root / "desktop")],
    datas=datas,
    hiddenimports=hidden,
    excludes=["tkinter", "numpy", "PIL.ImageQt", "PIL.ImageTk"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name=NAME, console=False,
    icon=str(root / "desktop" / ("icon.icns" if sys.platform == "darwin" else "icon.ico")),
)
coll = COLLECT(exe, a.binaries, a.datas, name=NAME)
if sys.platform == "darwin":
    BUNDLE(
        coll, name=f"{NAME}.app", icon=str(root / "desktop" / "icon.icns"),
        bundle_identifier="net.vronizor.lux-archive",
        info_plist={
            "LSUIElement": True,
            "CFBundleShortVersionString": VERSION.lstrip("v") if VERSION != "dev" else "0",
            "NSHighResolutionCapable": True,
        },
    )
