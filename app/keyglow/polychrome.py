"""The motherboard's lights: ASRock's Polychrome controller on USB (26CE:01A2), which drives the
board's own lights and its RGB and addressable RGB headers (fans, strips).

Its protocol is as OpenRGB documents it (ASRockPolychromeUSBController): 64-byte reports, each
answered. A zone is given an effect of the controller's own, one colour and a speed; the
controller runs it by itself, and keeps it across restarts once told to save (commit)."""

from __future__ import annotations

from dataclasses import dataclass

VID, PID = 0x26CE, 0x01A2

SET_ZONE, READ_ZONE, COMMIT, READ_HEADER = 0x10, 0x11, 0x12, 0x14
LED_COUNTS, RG_SWAP, PRESENT = 0x02, 0x03, 0x01
ABSENT_ZONE = 0x1E

ZONE_NAMES = ('RGB header 1', 'RGB header 2', 'Addressable header 1', 'Addressable header 2', 'Chipset',
              'I/O cover', 'Board', 'Addressable header 3')

# The controller's effects, by its numbers
OFF, STATIC, BREATHING, STROBE, SPECTRUM, RANDOM, MUSIC, WAVE, SPRING, STACK, CRAM, SCAN, NEON, WATER, RAINBOW = \
    range(15)


@dataclass(frozen=True)
class Zone:
    number: int
    leds: int
    swapped: bool           # takes red and green in the usual order (most take green first)

    @property
    def name(self) -> str:
        return ZONE_NAMES[self.number]


class Board:
    """The protocol, over anything that sends a report and gives back the answer (a HID device,
    or FakeBoard in tests)."""

    def __init__(self, link):
        self.link = link
        self.zones: list[Zone] = []
        self._read_zones()

    def close(self) -> None:
        close = getattr(self.link, 'close', None)
        if close:
            close()

    def _ask(self, *data: int) -> bytes:
        # an answer to a read has the zone or setting asked about at [3]: a late answer to an
        # earlier request is passed over
        return self.link.transact(bytes(data).ljust(64, b'\0'), data[2] if len(data) > 2 else None)

    def _read_zones(self) -> None:
        counts = self._ask(READ_HEADER, 0, LED_COUNTS)[4:12]
        swapped = self._ask(READ_HEADER, 0, RG_SWAP)[4]
        present = self._ask(READ_HEADER, 0, PRESENT)[4]
        self.zones = [Zone(z, counts[z], bool(swapped >> z & 1)) for z in range(8)
                      if counts[z] != ABSENT_ZONE and present >> z & 1]

    def _packet(self, zone: Zone, mode: int, rgb, speed: int) -> bytes:
        r, g, b = rgb
        first, second = (r, g) if zone.swapped else (g, r)
        data = bytearray(64)
        data[0], data[2], data[3] = SET_ZONE, zone.number, mode
        data[4], data[5], data[6], data[7], data[8] = first, second, b, speed, 0xFF
        return bytes(data)

    def set(self, mode: int, rgb, speed: int) -> None:
        """Every zone the effect, at once (not yet kept across restarts: commit). Each zone is read
        back and sent again if it didn't take: on this PC a write right after the controller was
        opened was once lost."""
        wanted = (mode, tuple(rgb), speed)
        for zone in self.zones:
            for attempt in range(3):
                self.link.transact(self._packet(zone, mode, rgb, speed))     # its answer names no zone
                mine = self.read(zone)
                if mine == wanted or (mode == OFF and mine[0] == OFF):
                    break

    def read(self, zone: Zone) -> tuple:
        """(mode, (r, g, b), speed) as the zone has it now."""
        answer = self._ask(READ_ZONE, 0, zone.number)
        first, second, b = answer[5:8]
        rgb = (first, second, b) if zone.swapped else (second, first, b)
        return answer[4], rgb, answer[8]

    def commit(self) -> None:
        """Keeps what each zone shows now across restarts."""
        self._ask(COMMIT)


class _HidLink:
    def __init__(self, device):
        self.device = device

    def transact(self, packet: bytes, about: int | None = None) -> bytes:
        self.device.flush()
        self.device.write(packet)
        answer = self.device.read()
        for _ in range(3):
            if about is None or len(answer) > 3 and answer[3] == about:
                break
            try:
                answer = self.device.read(250)
            except TimeoutError:
                break
        return answer

    def close(self) -> None:
        self.device.close()


def find() -> Board | None:
    """The board's controller, if it is there."""
    from . import hid
    found = hid.interfaces(VID, PID)
    if not found:
        return None
    return Board(_HidLink(hid.Device(found[0])))


class FakeBoard:
    """A Polychrome controller in Python, shaped like this PC's B850M Steel Legend: an RGB header,
    three addressable headers and the board's own lights."""

    def __init__(self, counts=(1, 1, 80, 80, 5, 7, 5, 80), present=0xCD, swapped=0xCD):
        self.counts, self.present, self.swapped = bytes(counts), present, swapped
        self.live = {z: (OFF, (0, 0, 0), 0) for z in range(8)}         # zone -> (mode, raw colour, speed)
        self.saved = dict(self.live)
        self.packets = 0
        self.commits = 0
        self.closed = False

    def transact(self, packet: bytes, about: int | None = None) -> bytes:
        assert len(packet) == 64
        self.packets += 1
        out = bytearray(64)
        out[0] = 0x13
        command = packet[0]
        out[3] = packet[2]
        if command == READ_HEADER:
            if packet[2] == LED_COUNTS:
                out[4:12] = self.counts
            elif packet[2] == RG_SWAP:
                out[4] = self.swapped
            elif packet[2] == PRESENT:
                out[4] = self.present
        elif command == SET_ZONE:
            self.live[packet[2]] = (packet[3], tuple(packet[4:7]), packet[7])
        elif command == READ_ZONE:
            mode, raw, speed = self.live[packet[2]]
            out[4], out[5:8], out[8] = mode, bytes(raw), speed
        elif command == COMMIT:
            self.saved = dict(self.live)
            self.commits += 1
        return bytes(out)

    def close(self) -> None:
        self.closed = True
