import threading


def run_mac(title, icon_path, on_open, on_quit):
    from AppKit import (
        NSApplication, NSApplicationActivationPolicyAccessory, NSImage, NSMenu, NSMenuItem, NSStatusBar,
        NSVariableStatusItemLength,
    )
    from Foundation import NSObject

    class LuxDelegate(NSObject):
        def open_(self, sender):
            on_open()

        def quit_(self, sender):
            on_quit()

        def applicationShouldHandleReopen_hasVisibleWindows_(self, app, visible):
            print("reopen")
            on_open()
            return False

    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    delegate = LuxDelegate.alloc().init()
    app.setDelegate_(delegate)
    item = NSStatusBar.systemStatusBar().statusItemWithLength_(NSVariableStatusItemLength)
    image = NSImage.alloc().initWithContentsOfFile_(str(icon_path))
    if image:
        image.setSize_((18, 18))
        item.button().setImage_(image)
    else:
        item.button().setTitle_("Lux")
    item.button().setToolTip_(title)
    menu = NSMenu.alloc().init()
    for label, action in ((f"Open {title}", "open:"), (f"Quit {title}", "quit:")):
        entry = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(label, action, "")
        entry.setTarget_(delegate)
        menu.addItem_(entry)
    item.setMenu_(menu)
    print("menu bar icon ready")
    app.run()


def start_windows(title, icon_path, on_open, on_quit):
    import pystray
    from PIL import Image

    icon = pystray.Icon(
        "lux-archive", Image.open(icon_path), title,
        pystray.Menu(
            pystray.MenuItem(f"Open {title}", lambda: on_open(), default=True),
            pystray.MenuItem(f"Quit {title}", lambda: on_quit()),
        ),
    )

    def run():
        try:
            icon.run(lambda i: (setattr(i, "visible", True), print("tray icon ready")))
        except Exception as e:
            print("no tray icon:", e)

    threading.Thread(target=run, daemon=True).start()
    return icon
