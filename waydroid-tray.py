#!/usr/bin/python3
"""System tray launcher for Waydroid (KDE Plasma).

Left click    open the selected target: the full Android UI or a pinned app
Middle click  start or stop the Waydroid session
Scroll        switch the selected target (full UI + pinned apps)
Right click   menu: open, session, click target, all apps, pins, icon style,
              start at login, quit

The tray icon is KDE's KStatusNotifierItem (its Python bindings ship with the
kstatusnotifieritem package), which implements the StatusNotifierItem and
dbusmenu protocols, including scroll and middle click. Session state comes from
watching Waydroid's id.waydro.Session name on the session bus, so nothing polls.

Apps are the waydroid.<package>.desktop files that Waydroid writes to
~/.local/share/applications; the menu follows installs and removals.
"""

import argparse
import html
import os
import re
import shutil
import signal
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

try:
    from KNotifications import KNotification
    from KStatusNotifierItem import KStatusNotifierItem
    from PySide6.QtCore import QFileSystemWatcher, QLockFile, QProcess, QSettings, QSize, Qt, QTimer
    from PySide6.QtDBus import QDBusConnection, QDBusServiceWatcher
    from PySide6.QtGui import QActionGroup, QIcon, QImage, QPainter, QPixmap
    from PySide6.QtWidgets import QApplication, QMenu
except ImportError as exc:
    sys.exit(f"waydroid-tray: missing Python module '{exc.name}'. Install pyside6 "
             "(kstatusnotifieritem and knotifications provide the KDE modules).")

__version__ = "0.1.0"

APP_ID = "waydroid-tray"
TITLE = "Waydroid Tray"
APP_ICON = "waydroid"
FALLBACK_ICON = "smartphone"
MONO_ICON = "smartphone-symbolic"
CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
DATA_HOME = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
APPS_DIR = DATA_HOME / "applications"
APP_FILE_RE = re.compile(r"^waydroid\.(.+)\.desktop$")
WAYDROID_CONFIG = Path("/var/lib/waydroid/waydroid.cfg")  # exists once `waydroid init` ran
# Per-user, so it shows in System Settings > Autostart (which lists only this folder).
AUTOSTART_FILE = CONFIG_HOME / "autostart" / f"{APP_ID}.desktop"
ICON_STYLES = {"color": "Color", "grayscale": "Grayscale", "monochrome": "Monochrome (follows theme)"}
ICON_SIZES = (16, 22, 24, 32, 48, 64, 128)
STOPPED_OPACITY = 0.45  # tray icon while the session is stopped
SCROLL_STEP = 120  # one mouse-wheel notch
SESSION_BUS_NAME = "id.waydro.Session"


# ------------------------------------------------------------------ targets

@dataclass(frozen=True)
class Target:
    key: str   # Android package name; "" for the full UI
    name: str
    icon: str  # image path or theme icon name


FULL_UI = Target("", "Full UI", APP_ICON)


def read_app(path: Path) -> Target | None:
    """A Waydroid app from its waydroid.<package>.desktop file."""
    if not (m := APP_FILE_RE.match(path.name)):
        return None
    entry: dict[str, str] = {}
    in_main = False
    try:
        with path.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if line.startswith("["):
                    in_main = line == "[Desktop Entry]"
                elif in_main and "=" in line:
                    key, value = line.split("=", 1)
                    entry.setdefault(key.strip(), value.strip())
    except OSError:
        return None
    package = m.group(1)
    return Target(package, entry.get("Name") or package, entry.get("Icon", ""))


def find_apps() -> list[Target]:
    if not APPS_DIR.is_dir():
        return []
    apps = (read_app(p) for p in APPS_DIR.glob("waydroid.*.desktop") if p.is_file())
    return sorted((a for a in apps if a), key=lambda a: a.name.lower())


# ---------------------------------------------------------------- autostart

def program_path() -> Path:
    return Path(os.path.realpath(__file__))


def autostart_enabled() -> bool:
    try:
        text = AUTOSTART_FILE.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return not re.search(r"^\s*Hidden\s*=\s*true\s*$", text, re.MULTILINE | re.IGNORECASE)


