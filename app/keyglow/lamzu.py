"""LAMZU mice on LAMZU Aurora's 64-byte protocol: the Maya X and its 8K dongle, the Maya X V2.

The protocol is as Device HUB documents and implements it (github.com/pity-zxcv/device-hub,
MIT or Apache-2.0, docs/PROTOCOL_NOTES.md section 5 and crates/devhub-hid/src/lamzu.rs),
with each model's limits from LAMZU's own table (lamzu.net/Config/env-models.json).

- Settings travel on the interface whose collection is FFFF:00 with a 64-byte feature report.
  A request is [0, 0, target, size, group, command, profile, values...]: target 2 is the mouse
  (through the dongle too), size a fixed number for each command (LAMZU's own, kept as found),
  profile 1-4.
- An answer is [status, 0, target, length, group, command, payload...] with the report id left
  off: status A1 is done, A2 or A3 refused. A read's command is the write's plus 0x80, and its
  payload starts with the profile asked about.
- A write takes effect at once and the mouse keeps it (its flash): nothing to save.
- Only the active profile is read or written. Device HUB found reading a profile never set up
  can upset the mouse's settings.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field, replace

from . import hid

OK, REFUSED = 0xA1, (0xA2, 0xA3)
MOUSE = 2


@dataclass(frozen=True)
class Model:
    name: str
    dpi_max: int
    polling: tuple[int, ...]            # Hz this connection offers
    lod: tuple[float, ...]              # mm
    sleep: tuple[int, ...]              # seconds
    wireless: bool
    hyper: bool = True                  # Competition Mode


_MAYA_X = dict(dpi_max=30000, lod=(0.7, 1.0, 2.0), sleep=(10, 30, 60, 300, 600, 1800))
_MAYA_X_V2 = dict(dpi_max=50000, lod=(0.7, 1.0, 1.3, 1.5, 1.7), sleep=(60, 300, 600, 900, 1200, 1500))
_WIRED_8K = (500, 1000, 2000, 4000, 8000)
_WIRELESS_8K = (1000, 2000, 4000, 8000)

MODELS: dict[tuple[int, int], Model] = {
    (0x373E, 0x001C): Model('LAMZU Maya X', polling=(125, 250, 500, 1000), wireless=False, **_MAYA_X),
    (0x373E, 0x001D): Model('LAMZU Maya X', polling=(125, 250, 500, 1000), wireless=True, **_MAYA_X),
    (0x373E, 0x001E): Model('LAMZU Maya X', polling=_WIRELESS_8K, wireless=True, **_MAYA_X),
    (0x37B0, 0x0044): Model('LAMZU Maya X V2', polling=_WIRED_8K, wireless=False, **_MAYA_X_V2),
    (0x37B0, 0x0048): Model('LAMZU Maya X V2', polling=_WIRELESS_8K, wireless=True, **_MAYA_X_V2),
}

# Polling rate codes, as LAMZU's own configurator writes them. 16 reads as 1000 Hz too.
_RATE_CODE = {125: 8, 250: 4, 500: 2, 1000: 1, 2000: 32, 4000: 64, 8000: 128}
_CODE_RATE = {code: hz for hz, code in _RATE_CODE.items()} | {16: 1000}

# (group, read command) of each on/off setting; the write command is the read's less 0x80.
SWITCHES = {
    'motion_sync': (1, 0x89),
    'angle_snap': (1, 0x84),
    'ripple': (1, 0x8A),
    'hyper': (1, 0x8B),
}
# Each command's size byte, LAMZU's own: (group, command without 0x80) -> size.
_SIZE = {(1, 0x00): 2, (1, 0x08): 2, (1, 0x02): 2, (1, 0x09): 2, (1, 0x04): 2, (1, 0x0A): 2, (1, 0x0B): 2,
         (1, 0x01): 26, (2, 0x01): 19, (0, 0x08): 2, (0, 0x07): 3, (0, 0x05): 1, (0, 0x03): 2}
_READ_SIZE = {(1, 0x81): 10, (0, 0x81): 16}     # reads that differ from their write's size
DEBOUNCE_MAX = 15


class MouseError(OSError):
    pass


@dataclass(frozen=True)
class Stage:
    dpi: int
    color: tuple[int, int, int] = (255, 255, 255)


@dataclass(frozen=True)
class Settings:
    """What the mouse holds for its active profile."""
    profile: int
    stages: tuple[Stage, ...]
    active: int                         # index into stages
    polling: int | None                 # Hz
    lod: float | None                   # mm
    debounce: int | None                # ms
    sleep: int | None                   # seconds
    switches: dict[str, bool] = field(default_factory=dict)

    def with_(self, **changes) -> Settings:
        return replace(self, **changes)


@dataclass(frozen=True)
class Battery:
    percent: int
    charging: bool


def lod_code(mm: float) -> int:
    """LAMZU's setLOD: under 1 mm is tenths | 0x80, 1.x mm is BCD 0x1x, whole millimetres as is."""
    tenths = round(mm * 10)
    if 1 <= tenths <= 9:
        return tenths | 0x80
    if tenths in (10, 20):
        return tenths // 10
    if 11 <= tenths <= 19:
        return 0x10 | (tenths % 10)
    raise ValueError(f'lift-off distance {mm} mm')


