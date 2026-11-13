"""The memory sticks' lights, through Keyglow Lights.

A memory stick's lights hang off the PC's SMBus, which only a driver can reach. Keyglow Lights - a
small service of Keyglow's own (lights\\service, in C#) - reaches it through PawnIO, the driver
FanControl and OpenRGB use, and sets the effect on Corsair's RGB memory. Nothing listens: Keyglow
lays what it wants in shared memory (ASK, which signed-in users may write), sets an event
(WANTED), and reads the answer in another block (STATUS, which they may only read).

The service stops itself after a minute unasked; Keyglow starts it again when it next wants
something (signed-in users may start it, nothing more). Its setup (lights\\KeyglowLightsSetup.exe)
installs it into Program Files - checking every file against hashes built into itself - and is run
with administrator permission from the Memory page (run_setup).
"""

from __future__ import annotations

import ctypes
import os
import struct
import sys
import time
import winreg
from ctypes import wintypes
from dataclasses import dataclass, field, replace
from pathlib import Path

SERVICE = 'KeyglowLights'
STATUS = r'Global\KeyglowLights'
ASK = r'Global\KeyglowLightsAsk'
WANTED = r'Global\KeyglowLightsWanted'
STATUS_MAGIC, ASK_MAGIC, LAYOUT = 0x544C474B, 0x414C474B, 1
STATUS_SIZE, ASK_SIZE = 360, 64
LEDS = 12               # colours a request carries, one per light (sticks have 6 to 12)
INSTALLED = Path(os.environ.get('ProgramFiles', r'C:\Program Files')) / 'Keyglow Lights' / 'KeyglowLights.exe'
SETUP_ANSWERS = {
    0: '', 2: 'Administrator rights are required.',
    3: 'The service files do not match this build of Keyglow. Reinstall Keyglow.',
    4: 'The existing service did not stop. Restart Windows and try again.',
    5: 'The service files could not be copied.', 6: 'Windows did not register the service.',
}

# The service's answers (Status in Program.cs), and two of Keyglow's own
READY, NO_PAWNIO, NO_MEMORY, FAILED, STARTING = range(5)
NOT_INSTALLED, NOT_RUNNING = 10, 11

# Corsair's effects, by its numbers
COLOR_SHIFT, COLOR_PULSE, RAINBOW_WAVE, COLOR_WAVE, VISOR, RAIN, MARQUEE, RAINBOW, SEQUENTIAL = \
    0x00, 0x01, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09
STATIC = 0x10

_FILE_MAP_WRITE, _FILE_MAP_READ, _EVENT_MODIFY_STATE = 0x0002, 0x0004, 0x0002
_SC_MANAGER_CONNECT, _SERVICE_QUERY_STATUS, _SERVICE_START = 0x0001, 0x0004, 0x0010
_ERROR_SERVICE_ALREADY_RUNNING, _ERROR_CANCELLED = 1056, 1223
_STATES = {1: 'stopped', 2: 'starting', 3: 'stopping', 4: 'running', 5: 'continuing', 6: 'pausing', 7: 'paused'}

NAMES = {   # product id's high byte -> the model
    0x01: 'Corsair Vengeance RGB Pro DDR4', 0x02: 'Corsair Dominator Platinum RGB DDR4',
    0x03: 'Corsair Vengeance RGB Pro SL DDR4', 0x04: 'Corsair Vengeance RGB RS DDR4',
    0x06: 'Corsair Dominator Platinum RGB DDR5', 0x07: 'Corsair Vengeance RGB DDR5',
    0x08: 'Corsair Dominator Titanium RGB DDR5', 0x09: 'Corsair Vengeance RGB DDR5',
    0x0A: 'Corsair Vengeance Shugo Series DDR5', 0x0B: 'Corsair Vengeance RGB RS DDR5',
}


