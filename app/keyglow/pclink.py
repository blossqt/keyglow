"""The PC's lights kept in step with the window, from a thread of their own: the motherboard's
controller is looked for and set at once (and told to keep it once changes stop for a moment), and
the memory is asked of Keyglow Lights, the newest wish first - its service may take a few seconds
to start."""

from __future__ import annotations

import ctypes
import threading
import time
from ctypes import wintypes

from PySide6.QtCore import QObject, Signal

from . import pc, polychrome, ram

LOOK_EVERY = 3.0        # s between looks for the board and at the memory's service
ICUE_EVERY = 5.0        # s between looks for iCUE
COMMIT_AFTER = 1.5      # s after the last change, the board keeps it across restarts


def icue_running() -> bool:
    """Whether Corsair's iCUE is running: it sets the memory's lights itself, over Keyglow's."""
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)

    class Entry(ctypes.Structure):
        _fields_ = [('dwSize', wintypes.DWORD), ('cntUsage', wintypes.DWORD), ('th32ProcessID', wintypes.DWORD),
                    ('th32DefaultHeapID', ctypes.c_void_p), ('th32ModuleID', wintypes.DWORD),
                    ('cntThreads', wintypes.DWORD), ('th32ParentProcessID', wintypes.DWORD),
                    ('pcPriClassBase', ctypes.c_long), ('dwFlags', wintypes.DWORD), ('szExeFile', ctypes.c_wchar * 260)]
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.Process32FirstW.argtypes = kernel.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    snapshot = kernel.CreateToolhelp32Snapshot(0x2, 0)          # TH32CS_SNAPPROCESS
    if not snapshot or snapshot == wintypes.HANDLE(-1).value:
        return False
    try:
        entry = Entry()
        entry.dwSize = ctypes.sizeof(Entry)
        more = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
        while more:
            if entry.szExeFile.lower() == 'icue.exe':
                return True
            more = kernel.Process32NextW(snapshot, ctypes.byref(entry))
        return False
    finally:
        kernel.CloseHandle(snapshot)


class PcLink(QObject):
    board = Signal(object)          # the board's zones (polychrome.Zone list), or None while none is found
    memory = Signal(object)         # Keyglow Lights' answer (ram.Answer)
    icue = Signal(bool)             # iCUE is running
    setup_done = Signal(str)        # an install or removal of Keyglow Lights ended: what went wrong, if anything

    def __init__(self, find_board=polychrome.find, lights=None, icue=icue_running):
        super().__init__()
        self._find_board = find_board
        self.lights = lights if lights is not None else ram.Lights()
        self._icue = icue
        self._wake = threading.Condition()
        self._wanted: dict = {}             # 'ram' / 'board' -> pc.Part, not yet sent
        self._setup: str | None = None
        self._running = False
        self._thread: threading.Thread | None = None
        self.device: polychrome.Board | None = None
        self.answer = ram.Answer(ram.STARTING)
        self.icue_running = False

    # --- from the window --------------------------------------------------------------------

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._run, name='keyglow-pc', daemon=True)
        self._thread.start()

    def stop(self) -> None:
        with self._wake:
            self._running = False
            self._wake.notify_all()
        if self._thread:
            self._thread.join(8)
        if self.device:
            try:
                if self._dirty_at is not None:
                    self.device.commit()
                self.device.close()
            except Exception:
                pass
            self.device = None
        self.lights.close()

    def want(self, part: str, lighting: pc.Part) -> None:
        """The lighting a part shows ('ram' or 'board'): it follows."""
        with self._wake:
            self._wanted[part] = lighting
            self._wake.notify_all()

    def setup(self, action: str) -> None:
        """Installs ('--install') or removes ('--uninstall') Keyglow Lights; Windows asks first."""
        with self._wake:
            self._setup = action
            self._wake.notify_all()

    # --- on the thread ----------------------------------------------------------------------

    _dirty_at: float | None = None

    def _run(self) -> None:
        sent: dict = {}             # what each part was last set to
        latest: dict = {}           # what the window last wanted of each part
        tried = None                # the memory's lighting last asked for, set or not
        looked = icued = -LOOK_EVERY
        first = True
        while True:
            with self._wake:
                if not self._running:
                    return
                if not self._wanted and self._setup is None:
                    self._wake.wait(0.25)
                wanted, self._wanted = self._wanted, {}
                setup, self._setup = self._setup, None
            now = time.monotonic()
            if setup:
                words = ram.run_setup(setup)
                self.setup_done.emit(words)
                looked, first = -LOOK_EVERY, True
            if now - icued > ICUE_EVERY:
                icued = now
                running = self._icue()
                if running != self.icue_running or first:
                    self.icue_running = running
                    self.icue.emit(running)
            if now - looked > LOOK_EVERY:
                looked = now
                ready_before = self.answer.status == ram.READY
                self._look(first)
                if self.answer.status == ram.READY and not ready_before:
                    tried = None                    # just installed or started: what was wanted goes now
                first = False
            latest.update(wanted)
            board = latest.get('board')
            if board is not None and self.device and sent.get('board') != board:
                try:
                    self.device.set(*pc.board_effect(board))
                    sent['board'] = board
                    self._dirty_at = time.monotonic()
                except Exception:
                    self._lose_board()
            memory = latest.get('ram')
            if memory is not None and sent.get('ram') != memory and memory != tried:
                tried = memory
                answer = self.lights.ask(pc.ram_request(memory))
                if answer.took:
                    sent['ram'] = memory
                self._tell(answer)
            if self._dirty_at is not None and time.monotonic() - self._dirty_at > COMMIT_AFTER and self.device:
                try:
                    self.device.commit()
                except Exception:
                    self._lose_board()
                self._dirty_at = None

    def _look(self, first: bool) -> None:
        if self.device is None:
            try:
                self.device = self._find_board()
            except Exception:
                self.device = None
            if self.device is not None or first:
                self.board.emit(list(self.device.zones) if self.device else None)
        # the first look starts the service, so the sticks it finds can be named; later ones only
        # read what it last said (it stops itself after a minute unasked, and that is fine)
        answer = self.lights.wake() if first else self.lights.answer()
        if answer.status == ram.NOT_RUNNING and self.answer.sticks:
            return                          # stopped by itself: what it found still stands
        self._tell(answer)

    def _tell(self, answer: ram.Answer) -> None:
        if (answer.status, answer.sticks, answer.message) != (self.answer.status, self.answer.sticks,
                                                              self.answer.message):
            self.memory.emit(answer)
        self.answer = answer

    def _lose_board(self) -> None:
        if self.device:
            try:
                self.device.close()
            except Exception:
                pass
        self.device = None
        self._dirty_at = None
        self.board.emit(None)
