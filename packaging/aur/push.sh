#!/usr/bin/env bash
# Push the AUR package files in this folder to the AUR. The AUR repo is cloned into a temporary
# folder, updated, committed and pushed, and the folder is deleted, so no AUR clone is kept around.
# Needs your AUR SSH key (it asks for its passphrase).
#   packaging/aur/push.sh
set -euo pipefail
cd "$(dirname "$0")"
src="$(pwd)"
files=(PKGBUILD .SRCINFO waydroid-tray.install)
# AUR_REMOTE is the repo's SSH address; the default needs aur.archlinux.org to use your AUR key.
remote="${AUR_REMOTE:-ssh://aur@aur.archlinux.org/waydroid-tray.git}"

makepkg --printsrcinfo | cmp -s - .SRCINFO ||
  { echo ".SRCINFO does not match PKGBUILD (run makepkg --printsrcinfo > .SRCINFO)" >&2; exit 1; }

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
git clone -q "$remote" "$work/aur"
cp "${files[@]}" "$work/aur/"
cd "$work/aur"
git add "${files[@]}"
if git diff --cached --quiet; then
  echo "The AUR already has these files."
else
  ver="$(sed -n 's/^\s*pkgver = //p' .SRCINFO)-$(sed -n 's/^\s*pkgrel = //p' .SRCINFO)"
  git commit -q -m "Update to $ver"
  git push -q origin HEAD:master
  echo "Pushed $ver to the AUR."
fi
