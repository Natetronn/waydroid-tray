# Waydroid Tray

A KDE Plasma system tray icon for [Waydroid](https://waydro.id).

| Input        | Action                                                         |
| ------------ | -------------------------------------------------------------- |
| Left click   | Open the selected target: the full Android UI or a pinned app  |
| Middle click | Start or stop the Waydroid session                             |
| Scroll       | Switch the selected target (full UI and pinned apps)           |
| Right click  | Menu: open, session, click target, all apps, pins, icon style, start at login, quit |

The icon is dimmed while the session is stopped, and the tooltip shows the
session state. Opening an app or the full UI while the session is stopped
starts it.

The icon appears in **System Tray Settings → Entries** as *Waydroid Tray*,
where it can be set to *Shown when relevant*, *Always shown*, *Always hidden*
or *Disabled*. It must be running to be listed there.

## Install

**From source, per user (no root):**

```sh
./install.sh      # installs to ~/.local and starts it
./uninstall.sh    # removes it (keeps your settings)
```

**From source, system-wide:** `sudo make install PREFIX=/usr`

The first time it runs, it adds itself to `~/.config/autostart`, so it starts
at every login. Turn that off with **Start at Login** in its menu, or remove it
in **System Settings → Autostart**; either way it stays off. **Quit** in the
menu stops it until next login. After an upgrade a running tray restarts
itself, so the new version is active straight away.

Requirements (all in the Arch repos): `waydroid` (initialized with
`waydroid init`), `pyside6`, `kstatusnotifieritem` and `knotifications`. The
last two come with Plasma; their Python modules need `pyside6`.

## Apps and pins

The app list comes from the `waydroid.<package>.desktop` files Waydroid writes
to `~/.local/share/applications`, so it follows app installs and removals.

- **Apps** opens any app once.
- **Pinned Apps** chooses which apps join *Click Opens* and the scroll cycle.

## Icon styles

*Tray Icon* in the menu: **Color** (the selected app's icon, or Waydroid's),
**Grayscale**, or **Monochrome**, which uses the theme's symbolic phone icon
and follows the panel's light/dark colors.

## Settings

Stored in `~/.config/waydroid-tray/waydroid-tray.conf` (selected target,
pinned apps, icon style, and whether the autostart entry has been added once).

## How it works

The tray icon is KDE's `KStatusNotifierItem` through its official PySide6
bindings, which handle the StatusNotifierItem and dbusmenu protocols, including
scroll and middle click. Session state comes from watching Waydroid's
`id.waydro.Session` name on the session bus, so nothing polls.

Apps, the full UI and the session are started with the `waydroid` CLI, each in
its own systemd scope. That matters because when the session is stopped,
`waydroid app launch` and `show-full-ui` become the session process, and it
must outlive the tray.

## License

MIT, see [LICENSE](LICENSE).