def set_autostart(enabled: bool) -> None:
    if not enabled:
        AUTOSTART_FILE.unlink(missing_ok=True)
        return
    exe = program_path()
    AUTOSTART_FILE.parent.mkdir(parents=True, exist_ok=True)
    # TryExec: once the program is uninstalled, the session skips this entry.
    AUTOSTART_FILE.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={TITLE}\n"
        "Comment=System tray launcher for Waydroid\n"
        f'Exec="{exe}"\n'
        f"TryExec={exe}\n"
        f"Icon={APP_ICON}\n"
        "Terminal=false\n", encoding="utf-8")


def seed_autostart(settings: QSettings) -> None:
    """Turn on start at login the first time an installed copy runs. Only once, so
    removing it (in the menu or System Settings) is respected."""
    if settings.value("autostart_seeded", False, type=bool):
        return
    if program_path().name != APP_ID:  # run from a source checkout (waydroid-tray.py)
        return
    try:
        if not AUTOSTART_FILE.exists():
            set_autostart(True)
    except OSError as exc:
        print(f"waydroid-tray: could not add the autostart entry: {exc}", file=sys.stderr)
        return
    settings.setValue("autostart_seeded", True)


# -------------------------------------------------------------------- icons

def load_icon(spec: str) -> QIcon:
    """QIcon for an image path or theme icon name, falling back to Waydroid's icon."""
    if spec.startswith("/"):
        if Path(spec).is_file():
            return QIcon(spec)
    elif spec and QIcon.hasThemeIcon(spec):
        return QIcon.fromTheme(spec)
    return QIcon.fromTheme(APP_ICON, QIcon.fromTheme(FALLBACK_ICON))


def menu_icon(target: Target) -> QIcon:
    return load_icon(target.icon) if target.icon else QIcon()


def grayscale(image: QImage) -> QImage:
    """Grayscale copy of image that keeps its transparency."""
    src = image.convertToFormat(QImage.Format.Format_ARGB32)
    src.setDevicePixelRatio(1.0)
    out = src.convertToFormat(QImage.Format.Format_Grayscale8).convertToFormat(
        QImage.Format.Format_ARGB32_Premultiplied)
    painter = QPainter(out)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
    painter.drawImage(0, 0, src)
    painter.end()
    return out


def faded(image: QImage, opacity: float) -> QImage:
    out = QImage(image.size(), QImage.Format.Format_ARGB32_Premultiplied)
    out.fill(Qt.GlobalColor.transparent)
    painter = QPainter(out)
    painter.setOpacity(opacity)
    painter.drawImage(0, 0, image)
    painter.end()
    return out


def styled_icon(icon: QIcon, gray: bool, opacity: float) -> QIcon:
    """icon rendered at the tray sizes, optionally grayscale and faded."""
    out = QIcon()
    for size in ICON_SIZES:
        image = icon.pixmap(QSize(size, size), 1.0).toImage()
        if image.isNull():
            continue
        if gray:
            image = grayscale(image)
        if opacity < 1.0:
            image = faded(image, opacity)
        out.addPixmap(QPixmap.fromImage(image))
    return out


# ---------------------------------------------------------------------- app

