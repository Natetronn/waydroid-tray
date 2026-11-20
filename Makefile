# System install (packages):  make install DESTDIR="$pkgdir" PREFIX=/usr
# Per-user install:           ./install.sh  (wraps this with PREFIX=~/.local)

PREFIX       ?= /usr/local
BINDIR       ?= $(PREFIX)/bin
DATADIR      ?= $(PREFIX)/share
DOCDIR       ?= $(DATADIR)/doc/waydroid-tray
LICENSEDIR   ?= $(DATADIR)/licenses/waydroid-tray
# No autostart entry here: the app adds one per user on its first run
# (~/.config/autostart, which System Settings > Autostart lists).

all:

install:
	install -Dm755 waydroid-tray.py        "$(DESTDIR)$(BINDIR)/waydroid-tray"
	install -Dm644 waydroid-tray.desktop   "$(DESTDIR)$(DATADIR)/applications/waydroid-tray.desktop"
	install -Dm644 README.md               "$(DESTDIR)$(DOCDIR)/README.md"
	install -Dm644 LICENSE                 "$(DESTDIR)$(LICENSEDIR)/LICENSE"

uninstall:
	rm -f  "$(DESTDIR)$(BINDIR)/waydroid-tray" \
	       "$(DESTDIR)$(DATADIR)/applications/waydroid-tray.desktop" \
	       "$(DESTDIR)$(LICENSEDIR)/LICENSE"
	rm -rf "$(DESTDIR)$(DOCDIR)"
	-rmdir "$(DESTDIR)$(LICENSEDIR)" 2>/dev/null

.PHONY: all install uninstall