def _calls():
    kernel, advapi, shell = ctypes.WinDLL('kernel32', use_last_error=True), \
        ctypes.WinDLL('advapi32', use_last_error=True), ctypes.WinDLL('shell32', use_last_error=True)
    kernel.OpenFileMappingW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.OpenFileMappingW.restype = wintypes.HANDLE
    kernel.MapViewOfFile.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]
    kernel.MapViewOfFile.restype = ctypes.c_void_p
    kernel.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
    kernel.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.OpenEventW.restype = wintypes.HANDLE
    kernel.SetEvent.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    advapi.OpenSCManagerW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
    advapi.OpenSCManagerW.restype = wintypes.HANDLE
    advapi.OpenServiceW.argtypes = [wintypes.HANDLE, wintypes.LPCWSTR, wintypes.DWORD]
    advapi.OpenServiceW.restype = wintypes.HANDLE
    advapi.StartServiceW.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p]
    advapi.QueryServiceStatus.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    advapi.CloseServiceHandle.argtypes = [wintypes.HANDLE]
    shell.ShellExecuteExW.argtypes = [ctypes.c_void_p]
    return kernel, advapi, shell


_kernel, _advapi, _shell = _calls()


@dataclass(frozen=True)
class Stick:
    bus: int
    address: int
    pid: int
    leds: int
    firmware: str

    @property
    def name(self) -> str:
        return NAMES.get(self.pid >> 8, 'Corsair RGB memory')


@dataclass(frozen=True)
class Answer:
    status: int
    when: int = 0               # ms since 1970
    done: int = 0               # the last request set
    failed: int = 0             # the last request that failed
    sticks: tuple = ()
    message: str = ''
    sequence: int = 0
    took: bool = False          # the request this answers was set


@dataclass(frozen=True)
class Request:
    mode: int
    speed: int = 1              # 0 slow, 1 medium, 2 fast
    brightness: int = 255
    a: tuple = (255, 255, 255)
    b: tuple = (0, 0, 0)
    leds: tuple = field(default_factory=lambda: ((255, 255, 255),) * LEDS)
    direction: int = 1          # down
    random: bool = False

    def pack(self) -> bytes:
        leds = b''.join(bytes(c) for c in self.leds)
        assert len(leds) == LEDS * 3
        return bytes((self.mode, self.speed, 1 if self.random else 0, self.direction, self.brightness,
                      *self.a, *self.b, 0)) + leds


class Lights:
    """Keyglow Lights, seen from Keyglow: what it found, and the effect asked of it."""

    def __init__(self, status: str = STATUS, ask: str = ASK, wanted: str = WANTED, service: str | None = SERVICE):
        self.names = status, ask, wanted
        self.service = service
        self._status = self._ask = self._event = None       # (mapping, view), (mapping, view), event
        self._number = 0

    def close(self) -> None:
        for held in (self._status, self._ask):
            if held:
                _kernel.UnmapViewOfFile(held[1])
                _kernel.CloseHandle(held[0])
        if self._event:
            _kernel.CloseHandle(self._event)
        self._status = self._ask = self._event = None

    def _open(self) -> bool:
        status, ask, wanted = self.names
        if not self._status:
            self._status = _map(status, _FILE_MAP_READ, STATUS_SIZE)
        if not self._ask:
            self._ask = _map(ask, _FILE_MAP_WRITE, ASK_SIZE)
        if not self._event:
            self._event = _kernel.OpenEventW(_EVENT_MODIFY_STATE, False, wanted) or None
        return bool(self._status and self._ask and self._event)

    def running(self) -> str:
        """'running', 'stopped', 'missing' ... ('running' for a stand-in with no service)."""
        return service_state(self.service) if self.service else 'running'

    def answer(self) -> Answer:
        """What the service last said - or why there is nothing to say."""
        state = self.running()
        if state == 'missing':
            return Answer(NOT_INSTALLED)
        if state != 'running' or not self._open():
            return Answer(NOT_RUNNING if state != 'running' else STARTING)
        return _read_status(self._status[1]) or Answer(STARTING)

    def wake(self, wait: float = 6.0) -> Answer:
        """The service running and done looking for memory (started if it had stopped): its answer."""
        deadline = time.monotonic() + wait
        if self.service and self.running() == 'missing':
            return Answer(NOT_INSTALLED)
        if self.service and self.running() != 'running':
            start(self.service)
            started = time.time() * 1000
        else:
            started = 0
        while True:
            answer = self.answer()
            if answer.status not in (NOT_RUNNING, STARTING) and answer.when >= started - 1000:
                return answer
            if time.monotonic() > deadline:
                return answer
            time.sleep(0.05)

    def ask(self, request: Request, wait: float = 4.0) -> Answer:
        """The effect set on every stick found: the service's answer once it has (or gave up)."""
        answer = self.wake()
        if answer.status != READY:
            return answer
        self._number = max(self._number, answer.done, answer.failed) + 1
        number = self._number
        view = self._ask[1]
        sequence = struct.unpack_from('<I', ctypes.string_at(view + 8, 4))[0]
        odd = (sequence & ~1) + 1
        ctypes.memmove(view + 8, struct.pack('<I', odd), 4)
        ctypes.memmove(view, struct.pack('<II', ASK_MAGIC, LAYOUT), 8)
        ctypes.memmove(view + 12, struct.pack('<I', number), 4)
        body = request.pack()
        ctypes.memmove(view + 16, body, len(body))
        ctypes.memmove(view + 8, struct.pack('<I', odd + 1), 4)
        _kernel.SetEvent(self._event)
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            answer = self.answer()
            if answer.done == number or answer.failed == number:
                return replace(answer, took=answer.done == number)
            time.sleep(0.02)
        return answer


