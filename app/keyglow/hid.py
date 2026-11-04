"""Talking to a HID device on Windows through hid.dll and SetupAPI, with ctypes: finding the
Drop ALT's interfaces, and sending and receiving its 32-byte raw HID reports."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass

_setupapi = ctypes.WinDLL('setupapi', use_last_error=True)
_hid = ctypes.WinDLL('hid', use_last_error=True)
_kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

DIGCF_PRESENT = 0x02
DIGCF_DEVICEINTERFACE = 0x10
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x01
FILE_SHARE_WRITE = 0x02
OPEN_EXISTING = 3
FILE_FLAG_OVERLAPPED = 0x40000000
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
WAIT_OBJECT_0 = 0
ERROR_IO_PENDING = 997
HIDP_STATUS_SUCCESS = 0x00110000


class GUID(ctypes.Structure):
    _fields_ = [('Data1', wintypes.DWORD), ('Data2', wintypes.WORD), ('Data3', wintypes.WORD),
                ('Data4', ctypes.c_ubyte * 8)]


class SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
    _fields_ = [('cbSize', wintypes.DWORD), ('InterfaceClassGuid', GUID), ('Flags', wintypes.DWORD),
                ('Reserved', ctypes.c_void_p)]


class HIDD_ATTRIBUTES(ctypes.Structure):
    _fields_ = [('Size', wintypes.ULONG), ('VendorID', wintypes.USHORT), ('ProductID', wintypes.USHORT),
                ('VersionNumber', wintypes.USHORT)]


class HIDP_CAPS(ctypes.Structure):
    _fields_ = [('Usage', wintypes.USHORT), ('UsagePage', wintypes.USHORT),
                ('InputReportByteLength', wintypes.USHORT), ('OutputReportByteLength', wintypes.USHORT),
                ('FeatureReportByteLength', wintypes.USHORT), ('Reserved', wintypes.USHORT * 17),
                ('NumberLinkCollectionNodes', wintypes.USHORT), ('NumberInputButtonCaps', wintypes.USHORT),
                ('NumberInputValueCaps', wintypes.USHORT), ('NumberInputDataIndices', wintypes.USHORT),
                ('NumberOutputButtonCaps', wintypes.USHORT), ('NumberOutputValueCaps', wintypes.USHORT),
                ('NumberOutputDataIndices', wintypes.USHORT), ('NumberFeatureButtonCaps', wintypes.USHORT),
                ('NumberFeatureValueCaps', wintypes.USHORT), ('NumberFeatureDataIndices', wintypes.USHORT)]


class OVERLAPPED(ctypes.Structure):
    _fields_ = [('Internal', ctypes.c_void_p), ('InternalHigh', ctypes.c_void_p), ('Offset', wintypes.DWORD),
                ('OffsetHigh', wintypes.DWORD), ('hEvent', wintypes.HANDLE)]


_hid.HidD_GetHidGuid.argtypes = [ctypes.POINTER(GUID)]
_hid.HidD_GetAttributes.argtypes = [wintypes.HANDLE, ctypes.POINTER(HIDD_ATTRIBUTES)]
_hid.HidD_GetAttributes.restype = wintypes.BOOLEAN
_hid.HidD_GetPreparsedData.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_void_p)]
_hid.HidD_GetPreparsedData.restype = wintypes.BOOLEAN
_hid.HidD_FreePreparsedData.argtypes = [ctypes.c_void_p]
_hid.HidP_GetCaps.argtypes = [ctypes.c_void_p, ctypes.POINTER(HIDP_CAPS)]
_hid.HidP_GetCaps.restype = ctypes.c_long
_setupapi.SetupDiGetClassDevsW.argtypes = [ctypes.POINTER(GUID), wintypes.LPCWSTR, wintypes.HWND, wintypes.DWORD]
_setupapi.SetupDiGetClassDevsW.restype = ctypes.c_void_p
_setupapi.SetupDiEnumDeviceInterfaces.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(GUID),
                                                  wintypes.DWORD, ctypes.POINTER(SP_DEVICE_INTERFACE_DATA)]
_setupapi.SetupDiEnumDeviceInterfaces.restype = wintypes.BOOL
_setupapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [ctypes.c_void_p, ctypes.POINTER(SP_DEVICE_INTERFACE_DATA),
                                                       ctypes.c_void_p, wintypes.DWORD,
                                                       ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
_setupapi.SetupDiGetDeviceInterfaceDetailW.restype = wintypes.BOOL
_setupapi.SetupDiDestroyDeviceInfoList.argtypes = [ctypes.c_void_p]
_kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                  wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
_kernel32.CreateFileW.restype = wintypes.HANDLE
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
_kernel32.CreateEventW.restype = wintypes.HANDLE
_kernel32.WriteFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                                ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(OVERLAPPED)]
_kernel32.ReadFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                               ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(OVERLAPPED)]
_kernel32.GetOverlappedResult.argtypes = [wintypes.HANDLE, ctypes.POINTER(OVERLAPPED),
                                          ctypes.POINTER(wintypes.DWORD), wintypes.BOOL]
_kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
_kernel32.WaitForSingleObject.restype = wintypes.DWORD
_kernel32.CancelIo.argtypes = [wintypes.HANDLE]
_kernel32.ResetEvent.argtypes = [wintypes.HANDLE]


@dataclass(frozen=True)
class Interface:
    path: str
    vid: int
    pid: int
    usage_page: int
    usage: int
    report_in: int      # bytes, the report id's included
    report_out: int


def _paths() -> list[str]:
    guid = GUID()
    _hid.HidD_GetHidGuid(ctypes.byref(guid))
    devs = _setupapi.SetupDiGetClassDevsW(ctypes.byref(guid), None, None, DIGCF_PRESENT | DIGCF_DEVICEINTERFACE)
    if not devs or devs == INVALID_HANDLE_VALUE:
        return []
    paths = []
    try:
        index = 0
        while True:
            data = SP_DEVICE_INTERFACE_DATA()
            data.cbSize = ctypes.sizeof(SP_DEVICE_INTERFACE_DATA)
            if not _setupapi.SetupDiEnumDeviceInterfaces(devs, None, ctypes.byref(guid), index, ctypes.byref(data)):
                break
            index += 1
            needed = wintypes.DWORD()
            _setupapi.SetupDiGetDeviceInterfaceDetailW(devs, ctypes.byref(data), None, 0, ctypes.byref(needed), None)
            buffer = ctypes.create_string_buffer(needed.value + 4)
            # SP_DEVICE_INTERFACE_DETAIL_DATA_W: a DWORD cbSize (8 on 64-bit), then the path
            ctypes.cast(buffer, ctypes.POINTER(wintypes.DWORD))[0] = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6
            if _setupapi.SetupDiGetDeviceInterfaceDetailW(devs, ctypes.byref(data), buffer, needed, None, None):
                paths.append(ctypes.wstring_at(ctypes.addressof(buffer) + 4))
    finally:
        _setupapi.SetupDiDestroyDeviceInfoList(devs)
    return paths


def _describe(path: str) -> Interface | None:
    # No access asked for: enough to read what an interface is, even a keyboard's Windows holds.
    handle = _kernel32.CreateFileW(path, 0, FILE_SHARE_READ | FILE_SHARE_WRITE, None, OPEN_EXISTING, 0, None)
    if not handle or handle == INVALID_HANDLE_VALUE:
        return None
    try:
        attributes = HIDD_ATTRIBUTES()
        attributes.Size = ctypes.sizeof(HIDD_ATTRIBUTES)
        if not _hid.HidD_GetAttributes(handle, ctypes.byref(attributes)):
            return None
        preparsed = ctypes.c_void_p()
        caps = HIDP_CAPS()
        if _hid.HidD_GetPreparsedData(handle, ctypes.byref(preparsed)):
            try:
                if _hid.HidP_GetCaps(preparsed, ctypes.byref(caps)) != HIDP_STATUS_SUCCESS:
                    return None
            finally:
                _hid.HidD_FreePreparsedData(preparsed)
        return Interface(path, attributes.VendorID, attributes.ProductID, caps.UsagePage, caps.Usage,
                         caps.InputReportByteLength, caps.OutputReportByteLength)
    finally:
        _kernel32.CloseHandle(handle)


def interfaces(vid: int, pid: int) -> list[Interface]:
    """Every HID interface of the device with that vendor and product id that is plugged in."""
    tag = f'vid_{vid:04x}&pid_{pid:04x}'
    found = []
    for path in _paths():
        if tag in path.lower():
            described = _describe(path)
            if described is not None and described.vid == vid and described.pid == pid:
                found.append(described)
    return found


class HidError(OSError):
    pass


class Device:
    """One HID interface opened for reports both ways."""

    def __init__(self, interface: Interface):
        self.interface = interface
        self._handle = _kernel32.CreateFileW(interface.path, GENERIC_READ | GENERIC_WRITE,
                                             FILE_SHARE_READ | FILE_SHARE_WRITE, None, OPEN_EXISTING,
                                             FILE_FLAG_OVERLAPPED, None)
        if not self._handle or self._handle == INVALID_HANDLE_VALUE:
            raise HidError(ctypes.get_last_error(), 'could not open the keyboard')
        self._event = _kernel32.CreateEventW(None, True, False, None)
        self._size_in = interface.report_in or 33
        self._size_out = interface.report_out or 33

    def close(self) -> None:
        if self._handle:
            _kernel32.CancelIo(self._handle)
            _kernel32.CloseHandle(self._handle)
            _kernel32.CloseHandle(self._event)
            self._handle = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _io(self, call, buffer, size: int, timeout_ms: int) -> int:
        _kernel32.ResetEvent(self._event)
        overlapped = OVERLAPPED()
        overlapped.hEvent = self._event
        done = wintypes.DWORD()
        if not call(self._handle, buffer, size, None, ctypes.byref(overlapped)):
            error = ctypes.get_last_error()
            if error != ERROR_IO_PENDING:
                raise HidError(error, 'the keyboard did not take a report')
        if _kernel32.WaitForSingleObject(self._event, timeout_ms) != WAIT_OBJECT_0:
            _kernel32.CancelIo(self._handle)
            _kernel32.GetOverlappedResult(self._handle, ctypes.byref(overlapped), ctypes.byref(done), True)
            raise TimeoutError('the keyboard did not answer')
        if not _kernel32.GetOverlappedResult(self._handle, ctypes.byref(overlapped), ctypes.byref(done), False):
            raise HidError(ctypes.get_last_error(), 'a report to or from the keyboard failed')
        return done.value

    def write(self, data: bytes, timeout_ms: int = 1000) -> None:
        report = bytes([0]) + data              # report id 0
        report = report.ljust(self._size_out, b'\0')[:self._size_out]
        buffer = ctypes.create_string_buffer(report, len(report))
        self._io(_kernel32.WriteFile, buffer, len(report), timeout_ms)

    def read(self, timeout_ms: int = 1000) -> bytes:
        buffer = ctypes.create_string_buffer(self._size_in)
        got = self._io(_kernel32.ReadFile, buffer, self._size_in, timeout_ms)
        return buffer.raw[1:got]                # past the report id
