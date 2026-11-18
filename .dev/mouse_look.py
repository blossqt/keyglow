"""Read-only: what HID interfaces a mouse has (names, usages, report sizes). Sends nothing."""
import ctypes
import sys
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from keyglow import hid  # noqa: E402

VID = int(sys.argv[1], 16) if len(sys.argv) > 1 else 0x373E
k32 = ctypes.WinDLL('kernel32', use_last_error=True)
h = ctypes.WinDLL('hid')
h.HidD_GetProductString.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.ULONG]
h.HidD_GetManufacturerString.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.ULONG]

for path in hid._paths():
    if f'vid_{VID:04x}' not in path.lower():
        continue
    handle = hid._kernel32.CreateFileW(path, 0, 3, None, 3, 0, None)
    name = maker = ''
    caps = hid.HIDP_CAPS()
    if handle and handle != hid.INVALID_HANDLE_VALUE:
        buf = ctypes.create_unicode_buffer(128)
        if h.HidD_GetProductString(handle, buf, 256):
            name = buf.value
        if h.HidD_GetManufacturerString(handle, buf, 256):
            maker = buf.value
        pre = ctypes.c_void_p()
        if hid._hid.HidD_GetPreparsedData(handle, ctypes.byref(pre)):
            hid._hid.HidP_GetCaps(pre, ctypes.byref(caps))
            hid._hid.HidD_FreePreparsedData(pre)
        hid._kernel32.CloseHandle(handle)
    tail = path.lower().split('#')[1]
    print(f'{tail:40} {maker!r} {name!r} page={caps.UsagePage:04X} usage={caps.Usage:02X} '
          f'in={caps.InputReportByteLength} out={caps.OutputReportByteLength} feat={caps.FeatureReportByteLength}')