def lod_mm(code: int) -> float | None:
    if code >= 0x80:
        return (code - 0x80) / 10
    if 0x10 <= code <= 0x19:
        return 1 + (code & 0x0F) / 10
    if code == 3:
        return 0.7
    if code in (1, 2):
        return float(code)
    return None


class Link:
    """One mouse's settings channel: a request, then its own answer."""

    WAIT = 3.0              # a write through the dongle can take seconds (a polling change re-tunes the radio)
    STEP = 0.015
    RESEND_AT = (1.0, 2.0)

    def __init__(self, device):
        self.device = device
        self._lock = threading.Lock()

    def close(self) -> None:
        self.device.close()

    def ask(self, group: int, command: int, values: bytes = b'', target: int = MOUSE) -> bytes:
        """The answer's payload. Raises MouseError when refused, TimeoutError when none comes."""
        size = _READ_SIZE.get((group, command)) or _SIZE[(group, command & 0x7F)]
        request = bytes([0, 0, target, size, group, command]) + values
        with self._lock:
            self.device.set_feature(request)
            started = time.perf_counter()
            resent = 0
            while True:
                time.sleep(self.STEP)
                answer = self.device.get_feature()
                payload = self._answers(answer, target, group, command, values)
                if payload is not None:
                    status = answer[0]
                    if status != OK:
                        raise MouseError(f'request {group}/{command:#04x} refused ({status:#04x})')
                    return payload
                waited = time.perf_counter() - started
                if waited > self.WAIT:
                    raise TimeoutError(f'no answer to {group}/{command:#04x}')
                if resent < len(self.RESEND_AT) and waited > self.RESEND_AT[resent]:
                    resent += 1
                    self.device.set_feature(request)

    @staticmethod
    def _answers(answer: bytes, target: int, group: int, command: int, values: bytes) -> bytes | None:
        """The payload if this is the answer to that request, else None (an older answer still
        in the buffer)."""
        if len(answer) < 6 or answer[2] != target or answer[4] != group or answer[5] != command:
            return None
        if answer[0] not in (OK, *REFUSED):
            return None
        length = answer[3]
        if 6 + length > len(answer):
            return None
        payload = answer[6:6 + length]
        if answer[0] in REFUSED:
            return payload
        if command >= 0x80 and values and payload[:1] != values[:1]:
            return None                 # a read names the profile it was asked about
        return payload