class WaydroidTray:
    def __init__(self, app: QApplication):
        self.app = app
        self.settings = QSettings(APP_ID, APP_ID)
        self.waydroid = shutil.which("waydroid")
        self.systemd_run = shutil.which("systemd-run")
        self.apps: list[Target] = []
        self._scroll_accum = 0

        self.item = KStatusNotifierItem(APP_ID)  # stable Id: listed in System Tray Settings
        self.item.setCategory(KStatusNotifierItem.ItemCategory.ApplicationStatus)
        self.item.setTitle(TITLE)
        self.item.setToolTipTitle(TITLE)
        self.item.setToolTipIconByName(APP_ICON)
        self.item.setStandardActionsEnabled(False)  # our menu has its own Quit
        self.item.setStatus(KStatusNotifierItem.ItemStatus.Active)
        self.menu = QMenu()
        self.item.setContextMenu(self.menu)  # the item takes ownership
        self.item.activateRequested.connect(lambda *_: self.open())
        self.item.secondaryActivateRequested.connect(lambda *_: self.toggle_session())
        self.item.scrollRequested.connect(self.scroll)

        bus = QDBusConnection.sessionBus()
        reply = bus.interface().isServiceRegistered(SESSION_BUS_NAME)
        self.running = bool(reply.value()) if reply.isValid() else False
        self.session_watcher = QDBusServiceWatcher(
            SESSION_BUS_NAME, bus, QDBusServiceWatcher.WatchModeFlag.WatchForOwnerChange)
        self.session_watcher.serviceOwnerChanged.connect(self.on_session_owner)

        seed_autostart(self.settings)
        AUTOSTART_FILE.parent.mkdir(parents=True, exist_ok=True)
        # Watches the apps folder (Waydroid adds and removes .desktop files there) and the
        # autostart folder (Start at Login, which System Settings > Autostart can change too).
        self.watcher = QFileSystemWatcher()
        self.watcher.directoryChanged.connect(self.schedule_reload)
        self.watcher.fileChanged.connect(self.schedule_reload)
        self.reload_timer = QTimer(singleShot=True, interval=500)
        self.reload_timer.timeout.connect(self.reload)
        self.reload()

    # ---- state ------------------------------------------------------------

    @property
    def pinned(self) -> set[str]:
        return {p for p in self.settings.value("pinned", "", type=str).split(",") if p}

    @property
    def targets(self) -> list[Target]:
        """What left click can open and scroll cycles through."""
        pinned = self.pinned
        return [FULL_UI, *(a for a in self.apps if a.key in pinned)]

    @property
    def selected(self) -> Target:
        key = self.settings.value("selected", "", type=str)
        return next((t for t in self.targets if t.key == key), FULL_UI)

    def select(self, target: Target) -> None:
        self.settings.setValue("selected", target.key)
        self.refresh()

    def set_pinned(self, target: Target, pinned: bool) -> None:
        keys = self.pinned
        if pinned:
            keys.add(target.key)
        else:
            keys.discard(target.key)
            if self.settings.value("selected", "", type=str) == target.key:
                self.settings.setValue("selected", FULL_UI.key)
        self.settings.setValue("pinned", ",".join(sorted(keys)))
        self.refresh()

    @property
    def icon_style(self) -> str:
        style = self.settings.value("icon_style", "color", type=str)
        return style if style in ICON_STYLES else "color"

    def set_icon_style(self, style: str) -> None:
        self.settings.setValue("icon_style", style)
        self.refresh()

    def on_session_owner(self, _name: str, _old: str, new: str) -> None:
        self.running = bool(new)
        self.refresh()

    def schedule_reload(self, *_) -> None:
        self.reload_timer.start()

    def reload(self) -> None:
        self.apps = find_apps()
        if files := self.watcher.files():
            self.watcher.removePaths(files)
        watched = set(self.watcher.directories())
        for folder in (APPS_DIR, AUTOSTART_FILE.parent):
            if folder.is_dir() and str(folder) not in watched:
                self.watcher.addPath(str(folder))
        if AUTOSTART_FILE.is_file():
            self.watcher.addPath(str(AUTOSTART_FILE))
        self.refresh()

    def refresh(self) -> None:
        self.update_icon()
        self.build_menu()

    # ---- presentation -----------------------------------------------------

    def primary_label(self) -> str:
        target = self.selected
        return "Open Full UI" if target is FULL_UI else f"Open {target.name}"

    def session_label(self) -> str:
        return "Stop Session" if self.running else "Start Session"

    def update_icon(self) -> None:
        style = self.icon_style
        opacity = 1.0 if self.running else STOPPED_OPACITY
        if style == "monochrome" and QIcon.hasThemeIcon(MONO_ICON):
            if self.running:
                self.item.setIconByName(MONO_ICON)  # by name, so Plasma recolors it
            else:
                self.item.setIconByPixmap(styled_icon(QIcon.fromTheme(MONO_ICON), False, opacity))
        else:
            # Monochrome without a symbolic icon in the theme: grayscale is the closest match.
            spec = "" if style == "monochrome" else self.selected.icon
            self.item.setIconByPixmap(styled_icon(load_icon(spec), style != "color", opacity))

        state = "Running" if self.running else "Stopped"
        scroll = ("Scroll: switch app" if len(self.targets) > 1
                  else "Pin apps in the menu to switch with scroll")
        self.item.setToolTipSubTitle("<br>".join([
            f"Session: <b>{state}</b>",
            f"Click: <b>{html.escape(self.primary_label())}</b>",
            f"Middle-click: {self.session_label()}",
            scroll,
        ]))

    def build_menu(self) -> None:
        m = self.menu
        m.clear()
        for kind in (QMenu, QActionGroup):  # submenus and groups from the previous build
            for child in m.findChildren(kind, options=Qt.FindChildOption.FindDirectChildrenOnly):
                child.deleteLater()

        def label(text: str) -> str:
            return text.replace("&", "&&")  # "&" marks mnemonics

        def add(menu: QMenu, text: str, slot, icon: QIcon | str = "", checked: bool | None = None,
                group: QActionGroup | None = None):
            icon = QIcon.fromTheme(icon) if isinstance(icon, str) else icon
            action = menu.addAction(icon, label(text))
            if checked is not None:
                action.setCheckable(True)
                action.setChecked(checked)
            if group:
                group.addAction(action)
            action.triggered.connect(lambda *_: QTimer.singleShot(0, slot))
            return action

        selected = self.selected
        add(m, self.primary_label(), self.open,
            icon="view-fullscreen" if selected is FULL_UI else menu_icon(selected))
        add(m, self.session_label(), self.toggle_session,
            icon="media-playback-stop" if self.running else "media-playback-start")
        m.addSeparator()

        m.addAction(label("Click Opens")).setEnabled(False)
        group = QActionGroup(m)
        for t in self.targets:
            add(m, t.name, lambda t=t: self.select(t), icon=menu_icon(t),
                checked=t.key == selected.key, group=group)

        apps = m.addMenu(QIcon.fromTheme("view-list-icons"), "Apps")
        pins = m.addMenu(QIcon.fromTheme("pin"), "Pinned Apps")
        if not self.apps:
            for sub in (apps, pins):
                sub.addAction("No Waydroid apps found").setEnabled(False)
        pinned = self.pinned
        for a in self.apps:
            add(apps, a.name, lambda a=a: self.open(a), icon=menu_icon(a))
            add(pins, a.name, lambda a=a, on=a.key not in pinned: self.set_pinned(a, on),
                icon=menu_icon(a), checked=a.key in pinned)
        m.addSeparator()

        icons = m.addMenu(QIcon.fromTheme("preferences-desktop-icons"), "Tray Icon")
        style_group = QActionGroup(icons)
        for style, text in ICON_STYLES.items():
            add(icons, text, lambda s=style: self.set_icon_style(s),
                checked=style == self.icon_style, group=style_group)
        add(m, "Start at Login", self.toggle_autostart, checked=autostart_enabled())
        m.addSeparator()
        add(m, "Quit", self.app.quit, icon="application-exit")

    # ---- input ------------------------------------------------------------

    def scroll(self, delta: int, orientation) -> None:
        targets = self.targets
        if orientation != Qt.Orientation.Vertical or len(targets) < 2:
            return
        self._scroll_accum += delta
        steps = 0
        while abs(self._scroll_accum) >= SCROLL_STEP:
            step = -1 if self._scroll_accum > 0 else 1  # wheel down = next target
            self._scroll_accum += SCROLL_STEP * step
            steps += step
        if steps:
            keys = [t.key for t in targets]
            index = keys.index(self.selected.key)
            self.select(targets[(index + steps) % len(targets)])

    # ---- actions ----------------------------------------------------------

    def open(self, target: Target | None = None) -> None:
        target = target or self.selected
        if target is FULL_UI:
            self.run_waydroid(["show-full-ui"])
        else:
            self.run_waydroid(["app", "launch", target.key])

    def toggle_session(self) -> None:
        self.run_waydroid(["session", "stop" if self.running else "start"])

    def run_waydroid(self, args: list[str]) -> None:
        if not self.waydroid:
            self.notify("waydroid was not found on PATH.")
            return
        if not WAYDROID_CONFIG.exists():
            self.notify("Waydroid is not set up yet. Run “sudo waydroid init” first.")
            return
        cmd = [self.waydroid, *args]
        if self.systemd_run:
            # Own scope: when the session is stopped, `waydroid app launch` and
            # `show-full-ui` become the session process, which must outlive the tray.
            cmd = [self.systemd_run, "--user", "--scope", "--collect", "--quiet",
                   "--slice=app.slice", f"--unit=app-{APP_ID}-waydroid-{uuid.uuid4().hex[:8]}",
                   *cmd]
        ok, _pid = QProcess.startDetached(cmd[0], cmd[1:], str(Path.home()))
        if not ok:
            self.notify(f"Failed to run “waydroid {' '.join(args)}”.")

    def toggle_autostart(self) -> None:
        try:
            set_autostart(not autostart_enabled())
        except OSError as exc:
            self.notify(f"Could not change the autostart entry: {exc}")
        self.reload()  # also re-watches the folder if it was deleted and recreated

    def notify(self, text: str) -> None:
        print(f"waydroid-tray: {text}", file=sys.stderr, flush=True)
        KNotification.event(KNotification.StandardEvent.Error, TITLE, text, APP_ICON)


