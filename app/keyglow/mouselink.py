"""The mouse kept in step with the window, from a thread of its own: looked for every few seconds,
read once found, and written to as its page changes - the newest wish first."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal

from . import hid, lamzu

LOOK_EVERY = 3.0        # s between looks for a mouse, or at one that is not answering
BATTERY_EVERY = 60.0    # s between battery readings

ABSENT, ASLEEP, READY = 'absent', 'asleep', 'ready'


@dataclass(frozen=True)
class View:
    """What the Mouse page shows."""
    status: str
    name: str = ''
    wireless: bool = False
    settings: lamzu.Settings | None = None
    model: lamzu.Model | None = None
    battery: lamzu.Battery | None = None
    problem: str = ''


class MouseLink(QObject):
    changed = Signal(object)        # View

    def __init__(self, opener=lamzu.open_first):
        super().__init__()
        self._open = opener
        self._wake = threading.Condition()
        self._wanted: lamzu.Settings | None = None
        self._running = False
        self._thread: threading.Thread | None = None
        self.mouse: lamzu.Mouse | None = None
        self.view = View(ABSENT)

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._run, name='keyglow-mouse', daemon=True)
        self._thread.start()

    def stop(self) -> None:
        with self._wake:
            self._running = False
            self._wake.notify_all()
        if self._thread:
            self._thread.join(8)
        self._drop()

    def want(self, settings: lamzu.Settings) -> None:
        """The settings the mouse should hold: written once the last ones are."""
        with self._wake:
            self._wanted = settings
            self._wake.notify_all()

    # --- on the thread ----------------------------------------------------------------------

    def _run(self) -> None:
        looked = battery_at = -LOOK_EVERY
        first = True
        while True:
            with self._wake:
                if not self._running:
                    return
                if self._wanted is None:
                    self._wake.wait(0.25)
                wanted, self._wanted = self._wanted, None
            now = time.monotonic()
            if self.mouse is None or self.view.status != READY:
                if now - looked > LOOK_EVERY or first:
                    looked = now
                    self._look(first)
                    battery_at = now
                    first = False
                continue
            if wanted is not None:
                self._write(wanted)
            elif now - battery_at > BATTERY_EVERY:
                battery_at = now
                self._tell(battery=self.mouse.battery())

    def _look(self, first: bool) -> None:
        if self.mouse is None:
            try:
                self.mouse = self._open()
            except OSError:
                self.mouse = None
            if self.mouse is None:
                if first or self.view.status != ABSENT:
                    self._emit(View(ABSENT))
                return
        mouse = self.mouse
        try:
            settings = mouse.read()
            battery = mouse.battery() if mouse.model.wireless else None
        except TimeoutError:
            # The dongle is there and the mouse is not answering it: off, asleep or out of range.
            if self.view.status != ASLEEP:
                self._emit(View(ASLEEP, mouse.model.name, mouse.model.wireless, model=mouse.model))
            return
        except lamzu.MouseError as error:
            self._emit(View(READY, mouse.model.name, mouse.model.wireless, model=mouse.model,
                            problem=f'The mouse settings could not be read ({error}). Reconnect the mouse.'))
            self._drop()
            return
        except OSError:
            self._drop()
            self._emit(View(ABSENT))
            return
        self._emit(View(READY, mouse.model.name, mouse.model.wireless, settings, mouse.model, battery))

    def _write(self, wanted: lamzu.Settings) -> None:
        mouse, view = self.mouse, self.view
        try:
            mouse.apply(view.settings, wanted)
            self._emit(View(READY, view.name, view.wireless, wanted, view.model, view.battery))
        except ValueError as error:
            self._emit(View(READY, view.name, view.wireless, view.settings, view.model, view.battery,
                            problem=f'Setting not applied: {error}.'))
        except TimeoutError:
            self._emit(View(ASLEEP, view.name, view.wireless, model=view.model))
        except lamzu.MouseError as error:
            # Refused part-way: show what the mouse really holds now.
            try:
                now = mouse.read()
            except OSError:
                now = view.settings
            self._emit(View(READY, view.name, view.wireless, now, view.model, view.battery,
                            problem=f'The mouse did not accept the change ({error}).'))
        except OSError:
            self._drop()
            self._emit(View(ABSENT))

    def _tell(self, battery) -> None:
        view = self.view
        if battery is not None and battery != view.battery:
            self._emit(View(view.status, view.name, view.wireless, view.settings, view.model, battery, view.problem))

    def _emit(self, view: View) -> None:
        self.view = view
        self.changed.emit(view)

    def _drop(self) -> None:
        if self.mouse is not None:
            try:
                self.mouse.close()
            except (OSError, hid.HidError):
                pass
        self.mouse = None
