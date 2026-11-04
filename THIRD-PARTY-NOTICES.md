# Third-party notices

Keyglow's own code is under the MIT licence (LICENSE). It ships with, or is built from:

## QMK Firmware (GPL-2.0-or-later)

`keyglow/firmware/keyglow_alt.bin` is QMK Firmware 0.26.11 built for `massdrop/alt` with the
keymap in this repository's `firmware/keyglow/` folder, which is under the GPL-2.0-or-later like
QMK itself. QMK's source: https://github.com/qmk/qmk_firmware/tree/0.26.11 - the binary is built
from it, unchanged, by `firmware/build.sh`.

## mdloader (GPL-3.0)

`tools/mdloader.exe` is Massdrop's mdloader, built unchanged from
https://github.com/Massdrop/mdloader at commit c4d56b478da8a061231d1992a263a8a1ae5873c6
(`build/bootstrap.ps1`). Its licence is in `tools/mdloader-LICENSE.txt`; the Atmel files it
includes are under `tools/mdloader-LICENSE_ATMEL.txt`.

## Qt for Python (LGPL-3.0)

PySide6 and Qt, under the LGPL-3.0: https://www.qt.io/licensing

## Geist Serif (SIL Open Font License 1.1)

Vercel's Geist Serif, in `keyglow/ui/` with its licence (GeistSerif-OFL.txt).

## Lucide icons (ISC)

The line icons in `keyglow/ui/suiteicons.py` are Lucide's (lucide-static 1.57.0, ISC); the
licence is kept in that file.