class SelfRestarter:
    """Re-exec this program when its file is replaced, e.g. by a package upgrade,
    so users never keep running the old version until their next login."""

    PACMAN_LOCK = Path("/var/lib/pacman/db.lck")
    MAX_WAIT = 600  # seconds to wait for a package transaction to finish

    def __init__(self, app: QApplication, lock: QLockFile):
        self.app = app
        self.lock = lock
        self.path = program_path()
        self.original = self._stat()
        self.pending = None
        self.waited = 0
        self.watcher = QFileSystemWatcher([str(self.path)])
        self.watcher.fileChanged.connect(self.on_changed)
        self.timer = QTimer(interval=1000)
        self.timer.timeout.connect(self.check)

    def _stat(self):
        try:
            st = self.path.stat()
        except OSError:
            return None
        return st.st_ino, st.st_mtime_ns, st.st_size

    def on_changed(self, _path: str) -> None:
        if not self.timer.isActive():
            self.waited, self.pending = 0, None
            self.timer.start()

    def check(self) -> None:
        self.waited += 1
        if self.PACMAN_LOCK.exists() and self.waited < self.MAX_WAIT:
            return  # package transaction (maybe also upgrading our deps) still running
        current = self._stat()
        if current is None:
            if self.waited >= 3:  # program was uninstalled
                self.timer.stop()
                print("waydroid-tray: program file removed, exiting", file=sys.stderr, flush=True)
                self.app.quit()
            return
        if current == self.original:  # touched but not changed
            self.timer.stop()
            self.watcher.addPath(str(self.path))
            return
        if current != self.pending:  # wait until the file has been stable for a second
            self.pending = current
            return
        self.timer.stop()
        print("waydroid-tray: program updated, restarting", file=sys.stderr, flush=True)
        self.lock.unlock()  # the new process image takes the lock again
        if os.access(self.path, os.X_OK):  # keeps the process name "waydroid-tray"
            os.execv(self.path, [str(self.path), *sys.argv[1:]])
        os.execv(sys.executable, [sys.executable, str(self.path), *sys.argv[1:]])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="waydroid-tray",
        description="System tray launcher for Waydroid (KDE Plasma). "
                    f"Apps are read from {APPS_DIR}/waydroid.*.desktop.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser.parse_args()


def main() -> int:
    parse_args()
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_ID)
    app.setApplicationDisplayName(TITLE)
    app.setDesktopFileName(APP_ID)
    app.setQuitOnLastWindowClosed(False)

    runtime = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
    lock = QLockFile(os.path.join(runtime, f"{APP_ID}.lock"))
    if not lock.tryLock(100):
        print("waydroid-tray is already running.", file=sys.stderr)
        return 0

    _tray = WaydroidTray(app)
    # Not under a debugger: re-exec would detach it.
    _restarter = None if "debugpy" in sys.modules else SelfRestarter(app, lock)
    print(f"waydroid-tray {__version__} started", file=sys.stderr, flush=True)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
