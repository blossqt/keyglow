"""The keyboard, kept in step with the window from a thread of its own: it finds the ALT, reads
its lighting, sends each change as it is made (only the bytes that changed), and has the keyboard
save once changes stop for a moment."""

from __future__ import annotations

import threading
import time

from PySide6.QtCore import QObject, Signal

from . import device
from . import state as st

LOOK_EVERY = 1.5        # s between looks for a keyboard while none is open
CHECK_EVERY = 2.0       # s between checks that an open keyboard is still there
SAVE_AFTER = 0.8        # s after the last change, the keyboard saves


class Link(QObject):
    status = Signal(str)        # device.ABSENT, STOCK or READY
    loaded = Signal(object)     # the keyboard's lighting (st.State), read as it was found
    failed = Signal(str)        # something went wrong, in words

    def __init__(self, look=device.look, opener=device.open_keyboard):
        super().__init__()
        self._look = look
        self._open = opener
        self._wake = threading.Condition()
        self._wanted: bytes | None = None
        self._jobs: list = []
        self._running = False
        self._paused = False
        self._thread: threading.Thread | None = None
        self.keyboard: device.Keyboard | None = None
        self.current = device.ABSENT
        self.outdated = False           # the keyboard found runs older Keyglow firmware than ours
        self.missing = False

    # --- from the window --------------------------------------------------------------------

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._run, name='keyglow-link', daemon=True)
        self._thread.start()

    def stop(self, save: bool = True) -> None:
        with self._wake:
            self._running = False
            self._wake.notify_all()
        if self._thread:
            self._thread.join(3)
        if self.keyboard and save:
            try:
                self.keyboard.save()
            except Exception:
                pass
        self._close()

    def want(self, state: st.State) -> None:
        """The lighting the window shows: the keyboard follows it."""
        with self._wake:
            self._wanted = state.pack()
            self._wake.notify_all()

    def do(self, name: str) -> None:
        """'defaults', 'reload' or 'bootloader', on the keyboard's thread."""
        with self._wake:
            self._jobs.append(name)
            self._wake.notify_all()

    def pause(self, paused: bool) -> None:
        """Lets go of the keyboard (while it is flashed), or looks for it again."""
        with self._wake:
            self._paused = paused
            self._wake.notify_all()

    # --- on the keyboard's thread -----------------------------------------------------------

    def _set(self, status: str) -> None:
        if status != self.current:
            self.current = status
            self.status.emit(status)

    def _close(self) -> None:
        if self.keyboard:
            try:
                self.keyboard.close()
            except Exception:
                pass
        self.keyboard = None

    def _find(self) -> None:
        found, interface = self._look()
        if found != device.READY:
            self._set(found)
            return
        try:
            keyboard = self._open(interface)
            lighting = keyboard.read_state()
        except Exception as error:      # unplugged as it was opened, or older firmware
            self.failed.emit(str(error))
            self._set(device.STOCK if isinstance(error, device.DeviceError) else device.ABSENT)
            return
        self.keyboard = keyboard
        self.outdated = keyboard.outdated
        self.missing = keyboard.size != st.STATE_SIZE     # its firmware has no Keyboard tab settings
        with self._wake:
            self._wanted = None         # the keyboard's own lighting wins over what the window had
        self._sent = lighting.pack()
        self.loaded.emit(lighting)
        self._set(device.READY)

    def _run(self) -> None:
        self._sent = b''
        dirty_at = None                 # when the newest change not yet saved went out
        checked = time.perf_counter()
        while True:
            with self._wake:
                if not self._running:
                    return
                if self._paused:
                    if self.keyboard:
                        self._close_saved(dirty_at)
                        dirty_at = None
                    self._wake.wait(0.5)
                    continue
                wait = LOOK_EVERY if self.keyboard is None else 0.25
                if not self._jobs and (self._wanted is None or self._wanted == self._sent):
                    self._wake.wait(wait)
                wanted, self._wanted = self._wanted, None
                jobs, self._jobs = self._jobs, []
            if self.keyboard is None:
                self._find()
                checked = time.perf_counter()
                continue
            try:
                for job in jobs:
                    self._job(job)
                    if job == 'bootloader':
                        self._close()
                        self._set(device.ABSENT)
                        break
                if self.keyboard is None:
                    continue
                if wanted is not None and wanted != self._sent:
                    self.keyboard.write_changes(self._sent, wanted)
                    self._sent = wanted
                    dirty_at = time.perf_counter()
                now = time.perf_counter()
                if dirty_at is not None and now - dirty_at > SAVE_AFTER:
                    self.keyboard.save()
                    dirty_at = None
                if now - checked > CHECK_EVERY:
                    checked = now
                    self.keyboard.hello()
            except Exception as error:
                self.failed.emit(str(error))
                self._close()
                self._set(device.ABSENT)

    def _job(self, job: str) -> None:
        if job == 'defaults':
            self.keyboard.defaults()
            self.keyboard.save()
            lighting = self.keyboard.read_state()
            self._sent = lighting.pack()
            self.loaded.emit(lighting)
        elif job == 'reload':
            self.keyboard.reload()
            lighting = self.keyboard.read_state()
            self._sent = lighting.pack()
            self.loaded.emit(lighting)
        elif job == 'bootloader':
            self.keyboard.save()
            self.keyboard.bootloader()

    def _close_saved(self, dirty_at) -> None:
        if dirty_at is not None:
            try:
                self.keyboard.save()
            except Exception:
                pass
        self._close()
        self._set(device.ABSENT)