def _map(name: str, access: int, size: int):
    mapping = _kernel.OpenFileMappingW(access, False, name)
    if not mapping:
        return None
    view = _kernel.MapViewOfFile(mapping, access, 0, 0, size)
    if not view:
        _kernel.CloseHandle(mapping)
        return None
    return mapping, view


def _read_status(view) -> Answer | None:
    for attempt in range(50):
        if attempt:
            time.sleep(0.001)
        raw = ctypes.string_at(view, STATUS_SIZE)
        magic, layout, sequence, status, when, done, failed, count = struct.unpack_from('<IIIiqIII', raw)
        if magic != STATUS_MAGIC or layout != LAYOUT:
            return None
        if sequence % 2 or struct.unpack_from('<I', ctypes.string_at(view + 8, 4))[0] != sequence:
            continue
        sticks = []
        for i in range(min(count, 8)):
            m = raw[40 + i * 16:56 + i * 16]
            sticks.append(Stick(m[0], m[1], m[2] | m[3] << 8, m[4], m[6:16].split(b'\0')[0].decode('ascii', 'replace')))
        message = raw[168:360].decode('utf-16-le', 'replace').split('\0')[0]
        return Answer(status, when, done, failed, tuple(sticks), message, sequence)
    return None


def service_state(name: str = SERVICE) -> str:
    """'missing', or how it is: 'stopped', 'running', 'starting' and so on."""
    manager = _advapi.OpenSCManagerW(None, None, _SC_MANAGER_CONNECT)
    if not manager:
        return 'missing'
    try:
        service = _advapi.OpenServiceW(manager, name, _SERVICE_QUERY_STATUS)
        if not service:
            return 'missing'
        try:
            status = (wintypes.DWORD * 7)()
            if not _advapi.QueryServiceStatus(service, status):
                return 'unknown'
            return _STATES.get(status[1], 'unknown')
        finally:
            _advapi.CloseServiceHandle(service)
    finally:
        _advapi.CloseServiceHandle(manager)


def start(name: str = SERVICE) -> bool:
    """Start the service (signed-in users may); whether it is running or on its way."""
    manager = _advapi.OpenSCManagerW(None, None, _SC_MANAGER_CONNECT)
    if not manager:
        return False
    try:
        service = _advapi.OpenServiceW(manager, name, _SERVICE_START)
        if not service:
            return False
        try:
            return bool(_advapi.StartServiceW(service, 0, None)) or \
                ctypes.get_last_error() == _ERROR_SERVICE_ALREADY_RUNNING
        finally:
            _advapi.CloseServiceHandle(service)
    finally:
        _advapi.CloseServiceHandle(manager)


# --- installing it ----------------------------------------------------------------------------

def pawnio() -> bool:
    """Whether PawnIO is installed (FanControl and LibreHardwareMonitor install it)."""
    try:
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                       r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\PawnIO'))
        return True
    except OSError:
        return False


def dotnet() -> bool:
    """Whether Microsoft's .NET 10 runtime is installed, which the service runs on."""
    runtimes = Path(os.environ.get('ProgramFiles', r'C:\Program Files')) / 'dotnet' / 'shared' / 'Microsoft.NETCore.App'
    return runtimes.is_dir() and any(runtime.name.split('.')[0] == '10' for runtime in runtimes.glob('*'))


def bundled_folder() -> Path:
    """Where this Keyglow carries the service and its setup: beside Keyglow.exe - or, run from its
    source, in its last build."""
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent / 'lights'
    return Path(__file__).resolve().parents[2] / 'dist' / 'Keyglow' / 'lights'


