#!/bin/bash
# Builds Keyglow's firmware for the Drop ALT (v1) inside KeyglowBuild's MSYS2 (see build/bootstrap.ps1)
# and copies it into the app as app/keyglow/firmware/keyglow_alt.bin.
#
# QMK dropped the ALT v1 (its arm_atsam platform) after 0.26.x, so the build uses tag 0.26.11.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
BUILD="${KEYGLOW_BUILD:-/c/Users/haoch/AppData/Local/KeyglowBuild}"

export MSYSTEM=UCRT64
export PATH="$BUILD/bin:/ucrt64/bin:/usr/bin:$PATH"
export USERPROFILE="$(cygpath -w "$HOME" 2>/dev/null || echo 'C:\Users\haoch')"
export QMK_HOME="$BUILD/qmk"

KEYMAP="$QMK_HOME/keyboards/massdrop/alt/keymaps/keyglow"
rm -rf "$KEYMAP"
cp -r "$HERE/keyglow" "$KEYMAP"

cd "$QMK_HOME"
make -j8 massdrop/alt:keyglow 2>&1 | grep -E "error|warning|Error|\[OK\]|\[ERRORS\]|\[WARNINGS\]" || true
test -f massdrop_alt_keyglow.bin

mkdir -p "$HERE/../app/keyglow/firmware"
cp massdrop_alt_keyglow.bin "$HERE/../app/keyglow/firmware/keyglow_alt.bin"
ls -l "$HERE/../app/keyglow/firmware/keyglow_alt.bin"
