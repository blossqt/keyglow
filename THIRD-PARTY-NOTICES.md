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

## Keyglow Lights (`lights\`)

The small service that sets the memory's lights carries these, unchanged, as the DLLs in
`lights\service\`:

| Component | Licence | Source |
|-----------|---------|--------|
| LibreHardwareMonitorLib 0.9.6 | MPL-2.0 | https://github.com/LibreHardwareMonitor/LibreHardwareMonitor |
| BlackSharp.Core 1.0.7 | MPL-2.0 | https://github.com/Blacktempel/BlackSharp |
| DiskInfoToolkit 1.1.2 | MPL-2.0 | https://github.com/Blacktempel/DiskInfoToolkit |
| RAMSPDToolkit-NDD 1.4.2 | MPL-2.0 | https://github.com/Blacktempel/RAMSPDToolkit |
| HidSharp 2.6.4 | Apache-2.0 | https://software.seekye.com/hidsharp |
| Mono.Posix.NETStandard 1.0.0 | MIT | https://github.com/mono/mono |
| System.Management, System.IO.Ports, System.CodeDom, System.Diagnostics.EventLog, System.ServiceProcess.ServiceController | MIT | https://github.com/dotnet/dotnet |

The MPL-2.0 components' source is at the addresses above; Keyglow changes none of them. The service
uses only the signed PawnIO SMBus modules LibreHardwareMonitorLib carries, through PawnIO
(https://pawnio.eu), which is installed separately.

## OpenRGB's protocol notes

How Corsair's RGB memory and ASRock's Polychrome USB controller are spoken to follows OpenRGB's
drivers for them (https://gitlab.com/CalcProgrammer1/OpenRGB, GPL-2.0-or-later). Keyglow's code
for both is its own; none of OpenRGB's is included.