class Mouse:
    """A LAMZU mouse: its settings, read and written for the active profile."""

    SETTLE = 0.3            # s after a DPI table or colours: the mouse is writing its flash

    def __init__(self, link: Link, model: Model):
        self.link = link
        self.model = model

    def close(self) -> None:
        self.link.close()

    # ------------------------------------------------------------------ reading

    def profile(self) -> int:
        payload = self.link.ask(0, 0x85)
        if not payload or not 1 <= payload[0] <= 4:
            raise MouseError(f'active profile unreadable: {payload.hex()}')
        return payload[0]

    def _get(self, group: int, command: int, profile: int, extra: bytes = b'') -> bytes:
        payload = self.link.ask(group, command, bytes([profile]) + extra)
        if len(payload) < 2:
            raise MouseError(f'short answer to {group}/{command:#04x}')
        return payload

    def battery(self) -> Battery | None:
        try:
            payload = self.link.ask(0, 0x83)
        except (MouseError, TimeoutError):
            return None
        if len(payload) < 2:
            return None
        return Battery(min(payload[1], 100), payload[0] == 1)

    def firmware(self) -> str:
        payload = self.link.ask(0, 0x81)
        return '.'.join(str(b) for b in payload[:4])

    def stages(self, profile: int) -> tuple[tuple[Stage, ...], int]:
        payload = self._get(1, 0x81, profile, bytes([6]))
        count = payload[1]
        if not 1 <= count <= 5 or len(payload) < 2 + 4 * count:
            raise MouseError(f'DPI table unreadable: {payload.hex()}')
        dpis = [int.from_bytes(payload[2 + 4 * i:4 + 4 * i], 'big') for i in range(count)]
        if not all(50 <= dpi <= self.model.dpi_max for dpi in dpis):
            raise MouseError(f'DPI out of range: {dpis}')
        try:
            colours = self._get(2, 0x81, profile)[1:]
        except (MouseError, TimeoutError):
            colours = b''
        stages = tuple(Stage(dpi, tuple(colours[3 * i:3 * i + 3]) if len(colours) >= 3 * i + 3 else (255, 255, 255))
                       for i, dpi in enumerate(dpis))
        active = self._get(1, 0x82, profile)[1]
        return stages, min(max(active, 1), count) - 1

    def read(self) -> Settings:
        profile = self.profile()
        stages, active = self.stages(profile)

        def value(group, command):
            try:
                return self._get(group, command, profile)[1]
            except (MouseError, TimeoutError):
                return None
        rate = value(1, 0x80)
        lod = value(1, 0x88)
        debounce = value(0, 0x88)
        try:
            sleep_payload = self._get(0, 0x87, profile)
            sleep = int.from_bytes(sleep_payload[1:3], 'big') if len(sleep_payload) >= 3 else None
        except (MouseError, TimeoutError):
            sleep = None
        switches = {}
        for name, (group, command) in SWITCHES.items():
            if name == 'hyper' and not self.model.hyper:
                continue
            got = value(group, command)
            if got is not None:
                switches[name] = got == 1
        return Settings(
            profile=profile, stages=stages, active=active,
            polling=_CODE_RATE.get(rate) if rate is not None else None,
            lod=lod_mm(lod) if lod is not None else None,
            debounce=debounce if debounce is not None and debounce <= 32 else None,
            sleep=sleep if sleep not in (None, 0, 0xFF00, 0xFFFF) else None,
            switches=switches)

    # ------------------------------------------------------------------ writing

    def _set(self, group: int, command: int, profile: int, values: bytes) -> None:
        self.link.ask(group, command, bytes([profile]) + values)

    def apply(self, old: Settings, new: Settings) -> None:
        """Writes what differs between old (as read) and new, to the profile old was read from."""
        self.check(new)
        profile = old.profile
        if [s.dpi for s in new.stages] != [s.dpi for s in old.stages]:
            dpis = b''.join(s.dpi.to_bytes(2, 'big') * 2 for s in new.stages)      # X and Y alike
            self._set(1, 0x01, profile, bytes([len(new.stages)]) + dpis)
            time.sleep(self.SETTLE)     # the mouse writes its flash: the next request can be missed
        if [s.color for s in new.stages] != [s.color for s in old.stages]:
            colours = b''.join(bytes(s.color) for s in new.stages).ljust(18, b'\0')
            self._set(2, 0x01, profile, colours)
            time.sleep(self.SETTLE)
        if new.active != old.active or len(new.stages) != len(old.stages):
            self._set(1, 0x02, profile, bytes([min(new.active, len(new.stages) - 1) + 1]))
        if new.polling != old.polling and new.polling is not None:
            self._set(1, 0x00, profile, bytes([_RATE_CODE[new.polling]]))
        if new.lod != old.lod and new.lod is not None:
            self._set(1, 0x08, profile, bytes([lod_code(new.lod)]))
        if new.debounce != old.debounce and new.debounce is not None:
            self._set(0, 0x08, profile, bytes([new.debounce]))
        if new.sleep != old.sleep and new.sleep is not None:
            self._set(0, 0x07, profile, new.sleep.to_bytes(2, 'big'))
        for name, on in new.switches.items():
            if old.switches.get(name) != on:
                group, command = SWITCHES[name]
                self._set(group, command - 0x80, profile, bytes([int(on)]))

    def check(self, settings: Settings) -> None:
        model = self.model
        if not 1 <= len(settings.stages) <= 5:
            raise ValueError('one to five DPI stages')
        if not all(50 <= s.dpi <= model.dpi_max for s in settings.stages):
            raise ValueError(f'DPI from 50 to {model.dpi_max}')
        if not 0 <= settings.active < len(settings.stages):
            raise ValueError('active stage')
        if settings.polling is not None and settings.polling not in model.polling:
            raise ValueError(f'polling rate {settings.polling} Hz')
        if settings.lod is not None and settings.lod not in model.lod:
            raise ValueError(f'lift-off distance {settings.lod} mm')
        if settings.sleep is not None and settings.sleep not in model.sleep:
            raise ValueError(f'sleep time {settings.sleep} s')
        if settings.debounce is not None and not 0 <= settings.debounce <= DEBOUNCE_MAX:
            raise ValueError('debounce time')