def exe_version(path: Path) -> str:
    """An exe's file version, '1.0.0' ('' if it has none)."""
    version = ctypes.WinDLL('version')
    size = version.GetFileVersionInfoSizeW(str(path), None)
    if not size:
        return ''
    data = ctypes.create_string_buffer(size)
    if not version.GetFileVersionInfoW(str(path), 0, size, data):
        return ''
    pointer, length = ctypes.c_void_p(), wintypes.UINT()
    if not version.VerQueryValueW(data, '\\', ctypes.byref(pointer), ctypes.byref(length)):
        return ''
    ms, ls = struct.unpack_from('<II', ctypes.string_at(pointer.value + 8, 8))
    return f'{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}'


def outdated() -> bool:
    """Whether this Keyglow carries a newer service than the one installed."""
    if not INSTALLED.is_file():
        return False
    bundled = bundled_folder() / 'service' / 'KeyglowLights.exe'
    if not bundled.is_file():
        return False

    def key(v):
        return tuple(int(p) if p.isdigit() else 0 for p in v.split('.'))
    return key(exe_version(bundled)) > key(exe_version(INSTALLED))


class _ShellExecuteInfo(ctypes.Structure):
    _fields_ = [('cbSize', wintypes.DWORD), ('fMask', ctypes.c_ulong), ('hwnd', wintypes.HWND),
                ('lpVerb', wintypes.LPCWSTR), ('lpFile', wintypes.LPCWSTR), ('lpParameters', wintypes.LPCWSTR),
                ('lpDirectory', wintypes.LPCWSTR), ('nShow', ctypes.c_int), ('hInstApp', wintypes.HINSTANCE),
                ('lpIDList', ctypes.c_void_p), ('lpClass', wintypes.LPCWSTR), ('hkeyClass', wintypes.HKEY),
                ('dwHotKey', wintypes.DWORD), ('hIconOrMonitor', wintypes.HANDLE), ('hProcess', wintypes.HANDLE)]


def run_setup(action: str) -> str:
    """Install ('--install') or remove ('--uninstall') the service, through its setup run with
    administrator permission - Windows asks first. Waits for it; what went wrong, if anything."""
    setup = bundled_folder() / 'KeyglowLightsSetup.exe'
    if not setup.is_file():
        return 'This build of Keyglow does not include the Keyglow Lights service.'
    info = _ShellExecuteInfo()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = 0x00000040 | 0x00000100            # SEE_MASK_NOCLOSEPROCESS, SEE_MASK_NOASYNC
    info.lpVerb, info.lpFile, info.lpParameters = 'runas', str(setup), action
    info.lpDirectory, info.nShow = str(setup.parent), 0
    if not _shell.ShellExecuteExW(ctypes.byref(info)):
        return '' if ctypes.get_last_error() == _ERROR_CANCELLED else 'The service setup did not start.'
    if not info.hProcess:
        return 'The service setup did not start.'
    try:
        _kernel.WaitForSingleObject(info.hProcess, 0xFFFFFFFF)
        code = wintypes.DWORD()
        _kernel.GetExitCodeProcess(info.hProcess, ctypes.byref(code))
    finally:
        _kernel.CloseHandle(info.hProcess)
    return SETUP_ANSWERS.get(code.value, f'The service setup failed (code {code.value}).')


class FakeLights:
    """Keyglow Lights with two stand-in Corsair Vengeance RGB DDR5 sticks, for tests and the
    build's self-test: every request is taken, and kept in .asked."""

    def __init__(self, status: int = READY):
        self.status = status
        self.asked: list[Request] = []
        self.sticks = (Stick(0, 0x58, 0x0700, 10, '1.3.0'), Stick(0, 0x5A, 0x0700, 10, '1.3.0'))

    def answer(self) -> Answer:
        sticks = self.sticks if self.status == READY else ()
        return Answer(self.status, int(time.time() * 1000), len(self.asked), 0, sticks)

    def wake(self, wait: float = 0) -> Answer:
        return self.answer()

    def ask(self, request: Request, wait: float = 0) -> Answer:
        if self.status != READY:
            return self.answer()
        self.asked.append(request)
        return replace(self.answer(), took=True)

    def close(self) -> None:
        pass
