# AUR packaging

`PKGBUILD`, `waydroid-tray.install` and `.SRCINFO` are the contents of the AUR
repo (`ssh://aur@aur.archlinux.org/waydroid-tray.git`). They are edited here;
`push.sh` publishes them, so no separate AUR clone is needed.

Release steps:

1. Bump `__version__` in `waydroid-tray.py`, commit, tag `vX.Y.Z`, push the tag to GitHub.
2. Here: set `pkgver`, reset `pkgrel=1`, then
   ```sh
   updpkgsums                         # fills sha256sums from the GitHub tarball
   makepkg -si                        # test build + install
   makepkg --printsrcinfo > .SRCINFO
   ```
3. Commit and push these files to GitHub.
4. `./push.sh`: clones the AUR repo into a temporary folder, copies the three
   files in, commits "Update to X.Y.Z-N", pushes, and deletes the folder. It
   needs your AUR SSH key, so run it from your own terminal.

A fix to the packaging only (PKGBUILD or install script, same upstream
version): bump `pkgrel` instead, regenerate `.SRCINFO`, then steps 3 and 4.