def find() -> list[tuple[hid.Interface, Model]]:
    """Every supported LAMZU mouse or dongle plugged in, by its settings interface."""
    found = []
    for (vid, pid), model in MODELS.items():
        for interface in hid.interfaces(vid, pid):
            if interface.usage_page == 0xFFFF and interface.usage == 0 and interface.report_feature >= 65:
                found.append((interface, model))
    return found


def open_first() -> Mouse | None:
    for interface, model in find():
        try:
            return Mouse(Link(hid.Device(interface)), model)
        except OSError:
            continue
    return None


class FakeDongle:
    """A stand-in for a Maya X's settings interface, answering as the real one does (the request
    echoed in its answer, a read's payload led by the profile), for tests and KEYGLOW_FAKE.
    asleep: the mouse is away from its dongle, and nothing new is answered."""

    def __init__(self):
        self.profile = 2
        self.dpis = [800, 1600]
        self.colours = [(208, 0, 103), (0, 165, 209)] + [(0, 0, 0)] * 4
        self.active = 2
        self.values = {(1, 0x00): 1, (1, 0x08): 2, (0, 0x08): 0, (1, 0x09): 0, (1, 0x04): 0, (1, 0x0A): 0,
                       (1, 0x0B): 0}
        self.sleep = 30
        self.battery = (0, 22)
        self.asleep = False
        self.closed = False
        self.requests: list[bytes] = []
        self._answer = bytes(64)

    def close(self) -> None:
        self.closed = True

    def set_feature(self, data: bytes) -> None:
        if self.closed:
            raise hid.HidError(1167, 'unplugged')
        request = bytes(data).ljust(64, b'\0')
        self.requests.append(request)
        if not self.asleep:
            self._answer = self._answer_to(request)

    def get_feature(self) -> bytes:
        if self.closed:
            raise hid.HidError(1167, 'unplugged')
        return self._answer

    def _answer_to(self, request: bytes) -> bytes:
        target, group, command = request[2], request[4], request[5]
        values = request[6:]
        profile = values[0]
        key = (group, command & 0x7F)
        status, payload = OK, b''
        if (group, command) == (0, 0x85):
            payload = bytes([self.profile])
        elif (group, command) == (0, 0x83):
            payload = bytes(self.battery)
        elif (group, command) == (0, 0x81):
            payload = bytes([0, 0, 0, 18])
        elif command >= 0x80 and profile != self.profile:
            status = 0xA3
        elif (group, command) == (1, 0x81):
            payload = bytes([profile, len(self.dpis)]) + b''.join(d.to_bytes(2, 'big') * 2 for d in self.dpis)
        elif (group, command) == (1, 0x01):
            count = values[1]
            self.dpis = [int.from_bytes(values[2 + 4 * i:4 + 4 * i], 'big') for i in range(count)]
        elif (group, command) == (2, 0x81):
            payload = bytes([profile]) + b''.join(bytes(c) for c in self.colours)
        elif (group, command) == (2, 0x01):
            self.colours = [tuple(values[1 + 3 * i:4 + 3 * i]) for i in range(6)]
        elif key == (1, 0x02):
            if command >= 0x80:
                payload = bytes([profile, self.active])
            else:
                self.active = values[1]
        elif key == (0, 0x07):
            if command >= 0x80:
                payload = bytes([profile]) + self.sleep.to_bytes(2, 'big')
            else:
                self.sleep = int.from_bytes(values[1:3], 'big')
        elif key in self.values:
            if command >= 0x80:
                payload = bytes([profile, self.values[key]])
            else:
                self.values[key] = values[1]
        else:
            status = 0xA3
        return (bytes([status, 0, target, len(payload), group, command]) + payload).ljust(64, b'\0')


def fake_mouse(dongle: FakeDongle | None = None) -> Mouse:
    mouse = Mouse(Link(dongle or FakeDongle()), MODELS[(0x373E, 0x001E)])
    mouse.SETTLE = 0
    return mouse
